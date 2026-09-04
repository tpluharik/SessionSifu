'use strict';


export const MIN_RESTORE_INTERVAL_MS = 1000;
export const MAX_PREVIOUS_SESSION_WINDOWS = 32;
export const AUTOMATIC_RESTORE_INTERVAL_MS = 8000;
export const WINDOW_RESTORE_INTERVAL_MS = 750;
// The attempt marker is cleared after a complete automatic restore. If GNOME
// Shell disappears mid-restore, it remains set and blocks another automatic
// attempt for a day; manual recovery is still available immediately.
export const AUTOMATIC_RESTORE_COOLDOWN_SECONDS = 24 * 60 * 60;
export const MAX_AUTOMATIC_RESTORE_APPLICATIONS = 4;
export const MAX_AUTOMATIC_WINDOWS_PER_APPLICATION = 2;

const BLOCKED_AUTOMATIC_DESKTOP_IDS = new Set([
    'org.gnome.sessionsifu.desktop',
    'org.gnome.shell.desktop',
    'org.gnome.shell.extensions.desktop',
    'gnome-shell.desktop',
]);

export function automaticRestoreDesktopIdAllowed(desktopFileId) {
    const id = String(desktopFileId ?? '').trim().toLowerCase();
    if (!id.endsWith('.desktop') || BLOCKED_AUTOMATIC_DESKTOP_IDS.has(id))
        return false;
    const compactId = id.replaceAll(/[^a-z0-9]/g, '');

    // Session/compositor helpers must never be relaunched as user apps. A
    // second DING/gjs or Shell process can take over desktop services and
    // terminate the running Wayland compositor.
    return !compactId.includes('sessionsifu') &&
        !compactId.includes('gnomeshell') &&
        !compactId.includes('gnomesession') &&
        !compactId.includes('settingsdaemon') &&
        !compactId.includes('desktopicons') &&
        !compactId.includes('rastersoftding');
}

export function restoreCommandAllowed(command) {
    if (!Array.isArray(command) || !command.length)
        return false;
    const executable = String(command[0] ?? '').split('/').pop().toLowerCase();
    if (['gnome-shell', 'gnome-session', 'gnome-session-binary',
        'gnome-session-quit', 'mutter', 'loginctl', 'shutdown', 'reboot', 'poweroff']
        .includes(executable))
        return false;
    const argumentsText = command.slice(1)
        .map(value => String(value).toLowerCase()).join('\n');
    if (executable === 'systemctl' &&
        /(^|\n)(exit|reboot|poweroff|halt)(\n|$)/.test(argumentsText))
        return false;
    if (argumentsText.includes('/gnome-shell/extensions/') ||
        argumentsText.includes('desktop-icons') ||
        argumentsText.includes('/ding.js'))
        return false;
    return true;
}

export function automaticRestoreAttemptAllowed(
    previousAttempt, now, cooldownSeconds = AUTOMATIC_RESTORE_COOLDOWN_SECONDS
) {
    if (!Number.isInteger(now) || now <= 0)
        return false;
    if (!Number.isInteger(previousAttempt) || previousAttempt <= 0)
        return true;
    // A clock correction must not permanently disable automatic restoration.
    if (previousAttempt > now + 60)
        return true;
    return now - previousAttempt >= cooldownSeconds;
}

export function automaticRestoreGroups(entries) {
    const byApplication = new Map();
    const rejected = [];
    for (const entry of entries) {
        const desktopFileId = entry?.sessionConfig?.desktop_file_id;
        if (!automaticRestoreDesktopIdAllowed(desktopFileId)) {
            rejected.push(entry);
            continue;
        }
        const key = String(desktopFileId).toLowerCase();
        if (!byApplication.has(key))
            byApplication.set(key, []);
        byApplication.get(key).push(entry);
    }

    const discarded = [];
    const groups = [...byApplication.entries()].map(([key, applicationEntries]) => {
        applicationEntries.sort((left, right) =>
            (right.modified ?? 0) - (left.modified ?? 0));
        // Crash-recovery folders can contain old records whose titles changed
        // between saves. The newest record's windows_count is a safer bound
        // than treating every historical title as a currently open window.
        const savedWindowCount = applicationEntries[0]?.sessionConfig?.windows_count;
        const applicationLimit = Number.isInteger(savedWindowCount) && savedWindowCount > 0
            ? Math.min(savedWindowCount, MAX_AUTOMATIC_WINDOWS_PER_APPLICATION)
            : 1;
        if (applicationEntries.length > applicationLimit) {
            discarded.push(...applicationEntries.slice(applicationLimit));
            applicationEntries.length = applicationLimit;
        }
        return {
            key,
            entries: applicationEntries,
            modified: applicationEntries[0]?.modified ?? 0,
        };
    });
    groups.sort((left, right) => right.modified - left.modified ||
        left.key.localeCompare(right.key));
    if (groups.length > MAX_AUTOMATIC_RESTORE_APPLICATIONS) {
        for (const group of groups.slice(MAX_AUTOMATIC_RESTORE_APPLICATIONS))
            discarded.push(...group.entries);
        groups.length = MAX_AUTOMATIC_RESTORE_APPLICATIONS;
    }
    return {groups, rejected, discarded};
}

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
