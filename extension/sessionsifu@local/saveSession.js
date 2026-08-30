'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';
import Meta from 'gi://Meta';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import * as SessionConfig from './model/sessionConfig.js';

import * as UiHelper from './ui/uiHelper.js';

import * as FileUtils from './utils/fileUtils.js';
import * as Log from './utils/log.js';
import * as MetaWindowUtils from './utils/metaWindowUtils.js';
import * as CommonError from './utils/CommonError.js';
import * as SubprocessUtils from './utils/subprocessUtils.js';
import {PrefsUtils} from './utils/prefsUtils.js';
import * as StringUtils from './utils/stringUtils.js';
import { shellVersion } from './constants.js';
import * as OpenFiles from './openFiles.js';

function ensurePrivateConfigRoot() {
    if (GLib.file_test(FileUtils.config_path_base, GLib.FileTest.IS_SYMLINK))
        throw new Error('Refusing symbolic-link SessionSifu storage');
    if (GLib.mkdir_with_parents(FileUtils.config_path_base, 0o700) !== 0)
        throw new Error('Could not create private SessionSifu storage');
    GLib.chmod(FileUtils.config_path_base, 0o700);
}


export const SaveSession = class {

    constructor(notifyUser) {
        this._notifyUser = notifyUser;
        this._log = new Log.Log();

        this._windowTracker = Shell.WindowTracker.get_default();
        this._subprocessLauncher = new Gio.SubprocessLauncher({
            flags: (Gio.SubprocessFlags.STDOUT_PIPE |
                    Gio.SubprocessFlags.STDERR_PIPE)});
        this._defaultAppSystem = Shell.AppSystem.get_default();
        this._openFileResolver = new OpenFiles.OpenFileResolver();

        this._settings = PrefsUtils.getSettings();

        this._sourceIds = [];
    }

    async saveSummaryAsync(cancellable) {
        try {
            if (cancellable && cancellable.is_cancelled()) {
                return;
            }

            const sessionConfig = new SessionConfig.SessionConfig();
            sessionConfig.active_workspace_index = global.workspace_manager.get_active_workspace_index();
            sessionConfig.n_workspace = global.workspace_manager.n_workspaces;
            const focusedWindow = global.display.get_focus_window();
            const focusedWindowClass = focusedWindow?.get_wm_class();
            if (focusedWindow && focusedWindowClass) {
                const sessionName = `${MetaWindowUtils.getStableWindowId(focusedWindow)}.json`;
                sessionConfig.focused_window = GLib.build_filenamev([FileUtils.current_session_path, focusedWindowClass, sessionName]);
            }
            delete sessionConfig.x_session_config_objects;

            await this._saveSessionConfigAsync({
                ...sessionConfig,
                session_name: FileUtils.current_session_summary_name
            }, FileUtils.current_session_path, cancellable);
        } catch(error) {
            this._log.error(error);
        }
    }

    async saveSessionAsync(sessionName, baseDir = null, backup = true) {
        try {
            this._openFileResolver.reset();
            this._log.debug(`Generating session ${sessionName}`);

            const sessionConfig = await this._buildSession(sessionName);

            sessionConfig.x_session_config_objects = sessionConfig.sort();

            if (backup) {
                await this.backupExistingSessionIfNecessary(sessionName, baseDir);
            }

            return await this._saveSessionConfigAsync(sessionConfig, baseDir);

            // TODO saved Notification
        } catch (error) {
            this._log.error(error);
            return false;
        }
    }

    async saveRecallAsync(
        sessionName,
        baseDir,
        excludedApps = [],
        includeFilePaths = false
    ) {
        try {
            this._openFileResolver.reset();
            const sessionConfig = await this._buildSession(sessionName, includeFilePaths);
            const focusedWindow = global.display.get_focus_window();
            const focusedWindowId = focusedWindow
                ? MetaWindowUtils.getStableWindowId(focusedWindow)
                : '';
            const exclusions = new Set(
                ['sessionsifu', ...excludedApps]
                    .map(value => String(value).trim().toLowerCase())
                    .filter(value => value));
            const recallWindows = sessionConfig.sort();
            sessionConfig.x_session_config_objects = recallWindows
                .filter(item => {
                    const identity = [item.app_name, item.desktop_file_id, item.wm_class]
                        .map(value => String(value ?? '').toLowerCase())
                        .join('\n');
                    return ![...exclusions].some(value => identity.includes(value));
                })
                .map(item => {
                    const sanitized = {...item};
                    const recallPid = Number.parseInt(sanitized.pid, 10);
                    sanitized.recall_pid = Number.isSafeInteger(recallPid) && recallPid > 0
                        ? recallPid : 0;
                    for (const field of [
                        'pid', 'username', 'client_machine_name',
                        'process_create_time', 'cpu_percent', 'memory_percent',
                        'cmd', 'desktop_file_id_full_path'])
                        delete sanitized[field];
                    if (!includeFilePaths)
                        sanitized.open_files = [];
                    sanitized.recall_focused = Boolean(
                        focusedWindowId && sanitized.window_id === focusedWindowId);
                    return sanitized;
                });
            if (!sessionConfig.x_session_config_objects.length)
                return false;
            sessionConfig.recall_schema = 3;
            sessionConfig.recall_capture_diagnostics = {
                expected_windows: Math.min(recallWindows.length, 64),
                excluded_windows: Math.min(
                    Math.max(0, recallWindows.length - sessionConfig.x_session_config_objects.length),
                    64),
            };
            sessionConfig.recall_include_file_paths = Boolean(includeFilePaths);
            sessionConfig.recall_displays = Main.layoutManager.monitors
                .slice(0, 8)
                .map((monitor, index) => ({
                    index,
                    x: Math.trunc(monitor.x),
                    y: Math.trunc(monitor.y),
                    width: Math.trunc(monitor.width),
                    height: Math.trunc(monitor.height),
                }))
                .filter(monitor => monitor.width > 0 && monitor.height > 0);
            return await this._saveSessionConfigAsync(sessionConfig, baseDir, null, true);
        } catch (error) {
            this._log.error(error);
            return false;
        }
    }

    async saveWindowsSessionAsync(metaWindows, cancellableMap) {
        try {
            this._openFileResolver.reset();
            const apps = new Set();
            for (const metaWindow of metaWindows) {
                const cancellable = cancellableMap ? cancellableMap.get(metaWindow) : null;
                if (cancellable && cancellable.is_cancelled()) continue;
                const app = this._windowTracker.get_window_app(metaWindow);
                if (!app) continue;
                if (UiHelper.ignoreWindows(metaWindow)) continue;
                apps.add(app);
            }

            if (!apps.size) return;

            const processInfoPromise = SubprocessUtils.getProcessInfo(apps);

            const result = [];
            for (const metaWindow of metaWindows) {
                try {
                    const cancellable = cancellableMap ? cancellableMap.get(metaWindow) : null;
                    if (cancellable && cancellable.is_cancelled()) continue;
                    const app = this._windowTracker.get_window_app(metaWindow);
                    if (!app) continue;
                    if (UiHelper.ignoreWindows(metaWindow)) continue;
                    const wmClass = metaWindow.get_wm_class();
                    if (!wmClass) continue;

                    const sessionName = `${MetaWindowUtils.getStableWindowId(metaWindow)}.json`;
                    const baseDir = `${FileUtils.current_session_path}/${wmClass}`;

                    this._log.debug(`Generating window session ${sessionName}`);

                    const [canContinue, sessionConfigObject] = this._builtSessionDetails(
                        app,
                        metaWindow,
                        cancellable);
                    if (!canContinue) return;

                    const processInfoMap = await processInfoPromise;
                    const processInfoArray = processInfoMap.get(metaWindow.get_pid());
                    this._setFieldsFromProcess(processInfoArray, sessionConfigObject);

                    const success = await this._saveSessionConfigAsync({
                        ...sessionConfigObject,
                        session_name: sessionName
                    }, baseDir, cancellable);
                    result.push([success, metaWindow, baseDir, sessionName]);
                } catch (e) {
                    // Ignore cancelation errors
                    if (!e?.cause?.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED)) {
                        this._log.error(e);
                    }
                    result.push([false, metaWindow]);
                }
            }
            return result;
        } catch (e) {
            this._log.error(e);
        }
    }

    async saveWindowSessionAsync(metaWindow, sessionName, baseDir, cancellable = null) {
        try {
            this._openFileResolver.reset();
            if (cancellable && cancellable.is_cancelled()) {
                return;
            }

            const app = this._windowTracker.get_window_app(metaWindow);
            if (!app) return;
            if (UiHelper.ignoreWindows(metaWindow)) return;

            this._log.debug(`Generating window session ${sessionName}`);

            const _getProcessInfoPromise = this._getProcessInfo([app])

            const [canContinue, sessionConfigObject] = this._builtSessionDetails(
                app,
                metaWindow,
                cancellable);
            if (!canContinue) return;

            const processInfoMap = await _getProcessInfoPromise;
            const processInfoArray = processInfoMap.get(metaWindow.get_pid());
            this._setFieldsFromProcess(processInfoArray, sessionConfigObject);

            return await this._saveSessionConfigAsync({
                ...sessionConfigObject,
                session_name: sessionName
            }, baseDir, cancellable);
        } catch (e) {
            this._log.error(e);
        }
    }

    async _buildSession(sessionName, includeOpenFiles = true) {
        const runningShellApps = this._defaultAppSystem.get_running();
        const _getProcessInfoPromise = includeOpenFiles
            ? SubprocessUtils.getProcessInfo(runningShellApps, (metaWindow) => {
                return UiHelper.ignoreWindows(metaWindow);
            })
            : Promise.resolve(new Map());

        const sessionConfig = new SessionConfig.SessionConfig();
        sessionConfig.session_name = sessionName ? sessionName : FileUtils.default_sessionName;
        sessionConfig.session_create_time = new Date().toLocaleString();
        sessionConfig.active_workspace_index = global.workspace_manager.get_active_workspace_index();
        sessionConfig.n_workspace = global.workspace_manager.n_workspaces;
        const processInfoMap = await _getProcessInfoPromise;

        for (const runningShellApp of runningShellApps) {
            let { metaWindows, ignoredWindowsMap } = this._doIgnoreWindows(runningShellApp);

            for (const metaWindow of metaWindows) {
                try {
                    const [canContinue, sessionConfigObject] = this._builtSessionDetails(runningShellApp, metaWindow);
                    if (!canContinue) {
                        continue;
                    }
                    sessionConfigObject.windows_count = runningShellApp.get_n_windows() - ignoredWindowsMap.get(runningShellApp).length;

                    const processInfoArray = processInfoMap.get(metaWindow.get_pid());
                    this._setFieldsFromProcess(
                        processInfoArray, sessionConfigObject, includeOpenFiles);

                    sessionConfig.x_session_config_objects.push(sessionConfigObject);
                } catch (e) {
                    this._log.error(e, `Failed to generate session ${sessionName}`);
                    global.notify_error(`Failed to generate session ${sessionName}`, e.message);
                }
            }
        }
        return sessionConfig;
    }

    _doIgnoreWindows(runningShellApp) {
        const ignoredWindowsMap = new Map();
        ignoredWindowsMap.set(runningShellApp, []);

        let metaWindows = runningShellApp.get_windows();
        metaWindows = metaWindows.filter(metaWindow => {
            if (UiHelper.ignoreWindows(metaWindow)) {
                ignoredWindowsMap.get(runningShellApp).push(metaWindow);
                return false;
            }
            return true;
        });
        return { metaWindows, ignoredWindowsMap };
    }

    _builtSessionDetails(runningShellApp, metaWindow, cancellable = null) {
        const sessionConfigObject = new SessionConfig.SessionConfigObject();
        if (cancellable && cancellable.is_cancelled()) {
            return [false, sessionConfigObject];
        }

        const appName = runningShellApp.get_name();

        sessionConfigObject.window_id = MetaWindowUtils.getStableWindowId(metaWindow);
        if (metaWindow.is_always_on_all_workspaces()) {
            sessionConfigObject.desktop_number = -1;
        } else {
            // If the window is on all workspaces, returns the currently active workspace.
            const workspace = metaWindow.get_workspace();
            // While an app such as VirtualBox Manager is starting, it opens
            // an phantom window (which is only existing a little while) at first,
            // then a second window opens. I don't know how to detect which window is phantom,
            // so that I can ignore it. If the workspace of an window is null, it probably means that
            // the window has been closed, so this window can be ignored safely.
            if (!workspace) {
                this._log.warn(`No workspace associated with window "${metaWindow.get_title()}" was found, ignoring...`);
                return [false, sessionConfigObject];
            }
            sessionConfigObject.desktop_number = workspace.index();
        }
        sessionConfigObject.monitor_number = metaWindow.get_monitor();
        sessionConfigObject.is_on_primary_monitor = metaWindow.is_on_primary_monitor();
        const savedMonitor = Main.layoutManager.monitors[sessionConfigObject.monitor_number];
        if (savedMonitor) {
            sessionConfigObject.monitor_geometry = {
                x: Math.trunc(savedMonitor.x), y: Math.trunc(savedMonitor.y),
                width: Math.trunc(savedMonitor.width), height: Math.trunc(savedMonitor.height),
            };
        }
        sessionConfigObject.pid = metaWindow.get_pid();
        // TODO Since we can launch an app in the terminal after `su - username` or `su username`, we
        // should get the user ID who creates/launches this process. In the future, we can restore
        // this kind of apps under the user ID
        sessionConfigObject.username = GLib.get_user_name();

        sessionConfigObject.client_machine_name = GLib.get_host_name();
        sessionConfigObject.window_title = metaWindow.get_title();
        sessionConfigObject.app_name = appName;
        sessionConfigObject.wm_class = metaWindow.get_wm_class();
        sessionConfigObject.wm_class_instance = metaWindow.get_wm_class_instance();
        sessionConfigObject.windows_count = runningShellApp.get_n_windows();
        sessionConfigObject.fullscreen = metaWindow.is_fullscreen();
        sessionConfigObject.minimized = metaWindow.minimized;
        sessionConfigObject.compositor_type = 'Wayland';

        const frameRect = metaWindow.get_frame_rect();
        let window_position = sessionConfigObject.window_position;
        window_position.provider = 'Meta';
        window_position.x_offset = frameRect.x;
        window_position.y_offset = frameRect.y;
        window_position.width = frameRect.width;
        window_position.height = frameRect.height;

        let window_state = sessionConfigObject.window_state;
        // See: ui/windowMenu.js:L80
        window_state.is_sticky = metaWindow.is_on_all_workspaces();
        window_state.is_above = metaWindow.is_above();

        if (shellVersion >= 49) {
            window_state.meta_maximized = metaWindow.is_maximized();
        } else {
            window_state.meta_maximized = metaWindow.get_maximized();
        }

        const windowTileFor = metaWindow.get_tile_match() ?? metaWindow._tile_match_awsm;
        if (windowTileFor) {
            const shellApp = this._windowTracker.get_window_app(windowTileFor);
            if (shellApp) {
                let window_tiling = {};
                window_tiling.window_tile_for = {
                    app_name: shellApp.get_name(),
                    desktop_file_id: shellApp.get_id(),
                    desktop_file_id_full_path: shellApp.get_app_info()?.get_filename(),
                    window_title: windowTileFor.get_title()
                };
                sessionConfigObject.window_tiling = window_tiling;
            }
        }

        const desktopAppInfo = runningShellApp.get_app_info();
        if (desktopAppInfo) {
            sessionConfigObject.desktop_file_id = runningShellApp.get_id();
            // Save the .desktop full path, so we know which desktop is used by this app.
            sessionConfigObject.desktop_file_id_full_path = desktopAppInfo.get_filename();
        } else {
            // This app is backed by a window, which means that
            // no app info associated with this application, we just set an empty string
            // Shell.App does have an id like window:22, but it's useless for restoring
            // If desktop_file_id is '', launch this application via command line
            sessionConfigObject.desktop_file_id = '';
            sessionConfigObject.desktop_file_id_full_path = '';

            // Generating a compatible desktop file for this app so that it can be recognized by `Shell.AppSystem.get_default().get_running()`
            // And also use it to restore window state and move windows to their workspace etc
            // See: https://gitlab.gnome.org/GNOME/gnome-shell/-/issues/4921

            // Note that the generated desktop file doesn't always work:
            // 1) The commandLine or cmdStr might not be always right, such as
            // querying the process of Wire-x.x.x.AppImage to get the cmd
            // returns '/tmp/.mount_Wire-3xXxIGA/wire-desktop'.
            // 2) ...

            this._log.info(`Generating a compatible desktop file for ${appName}`);
            let cmdStr = sessionConfigObject.cmd ? sessionConfigObject.cmd.join(' ').trim() : '';
            if (cmdStr.startsWith('./')) {
                // Try to get the working directory to complete the command line
                const proc = this._subprocessLauncher.spawnv(['pwdx', `${metaWindow.get_pid()}`]);
                // TODO Use async version in the future
                const result = proc.communicate_utf8(null, cancellable);
                let [, stdout, stderr] = result;
                let status = proc.get_exit_status();
                if (status === 0 && stdout) {
                    cmdStr = `${stdout.split(':')[1].trim()}/${cmdStr}`
                } else {
                    this._log.error(new Error('Failed to query an application working directory'));
                }

            }
            const iconString = runningShellApp.get_icon().to_string()
            const argument = {
                appName,
                commandLine: cmdStr,
                icon: iconString ? iconString : '',
                wmClass: metaWindow.get_wm_class(),
                wmClassInstance: metaWindow.get_wm_class_instance(),
            };

            const desktopFileName = '__' + appName + '.desktop';
            const desktopFileContent = StringUtils.format(FileUtils.loadDesktopTemplate(cancellable), argument);
            if (!desktopFileContent) {
                const errMsg = `Failed to generate a .desktop file ${desktopFileName} using ${JSON.stringify(argument)}`;
                this._log.error(new Error(errMsg));
            } else {
                this._log.info(`Generated a .desktop file, you can use the below content to create a .desktop file and copy it to ${FileUtils.desktop_file_store_path_base} :`
                    + '\n\n'
                    + desktopFileContent
                    + '\n');
            }

        }

        return [true, sessionConfigObject];
    }

    async backupExistingSessionIfNecessary(sessionName, baseDir) {

        const sessions_path = FileUtils.get_sessions_path();
        const session_file_path = GLib.build_filenamev([sessions_path, sessionName]);
        const session_file = Gio.File.new_for_path(session_file_path);
        ensurePrivateConfigRoot();
        if (GLib.file_test(session_file_path, GLib.FileTest.IS_SYMLINK))
            return Promise.reject(new Error('Refusing symbolic-link session file'));
        // Backup first if exists
        if (GLib.file_test(session_file_path, GLib.FileTest.EXISTS)) {
            this._log.debug(`Backing up existing session ${sessionName}`);

            const session_file_backup_path = FileUtils.get_sessions_backups_path();
            const session_file_backup = GLib.build_filenamev([session_file_backup_path, sessionName + '.backup-' + new Date().getTime()]);
            if (GLib.mkdir_with_parents(session_file_backup_path, 0o700) !== 0) {
                const errMsg = 'Cannot save session';
                const reason = 'Failed to create the private backup folder';
                return Promise.reject(new CommonError.CommonError(errMsg, {desc: reason}));
            }

            return new Promise((resolve, reject) => {
                session_file.copy_async(
                    Gio.File.new_for_path(session_file_backup),
                    Gio.FileCopyFlags.OVERWRITE,
                    GLib.PRIORITY_LOW,
                    null,
                    null,
                    (file, asyncResult) => {
                        let success = false;
                        let causedBy = null;
                        try {
                            success = session_file.copy_finish(asyncResult);
                            if (success) {
                                GLib.chmod(session_file_backup, 0o600);
                                resolve(success);
                                return;
                            }
                        } catch (e) {
                            causedBy = e;
                        }
                        const errMsg = 'Cannot save session';
                        const reason = 'Failed to create a private session backup';
                        reject(new CommonError.CommonError(errMsg, {desc: reason, cause: causedBy}));
                    }
                );
            });
        }
    }

    _saveSessionConfigAsync(
        sessionConfig,
        baseDir = null,
        cancellable = null,
        compact = false
    ) {
        if (cancellable && cancellable.is_cancelled()) {
            return Promise.resolve(false);
        }

        const sessions_path = FileUtils.get_sessions_path(baseDir);
        const session_file_path = GLib.build_filenamev([sessions_path, sessionConfig.session_name]);
        const sessionFile = Gio.File.new_for_path(session_file_path);
        ensurePrivateConfigRoot();
        if (GLib.file_test(session_file_path, GLib.FileTest.IS_SYMLINK))
            return Promise.reject(new Error('Refusing symbolic-link session file'));

        // https://gjs.guide/guides/gio/file-operations.html#saving-content
        // https://github.com/ewlsh/unix-permissions-cheat-sheet/blob/master/README.md#octal-notation
        // https://askubuntu.com/questions/472812/why-is-777-assigned-to-chmod-to-permit-everything-on-a-file
        // 0o stands for octal
        // Session state can include titles, paths and launch arguments. Keep it private.
        const sessionFolder = sessionFile.get_parent().get_path();
        if (GLib.file_test(sessionFolder, GLib.FileTest.IS_SYMLINK))
            return Promise.reject(new Error('Refusing symbolic-link session folder'));
        if (GLib.mkdir_with_parents(sessionFolder, 0o700) !== 0) {
            const errMsg = 'Cannot save session';
            const reason = 'Failed to create the private session folder';
            return Promise.reject(new CommonError.CommonError(errMsg, {desc: reason}));
        }

        const sessionConfigJson = JSON.stringify(sessionConfig, null, compact ? 0 : 4);
        const sessionConfigBytes = new TextEncoder().encode(sessionConfigJson);

        this._log.debug(`Saving session ${sessionConfig.session_name} to local file`);

        return new Promise((resolve, reject) => {
            // GIO already performs this replacement asynchronously. Starting it
            // immediately avoids starving Recall writes behind a busy Shell idle
            // queue while keeping the atomic replacement semantics.
            sessionFile.replace_contents_bytes_async(
                sessionConfigBytes,
                null,
                false,
                Gio.FileCreateFlags.REPLACE_DESTINATION,
                cancellable,
                (file, asyncResult) => {
                    let success = false;
                    let causedBy = null;
                    try {
                        success = sessionFile.replace_contents_finish(asyncResult);
                        if (success) {
                            GLib.chmod(sessionFolder, 0o700);
                            GLib.chmod(sessionFile.get_path(), 0o600);
                            const savedMsg = `Session ${sessionConfig.session_name} saved`;
                            Log.Log.getDefault().info(savedMsg);
                            if (this._notifyUser && this._settings.get_boolean('enable-save-session-notification')) {
                                Main.notify(`SessionSifu`, savedMsg);
                            }
                            resolve(success);
                            return;
                        }
                    } catch (e) {
                        causedBy = e;
                    }
                    const errMsg = 'Cannot save session';
                    const reason = 'Failed to write the private session file';
                    reject(new CommonError.CommonError(errMsg, {desc: reason, cause: causedBy}));
                });
        });
    }

    _setFieldsFromProcess(processInfoArray, sessionConfigObject, includeOpenFiles = true) {
        if (processInfoArray) {
            sessionConfigObject.process_create_time = processInfoArray.slice(0, 5).join(' ');
            sessionConfigObject.cpu_percent = processInfoArray.slice(5, 6).join();
            sessionConfigObject.memory_percent = processInfoArray.slice(6, 7).join();
            sessionConfigObject.cmd = processInfoArray.slice(8);
        } else {
            sessionConfigObject.process_create_time = null;
            sessionConfigObject.cpu_percent = null;
            sessionConfigObject.memory_percent = null;
            sessionConfigObject.cmd = null;
        }
        sessionConfigObject.open_files = includeOpenFiles
            ? this._openFileResolver.resolve(
                sessionConfigObject.pid,
                sessionConfigObject.cmd,
                sessionConfigObject.window_title)
            : [];
    }

    destroy() {
        if (this._windowTracker) {
            this._windowTracker = null;
        }
        if (this._defaultAppSystem) {
            this._defaultAppSystem = null;
        }
        if (this._subprocessLauncher) {
            this._subprocessLauncher = null;
        }
        if (this._openFileResolver) {
            this._openFileResolver.reset();
            this._openFileResolver = null;
        }
        if (this._sourceIds) {
            this._sourceIds.forEach(sourceId => {
                GLib.Source.remove(sourceId);
            });
            this._sourceIds = null;
        }
    }

}
