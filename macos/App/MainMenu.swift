import AppKit

/// The main menu. It is visible only while a window is open (the app is a
/// menu bar app otherwise), but it also provides the standard Edit shortcuts
/// for text fields and Close/Minimize for windows.
@MainActor
enum MainMenu {
    static func install(target: AppDelegate) {
        let mainMenu = NSMenu()

        let appMenu = NSMenu()
        appMenu.addItem(item(NSLocalizedString("About Local Tasks Bridge", comment: "Menu item"), #selector(AppDelegate.showAbout(_:)), target: target))
        appMenu.addItem(.separator())
        appMenu.addItem(item(NSLocalizedString("Settings…", comment: "Menu item"), #selector(AppDelegate.showSettingsWindow(_:)), key: ",", target: target))
        appMenu.addItem(.separator())
        appMenu.addItem(item(NSLocalizedString("Hide Local Tasks Bridge", comment: "Menu item"), #selector(NSApplication.hide(_:)), key: "h"))
        appMenu.addItem(item(NSLocalizedString("Quit Local Tasks Bridge", comment: "Menu item"), #selector(NSApplication.terminate(_:)), key: "q"))
        addSubmenu(appMenu, to: mainMenu)

        let editMenu = NSMenu(title: NSLocalizedString("Edit", comment: "Menu"))
        editMenu.addItem(item(NSLocalizedString("Undo", comment: "Menu item"), Selector(("undo:")), key: "z"))
        let redo = item(NSLocalizedString("Redo", comment: "Menu item"), Selector(("redo:")), key: "z")
        redo.keyEquivalentModifierMask = [.command, .shift]
        editMenu.addItem(redo)
        editMenu.addItem(.separator())
        editMenu.addItem(item(NSLocalizedString("Cut", comment: "Menu item"), #selector(NSText.cut(_:)), key: "x"))
        editMenu.addItem(item(NSLocalizedString("Copy", comment: "Menu item"), #selector(NSText.copy(_:)), key: "c"))
        editMenu.addItem(item(NSLocalizedString("Paste", comment: "Menu item"), #selector(NSText.paste(_:)), key: "v"))
        editMenu.addItem(item(NSLocalizedString("Select All", comment: "Menu item"), #selector(NSText.selectAll(_:)), key: "a"))
        addSubmenu(editMenu, to: mainMenu)

        let windowMenu = NSMenu(title: NSLocalizedString("Window", comment: "Menu"))
        windowMenu.addItem(item(NSLocalizedString("Minimize", comment: "Menu item"), #selector(NSWindow.performMiniaturize(_:)), key: "m"))
        windowMenu.addItem(item(NSLocalizedString("Close", comment: "Menu item"), #selector(NSWindow.performClose(_:)), key: "w"))
        addSubmenu(windowMenu, to: mainMenu)

        NSApp.mainMenu = mainMenu
        NSApp.windowsMenu = windowMenu
    }

    private static func item(_ title: String, _ action: Selector, key: String = "", target: AnyObject? = nil) -> NSMenuItem {
        let menuItem = NSMenuItem(title: title, action: action, keyEquivalent: key)
        menuItem.target = target
        return menuItem
    }

    private static func addSubmenu(_ submenu: NSMenu, to menu: NSMenu) {
        let holder = NSMenuItem()
        holder.submenu = submenu
        menu.addItem(holder)
    }
}
