import Foundation

/// The result of a finished child process.
struct ProcessOutput {
    var exitCode: Int32
    var killedBySignal: Bool
    var stdout: Data
    var stderr: Data
    var timedOut: Bool
    var cancelled: Bool
}

enum OutputStream {
    case stdout
    case stderr
}

/// A child process whose output is either collected (one-shot commands) or
/// delivered line by line (the long-running `run-loop`).
///
/// Stopping always sends SIGTERM first and SIGKILL only if the process is still
/// running after its grace period. Completion waits for both pipes to reach
/// end-of-file, but no longer than `drainGracePeriod` after exit, so a
/// grandchild that inherited a pipe cannot keep a finished command pending.
final class ChildProcess: @unchecked Sendable {
    static let defaultTerminationGracePeriod: TimeInterval = 5
    static let drainGracePeriod: TimeInterval = 2

    private let process = Process()
    private let terminationGracePeriod: TimeInterval
    private let stdoutPipe = Pipe()
    private let stderrPipe = Pipe()
    private let lock = NSLock()
    private let lineHandler: ((OutputStream, String) -> Void)?

    private var stdoutData = Data()
    private var stderrData = Data()
    private var partialLines: [OutputStream: Data] = [:]
    private var openStreams = 2
    private var launched = false
    private var exited = false
    private var finished = false
    private var timedOut = false
    private var cancelled = false
    private var exitCode: Int32 = -1
    private var killedBySignal = false
    private var completion: ((ProcessOutput) -> Void)?

    /// - Parameters:
    ///   - terminationGracePeriod: how long to wait after SIGTERM before SIGKILL.
    ///   - lineHandler: when set, output is split into lines and passed here (on
    ///     a background queue) instead of being collected.
    init(
        executable: URL,
        arguments: [String],
        environment: [String: String],
        currentDirectory: URL? = nil,
        terminationGracePeriod: TimeInterval = ChildProcess.defaultTerminationGracePeriod,
        lineHandler: ((OutputStream, String) -> Void)? = nil
    ) {
        self.terminationGracePeriod = terminationGracePeriod
        process.executableURL = executable
        process.arguments = arguments
        process.environment = environment
        if let currentDirectory {
            process.currentDirectoryURL = currentDirectory
        }
        self.lineHandler = lineHandler
    }

    var processIdentifier: Int32 {
        lock.lock()
        defer { lock.unlock() }
        return launched ? process.processIdentifier : 0
    }

    var isRunning: Bool {
        lock.lock()
        defer { lock.unlock() }
        return launched && !exited
    }

