"""リアルタイム文字起こし＋翻訳のフローティング字幕（ローカル完結 / Apple Silicon）。

  uv run translater.py                          # 既定マイク, ja→en
  uv run translater.py --device BlackHole       # システム音声（BlackHole 経由）
  uv run translater.py --direction en-ja
  uv run translater.py --file samples/ja.wav --no-ui
  uv run translater.py --list-devices

構成: 音声 → [VADスレッド] silero-vad で発話区間 → [MLXスレッド] STT → PLaMo 翻訳 → 字幕UI
MLX はスレッドを跨ぐとストリームエラーになるため、モデルのロードと推論はすべて MLX スレッドで行う。
"""

import argparse
import collections
import html
import json
import logging
import os
import queue
import resource
import signal
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

import numpy as np

# ローカル完結: キャッシュ済みモデルだけを使い HF へ問い合わせない。初回のみ HF_HUB_OFFLINE=0 で取得する
os.environ.setdefault("HF_HUB_OFFLINE", "1")
warnings.filterwarnings("ignore", category=FutureWarning)  # torch.jit.load の非推奨警告（silero-vad 内部）

SR = 16000
VAD_CHUNK = 512  # silero-vad は 16kHz で 512 サンプル固定
DIRS = {"ja-en": ("ja", "en"), "en-ja": ("en", "ja"), "auto": (None, None)}
DIR_LABELS = {"ja-en": "日本語 → 英語", "en-ja": "英語 → 日本語", "auto": "自動検出（ja⇄en）"}

log = logging.getLogger("translater")


def report_event(event, **fields):
    """アプリ版の親プロセスへ状態を通知。通常のCLI実行では出力しない。"""
    if os.environ.get("MEETING_TRANSLATER_EVENTS") == "1":
        print("MEETING_EVENT " + json.dumps({"event": event, **fields}, ensure_ascii=False), flush=True)


# ---------- STT（差し替えはここに1クラス足して STT に登録） ----------

class HaasSTT:
    """Haas-ja-v1.0（日本語専用）。haas-mlx で Metal 実行。"""

    def __init__(self):
        import sentencepiece as spm
        from haas_mlx.model import HaasModel
        from huggingface_hub import snapshot_download

        d = Path(snapshot_download("mrjnzzz/Haas-ja-v1.0-mlx"))
        self.model = HaasModel.load(d)
        self.sp = spm.SentencePieceProcessor(model_file=str(d / "tokenizer.model"))

    def __call__(self, audio, lang):
        import mlx.core as mx
        from haas_mlx.longform import transcribe_text

        return transcribe_text(self.model, mx.array(audio), self.sp).strip(), "ja"


class WhisperSTT:
    """mlx-whisper（多言語。lang=None で自動検出）。"""

    def __init__(self, repo):
        import mlx_whisper

        self.transcribe, self.repo = mlx_whisper.transcribe, repo

    def __call__(self, audio, lang):
        r = self.transcribe(audio, path_or_hf_repo=self.repo, language=lang,
                            condition_on_previous_text=False, verbose=None)
        return r["text"].strip(), r["language"]


STT = {"haas": lambda args: HaasSTT(), "whisper": lambda args: WhisperSTT(args.whisper_model)}


# ---------- 翻訳 ----------

class Translator:
    """PLaMo 3 Translate。直近 history 文の原文/訳文ペアを文脈として渡す。"""

    def __init__(self, repo, history):
        from mlx_lm import generate, load
        from mlx_lm.sample_utils import make_sampler

        self.model, self.tok = load(repo, trust_remote_code=True,
                                    tokenizer_config={"trust_remote_code": True})
        self.tok.add_eos_token("<|plamo:tag|>")
        self.generate, self.sampler = generate, make_sampler(temp=0)
        self.history = collections.deque(maxlen=history)
        self.pair = None

    def __call__(self, text, src, tgt, commit=True):
        """commit=False（途中経過）は文脈履歴に残さない。"""
        if (src, tgt) != self.pair:  # 方向が変わったら文脈を捨てる（テンプレートは全ペア同一方向が前提）
            self.history.clear()
            self.pair = (src, tgt)
        msgs = [m for s, t in self.history
                for m in ({"role": "user", "content": s}, {"role": "assistant", "content": t})]
        msgs.append({"role": "user", "content": text})
        kw = {"source_lang": src} if src else {}  # 省略時は PLaMo が原文の言語を自動判定
        prompt = self.tok.apply_chat_template(msgs, target_lang=tgt, add_generation_prompt=True,
                                              tokenize=False, **kw)
        out = self.generate(self.model, self.tok, prompt=prompt, max_tokens=512, sampler=self.sampler)
        out = out.split("<|plamo:")[0].strip()
        if commit:
            self.history.append((text, out))
        return out


