// App-core tests: process handling, engine JSON mapping, the run-loop
// supervisor, and the private log, without AppKit, windows, Reminders, or
// network. Run with macos/Tests/run-app-core-tests.sh.

import Foundation

var failures = 0
var checks = 0

func check(_ condition: @autoclosure () -> Bool, _ message: String, line: UInt = #line) {
    checks += 1
    if !condition() {
        failures += 1
        print("FAIL line \(line): \(message)")
    }
}

func section(_ name: String) {
    print("== \(name)")
}

func output(_ stdout: String, exit: Int32 = 0, cancelled: Bool = false, timedOut: Bool = false) -> ProcessOutput {
    ProcessOutput(exitCode: exit, killedBySignal: false, stdout: Data(stdout.utf8), stderr: Data(),
                  timedOut: timedOut, cancelled: cancelled)
}

func run(_ executable: String, _ arguments: [String], input: Data? = nil, timeout: TimeInterval? = nil,
         grace: TimeInterval = ChildProcess.defaultTerminationGracePeriod, cancelAfter: TimeInterval? = nil) async -> (ProcessOutput, TimeInterval) {
    let started = Date()
    let child = ChildProcess(executable: URL(fileURLWithPath: executable), arguments: arguments,
                             environment: ProcessInfo.processInfo.environment, terminationGracePeriod: grace)
    if let cancelAfter {
        DispatchQueue.global().asyncAfter(deadline: .now() + cancelAfter) { child.cancel() }
    }
    let result: ProcessOutput = await withCheckedContinuation { continuation in
        do {
            try child.start(input: input, timeout: timeout) { continuation.resume(returning: $0) }
        } catch {
            continuation.resume(returning: output("", exit: -99))
        }
    }
    return (result, Date().timeIntervalSince(started))
}

let arguments = CommandLine.arguments
guard arguments.count == 3 else {
    print("usage: app-core-tests REPO_ROOT WORK_DIR")
    exit(2)
}
let repoRoot = URL(fileURLWithPath: arguments[1])
let work = URL(fileURLWithPath: arguments[2])
let fileManager = FileManager.default

// MARK: - Engine JSON mapping

section("Engine output mapping")
do {
    if case .success = EngineClient.interpret(output("{\"ok\": true, \"x\": 1}")) {} else { check(false, "ok:true succeeds") }
    if case .failure(let error) = EngineClient.interpret(output("{\"ok\": false, \"error\": {\"code\": \"config_invalid\", \"message\": \"bad\"}}", exit: 7)) {
        check(error.code == EngineErrorCode.configInvalid && error.message == "bad", "engine error code and message are kept")
    } else { check(false, "ok:false fails") }
    if case .failure(let error) = EngineClient.interpret(output("", exit: 3)) {
        check(error.code == EngineErrorCode.authRequired && !error.message.isEmpty, "exit 3 without JSON maps to auth_required")
    } else { check(false, "exit 3 fails") }
    if case .failure(let error) = EngineClient.interpret(output("not json")) {
        check(error.code == EngineErrorCode.invalidOutput, "garbage on exit 0 is invalid_output")
    } else { check(false, "garbage fails") }
    if case .failure(let error) = EngineClient.interpret(output("", cancelled: true)) {
        check(error.isCancellation, "cancelled output maps to cancelled")
    } else { check(false, "cancelled fails") }
    if case .failure(let error) = EngineClient.interpret(output("", exit: 15, timedOut: true)) {
        check(error.code == EngineErrorCode.timeout, "timed-out output maps to timeout")
    } else { check(false, "timeout fails") }
    check(EngineClient.jsonObject(in: Data("progress\n{\"ok\": true}\n".utf8)) == Data("{\"ok\": true}".utf8), "stray lines before the JSON object are skipped")
    for (status, code) in [(4, "account_binding_required"), (5, "approval_required"), (6, "reminders_unavailable"), (8, "oauth_client_missing"), (9, "network"), (10, "plan_changed"), (1, "failed")] {
        check(EngineErrorCode.forExitStatus(Int32(status)) == code, "exit \(status) maps to \(code)")
    }

    let event = EngineEvent.parse(line: "@@LTB {\"event\": \"approval_requested\", \"destructive_fingerprint\": \"ab\", \"destructive_count\": 7}")
    check(event?.event == "approval_requested" && event?.destructiveCount == 7, "event lines parse")
    check(EngineEvent.parse(line: "Starting sync loop") == nil, "other lines are not events")

    let plan = try JSONDecoder().decode(SyncPlan.self, from: Data("{\"total_count\": 6, \"counts\": {\"google_tasks.create\": 2, \"apple_reminders.create\": 1, \"google_tasks.update\": 2, \"apple_reminders.update\": 1}}".utf8))
    let summary = PlanSummary(plan: plan)
    check(summary.addToGoogle == 2 && summary.addOnMac == 1 && summary.updates == 3 && summary.deletions == 0, "plan counts are summarized")
    check(summary.lines == ["Add 2 tasks to Google Tasks", "Add 1 reminder on this Mac", "Update 3 items"], "plan summary lines: \(summary.lines)")

    check(ProxyChoice(configValue: "").mode == .system && ProxyChoice(configValue: "none").mode == .direct, "proxy modes parse")
    check(ProxyChoice(configValue: "http://127.0.0.1:7890").isValid, "http proxy with port is valid")
    check(!ProxyChoice(configValue: "127.0.0.1:7890").isValid && !ProxyChoice(configValue: "http://proxy").isValid, "proxy without scheme or port is invalid")
    var config = BridgeConfig()
    config.syncIntervalSeconds = 60
    check(SyncOptions(config: config, sharedClient: true).intervalSeconds == 300, "shared sign-in proposes 5 minutes")
    check(SyncOptions(config: config, sharedClient: false).intervalSeconds == 60, "own client keeps 1 minute")
    check(EngineDate.string(from: Date(timeIntervalSince1970: 0)) == "1970-01-01T00:00:00+00:00", "timestamps use +00:00")
    check(String(decoding: JSONValue.encodeObject(["n": .int(60), "r": .double(0.25), "l": .strings(["A"])]), as: UTF8.self) == "{\"l\":[\"A\"],\"n\":60,\"r\":0.25}", "merge payload encodes integers as integers")
} catch {
    check(false, "mapping tests threw \(error)")
}

