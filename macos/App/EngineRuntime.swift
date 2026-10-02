import Foundation

/// The interpreter and engine script the app runs.
struct EngineRuntime: Equatable {
    var python: URL
    var engine: URL
    var bundle: URL
}

enum EngineAvailability: Equatable {
    case locating
    case ready(EngineRuntime)
    /// No Python 3.9+ qualified (contract section 2).
    case pythonMissing
    /// The bundle is incomplete; the engine script is not where it should be.
    case engineMissing(String)
}

/// Finds Python in the order of contract section 2.
enum PythonLocator {
    static let minimumVersionCheck = "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)"

    static func engineScript(in bundle: URL) -> URL {
        bundle.appendingPathComponent("Contents/Resources/engine/local_tasks_bridge.py")
    }

    /// Resolves the runtime. Runs short subprocesses, so call it off the main thread.
    static func locate(bundle: URL, environment: [String: String] = ProcessInfo.processInfo.environment) -> EngineAvailability {
        let engine = engineScript(in: bundle)
        guard FileManager.default.isReadableFile(atPath: engine.path) else {
            return .engineMissing(engine.path)
        }
        guard let python = findPython(bundle: bundle, environment: environment) else {
            return .pythonMissing
        }
        return .ready(EngineRuntime(python: python, engine: engine, bundle: bundle))
    }

    static func findPython(bundle: URL, environment: [String: String]) -> URL? {
        let checkEnvironment = EngineClient.baseEnvironment(from: environment)
        func usable(_ url: URL) -> Bool {
            guard FileManager.default.isExecutableFile(atPath: url.path) else {
                return false
            }
            return ChildProcess.exitStatus(
                of: url,
                arguments: ["-I", "-B", "-c", minimumVersionCheck],
                environment: checkEnvironment,
                timeout: 15
            ) == 0
        }

        if let configured = environment["LTB_PYTHON"], !configured.isEmpty,
           let url = resolveCommand(configured, searchPath: environment["PATH"]), usable(url) {
            return url
        }
        let embedded = bundle.appendingPathComponent("Contents/Resources/python/bin/python3")
        if usable(embedded) {
            return embedded
        }
        // Without the Command Line Tools, /usr/bin/python3 is a shim that opens
        // the installer instead of running Python.
        let systemPython = URL(fileURLWithPath: "/usr/bin/python3")
        if commandLineToolsInstalled(environment: environment), usable(systemPython) {
            return systemPython
        }
        for path in ["/opt/homebrew/bin/python3", "/usr/local/bin/python3"] {
            let url = URL(fileURLWithPath: path)
            if usable(url) {
                return url
            }
        }
        return nil
    }

    static func commandLineToolsInstalled(environment: [String: String] = ProcessInfo.processInfo.environment) -> Bool {
        ChildProcess.exitStatus(
            of: URL(fileURLWithPath: "/usr/bin/xcode-select"),
            arguments: ["-p"],
            environment: environment,
            timeout: 10
        ) == 0
    }

    private static func resolveCommand(_ command: String, searchPath: String?) -> URL? {
        if command.contains("/") {
            return URL(fileURLWithPath: (command as NSString).expandingTildeInPath)
        }
        for directory in (searchPath ?? "").split(separator: ":") where !directory.isEmpty {
            let candidate = URL(fileURLWithPath: String(directory)).appendingPathComponent(command)
            if FileManager.default.isExecutableFile(atPath: candidate.path) {
                return candidate
            }
        }
        return nil
    }
}
