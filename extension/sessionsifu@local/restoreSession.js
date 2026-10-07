'use strict';

import Shell from 'gi://Shell';
import Gio from 'gi://Gio';
import GioUnix from 'gi://GioUnix';
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
import {compositorOperations} from './compositorOperations.js';
import {restoreActivity} from './recallActivity.js';
import {groupRestoreEntries, loadRestoreEntries} from './restoreScheduling.js';
import {MAX_WORKSPACE_INDEX, launchWorkspaceIndex} from './windowSafety.js';
import {
    AUTOMATIC_RESTORE_INTERVAL_MS,
    MIN_RESTORE_INTERVAL_MS,
    automaticRestoreDesktopIdAllowed,
    automaticRestoreTargetAllowed,
    automaticRestoreAttemptAllowed,
    automaticRestoreGroups,
    deduplicatePreviousSessionEntries,
    interruptedRestoreApplications,
    previousSessionIdentity,
    restoreCommandAllowed,
    remainingRestoreDelay,
} from './restoreSafety.js';


function _enabledDesktopAutostart(path, currentDesktops) {
    try {
        const keyFile = new GLib.KeyFile();
        keyFile.load_from_file(path, GLib.KeyFileFlags.NONE);
        const group = GLib.KEY_FILE_DESKTOP_GROUP;
        if (keyFile.get_string(group, 'Type') !== 'Application' ||
            (keyFile.has_key(group, 'Hidden') &&
                keyFile.get_boolean(group, 'Hidden')) ||
            (keyFile.has_key(group, 'X-GNOME-Autostart-enabled') &&
                !keyFile.get_boolean(group, 'X-GNOME-Autostart-enabled')))
            return null;

        const onlyShowIn = keyFile.has_key(group, 'OnlyShowIn')
            ? keyFile.get_string_list(group, 'OnlyShowIn')
                .map(value => value.toLowerCase()) : [];
        const notShowIn = keyFile.has_key(group, 'NotShowIn')
            ? keyFile.get_string_list(group, 'NotShowIn')
                .map(value => value.toLowerCase()) : [];
        if ((onlyShowIn.length &&
            !onlyShowIn.some(value => currentDesktops.has(value))) ||
            notShowIn.some(value => currentDesktops.has(value)))
            return null;

        const appInfo = GioUnix.DesktopAppInfo.new_from_filename(path);
        if (!appInfo)
            return null;
        return String(appInfo.get_executable?.() ?? '')
            .trim().split('/').pop().toLowerCase();
    } catch (_error) {
        return null;
    }
}


