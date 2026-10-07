'use strict';

// Group without dropping/reordering records within an application. Manual
// sessions may include validated command-only targets as well as desktop IDs.
export function groupRestoreEntries(entries, applicationKey) {
    const groups = new Map();
    for (const entry of entries) {
        const key = applicationKey(entry.sessionConfig);
        if (!groups.has(key))
            groups.set(key, []);
        groups.get(key).push(entry);
    }
    return [...groups.values()];
}

// Only file preparation is concurrent. Launching and native window operations
// stay on their existing serial queues. Results retain their original order.
export async function loadRestoreEntries(files, load, mayContinue, concurrency = 4) {
    const results = new Array(files.length);
    let next = 0;
    const worker = async () => {
        while (mayContinue()) {
            const index = next++;
            if (index >= files.length)
                return;
            results[index] = await load(files[index]);
        }
    };
    await Promise.all(Array.from({length: Math.min(concurrency, files.length)}, worker));
    return results.filter(Boolean);
}
