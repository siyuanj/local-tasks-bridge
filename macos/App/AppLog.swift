import Foundation

/// The app's private log, ~/Library/Logs/LocalTasksBridge/app.log.
///
/// The directory is kept at 0700 and the file at 0600 because engine output can
/// contain reminder titles. The file rotates at 5 MiB, keeping one `.1` copy.
/// launchd also points the login item's stdout and stderr at this file; after a
/// rotation those descriptors are moved to the new file so nothing is lost.
final class AppLog: @unchecked Sendable {
    static let defaultMaxBytes: UInt64 = 5 * 1024 * 1024

    private let url: URL
    private let maxBytes: UInt64
    private let queue = DispatchQueue(label: "io.github.siyuanj.LocalTasksBridge.app-log")
    private var descriptor: Int32 = -1
    private let timestampFormatter = ISO8601DateFormatter()

    init(url: URL, maxBytes: UInt64 = AppLog.defaultMaxBytes) {
        self.url = url
        self.maxBytes = maxBytes
    }

    deinit {
        if descriptor >= 0 {
            close(descriptor)
        }
    }

    /// Appends one timestamped entry; multi-line messages keep the prefix on every line.
    func write(_ message: String) {
        let stamp = timestampFormatter.string(from: Date())
        let lines = message.split(separator: "\n", omittingEmptySubsequences: false)
        let text = lines.map { "[\(stamp)] \($0)" }.joined(separator: "\n") + "\n"
        queue.async { [self] in
            append(Data(text.utf8))
        }
    }

    /// Waits until everything written so far is on disk.
    func flush() {
        queue.sync {
            if descriptor >= 0 {
                fsync(descriptor)
            }
        }
    }

    private func append(_ data: Data) {
        guard openIfNeeded() else {
            return
        }
        var info = stat()
        if fstat(descriptor, &info) == 0, UInt64(info.st_size) + UInt64(data.count) > maxBytes {
            rotate(current: info)
            guard openIfNeeded() else {
                return
            }
        }
        data.withUnsafeBytes { buffer in
            guard let base = buffer.baseAddress else {
                return
            }
            var offset = 0
            while offset < buffer.count {
                let written = Darwin.write(descriptor, base + offset, buffer.count - offset)
                if written <= 0 {
                    if written < 0 && errno == EINTR {
                        continue
                    }
                    return
                }
                offset += written
            }
        }
    }

    private func openIfNeeded() -> Bool {
        if descriptor >= 0 {
            return true
        }
        let directory = url.deletingLastPathComponent()
        do {
            try FileManager.default.createDirectory(
                at: directory,
                withIntermediateDirectories: true,
                attributes: [.posixPermissions: 0o700]
            )
        } catch {
            return false
        }
        chmod(directory.path, 0o700)
        let fd = open(url.path, O_WRONLY | O_CREAT | O_APPEND | O_CLOEXEC, 0o600)
        guard fd >= 0 else {
            return false
        }
        // launchd may have created the file with its own default mode.
        fchmod(fd, 0o600)
        descriptor = fd
        return true
    }

    private func rotate(current info: stat) {
        let redirected = [STDOUT_FILENO, STDERR_FILENO].filter { standardDescriptor in
            var other = stat()
            return fstat(standardDescriptor, &other) == 0 && other.st_dev == info.st_dev && other.st_ino == info.st_ino
        }
        close(descriptor)
        descriptor = -1
        rename(url.path, url.path + ".1")
        guard openIfNeeded() else {
            return
        }
        for standardDescriptor in redirected {
            dup2(descriptor, standardDescriptor)
        }
    }
}
