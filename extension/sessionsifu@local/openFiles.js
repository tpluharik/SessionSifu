'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as Log from './utils/log.js';


export const OPEN_FILE_LIMIT = 32;
export const OPEN_FD_SCAN_LIMIT = 512;
export const RECENT_FILE_SCAN_LIMIT = 2048;

function allowedRoots() {
    const username = GLib.get_user_name();
    const runtime = GLib.get_user_runtime_dir();
    return [
        GLib.get_home_dir(),
        `/media/${username}`,
        `/run/media/${username}`,
        '/mnt',
        runtime ? GLib.build_filenamev([runtime, 'gvfs']) : null,
    ].filter(root => root);
}

function pathIsInside(path, root) {
    return path === root || path.startsWith(`${root}/`);
}

export function isCandidatePath(path, allowHidden = false) {
    if (typeof path !== 'string' || !path.startsWith('/') ||
        path.endsWith(' (deleted)') || /[\u0000-\u001f]/.test(path))
        return false;

    const roots = allowedRoots();
    if (!roots.some(root => pathIsInside(path, root)))
        return false;

    const home = GLib.get_home_dir();
    if (!allowHidden && pathIsInside(path, home)) {
        const relative = path.slice(home.length).replace(/^\/+/, '');
        if (relative.split('/').some(part => part.startsWith('.')))
            return false;
    }

    return true;
}

export function isReadableRegularFile(path) {
    try {
        const info = Gio.File.new_for_path(path).query_info(
            'standard::type,access::can-read',
            Gio.FileQueryInfoFlags.NONE,
            null);
        return info.get_file_type() === Gio.FileType.REGULAR &&
            info.get_attribute_boolean('access::can-read');
    } catch (_error) {
        return false;
    }
}

export function listOpenFiles(pid) {
    if (!Number.isInteger(pid) || pid <= 0)
        return [];

    const paths = [];
    const seen = new Set();
    let inspected = 0;
    const directory = Gio.File.new_for_path(`/proc/${pid}/fd`);
    let enumerator = null;
    try {
        enumerator = directory.enumerate_children(
            'standard::name,standard::symlink-target',
            Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS,
            null);
        let info;
        while (paths.length < OPEN_FILE_LIMIT && inspected < OPEN_FD_SCAN_LIMIT &&
            (info = enumerator.next_file(null))) {
            inspected++;
            const target = info.get_symlink_target();
            if (!isCandidatePath(target) || seen.has(target) ||
                !isReadableRegularFile(target))
                continue;
            seen.add(target);
            paths.push(target);
        }
    } catch (error) {
        Log.Log.getDefault().debug(`Could not inspect open files for process ${pid}: ${error.message}`);
    } finally {
        try {
            enumerator?.close(null);
        } catch (_error) {
        }
    }
    return paths.sort((a, b) => a.localeCompare(b));
}

function pathFromArgument(argument) {
    if (typeof argument !== 'string')
        return null;
    if (argument.startsWith('file://'))
        return Gio.File.new_for_uri(argument).get_path();
    return argument.startsWith('/') ? argument : null;
}

export function commandLineFiles(commandLine) {
    if (!Array.isArray(commandLine))
        return [];

    const result = [];
    const seen = new Set();
    for (const argument of commandLine.slice(1)) {
        if (result.length >= OPEN_FILE_LIMIT)
            break;
        const path = pathFromArgument(argument);
        if (!isCandidatePath(path, true) || seen.has(path) ||
            !isReadableRegularFile(path))
            continue;
        seen.add(path);
        result.push(path);
    }
    return result;
}

function loadRecentFiles() {
    const bookmarkFile = new GLib.BookmarkFile();
    const path = GLib.build_filenamev([
        GLib.get_user_data_dir(),
        'recently-used.xbel',
    ]);
    try {
        bookmarkFile.load_from_file(path);
    } catch (error) {
        Log.Log.getDefault().debug(`Could not load recent files: ${error.message}`);
        return [];
    }

    const result = [];
    for (const uri of bookmarkFile.get_uris().slice(-RECENT_FILE_SCAN_LIMIT)) {
        try {
            const file = Gio.File.new_for_uri(uri);
            const filePath = file.get_path();
            if (!isCandidatePath(filePath, true) || !isReadableRegularFile(filePath))
                continue;
            result.push({
                path: filePath,
                basename: GLib.path_get_basename(filePath),
                modified: bookmarkFile.get_modified_date_time(uri)?.to_unix() ?? 0,
            });
        } catch (_error) {
        }
    }
    return result.sort((a, b) => b.modified - a.modified);
}

export function recentFileForWindow(recentFiles, windowTitle) {
    if (!Array.isArray(recentFiles) || typeof windowTitle !== 'string')
        return null;
    return recentFiles.find(item =>
        typeof item?.basename === 'string' && item.basename.length >= 3 &&
        windowTitle.includes(item.basename))?.path ?? null;
}

export const OpenFileResolver = class {
    constructor() {
        this.reset();
    }

    reset() {
        this._descriptorFilesByPid = new Map();
        this._recentFiles = null;
    }

    resolve(pid, commandLine, windowTitle) {
        if (!this._descriptorFilesByPid.has(pid))
            this._descriptorFilesByPid.set(pid, listOpenFiles(pid));

        const candidates = [
            ...this._descriptorFilesByPid.get(pid),
            ...commandLineFiles(commandLine),
        ];
        if (typeof windowTitle === 'string' && windowTitle.length) {
            this._recentFiles ??= loadRecentFiles();
            const recent = recentFileForWindow(this._recentFiles, windowTitle);
            if (recent)
                candidates.push(recent);
        }

        return [...new Set(candidates)].slice(0, OPEN_FILE_LIMIT);
    }
};

export function existingOpenFiles(paths) {
    if (!Array.isArray(paths))
        return [];

    const result = [];
    const seen = new Set();
    for (const path of paths) {
        if (result.length >= OPEN_FILE_LIMIT)
            break;
        if (!isCandidatePath(path, true) || seen.has(path) || !isReadableRegularFile(path))
            continue;
        seen.add(path);
        result.push(path);
    }
    return result;
}
