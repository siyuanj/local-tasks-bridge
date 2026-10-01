import Foundation

/// The proxy setting: system settings (""), a direct connection ("none"), or
/// a custom HTTP proxy ("http://host:port").
struct ProxyChoice: Equatable {
    enum Mode: Hashable {
        case system
        case direct
        case custom
    }

    static let exampleURL = "http://127.0.0.1:7890"

    var mode: Mode = .system
    var customURL = ""

    init() {}

    init(configValue: String?) {
        let value = (configValue ?? "").trimmingCharacters(in: .whitespaces)
        switch value {
        case "":
            mode = .system
        case "none":
            mode = .direct
        default:
            mode = .custom
            customURL = value
        }
    }

    var configValue: String {
        switch mode {
        case .system: return ""
        case .direct: return "none"
        case .custom: return customURL.trimmingCharacters(in: .whitespaces)
        }
    }

    /// Only a custom proxy can be invalid: it needs http:// or https://, a host, and a port.
    var isValid: Bool {
        guard mode == .custom else {
            return true
        }
        guard let url = URL(string: configValue),
              let scheme = url.scheme?.lowercased(), scheme == "http" || scheme == "https",
              let host = url.host, !host.isEmpty,
              url.port != nil else {
            return false
        }
        return true
    }
}

/// Sync choices shown in setup and in Settings, as stored by `config merge`.
struct SyncOptions: Equatable {
    static let intervalChoices = [60, 300, 900]
    /// With the shared sign-in the engine polls Google at most every 5 minutes.
    static let sharedClientMinimumInterval = 300

    var bidirectional = true
    var deleteStale = true
    var includeUndated = true
    var importExisting = true
    var intervalSeconds = 60
    var proxy = ProxyChoice()

    init() {}

    /// - Parameter sharedClient: the shared sign-in has a quota shared by
    ///   everyone, so a fresh setup with it defaults to every 5 minutes.
    init(config: BridgeConfig, sharedClient: Bool) {
        bidirectional = config.bidirectional ?? true
        deleteStale = config.deleteStale ?? true
        includeUndated = config.tasksSyncUndated ?? true
        importExisting = config.tasksImportUnsynced ?? true
        let configured = config.syncIntervalSeconds ?? 60
        intervalSeconds = sharedClient ? max(configured, Self.sharedClientMinimumInterval) : configured
        proxy = ProxyChoice(configValue: config.proxy)
    }

    var mergeValues: [String: JSONValue] {
        [
            "bidirectional": .bool(bidirectional),
            "delete_stale": .bool(deleteStale),
            "tasks_sync_undated": .bool(includeUndated),
            "tasks_import_unsynced": .bool(importExisting),
            "sync_interval_seconds": .int(intervalSeconds),
            "proxy": .string(proxy.configValue),
        ]
    }
}

enum ConfigKeys {
    private static let loopKeys: Set<String> = [
        "include_lists", "list_policies", "bidirectional", "delete_stale", "conflict_policy",
        "sync_interval_seconds", "max_destructive_changes", "max_destructive_ratio",
        "proxy", "oauth_client", "language",
    ]

    /// Whether saving these keys should restart the supervised `run-loop`.
    static func affectRunningLoop(_ keys: Set<String>) -> Bool {
        keys.contains { loopKeys.contains($0) || $0.hasPrefix("tasks_") }
    }
}

/// Human summary of a sync plan's `counts` (contract `sync`).
struct PlanSummary: Equatable {
    var addToGoogle = 0
    var addOnMac = 0
    var createGoogleLists = 0
    var updates = 0
    var completions = 0
    var deletions = 0

    init(plan: SyncPlan?) {
        guard let plan else {
            return
        }
        addToGoogle = plan.count("google_tasks.create")
        addOnMac = plan.count("apple_reminders.create")
        createGoogleLists = plan.count("google_tasks.create_list")
        updates = plan.count("google_tasks.update") + plan.count("apple_reminders.update")
            + plan.count("google_tasks.attach") + plan.count("google_tasks.attach_after_create")
        completions = plan.count("google_tasks.complete") + plan.count("apple_reminders.complete")
        deletions = plan.count("google_tasks.delete") + plan.count("apple_reminders.delete")
    }

    var isEmpty: Bool {
        addToGoogle + addOnMac + createGoogleLists + updates + completions + deletions == 0
    }

    var lines: [String] {
        var lines: [String] = []
        if addToGoogle > 0 {
            lines.append(Self.count(addToGoogle,
                one: NSLocalizedString("Add 1 task to Google Tasks", comment: "First sync summary"),
                other: NSLocalizedString("Add %d tasks to Google Tasks", comment: "First sync summary")))
        }
        if addOnMac > 0 {
            lines.append(Self.count(addOnMac,
                one: NSLocalizedString("Add 1 reminder on this Mac", comment: "First sync summary"),
                other: NSLocalizedString("Add %d reminders on this Mac", comment: "First sync summary")))
        }
        if createGoogleLists > 0 {
            lines.append(Self.count(createGoogleLists,
                one: NSLocalizedString("Create 1 list in Google Tasks", comment: "First sync summary"),
                other: NSLocalizedString("Create %d lists in Google Tasks", comment: "First sync summary")))
        }
        if updates > 0 {
            lines.append(Self.count(updates,
                one: NSLocalizedString("Update 1 item", comment: "First sync summary"),
                other: NSLocalizedString("Update %d items", comment: "First sync summary")))
        }
        if completions > 0 {
            lines.append(Self.count(completions,
                one: NSLocalizedString("Mark 1 item as completed", comment: "First sync summary"),
                other: NSLocalizedString("Mark %d items as completed", comment: "First sync summary")))
        }
        if deletions > 0 {
            lines.append(Self.count(deletions,
                one: NSLocalizedString("Delete 1 item", comment: "First sync summary"),
                other: NSLocalizedString("Delete %d items", comment: "First sync summary")))
        }
        return lines
    }

    private static func count(_ value: Int, one: String, other: String) -> String {
        value == 1 ? one : String(format: other, value)
    }
}
