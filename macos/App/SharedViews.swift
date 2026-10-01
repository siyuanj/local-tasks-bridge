import SwiftUI

/// A red message with an icon, for errors from the engine or the system.
struct ErrorText: View {
    var message: String

    var body: some View {
        Label {
            Text(message).fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: "exclamationmark.triangle.fill").foregroundColor(.orange)
        }
        .foregroundColor(.primary)
        .textSelection(.enabled)
    }
}

/// A secondary note with an icon.
struct NoticeText: View {
    var message: String
    var systemImage = "info.circle"

    var body: some View {
        Label {
            Text(message).fixedSize(horizontal: false, vertical: true)
        } icon: {
            Image(systemName: systemImage)
        }
        .font(.callout)
        .foregroundColor(.secondary)
    }
}

/// One choice of a group, with a title and an explanation under it.
struct RadioOption: View {
    var title: String
    var detail: String?
    var isSelected: Bool
    var action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(alignment: .firstTextBaseline, spacing: 8) {
                Image(systemName: isSelected ? "largecircle.fill.circle" : "circle")
                    .foregroundColor(isSelected ? .accentColor : .secondary)
                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                    if let detail {
                        Text(detail)
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                }
                Spacer(minLength: 0)
            }
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .accessibilityAddTraits(isSelected ? [.isButton, .isSelected] : .isButton)
    }
}

/// Setup progress: one dot per step, with the step names underneath.
struct StepIndicator: View {
    var titles: [String]
    var current: Int

    var body: some View {
        HStack(alignment: .top, spacing: 0) {
            ForEach(Array(titles.enumerated()), id: \.offset) { index, title in
                VStack(spacing: 4) {
                    ZStack {
                        Circle()
                            .fill(index <= current ? Color.accentColor : Color.secondary.opacity(0.25))
                            .frame(width: 18, height: 18)
                        if index < current {
                            Image(systemName: "checkmark")
                                .font(.system(size: 9, weight: .bold))
                                .foregroundColor(.white)
                        } else {
                            Text(verbatim: "\(index + 1)")
                                .font(.system(size: 10, weight: .semibold))
                                .foregroundColor(index == current ? .white : .secondary)
                        }
                    }
                    Text(title)
                        .font(.caption2)
                        .foregroundColor(index == current ? .primary : .secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.8)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(String(
            format: NSLocalizedString("Step %d of %d: %@", comment: "Setup step indicator accessibility label"),
            current + 1, titles.count, titles.indices.contains(current) ? titles[current] : ""
        ))
    }
}

/// Two-way sync or Mac → Google only (`bidirectional`).
struct DirectionPicker: View {
    @Binding var bidirectional: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            RadioOption(
                title: NSLocalizedString("Two-way sync (recommended)", comment: "Sync direction"),
                detail: NSLocalizedString("Changes on this Mac and in Google Tasks both sync to the other side.", comment: "Sync direction detail"),
                isSelected: bidirectional
            ) { bidirectional = true }
            RadioOption(
                title: NSLocalizedString("Mac → Google only", comment: "Sync direction"),
                detail: NSLocalizedString("Reminders are copied to Google Tasks; changes made in Google Tasks are not copied back.", comment: "Sync direction detail"),
                isSelected: !bidirectional
            ) { bidirectional = false }
        }
    }
}

/// How often to sync: 1, 5, or 15 minutes (plus a custom value from the config).
/// Shorter choices than the shared sign-in's minimum are not offered with it.
struct IntervalPicker: View {
    @Binding var seconds: Int
    var sharedClient: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Picker(NSLocalizedString("Sync every", comment: "Sync interval picker label"), selection: selection) {
                ForEach(choices, id: \.self) { value in
                    Text(Self.label(for: value)).tag(value)
                }
            }
            .pickerStyle(.segmented)
            .fixedSize()
            Text(sharedClient
                ? NSLocalizedString("The shared sign-in has one daily Google quota for everyone who uses it, so every 5 minutes is recommended.", comment: "Sync interval note")
                : NSLocalizedString("Changes you make in Reminders also start a sync within a few seconds.", comment: "Sync interval note"))
                .font(.caption)
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }

    private var selection: Binding<Int> {
        Binding(
            get: { sharedClient ? max(seconds, SyncOptions.sharedClientMinimumInterval) : seconds },
            set: { seconds = $0 }
        )
    }

    private var choices: [Int] {
        let current = selection.wrappedValue
        let standard = SyncOptions.intervalChoices.filter { !sharedClient || $0 >= SyncOptions.sharedClientMinimumInterval }
        return standard.contains(current) ? standard : (standard + [current]).sorted()
    }

    static func label(for seconds: Int) -> String {
        if seconds % 60 == 0 {
            let minutes = seconds / 60
            return minutes == 1
                ? NSLocalizedString("1 minute", comment: "Sync interval")
                : String(format: NSLocalizedString("%d minutes", comment: "Sync interval"), minutes)
        }
        return String(format: NSLocalizedString("%d seconds", comment: "Sync interval"), seconds)
    }
}

