import Foundation

// Typed views of the engine's JSON output (docs/app-engine-contract.md,
// section 5). Every field is optional so an older or newer engine that omits a
// field still decodes; only the fields the app uses are declared.

struct EngineVersionInfo: Decodable {
    var version: String?
    var python: String?
    var enginePath: String?

    enum CodingKeys: String, CodingKey {
        case version, python
        case enginePath = "engine_path"
    }
}

struct OAuthClientStatus: Decodable, Equatable {
    /// "auto", "custom", or "bundled": the configured preference.
    var mode: String?
    /// "custom", "bundled", or null: the client a new sign-in would use.
    var active: String?
    var customReady: Bool?
    var bundledAvailable: Bool?

    enum CodingKeys: String, CodingKey {
        case mode, active
        case customReady = "custom_ready"
        case bundledAvailable = "bundled_available"
    }

    var usesSharedClient: Bool { active == "bundled" }
}

struct AgentStatus: Decodable, Equatable {
    var installed: Bool?
    var loaded: Bool?
    var label: String?
    var program: String?
}

struct EngineStatus: Decodable, Equatable {
    var version: String?
    var configPath: String?
    var configExists: Bool?
    var setupCompleted: Bool?
    var condition: String?
    var headline: String?
    var action: String?
    var state: String?
    var paused: Bool?
    var lastSuccessAt: String?
    var lastStartAt: String?
    var lastEndAt: String?
    var consecutiveFailures: Int?
    var pendingDestructiveCounts: [String: Int]?
    var oauthClient: OAuthClientStatus?
    var tokenReady: Bool?
    var includeLists: [String]?
    var syncIntervalSeconds: Int?
    /// The interval the loop really uses (at least 5 minutes with the shared sign-in).
    var effectiveSyncIntervalSeconds: Int?
    /// Some `run-loop` holds the loop lock (this app's child or another one).
    var loopRunning: Bool?
    var agent: AgentStatus?
    var logPath: String?
    var legacyInstallDetected: Bool?

    enum CodingKeys: String, CodingKey {
        case version, condition, headline, action, state, paused, agent
        case configPath = "config_path"
        case configExists = "config_exists"
        case setupCompleted = "setup_completed"
        case lastSuccessAt = "last_success_at"
        case lastStartAt = "last_start_at"
        case lastEndAt = "last_end_at"
        case consecutiveFailures = "consecutive_failures"
        case pendingDestructiveCounts = "pending_destructive_counts"
        case oauthClient = "oauth_client"
        case tokenReady = "token_ready"
        case includeLists = "include_lists"
        case syncIntervalSeconds = "sync_interval_seconds"
        case effectiveSyncIntervalSeconds = "effective_sync_interval_seconds"
        case loopRunning = "loop_running"
        case logPath = "log_path"
        case legacyInstallDetected = "legacy_install_detected"
    }

    var isSetupCompleted: Bool { setupCompleted ?? false }
    var isPaused: Bool { paused ?? false }
    var lastSuccessDate: Date? { EngineDate.parse(lastSuccessAt) }
}

struct AppleList: Decodable, Equatable, Identifiable {
    var id: String
    var title: String
    var accountTitle: String?
    var accountId: String?

    enum CodingKeys: String, CodingKey {
        case id, title
        case accountTitle = "account_title"
        case accountId = "account_id"
    }
}

struct GoogleTaskList: Decodable, Equatable, Identifiable {
    var id: String
    var title: String
}

struct ListsResponse: Decodable {
    var apple: [AppleList]?
    var google: [GoogleTaskList]?
}

/// The user-facing settings shown by `config show` (see `config merge`).
struct BridgeConfig: Decodable, Equatable {
    var includeLists: [String]?
    var bidirectional: Bool?
    var deleteStale: Bool?
    var conflictPolicy: String?
    var tasksSyncUndated: Bool?
    var tasksImportUnsynced: Bool?
    var syncIntervalSeconds: Int?
    var maxDestructiveChanges: Int?
    var maxDestructiveRatio: Double?
    var mutationApprovalPrompt: Bool?
    var macosNotifications: Bool?
    var language: String?
    var proxy: String?
    var oauthClient: String?
    var setupCompletedAt: String?

    enum CodingKeys: String, CodingKey {
        case bidirectional, language, proxy
        case includeLists = "include_lists"
        case deleteStale = "delete_stale"
        case conflictPolicy = "conflict_policy"
        case tasksSyncUndated = "tasks_sync_undated"
        case tasksImportUnsynced = "tasks_import_unsynced"
        case syncIntervalSeconds = "sync_interval_seconds"
        case maxDestructiveChanges = "max_destructive_changes"
        case maxDestructiveRatio = "max_destructive_ratio"
        case mutationApprovalPrompt = "mutation_approval_prompt"
        case macosNotifications = "macos_notifications"
        case oauthClient = "oauth_client"
        case setupCompletedAt = "setup_completed_at"
    }
}

