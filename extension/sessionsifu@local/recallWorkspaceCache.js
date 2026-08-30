'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as FileUtils from './utils/fileUtils.js';
import * as Log from './utils/log.js';


export const CACHE_LIMIT = 64;
export const CACHE_TOTAL_BYTES = 64 * 1024 * 1024;
export const CACHE_MAX_AGE_SECONDS = 30 * 24 * 60 * 60;
const MAX_CACHE_FILE_BYTES = 16 * 1024 * 1024;
const _previews = new Map();
let _serial = 0;

function _key(windowId) {
    const value = String(windowId ?? '');
    return value
        ? GLib.compute_checksum_for_string(GLib.ChecksumType.SHA256, value, -1)
        : '';
}

function _ensurePrivateDirectory() {
    if (GLib.file_test(FileUtils.recall_window_cache_path, GLib.FileTest.IS_SYMLINK))
        throw new Error('Refusing symbolic-link Recall workspace staging');
    if (GLib.mkdir_with_parents(FileUtils.recall_window_cache_path, 0o700) !== 0)
        throw new Error('Could not create private Recall workspace staging');
    GLib.chmod(FileUtils.recall_window_cache_path, 0o700);
}

export function capturePath(windowId) {
    const key = _key(windowId);
    if (!key)
        return null;
    _ensurePrivateDirectory();
    return GLib.build_filenamev([
        FileUtils.recall_window_cache_path,
        `.capture-${key}-${GLib.uuid_string_random()}.png`,
    ]);
}

export function storePreview(windowId, sourcePath, context = '') {
    const key = _key(windowId);
    if (!key)
        return false;
    const source = Gio.File.new_for_path(sourcePath);
    const info = source.query_info(
        'standard::type,standard::is-symlink,standard::size,time::modified',
        Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
    if (info.get_file_type() !== Gio.FileType.REGULAR || info.get_is_symlink() ||
        info.get_size() <= 0 || info.get_size() > MAX_CACHE_FILE_BYTES)
        return false;
    const [ok, bytes] = source.load_contents(null);
    if (!ok || bytes.length <= 0 || bytes.length > MAX_CACHE_FILE_BYTES)
        return false;
    _previews.get(key)?.bytes.fill(0);
    _previews.set(key, {
        bytes,
        context: String(context),
        serial: ++_serial,
        modified: info.get_modification_date_time()?.to_unix() ?? Math.floor(Date.now() / 1000),
    });
    prunePreviewCache();
    return _previews.has(key);
}

export function restorePreview(
    windowId, targetPath, maxAgeSeconds = CACHE_MAX_AGE_SECONDS, context = ''
) {
    const preview = _previews.get(_key(windowId));
    if (!preview || preview.context !== String(context) ||
        GLib.file_test(targetPath, GLib.FileTest.IS_SYMLINK))
        return 0;
    const now = Math.floor(Date.now() / 1000);
    if (!preview.modified || preview.modified > now + 60 ||
        now - preview.modified > maxAgeSeconds)
        return 0;
    Gio.File.new_for_path(targetPath).replace_contents(
        preview.bytes, null, false, Gio.FileCreateFlags.REPLACE_DESTINATION, null);
    GLib.chmod(targetPath, 0o600);
    return preview.modified;
}

export function clearPreviewCache() {
    const removed = _previews.size;
    for (const preview of _previews.values())
        preview.bytes.fill(0);
    _previews.clear();
    // No long-lived plaintext cache is written to disk. Only abandoned native
    // screenshot staging files can remain after a killed Shell process.
    if (GLib.file_test(FileUtils.recall_window_cache_path, GLib.FileTest.IS_SYMLINK))
        return removed;
    const directory = Gio.File.new_for_path(FileUtils.recall_window_cache_path);
    try {
        const enumerator = directory.enumerate_children(
            'standard::name,standard::type', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
        let info;
        while ((info = enumerator.next_file(null))) {
            if (!info.get_name().startsWith('.capture-'))
                continue;
            try {
                directory.get_child(info.get_name()).delete(null);
            } catch (error) {
                Log.Log.getDefault().error(error, 'Could not clear Recall staging file');
            }
        }
        enumerator.close(null);
    } catch (error) {
        if (!error.matches?.(Gio.IOErrorEnum, Gio.IOErrorEnum.NOT_FOUND))
            Log.Log.getDefault().error(error, 'Could not clear Recall workspace staging');
    }
    return removed;
}

export function prunePreviewCache(limit = CACHE_LIMIT) {
    const entries = [..._previews.entries()].sort((a, b) => b[1].serial - a[1].serial);
    let totalBytes = 0;
    for (const [index, [key, preview]] of entries.entries()) {
        totalBytes += preview.bytes.length;
        if (index >= Math.max(0, limit) || totalBytes > CACHE_TOTAL_BYTES) {
            preview.bytes.fill(0);
            _previews.delete(key);
        }
    }
}
