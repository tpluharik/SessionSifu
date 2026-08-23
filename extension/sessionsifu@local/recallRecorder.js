'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import * as FileUtils from './utils/fileUtils.js';
import * as Log from './utils/log.js';
import * as MetaWindowUtils from './utils/metaWindowUtils.js';
import * as SaveSession from './saveSession.js';
import {recallActivity} from './recallActivity.js';
import {recallExclusions, screenshotBlockingExclusions} from './recallPrivacy.js';


export const RECALL_PATTERN = /^recall-\d{8}-\d{6}-\d{3}\.json$/;
export const RECALL_LIMIT = 500;
const MAX_RECALL_BYTES = 2 * 1024 * 1024;
const MAX_SCREENSHOT_BYTES = 64 * 1024 * 1024;
const MAX_DISPLAYS = 8;
const MAX_WINDOW_PREVIEWS = 64;
const PRUNE_INTERVAL_US = 5 * 60 * 1000 * 1000;
const _summaryCache = new Map();

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

function _screenshotPath(name) {
    return GLib.build_filenamev([
        FileUtils.recall_path, name.replace(/\.json$/, '.png')]);
}

function _rawScreenshotPath(name) {
    return GLib.build_filenamev([
        FileUtils.recall_path, name.replace(/\.json$/, '-raw.png')]);
}

function _displayScreenshotPath(name, index) {
    return GLib.build_filenamev([
        FileUtils.recall_path, name.replace(/\.json$/, `-display-${index}.jpg`)]);
}

function _windowScreenshotPath(name, index, raw = false) {
    return GLib.build_filenamev([
        FileUtils.recall_path,
        name.replace(/\.json$/, `-window-${index}${raw ? '-raw.png' : '.jpg'}`),
    ]);
}

