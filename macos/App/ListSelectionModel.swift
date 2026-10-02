import SwiftUI

/// The list picker shared by setup and Settings: Reminders lists with their
/// Google Tasks counterparts, and Google lists that have no Reminders list.
///
/// `include_lists` holds titles, so lists with the same title in different
/// accounts are one row and sync together.
@MainActor
final class ListSelectionModel: ObservableObject {
    struct Row: Identifiable, Equatable {
        enum Match: Equatable {
            case google
            case willBeCreated
            /// Google lists could not be read, so the match is unknown.
            case unknown
            /// Selected in the settings but no longer present in Reminders.
            case missingInReminders
        }

        var title: String
        var accounts: [String]
        var match: Match
        var id: String { title }
    }

    @Published private(set) var rows: [Row] = []
    @Published private(set) var googleOnlyTitles: [String] = []
    @Published var selected: Set<String> = []
    @Published private(set) var loading = false
    @Published private(set) var loaded = false
    @Published private(set) var errorMessage: String?
    @Published private(set) var errorCode: String?
    /// Set when Reminders lists loaded but Google lists did not.
    @Published private(set) var googleProblem: String?
    @Published private(set) var creatingTitle: String?
    @Published private(set) var createProblem: String?

    private let app: AppModel

    init(app: AppModel) {
        self.app = app
    }

    var selectedTitles: [String] {
        rows.map(\.title).filter { selected.contains($0) }
    }

    func isSelected(_ title: String) -> Binding<Bool> {
        Binding(
            get: { self.selected.contains(title) },
            set: { isOn in
                if isOn {
                    self.selected.insert(title)
                } else {
                    self.selected.remove(title)
                }
            }
        )
    }

    /// Loads both sides. `preselect` replaces the selection; nil keeps it.
    func load(preselect: [String]? = nil) async {
        guard let client = app.client else {
            return
        }
        loading = true
        errorMessage = nil
        errorCode = nil
        googleProblem = nil
        defer {
            loading = false
        }

        let response: ListsResponse
        do {
            response = try await client.lists(includeGoogle: true)
        } catch let error as EngineError where error.code == EngineErrorCode.network
            || error.code == EngineErrorCode.authRequired
            || error.code == EngineErrorCode.oauthClientMissing {
            googleProblem = error.message
            do {
                response = try await client.lists(includeGoogle: false)
            } catch {
                fail(error)
                return
            }
        } catch {
            fail(error)
            return
        }

        if let preselect {
            selected = Set(preselect)
        }
        apply(response)
        loaded = true
    }

    /// Creates an empty Reminders list for a Google Tasks list, then reloads.
    func createInReminders(_ title: String) async {
        creatingTitle = title
        createProblem = nil
        do {
            try app.reminders.createList(named: title)
            selected.insert(title)
            await load()
        } catch {
            createProblem = error.localizedDescription
        }
        creatingTitle = nil
    }

    private func apply(_ response: ListsResponse) {
        let googleTitles = response.google.map { Set($0.map(\.title)) }
        var accountsByTitle: [String: [String]] = [:]
        var order: [String] = []
        for list in response.apple ?? [] {
            if accountsByTitle[list.title] == nil {
                order.append(list.title)
                accountsByTitle[list.title] = []
            }
            let account = list.accountTitle ?? ""
            if !account.isEmpty, !accountsByTitle[list.title, default: []].contains(account) {
                accountsByTitle[list.title, default: []].append(account)
            }
        }

        var newRows = order.map { title -> Row in
            let match: Row.Match
            if let googleTitles {
                match = googleTitles.contains(title) ? .google : .willBeCreated
            } else {
                match = .unknown
            }
            return Row(title: title, accounts: accountsByTitle[title] ?? [], match: match)
        }
        let present = Set(order)
        for title in selected.sorted() where !present.contains(title) {
            newRows.append(Row(title: title, accounts: [], match: .missingInReminders))
        }
        rows = newRows
        var googleOnly: [String] = []
        for list in response.google ?? [] where !present.contains(list.title) && !googleOnly.contains(list.title) {
            googleOnly.append(list.title)
        }
        googleOnlyTitles = googleOnly
    }

    private func fail(_ error: Error) {
        let engineError = error as? EngineError
        errorCode = engineError?.code
        errorMessage = engineError?.message ?? error.localizedDescription
    }
}