# ---------- VAD ----------

class Segmenter:
    """silero-vad で発話区間を切り出す。無音 silence_ms で確定、max_sec を超えたら強制分割。

    feed() は (音声, 確定か) のリストを返す。発話中は partial_sec ごとに途中経過（ここまでの音声）も返す。
    """

    def __init__(self, silence_ms=500, max_sec=15.0, partial_sec=1.0):
        import torch
        from silero_vad import VADIterator, load_silero_vad

        torch.set_num_threads(1)
        self.torch = torch
        self.vad = VADIterator(load_silero_vad(), sampling_rate=SR,
                               min_silence_duration_ms=silence_ms, speech_pad_ms=100)
        self.max_chunks = int(max_sec * SR / VAD_CHUNK)
        self.partial_chunks = int(partial_sec * SR / VAD_CHUNK)  # 0 で途中経過なし
        self.pre = collections.deque(maxlen=10)  # 検出直前 ~320ms も含める（語頭欠け防止）
        self.buf = None  # 発話中のチャンク列
        self.rest = np.zeros(0, np.float32)

    def feed(self, audio):
        out = []
        self.rest = np.concatenate([self.rest, audio])
        n = len(self.rest) // VAD_CHUNK * VAD_CHUNK
        for i in range(0, n, VAD_CHUNK):
            c = self.rest[i:i + VAD_CHUNK]
            ev = self.vad(self.torch.from_numpy(c)) or {}
            if self.buf is None:
                self.pre.append(c)
                if "start" in ev:
                    self.buf = list(self.pre)
                continue
            self.buf.append(c)
            if "end" in ev:
                out.append((np.concatenate(self.buf), True))
                self.buf = None
                self.pre.clear()
            elif len(self.buf) >= self.max_chunks:
                # ponytail: 長い連続発話は語の途中でも切る。精度が問題なら直近の小休止で切る
                out.append((np.concatenate(self.buf), True))
                self.buf = []
            elif self.partial_chunks and len(self.buf) % self.partial_chunks == 0:
                out.append((np.concatenate(self.buf), False))
        self.rest = self.rest[n:]
        return out

    def flush(self):
        buf, self.buf = self.buf, None
        return (np.concatenate(buf), True) if buf else None


# ---------- パイプライン ----------

def load_audio(path):
    """任意の音声/動画ファイルを 16kHz mono float32 で読む（ffmpeg）。"""
    raw = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(path),
                          "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32)