    /// Launches the process. `completion` runs exactly once, on a background queue.
    func start(input: Data?, timeout: TimeInterval?, completion: @escaping (ProcessOutput) -> Void) throws {
        lock.lock()
        self.completion = completion
        if cancelled {
            lock.unlock()
            finish()
            return
        }

        process.standardOutput = stdoutPipe
        process.standardError = stderrPipe
        let inputPipe = input == nil ? nil : Pipe()
        process.standardInput = inputPipe ?? FileHandle.nullDevice
        process.terminationHandler = { [self] finishedProcess in
            processExited(status: finishedProcess.terminationStatus, reason: finishedProcess.terminationReason)
        }
        stdoutPipe.fileHandleForReading.readabilityHandler = { [self] handle in
            received(handle.availableData, from: .stdout)
        }
        stderrPipe.fileHandleForReading.readabilityHandler = { [self] handle in
            received(handle.availableData, from: .stderr)
        }

        do {
            try process.run()
        } catch {
            stdoutPipe.fileHandleForReading.readabilityHandler = nil
            stderrPipe.fileHandleForReading.readabilityHandler = nil
            process.terminationHandler = nil
            self.completion = nil
            lock.unlock()
            throw error
        }
        launched = true
        lock.unlock()

        if let inputPipe, let input {
            DispatchQueue.global(qos: .utility).async {
                let handle = inputPipe.fileHandleForWriting
                // EPIPE (the child exited without reading) is not an error here;
                // SIGPIPE is ignored process-wide in main.swift.
                try? handle.write(contentsOf: input)
                try? handle.close()
            }
        }
        if let timeout {
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeout) { [weak self] in
                self?.timeoutExpired()
            }
        }
    }

    /// Stops the process (SIGTERM, then SIGKILL after the grace period). Before
    /// `start` it only marks the process cancelled; `start` then completes at once.
    func cancel() {
        lock.lock()
        cancelled = true
        let running = launched && !exited
        lock.unlock()
        if running {
            terminate()
        }
    }

    func terminate() {
        lock.lock()
        let running = launched && !exited
        let pid = process.processIdentifier
        lock.unlock()
        guard running, pid > 0 else {
            return
        }
        kill(pid, SIGTERM)
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + terminationGracePeriod) { [weak self] in
            guard let self, self.isRunning else {
                return
            }
            kill(pid, SIGKILL)
        }
    }

    private func timeoutExpired() {
        lock.lock()
        let running = launched && !exited
        if running {
            timedOut = true
        }
        lock.unlock()
        if running {
            terminate()
        }
    }

    private func received(_ data: Data, from stream: OutputStream) {
        if data.isEmpty {
            pipe(for: stream).fileHandleForReading.readabilityHandler = nil
            lock.lock()
            let remainder = partialLines.removeValue(forKey: stream)
            openStreams -= 1
            let done = openStreams <= 0 && exited
            lock.unlock()
            if let remainder, !remainder.isEmpty {
                lineHandler?(stream, String(decoding: remainder, as: UTF8.self))
            }
            if done {
                finish()
            }
            return
        }

        guard let lineHandler else {
            lock.lock()
            switch stream {
            case .stdout: stdoutData.append(data)
            case .stderr: stderrData.append(data)
            }
            lock.unlock()
            return
        }

        lock.lock()
        var buffer = partialLines[stream] ?? Data()
        buffer.append(data)
        var lines: [String] = []
        while let newline = buffer.firstIndex(of: 0x0A) {
            lines.append(String(decoding: buffer[buffer.startIndex..<newline], as: UTF8.self))
            buffer.removeSubrange(buffer.startIndex...newline)
        }
        partialLines[stream] = buffer
        lock.unlock()
        for line in lines {
            lineHandler(stream, line)
        }
    }

    private func processExited(status: Int32, reason: Process.TerminationReason) {
        lock.lock()
        exited = true
        exitCode = status
        killedBySignal = reason == .uncaughtSignal
        let done = openStreams <= 0
        lock.unlock()
        if done {
            finish()
        } else {
            DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + Self.drainGracePeriod) { [weak self] in
                self?.finish()
            }
        }
    }

    private func finish() {
        lock.lock()
        guard !finished else {
            lock.unlock()
            return
        }
        finished = true
        let output = ProcessOutput(
            exitCode: exitCode,
            killedBySignal: killedBySignal,
            stdout: stdoutData,
            stderr: stderrData,
            timedOut: timedOut,
            cancelled: cancelled
        )
        let completion = self.completion
        self.completion = nil
        let wasLaunched = launched
        lock.unlock()

        if wasLaunched {
            for pipe in [stdoutPipe, stderrPipe] {
                pipe.fileHandleForReading.readabilityHandler = nil
            }
            process.terminationHandler = nil
        }
        completion?(output)
    }

    private func pipe(for stream: OutputStream) -> Pipe {
        stream == .stdout ? stdoutPipe : stderrPipe
    }
}

extension ChildProcess {
    /// Runs a short helper synchronously and returns its exit status, or nil if
    /// it could not start or did not finish within `timeout`. Off the main thread only.
    static func exitStatus(
        of executable: URL,
        arguments: [String],
        environment: [String: String],
        timeout: TimeInterval
    ) -> Int32? {
        let child = ChildProcess(executable: executable, arguments: arguments, environment: environment)
        let semaphore = DispatchSemaphore(value: 0)
        var result: ProcessOutput?
        do {
            try child.start(input: nil, timeout: timeout) { output in
                result = output
                semaphore.signal()
            }
        } catch {
            return nil
        }
        semaphore.wait()
        guard let result, !result.timedOut, !result.killedBySignal else {
            return nil
        }
        return result.exitCode
    }
}