// MARK: - Child processes

section("Child processes")
do {
    let (collected, _) = await run("/bin/sh", ["-c", "echo out; echo err >&2; exit 3"])
    check(collected.exitCode == 3 && String(decoding: collected.stdout, as: UTF8.self) == "out\n" && String(decoding: collected.stderr, as: UTF8.self) == "err\n", "stdout, stderr, and exit status are collected")

    let (echoed, _) = await run("/bin/cat", [], input: Data("hello".utf8))
    check(String(decoding: echoed.stdout, as: UTF8.self) == "hello", "stdin input reaches the child")

    let (timed, timedTook) = await run("/bin/sleep", ["30"], timeout: 0.5)
    check(timed.timedOut && timedTook < 5, "a timeout stops the child (took \(timedTook) s)")

    let (cancelled, cancelTook) = await run("/bin/sleep", ["30"], cancelAfter: 0.3)
    check(cancelled.cancelled && cancelTook < 5, "cancel sends SIGTERM (took \(cancelTook) s)")

    let (stubborn, stubbornTook) = await run("/bin/sh", ["-c", "trap '' TERM; while :; do sleep 0.1; done"], grace: 1, cancelAfter: 0.3)
    check(stubborn.killedBySignal && stubbornTook < 6, "a child ignoring SIGTERM is killed after the grace period (took \(stubbornTook) s)")

    final class Lines: @unchecked Sendable {
        let lock = NSLock()
        var values: [String] = []
        func add(_ line: String) { lock.lock(); values.append(line); lock.unlock() }
    }
    let lines = Lines()
    let streaming = ChildProcess(executable: URL(fileURLWithPath: "/usr/bin/printf"), arguments: ["a\\nb\\npartial"],
                                 environment: [:], lineHandler: { _, line in lines.add(line) })
    _ = await withCheckedContinuation { (continuation: CheckedContinuation<ProcessOutput, Never>) in
        try? streaming.start(input: nil, timeout: 5) { continuation.resume(returning: $0) }
    }
    check(lines.values == ["a", "b", "partial"], "line mode splits lines and flushes the last one: \(lines.values)")
}

// MARK: - Python discovery

