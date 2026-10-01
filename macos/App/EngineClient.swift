import Foundation

/// Error codes from contract section 4, plus the few the app adds itself.
enum EngineErrorCode {
    static let failed = "failed"
    static let usage = "usage"
    static let authRequired = "auth_required"
    static let accountBindingRequired = "account_binding_required"
    static let approvalRequired = "approval_required"
    static let remindersUnavailable = "reminders_unavailable"
    static let configInvalid = "config_invalid"
    static let oauthClientMissing = "oauth_client_missing"
    static let network = "network"
    static let planChanged = "plan_changed"

    static let timeout = "timeout"
    static let cancelled = "cancelled"
    static let launchFailed = "launch_failed"
    static let invalidOutput = "invalid_output"
    static let engineUnavailable = "engine_unavailable"

    static func forExitStatus(_ status: Int32) -> String {
        switch status {
        case 2: return usage
        case 3: return authRequired
        case 4: return accountBindingRequired
        case 5: return approvalRequired
        case 6: return remindersUnavailable
        case 7: return configInvalid
        case 8: return oauthClientMissing
        case 9: return network
        case 10: return planChanged
        default: return failed
        }
    }
}

/// A failed engine command. `message` is ready to show: the engine localizes
/// its own messages (LTB_LANG), and the app localizes the fallbacks.
struct EngineError: Error, LocalizedError {
    var code: String
    var message: String
    var exitCode: Int32?
    /// The complete JSON object the engine printed, if any (e.g. the blocked plan).
    var payload: Data?

    init(code: String, message: String? = nil, exitCode: Int32? = nil, payload: Data? = nil) {
        self.code = code
        self.message = message.flatMap { $0.isEmpty ? nil : $0 } ?? EngineError.fallbackMessage(for: code)
        self.exitCode = exitCode
        self.payload = payload
    }

    var errorDescription: String? { message }
    var isCancellation: Bool { code == EngineErrorCode.cancelled }

    func decodePayload<T: Decodable>(_ type: T.Type) -> T? {
        guard let payload else {
            return nil
        }
        return try? JSONDecoder().decode(T.self, from: payload)
    }

    static func fallbackMessage(for code: String) -> String {
        switch code {
        case EngineErrorCode.usage:
            return NSLocalizedString("The sync engine did not understand the request. Reinstall Local Tasks Bridge so the app and engine match.", comment: "Engine error")
        case EngineErrorCode.authRequired:
            return NSLocalizedString("Sign in to Google again to keep syncing.", comment: "Engine error")
        case EngineErrorCode.accountBindingRequired:
            return NSLocalizedString("The Apple or Google account is different from the one this Mac synced with before.", comment: "Engine error")
        case EngineErrorCode.approvalRequired:
            return NSLocalizedString("Some deletions or completions are waiting for your approval.", comment: "Engine error")
        case EngineErrorCode.remindersUnavailable:
            return NSLocalizedString("Local Tasks Bridge can’t read Reminders. Allow access in System Settings > Privacy & Security > Reminders.", comment: "Engine error")
        case EngineErrorCode.configInvalid:
            return NSLocalizedString("A setting is invalid.", comment: "Engine error")
        case EngineErrorCode.oauthClientMissing:
            return NSLocalizedString("No Google sign-in method is set up yet.", comment: "Engine error")
        case EngineErrorCode.network:
            return NSLocalizedString("Google can’t be reached right now. Check your internet connection and proxy settings.", comment: "Engine error")
        case EngineErrorCode.planChanged:
            return NSLocalizedString("The pending changes are different now. Review them again.", comment: "Engine error")
        case EngineErrorCode.timeout:
            return NSLocalizedString("The sync engine took too long to respond.", comment: "Engine error")
        case EngineErrorCode.cancelled:
            return NSLocalizedString("Cancelled.", comment: "Engine error")
        case EngineErrorCode.launchFailed:
            return NSLocalizedString("The sync engine could not be started.", comment: "Engine error")
        case EngineErrorCode.invalidOutput:
            return NSLocalizedString("The sync engine returned an unexpected response.", comment: "Engine error")
        case EngineErrorCode.engineUnavailable:
            return NSLocalizedString("Python 3.9 or newer is required.", comment: "Engine error")
        default:
            return NSLocalizedString("Something went wrong. Details are in the log.", comment: "Engine error")
        }
    }
}

