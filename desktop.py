"""Macアプリの設定画面。翻訳エンジンは別プロセスで開始・停止する。"""

import codecs
import json
import os
from pathlib import Path
import sys

from PyQt6 import QtCore, QtGui, QtWidgets

ROOT = Path(__file__).resolve().parent
EVENT_PREFIX = "MEETING_EVENT "
MODELS = (
    "pfnet/plamo-3-translate-0.8b-MLX-4bit",
    "mrjnzzz/Haas-ja-v1.0-mlx",
    "mlx-community/whisper-large-v3-turbo",
)


def download_models():
    # huggingface_hub は環境変数を import 時に読む。
    os.environ["HF_HUB_OFFLINE"] = "0"
    from huggingface_hub import snapshot_download

    for index, repo in enumerate(MODELS, 1):
        print(f"モデルを取得中（{index}/{len(MODELS)}）: {repo}", flush=True)
        snapshot_download(repo)
    print("モデルの準備が完了しました。", flush=True)


class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Meeting Translater")
        self.resize(570, 560)
        self.settings = QtCore.QSettings("meeting-translater", "desktop")
        self.process = QtCore.QProcess(self)
        self.process.setProcessChannelMode(QtCore.QProcess.ProcessChannelMode.MergedChannels)
        self.process.readyReadStandardOutput.connect(self.read_output)
        self.process.finished.connect(self.finished)
        self.process.errorOccurred.connect(self.process_error)
        self.mode = None
        self.stopping = False
        self.last_error = ""
        self.output_buffer = ""
        self.decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self.kill_timer = QtCore.QTimer(self, singleShot=True, interval=5000)
        self.kill_timer.timeout.connect(self.process.kill)

        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)
        title = QtWidgets.QLabel("Meeting Translater")
        title.setStyleSheet("font-size: 25px; font-weight: 600;")
        layout.addWidget(title)
        intro = QtWidgets.QLabel("会議の音声を、原文と翻訳の字幕で表示します。")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QtWidgets.QFormLayout()
        form.setSpacing(12)
        self.direction = QtWidgets.QComboBox()
        for label, value in (("自動判定（日本語 ⇄ 英語）", "auto"),
                             ("英語 → 日本語", "en-ja"), ("日本語 → 英語", "ja-en")):
            self.direction.addItem(label, value)
        index = self.direction.findData(self.settings.value("direction", "auto"))
        self.direction.setCurrentIndex(max(0, index))
        form.addRow("翻訳方向", self.direction)

        device_row = QtWidgets.QHBoxLayout()
        self.device = QtWidgets.QComboBox()
        self.device.setMinimumWidth(260)
        device_row.addWidget(self.device, 1)
        self.refresh = QtWidgets.QPushButton("更新")
        self.refresh.clicked.connect(self.refresh_devices)
        device_row.addWidget(self.refresh)
        form.addRow("音声入力", device_row)

        self.font_size = QtWidgets.QSpinBox()
        self.font_size.setRange(14, 64)
        self.font_size.setValue(int(self.settings.value("font_size", 26)))
        self.font_size.setSuffix(" px")
        form.addRow("字幕の文字サイズ", self.font_size)
        layout.addLayout(form)

        hint = QtWidgets.QLabel(
            "会議・動画の音声には「BlackHole 2ch」を選び、再生側の出力を\n"
            "スピーカー＋BlackHoleの「複数出力装置」に設定してください。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)

        buttons = QtWidgets.QHBoxLayout()
        self.start_button = QtWidgets.QPushButton("翻訳を開始")
        self.start_button.setMinimumHeight(40)
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.start_translation)
        buttons.addWidget(self.start_button, 1)
        self.stop_button = QtWidgets.QPushButton("停止")
        self.stop_button.setMinimumHeight(40)
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop)
        buttons.addWidget(self.stop_button)
        layout.addLayout(buttons)

        self.status = QtWidgets.QLabel("翻訳方向と音声入力を選んで「翻訳を開始」を押してください。")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("動作状況")
        layout.addWidget(self.status)

        setup_row = QtWidgets.QHBoxLayout()
        self.download_button = QtWidgets.QPushButton("初回準備・モデルを取得")
        self.download_button.clicked.connect(self.start_download)
        setup_row.addWidget(self.download_button)
        self.help_button = QtWidgets.QPushButton("使い方")
        self.help_button.clicked.connect(self.show_help)
        setup_row.addWidget(self.help_button)
        setup_row.addStretch()
        layout.addLayout(setup_row)
        note = QtWidgets.QLabel("モデル取得時のみインターネットに接続します（初回は約3.6GB）。")
        note.setWordWrap(True)
        note.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(note)

        self.details = QtWidgets.QGroupBox("動作ログ")
        log_layout = QtWidgets.QVBoxLayout(self.details)
        self.log = QtWidgets.QPlainTextEdit(readOnly=True)
        self.log.setMaximumBlockCount(500)
        self.log.setMinimumHeight(110)
        log_layout.addWidget(self.log)
        layout.addWidget(self.details, 1)
        self.refresh_devices()

    def refresh_devices(self):
        saved = self.device.currentData() or self.settings.value("device", "")
        self.device.clear()
        self.device.addItem("Macの既定のマイク", "")
        try:
            import sounddevice as sd

            # Core Audio のデバイス一覧を再取得する（接続変更にも対応）。
            sd._terminate()
            sd._initialize()
            for info in sd.query_devices():
                if info["max_input_channels"] > 0:
                    self.device.addItem(info["name"], info["name"])
        except Exception as error:
            self.log.appendPlainText(f"音声入力を取得できませんでした: {error}")
        index = self.device.findData(saved)
        self.device.setCurrentIndex(max(0, index))

    def save_settings(self):
        self.settings.setValue("direction", self.direction.currentData())
        self.settings.setValue("device", self.device.currentData())
        self.settings.setValue("font_size", self.font_size.value())
        self.settings.sync()

    def launch(self, mode, arguments):
        if self.mode is not None:
            return
        self.save_settings()
        self.mode, self.stopping, self.last_error, self.output_buffer = mode, False, "", ""
        self.decoder.reset()
        self.log.clear()
        self.set_running(True)
        env = QtCore.QProcessEnvironment.systemEnvironment()
        env.insert("HF_HUB_OFFLINE", "0" if mode == "download" else "1")
        env.insert("PYTHONUNBUFFERED", "1")
        env.insert("MEETING_TRANSLATER_EVENTS", "1")
        self.process.setProcessEnvironment(env)
        self.process.setWorkingDirectory(str(ROOT))
        self.process.start(sys.executable, arguments)

    def start_translation(self):
        self.status.setText("モデルを読み込んでいます…")
        arguments = [str(ROOT / "translater.py"), "--direction", self.direction.currentData(),
                     "--font-size", str(self.font_size.value())]
        if self.device.currentData():
            arguments += ["--device", self.device.currentData()]
        self.launch("translation", arguments)

    def start_download(self):
        self.status.setText("モデルを取得しています。初回は数分かかる場合があります…")
        self.launch("download", [str(Path(__file__).resolve()), "--download-models"])

    def set_running(self, running):
        for control in (self.start_button, self.download_button, self.direction,
                        self.device, self.refresh, self.font_size):
            control.setEnabled(not running)
        self.stop_button.setEnabled(running)

    def read_output(self):
        self.output_buffer += self.decoder.decode(bytes(self.process.readAllStandardOutput()))
        lines = self.output_buffer.split("\n")
        self.output_buffer = lines.pop()
        for line in lines:
            if line.startswith(EVENT_PREFIX):
                try:
                    self.handle_event(json.loads(line[len(EVENT_PREFIX):]))
                except (ValueError, KeyError):
                    self.log.appendPlainText(line)
            else:
                self.log.appendPlainText(line.rstrip())
                if self.mode == "download" and line.startswith("モデル"):
                    self.status.setText(line)

    def handle_event(self, event):
        kind = event["event"]
        if kind == "loading":
            self.status.setText(event["message"])
        elif kind == "ready":
            self.status.setText(f"翻訳中：{event['device']}。字幕ウィンドウに表示します。")
        elif kind == "error":
            self.last_error = event["message"]
            self.log.appendPlainText(self.last_error)

    def stop(self):
        if self.mode is None:
            return
        self.stopping = True
        self.status.setText("停止しています…")
        self.stop_button.setEnabled(False)
        # SIGINT で字幕の位置を保存。ダウンロード側も中断できる。
        import signal

        if self.process.processId():
            try:
                os.kill(self.process.processId(), signal.SIGINT)
            except ProcessLookupError:
                pass  # 終了通知を処理する直前に停止が押された場合。
        self.kill_timer.start()

    def finished(self, code, _status):
        self.kill_timer.stop()
        self.read_output()
        if self.output_buffer:
            self.log.appendPlainText(self.output_buffer)
        mode, self.mode = self.mode, None
        self.set_running(False)
        if self.stopping:
            self.status.setText("停止しました。設定を変更して再開できます。")
        elif code == 0:
            self.status.setText("モデルの準備が完了しました。「翻訳を開始」を押してください。"
                                if mode == "download" else "翻訳を終了しました。")
        else:
            self.status.setText(self.last_error or "起動できませんでした。動作ログを確認してください。")
            if mode == "translation":
                self.log.appendPlainText(
                    "モデルが未取得の場合は「初回準備・モデルを取得」を押してください。\n"
                    "マイクの権限は「システム設定 → プライバシーとセキュリティ → マイク」で確認できます。")

    def process_error(self, error):
        if error == QtCore.QProcess.ProcessError.FailedToStart:
            self.mode = None
            self.set_running(False)
            self.status.setText("処理を起動できませんでした。")
            self.log.appendPlainText(self.process.errorString())

    def show_help(self):
        QtWidgets.QMessageBox.information(
            self, "使い方",
            "1. 初回は「初回準備・モデルを取得」でモデルを用意します。\n"
            "2. 翻訳方向と音声入力を選び、「翻訳を開始」を押します。\n"
            "3. 終えるときは「停止」を押します。\n\n"
            "会議の相手の声：入力にBlackHole 2chを選び、会議アプリの\n"
            "出力先をスピーカー＋BlackHoleの複数出力装置に設定してください。\n\n"
            "字幕はドラッグで移動、右下でサイズ変更できます。\n"
            "右クリックで翻訳方向の切替、スクロールで履歴を確認できます。\n"
            "音声はクラウドへ送信しません。")

    def closeEvent(self, event):
        self.save_settings()
        if self.process.state() != QtCore.QProcess.ProcessState.NotRunning:
            self.stop()
            if not self.process.waitForFinished(2000):
                self.process.kill()
                self.process.waitForFinished(1000)
        event.accept()


def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName("Meeting Translater")
    app.setApplicationDisplayName("Meeting Translater")
    bundle = os.environ.get("MEETING_TRANSLATER_APP_BUNDLE")
    if bundle:
        app.setWindowIcon(QtGui.QIcon(str(Path(bundle) / "Contents/Resources/AppIcon.icns")))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    if "--download-models" in sys.argv:
        download_models()
    else:
        sys.exit(main())