struct ConfigResponse: Decodable {
    var configPath: String?
    var config: BridgeConfig?

    enum CodingKeys: String, CodingKey {
        case config
        case configPath = "config_path"
    }
}

struct ClientImportResponse: Decodable {
    var clientIdHint: String?

    enum CodingKeys: String, CodingKey {
        case clientIdHint = "client_id_hint"
    }
}

struct AuthResponse: Decodable {
    var accountEmail: String?
    var clientMode: String?

    enum CodingKeys: String, CodingKey {
        case accountEmail = "account_email"
        case clientMode = "client_mode"
    }
}

struct AccountResponse: Decodable {
    var accountEmail: String?
    var tasklistCount: Int?

    enum CodingKeys: String, CodingKey {
        case accountEmail = "account_email"
        case tasklistCount = "tasklist_count"
    }
}

struct SyncPlan: Decodable, Equatable {
    var totalCount: Int?
    var destructiveCount: Int?
    var counts: [String: Int]?

    enum CodingKeys: String, CodingKey {
        case counts
        case totalCount = "total_count"
        case destructiveCount = "destructive_count"
    }

    func count(_ key: String) -> Int { counts?[key] ?? 0 }
}

struct SyncResponse: Decodable {
    var dryRun: Bool?
    var plan: SyncPlan?

    enum CodingKeys: String, CodingKey {
        case plan
        case dryRun = "dry_run"
    }
}

struct ApprovalItem: Decodable, Equatable {
    var operation: String?
    var label: String?
    var list: String?
    var title: String?
}

struct ApprovalsResponse: Decodable {
    var pending: Bool?
    var destructiveFingerprint: String?
    var destructiveCount: Int?
    var population: Int?
    var ratio: Double?
    var items: [ApprovalItem]?

    enum CodingKeys: String, CodingKey {
        case pending, population, ratio, items
        case destructiveFingerprint = "destructive_fingerprint"
        case destructiveCount = "destructive_count"
    }
}

struct MigrateResponse: Decodable {
    var migratedFrom: String?
    var copied: [String]?
    var legacyAgentStopped: Bool?

    enum CodingKeys: String, CodingKey {
        case copied
        case migratedFrom = "migrated_from"
        case legacyAgentStopped = "legacy_agent_stopped"
    }
}

/// One `@@LTB {...}` line from `run-loop` (contract run-loop table).
struct EngineEvent: Decodable, Equatable {
    var event: String
    var at: String?
    var version: String?
    var interval: Int?
    var state: String?
    var condition: String?
    var consecutiveFailures: Int?
    var title: String?
    var message: String?
    var severity: String?
    var destructiveFingerprint: String?
    var destructiveCount: Int?

    enum CodingKeys: String, CodingKey {
        case event, at, version, interval, state, condition, title, message, severity
        case consecutiveFailures = "consecutive_failures"
        case destructiveFingerprint = "destructive_fingerprint"
        case destructiveCount = "destructive_count"
    }

    static let linePrefix = "@@LTB "

    /// Parses a stdout line; returns nil for anything that is not an event.
    static func parse(line: String) -> EngineEvent? {
        guard line.hasPrefix(linePrefix) else {
            return nil
        }
        let payload = line.dropFirst(linePrefix.count)
        return try? JSONDecoder().decode(EngineEvent.self, from: Data(payload.utf8))
    }
}

/// Successful responses carry `"ok": true`; failures carry an `error` object.
struct EngineEnvelope: Decodable {
    struct ErrorBody: Decodable {
        var code: String?
        var message: String?
    }

    var ok: Bool?
    var error: ErrorBody?
}

/// ISO 8601 timestamps as the engine writes them, e.g. 2026-10-01T10:41:09+00:00.
enum EngineDate {
    private static let withFraction: ISO8601DateFormatter = {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return formatter
    }()
    private static let plain = ISO8601DateFormatter()
    // "+00:00" rather than "Z": Python 3.9's datetime.fromisoformat rejects "Z".
    private static let writer: DateFormatter = {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.timeZone = TimeZone(secondsFromGMT: 0)
        formatter.dateFormat = "yyyy-MM-dd'T'HH:mm:ssxxx"
        return formatter
    }()

    static func parse(_ text: String?) -> Date? {
        guard let text, !text.isEmpty else {
            return nil
        }
        return plain.date(from: text) ?? withFraction.date(from: text)
    }

    static func string(from date: Date) -> String {
        writer.string(from: date)
    }
}