/// Tracks running engine commands so they can all be stopped when the app quits.
final class ProcessRegistry: @unchecked Sendable {
    private let lock = NSLock()
    private var processes: [ObjectIdentifier: ChildProcess] = [:]

    func add(_ process: ChildProcess) {
        lock.lock()
        processes[ObjectIdentifier(process)] = process
        lock.unlock()
    }

    func remove(_ process: ChildProcess) {
        lock.lock()
        processes[ObjectIdentifier(process)] = nil
        lock.unlock()
    }

    func terminateAll() {
        lock.lock()
        let running = Array(processes.values)
        lock.unlock()
        running.forEach { $0.cancel() }
    }
}

/// Runs engine commands: `python3 -B <engine> --config <config> <command> …`.
final class EngineClient: @unchecked Sendable {
    static let defaultTimeout: TimeInterval = 60
    /// Read-only commands that run often; only their failures are logged.
    private static let quietCommands: Set<String> = ["status", "version", "config show", "client status", "agent status", "lists"]

    let runtime: EngineRuntime
    let paths: AppPaths
    private let log: AppLog?
    private let registry = ProcessRegistry()

    init(runtime: EngineRuntime, paths: AppPaths, log: AppLog?) {
        self.runtime = runtime
        self.paths = paths
        self.log = log
    }

    /// The inherited environment without Python or event-stream overrides,
    /// plus the fixed variables of contract section 3.
    static func baseEnvironment(from inherited: [String: String]) -> [String: String] {
        var environment = inherited.filter { key, _ in
            !key.hasPrefix("PYTHON") && key != "__PYVENV_LAUNCHER__" && key != "LTB_EVENT_STREAM"
        }
        environment["PATH"] = "/usr/bin:/bin:/usr/sbin:/sbin"
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        environment["PYTHONUNBUFFERED"] = "1"
        return environment
    }

    func environment(eventStream: Bool) -> [String: String] {
        var environment = Self.baseEnvironment(from: ProcessInfo.processInfo.environment)
        environment["LTB_LANG"] = AppInfo.engineLanguage
        environment["LTB_APP_BUNDLE"] = runtime.bundle.path
        // Tells the engine the app itself is calling (for example, never boot
        // out the login item that is running this app). `ltb` does not set it.
        environment["LTB_CALLER"] = "app"
        if eventStream {
            environment["LTB_EVENT_STREAM"] = "stdout"
        }
        return environment
    }

    func arguments(for command: [String]) -> [String] {
        ["-B", runtime.engine.path, "--config", paths.configFile.path] + command
    }

    /// Runs a command and returns the JSON object it printed on success.
    func run(_ command: [String], input: Data? = nil, timeout: TimeInterval? = EngineClient.defaultTimeout) async throws -> Data {
        let started = Date()
        let child = ChildProcess(
            executable: runtime.python,
            arguments: arguments(for: command),
            environment: environment(eventStream: false),
            currentDirectory: FileManager.default.homeDirectoryForCurrentUser
        )
        registry.add(child)
        defer { registry.remove(child) }

        let output: ProcessOutput
        do {
            output = try await withTaskCancellationHandler {
                try await withCheckedThrowingContinuation { (continuation: CheckedContinuation<ProcessOutput, Error>) in
                    do {
                        try child.start(input: input, timeout: timeout) { continuation.resume(returning: $0) }
                    } catch {
                        continuation.resume(throwing: error)
                    }
                }
            } onCancel: {
                child.cancel()
            }
        } catch {
            log?.write("engine \(command.joined(separator: " ")): could not start \(runtime.python.path): \(error.localizedDescription)")
            throw EngineError(code: EngineErrorCode.launchFailed)
        }

        let result = Self.interpret(output)
        record(command: command, output: output, result: result, duration: Date().timeIntervalSince(started))
        return try result.get()
    }

