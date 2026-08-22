'use strict';

import GObject from 'gi://GObject';
import St from 'gi://St';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import Meta from 'gi://Meta';
import Clutter from 'gi://Clutter';


import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';

import * as MoveSession from './moveSession.js';
import * as RestoreSession from './restoreSession.js';
import * as Constants from './constants.js';

import * as FileUtils from './utils/fileUtils.js';
import * as SessionItem from './ui/sessionItem.js';
import * as SearchSessionItem from './ui/searchSessionItem.js';
import * as PopupMenuButtonItems from './ui/popupMenuButtonItems.js';
import * as IconFinder from './utils/iconFinder.js';
import {PrefsUtils} from './utils/prefsUtils.js';
import * as Log from './utils/log.js';
import * as Signal from './utils/signal.js';
import {mayRestoreApplications} from './runtimeSafety.js';
import {recallActivity} from './recallActivity.js';


export const NEW_WINDOW_SETTLE_DELAY_MS = 750;


export const AwsIndicator = GObject.registerClass(
class AwsIndicator extends PanelMenu.Button {

    _init() {
        super._init(0.0, "SessionSifu");

        this._isDestroyed = false;

        this._windowTracker = Shell.WindowTracker.get_default();

        this._settings = PrefsUtils.getSettings();
        this._log = new Log.Log();
        this._signal = new Signal.Signal();

        this._itemIndex = 0;

        this._sessions_path = FileUtils.sessions_path;

        this.monitors = [];

        this._sessionsMenuSection = null;

        // TODO backup path

        // Use the SessionSifu yin-yang mark so the panel identity matches the app.
        this._iconBox = new St.BoxLayout({
            style_class: 'panel-status-menu-box',
        });
        this._mainIcon = new St.Icon({
            gicon: IconFinder.find('sessionsifu-symbolic.svg'),
            style_class: 'popup-menu-icon'
        });
        this._savingIcon = new St.Icon({
            icon_name: 'media-record-symbolic',
            style_class: 'popup-menu-icon',
            visible: recallActivity.saving,
        });
        this._iconBox.add_child(this._mainIcon);
        this._iconBox.add_child(this._savingIcon);
        this.add_child(this._iconBox);
        this._recallActivityChangedId = recallActivity.connect(
            'changed', (_activity, saving) => this._updateRecallActivity(saving));

        this._createMenu();

        this.menu.connect('open-state-changed', this._onOpenStateChanged.bind(this));

        // Open menu
        // this.menu.open(true);
        // Toggle menu
        // this.menu.toggle();

        // Remove all activate signals on all menu items, so the panel menu can always stay open
        // See: PopupMenu#itemActivated() => this.menu._getTopMenu().close
        this.menu.itemActivated = function(animate) {};

        this._moveSession = new MoveSession.MoveSession();

        this._metaWindowConnectIds = [];
        this._display = global.display;
        this._displayId = this._display.connect('window-created', this._windowCreated.bind(this));

        this._closingWindows = new WeakSet();
        this._restoringWindows = new WeakMap();
        this._restoredWindows = new WeakSet();
        this._windowSettleWaits = new Map();

    }

    _waitForWindowSettle(metaWindow) {
        if (this._isDestroyed || this._closingWindows.has(metaWindow) ||
            !mayRestoreApplications())
            return Promise.resolve(false);

        const pending = this._windowSettleWaits.get(metaWindow);
        if (pending)
            return pending.promise;

        let finish;
        const promise = new Promise(resolve => {
            finish = resolve;
        });
        const sourceId = GLib.timeout_add(
            GLib.PRIORITY_LOW,
            NEW_WINDOW_SETTLE_DELAY_MS,
            () => {
                this._windowSettleWaits.delete(metaWindow);
                finish(!this._isDestroyed && !this._closingWindows.has(metaWindow) &&
                    mayRestoreApplications());
                return GLib.SOURCE_REMOVE;
            });
        this._windowSettleWaits.set(metaWindow, {sourceId, finish, promise});
        return promise;
    }

    _cancelWindowSettle(metaWindow) {
        const pending = this._windowSettleWaits.get(metaWindow);
        if (!pending)
            return;
        GLib.Source.remove(pending.sourceId);
        this._windowSettleWaits.delete(metaWindow);
        pending.finish(false);
    }

    async _restoreWindowOnce(metaWindow, savedWindowSessions) {
        if (this._isDestroyed || this._closingWindows.has(metaWindow))
            return false;
        if (this._restoredWindows.has(metaWindow))
            return true;
        const activeRestore = this._restoringWindows.get(metaWindow);
        if (activeRestore)
            return activeRestore;

        const operation = (async () => {
            try {
                if (!await this._waitForWindowSettle(metaWindow))
                    return false;
                const restored = await this._moveSession.moveWindowByMetaWindow(
                    metaWindow, savedWindowSessions);
                if (restored)
                    this._restoredWindows.add(metaWindow);
                return restored;
            } catch (error) {
                this._log.error(error, 'Could not restore a newly created window');
                return false;
            } finally {
                this._restoringWindows.delete(metaWindow);
            }
        })();
        this._restoringWindows.set(metaWindow, operation);
        return operation;
    }

    // TODO Move this method and related code to a single .js file
    async _windowCreated(display, metaWindow, userData) {
        let metaWindowActor = metaWindow.get_compositor_private();
        // https://github.com/paperwm/PaperWM/blob/10215f57e8b34a044e10b7407cac8fac4b93bbbc/tiling.js#L2120
        // https://gjs-docs.gnome.org/meta8~8_api/meta.windowactor#signal-first-frame
        let firstFrameId = metaWindowActor?.connect('first-frame', async () => {
            if (this._isDestroyed) {
                metaWindowActor.disconnect(firstFrameId);
                return;
            }

            if (this._closingWindows.has(metaWindow)) {
                return;
            }

            const shellApp = this._windowTracker.get_window_app(metaWindow);
            if (!shellApp) {
                return;
            }

            // NOTE: The title of a dialog (for example a close warning dialog, like gnome-terminal) attached to a window is ''
            this._log.debug(`window-created -> first-frame: ${shellApp.get_name()} -> ${metaWindow.get_title()}`);

            const restoringApps = RestoreSession.restoreSessionObject.restoringApps;
            if (!restoringApps)
                return;
            let shellAppData = restoringApps.get(shellApp);
            if (!shellAppData) {
                shellAppData = restoringApps.get(metaWindow.get_pid());
            }
            if (!shellAppData) {
                return;
            }

            const saved_window_sessions = shellAppData.saved_window_sessions;

            if (await this._restoreWindowOnce(metaWindow, saved_window_sessions) &&
                !this._isDestroyed && firstFrameId) {
                metaWindowActor.disconnect(firstFrameId);
                firstFrameId = 0;
            }
        }) ?? 0;

        let shownId = metaWindow.connect('shown', async () => {
            if (this._isDestroyed) {
                metaWindow.disconnect(shownId);
                return;
            }

            if (this._closingWindows.has(metaWindow)) {
                return;
            }

            const shellApp = this._windowTracker.get_window_app(metaWindow);
            if (!shellApp) {
                return;
            }

            // NOTE: The title of a dialog (for example a close warning dialog, like gnome-terminal) attached to a window is ''
            this._log.debug(`window-created -> shown: ${shellApp.get_name()} -> ${metaWindow.get_title()}`);

            const restoringApps = RestoreSession.restoreSessionObject.restoringApps;
            if (!restoringApps)
                return;
            let shellAppData = restoringApps.get(shellApp);
            if (!shellAppData) {
                shellAppData = restoringApps.get(metaWindow.get_pid());
            }
            if (!shellAppData) {
                return;
            }

            const saved_window_sessions = shellAppData.saved_window_sessions;

            if (await this._restoreWindowOnce(metaWindow, saved_window_sessions) &&
                !this._isDestroyed && shownId) {
                metaWindow.disconnect(shownId);
                shownId = 0;
            }
        });


        /*
        We have to disconnect firstFrameId within the unmanaging signal of metaWindow.

        If we do this in `destroy()`, the metaWindowActor instance has been disposed, disconnecting signals from
        metaWindowActor gets many errors when disable extension: Object .MetaWindowActorWayland (0x55fae658e3d0), has been already disposed — impossible to access it. This might be caused by the object having been destroyed from C code using something such as destroy(), dispose(), or remove() vfuncs.
        I don't know why 😢. TODO

        But metaWindow is not disposed in `destroy()`, so we can disconnect signals from it there.
        */
        let unmanagingId = metaWindow.connect('unmanaging', () => {
            this._closingWindows.add(metaWindow);
            this._cancelWindowSettle(metaWindow);
            this._moveSession.cancelWindow(metaWindow);
            // Fix ../gobject/gsignal.c:2732: instance '0x55629xxxxxx' has no handler with id '11000' when disable this extension right after restore apps
            this._signal.disconnectSafely(metaWindowActor, firstFrameId);
        });

        // The window title might be changing multiple times while the app is starting.
        // For some apps, such as Visual Studio Code, when it's starting, the first title is `Visual Studio Code`,
        // the second could be `indicator.js - gnome-shell-extension-sessionsifu - Visual Studio Code`.
        // In the above instance, `notify::title` catches the second.
        let titleChangedId = metaWindow.connect('notify::title', async () => {
            if (this._isDestroyed) {
                metaWindow.disconnect(titleChangedId);
                return;
            }

            if (this._closingWindows.has(metaWindow)) {
                return;
            }

            const shellApp = this._windowTracker.get_window_app(metaWindow);
            if (!shellApp) {
                return;
            }

            // NOTE: The title of a dialog (for example a close warning dialog, like gnome-terminal) attached to a window is ''
            this._log.debug(`window-created -> title changed: ${shellApp.get_name()} -> ${metaWindow.get_title()}`);

            const restoringApps = RestoreSession.restoreSessionObject.restoringApps;
            if (!restoringApps)
                return;
            let shellAppData = restoringApps.get(shellApp);
            if (!shellAppData) {
                shellAppData = restoringApps.get(metaWindow.get_pid());
            }
            if (!shellAppData) {
                return;
            }

            const saved_window_sessions = shellAppData.saved_window_sessions;

            if (await this._restoreWindowOnce(metaWindow, saved_window_sessions) &&
                !this._isDestroyed && titleChangedId) {
                metaWindow.disconnect(titleChangedId);
                titleChangedId = 0;
            }
        });

        this._metaWindowConnectIds.push([metaWindow, shownId]);
        this._metaWindowConnectIds.push([metaWindow, unmanagingId]);
        this._metaWindowConnectIds.push([metaWindow, titleChangedId]);
    }

    _onOpenStateChanged(menu, state) {
        if (state) {
            this._searchSessionItem.reset();
            this._searchSessionItem._clearIcon.hide();
            this._searchSessionItem._entry.grab_key_focus();
        }
        super._onOpenStateChanged(menu, state);
    }

    _createMenu() {
        this._addButtonItems();

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem(), this._itemIndex++);

        this._searchSessionItem = new SearchSessionItem.SearchSessionItem();
        const searchEntryText = this._searchSessionItem._entry.get_clutter_text()
        searchEntryText.connect('text-changed', this._onSearch.bind(this));
        this._searchSessionItem._filterAutoRestoreSwitch.connect('notify::state', this._onAutoRestoreSwitchChanged.bind(this));

        this.menu.addMenuItem(this._searchSessionItem, this._itemIndex++);

        this._addScrollableSessionsMenuSection();
        this._addSessionItems().catch(error => {
            this._log.error(error, 'Error adding session items while creating indicator menu');
        });

        this._addSessionFolderMonitor();
        this._settings.connect('changed::debugging-mode', () => {
            this._addSessionItems().catch(error => {
                this._log.error(error, 'Error reloading session items while debugging-mode was changed');
            });
        });

        this.menu.addMenuItem(new PopupMenu.PopupSeparatorMenuItem());
        this._recallMenuItem = new PopupMenu.PopupSubMenuMenuItem('');
        const pauseFor = seconds => {
            this._settings.set_int64(
                'recall-pause-until', Math.floor(Date.now() / 1000) + seconds);
        };
        this._recallMenuItem.menu.addAction('Resume capture', () => {
            this._settings.set_int64('recall-pause-until', 0);
            this._settings.set_boolean('recall-enabled', true);
        });
        this._recallMenuItem.menu.addAction('Pause for 15 minutes', () => pauseFor(15 * 60));
        this._recallMenuItem.menu.addAction('Pause for 1 hour', () => pauseFor(60 * 60));
        this._recallMenuItem.menu.addAction('Pause until tomorrow', () => {
            const tomorrow = new Date();
            tomorrow.setHours(24, 0, 0, 0);
            this._settings.set_int64('recall-pause-until', Math.floor(tomorrow.getTime() / 1000));
        });
        this._recallMenuItem.menu.addAction('Pause indefinitely', () => {
            this._settings.set_int64('recall-pause-until', -1);
        });
        this._recallMenuItem.menu.addAction('Turn Recall off', () => {
            this._settings.set_boolean('recall-enabled', false);
        });
        this._recallMenuItem.menu.addAction('Recall settings…', () => {
            try {
                Gio.Subprocess.new([FileUtils.getManagerExecutable()], Gio.SubprocessFlags.NONE);
            } catch (error) {
                this._log.error(error, 'Could not open Privacy Recall settings');
            }
        });
        this.menu.addMenuItem(this._recallMenuItem);
        this.menu.addAction('Browse Recall Snapshots…', () => {
            try {
                Gio.Subprocess.new(
                    [FileUtils.getManagerExecutable(), '--recall-search'],
                    Gio.SubprocessFlags.NONE);
            } catch (error) {
                this._log.error(error, 'Could not open Privacy Recall search');
            }
        });
        this._recallChangedId = this._settings.connect(
            'changed::recall-enabled', () => this._updateRecallItem());
        this._recallPauseChangedId = this._settings.connect(
            'changed::recall-pause-until', () => this._updateRecallItem());
        this._updateRecallItem();
        this.menu.addAction('Open SessionSifu…', () => {
            try {
                Gio.Subprocess.new([FileUtils.getManagerExecutable()], Gio.SubprocessFlags.NONE);
            } catch (error) {
                this._log.error(error, 'Could not open SessionSifu');
            }
        });
        this.menu.addAction('Turn Off SessionSifu', () => {
            GLib.idle_add(GLib.PRIORITY_DEFAULT_IDLE, () => {
                try {
                    Gio.Subprocess.new(
                        ['gnome-extensions', 'disable', 'sessionsifu@local'],
                        Gio.SubprocessFlags.NONE);
                } catch (error) {
                    this._log.error(error, 'Could not turn off SessionSifu');
                }
                return GLib.SOURCE_REMOVE;
            });
        });
    }

    _updateRecallItem() {
        if (!this._recallMenuItem)
            return;
        const pausedUntil = this._settings.get_int64('recall-pause-until');
        const paused = pausedUntil < 0 || pausedUntil > Math.floor(Date.now() / 1000);
        this._recallMenuItem.label.set_text(
            recallActivity.saving
                ? 'Privacy Recall: Saving…'
                : this._settings.get_boolean('recall-enabled')
                ? paused
                    ? 'Privacy Recall: Paused'
                    : 'Privacy Recall: Active'
                : 'Privacy Recall: Off — Open settings');
    }

    _updateRecallActivity(saving) {
        if (this._isDestroyed)
            return;
        this._savingIcon.visible = saving;
        this.accessible_name = saving
            ? 'SessionSifu — saving Privacy Recall'
            : 'SessionSifu';
        this._updateRecallItem();
    }

    _addScrollableSessionsMenuSection() {
        this._sessionsMenuSection = new PopupMenu.PopupMenuSection();
        this._scrollableSessionsMenuSection = new PopupMenu.PopupMenuSection();
        let scrollView = new St.ScrollView({
            style_class: 'session-menu-section',
            overlay_scrollbars: true
        });

        // Clutter.Container was removed from Gnome 46, see:
        // https://gjs.guide/extensions/upgrading/gnome-shell-46.html
        scrollView[Clutter.Container ? 'add_actor' : 'set_child'](this._sessionsMenuSection.actor);
        this._scrollableSessionsMenuSection.actor.add_child(scrollView);

        this.menu.addMenuItem(this._scrollableSessionsMenuSection);
    }

    _addButtonItems() {
        this._popupMenuButtonItems = new PopupMenuButtonItems.PopupMenuButtonItems();
        const buttonItems = this._popupMenuButtonItems.buttonItems;
        buttonItems.forEach(item => {
            this.menu.addMenuItem(item, this._itemIndex++);
        });

    }

    async _addSessionItems() {
        if (!GLib.file_test(this._sessions_path, GLib.FileTest.EXISTS)) {
            // TODO Empty session
            this._log.info(`${this._sessions_path} not found! It's harmless, please save some windows in the panel menu to create it automatically.`);
            this._sessionsMenuSection.removeAll();
            return;
        }

        this._log.debug('List all sessions to add session items');

        let sessionFileInfos = [];
        await FileUtils.listAllSessions(null, false, (file, info) => {
            // We have an interest in regular and text files

            const file_type = info.get_file_type();
            if (file_type !== Gio.FileType.REGULAR) {
                this._log.debug(`${file.get_path()} (file type is ${file_type}) is not a regular file, skipping`);
                return;
            }
            const content_type = info.get_content_type();
            if (content_type !== 'text/plain') {
                this._log.debug(`${file.get_path()} (content type is ${content_type}) is not a text file, skipping`);
                return;
            }

            // Skip the `Recently Closed Session` file since it has been added to the session list already.
            if (file.equal(FileUtils.recently_closed_session_file)) {
                return;
            }

            this._log.debug(`Processing ${file.get_path()}`);
            sessionFileInfos.push({
                info: info,
                file: file
            });

        }).catch(e => {
            this._log.error(e, 'Error listing all sessions')
        });

        // Sort by modification time: https://gjs-docs.gnome.org/gio20~2.0/gio.fileenumerator
        // The latest on the top, if a file has no modification time put it on the bottom
        sessionFileInfos.sort((sessionFileInfo1, sessionFileInfo2) => {
            const info1 = sessionFileInfo1.info;
            let modification_date_time1 = info1.get_modification_date_time();
            const info2 = sessionFileInfo2.info;
            let modification_date_time2 = info2.get_modification_date_time();

            if (!modification_date_time1 && !modification_date_time2) {
                return 0;
            }

            if (!modification_date_time1 && modification_date_time2) {
                return 1;
            }

            if (modification_date_time1 && !modification_date_time2) {
                return -1;
            }

            // https://gjs-docs.gnome.org/glib20~2.66.1/glib.datetime#function-compare
            // -1, 0 or 1 if dt1 is less than, equal to or greater than dt2.
            return modification_date_time2.compare(modification_date_time1);
        });

        this._sessionsMenuSection.removeAll();

        let info = null;
        try {
            info = FileUtils.recently_closed_session_file.query_info(
                [Gio.FILE_ATTRIBUTE_STANDARD_NAME,
                    Gio.FILE_ATTRIBUTE_TIME_MODIFIED].join(','),
                Gio.FileQueryInfoFlags.NONE,
                null);
        } catch (ignored) {}

        // Recently Closed Session always on the top
        let item = new SessionItem.SessionItem(info, FileUtils.recently_closed_session_file, this);
        this._sessionsMenuSection.addMenuItem(item, this._itemIndex++);

        for (const sessionFileInfo of sessionFileInfos) {
            const info = sessionFileInfo.info;
            const file = sessionFileInfo.file;
            let item = new SessionItem.SessionItem(info, file, this);
            this._sessionsMenuSection.addMenuItem(item, this._itemIndex++);
        }

    }

    /**
     * monitor files changes, recreate items when necessary.
     *
     */
    _addSessionFolderMonitor() {
        const sessionPathFile = Gio.File.new_for_path(this._sessions_path);
        this._monitor_directory(sessionPathFile);

        // Moving a directory on the same filesystem doesn’t move its contents, so we
        // monitor each parent directory because I want to receive the `changed` when they are moved
        let parent = sessionPathFile.get_parent();
        // If parent is null, then it represents the root directory of the file system
        while (parent) {
            if (parent.get_path() === `${FileUtils.user_config}`) {
                break;
            }
            this._monitor_directory(parent);
            parent = parent.get_parent();
        }

    }

    _monitor_directory(directory) {
        const monitor = directory.monitor_directory(
            Gio.FileMonitorFlags.WATCH_MOUNTS |
            Gio.FileMonitorFlags.WATCH_MOVES, null);
        monitor.connect('changed', this._sessionChanged.bind(this));
        this.monitors.push(monitor);
    }

    // https://gjs-docs.gnome.org/gio20~2.66p/gio.filemonitor#signal-changed
    // Looks like the document is wrong ...
    _sessionChanged(monitor, fileMonitored, otherFile, eventType) {
        const pathMonitored = fileMonitored.get_path();
        const otherFilePath = otherFile?.get_path();
        this._log.debug(`Session changed, readd all session items from ${this._sessions_path}. ${pathMonitored} changed. other_file: ${otherFilePath}. Event type: ${eventType}`);

        // Ignore CHANGED and CREATED events, since in both cases
        // we'll get a CHANGES_DONE_HINT event when done.
        if (eventType === Gio.FileMonitorEvent.CHANGED ||
            eventType === Gio.FileMonitorEvent.CREATED) {
                return;
        }

        // The eventType is Gio.FileMonitorEvent.RENAMED while modify the content of a text file,
        // so otherFile is the correct file we need to read.
        // The doc said:
        // If using Gio.FileMonitorFlags.WATCH_MOVES on a directory monitor, and
        // the information is available (and if supported by the backend),
        // event_type may be Gio.FileMonitorEvent.RENAMED,
        // Gio.FileMonitorEvent.MOVED_IN or Gio.FileMonitorEvent.MOVED_OUT.
        if (eventType === Gio.FileMonitorEvent.RENAMED) {
            fileMonitored = otherFile;
        }

        // Ignore temporary files generated by Gio
        if (fileMonitored.get_basename().startsWith('.goutputstream-')) {
            return;
        }

        let info = null;
        try {
            info = fileMonitored.query_info(
                [Gio.FILE_ATTRIBUTE_STANDARD_TYPE,
                    Gio.FILE_ATTRIBUTE_STANDARD_CONTENT_TYPE].join(','),
                Gio.FileQueryInfoFlags.NONE,
                null);
        } catch (ignored) {}

        // Ignore none regular and text files
        if (info) {
            const file_type = info.get_file_type();
            const content_type = info.get_content_type();
            if (!(file_type === Gio.FileType.REGULAR &&
                  content_type === 'text/plain') &&
                    // Parent folders could be changed
                    !this._sessions_path.startsWith(pathMonitored)) {
                return;
            }
        }

        // It probably is a problem when there are large amount session files,
        // say thousands of them, but who creates that much?
        //
        // Can use Gio.FileMonitorEvent to modify the results
        // of this._sessionsMenuSection._getMenuItems() when the performance
        // is a problem to be resolved, it's a more complex implement.
        this._addSessionItems().catch(error => {
            this._log.error(error, 'Error adding session items while session was changed');
        });
    }

    _onAutoRestoreSwitchChanged() {
        this._search();
        this._filterAutoRestore();
    }

    _filterAutoRestore() {
        const switchState = this._searchSessionItem._filterAutoRestoreSwitch.state;
        if (switchState) {
            const menuItems = this._sessionsMenuSection._getMenuItems();
            for (const menuItem of menuItems) {
                const sessionName = menuItem._filename;
                if (menuItem.actor.visible) {
                    const visible = sessionName == this._settings.get_string(Constants.PREFS_SETTING_AUTORESTORE_SESSIONS);
                    menuItem.actor.visible = visible;
                }
            }
        }
    }

    _onSearch() {
        this._search();
        this._filterAutoRestore();
    }

    _search() {
        this._searchSessionItem._clearIcon.show();

        let searchText = this._searchSessionItem._entry.text;
        if (!(searchText && searchText.trim())) {
            // when search entry is empty, hide clear button
            if (!searchText) {
                this._searchSessionItem._clearIcon.hide();
            }
            const menuItems = this._sessionsMenuSection._getMenuItems();
            for (const menuItem of menuItems) {
                menuItem.actor.visible = true;
            }
        } else {
            const menuItems = this._sessionsMenuSection._getMenuItems();
            searchText = searchText.toLowerCase().trim();
            for (const menuItem of menuItems) {
                const sessionName = menuItem._filename.toLowerCase();
                menuItem.actor.visible = sessionName.includes(searchText);
            }
        }
    }

    destroy() {
        this._isDestroyed = true;

        if (this._recallChangedId) {
            this._settings.disconnect(this._recallChangedId);
            this._recallChangedId = 0;
        }
        if (this._recallPauseChangedId) {
            this._settings.disconnect(this._recallPauseChangedId);
            this._recallPauseChangedId = 0;
        }
        if (this._recallActivityChangedId) {
            recallActivity.disconnect(this._recallActivityChangedId);
            this._recallActivityChangedId = 0;
        }

        if (this._windowSettleWaits) {
            for (const [metaWindow, pending] of this._windowSettleWaits) {
                GLib.Source.remove(pending.sourceId);
                pending.finish(false);
                this._windowSettleWaits.delete(metaWindow);
            }
            this._windowSettleWaits = null;
        }

        if (this.monitors) {
            this.monitors.forEach ((monitor) => {
                monitor.cancel();
                monitor = null;
            });
            this.monitors = [];
        }

        if (this._sessions_path) {
            this._sessions_path = null;
        }

        if (this._metaWindowConnectIds) {
            for (let [obj, signalId] of this._metaWindowConnectIds) {
                // Fix ../gobject/gsignal.c:2732: instance '0x55629xxxxxx' has no handler with id '11000' when disable this extension right after restore apps
                this._signal.disconnectSafely(obj, signalId);
            }
            this._metaWindowConnectIds = null;
        }

        if (this._displayId) {
            this._display.disconnect(this._displayId);
            this._displayId = 0;
        }

        if (this._moveSession) {
            this._moveSession.destroy();
            this._moveSession = null;
        }

        if (this._log) {
            this._log.destroy();
            this._log = null;
        }

        super.destroy();

    }

});
