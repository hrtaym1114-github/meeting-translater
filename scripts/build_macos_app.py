"""このMac用の .app を作成・インストールする（外部配布用ではない）。"""

import argparse
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def create_icon(target):
    from PyQt6 import QtCore, QtGui

    app = QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])
    with tempfile.TemporaryDirectory() as directory:
        iconset = Path(directory) / "AppIcon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                pixels = size * scale
                image = QtGui.QImage(pixels, pixels, QtGui.QImage.Format.Format_ARGB32_Premultiplied)
                image.fill(QtCore.Qt.GlobalColor.transparent)
                painter = QtGui.QPainter(image)
                painter.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
                painter.scale(pixels / 1024, pixels / 1024)
                gradient = QtGui.QLinearGradient(0, 0, 1024, 1024)
                gradient.setColorAt(0, QtGui.QColor("#2257bd"))
                gradient.setColorAt(1, QtGui.QColor("#149ba4"))
                painter.setPen(QtCore.Qt.PenStyle.NoPen)
                painter.setBrush(gradient)
                painter.drawRoundedRect(QtCore.QRectF(40, 40, 944, 944), 220, 220)
                painter.setBrush(QtGui.QColor("#ffffff"))
                painter.drawRoundedRect(QtCore.QRectF(185, 250, 654, 460), 100, 100)
                path = QtGui.QPainterPath()
                path.moveTo(290, 690)
                path.lineTo(290, 800)
                path.lineTo(420, 690)
                painter.drawPath(path)
                pen = QtGui.QPen(QtGui.QColor("#247caa"), 38)
                pen.setCapStyle(QtCore.Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                for x, height in ((330, 80), (420, 170), (510, 250), (600, 170), (690, 80)):
                    painter.drawLine(QtCore.QPointF(x, 480 - height / 2),
                                     QtCore.QPointF(x, 480 + height / 2))
                painter.end()
                suffix = "@2x" if scale == 2 else ""
                image.save(str(iconset / f"icon_{size}x{size}{suffix}.png"))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(target)], check=True)
    del app


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true", help="~/Applications にインストール")
    args = parser.parse_args()
    if sys.platform != "darwin":
        parser.error("macOSで実行してください")
    if not (ROOT / ".venv/bin/python").exists():
        parser.error("先に uv sync を実行してください")
    destination = ROOT / "dist/Meeting Translater.app"
    # ビルド成功後にのみ既存のアプリを置き換える。
    destination.parent.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination.parent) as temporary:
        app = Path(temporary) / destination.name
        contents = app / "Contents"
        (contents / "MacOS").mkdir(parents=True)
        (contents / "Resources").mkdir()
        info = {
            "CFBundleName": "Meeting Translater",
            "CFBundleDisplayName": "Meeting Translater",
            "CFBundleIdentifier": "local.meeting-translater.desktop",
            "CFBundleExecutable": "MeetingTranslater",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "0.1.0",
            "CFBundleVersion": "1",
            "CFBundleIconFile": "AppIcon",
            "LSMinimumSystemVersion": "14.0",
            "NSHighResolutionCapable": True,
            "NSMicrophoneUsageDescription": "音声を文字起こし・翻訳して字幕を表示するためにマイクを使用します。音声はクラウドに送信しません。",
            "MeetingTranslaterProjectPath": str(ROOT),
        }
        with (contents / "Info.plist").open("wb") as stream:
            plistlib.dump(info, stream)
        create_icon(contents / "Resources/AppIcon.icns")
        subprocess.run(["swiftc", str(ROOT / "macos/Launcher.swift"), "-O", "-o",
                        str(contents / "MacOS/MeetingTranslater")], check=True)
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], check=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(app), destination)
    print(f"作成: {destination}")
    if args.install:
        installed = Path.home() / "Applications" / destination.name
        installed.parent.mkdir(exist_ok=True)
        if installed.exists():
            # 別のアプリを誤って上書きしない。
            with (installed / "Contents/Info.plist").open("rb") as stream:
                old_info = plistlib.load(stream)
            if old_info.get("CFBundleIdentifier") != "local.meeting-translater.desktop":
                raise RuntimeError(f"同名の別アプリが存在します: {installed}")
            shutil.rmtree(installed)
        shutil.copytree(destination, installed)
        print(f"インストール: {installed}")


if __name__ == "__main__":
    main()
