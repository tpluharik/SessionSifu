'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as Log from './utils/log.js';


export const OPEN_FILE_LIMIT = 32;
export const OPEN_FD_SCAN_LIMIT = 512;

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

export function isCandidatePath(path) {
    if (typeof path !== 'string' || !path.startsWith('/') ||
        path.endsWith(' (deleted)') || /[\u0000-\u001f]/.test(path))
        return false;

    const roots = allowedRoots();
    if (!roots.some(root => pathIsInside(path, root)))
        return false;

    const home = GLib.get_home_dir();
    if (pathIsInside(path, home)) {
        const relative = path.slice(home.length).replace(/^\/+/, '');
        if (relative.split('/').some(part => part.startsWith('.')))
            return false;
    }

    return true;
}

function isReadableRegularFile(path) {
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

export function existingOpenFiles(paths) {
    if (!Array.isArray(paths))
        return [];

    const result = [];
    const seen = new Set();
    for (const path of paths) {
        if (result.length >= OPEN_FILE_LIMIT)
            break;
        if (!isCandidatePath(path) || seen.has(path) || !isReadableRegularFile(path))
            continue;
        seen.add(path);
        result.push(path);
    }
    return result;
}
