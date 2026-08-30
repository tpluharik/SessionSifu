#!/usr/bin/gjs -m

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

// GLib may cache XDG_RUNTIME_DIR before JavaScript starts. The runner must set
// an isolated directory in the child environment, never mutate it in-process.
const root = ARGV[0];
if (!root || GLib.getenv('XDG_RUNTIME_DIR') !== root)
    throw new Error('Pass a private test runtime directory in XDG_RUNTIME_DIR and argv');
const Cache = await import('../extension/sessionsifu@local/recallWorkspaceCache.js');
const FileUtils = await import('../extension/sessionsifu@local/utils/fileUtils.js');
if (!FileUtils.recall_window_cache_path.startsWith(`${root}/`))
    throw new Error('Refusing to test against the real runtime cache');

function write(path, text) {
    Gio.File.new_for_path(path).replace_contents(
        new TextEncoder().encode(text), null, false, Gio.FileCreateFlags.PRIVATE, null);
}

function read(path) {
    const [ok, bytes] = Gio.File.new_for_path(path).load_contents(null);
    if (!ok)
        throw new Error('Could not read test preview');
    return new TextDecoder().decode(bytes);
}

function removeTree(file) {
    const type = file.query_file_type(Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
    if (type === Gio.FileType.DIRECTORY) {
        const enumerator = file.enumerate_children(
            'standard::name', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
        let info;
        while ((info = enumerator.next_file(null)))
            removeTree(file.get_child(info.get_name()));
        enumerator.close(null);
    }
    file.delete(null);
}

try {
    const source = `${root}/source.png`;
    const restored = `${root}/restored.png`;
    write(source, 'workspace-1-window-pixels');
    if (!Cache.storePreview(42, source))
        throw new Error('Could not cache a visible workspace preview');
    if (!Cache.restorePreview('42', restored) || read(restored) !== read(source))
        throw new Error('A later workspace did not recover the same window preview');
    if (Cache.restorePreview('never-seen', `${root}/missing.png`))
        throw new Error('A never-visited window received a fabricated preview');
    if (Cache.restorePreview(42, restored, Cache.CACHE_MAX_AGE_SECONDS, 'different page'))
        throw new Error('A changed window context reused stale screenshot pixels');
    if (Cache.restorePreview(42, restored, -1))
        throw new Error('An expired cache preview was reused');
    const captured = Cache.capturePath('../../outside');
    if (!captured.startsWith(`${FileUtils.recall_window_cache_path}/.capture-`) ||
        !/\.capture-[0-9a-f]{64}-[0-9a-f-]+\.png$/.test(captured))
        throw new Error('Window IDs can escape the private cache directory');
    const linked = `${root}/linked.png`;
    Gio.File.new_for_path(linked).make_symbolic_link(source, null);
    if (Cache.storePreview('symlink', linked))
        throw new Error('A symbolic-link source was cached');
    if (Cache.restorePreview(42, linked))
        throw new Error('A symbolic-link destination was overwritten');
    write(source, 'workspace-3-window-pixels');
    Cache.storePreview(99, source);
    Cache.prunePreviewCache(1);
    if (Cache.clearPreviewCache() !== 1)
        throw new Error('Workspace cache retention limit was not enforced');
    if (Cache.restorePreview(42, restored) || Cache.restorePreview(99, restored))
        throw new Error('Cleared workspace previews were still available');
    print('Recall workspace cache checks passed');
} finally {
    removeTree(Gio.File.new_for_path(root));
}
