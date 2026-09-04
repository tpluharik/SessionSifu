import {
    AUTOMATIC_RESTORE_INTERVAL_MS,
    MAX_AUTOMATIC_RESTORE_APPLICATIONS,
    MAX_AUTOMATIC_WINDOWS_PER_APPLICATION,
    MAX_PREVIOUS_SESSION_WINDOWS,
    MIN_RESTORE_INTERVAL_MS,
    WINDOW_RESTORE_INTERVAL_MS,
    AUTOMATIC_RESTORE_COOLDOWN_SECONDS,
    automaticRestoreAttemptAllowed,
    automaticRestoreDesktopIdAllowed,
    automaticRestoreGroups,
    deduplicatePreviousSessionEntries,
    previousSessionIdentity,
    restoreCommandAllowed,
} from '../extension/sessionsifu@local/restoreSafety.js';


const original = {
    desktop_file_id: 'chatgpt.desktop',
    window_title: 'ChatGPT',
    desktop_number: 0,
    open_files: ['/tmp/example.txt'],
};
const reorderedFiles = {...original, open_files: ['/tmp/example.txt', '/tmp/example.txt']};
if (previousSessionIdentity(original) !== previousSessionIdentity(reorderedFiles))
    throw new Error('Equivalent saved windows did not receive the same identity');

const oldEntry = {sessionConfig: original, modified: 1, marker: 'old'};
const newEntry = {sessionConfig: {...original}, modified: 2, marker: 'new'};
const distinctEntry = {
    sessionConfig: {...original, window_title: 'A different conversation'},
    modified: 1,
    marker: 'distinct',
};
const deduplicated = deduplicatePreviousSessionEntries([
    oldEntry, distinctEntry, newEntry,
]);
if (deduplicated.entries.length !== 2 || deduplicated.duplicates.length !== 1)
    throw new Error('Duplicate previous-session windows were not collapsed');
if (!deduplicated.entries.includes(newEntry) || !deduplicated.duplicates.includes(oldEntry))
    throw new Error('The newest duplicate previous-session window was not retained');

if (MIN_RESTORE_INTERVAL_MS < 1000 || WINDOW_RESTORE_INTERVAL_MS < 750 ||
    MAX_PREVIOUS_SESSION_WINDOWS > 32 ||
    MAX_AUTOMATIC_RESTORE_APPLICATIONS > 4 ||
    MAX_AUTOMATIC_WINDOWS_PER_APPLICATION > 2)
    throw new Error('Previous-session restore safety limits are too permissive');
if (AUTOMATIC_RESTORE_COOLDOWN_SECONDS < 24 * 60 * 60 ||
    !automaticRestoreAttemptAllowed(0, 1000) ||
    automaticRestoreAttemptAllowed(950, 1000) ||
    !automaticRestoreAttemptAllowed(1, 1000, 100))
    throw new Error('Automatic restore crash-loop guard is incorrect');

for (const unsafe of [
    '', 'gjs', 'org.gnome.SessionSifu.desktop', 'org.gnome.Shell.desktop',
    'org.gnome.SettingsDaemon.MediaKeys.desktop', 'desktop-icons-ng.desktop',
]) {
    if (automaticRestoreDesktopIdAllowed(unsafe))
        throw new Error(`Unsafe automatic restore target was accepted: ${unsafe}`);
}
if (!automaticRestoreDesktopIdAllowed('chatgpt.desktop'))
    throw new Error('A normal desktop application was rejected');

const automaticEntries = [];
for (let application = 0; application < MAX_AUTOMATIC_RESTORE_APPLICATIONS + 2;
    application++) {
    for (let window = 0; window < MAX_AUTOMATIC_WINDOWS_PER_APPLICATION + 2;
        window++) {
        automaticEntries.push({
            modified: application * 100 + window,
            sessionConfig: {
                desktop_file_id: `example-${application}.desktop`,
                window_title: `Window ${window}`,
                windows_count: 2,
            },
        });
    }
}
automaticEntries.push({
    modified: 9999,
    sessionConfig: {app_name: 'gjs', cmd: ['gjs', 'ding.js']},
});
const automaticPlan = automaticRestoreGroups(automaticEntries);
if (automaticPlan.groups.length !== MAX_AUTOMATIC_RESTORE_APPLICATIONS)
    throw new Error('Automatic restore application cap was not applied');
if (automaticPlan.groups.some(group =>
    group.entries.length > 2 ||
    group.entries.length > MAX_AUTOMATIC_WINDOWS_PER_APPLICATION))
    throw new Error('Automatic restore per-application window cap was not applied');
if (automaticPlan.rejected.length !== 1)
    throw new Error('Command-only Shell helper was not rejected');
if (AUTOMATIC_RESTORE_INTERVAL_MS < 8000)
    throw new Error('Automatic restore launch pacing is too aggressive');

for (const command of [
    ['gnome-shell', '--replace'],
    ['mutter', '--wayland'],
    ['gnome-session-quit', '--logout'],
    ['systemctl', '--user', 'exit'],
    ['loginctl', 'terminate-user', '1000'],
    ['gjs', '/usr/share/gnome-shell/extensions/ding@rastersoft.com/app/ding.js'],
]) {
    if (restoreCommandAllowed(command))
        throw new Error(`Unsafe Shell helper command was accepted: ${command}`);
}
if (!restoreCommandAllowed(['/usr/bin/example-editor', '/tmp/document.txt']))
    throw new Error('A normal direct application command was rejected');