function _desktopAutostartTargets() {
    const desktopIds = new Set();
    const executables = new Set();
    const seen = new Set();
    const configDirectories = [
        GLib.get_user_config_dir(),
        ...GLib.get_system_config_dirs(),
    ];
    const currentDesktops = new Set(
        String(GLib.getenv('XDG_CURRENT_DESKTOP') ?? 'GNOME')
            .split(':').map(value => value.trim().toLowerCase()).filter(value => value));

    // XDG autostart uses the first matching filename, with the user directory
    // taking precedence. A hidden user entry therefore disables a system one.
    for (const configDirectory of configDirectories) {
        const directory = Gio.File.new_for_path(
            GLib.build_filenamev([configDirectory, 'autostart']));
        let enumerator = null;
        try {
            enumerator = directory.enumerate_children(
                'standard::name,standard::type',
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
            let info;
            while ((info = enumerator.next_file(null)) !== null) {
                const filename = info.get_name();
                if (!filename.toLowerCase().endsWith('.desktop') || seen.has(filename))
                    continue;
                seen.add(filename);

                const path = GLib.build_filenamev([
                    configDirectory, 'autostart', filename,
                ]);
                const executable = _enabledDesktopAutostart(path, currentDesktops);
                if (executable === null)
                    continue;
                desktopIds.add(filename.toLowerCase());
                if (executable)
                    executables.add(executable);
            }
        } catch (_error) {
            // Missing and malformed autostart directories are normal. They
            // must not prevent restoration of unrelated applications.
        } finally {
            try { enumerator?.close(null); } catch (_error) { /* Already closed. */ }
        }
    }
    return {desktopIds, executables};
}


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
        this._autostartTargets = _desktopAutostartTargets();

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
        this._pendingReadinessWaits = new Set();
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
        return this._runRestore(() => this._restoreSessionFromFile(
            session_file_path, selectedApplicationKeys, automatic), automatic);
    }

    async _restoreSessionFromFile(
        session_file_path, selectedApplicationKeys, automatic
    ) {
        if (!mayRestoreApplications() || this._destroyed)
            return;

        const session_file = Gio.File.new_for_path(session_file_path);
        const contents = await this._loadSessionContents(session_file);
        if (!contents || this._destroyed || !mayRestoreApplications()) {
            return;
        }

        let session_config = FileUtils.getJsonObj(contents);
        let session_config_objects = session_config.x_session_config_objects;
        if (!(session_config_objects && session_config_objects.length)) {
            this._log.error(new Error('Saved session details not found'));
            global.notify_error('No session to restore', 'Session configuration is empty.');
            return;
        }

        if (selectedApplicationKeys !== null) {
            const selected = selectedApplicationKeys instanceof Set
                ? selectedApplicationKeys
                : new Set(selectedApplicationKeys);
            session_config_objects = session_config_objects.filter(
                session => selected.has(this._sessionApplicationKey(session)));
        }

        if (automatic) {
            const planned = this._automaticRestorePlan(session_config_objects.map(
                sessionConfig => ({sessionConfig, modified: 0})), true);
            session_config_objects = planned.groups.flatMap(group =>
                group.entries.map(entry => entry.sessionConfig));
            if (planned.rejected.length || planned.discarded.length) {
                this._retained += planned.rejected.length + planned.discarded.length;
                this._log.warn(
                    `Skipped ${planned.rejected.length} unsafe and ` +
                    `${planned.discarded.length} excess automatic restore records`);
            }
        }

        if (session_config_objects.length === 0) {
            return true;
        }

        const groups = groupRestoreEntries(session_config_objects.map(
            sessionConfig => ({sessionConfig})), session => this._sessionApplicationKey(session));
        let processed = 0;
        for (const entries of groups) {
            this._registerRestoreEntries(entries);
            for (const {sessionConfig} of entries) {
                if (!mayRestoreApplications() || this._destroyed)
                    return false;
                this._progress(`Processing window ${++processed} of ${session_config_objects.length}…`);
                const [handled, , deferred] = await this._restoreQueuedEntry(
                    sessionConfig, {deferLayout: true});
                if (!handled && !deferred)
                    this._retained++;
                if (processed < session_config_objects.length &&
                    !await this._waitBeforeNextRestore(MIN_RESTORE_INTERVAL_MS))
                    return false;
            }
        }
        await this._reconcileDeferredLayouts();
        return mayRestoreApplications() && !this._destroyed;
    }

    async restorePreviousSession(removeAfterRestore, automatic = true) {
        return this._runRestore(() => this._restorePreviousSession(
            removeAfterRestore, automatic), automatic);
    }

    async _restorePreviousSession(removeAfterRestore, automatic) {
        try {
            if (!mayRestoreApplications() || this._destroyed)
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

            const sessionEntries = await loadRestoreEntries(sessionFiles, async file => {
                try {
                    const contents = await this._loadSessionContents(file);
                    if (!contents)
                        return null;

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
                    return {file, sessionConfig, modified, contents};
                } catch (error) {
                    this._retained++;
                    this._log.error(error, `Could not load previous-session state from ${file.get_path()}`);
                    return null;
                }
            }, () => mayRestoreApplications() && !this._destroyed);
            const deduplicated = deduplicatePreviousSessionEntries(sessionEntries);
            if (deduplicated.duplicates.length) {
                this._log.warn(
                    `Skipped ${deduplicated.duplicates.length} duplicate previous-session ` +
                    'window records');
            }

            const restoreEntries = deduplicated.entries;
            const planned = this._automaticRestorePlan(restoreEntries, automatic);
            this._retained += planned.rejected.length + planned.discarded.length;
            if (planned.rejected.length || planned.discarded.length) {
                this._log.warn(
                    `Skipped ${planned.rejected.length} unsafe and ` +
                    `${planned.discarded.length} excess automatic restore records`);
                // Keep unavailable and deferred records for later recovery.
            }

            let completed = true;
            const retirements = new Map();
            const retire = async sessionConfig => {
                if (!removeAfterRestore || !mayRestoreApplications() || this._destroyed)
                    return;
                const entry = retirements.get(sessionConfig);
                if (!entry)
                    return;
                await this._retireSessionEntry(entry);
                const identity = previousSessionIdentity(sessionConfig);
                for (const duplicate of deduplicated.duplicates) {
                    if (previousSessionIdentity(duplicate.sessionConfig) === identity)
                        await this._retireSessionEntry(duplicate);
                }
            };
            for (let groupIndex = 0; groupIndex < planned.groups.length; groupIndex++) {
                if (!mayRestoreApplications() || this._destroyed)
                    return;

                const groupEntries = planned.groups[groupIndex].entries;
                this._registerRestoreEntries(groupEntries);
                this._progress(`Processing application ${groupIndex + 1} of ${planned.groups.length}…`);
                for (let entryIndex = 0; entryIndex < groupEntries.length; entryIndex++) {
                    if (!mayRestoreApplications() || this._destroyed)
                        return;
                    const {file, sessionConfig, contents} = groupEntries[entryIndex];
                    retirements.set(sessionConfig, {file, contents});
                    const [launched, , deferred] = await this._restoreQueuedEntry(
                        sessionConfig, {deferLayout: true});
                    if (!launched && !deferred)
                        this._retained++;
                    if (removeAfterRestore && launched) {
                        this._log.debug(`Restored one window for ${sessionConfig.app_name}`);
                        await retire(sessionConfig);
                    }
                    if (groupEntries[entryIndex + 1] &&
                        !await this._waitBeforeNextRestore(MIN_RESTORE_INTERVAL_MS)) {
                        completed = false;
                        break;
                    }
                }

                if (planned.groups[groupIndex + 1] &&
                    !await this._waitBeforeNextRestore(MIN_RESTORE_INTERVAL_MS)) {
                    completed = false;
                    break;
                }
            }
            if (completed)
                await this._reconcileDeferredLayouts(retire);
            return completed && mayRestoreApplications() && !this._destroyed;
        } catch (error) {
            this._log.error(error);
            throw error;
        }
    }

    _progress(message) {
        this._settings.set_string('restore-progress', message);
    }

    async _retireSessionEntry({file, contents}) {
        // A live tracker may have saved newer state during the readiness wait.
        // Retire only the record we actually read, including older duplicates.
        try {
            const current = await this._loadSessionContents(file);
            if (current && current.length === contents.length &&
                current.every((byte, index) => byte === contents[index]))
                FileUtils.removeFile(file.get_path());
        } catch (error) {
            this._log.warn(`Could not retire a handled restore record: ${error.message}`);
        }
    }

    async _runRestore(task, automatic) {
        if (restoreSessionObject.activeRestorer) {
            global.notify_error('Restore already in progress', 'Wait for the current queue to finish.');
            return false;
        }
        if (!mayRestoreApplications() || this._destroyed)
            return false;
        restoreSessionObject.activeRestorer = this;
        restoreSessionObject.restoringApps = new Map();
        this._retained = 0;
        this._timedOutApps = new Set();
        this._deferredLayouts = [];
        this._lastLaunchStartedAt = null;
        this._restoredApps?.clear();
        this._launchedFilesByApp?.clear();
        this._cmdAppIdMap?.clear();
        restoreActivity.begin();
        try {
            if (!this._beginAutomaticRestore(automatic))
                return false;
            this._progress('Preparing restore queue…');
            const completed = await task();
            if (completed) {
                this._completeAutomaticRestore();
                this._progress(this._retained
                    ? `Restore queue finished; ${this._retained} records retained or skipped. Review the saved session before retrying.`
                    : 'Restore queue finished. Check application windows and documents; applications control their own recovery.');
            } else {
                this._progress('Restore interrupted. Remaining records are available for manual recovery.');
            }
            return completed;
        } catch (error) {
            this._progress('Restore failed. Saved records remain available; see the session log.');
            this._log.error(error);
            return false;
        } finally {
            for (const finish of this._pendingReadinessWaits ?? [])
                finish(false);
            this._deferredLayouts = [];
            restoreSessionObject.restoringApps?.clear();
            if (restoreSessionObject.activeRestorer === this)
                restoreSessionObject.activeRestorer = null;
            restoreActivity.end();
        }
    }

    async _restoreQueuedEntry(sessionConfig, {deferLayout = false} = {}) {
        this._entryStartedAt = GLib.get_monotonic_time();
        const id = sessionConfig.desktop_file_id ?? '';
        if (this._timedOutApps.has(id))
            return [false, false];
        this._checkpointApplication(id);
        const result = await this._restoreOneSession(sessionConfig);
        if (this._destroyed || !mayRestoreApplications())
            return [false, false];
        const app = id ? this._defaultAppSystem.lookup_app(id) : null;
        if (result[0] && app) {
            const deadline = GLib.get_monotonic_time() + 30 * 1000000;
            while (app.get_state() !== Shell.AppState.RUNNING || !app.get_windows().length) {
                if (GLib.get_monotonic_time() >= deadline) {
                    this._timedOutApps.add(id);
                    restoreSessionObject.restoringApps?.delete(app);
                    this._log.warn(`Application did not become ready within 30 seconds: ${id}`);
                    return [false, result[1]];
                }
                if (!await this._waitForRestoreEvent(app, 1000))
                    return [false, result[1]];
            }
            // Let mapped windows settle before issuing another launch request.
            if (!sessionConfig.moved &&
                !await this._waitBeforeNextRestore(MIN_RESTORE_INTERVAL_MS, true))
                return [false, result[1]];
            // Readiness is not layout completion. Share the native-operation
            // queue with shown/title callbacks and Recall before retiring data.
            const layoutDeadline = GLib.get_monotonic_time() + 10 * 1000000;
            while (!sessionConfig.moved) {
                if (await this._moveSession.moveWindowsByShellApp(app, [sessionConfig],
                    () => this._checkpointApplication(id)) ||
                    sessionConfig.moved)
                    break;
                if (deferLayout) {
                    this._deferredLayouts.push({app, sessionConfig});
                    return [false, result[1], true];
                }
                if (GLib.get_monotonic_time() >= layoutDeadline) {
                    this._log.warn(`Saved window layout did not become ready: ${id}; record retained`);
                    return [false, result[1]];
                }
                if (!await this._waitForRestoreEvent(app, 1000))
                    return [false, result[1]];
            }
        }
        if (result[0])
            this._markApplicationHandled(sessionConfig);
        return result;
    }

    _markApplicationHandled(sessionConfig) {
        delete this._heldApplications[(sessionConfig.desktop_file_id ?? '').toLowerCase()];
        this._settings.set_string('restore-held-applications', JSON.stringify(this._heldApplications));
    }

    _checkpointApplication(id) {
        id = id.toLowerCase();
        const timestamp = Math.floor(Date.now() / 1000);
        if (this._settings.get_string('restore-active-application') === id &&
            this._settings.get_int64('last-automatic-restore-attempt') === timestamp)
            return;
        this._settings.set_string('restore-active-application', id);
        this._settings.set_int64('last-automatic-restore-attempt', timestamp);
        // Persist before native work, including late shown/title callbacks that
        // belong to a different app from the queue's current launch entry.
        Gio.Settings.sync();
    }

    _registerRestoreEntries(entries) {
        for (const {sessionConfig} of entries) {
            const app = sessionConfig.desktop_file_id
                ? this._defaultAppSystem.lookup_app(sessionConfig.desktop_file_id) : null;
            if (!app)
                continue;
            const mapping = restoreSessionObject.restoringApps.get(app) ?? {saved_window_sessions: []};
            if (!mapping.saved_window_sessions.includes(sessionConfig))
                mapping.saved_window_sessions.push(sessionConfig);
            restoreSessionObject.restoringApps.set(app, mapping);
        }
    }

    async _reconcileDeferredLayouts(onHandled = async () => {}) {
        let pending = this._deferredLayouts ?? [];
        const deadline = GLib.get_monotonic_time() + 10 * 1000000;
        while (pending.length && !this._destroyed && mayRestoreApplications()) {
            const remaining = [];
            for (const entry of pending) {
                if (this._destroyed || !mayRestoreApplications())
                    return;
                const {app, sessionConfig} = entry;
                // Every later native attempt needs its own durable crash marker.
                this._checkpointApplication(sessionConfig.desktop_file_id ?? '');
                let running = false;
                try { running = app.get_state() === Shell.AppState.RUNNING; } catch (_error) {}
                const handled = sessionConfig.moved || (running &&
                    await this._moveSession.moveWindowsByShellApp(app, [sessionConfig],
                        () => this._checkpointApplication(sessionConfig.desktop_file_id ?? '')));
                if (this._destroyed || !mayRestoreApplications())
                    return;
                if (handled) {
                    this._markApplicationHandled(sessionConfig);
                    await onHandled(sessionConfig);
                } else {
                    remaining.push(entry);
                }
            }
            pending = remaining;
            if (!pending.length || GLib.get_monotonic_time() >= deadline)
                break;
            if (!await this._waitForRestoreEvent(null, 1000, pending.map(entry => entry.app)))
                return;
        }
        this._retained += pending.length;
        if (pending.length)
            this._log.warn(`Saved window layouts did not become ready: ${pending.length} records retained`);
        this._deferredLayouts = [];
    }

    _waitForRestoreEvent(app, milliseconds, apps = app ? [app] : []) {
        if (this._destroyed || !mayRestoreApplications())
            return Promise.resolve(false);
        this._pendingReadinessWaits ??= new Set();
        return new Promise(resolve => {
            const connections = [];
            let sourceId = 0;
            let finished = false;
            const finish = result => {
                if (finished)
                    return;
                finished = true;
                if (sourceId)
                    GLib.Source.remove(sourceId);
                for (const [object, id] of connections) {
                    try { object.disconnect(id); } catch (_error) {}
                }
                this._pendingReadinessWaits.delete(finish);
                resolve(result && !this._destroyed && mayRestoreApplications());
            };
            const wake = () => finish(true);
            const connect = (object, signal) => {
                try {
                    if (object?.connect)
                        connections.push([object, object.connect(signal, wake)]);
                } catch (_error) {
                    // Unsupported signals retain the original one-second poll.
                }
            };
            for (const target of new Set(apps)) {
                connect(target, 'notify::state');
                connect(target, 'windows-changed');
                try {
                    for (const window of target.get_windows())
                        if (!window._aboutToClose) {
                            connect(window, 'unmanaging');
                            connect(window, 'notify::title');
                        }
                } catch (_error) {
                    // A closing/disposed app must retain the timer fallback.
                }
            }
            this._pendingReadinessWaits.add(finish);
            sourceId = GLib.timeout_add(GLib.PRIORITY_LOW, milliseconds, () => {
                sourceId = 0;
                finish(true);
                return GLib.SOURCE_REMOVE;
            });
        });
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

    _beginAutomaticRestore(automatic = true) {
        const now = Math.floor(Date.now() / 1000);
        const previousAttempt = this._settings.get_int64('last-automatic-restore-attempt');
        this._heldApplications = interruptedRestoreApplications(
            this._settings.get_string('restore-held-applications'),
            this._settings.get_string('restore-active-application'), previousAttempt, now);
        this._settings.set_string('restore-held-applications', JSON.stringify(this._heldApplications));
        if (automatic && !automaticRestoreAttemptAllowed(previousAttempt, now)) {
            this._log.warn(
                'Skipping repeated automatic restore to protect the desktop from a crash loop');
            global.notify_error(
                'Automatic restore paused',
                'SessionSifu detected a recent restore attempt. Manual restore remains available.');
            this._progress('Automatic restore paused after a recent interrupted attempt. Use Restore Now for manual recovery.');
            return false;
        }
        // The old marker has now been converted to an application hold.
        // A fresh checkpoint is written only when launch work actually starts.
        this._completeAutomaticRestore();
        return true;
    }

    _completeAutomaticRestore() {
        this._settings.set_int64('last-automatic-restore-attempt', 0);
        this._settings.set_string('restore-active-application', '');
        this._log.info('Cleared the active restore checkpoint');
    }

    _sessionApplicationKey(sessionConfig) {
        if (sessionConfig.desktop_file_id)
            return `desktop:${sessionConfig.desktop_file_id}`;
        if (Array.isArray(sessionConfig.cmd) && sessionConfig.cmd.length)
            return `command-sha256:${GLib.compute_checksum_for_string(
                GLib.ChecksumType.SHA256, JSON.stringify(sessionConfig.cmd), -1)}`;
        return `application:${sessionConfig.app_name ?? ''}`;
    }

    _automaticRestorePlan(entries, automatic = false) {
        const availableEntries = [];
        const unavailableEntries = [];
        for (const entry of entries) {
            const desktopFileId = entry?.sessionConfig?.desktop_file_id;
            const shellApp = desktopFileId
                ? this._defaultAppSystem.lookup_app(desktopFileId)
                : null;
            const appInfo = shellApp?.get_app_info?.();
            if ((automatic && this._heldApplications[desktopFileId?.toLowerCase()]) ||
                !automaticRestoreDesktopIdAllowed(desktopFileId) ||
                (automatic && !automaticRestoreTargetAllowed(
                    desktopFileId, appInfo?.get_executable?.(),
                    this._autostartTargets?.desktopIds,
                    this._autostartTargets?.executables)) ||
                !shellApp || !appInfo || appInfo.should_show?.() === false) {
                unavailableEntries.push(entry);
                continue;
            }
            availableEntries.push(entry);
        }
        const planned = automaticRestoreGroups(availableEntries, true);
        planned.rejected.push(...unavailableEntries);
        return planned;
    }

    _waitBeforeNextRestore(minimumIntervalMs = MIN_RESTORE_INTERVAL_MS, fixedDelay = false) {
        if (!mayRestoreApplications() || this._destroyed)
            return Promise.resolve(false);

        const interval = fixedDelay ? minimumIntervalMs
            : remainingRestoreDelay(Math.max(minimumIntervalMs, this._restore_session_interval),
                this._entryStartedAt, GLib.get_monotonic_time());
        if (interval <= 0)
            return Promise.resolve(true);
        return new Promise(resolve => {
            const sourceId = GLib.timeout_add(
                GLib.PRIORITY_LOW,
                interval,
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
                // STARTING applications can expose half-mapped windows while
                // their StartupNotify transaction is still active. Touching
                // those windows immediately has crashed Mutter on Wayland.
                // The indicator's shown/title callbacks restore them after the
                // normal settle delay; only stable RUNNING apps are moved here.
                const appWasStableRunning =
                    shell_app.get_state() === Shell.AppState.RUNNING;
                const appInfo = shell_app.get_app_info();
                const restorableDocuments = OpenFiles.appInfoSupportsDocumentFiles(appInfo)
                    ? OpenFiles.existingOpenFiles(session_config_object.open_files)
                    : [];
                const restoringShellAppData = restoreSessionObject.restoringApps.get(shell_app);
                if (restoringShellAppData) {
                    if (!restoringShellAppData.saved_window_sessions.includes(session_config_object))
                        restoringShellAppData.saved_window_sessions.push(session_config_object);
                } else {
                    restoreSessionObject.restoringApps.set(shell_app, {
                        saved_window_sessions: [session_config_object]
                    });
                }

                if (this._willLaunch(shell_app, session_config_object.open_files) &&
                    !await this._waitForLaunchTurn())
                    return [false, false];
                const launchResult = await compositorOperations.run(
                    () => {
                        this._checkpointApplication(desktop_file_id);
                        const result = this.launch(shell_app,
                            session_config_object.desktop_number,
                            session_config_object.open_files);
                        // Time queued behind capture is not a launch safety gap.
                        this._entryStartedAt = GLib.get_monotonic_time();
                        return result;
                    },
                    () => !this._destroyed && mayRestoreApplications());
                [launched, running] = launchResult || [false, false];
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
                    if (appWasStableRunning && restorableDocuments.length === 0) {
                        const movedExisting = await this._moveSession.moveWindowsByShellApp(
                            shell_app, [session_config_object],
                            () => this._checkpointApplication(desktop_file_id));
                        if (!movedExisting && !session_config_object.moved) {
                            this._log.warn(
                                `Waiting for a matching existing window for ${app_name}`);
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
                    if (!await this._waitForLaunchTurn())
                        return [false, false];
                    const spawned = await compositorOperations.run(() => {
                        this._checkpointApplication(desktop_file_id ?? '');
                        this._lastLaunchStartedAt = GLib.get_monotonic_time();
                        const result = SubprocessUtils.spawnDirectArgv(cmd);
                        this._entryStartedAt = GLib.get_monotonic_time();
                        return result;
                    }, () => !this._destroyed && mayRestoreApplications());
                    if (!spawned)
                        return [false, false];
                    const [, childPid, normalizedKey] = spawned;
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
        if (this._destroyed || !mayRestoreApplications())
            return [false, false];
        desktopNumber = launchWorkspaceIndex(
            desktopNumber, global.workspace_manager.n_workspaces);
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
            this._lastLaunchStartedAt = GLib.get_monotonic_time();
            const launched = appInfo.launch(files, context);
            if (launched)
                paths.forEach(path => launchedFiles.add(path));
            return launched;
        };

        if (this._restoredApps.has(shellApp)) {
            if (canLaunchFiles)
                return [launchFiles(), false];
            this._log.info(`${shellApp.get_name()} is restored, skipping`);
            // Reusing a previous launch is not another process launch. In
            // particular, do not log browser-owned recovery as a second start.
            return [true, true];
        }

        if (this._appIsRunning(shellApp)) {
            if (canLaunchFiles)
                return [launchFiles(), true];
            this._log.info(`${shellApp.get_name()} is running, skipping`);
            // During an active restore, keep the complete expected-window map
            // for late browser-owned recovery. Completion clears it globally.
            if (!restoreSessionObject.activeRestorer && shellApp.get_state() === Shell.AppState.RUNNING)
                restoreSessionObject.restoringApps.delete(shellApp);
            return [true, true];
        }

        if (canLaunchFiles)
            return [launchFiles(), false];

        this._lastLaunchStartedAt = GLib.get_monotonic_time();
        const launched = shellApp.launch(
            // 0 for current event timestamp
            0,
            desktopNumber,
            this._getProperGpuPref(shellApp));
        return [launched, false];
    }

    _willLaunch(shellApp, openFiles = []) {
        const appInfo = shellApp.get_app_info();
        const launchedFiles = this._launchedFilesByApp.get(shellApp) ?? new Set();
        const newDocuments = OpenFiles.appInfoSupportsDocumentFiles(appInfo) &&
            OpenFiles.existingOpenFiles(openFiles).some(path => !launchedFiles.has(path));
        return newDocuments || (!this._restoredApps.has(shellApp) && !this._appIsRunning(shellApp));
    }

    _waitForLaunchTurn() {
        if (!Number.isFinite(this._lastLaunchStartedAt))
            return Promise.resolve(!this._destroyed && mayRestoreApplications());
        const delay = remainingRestoreDelay(
            Math.max(AUTOMATIC_RESTORE_INTERVAL_MS, this._restore_session_interval),
            this._lastLaunchStartedAt, GLib.get_monotonic_time());
        return this._waitBeforeNextRestore(delay, true);
    }

    _appIsRunning(app) {
        // STARTING may not yet be present in get_running(). Reuse the app's
        // startup transaction instead of racing desktop/autostart launchers.
        if (app.get_state() >= Shell.AppState.STARTING)
            return true;
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

    cancel() {
        this._destroyed = true;
        for (const finish of this._pendingReadinessWaits ?? [])
            finish(false);
        if (restoreSessionObject.activeRestorer === this)
            restoreSessionObject.restoringApps?.clear();
        for (const [sourceId, resolve] of this._pendingRestoreDelays ?? []) {
            GLib.Source.remove(sourceId);
            resolve(false);
        }
        this._pendingRestoreDelays?.clear();
        this._moveSession?.destroy();
        this._progress('Restore interrupted. Remaining records are available for manual recovery.');
    }

    destroy() {
        this._destroyed = true;
        for (const finish of this._pendingReadinessWaits ?? [])
            finish(false);

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