section("Python discovery")
do {
    let bundle = work.appendingPathComponent("Fake.app")
    let embedded = bundle.appendingPathComponent("Contents/Resources/python/bin")
    try fileManager.createDirectory(at: embedded, withIntermediateDirectories: true)
    let fakePython = embedded.appendingPathComponent("python3")
    try "#!/bin/sh\nexit 0\n".write(to: fakePython, atomically: true, encoding: .utf8)
    chmod(fakePython.path, 0o755)
    let tooOld = work.appendingPathComponent("python-too-old")
    try "#!/bin/sh\nexit 1\n".write(to: tooOld, atomically: true, encoding: .utf8)
    chmod(tooOld.path, 0o755)

    check(PythonLocator.findPython(bundle: bundle, environment: ["PATH": "/usr/bin:/bin"]) == fakePython, "the embedded Python comes before system ones")
    check(PythonLocator.findPython(bundle: bundle, environment: ["LTB_PYTHON": "/usr/bin/true", "PATH": "/usr/bin:/bin"])?.path == "/usr/bin/true", "LTB_PYTHON comes first")
    check(PythonLocator.findPython(bundle: bundle, environment: ["LTB_PYTHON": tooOld.path, "PATH": "/usr/bin:/bin"]) == fakePython, "an unusable LTB_PYTHON is skipped")
    if case .engineMissing = PythonLocator.locate(bundle: bundle) {} else { check(false, "a bundle without the engine is reported") }
} catch {
    check(false, "python discovery tests threw \(error)")
}

// MARK: - Engine commands

section("Engine commands (temporary HOME, no launchctl)")
do {
    guard let python = PythonLocator.findPython(bundle: work.appendingPathComponent("NoSuch.app"), environment: ProcessInfo.processInfo.environment) else {
        throw NSError(domain: "tests", code: 1, userInfo: [NSLocalizedDescriptionKey: "no Python 3.9+"])
    }
    let configDirectory = work.appendingPathComponent("config/local-tasks-bridge")
    let paths = AppPaths(configDirectory: configDirectory, configFile: configDirectory.appendingPathComponent("config.json"),
                         logDirectory: work.appendingPathComponent("logs"))
    let runtime = EngineRuntime(python: python, engine: repoRoot.appendingPathComponent("engine/local_tasks_bridge.py"),
                                bundle: work.appendingPathComponent("Fake.app"))
    let client = EngineClient(runtime: runtime, paths: paths, log: AppLog(url: paths.appLog))

    let version = try await client.version()
    check(version.version?.isEmpty == false, "version --json decodes")
    let status = try await client.status()
    check(status.setupCompleted == false && status.condition == "setup_required", "fresh status needs setup")
    check(status.headline == "Setup is not complete.", "LTB_LANG=en gives English headlines: \(status.headline ?? "nil")")
    try await client.configInit()
    let merged = try await client.configMerge(["include_lists": .strings(["Work"]), "sync_interval_seconds": .int(300), "max_destructive_ratio": .double(0.3)])
    check(merged.includeLists == ["Work"] && merged.syncIntervalSeconds == 300 && merged.maxDestructiveRatio == 0.3, "config merge round-trips")
    let shown = try await client.configShow()
    check(shown.includeLists == ["Work"], "config show reads the merge back")
    do {
        try await client.configMerge(["sync_interval_seconds": .int(30)])
        check(false, "an interval under 60 s is rejected")
    } catch let error as EngineError {
        check(error.code == EngineErrorCode.configInvalid && error.exitCode == 7 && !error.message.isEmpty, "config_invalid arrives with its message")
    }
    let before = try await client.clientStatus()
    check(before.customReady == false, "no own client yet")

    let webClient = work.appendingPathComponent("web-client.json")
    try "{\"web\": {\"client_id\": \"1-x.apps.googleusercontent.com\"}}".write(to: webClient, atomically: true, encoding: .utf8)
    do {
        _ = try await client.importClient(at: webClient)
        check(false, "a Web client is rejected")
    } catch let error as EngineError {
        check(error.code == EngineErrorCode.oauthClientMissing && error.message.contains("Desktop app"), "Web client rejection explains Desktop app: \(error.message)")
    }
    let desktopClient = work.appendingPathComponent("desktop-client.json")
    try "{\"installed\": {\"client_id\": \"1234567890-abc.apps.googleusercontent.com\", \"client_secret\": \"s\"}}".write(to: desktopClient, atomically: true, encoding: .utf8)
    let imported = try await client.importClient(at: desktopClient)
    check(imported.clientIdHint?.isEmpty == false, "a Desktop client imports with a hint")
    let after = try await client.clientStatus()
    check(after.active == "custom", "the imported client becomes active")

    try await client.pause()
    let paused = try await client.status()
    check(paused.paused == true, "pause shows in status")
    try await client.resume()
    let resumed = try await client.status()
    check(resumed.paused == false, "resume shows in status")
    try await client.syncNow()

    let doctor = try await client.doctor()
    check((try? JSONSerialization.jsonObject(with: doctor) as? [String: Any])?["checks"] != nil, "doctor --json has checks")
} catch {
    check(false, "engine command tests threw \(error)")
}

