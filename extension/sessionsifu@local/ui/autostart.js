'use strict';

/* exported AutostartServiceProvider, AutostartService, AutostartDialog */

import GObject from 'gi://GObject';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Clutter from 'gi://Clutter';

import * as EndSessionDialog from 'resource:///org/gnome/shell/ui/endSessionDialog.js';

import {gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Dialog from 'resource:///org/gnome/shell/ui/dialog.js';
import * as ModalDialog from 'resource:///org/gnome/shell/ui/modalDialog.js';

import * as Autoclose from './autoclose.js';
import * as RestoreSession from '../restoreSession.js';
import * as SaveSession from '../saveSession.js';
import * as Constants from '../constants.js';
import * as ContinuousSaver from '../continuousSaver.js';
import * as RecallRecorder from '../recallRecorder.js';

import * as Log from '../utils/log.js';
import {PrefsUtils} from '../utils/prefsUtils.js';
import * as FileUtils from '../utils/fileUtils.js';


let _requiredToRestorePrevious = false;

export const AutostartServiceProvider = GObject.registerClass(
    class AutostartServiceProvider extends GObject.Object {

        _init() {
            super._init();

            this._log = new Log.Log();

            this._autostartDbusXml = new TextDecoder().decode(
                FileUtils.current_extension_dir.get_child('dbus-interfaces').get_child('org.gnome.Shell.Extensions.SessionSifu.Control.xml').load_contents(null)[1]);

            this._autostartService = null;
            this._autostartDbusImpl = null;

            // https://gjs.guide/guides/gio/dbus.html#exporting-interfaces
            this._dbusNameOwnerId = Gio.bus_own_name(
                Gio.BusType.SESSION,
                'org.gnome.Shell.Extensions.SessionSifu',
                Gio.BusNameOwnerFlags.NONE,
                this.onBusAcquired.bind(this),
                this.onNameAcquired.bind(this),
                this.onNameLost.bind(this),
            );


        }

        onBusAcquired(connection, name) {
            this._log.debug(`DBus bus with name ${name} acquired!`);

            this._autostartService = new AutostartService();

            // Gio.DBusExportedObject.wrapJSObject(interfaceInfo, jsObj) is provided by GJS.
            // See: https://gitlab.gnome.org/GNOME/gjs/-/blob/master/modules/core/overrides/Gio.js#L391
            this._autostartDbusImpl = Gio.DBusExportedObject.wrapJSObject(this._autostartDbusXml, this._autostartService);
            this._autostartDbusImpl.export(connection, '/org/gnome/Shell/Extensions/SessionSifu');

        }

        onNameAcquired(connection, name) {
            this._log.debug(`DBus name ${name} acquired!`);
        }

        onNameLost(connection, name) {
            this._log.debug(`Dbus name ${name} lost`);
        }

        disable() {
            // To avoid the below error
            // Avoid exporting the control interface twice when the extension is re-enabled.
            // when disable and enable this extension
            if (this._autostartDbusImpl) {
                this._autostartDbusImpl.flush();
                this._autostartDbusImpl.unexport();
                this._autostartDbusImpl = null;
            }

            if (this._dbusNameOwnerId) {
                Gio.bus_unown_name(this._dbusNameOwnerId);
                this._dbusNameOwnerId = 0;
            }

            if (this._autostartService) {
                this._autostartService._disable();
                this._autostartService = null;
            }
        }
    });

const AutostartService = GObject.registerClass(
    class AutostartService extends GObject.Object {

        _init() {
            super._init();

            this._log = new Log.Log();
            this._autostartDialog = null;
            this._restorePreviousSourceId = 0;
            this._idleIdOpenRestoreSessionDialog = 0;
            this._lastOperationUs = new Map();

            this._settings = PrefsUtils.getSettings();
            this._sessionName = this._settings.get_string(Constants.PREFS_SETTING_AUTORESTORE_SESSIONS);
            this._continuousSaver = new ContinuousSaver.ContinuousSaver(this._settings);
            this._recallRecorder = new RecallRecorder.RecallRecorder(this._settings);
        }

        Ping() {
            return 'SessionSifu 3.1.7 is ready';
        }

        _validSessionName(sessionName) {
            return typeof sessionName === 'string' &&
                /^[A-Za-z0-9][A-Za-z0-9 _.-]{0,63}$/.test(sessionName) &&
                sessionName !== FileUtils.sessions_backup_folder_name;
        }

        _allowOperation(name, minimumIntervalMs) {
            const now = GLib.get_monotonic_time();
            const previous = this._lastOperationUs.get(name) ?? 0;
            if (now - previous < minimumIntervalMs * 1000)
                return false;
            this._lastOperationUs.set(name, now);
            return true;
        }

        SaveSession(sessionName) {
            if (!this._allowOperation('save', 1000))
                return 'ERROR: Save request rate limit exceeded';
            if (!this._validSessionName(sessionName))
                return 'ERROR: Session name must be 1-64 safe characters';

            const saver = new SaveSession.SaveSession(true);
            saver.saveSessionAsync(sessionName).catch(error => this._log.error(error));
            return `Saving current desktop as '${sessionName}'`;
        }

        RestoreSession(sessionName) {
            if (!this._allowOperation('restore', 3000))
                return 'ERROR: Restore request rate limit exceeded';
            if (!this._validSessionName(sessionName))
                return 'ERROR: Invalid session name';

            const [exists] = FileUtils.sessionExists(sessionName);
            if (!exists)
                return `ERROR: Session '${sessionName}' does not exist`;

            Autoclose.autocloseObject.sessionClosedByUser = false;
            RestoreSession.restoreSessionObject.restoringApps = new Map();
            const restorer = new RestoreSession.RestoreSession();
            restorer.restoreSession(sessionName);
            return `Restoring session '${sessionName}'`;
        }

        DeleteSession(sessionName) {
            if (!this._allowOperation('delete-session', 1000))
                return 'ERROR: Delete request rate limit exceeded';
            if (!this._validSessionName(sessionName))
                return 'ERROR: Invalid session name';

            if (!FileUtils.sessionExists(sessionName)[0])
                return `ERROR: Session '${sessionName}' does not exist`;

            return FileUtils.trashSession(sessionName)
                ? `Moved session '${sessionName}' to Trash`
                : `ERROR: Could not move session '${sessionName}' to Trash`;
        }

        ListSessions() {
            const sessions = [];
            const directory = Gio.File.new_for_path(FileUtils.sessions_path);
            try {
                const enumerator = directory.enumerate_children(
                    'standard::name,standard::type,time::modified',
                    Gio.FileQueryInfoFlags.NONE,
                    null);
                let info;
                while ((info = enumerator.next_file(null))) {
                    if (info.get_file_type() !== Gio.FileType.REGULAR)
                        continue;
                    sessions.push({
                        name: info.get_name(),
                        modified: info.get_modification_date_time()?.to_unix() ?? 0,
                    });
                }
                enumerator.close(null);
            } catch (error) {
                if (!error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
                    this._log.error(error);
            }
            sessions.sort((a, b) => b.modified - a.modified);
            return JSON.stringify(sessions);
        }

        ListHistory() {
            return JSON.stringify(ContinuousSaver.listSnapshots());
        }

        SaveHistoryNow() {
            if (!this._allowOperation('save-history', 1000))
                return 'ERROR: Snapshot request rate limit exceeded';
            this._continuousSaver.saveNow(true).catch(error => this._log.error(error));
            return 'Saving an automatic snapshot now';
        }

        RestoreHistory(snapshotName) {
            if (!this._allowOperation('restore-history', 3000))
                return 'ERROR: Restore request rate limit exceeded';
            const path = ContinuousSaver.snapshotPath(snapshotName);
            if (!path || !GLib.file_test(path, GLib.FileTest.EXISTS))
                return 'ERROR: Automatic snapshot does not exist';

            Autoclose.autocloseObject.sessionClosedByUser = false;
            RestoreSession.restoreSessionObject.restoringApps = new Map();
            const restorer = new RestoreSession.RestoreSession();
            restorer.restoreSessionFromFile(path);
            return `Restoring automatic snapshot '${snapshotName}'`;
        }

        ListRecall(query) {
            return JSON.stringify(RecallRecorder.listRecall(
                query, this._settings.get_strv('recall-excluded-apps')));
        }

        CaptureRecallNow() {
            if (!this._allowOperation('capture-recall', 1000))
                return 'ERROR: Recall capture rate limit exceeded';
            if (!this._settings.get_boolean('recall-enabled'))
                return 'ERROR: Privacy Recall is disabled';
            this._recallRecorder.saveNow().catch(error => this._log.error(error));
            return 'Saving a private local Recall entry';
        }

        DeleteRecall() {
            if (!this._allowOperation('delete-recall', 3000))
                return 'ERROR: Recall delete rate limit exceeded';
            const removed = RecallRecorder.deleteRecall();
            return `Deleted ${removed} Privacy Recall entries`;
        }

        OpenManager() {
            try {
                Gio.Subprocess.new(
                    [FileUtils.getManagerExecutable()],
                    Gio.SubprocessFlags.NONE);
                return 'Opening SessionSifu';
            } catch (error) {
                this._log.error(error);
                return `ERROR: ${error.message}`;
            }
        }

        // Restore the session selected in preferences at login.
        RestoreSelectedSession() {
            const enableRestoreSelectedSession = this._settings.get_boolean('enable-autorestore-sessions');
            if (!enableRestoreSelectedSession) {
                const enableRestorePreviousSession = this._settings.get_boolean('enable-restore-previous-session');
                if (enableRestorePreviousSession) {
                    return "Ignoring this operation. RestoreSession is disabled, but RestorePreviousSession is enabled";
                }
                const disabledFeatureMsg = "ERROR: Selected-session restore is disabled";
                Main.notify('SessionSifu', disabledFeatureMsg);
                return disabledFeatureMsg;
            }

            const restoringMsg = `Restoring selected session '${this._sessionName}'`;
            this._log.info(restoringMsg);
            Main.notify('SessionSifu', restoringMsg);

            this._autostartDialog = new AutostartDialog();
            if (this._settings.get_boolean('restore-at-startup-without-asking')) {
                this._autostartDialog._confirm();
                return `Restore session '${this._sessionName}' without asking ...`;
            } else {
                // Since this._autostartDialog.open() is idempotent (it will check the dialog state),
                // it's ok to call it twice.
                // Before the startup-complete emits, `Main.pushModal(this, params).get_seat_state()`
                // returns CLUTTER_GRAB_STATE_NONE (0), which causes the dialog can't open. See: modalDialog.open() -> modalDialog.pushModal()
                Main.layoutManager.connect('startup-complete', () => {
                    this._idleIdOpenRestoreSessionDialog = GLib.idle_add(GLib.PRIORITY_LOW, () => {
                        this._autostartDialog.open();
                        this._idleIdOpenRestoreSessionDialog = null;
                        return GLib.SOURCE_REMOVE;
                    });
                });
                this._autostartDialog.open();
                return 'Opening dialog to restore ...';
            }

        }

        // TODO Press some hotkey (like Ctrl) so this time will not restore the previous session?
        // Call this method asynchronously through, for example:
        // `gdbus call --session --dest org.gnome.Shell.Extensions.SessionSifu --object-path /org/gnome/Shell/Extensions/SessionSifu --method org.gnome.Shell.Extensions.SessionSifu.Control.RestorePreviousSession "{'removeAfterRestore': <false>}"`
        // `gdbus call --session --dest org.gnome.Shell.Extensions.SessionSifu --object-path /org/gnome/Shell/Extensions/SessionSifu --method org.gnome.Shell.Extensions.SessionSifu.Control.RestorePreviousSession "{}"`
        RestorePreviousSession(args) {
            let removeAfterRestore = args.removeAfterRestore;
            if (removeAfterRestore) {
                removeAfterRestore = removeAfterRestore.get_boolean();
            } else {
                removeAfterRestore = true;
            }
            return this._restorePreviousSession(removeAfterRestore);
        }

        _restorePreviousSession(removeAfterRestore) {
            const enableRestorePreviousSession = this._settings.get_boolean('enable-restore-previous-session');
            if (!enableRestorePreviousSession) {
                const enableRestoreSelectedSession = this._settings.get_boolean('enable-autorestore-sessions');
                if (enableRestoreSelectedSession) {
                    return "Ignoring this operation. RestorePreviousSession is disabled, but RestoreSession is enabled";
                }
                const disabledFeatureMsg = "ERROR: RestorePreviousSession is disabled, please enable it through 'Preferences -> Restore sessions -> Restore previous apps and windows at startup'";
                Main.notify('SessionSifu', disabledFeatureMsg);
                return disabledFeatureMsg;
            }

            if (!Main.layoutManager._startingUp) {
                const msg = 'Restoring the previous apps and windows';
                this._log.info(`${msg}, gnome shell layoutManager has been started up.`);
                Main.notify('SessionSifu', msg);

                this._restorePreviousWithDelay(removeAfterRestore);
                return msg;
            } else {
                if (_requiredToRestorePrevious) return;

                _requiredToRestorePrevious = true;
                const msg = 'Required to restore the previous apps and windows';
                Main.notify('SessionSifu', msg);
                Main.layoutManager.connect('startup-complete', () => {
                    const msg = 'Restoring the previous apps and windows';
                    this._log.info(`${msg} after startup-complete`);
                    Main.notify('SessionSifu', msg);
                    this._restorePreviousWithDelay(removeAfterRestore);
                });
                return msg;
            }

        }

        _restorePreviousWithDelay(removeAfterRestore) {
            const restorePreviousDelay = this._settings.get_int('restore-previous-delay') * 1000;
            this._restorePreviousSourceId = GLib.timeout_add(GLib.PRIORITY_LOW, restorePreviousDelay,
                () => {
                    this._restorePreviousSourceId = 0;
                    const restoreSession = new RestoreSession.RestoreSession();
                    restoreSession.restorePreviousSession(removeAfterRestore);
                    return GLib.SOURCE_REMOVE;
                });
        }

        _disable() {
            if (this._continuousSaver) {
                this._continuousSaver.destroy();
                this._continuousSaver = null;
            }
            if (this._recallRecorder) {
                this._recallRecorder.destroy();
                this._recallRecorder = null;
            }
            if (this._autostartDialog) {
                this._autostartDialog.destroy();
                this._autostartDialog = null;
            }
            if (this._restorePreviousSourceId) {
                GLib.Source.remove(this._restorePreviousSourceId);
                this._restorePreviousSourceId = null;
            }
            if (this._idleIdOpenRestoreSessionDialog) {
                GLib.Source.remove(this._idleIdOpenRestoreSessionDialog);
                this._idleIdOpenRestoreSessionDialog = null;
            }
        }

    });

// Based on endSessionDialog in Gnome shell
const AutostartDialog = GObject.registerClass(
    class AutostartDialog extends ModalDialog.ModalDialog {

        _init() {
            super._init({
                styleClass: 'restore-session-dialog',
                destroyOnClose: true
            });

            this._settings = PrefsUtils.getSettings();

            this._sessionName = this._settings.get_string(Constants.PREFS_SETTING_AUTORESTORE_SESSIONS);

            this._totalSecondsToStayOpen = this._settings.get_int('autorestore-sessions-timer');
            this._secondsLeft = 0;

            this.connect('opened', this._onOpened.bind(this));

            this._confirmDialogContent = new Dialog.MessageDialogContent();
            this._confirmDialogContent.title = `Restore session '${this._sessionName}'`;

            this.addButton({
                action: this._cancel.bind(this),
                label: _('Cancel'),
                key: Clutter.KEY_Escape,
            });

            this._confirmButton = this.addButton({
                action: () => {
                    this.close();
                    let signalId = this.connect('closed', () => {
                        this.disconnect(signalId);
                        this._confirm();
                    });
                },
                label: _('Confirm'),
            });

            this.contentLayout.add_child(this._confirmDialogContent);

        }

        _confirm() {
            Autoclose.autocloseObject.sessionClosedByUser = false;
            const _restoreSession = new RestoreSession.RestoreSession();
            _restoreSession.restoreSession(this._sessionName);
        }

        _cancel() {
            this.close();
        }

        _onOpened() {
            let open = this.state == ModalDialog.State.OPENING || this.state == ModalDialog.State.OPENED;
            if (!open)
                return;

            if (this._sessionName) {
                const [exists, sessionFilePath] = FileUtils.sessionExists(this._sessionName);
                if (exists) {
                    this._startTimer();
                    this._sync();
                } else {
                    this._confirmDialogContent.description = `ERROR: Session '${this._sessionName}' does not exist`;
                    this._confirmDialogContent._description.set_style('color:red;');
                    this._confirmButton.set_reactive(false);
                }
            } else {
                this._confirmDialogContent.description = "ERROR: You don't select any session to restore";
                this._confirmDialogContent._description.set_style('color:red;');
                this._confirmButton.set_reactive(false);
            }
        }

        _sync() {

            const displayTime = EndSessionDialog._roundSecondsToInterval(this._totalSecondsToStayOpen,
                                                                         this._secondsLeft,
                                                                         1);
            const desc = _.ngettext('\'' + this._sessionName + '\' will be restored in %d second',
                '\'' + this._sessionName + '\' will be restored in %d seconds', displayTime).format(displayTime);
            this._confirmDialogContent.description = desc;

        }

        _startTimer() {
            let startTime = GLib.get_monotonic_time();
            this._secondsLeft = this._totalSecondsToStayOpen;

            this._timerId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 1, () => {
                let currentTime = GLib.get_monotonic_time();
                let secondsElapsed = (currentTime - startTime) / 1000000;

                this._secondsLeft = this._totalSecondsToStayOpen - secondsElapsed;
                if (this._secondsLeft > 0) {
                    this._sync();
                    return GLib.SOURCE_CONTINUE;
                }

                this._confirm();
                this.close();
                this._timerId = 0;

                return GLib.SOURCE_REMOVE;
            });
            GLib.Source.set_name_by_id(this._timerId, '[gnome-shell-extension-sessionsifu] this._confirm');
        }

        destroy() {
            if (this._timerId > 0) {
                GLib.source_remove(this._timerId);
                this._timerId = 0;
            }
            this._secondsLeft = 0;
        }


    });
