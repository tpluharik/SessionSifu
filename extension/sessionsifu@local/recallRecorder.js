'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as FileUtils from './utils/fileUtils.js';
import * as Log from './utils/log.js';
import * as SaveSession from './saveSession.js';


export const RECALL_PATTERN = /^recall-\d{8}-\d{6}-\d{3}\.json$/;
export const RECALL_LIMIT = 500;
const MAX_RECALL_BYTES = 2 * 1024 * 1024;

export function recallName(now = new Date()) {
    const iso = now.toISOString();
    const compact = iso
        .replaceAll('-', '')
        .replaceAll(':', '')
        .replace('T', '-')
        .slice(0, 15);
    return `recall-${compact}-${iso.slice(20, 23)}.json`;
}

function _ensurePrivateDirectory() {
    if (GLib.file_test(FileUtils.recall_path, GLib.FileTest.IS_SYMLINK))
        throw new Error('Refusing to use a symbolic link for Privacy Recall storage');
    if (GLib.mkdir_with_parents(FileUtils.recall_path, 0o700) !== 0)
        throw new Error(`Could not create Privacy Recall storage: ${FileUtils.recall_path}`);
    GLib.chmod(FileUtils.recall_path, 0o700);
}

function _entryFiles() {
    const entries = [];
    const directory = Gio.File.new_for_path(FileUtils.recall_path);
    try {
        const enumerator = directory.enumerate_children(
            'standard::name,standard::type,standard::is-symlink,standard::size,time::modified',
            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
            null);
        let info;
        while ((info = enumerator.next_file(null))) {
            if (info.get_file_type() !== Gio.FileType.REGULAR ||
                info.get_is_symlink() || !RECALL_PATTERN.test(info.get_name()))
                continue;
            entries.push({
                name: info.get_name(),
                path: GLib.build_filenamev([FileUtils.recall_path, info.get_name()]),
                modified: info.get_modification_date_time()?.to_unix() ?? 0,
                size: info.get_size(),
            });
        }
        enumerator.close(null);
    } catch (error) {
        if (!error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
            Log.Log.getDefault().error(error);
    }
    entries.sort((a, b) => b.modified - a.modified || b.name.localeCompare(a.name));
    return entries;
}

function _summary(entry) {
    if (entry.size <= 0 || entry.size > MAX_RECALL_BYTES)
        return null;
    try {
        const file = Gio.File.new_for_path(entry.path);
        const [ok, contents] = file.load_contents(null);
        if (!ok)
            return null;
        const payload = JSON.parse(new TextDecoder().decode(contents));
        if (payload.recall_schema !== 1 || !Array.isArray(payload.x_session_config_objects))
            return null;
        const apps = [];
        const titles = [];
        const files = [];
        for (const window of payload.x_session_config_objects.slice(0, 512)) {
            const app = String(window.app_name ?? window.desktop_file_id ?? '').slice(0, 512);
            const title = String(window.window_title ?? '').slice(0, 4096);
            if (app && !apps.includes(app))
                apps.push(app);
            if (title && !titles.includes(title))
                titles.push(title);
            for (const path of (window.open_files ?? []).slice(0, 32)) {
                const value = String(path).slice(0, 4096);
                if (value && !files.includes(value))
                    files.push(value);
            }
        }
        return {
            name: entry.name,
            modified: entry.modified,
            captured_at: String(payload.session_create_time ?? ''),
            apps,
            titles,
            files,
        };
    } catch (error) {
        Log.Log.getDefault().error(error, `Could not read Privacy Recall entry ${entry.path}`);
        return null;
    }
}

export function listRecall(query = '') {
    const needle = String(query).trim().toLowerCase().slice(0, 256);
    const results = [];
    for (const entry of _entryFiles()) {
        const summary = _summary(entry);
        if (!summary)
            continue;
        const searchable = [...summary.apps, ...summary.titles, ...summary.files]
            .join('\n').toLowerCase();
        if (!needle || searchable.includes(needle))
            results.push(summary);
        if (results.length >= 100)
            break;
    }
    return results;
}

export function deleteRecall() {
    let removed = 0;
    for (const entry of _entryFiles()) {
        try {
            Gio.File.new_for_path(entry.path).delete(null);
            removed++;
        } catch (error) {
            Log.Log.getDefault().error(error, `Could not delete Privacy Recall entry ${entry.path}`);
        }
    }
    return removed;
}

export const RecallRecorder = class {
    constructor(settings) {
        this._settings = settings;
        this._log = new Log.Log();
        this._initialTimeoutId = 0;
        this._periodicTimeoutId = 0;
        this._saving = false;
        this._settingsIds = [
            this._settings.connect('changed::recall-enabled', () => this._reschedule()),
            this._settings.connect('changed::recall-interval', () => this._reschedule()),
            this._settings.connect('changed::recall-retention-hours', () => this._prune()),
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
        if (!this._settings.get_boolean('recall-enabled'))
            return;
        const interval = Math.max(60, this._settings.get_int('recall-interval'));
        this._initialTimeoutId = GLib.timeout_add_seconds(
            GLib.PRIORITY_LOW,
            Math.min(60, interval),
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

    async saveNow() {
        if (this._saving || !this._settings.get_boolean('recall-enabled'))
            return false;
        this._saving = true;
        try {
            _ensurePrivateDirectory();
            const name = recallName();
            const saver = new SaveSession.SaveSession(false);
            const saved = await saver.saveRecallAsync(
                name,
                FileUtils.recall_path,
                this._settings.get_strv('recall-excluded-apps'),
                this._settings.get_boolean('recall-include-file-paths'));
            if (!saved)
                return false;
            const path = GLib.build_filenamev([FileUtils.recall_path, name]);
            GLib.chmod(path, 0o600);
            this._prune();
            return true;
        } catch (error) {
            this._log.error(error, 'Privacy Recall capture failed');
            return false;
        } finally {
            this._saving = false;
        }
    }

    _prune() {
        const retention = Math.max(
            1, Math.min(720, this._settings.get_int('recall-retention-hours')));
        const cutoff = Math.floor(Date.now() / 1000) - retention * 60 * 60;
        for (const [index, entry] of _entryFiles().entries()) {
            if (index < RECALL_LIMIT && entry.modified >= cutoff)
                continue;
            try {
                Gio.File.new_for_path(entry.path).delete(null);
            } catch (error) {
                this._log.error(error, `Could not prune Privacy Recall entry ${entry.path}`);
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
