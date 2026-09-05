// Exercise the real queue methods without launching apps in the host desktop.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const base = new URL('../extension/sessionsifu@local/', import.meta.url);
let now = 0;
let safe = true;
let files = [];
const removed = [];
const context = vm.createContext({
    console, Date, Map, Set, JSON,
    global: {notify_error() {}}, logError() {},
});
const safety = new vm.SourceTextModule(await readFile(new URL('restoreSafety.js', base), 'utf8'), {context});
await safety.link(() => { throw Error('Unexpected dependency'); });
await safety.evaluate();
const stubs = {
    'gi://Shell': {default: {AppState: {RUNNING: 2}}},
    'gi://Gio': {default: {Settings: {sync() {}}, FileQueryInfoFlags: {NOFOLLOW_SYMLINKS: 0}}},
    'gi://GLib': {default: {get_monotonic_time: () => now, build_filenamev: parts => parts.join('/')}},
    './utils/fileUtils.js': {
        current_session_path: '/state',
        listAllSessions: async (_path, _recursive, callback) => {
            for (const file of files) callback(file, {get_content_type: () => 'application/json'});
        },
        getJsonObj: bytes => JSON.parse(new TextDecoder().decode(bytes)),
        removeFile: path => removed.push(path),
    }, './utils/log.js': {},
    './utils/prefsUtils.js': {PrefsUtils: {}}, './utils/subprocessUtils.js': {},
    './utils/dateUtils.js': {}, './utils/stringUtils.js': {}, './openFiles.js': {},
    './moveSession.js': {}, './runtimeSafety.js': {mayRestoreApplications: () => safe},
    './compositorOperations.js': {compositorOperations: {run: (operation, mayRun) =>
        Promise.resolve(mayRun() ? operation() : false)}},
    './windowSafety.js': {MAX_WORKSPACE_INDEX: 32},
};
const source = new vm.SourceTextModule(await readFile(new URL('restoreSession.js', base), 'utf8'), {context});
await source.link(async name => {
    if (name === './restoreSafety.js') return safety;
    const exports = stubs[name];
    assert.ok(exports, `Missing stub ${name}`);
    return new vm.SyntheticModule(Object.keys(exports), function () {
        for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
    }, {context});
});
await source.evaluate();
const {RestoreSession, restoreSessionObject} = source.namespace;
const make = (values = {}) => {
    const state = new Map(Object.entries(values));
    const restorer = Object.create(RestoreSession.prototype);
    Object.assign(restorer, {
        _settings: {
            get_string: key => state.get(key) ?? '', get_int64: key => state.get(key) ?? 0,
            set_string: (key, value) => state.set(key, value),
            set_int64: (key, value) => state.set(key, value),
        },
        _log: {info() {}, warn() {}, error() {}, debug() {}}, _destroyed: false,
    });
    return {restorer, state};
};

// A legacy timestamp from yesterday must not prevent a normal login today.
const yesterday = Math.floor(Date.now() / 1000) - 22 * 3600;
let {restorer, state} = make({'last-automatic-restore-attempt': yesterday});
let called = false;
assert.equal(await restorer._runRestore(async () => { called = true; return true; }, true), true);
assert.ok(called);
assert.equal(state.get('last-automatic-restore-attempt'), 0);

// Recent failures pause auto, but manual recovery remains possible.
({restorer, state} = make({
    'last-automatic-restore-attempt': Math.floor(Date.now() / 1000) - 20,
    'restore-active-application': 'bad.desktop',
}));
called = false;
assert.equal(await restorer._runRestore(async () => { called = true; return true; }, true), false);
assert.equal(called, false);
assert.match(state.get('restore-progress'), /paused/);
assert.equal(await restorer._runRestore(async () => true, false), true);

// All application groups survive planning; only the interrupted app is held.
restorer._defaultAppSystem = {lookup_app: () => ({get_app_info: () => ({should_show: () => true})})};
const entries = Array.from({length: 9}, (_, index) => ({sessionConfig: {
    desktop_file_id: index === 0 ? 'bad.desktop' : `app-${index}.desktop`, windows_count: 1,
}}));
assert.equal(restorer._automaticRestorePlan(entries, true).groups.length, 8);
assert.equal(restorer._automaticRestorePlan(entries, false).groups.length, 9);

