'use strict';


export const MIN_RESTORE_INTERVAL_MS = 750;
export const MAX_PREVIOUS_SESSION_WINDOWS = 64;

export function previousSessionIdentity(sessionConfig) {
    const application = String(
        sessionConfig?.desktop_file_id ?? sessionConfig?.app_name ?? '');
    const command = Array.isArray(sessionConfig?.cmd)
        ? sessionConfig.cmd.map(value => String(value)).slice(0, 64)
        : [];
    const files = Array.isArray(sessionConfig?.open_files)
        ? [...new Set(sessionConfig.open_files.map(value => String(value)))].sort().slice(0, 64)
        : [];
    return JSON.stringify([
        application,
        command,
        String(sessionConfig?.wm_class ?? ''),
        String(sessionConfig?.window_title ?? ''),
        Number.isInteger(sessionConfig?.desktop_number)
            ? sessionConfig.desktop_number
            : 0,
        files,
    ]);
}

export function deduplicatePreviousSessionEntries(entries) {
    const newestByIdentity = new Map();
    const duplicates = [];
    for (const entry of entries) {
        const identity = previousSessionIdentity(entry.sessionConfig);
        const existing = newestByIdentity.get(identity);
        if (!existing) {
            newestByIdentity.set(identity, entry);
            continue;
        }
        if ((entry.modified ?? 0) > (existing.modified ?? 0)) {
            duplicates.push(existing);
            newestByIdentity.set(identity, entry);
        } else {
            duplicates.push(entry);
        }
    }
    return {entries: [...newestByIdentity.values()], duplicates};
}