function _removeFile(path) {
    try {
        Gio.File.new_for_path(path).delete(null);
    } catch (error) {
        if (!error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
            Log.Log.getDefault().error(error, `Could not delete Recall screenshot ${path}`);
    }
}

function _removeScreenshots(name) {
    _removeFile(_screenshotPath(name));
    _removeFile(_rawScreenshotPath(name));
    for (let index = 0; index < MAX_DISPLAYS; index++)
        _removeFile(_displayScreenshotPath(name, index));
    for (let index = 0; index < MAX_WINDOW_PREVIEWS; index++) {
        _removeFile(_windowScreenshotPath(name, index));
        _removeFile(_windowScreenshotPath(name, index, true));
    }
}

function _invalidateSummary(name) {
    _summaryCache.delete(GLib.build_filenamev([FileUtils.recall_path, name]));
}

function _excludedApplicationVisible(excludedApps = []) {
    const exclusions = screenshotBlockingExclusions(excludedApps);
    if (!exclusions.length)
        return false;
    const tracker = Shell.WindowTracker.get_default();
    for (const actor of global.get_window_actors()) {
        const window = actor.meta_window;
        if (!window || !window.showing_on_its_workspace?.())
            continue;
        const app = tracker.get_window_app(window);
        const identity = [
            app?.get_id?.(), app?.get_name?.(), window.get_wm_class?.(),
            window.get_wm_class_instance?.(),
        ].map(value => String(value ?? '').toLowerCase()).join('\n');
        if (exclusions.some(value => identity.includes(value)))
            return true;
    }
    return false;
}

function _captureScreenshot(path) {
    return new Promise((resolve, reject) => {
        let stream;
        try {
            stream = Gio.File.new_for_path(path).replace(
                null, false, Gio.FileCreateFlags.PRIVATE, null);
            const screenshot = new Shell.Screenshot();
            screenshot.screenshot(false, stream, (source, result) => {
                try {
                    const [success] = source.screenshot_finish(result);
                    stream.close(null);
                    if (!success)
                        throw new Error('GNOME Shell did not return a screenshot');
                    const size = Gio.File.new_for_path(path).query_info(
                        'standard::size', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null)
                        .get_size();
                    if (size <= 0 || size > MAX_SCREENSHOT_BYTES)
                        throw new Error(`Recall screenshot has an unsafe size: ${size}`);
                    GLib.chmod(path, 0o600);
                    resolve(path);
                } catch (error) {
                    try {
                        stream.close(null);
                    } catch (_) {
                        // The callback may already have closed the stream.
                    }
                    _removeFile(path);
                    reject(error);
                }
            });
        } catch (error) {
            try {
                stream?.close(null);
            } catch (_) {
                // Ignore cleanup failures while reporting the original error.
            }
            reject(error);
        }
    });
}

function _captureWindowActor(path, actor) {
    return new Promise((resolve, reject) => {
        let stream;
        try {
            if (!actor || actor.is_destroyed?.())
                throw new Error('Recall window actor is no longer available');
            const content = actor.paint_to_content(null);
            const texture = content?.get_texture?.();
            if (!texture)
                throw new Error('Recall window has no renderable surface');
            stream = Gio.File.new_for_path(path).replace(
                null, false, Gio.FileCreateFlags.PRIVATE, null);
            Shell.Screenshot.composite_to_stream(
                texture, 0, 0, -1, -1, 1.0,
                null, 0, 0, 1.0, stream,
                (_source, result) => {
                    try {
                        const pixbuf = Shell.Screenshot.composite_to_stream_finish(result);
                        stream.close(null);
                        if (!pixbuf)
                            throw new Error('GNOME Shell could not render the Recall window');
                        const size = Gio.File.new_for_path(path).query_info(
                            'standard::size', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null)
                            .get_size();
                        if (size <= 0 || size > MAX_SCREENSHOT_BYTES)
                            throw new Error(`Recall window screenshot has an unsafe size: ${size}`);
                        GLib.chmod(path, 0o600);
                        resolve(true);
                    } catch (error) {
                        try {
                            stream.close(null);
                        } catch (_) {
                            // The callback may already have closed the stream.
                        }
                        _removeFile(path);
                        reject(error);
                    }
                });
        } catch (error) {
            try {
                stream?.close(null);
            } catch (_) {
                // Ignore cleanup failures while reporting the original error.
            }
            _removeFile(path);
            reject(error);
        }
    });
}

async function _captureWindowActors(name) {
    const path = GLib.build_filenamev([FileUtils.recall_path, name]);
    const file = Gio.File.new_for_path(path);
    const [ok, contents] = file.load_contents(null);
    if (!ok)
        return 0;
    const payload = JSON.parse(new TextDecoder().decode(contents));
    const windowIndexes = new Map(
        (payload.x_session_config_objects ?? [])
            .slice(0, MAX_WINDOW_PREVIEWS)
            .map((window, index) => [String(window.window_id ?? ''), index])
            .filter(([windowId]) => windowId));
    if (!windowIndexes.size)
        return 0;
    const jobs = [];
    for (const actor of global.get_window_actors()) {
        if (jobs.length >= MAX_WINDOW_PREVIEWS)
            break;
        const metaWindow = actor?.meta_window;
        if (!metaWindow)
            continue;
        const index = windowIndexes.get(MetaWindowUtils.getStableWindowId(metaWindow));
        if (index === undefined)
            continue;
        jobs.push([index, actor]);
    }
    let captured = 0;
    // Small batches reduce latency without flooding Mutter with paint requests.
    for (let offset = 0; offset < jobs.length; offset += 4) {
        const results = await Promise.allSettled(
            jobs.slice(offset, offset + 4).map(([index, actor]) =>
                _captureWindowActor(_windowScreenshotPath(name, index, true), actor)));
        captured += results.filter(result => result.status === 'fulfilled').length;
    }
    return captured;
}

function _compressScreenshot(rawPath, name, displays) {
    return new Promise((resolve, reject) => {
        try {
            const stem = GLib.build_filenamev([
                FileUtils.recall_path, name.replace(/\.json$/, '')]);
            const process = Gio.Subprocess.new([
                FileUtils.getManagerExecutable(),
                '--compress-recall-preview',
                rawPath,
                stem,
                '--display-layout',
                JSON.stringify(displays),
            ], Gio.SubprocessFlags.STDERR_PIPE);
            process.communicate_utf8_async(null, null, (source, result) => {
                try {
                    const [, , stderr] = source.communicate_utf8_finish(result);
                    if (!source.get_successful())
                        throw new Error(stderr?.trim() || 'Recall preview compressor failed');
                    resolve(true);
                } catch (error) {
                    reject(error);
                }
            });
        } catch (error) {
            reject(error);
        }
    });
}

function _finalizeCapture(name) {
    recallActivity.begin();
    try {
        const path = GLib.build_filenamev([FileUtils.recall_path, name]);
        const process = Gio.Subprocess.new([
            FileUtils.getManagerExecutable(), '--finalize-recall', path,
        ], Gio.SubprocessFlags.STDERR_PIPE);
        process.communicate_utf8_async(null, null, (source, result) => {
            try {
                const [, , stderr] = source.communicate_utf8_finish(result);
                if (!source.get_successful())
                    throw new Error(stderr?.trim() || 'Recall vault finalization failed');
            } catch (error) {
                Log.Log.getDefault().error(error, 'Could not finalize encrypted Recall capture');
                _removeFile(path);
                _removeScreenshots(name);
            } finally {
                recallActivity.end();
            }
        });
    } catch (error) {
        Log.Log.getDefault().error(error, 'Could not start Recall vault finalization');
        const path = GLib.build_filenamev([FileUtils.recall_path, name]);
        _removeFile(path);
        _removeScreenshots(name);
        recallActivity.end();
    }
}

function _summary(entry, excludedApps = []) {
    if (entry.size <= 0 || entry.size > MAX_RECALL_BYTES)
        return null;
    const exclusions = recallExclusions(excludedApps);
    const exclusionsKey = exclusions.join('\n');
    const cached = _summaryCache.get(entry.path);
    if (cached?.modified === entry.modified && cached?.size === entry.size &&
        cached?.exclusionsKey === exclusionsKey)
        return cached.summary;
    try {
        const file = Gio.File.new_for_path(entry.path);
        const [ok, contents] = file.load_contents(null);
        if (!ok)
            return null;
        const payload = JSON.parse(new TextDecoder().decode(contents));
        if (![1, 2].includes(payload.recall_schema) ||
            !Array.isArray(payload.x_session_config_objects))
            return null;
        const apps = [];
        const titles = [];
        const files = [];
        const windows = [];
        let includedWindows = 0;
        for (const window of payload.x_session_config_objects.slice(0, 512)) {
            const identity = [window.app_name, window.desktop_file_id, window.wm_class]
                .map(value => String(value ?? '').toLowerCase())
                .join('\n');
            if (exclusions.some(value => identity.includes(value)))
                continue;
            includedWindows++;
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
            const position = window.window_position ?? {};
            windows.push({
                app,
                title,
                files: (window.open_files ?? []).slice(0, 32)
                    .map(path => String(path).slice(0, 4096)),
                monitor: Number.isInteger(window.monitor_number)
                    ? window.monitor_number
                    : 0,
                x: Number(position.x_offset),
                y: Number(position.y_offset),
                width: Number(position.width),
                height: Number(position.height),
            });
        }
        if (!includedWindows) {
            _summaryCache.set(entry.path, {
                modified: entry.modified,
                size: entry.size,
                exclusionsKey,
                summary: null,
            });
            return null;
        }
        const displays = (payload.recall_displays ?? [])
            .slice(0, MAX_DISPLAYS)
            .map((display, fallbackIndex) => ({
                index: Number.isInteger(display.index) ? display.index : fallbackIndex,
                x: Number(display.x),
                y: Number(display.y),
                width: Number(display.width),
                height: Number(display.height),
            }))
            .filter(display => Number.isFinite(display.x) && Number.isFinite(display.y) &&
                Number.isFinite(display.width) && Number.isFinite(display.height) &&
                display.width > 0 && display.height > 0);
        const screenshots = displays
            .map(display => ({
                ...display,
                path: _displayScreenshotPath(entry.name, display.index),
            }))
            .filter(display => GLib.file_test(display.path, GLib.FileTest.IS_REGULAR));
        const legacyScreenshot = _screenshotPath(entry.name);
        const summary = {
            name: entry.name,
            modified: entry.modified,
            captured_at: String(payload.session_create_time ?? ''),
            apps,
            titles,
            files,
            screenshots,
            screenshot: GLib.file_test(legacyScreenshot, GLib.FileTest.IS_REGULAR)
                ? legacyScreenshot
                : '',
            _windows: windows,
        };
        _summaryCache.set(entry.path, {
            modified: entry.modified,
            size: entry.size,
            exclusionsKey,
            summary,
        });
        return summary;
    } catch (error) {
        _summaryCache.delete(entry.path);
        Log.Log.getDefault().error(error, `Could not read Privacy Recall entry ${entry.path}`);
        return null;
    }
}

export function listRecall(query = '', excludedApps = []) {
    const needle = String(query).trim().toLowerCase().slice(0, 256);
    const results = [];
    for (const entry of _entryFiles()) {
        const summary = _summary(entry, excludedApps);
        if (!summary)
            continue;
        const searchable = [...summary.apps, ...summary.titles, ...summary.files]
            .join('\n').toLowerCase();
        if (!needle || searchable.includes(needle)) {
            const result = {...summary};
            delete result._windows;
            result.matches = needle
                ? summary._windows.filter(window => [
                    window.app, window.title, ...window.files,
                ].join('\n').toLowerCase().includes(needle))
                    .filter(window => Number.isFinite(window.x) &&
                        Number.isFinite(window.y) && Number.isFinite(window.width) &&
                        Number.isFinite(window.height) && window.width > 0 && window.height > 0)
                    .slice(0, 12)
                : [];
            results.push(result);
        }
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
            _removeScreenshots(entry.name);
            _summaryCache.delete(entry.path);
            removed++;
        } catch (error) {
            Log.Log.getDefault().error(error, `Could not delete Privacy Recall entry ${entry.path}`);
        }
    }
    return removed;
}

