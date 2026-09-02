'use strict';

import Shell from 'gi://Shell';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as FileUtils from './utils/fileUtils.js';
import * as Log from './utils/log.js';
import {PrefsUtils} from './utils/prefsUtils.js';
import * as SubprocessUtils from './utils/subprocessUtils.js';
import * as DateUtils from './utils/dateUtils.js';
import * as StringUtils from './utils/stringUtils.js';
import * as OpenFiles from './openFiles.js';
import * as MoveSession from './moveSession.js';
import {mayRestoreApplications} from './runtimeSafety.js';
import {MAX_WORKSPACE_INDEX} from './windowSafety.js';
import {
    AUTOMATIC_RESTORE_INTERVAL_MS,
    MAX_PREVIOUS_SESSION_WINDOWS,
    MIN_RESTORE_INTERVAL_MS,
    automaticRestoreDesktopIdAllowed,
    automaticRestoreAttemptAllowed,
    automaticRestoreGroups,
    deduplicatePreviousSessionEntries,
    restoreCommandAllowed,
} from './restoreSafety.js';


export const restoreSessionObject = {
    // All launching apps by Shell.App#launch()
    restoringApps: new Map()
}

export const RestoreSession = class {

    constructor() {
        this._log = new Log.Log();
        this._settings = PrefsUtils.getSettings();
        restoreSessionObject.restoringApps ??= new Map();

        this.sessionName = FileUtils.default_sessionName;
        this._defaultAppSystem = Shell.AppSystem.get_default();
        this._windowTracker = Shell.WindowTracker.get_default();

        this._restore_session_interval = Math.max(
            MIN_RESTORE_INTERVAL_MS,
            this._settings.get_int('restore-session-interval'));

        // TODO Add to Preferences?
        // Launch apps using discrete graphics card might cause issues, like the white main window of superproductivity
        this._useDiscreteGraphicsCard = false;

        // All launched apps info by Shell.App#launch()
        this._restoredApps = new Map();
        this._launchedFilesByApp = new Map();
        this._moveSession = new MoveSession.MoveSession();

        // Tracking cmd and appId mapping
        this._cmdAppIdMap = new Map();

        this._display = global.display;

        this._connectIds = [];
        this._pendingRestoreDelays = new Map();
        this._destroyed = false;
    }

    /**
     * Restore workspaces and make them persistent, etc
     */
    static restoreFromSummary() {
        Log.Log.getDefault().debug(`Prepare to restore summary`);
        FileUtils.loadSummary().then(([summary, path]) => {
            Log.Log.getDefault().info(`Restoring summary from ${path}`);
            const workspaceManager = global.workspace_manager;
            const currentNWorkspace = workspaceManager.n_workspaces;
            const savedNWorkspace = Number.isInteger(summary.n_workspace)
                ? Math.min(summary.n_workspace, MAX_WORKSPACE_INDEX + 1)
                : currentNWorkspace;
            if (savedNWorkspace > currentNWorkspace) {
                for (let i = currentNWorkspace; i < savedNWorkspace; i++) {
                    workspaceManager.append_new_workspace(false, DateUtils.get_current_time());
                    workspaceManager.get_workspace_by_index(i)._keepAliveId = true;
                }
            }
        }).catch(e => Log.Log.getDefault().error(e));
    }

    restoreSession(sessionName, selectedApplicationKeys = null, automatic = false) {
        if (!mayRestoreApplications()) {
            this._log.info('Skipping session restore while the desktop session is ending');
            return;
        }
        if (!sessionName) {
            sessionName = this.sessionName;
        }

        const sessions_path = FileUtils.get_sessions_path();
        const session_file_path = GLib.build_filenamev([sessions_path, sessionName]);
        if (!GLib.file_test(session_file_path, GLib.FileTest.EXISTS)) {
            logError(new Error('Session file not found'));
            return;
        }

        this._log.info('Restoring a validated saved session');
        this.restoreSessionFromFile(
            session_file_path, selectedApplicationKeys, automatic)
            .catch(e => logError(e, 'Failed to restore saved session'));
    }

    async restoreSessionFromFile(
        session_file_path, selectedApplicationKeys = null, automatic = false
    ) {
        if (!mayRestoreApplications() || this._destroyed)
            return;

        const session_file = Gio.File.new_for_path(session_file_path);
        let [success, contents] = session_file.load_contents(null);
        if (!success) {
            return;
        }

        let session_config = FileUtils.getJsonObj(contents);
        let session_config_objects = session_config.x_session_config_objects;
        if (!(session_config_objects && session_config_objects.length)) {
            this._log.error(new Error('Saved session details not found'));
            global.notify_error('No session to restore', 'Session configuration is empty.');
            return;
        }

        if (automatic && !this._beginAutomaticRestore())
            return;

        if (selectedApplicationKeys !== null) {
            const selected = selectedApplicationKeys instanceof Set
                ? selectedApplicationKeys
                : new Set(selectedApplicationKeys);
            session_config_objects = session_config_objects.filter(
                session => selected.has(this._sessionApplicationKey(session)));
        }

        if (automatic) {
            const planned = this._automaticRestorePlan(session_config_objects.map(
                sessionConfig => ({sessionConfig, modified: 0})));
            session_config_objects = planned.groups.flatMap(group =>
                group.entries.map(entry => entry.sessionConfig));
            if (planned.rejected.length || planned.discarded.length) {
                this._log.warn(
                    `Skipped ${planned.rejected.length} unsafe and ` +
                    `${planned.discarded.length} excess automatic restore records`);
            }
        }

        if (session_config_objects.length === 0) return;

        const interval = automatic
            ? Math.max(this._restore_session_interval, AUTOMATIC_RESTORE_INTERVAL_MS)
            : this._restore_session_interval;
        for (let index = 0; index < session_config_objects.length; index++) {
            if (!mayRestoreApplications() || this._destroyed)
                return false;
            await this._restoreOneSession(session_config_objects[index]);
            if (session_config_objects[index + 1] &&
                !await this._waitBeforeNextRestore(interval))
                return false;
        }
        return true;
    }

    async restorePreviousSession(removeAfterRestore, automatic = true) {
        try {
            if (!mayRestoreApplications() || this._destroyed)
                return;
            if (automatic && !this._beginAutomaticRestore())
                return;

            this._log.info(`Restoring the previous session from ${FileUtils.current_session_path}`);

            const ignoringParentFolders = [
                GLib.build_filenamev([FileUtils.current_session_path, 'null']),
            ];
            const ignoringFilePaths = [
                GLib.build_filenamev([FileUtils.current_session_path, 'summary.json'])
            ];
            const sessionFiles = [];
            await FileUtils.listAllSessions(FileUtils.current_session_path, true, (file, info) => {
                const contentType = info.get_content_type();
                if (contentType !== 'application/json') {
                    return;
                }
                if (ignoringParentFolders.includes(file.get_parent().get_path())) {
                    return;
                }
                if (ignoringFilePaths.includes(file.get_path())) {
                    return;
                }
                sessionFiles.push(file);
            });

            const sessionEntries = [];
            for (const file of sessionFiles) {
                if (!mayRestoreApplications() || this._destroyed)
                    break;

                try {
                    const contents = await this._loadSessionContents(file);
                    if (!contents)
                        continue;

                    const sessionConfig = FileUtils.getJsonObj(contents);
                    sessionConfig._file_path = file.get_path();
                    let modified = 0;
                    try {
                        modified = file.query_info(
                            'time::modified',
                            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
                            null).get_modification_date_time()?.to_unix() ?? 0;
                    } catch (_error) {
                        // A missing timestamp does not make an otherwise valid
                        // previous-session record unsafe to restore.
                    }
                    sessionEntries.push({file, sessionConfig, modified});
                } catch (error) {
                    this._log.error(error, `Could not load previous-session state from ${file.get_path()}`);
                }
            }
            const deduplicated = deduplicatePreviousSessionEntries(sessionEntries);
            if (removeAfterRestore) {
                for (const duplicate of deduplicated.duplicates)
                    FileUtils.removeFile(duplicate.file.get_path());
            }
            if (deduplicated.duplicates.length) {
                this._log.warn(
                    `Skipped ${deduplicated.duplicates.length} duplicate previous-session ` +
                    'window records');
            }

            const restoreEntries = deduplicated.entries;
            if (restoreEntries.length > MAX_PREVIOUS_SESSION_WINDOWS) {
                this._log.warn(
                    `Restoring only ${MAX_PREVIOUS_SESSION_WINDOWS} of ` +
                    `${restoreEntries.length} previous-session windows in this login`);
                restoreEntries.sort((left, right) => right.modified - left.modified);
                restoreEntries.length = MAX_PREVIOUS_SESSION_WINDOWS;
            }
            const planned = this._automaticRestorePlan(restoreEntries);
            if (planned.rejected.length || planned.discarded.length) {
                this._log.warn(
                    `Skipped ${planned.rejected.length} unsafe and ` +
                    `${planned.discarded.length} excess automatic restore records`);
                if (removeAfterRestore) {
                    // Unsafe infrastructure records can never become valid user
                    // applications. Keep bounded excess records, however, so a
                    // later login can restore them instead of losing user state.
                    for (const entry of planned.rejected)
                        FileUtils.removeFile(entry.file.get_path());
                }
            }

            for (let groupIndex = 0; groupIndex < planned.groups.length; groupIndex++) {
                if (!mayRestoreApplications() || this._destroyed)
                    break;

                const groupEntries = planned.groups[groupIndex].entries;
                for (let entryIndex = 0; entryIndex < groupEntries.length; entryIndex++) {
                    if (!mayRestoreApplications() || this._destroyed)
                        break;
                    const {file, sessionConfig} = groupEntries[entryIndex];
                    const [launched] = await this._restoreOneSession(sessionConfig);
                    if (removeAfterRestore && launched) {
                        this._log.debug(`Restored one window for ${sessionConfig.app_name}`);
                        FileUtils.removeFile(file.get_path());
                    }
                    if (groupEntries[entryIndex + 1] &&
                        !await this._waitBeforeNextRestore(MIN_RESTORE_INTERVAL_MS))
                        break;
                }

                if (planned.groups[groupIndex + 1] &&
                    !await this._waitBeforeNextRestore(AUTOMATIC_RESTORE_INTERVAL_MS))
                    break;
            }
        } catch (error) {
            this._log.error(error);
        }
    }

    _loadSessionContents(file) {
        return new Promise((resolve, reject) => {
            file.load_contents_async(null, (source, asyncResult) => {
                try {
                    const [success, contents] = source.load_contents_finish(asyncResult);
                    resolve(success ? contents : null);
                } catch (error) {
                    reject(error);
                }
            });
        });
    }

    _beginAutomaticRestore() {
        const now = Math.floor(Date.now() / 1000);
        const previousAttempt = this._settings.get_int64('last-automatic-restore-attempt');
        if (!automaticRestoreAttemptAllowed(previousAttempt, now)) {
            this._log.warn(
                'Skipping repeated automatic restore to protect the desktop from a crash loop');
            global.notify_error(
                'Automatic restore paused',
                'SessionSifu detected a recent restore attempt. Manual restore remains available.');
            return false;
        }
        this._settings.set_int64('last-automatic-restore-attempt', now);
        return true;
    }

    _sessionApplicationKey(sessionConfig) {
        if (sessionConfig.desktop_file_id)
            return `desktop:${sessionConfig.desktop_file_id}`;
        if (Array.isArray(sessionConfig.cmd) && sessionConfig.cmd.length)
            return `command-sha256:${GLib.compute_checksum_for_string(
                GLib.ChecksumType.SHA256, JSON.stringify(sessionConfig.cmd), -1)}`;
        return `application:${sessionConfig.app_name ?? ''}`;
    }

    _automaticRestorePlan(entries) {
        const availableEntries = [];
        const unavailableEntries = [];
        for (const entry of entries) {
            const desktopFileId = entry?.sessionConfig?.desktop_file_id;
            const shellApp = desktopFileId
                ? this._defaultAppSystem.lookup_app(desktopFileId)
                : null;
            const appInfo = shellApp?.get_app_info?.();
            if (!automaticRestoreDesktopIdAllowed(desktopFileId) ||
                !shellApp || !appInfo || appInfo.should_show?.() === false) {
                unavailableEntries.push(entry);
                continue;
            }
            availableEntries.push(entry);
        }
        const planned = automaticRestoreGroups(availableEntries);
        planned.rejected.push(...unavailableEntries);
        return planned;
    }

    _waitBeforeNextRestore(minimumIntervalMs = MIN_RESTORE_INTERVAL_MS) {
        if (!mayRestoreApplications() || this._destroyed)
            return Promise.resolve(false);

        return new Promise(resolve => {
            const sourceId = GLib.timeout_add(
                GLib.PRIORITY_LOW,
                Math.max(minimumIntervalMs, this._restore_session_interval),
                () => {
                    this._pendingRestoreDelays.delete(sourceId);
                    resolve(mayRestoreApplications() && !this._destroyed);
                    return GLib.SOURCE_REMOVE;
                });
            this._pendingRestoreDelays.set(sourceId, resolve);
        });
    }

    async _restoreOneSession(session_config_object) {
        const app_name = session_config_object.app_name;
        let launched = false;
        let running = false;
        try {
            if (!mayRestoreApplications() || this._destroyed)
                return [launched, running];

            const desktop_file_id = session_config_object.desktop_file_id;
            const shell_app = desktop_file_id
                ? this._defaultAppSystem.lookup_app(desktop_file_id)
                : null;
            if (shell_app) {
                const appWasRunning = this._appIsRunning(shell_app);
                const appInfo = shell_app.get_app_info();
                const restorableDocuments = OpenFiles.appInfoSupportsDocumentFiles(appInfo)
                    ? OpenFiles.existingOpenFiles(session_config_object.open_files)
                    : [];
                const restoringShellAppData = restoreSessionObject.restoringApps.get(shell_app);
                if (restoringShellAppData) {
                    restoringShellAppData.saved_window_sessions.push(session_config_object);
                } else {
                    restoreSessionObject.restoringApps.set(shell_app, {
                        saved_window_sessions: [session_config_object]
                    });
                }

                [launched, running] = this.launch(
                    shell_app,
                    session_config_object.desktop_number,
                    session_config_object.open_files);
                if (launched) {
                    if (!running)
                        this._log.info(`${app_name} launched; preparing its saved window state`);
                    const existingShellAppData = this._restoredApps.get(shell_app);
                    if (existingShellAppData) {
                        existingShellAppData.saved_window_sessions.push(session_config_object);
                    } else {
                        this._restoredApps.set(shell_app, {
                            saved_window_sessions: [session_config_object]
                        });
                    }

                    // A running application may not create another window. Apply
                    // the saved state to its existing matching window instead of
                    // silently treating the record as restored.
                    if (appWasRunning && restorableDocuments.length === 0) {
                        const movedExisting = await this._moveSession.moveWindowsByShellApp(
                            shell_app, [session_config_object]);
                        if (!movedExisting) {
                            launched = false;
                            this._log.warn(
                                `No matching existing window was found for ${app_name}; retaining its restore record`);
                        }
                    }
                } else {
                    this._log.error(`Failed to launch ${app_name}`, `Failed to launch ${app_name}`);
                    global.notify_error(`Failed to launch ${app_name}`, `Failed to launch ${app_name}`);
                }
                return [launched, running];
            }

            // https://gjs-docs.gnome.org/gio20~2.0/gio.subprocesslauncher#method-set_environ
            // TODO Support snap apps
            const cmd = session_config_object.cmd;
            if (cmd && cmd.length) {
                if (!restoreCommandAllowed(cmd)) {
                    const message = `Refused to launch unsafe Shell helper ${app_name}`;
                    this._log.warn(message);
                    global.notify_error(
                        message,
                        'SessionSifu will not relaunch compositor or desktop services.');
                    return [launched, running];
                }
                const cmdKey = cmd.join('\0');
                const pid = this._cmdAppIdMap.get(cmdKey);
                if (pid) {
                    this._log.debug(`${app_name} might be running; preparing saved state`);

                    // Here we use pid as the key, because the associated ShellApp might not be instantiated at this moment
                    const restoringShellAppData = restoreSessionObject.restoringApps.get(pid);
                    if (restoringShellAppData) {
                        restoringShellAppData.saved_window_sessions.push(session_config_object);
                    } else {
                        restoreSessionObject.restoringApps.set(pid, {
                            saved_window_sessions: [session_config_object]
                        });
                    }
                    launched = true;
                    running = true;
                    return [launched, running];
                }

                try {
                    const [, childPid, normalizedKey] = SubprocessUtils.spawnDirectArgv(cmd);
                    this._log.info(`Launching ${app_name} using a validated argument array`);
                    this._cmdAppIdMap.set(cmdKey, childPid);
                    this._cmdAppIdMap.set(normalizedKey, childPid);
                    restoreSessionObject.restoringApps.set(childPid, {
                        saved_window_sessions: [session_config_object]
                    });
                    launched = true;
                } catch (error) {
                    const message = `Failed to launch ${app_name} safely`;
                    this._log.error(error, message);
                    global.notify_error(message, 'The saved executable or arguments were rejected.');
                }
            } else {
                const errorMsg = `Failed to launch ${app_name} via command line`;
                const errorDetail = 'The saved argument array is missing or invalid.';
                this._log.error(errorMsg, errorDetail);
                global.notify_error(errorMsg, errorDetail);
            }
            return [launched, running];
        } catch (e) {
            logError(e, `Failed to restore ${app_name}`);
            if (!launched) {
                global.notify_error(`Failed to restore ${app_name}`, e.message);
            }
            return [launched, running];
        }
    }

    launch(shellApp, desktopNumber, openFiles = []) {
        const appInfo = shellApp.get_app_info();
        const launchedFiles = this._launchedFilesByApp.get(shellApp) ?? new Set();
        this._launchedFilesByApp.set(shellApp, launchedFiles);
        const paths = (OpenFiles.appInfoSupportsDocumentFiles(appInfo)
            ? OpenFiles.existingOpenFiles(openFiles)
            : [])
            .filter(path => !launchedFiles.has(path));
        const files = paths.map(path => Gio.File.new_for_path(path));
        const canLaunchFiles = files.length > 0;
        const launchFiles = () => {
            const context = global.create_app_launch_context(
                DateUtils.get_current_time(),
                desktopNumber);
            this._log.info(`Launching ${shellApp.get_name()} with ${files.length} saved file(s)`);
            const launched = appInfo.launch(files, context);
            if (launched)
                paths.forEach(path => launchedFiles.add(path));
            return launched;
        };

        if (this._restoredApps.has(shellApp)) {
            if (canLaunchFiles)
                return [launchFiles(), false];
            this._log.info(`${shellApp.get_name()} is restored, skipping`);
            return [true, false];
        }

        if (this._appIsRunning(shellApp)) {
            if (canLaunchFiles)
                return [launchFiles(), true];
            this._log.info(`${shellApp.get_name()} is running, skipping`);
            // Delete shellApp from restoringApps to prevent it move the same app when close and open it manually.
            restoreSessionObject.restoringApps.delete(shellApp);
            return [true, true];
        }

        if (canLaunchFiles)
            return [launchFiles(), false];

        const launched = shellApp.launch(
            // 0 for current event timestamp
            0,
            desktopNumber,
            this._getProperGpuPref(shellApp));
        return [launched, false];
    }

    _appIsRunning(app) {
        // Running apps can be empty even if there are apps running when gnome-shell starting
        const running_apps = this._defaultAppSystem.get_running();
        for (const running_app of running_apps) {
            if (running_app.get_id() === app.get_id() &&
                running_app.get_state() >= Shell.AppState.STARTING) {
                return true;
            }
        }
        return false;
    }

    _getProperGpuPref(shell_app) {
        if (this._useDiscreteGraphicsCard) {
            const app_info = shell_app.get_app_info();
            if (app_info) {
                return app_info.get_boolean('PrefersNonDefaultGPU')
                    ? Shell.AppLaunchGpu.DEFAULT
                    : Shell.AppLaunchGpu.DISCRETE;
            }
        }
        return Shell.AppLaunchGpu.DEFAULT;
    }

    destroy() {
        this._destroyed = true;

        if (this._pendingRestoreDelays) {
            for (const [sourceId, resolve] of this._pendingRestoreDelays) {
                GLib.Source.remove(sourceId);
                resolve(false);
            }
            this._pendingRestoreDelays.clear();
            this._pendingRestoreDelays = null;
        }
        if (restoreSessionObject.restoringApps) {
            restoreSessionObject.restoringApps.clear();
            restoreSessionObject.restoringApps = null;
        }

        if (this._restoredApps) {
            this._restoredApps.clear();
            this._restoredApps = null;
        }
        if (this._launchedFilesByApp) {
            this._launchedFilesByApp.clear();
            this._launchedFilesByApp = null;
        }
        if (this._moveSession) {
            this._moveSession.destroy();
            this._moveSession = null;
        }

        if (this._defaultAppSystem) {
            this._defaultAppSystem = null;
        }

        if (this._windowTracker) {
            this._windowTracker = null;
        }

        if (this._log) {
            this._log.destroy();
            this._log = null;
        }

        if (this._connectIds) {
            for (let [obj, id] of this._connectIds) {
                obj.disconnect(id);
            }
            this._connectIds = null;
        }

    }

}
