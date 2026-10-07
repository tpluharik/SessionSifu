import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const base = new URL('../extension/sessionsifu@local/', import.meta.url);
const context = vm.createContext({console, Date, Map, Set, WeakSet});
const queueModule = new vm.SourceTextModule(
    await readFile(new URL('compositorOperations.js', base), 'utf8'), {context});
await queueModule.link(() => { throw Error('Unexpected dependency'); });
await queueModule.evaluate();
const {CompositorOperations, compositorOperations} = queueModule.namespace;
const queue = new CompositorOperations();
const order = [];
let release;
const capture = queue.run(() => {
    order.push('capture-start');
    return new Promise(resolve => { release = () => { order.push('capture-end'); resolve(); }; });
});
let alive = true;
const cancelled = queue.run(() => order.push('stale-layout'), () => alive);
const layout = queue.run(() => order.push('layout'));
await Promise.resolve();
assert.deepEqual(order, ['capture-start']);
alive = false;
release();
await Promise.all([capture, cancelled, layout]);
assert.deepEqual(order, ['capture-start', 'capture-end', 'layout']);
await assert.rejects(queue.run(() => { throw Error('native failure'); }), /native failure/);
assert.equal(await queue.run(() => 42), 42, 'Errors must not poison the queue');

// Actual entrypoints from separate UI and restore objects share one queue.
const source = new vm.SourceTextModule(
    await readFile(new URL('moveSession.js', base), 'utf8'), {context});
await source.link(async name => {
    if (name === './compositorOperations.js') return queueModule;
    const exports = name === './runtimeSafety.js' ? {mayRestoreApplications: () => true}
        : name === './restoreSafety.js' ? {WINDOW_RESTORE_INTERVAL_MS: 750}
        : name === './windowSafety.js' ? {clampWindowGeometry() {}, isValidWorkspaceIndex: () => true,
            isWindowUsable: () => true}
        : name === './windowTilingSupport.js' ? {WindowTilingSupport: {}}
        : name === './constants.js' ? {shellVersion: 50}
        : name.startsWith('gi://') ? {default: {}} : {};
    return new vm.SyntheticModule(Object.keys(exports), function () {
        for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
    }, {context});
});
await source.evaluate();
const {MoveSession} = source.namespace;
const make = () => Object.assign(Object.create(MoveSession.prototype), {
    _cancelledWindows: new WeakSet(), _log: {isDebug: () => false},
});
const direct = make();
const indicator = make();
const events = [];
let finish;
direct._moveWindowsByShellApp = () => new Promise(resolve => {
    events.push('direct'); finish = resolve;
});
indicator._moveWindowByMetaWindow = async () => { events.push('indicator'); return true; };
const first = direct.moveWindowsByShellApp({}, []);
const second = indicator.moveWindowByMetaWindow({}, []);
await Promise.resolve();
assert.deepEqual(events, ['direct']);
finish(true);
await Promise.all([first, second]);
assert.deepEqual(events, ['direct', 'indicator']);
const blocked = compositorOperations.run(() => new Promise(resolve => { finish = resolve; }));
const destroyed = indicator.moveWindowByMetaWindow({}, []);
await Promise.resolve();
indicator._destroyed = true;
finish();
await blocked;
assert.equal(await destroyed, false);
assert.equal(await make().moveWindowByMetaWindow({}, [], () => false), false);
const checkpointed = make();
const checkpointEvents = [];
checkpointed._moveWindowByMetaWindow = async () => { checkpointEvents.push('native-layout'); return true; };
assert.equal(await checkpointed.moveWindowByMetaWindow({}, [], () => true,
    () => checkpointEvents.push('durable-checkpoint')), true);
assert.deepEqual(checkpointEvents, ['durable-checkpoint', 'native-layout']);
checkpointEvents.length = 0;
assert.equal(await checkpointed.moveWindowByMetaWindow({}, [], () => false,
    () => checkpointEvents.push('stale-checkpoint')), false);
assert.deepEqual(checkpointEvents, [], 'Stale callbacks must not overwrite the active checkpoint');
checkpointed._moveWindowsByShellApp = async () => { checkpointEvents.push('app-layout'); return true; };
assert.equal(await checkpointed.moveWindowsByShellApp({}, [],
    () => checkpointEvents.push('app-checkpoint')), true);
assert.deepEqual(checkpointEvents, ['app-checkpoint', 'app-layout']);

// Matching the workspace is NOT proof that geometry/state was applied.
const saved = {windows_count: 1, window_title: 'test', desktop_number: 0};
const win = {get_title: () => 'test', get_workspace: () => ({index: () => 0})};
assert.equal(direct._getOneMatchedSavedWindow(win, [saved]), saved);
assert.equal(saved.moved, undefined);
direct._log.debug = () => {};
const sheet = {wm_class: 'libreoffice-startcenter', window_title: 'Budget - LibreOffice Calc',
    windows_count: 8, desktop_number: 0};