    func request<T: Decodable>(
        _ type: T.Type,
        _ command: [String],
        input: Data? = nil,
        timeout: TimeInterval? = EngineClient.defaultTimeout
    ) async throws -> T {
        let data = try await run(command, input: input, timeout: timeout)
        do {
            return try JSONDecoder().decode(T.self, from: data)
        } catch {
            log?.write("engine \(command.joined(separator: " ")): unexpected JSON: \(error)")
            throw EngineError(code: EngineErrorCode.invalidOutput, payload: data)
        }
    }

    /// The long-running scheduler child; the caller starts and supervises it.
    /// On SIGTERM the loop finishes a cycle in progress first, so it gets 30 s.
    func makeRunLoopProcess(lineHandler: @escaping (OutputStream, String) -> Void) -> ChildProcess {
        ChildProcess(
            executable: runtime.python,
            arguments: arguments(for: ["run-loop", "--log-file", paths.engineLog.path]),
            environment: environment(eventStream: true),
            currentDirectory: FileManager.default.homeDirectoryForCurrentUser,
            terminationGracePeriod: 30,
            lineHandler: lineHandler
        )
    }

    /// Stops every running one-shot command (used when the app quits).
    func terminateAll() {
        registry.terminateAll()
    }

    static func interpret(_ output: ProcessOutput) -> Result<Data, EngineError> {
        if output.cancelled {
            return .failure(EngineError(code: EngineErrorCode.cancelled))
        }
        if output.timedOut {
            return .failure(EngineError(code: EngineErrorCode.timeout))
        }
        let exitedCleanly = output.exitCode == 0 && !output.killedBySignal
        if let json = jsonObject(in: output.stdout),
           let envelope = try? JSONDecoder().decode(EngineEnvelope.self, from: json) {
            if exitedCleanly && envelope.ok != false {
                return .success(json)
            }
            let code = envelope.error?.code ?? EngineErrorCode.forExitStatus(exitedCleanly ? 1 : output.exitCode)
            return .failure(EngineError(code: code, message: envelope.error?.message, exitCode: output.exitCode, payload: json))
        }
        if exitedCleanly {
            return .failure(EngineError(code: EngineErrorCode.invalidOutput, exitCode: 0))
        }
        let code = output.killedBySignal ? EngineErrorCode.failed : EngineErrorCode.forExitStatus(output.exitCode)
        return .failure(EngineError(code: code, exitCode: output.exitCode))
    }

    /// The single JSON object a `--json` command prints; tolerates stray lines before it.
    static func jsonObject(in data: Data) -> Data? {
        let text = String(decoding: data, as: UTF8.self).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else {
            return nil
        }
        var candidates = [text]
        if let lastObjectLine = text.split(separator: "\n").last(where: { $0.hasPrefix("{") }) {
            candidates.append(String(lastObjectLine))
        }
        for candidate in candidates where candidate.hasPrefix("{") {
            let candidateData = Data(candidate.utf8)
            if (try? JSONSerialization.jsonObject(with: candidateData)) is [String: Any] {
                return candidateData
            }
        }
        return nil
    }

    private func record(command: [String], output: ProcessOutput, result: Result<Data, EngineError>, duration: TimeInterval) {
        guard let log else {
            return
        }
        let name = command.prefix(while: { !$0.hasPrefix("-") }).prefix(2).joined(separator: " ")
        let elapsed = String(format: "%.1fs", duration)
        switch result {
        case .success:
            if !Self.quietCommands.contains(name) {
                log.write("engine \(name): ok in \(elapsed)")
            }
        case .failure(let error):
            if error.isCancellation {
                log.write("engine \(name): cancelled after \(elapsed)")
                return
            }
            var entry = "engine \(name): \(error.code) (exit \(output.exitCode)) after \(elapsed)"
            let stderrTail = String(decoding: output.stderr, as: UTF8.self)
                .split(separator: "\n")
                .suffix(20)
                .map { "  stderr: \($0)" }
            if !stderrTail.isEmpty {
                entry += "\n" + stderrTail.joined(separator: "\n")
            }
            log.write(entry)
        }
    }
}