export function deleteRecallScreenshots() {
    let removed = 0;
    for (const entry of _entryFiles()) {
        const candidates = [_screenshotPath(entry.name), _rawScreenshotPath(entry.name)];
        for (let index = 0; index < MAX_DISPLAYS; index++)
            candidates.push(_displayScreenshotPath(entry.name, index));
        for (let index = 0; index < MAX_WINDOW_PREVIEWS; index++) {
            candidates.push(_windowScreenshotPath(entry.name, index));
            candidates.push(_windowScreenshotPath(entry.name, index, true));
        }
        for (const path of candidates) {
            if (!GLib.file_test(path, GLib.FileTest.IS_REGULAR))
                continue;
            _removeFile(path);
            removed++;
        }
        _summaryCache.delete(entry.path);
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
        this._screenshotSaving = false;
        this._screenshotGeneration = 0;
        this._lastPruneUs = 0;
        this._destroyed = false;
        this._settingsIds = [
            this._settings.connect('changed::recall-enabled', () => this._reschedule()),
            this._settings.connect('changed::recall-interval', () => this._reschedule()),
            this._settings.connect('changed::recall-pause-until', () => this._reschedule()),
            this._settings.connect('changed::recall-retention-hours', () => this._prune(true)),
            this._settings.connect('changed::recall-excluded-apps', () => {
                this._screenshotGeneration++;
                const removed = deleteRecallScreenshots();
                this._log.info(
                    `Recall exclusions changed; removed ${removed} existing screenshot previews`);
            }),
            this._settings.connect('changed::recall-capture-screenshots', () => {
                if (this._settings.get_boolean('recall-capture-screenshots'))
                    return;
                this._screenshotGeneration++;
                const removed = deleteRecallScreenshots();
                this._log.info(`Recall screenshots disabled; removed ${removed} previews`);
            }),
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
        const pausedUntil = this._settings.get_int64('recall-pause-until');
        if (pausedUntil < 0 || pausedUntil > Math.floor(Date.now() / 1000))
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
        const pausedUntil = this._settings.get_int64('recall-pause-until');
        if (pausedUntil < 0 || pausedUntil > Math.floor(Date.now() / 1000))
            return false;
        if (pausedUntil > 0)
            this._settings.set_int64('recall-pause-until', 0);
        this._saving = true;
        recallActivity.begin();
        const startedUs = GLib.get_monotonic_time();
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
            this._log.debug(
                `Recall metadata saved in ${Math.round((GLib.get_monotonic_time() - startedUs) / 1000)} ms`);
            let finalizeWithScreenshot = false;
            if (this._settings.get_boolean('recall-capture-screenshots')) {
                const screenshotGeneration = this._screenshotGeneration;
                const screenshotExclusions = this._settings.get_strv('recall-excluded-apps');
                if (Main.sessionMode.isLocked ||
                    _excludedApplicationVisible(screenshotExclusions)) {
                    this._log.info(
                        'Skipped Recall screenshot because the session is locked or an excluded app is visible');
                } else if (this._screenshotSaving) {
                    this._log.info(
                        'Skipped Recall screenshot because the previous preview is still encoding');
                } else {
                    finalizeWithScreenshot = true;
                    this._captureScreenshotForEntry(
                        name, screenshotGeneration, screenshotExclusions,
                        Main.layoutManager.monitors
                            .slice(0, MAX_DISPLAYS)
                            .map((monitor, index) => ({
                                index,
                                x: Math.trunc(monitor.x),
                                y: Math.trunc(monitor.y),
                                width: Math.trunc(monitor.width),
                                height: Math.trunc(monitor.height),
                            }))
                            .filter(monitor => monitor.width > 0 && monitor.height > 0));
                }
            }
            if (!finalizeWithScreenshot)
                _finalizeCapture(name);
            this._prune();
            return true;
        } catch (error) {
            this._log.error(error, 'Privacy Recall capture failed');
            return false;
        } finally {
            this._saving = false;
            recallActivity.end();
        }
    }

    async _captureScreenshotForEntry(name, screenshotGeneration, exclusions, displays) {
        this._screenshotSaving = true;
        recallActivity.begin();
        try {
            if (!displays.length)
                throw new Error('No active displays are available for Recall preview capture');
            const rawPath = _rawScreenshotPath(name);
            await _captureScreenshot(rawPath);
            await _captureWindowActors(name);
            if (this._destroyed || screenshotGeneration !== this._screenshotGeneration ||
                Main.sessionMode.isLocked || _excludedApplicationVisible(exclusions)) {
                _removeScreenshots(name);
                return;
            }
            await _compressScreenshot(rawPath, name, displays);
            if (this._destroyed || screenshotGeneration !== this._screenshotGeneration ||
                Main.sessionMode.isLocked || _excludedApplicationVisible(exclusions))
                _removeScreenshots(name);
            _invalidateSummary(name);
        } catch (error) {
            _removeScreenshots(name);
            this._log.error(error, 'Could not capture Recall screenshot preview');
        } finally {
            if (!this._destroyed)
                _finalizeCapture(name);
            this._screenshotSaving = false;
            recallActivity.end();
        }
    }

    _prune(force = false) {
        const nowUs = GLib.get_monotonic_time();
        if (!force && this._lastPruneUs &&
            nowUs - this._lastPruneUs < PRUNE_INTERVAL_US)
            return;
        this._lastPruneUs = nowUs;
        const retention = Math.max(
            1, Math.min(720, this._settings.get_int('recall-retention-hours')));
        const cutoff = Math.floor(Date.now() / 1000) - retention * 60 * 60;
        for (const [index, entry] of _entryFiles().entries()) {
            if (index < RECALL_LIMIT && entry.modified >= cutoff)
                continue;
            try {
                Gio.File.new_for_path(entry.path).delete(null);
                _removeScreenshots(entry.name);
                _summaryCache.delete(entry.path);
            } catch (error) {
                this._log.error(error, `Could not prune Privacy Recall entry ${entry.path}`);
            }
        }
    }

    destroy() {
        this._destroyed = true;
        this._screenshotGeneration++;
        this._removeTimers();
        for (const id of this._settingsIds)
            this._settings.disconnect(id);
        this._settingsIds = [];
        this._settings = null;
    }
};
