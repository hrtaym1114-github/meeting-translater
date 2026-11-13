"""VAD 分割・設定・書き出しの自己チェック（モデル不要・数秒）: uv run python test_translater.py"""

import tempfile
from pathlib import Path

import numpy as np

import translater
from translater import SR, Segmenter, export_text, load_audio

# 設定: 既定値 < 設定ファイル < コマンドライン。保存は追記。一時的なオプションは既定値にしない
with tempfile.TemporaryDirectory() as d:
    translater.SETTINGS = Path(d) / "sub" / "settings.json"
    assert translater.parse_args([]).font_size == 26, "設定ファイルが無ければ既定値"
    translater.save_settings(font_size=30, direction="en-ja", file="a.wav", device=None)
    translater.save_settings(opacity=0.5)
    a = translater.parse_args(["--direction", "auto"])
    assert (a.font_size, a.opacity, a.direction, a.file, a.device) == (30, 0.5, "auto", None, None), vars(a)

assert export_text([("10:00:00", "こんにちは", "Hello")]) == "[10:00:00] こんにちは\n           Hello\n\n"


def events(audio, **kw):
    seg = Segmenter(**kw)
    out = []
    for i in range(0, len(audio), SR // 10):  # 実運用と同じ 0.1 秒刻みで投入
        out += seg.feed(audio[i:i + SR // 10])
    out += seg.feed(np.zeros(SR, np.float32))
    if (rest := seg.flush()) is not None:
        out.append(rest)
    return out


def finals(evs):
    return [a for a, final in evs if final]


for name in ("ja", "en"):
    audio = load_audio(f"samples/{name}.wav")
    evs = events(audio)
    segs = finals(evs)
    print(name, [round(len(s) / SR, 2) for s in segs], "partials:", sum(not f for _, f in evs))
    assert len(segs) == 3, f"{name}: 3文 → 3区間のはず（{len(segs)}）"

    # 途中経過: 確定前に出て、確定版の先頭部分と一致する（同じ発話の音声が伸びていくだけ）
    pending = []
    for a, final in evs:
        if final:
            assert pending, "4秒前後の発話なら確定前に途中経過が出るはず"
            assert all(np.array_equal(a[:len(p)], p) for p in pending), "途中経過が確定版の先頭と一致しない"
            pending = []
        else:
            pending.append(a)
    assert not any(not f for _, f in events(audio, partial_sec=0)), "partial_sec=0 で途中経過が出た"

    capped = finals(events(audio, max_sec=1.0))
    assert len(capped) > 3, "max_sec で強制分割されるはず"
    assert max(len(s) for s in capped) <= SR * 1.0 + 512, "区間長が max_sec を超えている"
    # VAD の判定は同じなので、強制分割しても音声は1サンプルも欠けない
    assert sum(map(len, capped)) == sum(map(len, segs))

assert events(np.zeros(SR * 3, np.float32)) == [], "無音から区間が出てはいけない"
print("OK")
