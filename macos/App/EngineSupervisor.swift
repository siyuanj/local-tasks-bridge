import Foundation

/// Runs `run-loop` as a child process while setup is complete.
///
/// Event lines (`@@LTB {...}`) go to `onEvent`; any other output goes to the
/// app log. An unexpected exit is retried after 5 s, doubling up to 5 min; a
/// child that ran for 5 min or more counts as healthy and resets the delay.
/// A loop that exits because another `run-loop` holds the loop lock is
/// retried on the same schedule.
@MainActor
final class EngineSupervisor {
    enum Phase: Equatable {
        case stopped
        case running
        case waitingToRestart
        case stopping
    }

    static let initialRestartDelay: TimeInterval = 5
    static let maximumRestartDelay: TimeInterval = 300
    static let healthyRunDuration: TimeInterval = 300

    var onEvent: ((EngineEvent) -> Void)?
    var onPhaseChange: ((Phase) -> Void)?

    private(set) var phase: Phase = .stopped {
        didSet {
            if phase != oldValue {
                onPhaseChange?(phase)
            }
        }
    }
    private(set) var cycleInProgress = false

    private let log: AppLog
    private var client: EngineClient?
    private var child: ChildProcess?
    private var childStartedAt = Date()
    private var wantsRunning = false
    private var restartDelay = EngineSupervisor.initialRestartDelay
    private var pendingRestart: DispatchWorkItem?
    private var restartWhenIdle = false
    private var restartRequested = false
    private var stopWaiters: [CheckedContinuation<Void, Never>] = []
    private var checkedForOrphans = false

    init(log: AppLog) {
        self.log = log
    }

    var isActive: Bool { wantsRunning }

    func start(with client: EngineClient) {
        self.client = client
        guard !wantsRunning else {
            return
        }
        wantsRunning = true
        restartDelay = Self.initialRestartDelay
        launch()
    }

    /// Stops the child: SIGTERM, then SIGKILL if it is still running after 30 s
    /// (the engine finishes a cycle in progress before it exits).
    func stop() async {
        wantsRunning = false
        restartWhenIdle = false
        restartRequested = false
        pendingRestart?.cancel()
        pendingRestart = nil
        guard let child else {
            phase = .stopped
            return
        }
        phase = .stopping
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            stopWaiters.append(continuation)
            child.terminate()
        }
    }

    /// Restarts the child so it rereads settings, waiting for a running cycle to end.
    func restart() {
        guard wantsRunning else {
            return
        }
        guard let child else {
            pendingRestart?.cancel()
            pendingRestart = nil
            restartDelay = Self.initialRestartDelay
            launch()
            return
        }
        if cycleInProgress {
            restartWhenIdle = true
            return
        }
        restartRequested = true
        child.terminate()
    }

    private func launch() {
        guard wantsRunning, child == nil, let client else {
            return
        }
        if !checkedForOrphans {
            checkedForOrphans = true
            Self.terminateOrphanedLoops(enginePath: client.runtime.engine.path, configPath: client.paths.configFile.path, log: log)
        }
        let process = client.makeRunLoopProcess { [weak self] stream, line in
            DispatchQueue.main.async {
                self?.handle(line: line, from: stream)
            }
        }
        do {
            try process.start(input: nil, timeout: nil) { [weak self] output in
                DispatchQueue.main.async {
                    self?.childExited(process, output: output)
                }
            }
        } catch {
            log.write("run-loop could not start: \(error.localizedDescription)")
            scheduleRestart(afterRunningFor: 0)
            return
        }
        child = process
        childStartedAt = Date()
        cycleInProgress = false
        phase = .running
        log.write("run-loop started (pid \(process.processIdentifier))")
    }

    private func handle(line: String, from stream: OutputStream) {
        if stream == .stdout, line.hasPrefix(EngineEvent.linePrefix) {
            guard let event = EngineEvent.parse(line: line) else {
                log.write("run-loop sent an unreadable event line")
                return
            }
            switch event.event {
            case "cycle_started":
                cycleInProgress = true
            case "cycle_finished":
                cycleInProgress = false
                if restartWhenIdle {
                    restartWhenIdle = false
                    restartRequested = true
                    child?.terminate()
                }
            default:
                break
            }
            onEvent?(event)
            return
        }
        guard !line.trimmingCharacters(in: .whitespaces).isEmpty else {
            return
        }
        log.write("run-loop \(stream == .stdout ? "stdout" : "stderr"): \(line)")
    }

    private func childExited(_ process: ChildProcess, output: ProcessOutput) {
        guard process === child else {
            return
        }
        child = nil
        cycleInProgress = false
        let ranFor = Date().timeIntervalSince(childStartedAt)
        let how = output.killedBySignal ? "was stopped by signal \(output.exitCode)" : "exited with status \(output.exitCode)"
        log.write("run-loop \(how) after \(Int(ranFor)) s")

        let waiters = stopWaiters
        stopWaiters.removeAll()
        waiters.forEach { $0.resume() }

        guard wantsRunning else {
            phase = .stopped
            return
        }
        if restartRequested {
            restartRequested = false
            restartDelay = Self.initialRestartDelay
            launch()
        } else {
            scheduleRestart(afterRunningFor: ranFor)
        }
    }

    private func scheduleRestart(afterRunningFor ranFor: TimeInterval) {
        if ranFor >= Self.healthyRunDuration {
            restartDelay = Self.initialRestartDelay
        }
        let delay = restartDelay
        restartDelay = min(restartDelay * 2, Self.maximumRestartDelay)
        phase = .waitingToRestart
        log.write("run-loop restarts in \(Int(delay)) s")
        let work = DispatchWorkItem { [weak self] in
            guard let self else {
                return
            }
            self.pendingRestart = nil
            self.launch()
        }
        pendingRestart = work
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
    }

    /// A previous copy of the app that crashed or was force-quit leaves its
    /// `run-loop` child running under launchd. Stop those before starting a new one.
    /// Whether a `ps` command line is a `run-loop` of this engine and config.
    static func isOrphanedLoop(command: String, enginePath: String, configPath: String) -> Bool {
        command.contains(enginePath) && command.contains("--config \(configPath) ") && command.contains(" run-loop")
    }

    private static func terminateOrphanedLoops(enginePath: String, configPath: String, log: AppLog) {
        let ps = Process()
        ps.executableURL = URL(fileURLWithPath: "/bin/ps")
        ps.arguments = ["-axww", "-o", "pid=,ppid=,command="]
        let pipe = Pipe()
        ps.standardOutput = pipe
        ps.standardError = FileHandle.nullDevice
        do {
            try ps.run()
        } catch {
            return
        }
        let data = pipe.fileHandleForReading.readDataToEndOfFile()
        ps.waitUntilExit()
        for line in String(decoding: data, as: UTF8.self).split(separator: "\n") {
            let fields = line.split(separator: " ", maxSplits: 2, omittingEmptySubsequences: true)
            guard fields.count == 3, let pid = pid_t(fields[0]), fields[1] == "1" else {
                continue
            }
            let command = String(fields[2])
            if isOrphanedLoop(command: command, enginePath: enginePath, configPath: configPath) {
                log.write("stopping orphaned run-loop (pid \(pid)) left by an earlier copy of the app")
                kill(pid, SIGTERM)
            }
        }
    }
}
