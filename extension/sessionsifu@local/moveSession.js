'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import Meta from 'gi://Meta';

import * as UiHelper from './ui/uiHelper.js';

import * as FileUtils from './utils/fileUtils.js';
import * as Log from './utils/log.js';
import { shellVersion } from './constants.js';

import {WindowTilingSupport} from './windowTilingSupport.js';
import {
    clampWindowGeometry,
    isValidWorkspaceIndex,
    isWindowUsable,
} from './windowSafety.js';
import {layoutSafety, mayRestoreLayout, mayRestoreApplications} from './runtimeSafety.js';
import {WINDOW_RESTORE_INTERVAL_MS} from './restoreSafety.js';
import {compositorOperations} from './compositorOperations.js';


export const MoveSession = class {

    constructor() {
        this._log = new Log.Log();

        this.sessionName = FileUtils.default_sessionName;
        this._defaultAppSystem = Shell.AppSystem.get_default();
        this._windowTracker = Shell.WindowTracker.get_default();

        this._cancelledWindows = new WeakSet();
        this._pendingMonitorWaits = new Map();
        this._pendingGeometryRestores = new Map();
        this._pendingPacingWaits = new Map();

    }

    _isWindowUsable(metaWindow) {
        return !this._destroyed && mayRestoreLayout() &&
            !this._cancelledWindows.has(metaWindow) && isWindowUsable(metaWindow);
    }

    _layoutGuard(isCurrent = () => true) {
        const generation = layoutSafety.generation;
        return () => !this._destroyed && mayRestoreLayout(generation) && isCurrent();
    }

    _canMove(metaWindow, isCurrent = () => true) {
        return isCurrent() && this._isWindowUsable(metaWindow);
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
        const contents = await new Promise((resolve, reject) => {
            session_file.load_contents_async(null, (source, result) => {
                try {
                    const [ok, bytes] = source.load_contents_finish(result);
                    resolve(ok ? bytes : null);
                } catch (error) { reject(error); }
            });
        });
        if (contents && !this._destroyed) {
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

    moveWindowsByShellApp(shellApp, saved_window_sessions, beforeMove = () => {}, isCurrent = () => true) {
        const mayMove = this._layoutGuard(isCurrent);
        return compositorOperations.run(
            () => {
                beforeMove();
                return this._moveWindowsByShellApp(shellApp, saved_window_sessions, mayMove);
            },
            mayMove);
    }

    async _moveWindowsByShellApp(shellApp, saved_window_sessions, isCurrent = () => true) {
        try {
            const interestingWindows = this._getAutoMoveInterestingWindows(shellApp, saved_window_sessions);

            if (!interestingWindows.length) {
                return false;
            }

            let restoredAny = false;
            for (const interestingWindow of interestingWindows) {
                const metaWindow = interestingWindow.open_window;
                if (!this._canMove(metaWindow, isCurrent) || UiHelper.ignoreWindows(metaWindow))
                    continue;

                const saved_window_session = interestingWindow.saved_window_session;
                if (saved_window_session.moved)
                    continue;
                const title = metaWindow.get_title();
                const desktop_number = saved_window_session.desktop_number;

                try {
                    if (!await this._restoreWindowStates(metaWindow, saved_window_session, false, isCurrent) ||
                        !this._canMove(metaWindow, isCurrent))
                        continue;
                    if (!this._createEnoughWorkspace(desktop_number, isCurrent))
                        continue;

                    // Sticky windows don't need moving, in fact moving would unstick them
                    // See: https://gitlab.gnome.org/GNOME/gnome-shell/-/blob/gnome-41/js/ui/windowManager.js#L1070
                    const is_sticky = saved_window_session.window_state.is_sticky;
                    if (is_sticky && metaWindow.is_on_all_workspaces()) {
                        this._log.debug(`The window '${shellApp.get_name()} - ${title}' is already sticky on workspace ${desktop_number}`);
                    } else {
                        this._log.debug(`Auto move ${shellApp.get_name()} - ${title} to workspace ${desktop_number} from ${metaWindow.get_workspace().index()}`);
                        if (!this._changeWorkspace(metaWindow, desktop_number, isCurrent))
                            continue;
                    }

                } catch (e) {
                    // I just don't want one failure breaks the loop

                    this._log?.error(e, `Failed to move window ${title} for ${shellApp.get_name()} automatically`);
                    continue;
                }
                if (!this._canMove(metaWindow, isCurrent))
                    return restoredAny;
                saved_window_session.moved = true;
                restoredAny = true;
                if (!await this._waitForCompositor())
                    return restoredAny;
            }
            return restoredAny;
        } catch (error) {
            this._log.error(error, shellApp ? shellApp.get_name() : 'This app may be closed.');
            return false;
        }
    }

    // Inspired by https://github.com/Leleat/Tiling-Assistant/blob/main/tiling-assistant%40leleat-on-github/src/extension/resizeHandler.js
    _restoreTiling(metaWindow, saved_window_session, isCurrent = () => true) {
        if (!this._canMove(metaWindow, isCurrent))
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
    async _restoreMonitor(metaWindow, saved_window_session, isCurrent = () => true) {
        if (!this._canMove(metaWindow, isCurrent))
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
        let savedMonitorIndex = saved_window_session.monitor_number;
        const savedGeometry = saved_window_session.monitor_geometry;
        if (!saved_window_session.is_on_primary_monitor && savedGeometry &&
            Number.isFinite(savedGeometry.width) && savedGeometry.width > 0 &&
            Number.isFinite(savedGeometry.height) && savedGeometry.height > 0) {
            let bestIndex = -1;
            let bestScore = Number.POSITIVE_INFINITY;
            const savedAspect = savedGeometry.width / savedGeometry.height;
            for (let index = 0; index < monitorCount; index++) {
                let geometry;
                try {
                    geometry = global.display.get_monitor_geometry(index);
                } catch (_error) {
                    continue;
                }
                if (!geometry || geometry.width <= 0 || geometry.height <= 0)
                    continue;
                const score = Math.abs(geometry.width / geometry.height - savedAspect) +
                    Math.abs(geometry.width - savedGeometry.width) / savedGeometry.width +
                    Math.abs(geometry.height - savedGeometry.height) / savedGeometry.height;
                if (score < bestScore) {
                    bestScore = score;
                    bestIndex = index;
                }
            }
            if (bestIndex >= 0)
                savedMonitorIndex = bestIndex;
        }

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
                            finish(this._canMove(metaWindow, isCurrent) ? metaWindow : null);
                    });
                unmanagingId = metaWindow.connect('unmanaging', () => finish(null));
                timeoutId = GLib.timeout_add(GLib.PRIORITY_LOW, 1000, () => {
                    timeoutId = 0;
                    finish(this._canMove(metaWindow, isCurrent) &&
                        metaWindow.get_monitor() === toMonitorIndex ? metaWindow : null);
                    return GLib.SOURCE_REMOVE;
                });
                this._pendingMonitorWaits.set(metaWindow, finish);
                try {
                    if (!this._canMove(metaWindow, isCurrent) ||
                        toMonitorIndex < 0 || toMonitorIndex >= global.display.get_n_monitors()) {
                        finish(null);
                        return;
                    }
                    metaWindow.move_to_monitor(toMonitorIndex);
                } catch (error) {
                    finish(null);
                    this._log.error(error, 'Could not move a window to its saved monitor');
                }
            });
        }

        return Promise.resolve(metaWindow);
    }

    createEnoughWorkspaceAndMoveWindows(metaWindow, saved_window_sessions) {
        const mayMove = this._layoutGuard();
        return compositorOperations.run(
            () => this._createEnoughWorkspaceAndMoveWindows(metaWindow, saved_window_sessions, mayMove),
            () => this._canMove(metaWindow, mayMove));
    }

    async _createEnoughWorkspaceAndMoveWindows(metaWindow, saved_window_sessions, isCurrent = () => true) {
        try {
            if (!this._canMove(metaWindow, isCurrent) || UiHelper.ignoreWindows(metaWindow))
                return null;

            const saved_window_session = this._getOneMatchedSavedWindow(metaWindow, saved_window_sessions);
            if (!saved_window_session) {
                return null;
            }

            if (saved_window_session.moved) {
                return await this._restoreWindowStates(metaWindow, saved_window_session, false, isCurrent)
                    ? saved_window_session
                    : null;
            }

            if (!await this._restoreMonitor(metaWindow, saved_window_session, isCurrent) ||
                !this._canMove(metaWindow, isCurrent))
                return null;

            const desktop_number = saved_window_session.desktop_number;
            if (!this._createEnoughWorkspace(desktop_number, isCurrent))
                return null;
            if (this._log.isDebug()) {
                const shellApp = this._windowTracker.get_window_app(metaWindow);
                this._log.debug(`CEWM: Moving ${shellApp?.get_name()} - ${metaWindow.get_title()} to workspace ${desktop_number} from ${metaWindow.get_workspace().index()}`);
            }
            if (!this._changeWorkspace(metaWindow, desktop_number, isCurrent))
                return null;
            return saved_window_session;
        } catch (error) {
            this._log?.error(error, 'Window disappeared while preparing its workspace');
        }
    }

    moveWindowByMetaWindow(metaWindow, saved_window_sessions, isCurrent = () => true, beforeMove = () => {}) {
        const mayMove = this._layoutGuard(isCurrent);
        return compositorOperations.run(
            () => {
                beforeMove();
                return this._moveWindowByMetaWindow(metaWindow, saved_window_sessions, mayMove);
            },
            () => this._canMove(metaWindow, mayMove));
    }

    async _moveWindowByMetaWindow(metaWindow, saved_window_sessions, isCurrent = () => true) {
        try {
            if (!this._canMove(metaWindow, isCurrent) || UiHelper.ignoreWindows(metaWindow))
                return false;

            const saved_window_session = this._getOneMatchedSavedWindow(metaWindow, saved_window_sessions);
            if (!saved_window_session) {
                return false;
            }

            if (saved_window_session.moved) {
                return await this._restoreWindowStates(metaWindow, saved_window_session, false, isCurrent);
            } else {
                if (!await this._restoreWindowStates(metaWindow, saved_window_session, false, isCurrent) ||
                    !this._canMove(metaWindow, isCurrent))
                    return false;
                const desktop_number = saved_window_session.desktop_number;
                // It's necessary to move window again to ensure an app goes to its own workspace.
                // In a sort of situation, some apps probably just don't want to move when call createEnoughWorkspaceAndMoveWindows() from `Meta.Display::window-created` signal.
                if (!this._createEnoughWorkspace(desktop_number, isCurrent))
                    return false;
                const shellApp = this._windowTracker.get_window_app(metaWindow);
                const is_sticky = saved_window_session.window_state.is_sticky;
                if (is_sticky && metaWindow.is_on_all_workspaces()) {
                    this._log.debug(`The window '${shellApp.get_name()} - ${metaWindow.get_title()}' is already sticky on workspace ${desktop_number}`);
                } else {
                    this._log.debug(`MWMW: Moving ${shellApp?.get_name()} - ${metaWindow.get_title()} to workspace ${desktop_number} from ${metaWindow.get_workspace().index()}`);
                    if (!this._changeWorkspace(metaWindow, desktop_number, isCurrent))
                        return false;
                }
                if (!this._canMove(metaWindow, isCurrent))
                    return false;
                saved_window_session.moved = true;
                return true;
            }
        } catch (error) {
            this._log?.error(error, 'Window disappeared during layout restore');
            return false;
        }
    }

    _changeWorkspace(metaWindow, desktop_number, isCurrent = () => true) {
        if (!this._canMove(metaWindow, isCurrent))
            return false;
        if (!isValidWorkspaceIndex(desktop_number) ||
            desktop_number >= global.workspace_manager.n_workspaces)
            return false;
        if (metaWindow.get_workspace().index() === desktop_number)
            return true;
        metaWindow.change_workspace_by_index(desktop_number, false);
        // Restoration must never follow focus across workspaces. Activating each
        // newly launched window while several clients are mapping creates a
        // compositor-level focus/workspace storm on Wayland.
        return this._canMove(metaWindow, isCurrent);
    }

    _getOneMatchedSavedWindow(metaWindow, saved_window_sessions) {
        saved_window_sessions = saved_window_sessions.filter(saved_window_session => {
            return !saved_window_session.moved;
        });

        for (const saved_window_session of saved_window_sessions) {
            const title = metaWindow.get_title();
            const open_window_workspace_index = metaWindow.get_workspace().index();
            const desktop_number = saved_window_session.desktop_number;

            if (this._matchesSavedWindow(metaWindow, saved_window_session)) {
                if (open_window_workspace_index === desktop_number) {
                    if (this._log.isDebug()) {
                        const shellApp = this._windowTracker.get_window_app(metaWindow);
                        this._log.debug(`The window '${shellApp?.get_name()} - ${title}' is already on workspace ${desktop_number}`);
                    }
                }

                return saved_window_session;
            }
        }
        return null;
    }

    _matchesSavedWindow(window, saved) {
        const currentClass = window.get_wm_class?.() ?? saved.wm_class;
        const savedClass = saved.wm_class;
        const compatibleClass = currentClass === savedClass ||
            (/^libreoffice-(startcenter|writer|calc|impress|draw|base|math)$/i.test(currentClass ?? '') &&
             /^libreoffice-(startcenter|writer|calc|impress|draw|base|math)$/i.test(savedClass ?? ''));
        if (!compatibleClass)
            return false;
        const exactTitle = Boolean(saved.window_title) && window.get_title() === saved.window_title;
        // Transitional LibreOffice classes are compatible only when the
        // document title identifies the window; never assign a random sheet.
        return exactTitle || (currentClass === savedClass && saved.windows_count === 1);
    }

    /**
     * Restore varies window states, including:
     * * window states, such as Always on Top, Always on Visible Workspace
     * * window geometry
     * * window tiling
     *
     * @see https://help.gnome.org/users/gnome-help/stable/shell-windows-maximize.html.en
     */
    async _restoreWindowStates(metaWindow, saved_window_session, markToMoved = false, isCurrent = () => true) {
        try {
            if (!this._canMove(metaWindow, isCurrent) || UiHelper.ignoreWindows(metaWindow))
                return false;

            if (!await this._restoreMonitor(metaWindow, saved_window_session, isCurrent) ||
                !this._restoreWindowState(metaWindow, saved_window_session, isCurrent) ||
                !await this._restoreWindowGeometry(metaWindow, saved_window_session, isCurrent) ||
                !this._restoreTiling(metaWindow, saved_window_session, isCurrent) ||
                !this._canMove(metaWindow, isCurrent))
                return false;
            if (markToMoved) {
                saved_window_session.moved = true;
            }
            return true;
        } catch (error) {
            this._log?.error(error, 'Window disappeared while restoring its state');
            return false;
        }
    }

    _restoreWindowState(metaWindow, saved_window_session, isCurrent = () => true) {
        if (!this._canMove(metaWindow, isCurrent) || !saved_window_session?.window_state)
            return false;
        // window state
        const window_state = saved_window_session.window_state;
        if (window_state.is_above) {
            if (!metaWindow.is_above()) {
                this._log.debug(`Making ${metaWindow.get_title()} above`);
                metaWindow.make_above();
            }
        }
        if (!this._canMove(metaWindow, isCurrent))
            return false;
        if (window_state.is_sticky) {
            if (!metaWindow.is_on_all_workspaces()) {
                this._log.debug(`Making ${metaWindow.get_title()} sticky`);
                metaWindow.stick();
            }
        }

        if (!this._canMove(metaWindow, isCurrent))
            return false;

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

        return this._canMove(metaWindow, isCurrent);
    }

    /**
     * @see https://help.gnome.org/users/gnome-help/stable/shell-windows-maximize.html.en
     */
    async _restoreWindowGeometry(metaWindow, saved_window_session, isCurrent = () => true) {
        if (!this._canMove(metaWindow, isCurrent) || !saved_window_session?.window_state)
            return false;
        if (metaWindow.is_fullscreen?.() || saved_window_session.fullscreen)
            return this._canMove(metaWindow, isCurrent);
        let delay = false;
        const window_state = saved_window_session.window_state;
        const savedMetaMaximized = window_state.meta_maximized;
        // A maximized window already occupies its target work area. Mutter can
        // reject or crash on move_resize_frame() while maximization is being
        // applied, so geometry is restored only for non-maximized windows.
        if (savedMetaMaximized)
            return this._canMove(metaWindow, isCurrent);
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
                    delay = true;
                }
            }
        }

        if (delay) {
            // Keep the minimum animation settle delay, but require observed
            // unmaximization before resizing. Never force a native resize when
            // Mutter has not settled within the two-second budget.
            return new Promise(resolve => {
                const previous = this._pendingGeometryRestores.get(metaWindow);
                if (previous) {
                    GLib.Source.remove(previous.sourceId);
                    previous.resolve(false);
                }
                const deadline = GLib.get_monotonic_time() + 2 * 1000000;
                const finish = result => {
                    this._pendingGeometryRestores.delete(metaWindow);
                    resolve(result);
                    return GLib.SOURCE_REMOVE;
                };
                const sourceId = GLib.timeout_add(GLib.PRIORITY_LOW, 500, () => {
                    try {
                        if (!this._canMove(metaWindow, isCurrent) || metaWindow.is_fullscreen?.())
                            return finish(false);
                        if (GLib.get_monotonic_time() >= deadline)
                            return finish(false);
                        if (this._windowIsMaximized(metaWindow)) {
                            return GLib.SOURCE_CONTINUE;
                        }
                        return finish(this._moveResizeFrame(metaWindow, saved_window_session, isCurrent));
                    } catch (error) {
                        this._log?.error(error, 'Window did not settle before geometry restore');
                        return finish(false);
                    }
                });
                this._pendingGeometryRestores.set(metaWindow, {sourceId, resolve});
            });
        } else {
            return this._moveResizeFrame(metaWindow, saved_window_session, isCurrent);
        }
    }

    _windowIsMaximized(metaWindow) {
        return shellVersion >= 49 ? metaWindow.is_maximized() : Boolean(metaWindow.get_maximized());
    }

    _moveResizeFrame(metaWindow, saved_window_session, isCurrent = () => true) {
        if (!this._canMove(metaWindow, isCurrent) || this._windowIsMaximized(metaWindow) ||
            metaWindow.is_fullscreen?.())
            return false;
        const window_position = saved_window_session.window_position;
        if (window_position?.provider === 'Meta') {
            if (metaWindow.allows_move?.() === false || metaWindow.allows_resize?.() === false)
                return true;
            // Asking by a cached monitor index races monitor topology changes
            // and produced Mutter's logical_monitor assertion in crash logs.
            const rectWorkArea = metaWindow.get_work_area_current_monitor();
            if (!rectWorkArea || !this._isWindowUsable(metaWindow))
                return false;

            // For more info about the below issue see also: https://github.com/Leleat/Tiling-Assistant/blob/1e4176a9a7037ee5dd0612e4c9f9dbe45d4e67cf/tiling-assistant%40leleat-on-github/src/extension/tilingWindowManager.js#L186-L199

            const geometry = clampWindowGeometry(rectWorkArea, window_position);
            if (!geometry || !this._canMove(metaWindow, isCurrent))
                return false;
            metaWindow.move_resize_frame(
                false, geometry.x, geometry.y, geometry.width, geometry.height);
            return this._canMove(metaWindow, isCurrent);
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
        const assignedWindows = new Set();
        const open_windows = shellApp.get_windows();
        // A capture-scoped index avoids scanning every live window for every
        // saved title. Never cache native objects across lifecycle events.
        const byTitle = new Map();
        const byClass = new Map();
        const unknownClass = [];
        const add = (index, key, position) => {
            if (!index.has(key))
                index.set(key, []);
            index.get(key).push(position);
        };
        open_windows.forEach((window, position) => {
            if (!this._isWindowUsable(window))
                return;
            add(byTitle, window.get_title(), position);
            const wmClass = window.get_wm_class?.();
            if (wmClass == null)
                unknownClass.push(position);
            else
                add(byClass, wmClass, position);
        });
        saved_window_sessions.forEach(saved_window_session => {
            const candidates = new Set(byTitle.get(saved_window_session.window_title) ?? []);
            if (saved_window_session.windows_count === 1) {
                for (const position of byClass.get(saved_window_session.wm_class) ?? [])
                    candidates.add(position);
                for (const position of unknownClass)
                    candidates.add(position);
            }
            // Preserve the old first-match ordering and authoritative class /
            // exact-title rules, including LibreOffice transitional classes.
            [...candidates].sort((a, b) => a - b).forEach(position => {
                const open_window = open_windows[position];
                if (assignedWindows.has(open_window) || !this._isWindowUsable(open_window) ||
                    autoMoveInterestingWindows.some(item => item.saved_window_session === saved_window_session))
                    return;
                if (!this._matchesSavedWindow(open_window, saved_window_session)) {
                    return;
                }

                const title = open_window.get_title();
                const open_window_workspace_index = open_window.get_workspace().index();
                const desktop_number = saved_window_session.desktop_number;

                if (open_window_workspace_index === desktop_number) {
                    this._log.debug(`The window '${title}' is already on workspace ${desktop_number} for ${shellApp.get_name()}`);
                }
                autoMoveInterestingWindows.push({
                    open_window: open_window,
                    saved_window_session: saved_window_session
                });
                assignedWindows.add(open_window);

            });

        });

        return autoMoveInterestingWindows;
    }

    _createEnoughWorkspace(workspaceNumber, isCurrent = () => true) {
        const mayCreate = () => !this._destroyed && mayRestoreLayout() && isCurrent();
        if (!mayCreate() || !isValidWorkspaceIndex(workspaceNumber))
            return false;
        let workspaceManager = global.workspace_manager;

        // We have enough workspace now, return
        if (workspaceManager.n_workspaces >= workspaceNumber + 1) {
            return true;
        }

        // First, make all existing workspaces persistent
        for (let i = 0; i <= workspaceManager.n_workspaces - 1; i++) {
            if (!mayCreate())
                return false;
            let workspace = workspaceManager.get_workspace_by_index(i);
            if (!workspace._keepAliveId) {
                workspace._keepAliveId = true;
            }
        }

        // Second, make all newly added workspaces persistent, so they can not removed due to it does not contain any windows
        // And keep the last one non-persistent
        for (let i = workspaceManager.n_workspaces; i <= workspaceNumber; i++) {
            if (!mayCreate())
                return false;
            workspaceManager.append_new_workspace(false, 0);
            if (!mayCreate())
                return false;
            workspaceManager.get_workspace_by_index(i)._keepAliveId = true;
        }
        return workspaceManager.n_workspaces >= workspaceNumber + 1;
    }

    _waitForCompositor() {
        if (!mayRestoreApplications() || !this._windowTracker)
            return Promise.resolve(false);
        return new Promise(resolve => {
            const sourceId = GLib.timeout_add(
                GLib.PRIORITY_LOW, WINDOW_RESTORE_INTERVAL_MS, () => {
                    this._pendingPacingWaits.delete(sourceId);
                    resolve(Boolean(this._windowTracker) && mayRestoreApplications());
                    return GLib.SOURCE_REMOVE;
                });
            this._pendingPacingWaits.set(sourceId, resolve);
        });
    }

    destroy() {
        this._destroyed = true;
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
        for (const [sourceId, resolve] of this._pendingPacingWaits) {
            GLib.Source.remove(sourceId);
            resolve(false);
        }
        this._pendingPacingWaits.clear();

    }

}
