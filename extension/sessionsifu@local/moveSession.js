'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import Meta from 'gi://Meta';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import * as UiHelper from './ui/uiHelper.js';

import * as FileUtils from './utils/fileUtils.js';
import * as Log from './utils/log.js';
import * as DateUtils from './utils/dateUtils.js';
import { shellVersion } from './constants.js';

import {WindowTilingSupport} from './windowTilingSupport.js';
import {
    isValidWorkspaceIndex,
    isWindowUsable,
} from './windowSafety.js';
import {mayRestoreApplications} from './runtimeSafety.js';


export const MoveSession = class {

    constructor() {
        this._log = new Log.Log();

        this.sessionName = FileUtils.default_sessionName;
        this._defaultAppSystem = Shell.AppSystem.get_default();
        this._windowTracker = Shell.WindowTracker.get_default();

        this._cancelledWindows = new WeakSet();
        this._pendingMonitorWaits = new Map();
        this._pendingGeometryRestores = new Map();

    }

    _isWindowUsable(metaWindow) {
        return mayRestoreApplications() &&
            !this._cancelledWindows.has(metaWindow) && isWindowUsable(metaWindow);
    }

    cancelWindow(metaWindow) {
        if (!metaWindow)
            return;
        this._cancelledWindows.add(metaWindow);
        this._pendingMonitorWaits.get(metaWindow)?.(null);
        const pendingGeometry = this._pendingGeometryRestores.get(metaWindow);
        if (pendingGeometry) {
            GLib.Source.remove(pendingGeometry.sourceId);
            this._pendingGeometryRestores.delete(metaWindow);
            pendingGeometry.resolve(false);
        }
    }

    async moveWindows(sessionName) {
        if (!sessionName) {
            sessionName = this.sessionName;
        }

        const sessions_path = FileUtils.get_sessions_path();
        const session_file_path = GLib.build_filenamev([sessions_path, sessionName]);
        if (!GLib.file_test(session_file_path, GLib.FileTest.EXISTS)) {
            logError(new Error('Session file not found'));
            return;
        }

        this._log.info('Applying saved window layout');
        const session_file = Gio.File.new_for_path(session_file_path);
        let [success, contents] = session_file.load_contents(null);
        if (success) {
            let session_config = FileUtils.getJsonObj(contents);

            const session_config_objects = session_config.x_session_config_objects;
            if (!session_config_objects) {
                logError(new Error('Saved window details not found'));
                return;
            }

            // TODO Use global.get_window_actors(); / Meta.get_window_actors() / display.list_all_windows() instead and then call this.moveWindowByMetaWindow() and then can remove this.moveWindowsByShellApp()?
            await this.moveApps(session_config_objects);
        }

    }

    async moveApps(session_config_objects) {
        try {
            const running_apps = this._defaultAppSystem.get_running();
            for (const shellApp of running_apps) {
                await this.moveWindowsByShellApp(shellApp, session_config_objects);
            }
        } catch (error) {
            Log.Log.getDefault().error(error);
        }
    }

    async moveWindowsByShellApp(shellApp, saved_window_sessions) {
        try {
            const interestingWindows = this._getAutoMoveInterestingWindows(shellApp, saved_window_sessions);

            if (!interestingWindows.length) {
                return;
            }

            for (const interestingWindow of interestingWindows) {
                const metaWindow = interestingWindow.open_window;
                if (UiHelper.ignoreWindows(metaWindow) || !this._isWindowUsable(metaWindow))
                    continue;

                const saved_window_session = interestingWindow.saved_window_session;
                const title = metaWindow.get_title();
                const desktop_number = saved_window_session.desktop_number;

                try {
                    if (!await this._restoreWindowStates(metaWindow, saved_window_session))
                        continue;
                    if (!this._createEnoughWorkspace(desktop_number))
                        continue;

                    // Sticky windows don't need moving, in fact moving would unstick them
                    // See: https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/gnome-41/js/ui/windowManager.js#L1070
                    const is_sticky = saved_window_session.window_state.is_sticky;
                    if (is_sticky && metaWindow.is_on_all_workspaces()) {
                        this._log.debug(`The window '${shellApp.get_name()} - ${title}' is already sticky on workspace ${desktop_number}`);
                    } else {
                        this._log.debug(`Auto move ${shellApp.get_name()} - ${title} to workspace ${desktop_number} from ${metaWindow.get_workspace().index()}`);
                        if (!this._changeWorkspace(metaWindow, desktop_number))
                            continue;
                    }

                    // restore window state if necessary due to moving windows could lost window state
                    this._restoreWindowState(metaWindow, saved_window_session);

                } catch (e) {
                    // I just don't want one failure breaks the loop

                    this._log.error(e, `Failed to move window ${title} for ${shellApp.get_name()} automatically`);
                }
                saved_window_session.moved = true;
            }
        } catch (error) {
            this._log.error(error, shellApp ? shellApp.get_name() : 'This app may be closed.');
        }
    }

    // Inspired by https://github.com/Leleat/Tiling-Assistant/blob/main/tiling-assistant%40leleat-on-github/src/extension/resizeHandler.js
    _restoreTiling(metaWindow, saved_window_session) {
        if (!this._isWindowUsable(metaWindow))
            return false;
        WindowTilingSupport.prepareToTile(metaWindow, saved_window_session.window_tiling);
        return true;
    }

    /**
     * We need to move the window to the monitor it belongs before moving it to the workspace, because
     * the move itself could cause a workspace change if the window enters
     * the primary monitor
     *
     * @see https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/gnome-41/js/ui/workspace.js#L1497
     */
    async _restoreMonitor(metaWindow, saved_window_session) {
        if (!this._isWindowUsable(metaWindow))
            return null;
        const currentMonitorIndex = metaWindow.get_monitor();
        // -1 if the window has been recently unmanaged and does not have a monitor
        if (currentMonitorIndex === -1) {
            return null;
        }

        const shellApp = this._windowTracker.get_window_app(metaWindow);
        const monitorCount = global.display.get_n_monitors();
        const reportedPrimaryMonitor = global.display.get_primary_monitor();
        const primaryMonitorIndex = reportedPrimaryMonitor >= 0 &&
            reportedPrimaryMonitor < monitorCount
            ? reportedPrimaryMonitor
            : currentMonitorIndex;
        const savedMonitorIndex = saved_window_session.monitor_number;

        let toMonitorIndex = null;
        if (savedMonitorIndex === undefined) {
            if (currentMonitorIndex !== primaryMonitorIndex) {
                this._log.info(`${shellApp?.get_name()} - ${metaWindow.get_title()} doesn't have the monitor number data, click the save open windows button to save it. Moving it to the primary monitor ${primaryMonitorIndex} from ${currentMonitorIndex}`);
                toMonitorIndex = primaryMonitorIndex;
            }
        }
        // It's possible to save the unmanaged windows
        else if (savedMonitorIndex === -1) {
            if (currentMonitorIndex !== primaryMonitorIndex) {
                this._log.info(`${shellApp?.get_name()} - ${metaWindow.get_title()} is unmanaged when saving, moving it to the primary monitor ${primaryMonitorIndex} from ${currentMonitorIndex}`);
                toMonitorIndex = primaryMonitorIndex;
            }
        }
        else if (saved_window_session.is_on_primary_monitor) {
            if (currentMonitorIndex !== primaryMonitorIndex) {
                this._log.info(`Moving ${shellApp?.get_name()} - ${metaWindow.get_title()} to the primary monitor ${primaryMonitorIndex} from ${currentMonitorIndex}`);
                toMonitorIndex = primaryMonitorIndex;
            }
        }
        // It causes Gnome shell to crash, if we move a monitor to a non-existing monitor on X11 and Wayland!
        // We move all windows on non-existing monitors to the primary monitor
        else if (!Number.isInteger(savedMonitorIndex) || savedMonitorIndex < 0 ||
            savedMonitorIndex >= monitorCount) {
            if (currentMonitorIndex !== primaryMonitorIndex) {
                this._log.info(`Monitor ${savedMonitorIndex} doesn't exist. Moving ${shellApp?.get_name()} - ${metaWindow.get_title()} to the primary monitor ${primaryMonitorIndex} from ${currentMonitorIndex}`);
                toMonitorIndex = primaryMonitorIndex;
            }
        }
        else if (currentMonitorIndex !== savedMonitorIndex) {
            this._log.debug(`Moving ${shellApp?.get_name()} - ${metaWindow.get_title()} to monitor ${savedMonitorIndex} from ${currentMonitorIndex}`);
            // So, you don't want to unplug the monitor, which we are moving the window in to, at this moment. 🤣
            toMonitorIndex = savedMonitorIndex;
        }

        if (toMonitorIndex != null) {
            return new Promise(resolve => {
                // MetaWindow.move_to_monitor() can no longer be assumed to have updated the monitor on return, as under wayland
                // Wait for the monitor change to take effect
                // See: https://gitlab.gnome.org/GNOME/gnome-shell/-/commit/1cb01ec5b139da136cac665fc705e4ddd1d926a1
                let displayId = 0;
                let unmanagingId = 0;
                let timeoutId = 0;
                let finished = false;
                const finish = result => {
                    if (finished)
                        return;
                    finished = true;
                    if (displayId)
                        global.display.disconnect(displayId);
                    if (unmanagingId) {
                        try {
                            metaWindow.disconnect(unmanagingId);
                        } catch (_error) {
                        }
                    }
                    if (timeoutId)
                        GLib.Source.remove(timeoutId);
                    this._pendingMonitorWaits.delete(metaWindow);
                    resolve(result);
                };
                displayId = global.display.connect('window-entered-monitor',
                    (dsp, num, w) => {
                        if (w === metaWindow && num === toMonitorIndex)
                            finish(this._isWindowUsable(metaWindow) ? metaWindow : null);
                    });
                unmanagingId = metaWindow.connect('unmanaging', () => finish(null));
                timeoutId = GLib.timeout_add(GLib.PRIORITY_LOW, 1000, () => {
                    timeoutId = 0;
                    finish(this._isWindowUsable(metaWindow) ? metaWindow : null);
                    return GLib.SOURCE_REMOVE;
                });
                this._pendingMonitorWaits.set(metaWindow, finish);
                try {
                    metaWindow.move_to_monitor(toMonitorIndex);
                } catch (error) {
                    finish(null);
                    this._log.error(error, 'Could not move a window to its saved monitor');
                }
            });
        }

        return Promise.resolve(metaWindow);
    }

    async createEnoughWorkspaceAndMoveWindows(metaWindow, saved_window_sessions) {
        try {
            if (UiHelper.ignoreWindows(metaWindow) || !this._isWindowUsable(metaWindow))
                return null;

            const saved_window_session = this._getOneMatchedSavedWindow(metaWindow, saved_window_sessions);
            if (!saved_window_session) {
                return null;
            }

            if (saved_window_session.moved) {
                return await this._restoreWindowStates(metaWindow, saved_window_session)
                    ? saved_window_session
                    : null;
            }

            if (!await this._restoreMonitor(metaWindow, saved_window_session) ||
                !this._isWindowUsable(metaWindow))
                return null;

            const desktop_number = saved_window_session.desktop_number;
            if (!this._createEnoughWorkspace(desktop_number))
                return null;
            if (this._log.isDebug()) {
                const shellApp = this._windowTracker.get_window_app(metaWindow);
                this._log.debug(`CEWM: Moving ${shellApp?.get_name()} - ${metaWindow.get_title()} to workspace ${desktop_number} from ${metaWindow.get_workspace().index()}`);
            }
            if (!this._changeWorkspace(metaWindow, desktop_number))
                return null;
            return saved_window_session;
        } catch (error) {
            this._log.error(error, metaWindow ? metaWindow.get_title() : 'This window may be destroyed.');
        }
    }

    async moveWindowByMetaWindow(metaWindow, saved_window_sessions) {
        try {
            if (UiHelper.ignoreWindows(metaWindow) || !this._isWindowUsable(metaWindow))
                return false;

            const saved_window_session = this._getOneMatchedSavedWindow(metaWindow, saved_window_sessions);
            if (!saved_window_session) {
                return false;
            }

            if (saved_window_session.moved) {
                return await this._restoreWindowStates(metaWindow, saved_window_session);
            } else {
                if (!await this._restoreWindowStates(metaWindow, saved_window_session))
                    return false;
                const desktop_number = saved_window_session.desktop_number;
                // It's necessary to move window again to ensure an app goes to its own workspace.
                // In a sort of situation, some apps probably just don't want to move when call createEnoughWorkspaceAndMoveWindows() from `Meta.Display::window-created` signal.
                if (!this._createEnoughWorkspace(desktop_number))
                    return false;
                const shellApp = this._windowTracker.get_window_app(metaWindow);
                const is_sticky = saved_window_session.window_state.is_sticky;
                if (is_sticky && metaWindow.is_on_all_workspaces()) {
                    this._log.debug(`The window '${shellApp.get_name()} - ${metaWindow.get_title()}' is already sticky on workspace ${desktop_number}`);
                } else {
                    this._log.debug(`MWMW: Moving ${shellApp?.get_name()} - ${metaWindow.get_title()} to workspace ${desktop_number} from ${metaWindow.get_workspace().index()}`);
                    if (!this._changeWorkspace(metaWindow, desktop_number))
                        return false;
                }
                // The window state get lost during moving the window, and we need to restore window state again.
                this._restoreWindowState(metaWindow, saved_window_session);

                saved_window_session.moved = true;
                return true;
            }
        } catch (error) {
            this._log.error(error, metaWindow ? metaWindow.get_title() : 'This window may be destroyed.');
            return false;
        }
    }

    _changeWorkspace(metaWindow, desktop_number) {
        if (!this._isWindowUsable(metaWindow) || !isValidWorkspaceIndex(desktop_number) ||
            desktop_number >= global.workspace_manager.n_workspaces)
            return false;
        const currentFocusedWindow = global.display.get_focus_window();
        metaWindow.change_workspace_by_index(desktop_number, false);
        if (currentFocusedWindow === metaWindow && !Main.layoutManager._inOverview) {
            this._log.debug(`Following the previous focused window ${metaWindow.get_title()}`);
            Main.activateWindow(metaWindow, DateUtils.get_current_time());
        }
        return true;
    }

    _getOneMatchedSavedWindow(metaWindow, saved_window_sessions) {
        saved_window_sessions = saved_window_sessions.filter(saved_window_session => {
            return !saved_window_session.moved;
        });

        for (const saved_window_session of saved_window_sessions) {
            const title = metaWindow.get_title();
            const windows_count = saved_window_session.windows_count;
            const open_window_workspace_index = metaWindow.get_workspace().index();
            const desktop_number = saved_window_session.desktop_number;

            if (windows_count === 1 || title === saved_window_session.window_title) {
                if (open_window_workspace_index === desktop_number) {
                    if (this._log.isDebug()) {
                        const shellApp = this._windowTracker.get_window_app(metaWindow);
                        this._log.debug(`The window '${shellApp?.get_name()} - ${title}' is already on workspace ${desktop_number}`);
                    }
                    saved_window_session.moved = true;
                }

                return saved_window_session;
            }
        }
        return null;
    }

    /**
     * Restore varies window states, including:
     * * window states, such as Always on Top, Always on Visible Workspace
     * * window geometry
     * * window tiling
     *
     * @see https://help.gnome.org/users/gnome-help/stable/shell-windows-maximize.html.en
     */
    async _restoreWindowStates(metaWindow, saved_window_session, markToMoved = false) {
        try {
            if (UiHelper.ignoreWindows(metaWindow) || !this._isWindowUsable(metaWindow))
                return false;

            if (!await this._restoreMonitor(metaWindow, saved_window_session) ||
                !this._restoreWindowState(metaWindow, saved_window_session) ||
                !await this._restoreWindowGeometry(metaWindow, saved_window_session) ||
                !this._restoreTiling(metaWindow, saved_window_session))
                return false;
            if (markToMoved) {
                saved_window_session.moved = true;
            }
            return true;
        } catch (error) {
            this._log.error(error, metaWindow ? metaWindow.get_title() : 'This window may be destroyed.');
            return false;
        }
    }

    _restoreWindowState(metaWindow, saved_window_session) {
        if (!this._isWindowUsable(metaWindow) || !saved_window_session?.window_state)
            return false;
        // window state
        const window_state = saved_window_session.window_state;
        if (window_state.is_above) {
            if (!metaWindow.is_above()) {
                this._log.debug(`Making ${metaWindow.get_title()} above`);
                metaWindow.make_above();
            }
        }
        if (window_state.is_sticky) {
            if (!metaWindow.is_on_all_workspaces()) {
                this._log.debug(`Making ${metaWindow.get_title()} sticky`);
                metaWindow.stick();
            }
        }

        const savedMetaMaximized = window_state.meta_maximized;
        if (shellVersion >= 49) {
            // Maximize a window to take up all of the space
            if (savedMetaMaximized) {
                const currentMetaMaximized = metaWindow.is_maximized();
                if (!currentMetaMaximized) {
                    this._log.debug(`Maximizing ${metaWindow.get_title()}`);
                    metaWindow.maximize();
                }
            }
        } else {
            // Maximize a window to take up all of the space
            if (savedMetaMaximized === Meta.MaximizeFlags.BOTH) {
                const currentMetaMaximized = metaWindow.get_maximized();
                if (currentMetaMaximized !== Meta.MaximizeFlags.BOTH) {
                    this._log.debug(`Maximizing ${metaWindow.get_title()}`);
                    metaWindow.maximize(savedMetaMaximized);
                }
            }
        }

        return this._isWindowUsable(metaWindow);
    }

    /**
     * @see https://help.gnome.org/users/gnome-help/stable/shell-windows-maximize.html.en
     */
    async _restoreWindowGeometry(metaWindow, saved_window_session) {
        if (!this._isWindowUsable(metaWindow) || !saved_window_session?.window_state)
            return false;
        let delay = false;
        const window_state = saved_window_session.window_state;
        const savedMetaMaximized = window_state.meta_maximized;
        // A maximized window already occupies its target work area. Mutter can
        // reject or crash on move_resize_frame() while maximization is being
        // applied, so geometry is restored only for non-maximized windows.
        if (savedMetaMaximized)
            return this._isWindowUsable(metaWindow);
        if (shellVersion >= 49) {
            if (!savedMetaMaximized) {
                // It can't be resized if current window is in maximum mode, including vertically maximization along the left and right sides of the screen
                const currentMetaMaximized = metaWindow.is_maximized();
                if (currentMetaMaximized) {
                    metaWindow.set_unmaximize_flags(Meta.MaximizeFlags.BOTH);
                    metaWindow.unmaximize();
                    delay = true;
                }
            }
        } else {
            if (savedMetaMaximized !== Meta.MaximizeFlags.BOTH) {
                // It can't be resized if current window is in maximum mode, including vertically maximization along the left and right sides of the screen
                const currentMetaMaximized = metaWindow.get_maximized();
                if (currentMetaMaximized) {
                    metaWindow.unmaximize(currentMetaMaximized);
                    if (currentMetaMaximized !== Meta.MaximizeFlags.BOTH) {
                        delay = true;
                    }
                }
            }
        }

        if (delay) {
            // Upstream fix: https://github.com/nlpsuge/gnome-shell-extension-another-window-session-manager/issues/25
            // TODO Note that this is not a perfect solution to address the above issue.
            return new Promise(resolve => {
                const previous = this._pendingGeometryRestores.get(metaWindow);
                if (previous) {
                    GLib.Source.remove(previous.sourceId);
                    previous.resolve(false);
                }
                const sourceId = GLib.timeout_add(GLib.PRIORITY_LOW, 500, () => {
                    this._pendingGeometryRestores.delete(metaWindow);
                    resolve(this._moveResizeFrame(metaWindow, saved_window_session));
                    return GLib.SOURCE_REMOVE;
                });
                this._pendingGeometryRestores.set(metaWindow, {sourceId, resolve});
            });
        } else {
            return this._moveResizeFrame(metaWindow, saved_window_session);
        }
    }

    _moveResizeFrame(metaWindow, saved_window_session) {
        if (!this._isWindowUsable(metaWindow))
            return false;
        const window_position = saved_window_session.window_position;
        if (window_position?.provider === 'Meta') {
            const to_x = window_position.x_offset;
            const to_y = window_position.y_offset;
            const to_width = window_position.width;
            const to_height = window_position.height;

            if (![to_x, to_y, to_width, to_height].every(Number.isFinite) ||
                to_width <= 0 || to_height <= 0)
                return false;

            const currentMonitor = metaWindow.get_monitor();
            if (currentMonitor < 0 || currentMonitor >= global.display.get_n_monitors())
                return false;
            const rectWorkArea = metaWindow.get_work_area_for_monitor(currentMonitor);
            if (!rectWorkArea || !this._isWindowUsable(metaWindow))
                return false;

            // For more info about the below issue see also: https://github.com/Leleat/Tiling-Assistant/blob/1e4176a9a7037ee5dd0612e4c9f9dbe45d4e67cf/tiling-assistant%40leleat-on-github/src/extension/tilingWindowManager.js#L186-L199

            // Move first. Just in case that some apps can only be resized but not moved after `metaWindow.move_resize_frame()`
            metaWindow.move_frame(true, to_x, to_y);
            metaWindow.move_resize_frame(
                // Set `user_op` to true to fix an issue that a window does not move to negative x (like -176),
                // in which case if `user_op` is false it will move to (0,Y,W,H).
                true, // user_op
                to_x,

                // Fix the below issue:
                // No rect to clip to found!
                // No rect whose size to clamp to found!

                // Window might flies outside of the screen when resizing due to
                // the y axis of the saved window is less than the one of work area, see:
                // https://gitlab.gnome.org/GNOME/mutter/-/issues/1461
                // https://gitlab.gnome.org/GNOME/mutter/-/issues/1499

                Math.max(to_y, rectWorkArea.y),
                to_width,
                to_height);
            return this._isWindowUsable(metaWindow);
        }
        return true;
    }

    _getAutoMoveInterestingWindows(shellApp, saved_window_sessions) {
        saved_window_sessions = saved_window_sessions.filter(saved_window_session => {
            return !saved_window_session.moved;
        });

        if (!saved_window_sessions.length) {
            return [];
        }

        let autoMoveInterestingWindows = [];
        const open_windows = shellApp.get_windows();
        saved_window_sessions.forEach(saved_window_session => {
            open_windows.forEach(open_window => {
                if (open_window.get_wm_class() != saved_window_session.wm_class) {
                    return;
                }

                const title = open_window.get_title();
                const windows_count = saved_window_session.windows_count;
                const open_window_workspace_index = open_window.get_workspace().index();
                const desktop_number = saved_window_session.desktop_number;

                if (windows_count === 1 || title === saved_window_session.window_title) {
                    if (open_window_workspace_index === desktop_number) {
                        this._log.debug(`The window '${title}' is already on workspace ${desktop_number} for ${shellApp.get_name()}`);
                    }
                    autoMoveInterestingWindows.push({
                        open_window: open_window,
                        saved_window_session: saved_window_session
                    });
                }

            });

        });

        return autoMoveInterestingWindows;
    }

    _createEnoughWorkspace(workspaceNumber) {
        if (!isValidWorkspaceIndex(workspaceNumber))
            return false;
        let workspaceManager = global.workspace_manager;

        // We have enough workspace now, return
        if (workspaceManager.n_workspaces >= workspaceNumber + 1) {
            return true;
        }

        // First, make all existing workspaces persistent
        for (let i = 0; i <= workspaceManager.n_workspaces - 1; i++) {
            let workspace = workspaceManager.get_workspace_by_index(i);
            if (!workspace._keepAliveId) {
                workspace._keepAliveId = true;
            }
        }

        // Second, make all newly added workspaces persistent, so they can not removed due to it does not contain any windows
        // And keep the last one non-persistent
        for (let i = workspaceManager.n_workspaces; i <= workspaceNumber; i++) {
            workspaceManager.append_new_workspace(false, 0);
            workspaceManager.get_workspace_by_index(i)._keepAliveId = true;
        }
        return workspaceManager.n_workspaces >= workspaceNumber + 1;
    }

    destroy() {
        if (this._defaultAppSystem) {
            this._defaultAppSystem = null;
        }

        if (this._log) {
            this._log.destroy();
            this._log = null;
        }

        if (this._windowTracker) {
            this._windowTracker = null;
        }

        for (const finish of this._pendingMonitorWaits.values())
            finish(null);
        this._pendingMonitorWaits.clear();
        for (const [metaWindow, pending] of this._pendingGeometryRestores) {
            GLib.Source.remove(pending.sourceId);
            pending.resolve(false);
            this._cancelledWindows.add(metaWindow);
        }
        this._pendingGeometryRestores.clear();

    }

}
