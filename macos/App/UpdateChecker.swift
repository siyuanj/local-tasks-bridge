import AppKit

/// Check for Updates…: asks GitHub for the latest published release.
enum UpdateChecker {
    struct Release: Decodable {
        var tagName: String
        var htmlURL: URL?

        enum CodingKeys: String, CodingKey {
            case tagName = "tag_name"
            case htmlURL = "html_url"
        }
    }

    enum Outcome {
        case updateAvailable(version: String, page: URL)
        case upToDate
        /// 404: nothing published yet, or the repository is not public.
        case noPublishedRelease
        case failed(String)
    }

    @MainActor
    static func checkAndReport(proxy: String?) async {
        switch await check(proxy: proxy) {
        case .updateAvailable(let version, let page):
            let download = Alerts.confirm(
                title: String(format: NSLocalizedString("Local Tasks Bridge %@ is available", comment: "Update alert title; %@ is a version"), version),
                message: String(format: NSLocalizedString("You have version %@.", comment: "Update alert message; %@ is a version"), AppInfo.version),
                confirmTitle: NSLocalizedString("Download", comment: "Button")
            )
            if download {
                NSWorkspace.shared.open(page)
            }
        case .upToDate:
            Alerts.inform(
                title: NSLocalizedString("You’re up to date", comment: "Update alert title"),
                message: String(format: NSLocalizedString("Local Tasks Bridge %@ is the latest version.", comment: "Update alert message; %@ is a version"), AppInfo.version)
            )
        case .noPublishedRelease:
            Alerts.inform(
                title: NSLocalizedString("No release found", comment: "Update alert title"),
                message: NSLocalizedString("No release has been published on GitHub yet.", comment: "Update alert message")
            )
        case .failed(let reason):
            Alerts.inform(
                title: NSLocalizedString("Couldn’t check for updates", comment: "Update alert title"),
                message: reason
            )
        }
    }

    static func check(proxy: String?) async -> Outcome {
        var request = URLRequest(url: AppInfo.latestReleaseAPIURL, timeoutInterval: 20)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.setValue("LocalTasksBridge/\(AppInfo.version)", forHTTPHeaderField: "User-Agent")
        let session = URLSession(configuration: sessionConfiguration(proxy: proxy))
        defer { session.finishTasksAndInvalidate() }
        do {
            let (data, response) = try await session.data(for: request)
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 0
            switch statusCode {
            case 200:
                let release = try JSONDecoder().decode(Release.self, from: data)
                let latest = normalizedVersion(release.tagName)
                if isVersion(latest, newerThan: AppInfo.version) {
                    return .updateAvailable(version: latest, page: release.htmlURL ?? AppInfo.releasesURL)
                }
                return .upToDate
            case 404:
                return .noPublishedRelease
            case 403, 429:
                return .failed(NSLocalizedString("GitHub is limiting requests right now. Try again later.", comment: "Update check error"))
            default:
                return .failed(String(format: NSLocalizedString("GitHub answered with status %d.", comment: "Update check error"), statusCode))
            }
        } catch {
            return .failed(error.localizedDescription)
        }
    }

    static func normalizedVersion(_ tag: String) -> String {
        var version = tag.trimmingCharacters(in: .whitespaces)
        if version.hasPrefix("v") || version.hasPrefix("V") {
            version.removeFirst()
        }
        return version
    }

    /// Compares dotted numeric versions; anything after "-" or "+" is ignored.
    static func isVersion(_ candidate: String, newerThan current: String) -> Bool {
        func components(_ version: String) -> [Int] {
            let core = version.split(whereSeparator: { $0 == "-" || $0 == "+" }).first.map(String.init) ?? version
            return core.split(separator: ".").map { Int($0) ?? 0 }
        }
        let left = components(candidate)
        let right = components(current)
        for index in 0..<max(left.count, right.count) {
            let a = index < left.count ? left[index] : 0
            let b = index < right.count ? right[index] : 0
            if a != b {
                return a > b
            }
        }
        return false
    }

    /// Follows the app's proxy setting: system ("" or nil), direct ("none"), or http://host:port.
    static func sessionConfiguration(proxy: String?) -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        let setting = (proxy ?? "").trimmingCharacters(in: .whitespaces)
        if setting == "none" {
            configuration.connectionProxyDictionary = [
                kCFNetworkProxiesHTTPEnable as String: false,
                kCFNetworkProxiesHTTPSEnable as String: false,
            ]
        } else if let url = URL(string: setting), let host = url.host {
            let port = url.port ?? (url.scheme == "https" ? 443 : 80)
            configuration.connectionProxyDictionary = [
                kCFNetworkProxiesHTTPEnable as String: true,
                kCFNetworkProxiesHTTPProxy as String: host,
                kCFNetworkProxiesHTTPPort as String: port,
                kCFNetworkProxiesHTTPSEnable as String: true,
                kCFNetworkProxiesHTTPSProxy as String: host,
                kCFNetworkProxiesHTTPSPort as String: port,
            ]
        }
        return configuration
    }
}