// MARK: - Supervisor

section("Run-loop supervisor")
do {
    let logURL = work.appendingPathComponent("supervisor-logs/app.log")
    let log = AppLog(url: logURL)
    let paths = AppPaths(configDirectory: work.appendingPathComponent("sv"), configFile: work.appendingPathComponent("sv/config.json"),
                         logDirectory: work.appendingPathComponent("supervisor-logs"))
    let python = PythonLocator.findPython(bundle: work.appendingPathComponent("NoSuch.app"), environment: ProcessInfo.processInfo.environment)
        ?? URL(fileURLWithPath: "/usr/bin/python3")
    let runtime = EngineRuntime(python: python,
                                engine: repoRoot.appendingPathComponent("macos/Tests/AppCore/fake_engine.py"),
                                bundle: work.appendingPathComponent("Fake.app"))
    let client = EngineClient(runtime: runtime, paths: paths, log: log)

    setenv("FAKE_LOOP_SCENARIO", "crash", 1)
    let supervisor = EngineSupervisor(log: log)
    var events: [String] = []
    supervisor.onEvent = { events.append($0.event) }
    supervisor.start(with: client)
    try await Task.sleep(nanoseconds: 7_500_000_000)
    let started = events.filter { $0 == "loop_started" }.count
    check(events.starts(with: ["loop_started", "cycle_started", "notification", "cycle_finished"]), "events arrive in order: \(events)")
    check(started == 2, "an exited loop is restarted after the 5 s backoff (started \(started) times)")
    await supervisor.stop()
    check(supervisor.phase == .stopped, "stop() leaves the supervisor stopped")
    log.flush()
    let logText = (try? String(contentsOf: logURL, encoding: .utf8)) ?? ""
    check(logText.contains("stray stdout line") && logText.contains("stray stderr line"), "stray output goes to app.log")
    check(logText.contains("unreadable event line"), "a malformed event line is logged, not delivered")

    setenv("FAKE_LOOP_SCENARIO", "linger", 1)
    events.removeAll()
    supervisor.start(with: client)
    try await Task.sleep(nanoseconds: 1_500_000_000)
    let stopStarted = Date()
    await supervisor.stop()
    let stopTook = Date().timeIntervalSince(stopStarted)
    check(stopTook >= 0.9 && stopTook < 10, "stop() waits for a loop finishing its cycle (took \(stopTook) s)")
    check(events.last == "cycle_finished", "the cycle in progress finished before exit: \(events)")
}

// MARK: - Write commands and logging

