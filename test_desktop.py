"""GUIと子プロセス間のライフサイクルを検証（モデル・録音不要）。"""

import json
import tempfile
import time
import unittest
from pathlib import Path

from PyQt6 import QtCore, QtTest, QtWidgets

from desktop import MainWindow


class DesktopLifecycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.window = MainWindow()
        self.window.settings = QtCore.QSettings(
            str(Path(self.directory.name) / "settings.ini"), QtCore.QSettings.Format.IniFormat)

    def tearDown(self):
        self.window.close()
        self.window.deleteLater()
        self.app.processEvents()
        self.directory.cleanup()

    def wait_for(self, predicate, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.processEvents()
            if predicate():
                return
            QtTest.QTest.qWait(10)
        self.fail(f"タイムアウト: {self.window.status.text()}\n{self.window.log.toPlainText()}")

    def test_start_ready_stop_and_restart(self):
        # 日本語のマルチバイト文字を途中で分けて書き出し、通知の破損も検出。
        data = ("MEETING_EVENT " + json.dumps(
            {"event": "ready", "device": "テスト入力"}, ensure_ascii=False) + "\n").encode()
        split = data.index("テ".encode()) + 1
        script = ("import os, time\n"
                  f"os.write(1, {data[:split]!r})\n"
                  "time.sleep(0.1)\n"
                  f"os.write(1, {data[split:]!r})\n"
                  "time.sleep(60)\n")
        for _ in range(2):
            self.window.launch("translation", ["-c", script])
            self.wait_for(lambda: "翻訳中：テスト入力" in self.window.status.text())
            self.assertFalse(self.window.start_button.isEnabled())
            self.assertTrue(self.window.stop_button.isEnabled())
            self.window.stop()
            self.wait_for(lambda: self.window.mode is None)
            self.assertIn("停止しました", self.window.status.text())
            self.assertTrue(self.window.start_button.isEnabled())

    def test_failure_is_visible_and_can_retry(self):
        event = "MEETING_EVENT " + json.dumps({"event": "error", "message": "入力デバイスがありません"})
        self.window.launch("translation", ["-c", f"print({event!r}, flush=True); raise SystemExit(1)"])
        self.wait_for(lambda: self.window.mode is None)
        self.assertIn("入力デバイスがありません", self.window.status.text())
        self.assertTrue(self.window.download_button.isEnabled())
        self.window.launch("download", ["-c", "print('モデルの準備が完了しました。')"])
        self.wait_for(lambda: self.window.mode is None)
        self.assertIn("モデルの準備が完了", self.window.status.text())
        self.assertEqual(self.window.last_error, "")

    def test_closing_stops_child(self):
        self.window.launch("translation", ["-c", "import time; time.sleep(60)"])
        self.wait_for(lambda: self.window.process.processId() > 0)
        self.window.close()
        self.assertEqual(self.window.process.state(), QtCore.QProcess.ProcessState.NotRunning)


if __name__ == "__main__":
    unittest.main()