/// System proxy, no proxy, or a custom HTTP proxy.
struct ProxyEditor: View {
    @Binding var choice: ProxyChoice

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            RadioOption(
                title: NSLocalizedString("Use the system proxy settings (recommended)", comment: "Proxy option"),
                detail: nil,
                isSelected: choice.mode == .system
            ) { choice.mode = .system }
            RadioOption(
                title: NSLocalizedString("Don’t use a proxy", comment: "Proxy option"),
                detail: nil,
                isSelected: choice.mode == .direct
            ) { choice.mode = .direct }
            RadioOption(
                title: NSLocalizedString("Use this proxy:", comment: "Proxy option"),
                detail: nil,
                isSelected: choice.mode == .custom
            ) { choice.mode = .custom }
            TextField(ProxyChoice.exampleURL, text: $choice.customURL)
                .textFieldStyle(.roundedBorder)
                .disableAutocorrection(true)
                .frame(maxWidth: 320)
                .padding(.leading, 24)
                .disabled(choice.mode != .custom)
            if choice.mode == .custom && !choice.customURL.isEmpty && !choice.isValid {
                Text(NSLocalizedString("Enter the proxy as http://host:port, for example http://127.0.0.1:7890.", comment: "Proxy validation"))
                    .font(.caption)
                    .foregroundColor(.red)
                    .padding(.leading, 24)
            }
            Text(NSLocalizedString("In mainland China, Google is usually reachable only through a local proxy app, for example http://127.0.0.1:7890.", comment: "Proxy note"))
                .font(.caption)
                .foregroundColor(.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
    }
}

/// Reminders lists to sync, with their Google Tasks counterparts.
struct ListPickerView: View {
    @ObservedObject var model: ListSelectionModel
    var onRetry: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            if model.loading && !model.loaded {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text(NSLocalizedString("Loading your lists…", comment: "List picker"))
                        .foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 120)
            } else if let message = model.errorMessage {
                ErrorText(message: message)
                Button(NSLocalizedString("Try Again", comment: "Button"), action: onRetry)
            } else {
                if let problem = model.googleProblem {
                    NoticeText(
                        message: String(
                            format: NSLocalizedString("Google Tasks lists couldn’t be loaded: %@", comment: "List picker; %@ is the reason"),
                            problem
                        ),
                        systemImage: "exclamationmark.triangle"
                    )
                }
                ScrollView {
                    VStack(alignment: .leading, spacing: 10) {
                        if model.rows.isEmpty {
                            Text(NSLocalizedString("There are no lists in Reminders yet.", comment: "List picker"))
                                .foregroundColor(.secondary)
                        }
                        ForEach(model.rows) { row in
                            listRow(row)
                        }
                        if !model.googleOnlyTitles.isEmpty {
                            Divider().padding(.vertical, 4)
                            Text(NSLocalizedString("Google Tasks lists without a matching Reminders list", comment: "List picker section"))
                                .font(.headline)
                            Text(NSLocalizedString("To sync one of these, create a Reminders list with the same name.", comment: "List picker section note"))
                                .font(.caption)
                                .foregroundColor(.secondary)
                            ForEach(model.googleOnlyTitles, id: \.self) { title in
                                HStack {
                                    Text(title)
                                    Spacer()
                                    if model.creatingTitle == title {
                                        ProgressView().controlSize(.small)
                                    }
                                    Button(NSLocalizedString("Create in Reminders", comment: "Button")) {
                                        Task { await model.createInReminders(title) }
                                    }
                                    .disabled(model.creatingTitle != nil)
                                }
                            }
                            if let problem = model.createProblem {
                                ErrorText(message: problem)
                            }
                        }
                    }
                    .padding(10)
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
                .frame(minHeight: 150)
                .background(Color(nsColor: .textBackgroundColor).opacity(0.6))
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.secondary.opacity(0.25)))
                if model.loading {
                    ProgressView().controlSize(.small)
                }
            }
        }
    }

    private func listRow(_ row: ListSelectionModel.Row) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Toggle(isOn: model.isSelected(row.title)) {
                VStack(alignment: .leading, spacing: 1) {
                    Text(row.title)
                    if !row.accounts.isEmpty {
                        Text(row.accounts.joined(separator: ", "))
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .toggleStyle(.checkbox)
            Spacer()
            matchLabel(row.match)
        }
    }

    @ViewBuilder
    private func matchLabel(_ match: ListSelectionModel.Row.Match) -> some View {
        switch match {
        case .google:
            Label(NSLocalizedString("Matches a Google Tasks list", comment: "List picker row status"), systemImage: "checkmark.circle")
                .font(.caption)
                .foregroundColor(.green)
        case .willBeCreated:
            Label(NSLocalizedString("Will be created in Google Tasks", comment: "List picker row status"), systemImage: "plus.circle")
                .font(.caption)
                .foregroundColor(.secondary)
        case .missingInReminders:
            Label(NSLocalizedString("Not found in Reminders", comment: "List picker row status"), systemImage: "questionmark.circle")
                .font(.caption)
                .foregroundColor(.orange)
        case .unknown:
            EmptyView()
        }
    }
}