section("Write commands are never interrupted")
do {
    check(EngineClient.isWriteCommand(["sync", "--no-delete-stale", "--json"]), "a live sync writes")
    check(!EngineClient.isWriteCommand(["sync", "--dry-run", "--no-delete-stale", "--json"]), "a dry run is read-only")
    check(EngineClient.isWriteCommand(["rebuild", "--yes", "--json"]) && !EngineClient.isWriteCommand(["rebuild", "--dry-run", "--json"]), "rebuild --yes writes, --dry-run does not")
    for command in [["approvals", "apply", "f", "--json"], ["approvals", "hold", "f", "--json"], ["migrate", "--yes", "--json"],
                    ["uninstall", "--yes", "--json"], ["signout", "--revoke", "--json"], ["client", "import", "p", "--json"],
                    ["config", "init", "--force", "--json"], ["config", "merge", "--json"], ["agent", "install", "--app", "a", "--json"]] {
        check(EngineClient.isWriteCommand(command), "\(command.prefix(2).joined(separator: " ")) writes")
    }
    for command in [["auth", "--json"], ["status", "--json"], ["account", "--json"], ["lists", "--json"], ["approvals", "show", "--json"],
                    ["config", "show", "--json"], ["client", "status", "--json"], ["doctor", "--json"], ["agent", "status", "--json"]] {
        check(!EngineClient.isWriteCommand(command), "\(command.prefix(2).joined(separator: " ")) can be cancelled")
    }
    check(ConfigKeys.affectRunningLoop(["include_lists"]) && ConfigKeys.affectRunningLoop(["tasks_sync_undated"]) && ConfigKeys.affectRunningLoop(["proxy"]), "sync-behaviour keys restart the loop")
    check(!ConfigKeys.affectRunningLoop(["macos_notifications", "setup_completed_at"]), "other keys do not restart the loop")
    let engine = "/A/Local Tasks Bridge.app/Contents/Resources/engine/local_tasks_bridge.py"
    check(EngineSupervisor.isOrphanedLoop(command: "/usr/bin/python3 -I -B \(engine) --config /h/.config/local-tasks-bridge/config.json run-loop --log-file /l", enginePath: engine, configPath: "/h/.config/local-tasks-bridge/config.json"), "an orphaned loop of this engine and config matches")
    check(!EngineSupervisor.isOrphanedLoop(command: "/usr/bin/python3 -B \(engine) --config /other/config.json run-loop", enginePath: engine, configPath: "/h/.config/local-tasks-bridge/config.json"), "a loop with another config is left alone")

    let logURL = work.appendingPathComponent("write-logs/app.log")
    let log = AppLog(url: logURL)
    let python = PythonLocator.findPython(bundle: work.appendingPathComponent("NoSuch.app"), environment: ProcessInfo.processInfo.environment)
        ?? URL(fileURLWithPath: "/usr/bin/python3")
    let client = EngineClient(
        runtime: EngineRuntime(python: python, engine: repoRoot.appendingPathComponent("macos/Tests/AppCore/fake_engine.py"), bundle: work.appendingPathComponent("Fake.app")),
        paths: AppPaths(configDirectory: work.appendingPathComponent("w"), configFile: work.appendingPathComponent("w/config.json"), logDirectory: work.appendingPathComponent("write-logs")),
        log: log
    )

    let started = Date()
    let merge = Task { try await client.configMerge(["include_lists": .strings(["Work"])]) }
    try await Task.sleep(nanoseconds: 300_000_000)
    check(client.writeInProgress, "a running config merge counts as a write")
    merge.cancel()
    client.terminateReadOnlyCommands()
    let merged = try await merge.value
    check(merged.includeLists == ["Work"] && Date().timeIntervalSince(started) >= 0.9, "a cancelled write still runs to the end")
    await client.waitForWrites()
    check(!client.writeInProgress, "waitForWrites returns once writes are done")

    let statusStarted = Date()
    let status = Task { try await client.status() }
    try await Task.sleep(nanoseconds: 300_000_000)
    status.cancel()
    do {
        _ = try await status.value
        check(false, "a cancelled read-only command stops")
    } catch let error as EngineError {
        check(error.isCancellation && Date().timeIntervalSince(statusStarted) < 5, "a read-only command is cancelled with SIGTERM")
    }

    do {
        _ = try await client.doctor()
    } catch {}
    log.flush()
    let text = (try? String(contentsOf: logURL, encoding: .utf8)) ?? ""
    check(text.contains("engine doctor: failed (exit 1)"), "a failed command is logged by name, code, and exit status")
    check(!text.contains("SECRET-TITLE"), "engine stderr does not reach app.log")
} catch {
    check(false, "write command tests threw \(error)")
}

// MARK: - App log

section("App log")
do {
    let directory = work.appendingPathComponent("rotation")
    let url = directory.appendingPathComponent("app.log")
    let log = AppLog(url: url, maxBytes: 400)
    for index in 0..<40 {
        log.write("line \(index) with some padding text")
    }
    log.flush()
    let attributes = try fileManager.attributesOfItem(atPath: url.path)
    let directoryAttributes = try fileManager.attributesOfItem(atPath: directory.path)
    check(fileManager.fileExists(atPath: url.path + ".1"), "the log rotates to app.log.1")
    check((attributes[.size] as? NSNumber)?.intValue ?? 0 <= 400, "the current log stays under the limit")
    check((attributes[.posixPermissions] as? NSNumber)?.intValue == 0o600, "app.log is 0600")
    check((directoryAttributes[.posixPermissions] as? NSNumber)?.intValue == 0o700, "the log directory is 0700")
} catch {
    check(false, "log tests threw \(error)")
}

print(failures == 0 ? "PASS: \(checks) checks" : "FAILED: \(failures) of \(checks) checks")
exit(failures == 0 ? 0 : 1)
