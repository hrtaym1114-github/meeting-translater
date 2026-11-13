import AppKit
import Darwin

// Finder からターミナルなしでローカルの Python 環境へ引き継ぐ。
let bundle = Bundle.main
func fail(_ message: String) -> Never {
    let app = NSApplication.shared
    app.setActivationPolicy(.regular)
    app.activate(ignoringOtherApps: true)
    let alert = NSAlert()
    alert.messageText = "Meeting Translater を起動できません"
    alert.informativeText = message
    alert.alertStyle = .warning
    alert.runModal()
    exit(1)
}

guard let root = bundle.object(forInfoDictionaryKey: "MeetingTranslaterProjectPath") as? String else {
    fail("プロジェクトの場所が見つかりません。アプリを再作成してください。")
}
let python = root + "/.venv/bin/python"
let script = root + "/desktop.py"
guard FileManager.default.isExecutableFile(atPath: python),
      FileManager.default.fileExists(atPath: script) else {
    fail("プロジェクトまたは実行環境が見つかりません。\n" + root +
         "\n\nプロジェクトを移動した場合は、元の場所に戻すかアプリを再作成してください。")
}
setenv("MEETING_TRANSLATER_APP_BUNDLE", bundle.bundlePath, 1)
setenv("PYTHONUNBUFFERED", "1", 1)
let oldPath = ProcessInfo.processInfo.environment["PATH"] ?? "/usr/bin:/bin"
setenv("PATH", "/opt/homebrew/bin:/usr/local/bin:" + oldPath, 1)
chdir(root)
let logDirectory = FileManager.default.homeDirectoryForCurrentUser
    .appendingPathComponent("Library/Logs/Meeting Translater")
try? FileManager.default.createDirectory(at: logDirectory, withIntermediateDirectories: true)
let logFD = open(logDirectory.appendingPathComponent("app.log").path, O_WRONLY | O_CREAT | O_APPEND, 0o600)
if logFD >= 0 {
    dup2(logFD, STDOUT_FILENO)
    dup2(logFD, STDERR_FILENO)
    close(logFD)
}
let arguments = [python, script]
let argv = arguments.map { strdup($0) } + [nil]
_ = argv.withUnsafeBufferPointer { buffer in
    execv(python, buffer.baseAddress!)
}
fail("Pythonの起動に失敗しました。\n" + String(cString: strerror(errno)))