// MARK: - Commands

extension EngineClient {
    func version() async throws -> EngineVersionInfo {
        try await request(EngineVersionInfo.self, ["version", "--json"])
    }

    func status() async throws -> EngineStatus {
        try await request(EngineStatus.self, ["status", "--json"])
    }

    func configShow() async throws -> BridgeConfig {
        try await request(ConfigResponse.self, ["config", "show", "--json"]).config ?? BridgeConfig()
    }

    func configInit() async throws {
        _ = try await run(["config", "init", "--json"])
    }

    @discardableResult
    func configMerge(_ values: [String: JSONValue]) async throws -> BridgeConfig {
        let response = try await request(
            ConfigResponse.self,
            ["config", "merge", "--json"],
            input: JSONValue.encodeObject(values)
        )
        return response.config ?? BridgeConfig()
    }

    func clientStatus() async throws -> OAuthClientStatus {
        try await request(OAuthClientStatus.self, ["client", "status", "--json"])
    }

    func importClient(at file: URL) async throws -> ClientImportResponse {
        try await request(ClientImportResponse.self, ["client", "import", file.path, "--json"])
    }

    /// Opens Google sign-in in the browser and waits (up to 5 minutes, engine side).
    func signIn() async throws -> AuthResponse {
        try await request(AuthResponse.self, ["auth", "--json"], timeout: nil)
    }

    func account() async throws -> AccountResponse {
        try await request(AccountResponse.self, ["account", "--json"])
    }

    func signOut(revoke: Bool) async throws {
        _ = try await run(["signout"] + (revoke ? ["--revoke"] : []) + ["--json"])
    }

    func lists(includeGoogle: Bool) async throws -> ListsResponse {
        try await request(ListsResponse.self, ["lists"] + (includeGoogle ? ["--google"] : []) + ["--json"], timeout: 180)
    }

    func sync(dryRun: Bool, deleteStale: Bool) async throws -> SyncResponse {
        var command = ["sync"]
        if dryRun {
            command.append("--dry-run")
        }
        if !deleteStale {
            command.append("--no-delete-stale")
        }
        return try await request(SyncResponse.self, command + ["--json"], timeout: nil)
    }

    /// Builds a new sync map for the accounts now in use (account_binding_required).
    func rebuild(dryRun: Bool) async throws -> SyncResponse {
        try await request(SyncResponse.self, ["rebuild", dryRun ? "--dry-run" : "--yes", "--json"], timeout: nil)
    }

    func pause() async throws {
        _ = try await run(["pause", "--json"])
    }

    func resume() async throws {
        _ = try await run(["resume", "--json"])
    }

    func syncNow() async throws {
        _ = try await run(["sync-now", "--json"])
    }

    func pendingApprovals() async throws -> ApprovalsResponse {
        try await request(ApprovalsResponse.self, ["approvals", "show", "--json"], timeout: nil)
    }

    func applyApprovals(fingerprint: String) async throws {
        _ = try await run(["approvals", "apply", fingerprint, "--json"], timeout: nil)
    }

    func holdApprovals(fingerprint: String) async throws {
        _ = try await run(["approvals", "hold", fingerprint, "--json"])
    }

    func doctor() async throws -> Data {
        try await run(["doctor", "--json"])
    }

    func migrate() async throws -> MigrateResponse {
        try await request(MigrateResponse.self, ["migrate", "--yes", "--json"], timeout: 180)
    }

    func installAgent() async throws {
        _ = try await run(["agent", "install", "--app", runtime.bundle.path, "--json"])
    }

    func uninstallAgent() async throws {
        _ = try await run(["agent", "uninstall", "--json"])
    }

    func uninstall(revoke: Bool, deleteData: Bool) async throws {
        var command = ["uninstall"]
        if revoke {
            command.append("--revoke")
        }
        if deleteData {
            command.append("--delete-data")
        }
        _ = try await run(command + ["--yes", "--json"], timeout: 180)
    }
}
