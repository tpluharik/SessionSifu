import {
    MAX_PREVIOUS_SESSION_WINDOWS,
    MIN_RESTORE_INTERVAL_MS,
    deduplicatePreviousSessionEntries,
    previousSessionIdentity,
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

if (MIN_RESTORE_INTERVAL_MS < 500 || MAX_PREVIOUS_SESSION_WINDOWS > 100)
    throw new Error('Previous-session restore safety limits are too permissive');
