'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as FileUtils from './utils/fileUtils.js';
import * as Log from './utils/log.js';
import * as SaveSession from './saveSession.js';


export const SNAPSHOT_PATTERN = /^auto-\d{8}-\d{6}\.json$/;

function snapshotName() {
    const now = new Date();
    const compact = now.toISOString()
        .replaceAll('-', '')
        .replaceAll(':', '')
        .replace('T', '-')
        .slice(0, 15);
    return `auto-${compact}.json`;
}

export function snapshotPath(name) {
    if (!SNAPSHOT_PATTERN.test(name))
        return null;
    return GLib.build_filenamev([FileUtils.history_path, name]);
}

export function listSnapshots() {
    const snapshots = [];
    const directory = Gio.File.new_for_path(FileUtils.history_path);
    try {
        const enumerator = directory.enumerate_children(
            'standard::name,standard::type,time::modified',
            Gio.FileQueryInfoFlags.NONE,
            null);
        let info;
        while ((info = enumerator.next_file(null))) {
            const name = info.get_name();
            if (info.get_file_type() !== Gio.FileType.REGULAR ||
                !SNAPSHOT_PATTERN.test(name))
                continue;
            snapshots.push({
                name,
                modified: info.get_modification_date_time()?.to_unix() ?? 0,
            });
        }
        enumerator.close(null);
    } catch (error) {
        if (!error.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
            Log.Log.getDefault().error(error);
    }
    snapshots.sort((a, b) => b.modified - a.modified || b.name.localeCompare(a.name));
    return snapshots;
}

export const ContinuousSaver = class {
    constructor(settings) {
        this._settings = settings;
        this._log = new Log.Log();
        this._initialTimeoutId = 0;
        this._periodicTimeoutId = 0;
        this._saving = false;
        this._settingsIds = [
            this._settings.connect('changed::continuous-save-enabled', () => this._reschedule()),
            this._settings.connect('changed::continuous-save-interval', () => this._reschedule()),
        ];
        this._reschedule();
    }

    _removeTimers() {
        for (const property of ['_initialTimeoutId', '_periodicTimeoutId']) {
            if (this[property]) {
                GLib.Source.remove(this[property]);
                this[property] = 0;
            }
        }
    }

    _reschedule() {
        this._removeTimers();
        if (!this._settings.get_boolean('continuous-save-enabled'))
            return;

        const interval = Math.max(60, this._settings.get_int('continuous-save-interval'));
        this._initialTimeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_LOW,
            Math.min(30, interval),
            () => {
                this._initialTimeoutId = 0;
                this.saveNow();
                return GLib.SOURCE_REMOVE;
            });
        this._periodicTimeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_LOW,
            interval,
            () => {
                this.saveNow();
                return GLib.SOURCE_CONTINUE;
            });
    }

    async saveNow(force = false) {
        if (this._saving || (!force && !this._settings.get_boolean('continuous-save-enabled')))
            return false;
        this._saving = true;
        try {
            const name = snapshotName();
            const saver = new SaveSession.SaveSession(false);
            const saved = await saver.saveSessionAsync(name, FileUtils.history_path, false);
            if (!saved)
                return false;
            this._prune();
            return true;
        } catch (error) {
            this._log.error(error);
            return false;
        } finally {
            this._saving = false;
        }
    }

    _prune() {
        for (const snapshot of listSnapshots().slice(FileUtils.history_limit)) {
            const path = snapshotPath(snapshot.name);
            try {
                Gio.File.new_for_path(path).delete(null);
                this._log.info(`Removed old automatic snapshot ${path}`);
            } catch (error) {
                this._log.error(error);
            }
        }
    }

    destroy() {
        this._removeTimers();
        for (const id of this._settingsIds)
            this._settings.disconnect(id);
        this._settingsIds = [];
        this._settings = null;
    }
};