def capture(args, audio_q, ready):
    """音声を 0.1 秒ずつ audio_q へ。ファイル指定時は実時間で再生して模擬する。"""
    ready.wait()
    if args.file:
        audio = load_audio(args.file)
        log.info("ファイル再生: %s（%.1f 秒）", args.file, len(audio) / SR)
        report_event("ready", device=Path(args.file).name)
        for i in range(0, len(audio), SR // 10):
            audio_q.put(audio[i:i + SR // 10])
            time.sleep(0.1)
        audio_q.put(np.zeros(SR, np.float32))  # 末尾の無音で最後の発話を確定させる
        audio_q.put(None)
        return
    import sounddevice as sd

    dev = int(args.device) if args.device and args.device.isdigit() else args.device
    info = sd.query_devices(dev, "input")
    with sd.InputStream(samplerate=SR, channels=min(2, info["max_input_channels"]), dtype="float32",
                        device=dev, blocksize=SR // 10,
                        callback=lambda d, *_: audio_q.put(d.mean(axis=1))):
        log.info("録音開始: %s", info["name"])
        report_event("ready", device=info["name"])
        threading.Event().wait()


def vad_loop(args, audio_q, seg_q):
    seg = Segmenter(args.silence_ms, args.max_sec, args.partial_sec)
    while (a := audio_q.get()) is not None:
        for s, final in seg.feed(a):
            seg_q.put((s, time.monotonic(), final))
    if (r := seg.flush()) is not None:
        seg_q.put((r[0], time.monotonic(), True))
    seg_q.put(None)


def worker(args, state, seg_q, res_q, ready):
    import mlx.core as mx

    stts = {}

    def stt_for(src):
        name = args.stt or ("haas" if src == "ja" else "whisper")
        if name not in stts:
            report_event("loading", message="音声認識モデルを読み込んでいます…")
            t = time.monotonic()
            stts[name] = STT[name](args)
            stts[name](np.zeros(SR, np.float32), src)  # ウォームアップ（初回の kernel コンパイル）
            log.info("STT 準備完了: %s（%.1f 秒）", name, time.monotonic() - t)
        return stts[name]

    try:
        report_event("loading", message="翻訳モデルを読み込んでいます…")
        t = time.monotonic()
        mt = Translator(args.mt_model, args.history)
        mt("テスト", "ja", "en")
        mt.history.clear()
        log.info("翻訳 準備完了: %s（%.1f 秒）", args.mt_model, time.monotonic() - t)
        stt_for(DIRS[state["dir"]][0])
    except Exception:
        log.exception("モデルの読み込みに失敗。初回は `HF_HUB_OFFLINE=0 uv run translater.py` でダウンロードしてください")
        report_event("error", message="モデルを読み込めませんでした。初回準備でモデルを取得してください。")
        os._exit(1)  # UI を待機表示のまま残さない
    ready.set()

    def process(audio, t_end, final):
        """STT → 翻訳して res_q へ (原文, 訳文, 確定か)。確定は空でも送る（UI の途中表示を消すため）。"""
        try:
            src, tgt = DIRS[state["dir"]]
            t0 = time.monotonic()
            text, lang = stt_for(src)(audio, src)
            t1 = time.monotonic()
            out = ""
            if text:
                tgt = tgt or ("en" if lang == "ja" else "ja")
                out = mt(text, src, tgt, commit=final)
            t2 = time.monotonic()
        except Exception:
            log.exception("区間の処理に失敗（スキップして継続）")
            text = out = ""
        if text or final:
            res_q.put((text, out, final))
        if not text:
            return
        if final:
            log.info("[%s→%s] %s\n    => %s\n    音声 %.1fs | STT %.2fs | 翻訳 %.2fs | 発話終了→表示 %.2fs | MLX peak %.2fGB",
                     lang, tgt, text, out, len(audio) / SR, t1 - t0, t2 - t1,
                     t2 - t_end + args.silence_ms / 1000, mx.get_peak_memory() / 1e9)
        else:
            log.debug("途中 %.1fs: %s => %s（STT %.2fs 翻訳 %.2fs）", len(audio) / SR, text, out, t1 - t0, t2 - t1)

    stop = False
    while not stop and (item := seg_q.get()) is not None:
        items = [item]
        while not seg_q.empty():
            nxt = seg_q.get_nowait()
            if nxt is None:
                stop = True
                break
            items.append(nxt)
        # バックプレッシャー: 溜まった確定区間は1つに結合して1回で処理（取りこぼさず遅れを回収）。
        # 途中経過は最新の1つだけ処理し、古いものや確定済みの発話のものは捨てる
        finals = [i for i in items if i[2]]
        if len(finals) > 1:
            log.warning("処理が追いつかず %d 区間を結合", len(finals))
        if finals:
            process(np.concatenate([f[0] for f in finals]), finals[0][1], True)
        if not items[-1][2]:
            process(*items[-1])
    res_q.put(None)


# ---------- UI ----------

def run_ui(args, state, res_q, ready):
    from PyQt6 import QtCore, QtGui, QtWidgets

    Qt = QtCore.Qt

    class Overlay(QtWidgets.QWidget):
        def __init__(self):
            super().__init__(None, Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
            self.setWindowTitle("meeting-translater")
            # 履歴はホイールで遡れる。最下部にいる時だけ新しい字幕に追従する（遡り中は動かない）
            self.text = QtWidgets.QTextBrowser()
            self.text.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)  # 右クリックは独自メニューへ
            self.text.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(20, 14, 6, 6)
            lay.addWidget(self.text, 1)
            lay.addWidget(QtWidgets.QSizeGrip(self), 0,
                          Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
            # 文字の上でもドラッグで移動（ホイールはスクロールへ通す）
            self.drag = None
            for w in (self, self.text.viewport()):
                w.installEventFilter(self)
            self.settings = QtCore.QSettings("meeting-translater", "overlay")  # 位置とサイズを次回も復元
            if not self.restoreGeometry(self.settings.value("geometry", QtCore.QByteArray())):
                geo = QtGui.QGuiApplication.primaryScreen().availableGeometry()
                w, h = min(1000, geo.width() - 40), 60 + args.lines * args.font_size * 3
                self.setGeometry(geo.x() + (geo.width() - w) // 2, geo.bottom() - h - 40, w, h)
            self.count = 0  # 確定した発話数
            self.live = None  # 途中表示の先頭位置（QTextCursor）
            self.was_ready = False
            self.status()
            QtCore.QTimer(self, interval=100, timeout=self.poll).start()

        def poll(self):
            if ready.is_set() and not self.was_ready:
                self.was_ready = True
                self.status()
            while True:
                try:
                    item = res_q.get_nowait()
                except queue.Empty:
                    return
                if item is not None:
                    self.show_item(*item)

        def show_item(self, s, t, final):
            """末尾に字幕を出す。途中経過は薄い色で、次の途中経過か確定版でその場で差し替える。"""
            sb = self.text.verticalScrollBar()
            follow = sb.value() >= sb.maximum() - 4
            doc = self.text.document()
            cur = QtGui.QTextCursor(doc)
            cur.movePosition(QtGui.QTextCursor.MoveOperation.End)
            if self.live is not None:  # 前回の途中表示を消して同じ場所に書き直す
                cur.setPosition(self.live.position(), QtGui.QTextCursor.MoveMode.KeepAnchor)
                cur.removeSelectedText()
                self.live = None
                if not s:  # 確定したら無音/雑音だった: 途中表示ごと消す
                    cur.deletePreviousChar()  # 途中表示用に足した改行
            elif not s:
                return
            elif self.count == 0:
                self.text.clear()  # 待機メッセージを消す
                cur = QtGui.QTextCursor(doc)
            else:
                cur.insertBlock()
            if s:
                fs = args.font_size
                c1, c2 = ("#bbb", "#fff") if final else ("#777", "#aaa")
                start = cur.position()
                cur.insertHtml(
                    f"<p style='margin:0;color:{c1};font-size:{fs * 0.7:.0f}px'>{html.escape(s)}</p>"
                    f"<p style='margin:0 0 6px 0;color:{c2};font-size:{fs}px'>{html.escape(t)}</p>")
                if final:
                    self.count += 1
                    self.trim()
                else:  # 挿入後に作る（挿入位置にあるカーソルは挿入分だけ後ろへずれるため）
                    self.live = QtGui.QTextCursor(doc)
                    self.live.setPosition(start)
            if self.count == 0 and self.live is None:
                self.status()
            if follow:
                sb.setValue(sb.maximum())

        def trim(self):
            """古い発話から捨てる（1発話=2ブロック、最大 500 発話）。途中表示が無い時だけ呼ぶ。"""
            doc = self.text.document()
            while doc.blockCount() > 1000:
                c = QtGui.QTextCursor(doc.firstBlock())
                c.movePosition(QtGui.QTextCursor.MoveOperation.NextBlock, QtGui.QTextCursor.MoveMode.KeepAnchor)
                c.removeSelectedText()

        def status(self):
            if self.count or self.live is not None:
                return
            msg = (f"待機中 — {DIR_LABELS[state['dir']]}（右クリックで設定 / ドラッグで移動 / ホイールで履歴）"
                   if ready.is_set() else "モデル読み込み中…")
            self.text.setHtml(f"<p style='color:#aaa;font-size:{args.font_size * 0.7:.0f}px'>{msg}</p>")

        def clear(self):
            self.count = 0
            self.live = None
            self.status()

        def eventFilter(self, obj, e):
            t = e.type()
            if t == QtCore.QEvent.Type.MouseButtonPress and e.button() == Qt.MouseButton.LeftButton:
                # OS 標準のウィンドウ移動（滑らか）。使えない環境だけ自前で move する
                if not self.windowHandle().startSystemMove():
                    self.drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
                return True
            if t == QtCore.QEvent.Type.MouseMove and self.drag is not None:
                self.move(e.globalPosition().toPoint() - self.drag)
                return True
            if t == QtCore.QEvent.Type.MouseButtonRelease:
                self.drag = None
            return False

        def paintEvent(self, e):
            p = QtGui.QPainter(self)
            p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QtGui.QColor(0, 0, 0, int(255 * args.opacity)))
            p.drawRoundedRect(QtCore.QRectF(self.rect()), 14, 14)

        def contextMenuEvent(self, e):
            m = QtWidgets.QMenu(self)
            for d, label in DIR_LABELS.items():
                a = m.addAction(label)
                a.setCheckable(True)
                a.setChecked(d == state["dir"])
                a.triggered.connect(lambda _, d=d: (state.update(dir=d), self.status()))
            m.addSeparator()
            m.addAction("字幕をクリア", self.clear)
            m.addAction("終了", QtWidgets.QApplication.quit)
            m.exec(e.globalPos())

    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Meeting Translater")
    app.setApplicationDisplayName("Meeting Translater — 字幕")
    bundle = os.environ.get("MEETING_TRANSLATER_APP_BUNDLE")
    if bundle:
        app.setWindowIcon(QtGui.QIcon(str(Path(bundle) / "Contents/Resources/AppIcon.icns")))
    # Ctrl+C でも位置を保存して終了（poll タイマーが Python に制御を戻すのでハンドラが動く）
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    ov = Overlay()
    app.aboutToQuit.connect(lambda: ov.settings.setValue("geometry", ov.saveGeometry()))
    ov.show()
    app.exec()


# ---------- main ----------

def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--device", help="入力デバイス名の一部 or 番号（例: BlackHole）。省略で既定マイク")
    p.add_argument("--file", help="マイクの代わりに音声/動画ファイルを実時間で流す（検証用）")
    p.add_argument("--direction", choices=DIRS, default="ja-en")
    p.add_argument("--stt", choices=STT, help="省略時: 原文が日本語なら haas、それ以外は whisper")
    p.add_argument("--whisper-model", default="mlx-community/whisper-large-v3-turbo")
    p.add_argument("--mt-model", default="pfnet/plamo-3-translate-0.8b-MLX-4bit",
                   help="例: pfnet/plamo-3-translate-2b-MLX-4bit")
    p.add_argument("--history", type=int, default=3, help="翻訳時に文脈として渡す直近の文数")
    p.add_argument("--silence-ms", type=int, default=500, help="この長さの無音で発話を確定")
    p.add_argument("--max-sec", type=float, default=15.0, help="連続発話をこの秒数で強制分割")
    p.add_argument("--partial-sec", type=float, default=1.0, help="発話中の途中表示の間隔（0 で無効）")
    p.add_argument("--no-ui", action="store_true", help="字幕ウィンドウを出さずログのみ")
    p.add_argument("--font-size", type=int, default=26)
    p.add_argument("--lines", type=int, default=3, help="字幕ウィンドウの初期の高さ（発話数）")
    p.add_argument("--opacity", type=float, default=0.8, help="字幕背景の不透明度 0〜1")
    p.add_argument("--list-devices", action="store_true")
    args = p.parse_args()

    if args.list_devices:
        import sounddevice as sd

        print(sd.query_devices())
        return
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    def thread_error(args):
        log.error("音声処理を停止しました", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        report_event("error", message=f"音声処理を開始・継続できませんでした: {args.exc_value}")
        os._exit(1)

    threading.excepthook = thread_error

    state = {"dir": args.direction}
    audio_q, seg_q, res_q = queue.Queue(), queue.Queue(), queue.Queue()
    ready = threading.Event()
    threading.Thread(target=capture, args=(args, audio_q, ready), daemon=True).start()
    threading.Thread(target=vad_loop, args=(args, audio_q, seg_q), daemon=True).start()
    w = threading.Thread(target=worker, args=(args, state, seg_q, res_q, ready), daemon=True)
    w.start()
    try:
        if args.no_ui:
            w.join()
        else:
            run_ui(args, state, res_q, ready)
    except KeyboardInterrupt:
        pass
    # macOS の ru_maxrss はバイト単位
    log.info("プロセス最大RSS: %.2fGB", resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e9)


if __name__ == "__main__":
    main()
