import EventKit
import Foundation

enum RemindersAuthorization: Equatable {
    case notDetermined
    case granted
    /// macOS 14+: the app may add reminders but not read them, which is not enough.
    case writeOnly
    case denied
    case restricted
}

enum RemindersAccessError: LocalizedError {
    case noReminderAccount

    var errorDescription: String? {
        NSLocalizedString("There is no Reminders account on this Mac to create the list in.", comment: "Error creating a Reminders list")
    }
}

/// The app's EventKit connection. The app owns the Reminders permission; the
/// engine's helpers run as its children and inherit it.
@MainActor
final class RemindersAccess {
    private(set) lazy var store = EKEventStore()
    private var changeObserver: NSObjectProtocol?

    static let privacySettingsURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Reminders")!

    var authorization: RemindersAuthorization {
        let status = EKEventStore.authorizationStatus(for: .reminder)
        switch status.rawValue {
        case EKAuthorizationStatus.notDetermined.rawValue: return .notDetermined
        case EKAuthorizationStatus.restricted.rawValue: return .restricted
        case EKAuthorizationStatus.denied.rawValue: return .denied
        // 3 is `.authorized` before macOS 14 and `.fullAccess` from macOS 14 on.
        case 3: return .granted
        // 4 is `.writeOnly` (macOS 14+).
        case 4: return .writeOnly
        default: return .denied
        }
    }

    /// Shows the system prompt if the user has not decided yet.
    func requestAccess() async throws -> Bool {
        if #available(macOS 14.0, *) {
            return try await store.requestFullAccessToReminders()
        }
        return try await store.requestAccess(to: .reminder)
    }

    /// Creates an empty list in the account that holds new reminders by default.
    func createList(named title: String) throws {
        let calendar = EKCalendar(for: .reminder, eventStore: store)
        calendar.title = title
        let source = store.defaultCalendarForNewReminders()?.source
            ?? store.sources.first { !$0.calendars(for: .reminder).isEmpty }
        guard let source else {
            throw RemindersAccessError.noReminderAccount
        }
        calendar.source = source
        try store.saveCalendar(calendar, commit: true)
    }

    var defaultListTitle: String? {
        guard authorization == .granted else {
            return nil
        }
        return store.defaultCalendarForNewReminders()?.title
    }

    /// Calls `handler` on the main queue whenever the Reminders database changes.
    func observeChanges(_ handler: @escaping () -> Void) {
        guard changeObserver == nil else {
            return
        }
        changeObserver = NotificationCenter.default.addObserver(
            forName: .EKEventStoreChanged,
            object: store,
            queue: .main
        ) { _ in
            handler()
        }
    }
}
