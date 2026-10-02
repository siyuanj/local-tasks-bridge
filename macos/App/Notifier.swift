import Foundation
import UserNotifications

/// Posts the engine's `notification` events as user notifications. While the
/// event stream is on, the engine leaves notifications to the app.
@MainActor
final class Notifier: NSObject, UNUserNotificationCenterDelegate {
    /// Called with the notification's kind when the user clicks it.
    var onOpen: ((Kind) -> Void)?

    enum Kind: String {
        case info
        case problem
        case approval
    }

    private var center: UNUserNotificationCenter { UNUserNotificationCenter.current() }

    func activate() {
        center.delegate = self
    }

    @discardableResult
    func requestAuthorization() async -> Bool {
        (try? await center.requestAuthorization(options: [.alert, .sound])) ?? false
    }

    func authorizationStatus() async -> UNAuthorizationStatus {
        await center.notificationSettings().authorizationStatus
    }

    /// Each kind replaces the previous notification of the same kind, so
    /// Notification Center does not fill up.
    func post(title: String, message: String, kind: Kind) {
        let content = UNMutableNotificationContent()
        content.title = title.isEmpty ? AppInfo.productName : title
        content.body = message
        content.userInfo = ["kind": kind.rawValue]
        if kind != .info {
            content.sound = .default
        }
        center.add(UNNotificationRequest(identifier: "ltb.\(kind.rawValue)", content: content, trigger: nil))
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification,
        withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void
    ) {
        completionHandler([.banner, .list, .sound])
    }

    nonisolated func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse,
        withCompletionHandler completionHandler: @escaping () -> Void
    ) {
        let kind = Kind(rawValue: response.notification.request.content.userInfo["kind"] as? String ?? "") ?? .info
        DispatchQueue.main.async {
            self.onOpen?(kind)
        }
        completionHandler()
    }
}