// A competing restore cannot clear or replace the active window mapping.
let finish;
const first = make().restorer;
const pending = first._runRestore(() => new Promise(resolve => { finish = resolve; }), false);
const map = restoreSessionObject.restoringApps;
const second = make().restorer;
assert.equal(await second._runRestore(async () => true, false), false);
assert.equal(restoreSessionObject.restoringApps, map);
finish(true);
await pending;
assert.equal(restoreSessionObject.activeRestorer, null);

// Readiness has a real deadline, failed apps do not stall the next app.
({restorer, state} = make());
restorer._heldApplications = {};
restorer._timedOutApps = new Set();
restorer._restoreOneSession = async () => [true, false];
restorer._moveSession = {moveWindowsByShellApp: async () => true};
restorer._waitBeforeNextRestore = async milliseconds => { now += milliseconds * 1000; return safe; };
const testApps = new Map();
restorer._defaultAppSystem = {lookup_app: id => {
    if (!testApps.has(id)) testApps.set(id, {
    get_state: () => id === 'slow.desktop' ? 1 : 2,
    get_windows: () => id === 'slow.desktop' ? [] : [{}],
    });
    return testApps.get(id);
}};
const slowApp = restorer._defaultAppSystem.lookup_app('slow.desktop');
restoreSessionObject.restoringApps.set(slowApp, {saved_window_sessions: []});
assert.equal((await restorer._restoreQueuedEntry({desktop_file_id: 'slow.desktop'}))[0], false);
assert.equal(restoreSessionObject.restoringApps.has(slowApp), false,
    'Timed-out launches must not retain late window callbacks');

assert.equal(now, 30000000);
assert.equal((await restorer._restoreQueuedEntry({desktop_file_id: 'ready.desktop'}))[0], true);
assert.equal((await restorer._restoreQueuedEntry({desktop_file_id: 'slow.desktop'}))[0], false);

// A running app whose layout could not be applied must retain its record.
restorer._moveSession = {moveWindowsByShellApp: async () => false};
assert.equal((await restorer._restoreQueuedEntry({desktop_file_id: 'unmatched.desktop'}))[0], false);

// Errors release the queue lock and keep an actionable failure status.
({restorer, state} = make());
assert.equal(await restorer._runRestore(async () => { throw Error('test'); }, false), false);
assert.equal(restoreSessionObject.activeRestorer, null);
assert.match(state.get('restore-progress'), /failed/);

// Exercise the complete previous-desktop loop, including more than 32 records,
// failed entries, and a record rewritten by the live tracker during restore.
files = Array.from({length: 45}, (_, index) => ({
    index, get_path: () => `/state/${index}.json`,
    get_parent: () => ({get_path: () => '/state/apps'}),
    query_info: () => ({get_modification_date_time: () => ({to_unix: () => index})}),
}));
({restorer, state} = make());
restorer._defaultAppSystem = {lookup_app: () => ({get_app_info: () => ({should_show: () => true})})};
const processed = [];
restorer._loadSessionContents = async file => new TextEncoder().encode(JSON.stringify({
    desktop_file_id: `app-${file.index}.desktop`, windows_count: 1,
    window_title: file.index === 10 && processed.includes(file.index) ? 'New state' : 'Saved state',
}));
restorer._restoreQueuedEntry = async config => {
    const index = Number(config.desktop_file_id.match(/\d+/)[0]);
    processed.push(index);
    return [index !== 20, false];
};
restorer._waitBeforeNextRestore = async () => true;
assert.equal(await restorer.restorePreviousSession(true, false), true);
assert.equal(processed.length, 45);
assert.equal(removed.length, 43);
assert.ok(!removed.includes('/state/20.json'), 'Failed record must remain');
assert.ok(!removed.includes('/state/10.json'), 'Newer live state must remain');
assert.match(state.get('restore-progress'), /1 records retained/);
processed.length = 0;
removed.length = 0;
state.set('last-automatic-restore-attempt', yesterday);
assert.equal(await restorer.restorePreviousSession(true, true), true);
assert.equal(processed.length, 45, 'Automatic recovery must finish every eligible group too');
assert.equal(state.get('last-automatic-restore-attempt'), 0);

// Stopping the integration cancels pending waits without starting another app.
({restorer, state} = make());
let moveCancelled = false;
restorer._pendingRestoreDelays = new Map();
restorer._moveSession = {destroy: () => { moveCancelled = true; }};
restorer.cancel();
assert.ok(moveCancelled);
assert.equal(restorer._destroyed, true);
assert.match(state.get('restore-progress'), /interrupted/);
assert.equal(await restorer._runRestore(async () => true, false), false);
console.log('Restore queue regressions passed');