const sheetWindow = {get_wm_class: () => 'libreoffice-calc',
    get_title: () => sheet.window_title, get_workspace: () => ({index: () => 0})};
assert.equal(direct._getOneMatchedSavedWindow(sheetWindow, [sheet]), sheet);
assert.equal(direct._getAutoMoveInterestingWindows({get_windows: () => [sheetWindow],
    get_name: () => 'LibreOffice'}, [sheet]).length, 1);
assert.equal(direct._matchesSavedWindow({...sheetWindow, get_title: () => 'Other document'}, sheet), false);
assert.equal(direct._matchesSavedWindow({...sheetWindow, get_wm_class: () => 'unrelated'}, sheet), false);

// Indexed matching preserves exact-document/class policy, first-match order,
// single-window fallback and one-to-one assignment without a Cartesian scan.
const manySaved = Array.from({length: 80}, (_, i) => ({
    wm_class: 'editor', window_title: `Document ${i}`, windows_count: 80, desktop_number: 0,
}));
const manyWindows = manySaved.map(savedWindow => ({get_wm_class: () => 'editor',
    get_title: () => savedWindow.window_title, get_workspace: () => ({index: () => 0})})).reverse();
let matchChecks = 0;
const indexed = make();
indexed._log.debug = () => {};
const originalMatch = indexed._matchesSavedWindow;
indexed._matchesSavedWindow = function (...args) { matchChecks++; return originalMatch.apply(this, args); };
const indexedApp = {get_windows: () => manyWindows, get_name: () => 'Editor'};
assert.equal(indexed._getAutoMoveInterestingWindows(indexedApp, manySaved).length, 80);
assert.equal(matchChecks, 80, 'Unique titles need one authoritative check each, not 6400 candidates');
const single = {wm_class: 'editor', window_title: 'Old title', windows_count: 1, desktop_number: 0};
const ambiguous = indexed._getAutoMoveInterestingWindows(indexedApp, [single, single]);
assert.equal(ambiguous.length, 1, 'A saved record cannot be assigned twice');
assert.equal(ambiguous[0].open_window, manyWindows[0], 'Single-window fallback retains original ordering');
assert.equal(indexed._getAutoMoveInterestingWindows({get_windows: () => [win], get_name: () => 'Editor'}, [saved]).length, 1,
    'Missing WM_CLASS must preserve the existing matching fallback');
// Compare indexed selection to the previous nested matcher over deterministic
// mixtures of duplicate titles, missing classes and LibreOffice transitions.
const classes = ['editor', 'unrelated', 'libreoffice-startcenter', 'libreoffice-calc', null];
for (let seed = 0; seed < 30; seed++) {
    const windows = Array.from({length: 15}, (_, i) => ({
        get_wm_class: () => classes[(i * 7 + seed) % classes.length],
        get_title: () => (i + seed) % 6 ? `Title ${(i * 3 + seed) % 7}` : '',
        get_workspace: () => ({index: () => 0}),
    }));
    const records = Array.from({length: 18}, (_, i) => ({
        wm_class: classes[(i + seed) % classes.length],
        window_title: (i + seed) % 5 ? `Title ${(i + seed) % 7}` : '',
        windows_count: (i + seed) % 3 ? 5 : 1, desktop_number: 0,
        moved: (i + seed) % 11 === 0,
    }));
    const expected = [];
    const assigned = new Set();
    for (const record of records.filter(record => !record.moved)) {
        for (const window of windows) {
            if (assigned.has(window) || expected.some(item => item.saved_window_session === record))
                continue;
            if (originalMatch.call(indexed, window, record)) {
                expected.push({open_window: window, saved_window_session: record});
                assigned.add(window);
            }
        }
    }
    const actual = indexed._getAutoMoveInterestingWindows({get_windows: () => windows,
        get_name: () => 'Fixture'}, records);
    assert.equal(actual.length, expected.length);
    for (let i = 0; i < actual.length; i++) {
        assert.equal(actual[i].open_window, expected[i].open_window);
        assert.equal(actual[i].saved_window_session, expected[i].saved_window_session);
    }
}
console.log('Compositor serialization and layout regressions passed');

const guarded = new CompositorOperations();
let watchdog;
guarded.configureWatchdog(callback => { watchdog = callback; return 1; }, () => {});
let finishNative;
const hung = guarded.run(() => new Promise(resolve => { finishNative = resolve; }));
let ranQueued = false;
const pending = guarded.run(() => { ranQueued = true; });
const rejected = Promise.all([
    assert.rejects(hung, /timed out/),
    assert.rejects(pending, /timed out/),
]);
await Promise.resolve();
watchdog();
await rejected;
await assert.rejects(guarded.run(() => 42), /still pending/);
assert.equal(ranQueued, false);
finishNative();
await guarded._tail;
assert.equal(ranQueued, false, 'Expired queued work must never run after late native completion');
assert.equal(await guarded.run(() => 42), 42);
console.log('Watchdog preserves native ownership and recovers after late completion');
