import SwiftUI

/// Review Pending Changes: the deletions and completions held back by the
/// safety limit, grouped by what will happen and by list.
@MainActor
final class ApprovalsModel: ObservableObject {
    struct ListGroup: Identifiable, Equatable {
        var list: String
        var titles: [String]
        var id: String { list }
    }

    struct OperationGroup: Identifiable, Equatable {
        var label: String
        var lists: [ListGroup]
        var count: Int
        var id: String { label }
    }

    let app: AppModel
    var close: () -> Void = {}

    @Published private(set) var loading = false
    @Published private(set) var working = false
    @Published private(set) var response: ApprovalsResponse?
    @Published private(set) var groups: [OperationGroup] = []
    @Published private(set) var errorMessage: String?
    @Published private(set) var notice: String?
    @Published private(set) var appliedCount: Int?

    private var task: Task<Void, Never>?

    init(app: AppModel) {
        self.app = app
    }

    var pending: Bool { response?.pending == true && !(response?.destructiveFingerprint ?? "").isEmpty }

    /// Computes the current plan (network and Reminders), so it can take a moment.
    func load(notice: String? = nil) {
        guard let client = app.client else {
            return
        }
        task?.cancel()
        loading = true
        errorMessage = nil
        appliedCount = nil
        self.notice = notice
        task = Task {
            do {
                let result = try await client.pendingApprovals()
                response = result
                groups = Self.group(result.items ?? [])
            } catch let error as EngineError where error.isCancellation {
                // The window closed or a reload replaced this one.
            } catch {
                errorMessage = (error as? EngineError)?.message ?? error.localizedDescription
            }
            loading = false
        }
    }

    func apply() {
        guard let fingerprint = response?.destructiveFingerprint, let client = app.client else {
            return
        }
        let count = response?.destructiveCount ?? 0
        perform {
            try await client.applyApprovals(fingerprint: fingerprint)
            self.appliedCount = count
            self.response = nil
            self.groups = []
        }
    }

    func hold() {
        guard let fingerprint = response?.destructiveFingerprint, let client = app.client else {
            return
        }
        perform {
            try await client.holdApprovals(fingerprint: fingerprint)
            self.close()
        }
    }

    func cancelWork() {
        task?.cancel()
    }

    private func perform(_ work: @escaping () async throws -> Void) {
        task?.cancel()
        working = true
        errorMessage = nil
        task = Task {
            do {
                try await work()
            } catch let error as EngineError where error.code == EngineErrorCode.planChanged {
                working = false
                load(notice: error.message)
                return
            } catch let error as EngineError where error.isCancellation {
                // Nothing to report.
            } catch {
                errorMessage = (error as? EngineError)?.message ?? error.localizedDescription
            }
            working = false
            app.scheduleStatusRefresh()
        }
    }

    static func group(_ items: [ApprovalItem]) -> [OperationGroup] {
        var labels: [String] = []
        var byLabel: [String: [ApprovalItem]] = [:]
        for item in items {
            let label = item.label ?? item.operation ?? ""
            if byLabel[label] == nil {
                labels.append(label)
            }
            byLabel[label, default: []].append(item)
        }
        return labels.map { label in
            let entries = byLabel[label] ?? []
            var listOrder: [String] = []
            var titles: [String: [String]] = [:]
            for entry in entries {
                let list = entry.list ?? ""
                if titles[list] == nil {
                    listOrder.append(list)
                }
                titles[list, default: []].append(entry.title ?? "")
            }
            return OperationGroup(
                label: label,
                lists: listOrder.map { ListGroup(list: $0, titles: titles[$0] ?? []) },
                count: entries.count
            )
        }
    }
}

struct ApprovalsView: View {
    @ObservedObject var model: ApprovalsModel

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text(NSLocalizedString("Review Pending Changes", comment: "Window title")).font(.title2).bold()
            if model.loading {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(NSLocalizedString("Checking what needs your approval…", comment: "Approvals progress"))
                        .foregroundColor(.secondary)
                }
                Spacer()
            } else if let count = model.appliedCount {
                Label(
                    count == 1
                        ? NSLocalizedString("1 change was applied.", comment: "Approvals result")
                        : String(format: NSLocalizedString("%d changes were applied.", comment: "Approvals result"), count),
                    systemImage: "checkmark.circle.fill"
                )
                .foregroundColor(.green)
                Spacer()
                closeButton
            } else if model.pending, let response = model.response {
                pendingContent(response)
            } else if model.errorMessage == nil {
                Label(NSLocalizedString("Nothing needs your approval right now.", comment: "Approvals empty"), systemImage: "checkmark.circle")
                Spacer()
                closeButton
            }
            if let message = model.errorMessage {
                ErrorText(message: message)
                HStack {
                    Spacer()
                    Button(NSLocalizedString("Try Again", comment: "Button")) { model.load() }
                }
            }
        }
        .padding(20)
        .frame(minWidth: 520, minHeight: 440)
        .onAppear { model.load() }
    }

    private var closeButton: some View {
        HStack {
            Spacer()
            Button(NSLocalizedString("Close", comment: "Button")) { model.close() }
                .keyboardShortcut(.defaultAction)
        }
    }

    @ViewBuilder
    private func pendingContent(_ response: ApprovalsResponse) -> some View {
        Text(NSLocalizedString("One sync would delete or complete more items than your safety limit allows, so these changes are on hold. Nothing below has been changed yet, and everything else keeps syncing.", comment: "Approvals explanation"))
            .fixedSize(horizontal: false, vertical: true)
        if let notice = model.notice {
            NoticeText(message: notice)
        }
        Text(summary(response))
            .font(.headline)
        List {
            ForEach(model.groups) { group in
                Section(header: Text(verbatim: "\(group.label) (\(group.count))")) {
                    ForEach(group.lists) { list in
                        VStack(alignment: .leading, spacing: 2) {
                            Text(list.list.isEmpty ? NSLocalizedString("Unnamed list", comment: "Approvals") : list.list)
                                .font(.subheadline)
                                .foregroundColor(.secondary)
                            ForEach(Array(list.titles.enumerated()), id: \.offset) { _, title in
                                Text(verbatim: "• " + (title.isEmpty ? "—" : title))
                            }
                        }
                        .padding(.vertical, 2)
                    }
                }
            }
        }
        .listStyle(.inset(alternatesRowBackgrounds: false))
        HStack {
            if model.working {
                ProgressView().controlSize(.small)
            }
            Spacer()
            Button(NSLocalizedString("Keep On Hold", comment: "Button")) { model.hold() }
                .disabled(model.working)
            Button(applyTitle(response)) { model.apply() }
                .keyboardShortcut(.defaultAction)
                .disabled(model.working)
        }
    }

    private func summary(_ response: ApprovalsResponse) -> String {
        let count = response.destructiveCount ?? model.groups.reduce(0) { $0 + $1.count }
        let percent = Int(((response.ratio ?? 0) * 100).rounded())
        return String(
            format: NSLocalizedString("%d changes on hold (%d%% of %d synced items)", comment: "Approvals summary: count, percentage, population"),
            count, percent, response.population ?? 0
        )
    }

    private func applyTitle(_ response: ApprovalsResponse) -> String {
        let count = response.destructiveCount ?? 0
        return count == 1
            ? NSLocalizedString("Apply 1 Change", comment: "Button")
            : String(format: NSLocalizedString("Apply %d Changes", comment: "Button"), count)
    }
}
