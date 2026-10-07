// Exercise the real queue methods without launching apps in the host desktop.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const base = new URL('../extension/sessionsifu@local/', import.meta.url);
let now = 0;
let safe = true;
let files = [];
const removed = [];
let restoreBusy = 0;
const timers = new Map();
let timerId = 0;
const context = vm.createContext({
    console, Date, Map, Set, JSON,
    global: {notify_error() {}, workspace_manager: {n_workspaces: 2},
        create_app_launch_context: () => ({})}, logError() {},
});
const safety = new vm.SourceTextModule(await readFile(new URL('restoreSafety.js', base), 'utf8'), {context});
await safety.link(() => { throw Error('Unexpected dependency'); });
await safety.evaluate();
const stubs = {
    'gi://Shell': {default: {AppState: {STOPPED: 0, STARTING: 1, RUNNING: 2}}},
    'gi://GioUnix': {default: {DesktopAppInfo: {new_from_filename: () => null}}},
    'gi://Gio': {default: {Settings: {sync() {}}, FileQueryInfoFlags: {NOFOLLOW_SYMLINKS: 0},
        FileType: {REGULAR: 1}, File: {new_for_path: path => ({path,
            query_info: () => ({get_file_type: () => 1, get_attribute_boolean: () => true}),
        })}}},
    'gi://GLib': {default: {get_monotonic_time: () => now, build_filenamev: parts => parts.join('/'),
        get_home_dir: () => '/synthetic', get_user_name: () => 'test',
        get_user_runtime_dir: () => null,
        timeout_add: (_priority, delay, callback) => {
            timers.set(++timerId, {delay, callback}); return timerId;
        },
        Source: {remove: id => timers.delete(id)},
    }},
    './utils/fileUtils.js': {
        current_session_path: '/state',
        listAllSessions: async (_path, _recursive, callback) => {
            for (const file of files) callback(file, {get_content_type: () => 'application/json'});
        },
        getJsonObj: bytes => JSON.parse(new TextDecoder().decode(bytes)),
        removeFile: path => removed.push(path),
    }, './utils/log.js': {},
    './utils/prefsUtils.js': {PrefsUtils: {}}, './utils/subprocessUtils.js': {},
    './utils/dateUtils.js': {get_current_time: () => 0}, './utils/stringUtils.js': {},
    './moveSession.js': {}, './runtimeSafety.js': {mayRestoreApplications: () => safe},
    './compositorOperations.js': {compositorOperations: {run: (operation, mayRun) =>
        Promise.resolve(mayRun() ? operation() : false)}},
    './recallActivity.js': {restoreActivity: {
        begin: () => restoreBusy++, end: () => restoreBusy--,
    }},
    './windowSafety.js': {MAX_WORKSPACE_INDEX: 32,
        launchWorkspaceIndex: (index, count) => Number.isInteger(index) &&
            index >= 0 && index < count ? index : -1},
};
const source = new vm.SourceTextModule(await readFile(new URL('restoreSession.js', base), 'utf8'), {context});
const scheduling = new vm.SourceTextModule(await readFile(new URL('restoreScheduling.js', base), 'utf8'), {context});
await scheduling.link(() => { throw Error('Unexpected scheduling dependency'); });
await scheduling.evaluate();
const openFiles = new vm.SourceTextModule(await readFile(new URL('openFiles.js', base), 'utf8'), {context});
await openFiles.link(name => {
    const exports = stubs[name];
    assert.ok(exports, `Missing open-files stub ${name}`);
    return new vm.SyntheticModule(Object.keys(exports), function () {
        for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
    }, {context});
});
await source.link(async name => {
    if (name === './restoreSafety.js') return safety;
    if (name === './restoreScheduling.js') return scheduling;
    if (name === './openFiles.js') return openFiles;
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

// Login autostart owns automatic launch, while an explicit manual restore may
// still recover the application on demand.
restorer._autostartTargets = {
    desktopIds: new Set(['io.github.tpluharik.powersifu.desktop']),
    executables: new Set(['powersifu']),
};
restorer._defaultAppSystem = {lookup_app: () => ({get_app_info: () => ({
    should_show: () => true, get_executable: () => '/opt/powersifu',
})})};
const autostartEntry = [{sessionConfig: {
    desktop_file_id: 'io.github.tpluharik.PowerSifu.desktop', windows_count: 1,
}}];
assert.equal(restorer._automaticRestorePlan(autostartEntry, true).groups.length, 0);
assert.equal(restorer._automaticRestorePlan(autostartEntry, false).groups.length, 1);

// A competing restore cannot clear or replace the active window mapping.
let finish;
const first = make().restorer;
const pending = first._runRestore(() => new Promise(resolve => { finish = resolve; }), false);
assert.equal(restoreBusy, 1, 'Restore activity must cover waiting as well as launches');
const map = restoreSessionObject.restoringApps;
const second = make().restorer;
assert.equal(await second._runRestore(async () => true, false), false);
assert.equal(restoreSessionObject.restoringApps, map);
assert.equal(restoreBusy, 1, 'Rejected overlapping request must not change activity');
finish(true);
await pending;
assert.equal(restoreSessionObject.activeRestorer, null);
assert.equal(restoreBusy, 0);

// Readiness has a real deadline, failed apps do not stall the next app.
({restorer, state} = make());
restorer._heldApplications = {};
restorer._timedOutApps = new Set();
restorer._restoreOneSession = async () => [true, false];
restorer._moveSession = {moveWindowsByShellApp: async () => true};
restorer._waitBeforeNextRestore = async milliseconds => { now += milliseconds * 1000; return safe; };
restorer._waitForRestoreEvent = async (_app, milliseconds) => { now += milliseconds * 1000; return safe; };
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

let layoutAttempts = 0;
restorer._moveSession = {moveWindowsByShellApp: async () => ++layoutAttempts === 3};
assert.equal((await restorer._restoreQueuedEntry({desktop_file_id: 'late-layout.desktop'}))[0], true);
assert.equal(layoutAttempts, 3, 'Wait for late document titles and WM_CLASS before retiring records');

// Errors release the queue lock and keep an actionable failure status.
({restorer, state} = make());
assert.equal(await restorer._runRestore(async () => { throw Error('test'); }, false), false);
assert.equal(restoreSessionObject.activeRestorer, null);
assert.match(state.get('restore-progress'), /failed/);
assert.equal(restoreBusy, 0, 'Restore activity must stop on errors');

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

// Test the real scheduler: elapsed readiness counts toward pacing, but fixed
// compositor-settle waits and a larger user-configured interval remain intact.
({restorer, state} = make());
restorer._pendingRestoreDelays = new Map();
restorer._restore_session_interval = 1000;
restorer._entryStartedAt = 0;
now = 1750000;
let pacing = restorer._waitBeforeNextRestore(8000);
assert.equal(timers.get(timerId).delay, 6250);
timers.get(timerId).callback();
assert.equal(await pacing, true);
assert.equal(restorer._pendingRestoreDelays.size, 0);
now = 30000000;
const previousTimerId = timerId;
assert.equal(await restorer._waitBeforeNextRestore(8000), true);
assert.equal(timerId, previousTimerId, 'Slow readiness must not add another eight seconds');
pacing = restorer._waitBeforeNextRestore(1000, true);
assert.equal(timers.get(timerId).delay, 1000, 'Fixed settle delay must not shrink');
timers.get(timerId).callback();
await pacing;
restorer._restore_session_interval = 40000;
pacing = restorer._waitBeforeNextRestore(8000);
assert.equal(timers.get(timerId).delay, 10000, 'Keep user-selected pacing');
timers.get(timerId).callback();
await pacing;

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
// Exercise the actual launch boundary, not only the pure index helper.
({restorer, state} = make());
restorer._launchedFilesByApp = new Map();
restorer._restoredApps = new Map();
restorer._appIsRunning = () => false;
restorer._getProperGpuPref = () => 0;
let launchWorkspace;
const launchApp = {get_app_info: () => ({}),
    launch: (_timestamp, workspace) => { launchWorkspace = workspace; return true; }};
assert.equal(restorer.launch(launchApp, 30)[0], true);
assert.equal(launchWorkspace, -1, 'Missing workspace must not enter native launch');
assert.equal(restorer.launch(launchApp, 1)[0], true);
assert.equal(launchWorkspace, 1);
safe = false;
assert.equal(restorer.launch(launchApp, 0)[0], false);
assert.equal(launchWorkspace, 1, 'Shutdown must prevent native launch');

// Actual launch + actual browser policy: no replay, including saved documents
// left in older snapshots. STARTING is reused even with an empty running list.
safe = true;
({restorer, state} = make());
Object.assign(restorer, {_launchedFilesByApp: new Map(), _restoredApps: new Map(),
    _defaultAppSystem: {get_running: () => []}, _getProperGpuPref: () => 0});
let browserState = 0;
let browserLaunches = 0;
let documentLaunches = 0;
const browser = {
    get_id: () => 'firefox_firefox.desktop', get_name: () => 'Firefox',
    get_state: () => browserState,
    get_app_info: () => ({get_id: () => 'firefox_firefox.desktop',
        supports_files: () => true, supports_uris: () => true,
        get_supported_types: () => ['application/pdf', 'text/html'],
        launch: () => { documentLaunches++; return true; }}),
    launch: () => { browserLaunches++; browserState = 1; return true; },
};
const documents = ['/synthetic/already-recovered.pdf', '/synthetic/already-recovered.html'];
assert.equal(restorer.launch(browser, 0, documents)[0], true);
assert.equal(browserLaunches, 1);
assert.equal(documentLaunches, 0);
assert.equal(restorer.launch(browser, 0, documents)[1], true, 'Reuse STARTING browser');
restorer._restoredApps.set(browser, {});
browserState = 2;
assert.equal(restorer.launch(browser, 1, documents)[1], true, 'Reuse previous launch');
assert.equal(browserLaunches, 1, 'Multiple saved browser windows must launch once');
assert.equal(documentLaunches, 0, 'Do not reopen tabs recovered by Firefox');
const reopenedFiles = [];
const editor = {get_id: () => 'editor.desktop', get_name: () => 'Editor', get_state: () => 2,
    get_app_info: () => ({get_id: () => 'editor.desktop', supports_files: () => true,
        supports_uris: () => false, get_supported_types: () => ['text/plain'],
        launch: files => { reopenedFiles.push(...files.map(file => file.path)); return true; }}),
};
assert.equal(restorer.launch(editor, 0, ['/synthetic/first.txt'])[0], true);
restorer._restoredApps.set(editor, {});
assert.equal(restorer.launch(editor, 0, ['/synthetic/first.txt', '/synthetic/second.txt'])[0], true);
assert.deepEqual(reopenedFiles, ['/synthetic/first.txt', '/synthetic/second.txt'],
    'Document editors must still reopen files once, including additional saved documents');

// File preparation is bounded, cancellation stops new reads, and completion
// order never reorders the restore plan.
const {loadRestoreEntries, groupRestoreEntries} = scheduling.namespace;
let inFlight = 0;
let peak = 0;
const readers = [];
const loads = loadRestoreEntries([0, 1, 2, 3, 4], file => new Promise(resolve => {
    inFlight++;
    peak = Math.max(peak, inFlight);
    readers[file] = () => { inFlight--; resolve({file}); };
}), () => true, 2);
assert.equal(peak, 2);
readers[1]();
await new Promise(resolve => setImmediate(resolve));
readers[2]();
await new Promise(resolve => setImmediate(resolve));
readers[0]();
await new Promise(resolve => setImmediate(resolve));
readers[4](); readers[3]();
assert.deepEqual(Array.from(await loads, entry => entry.file), [0, 1, 2, 3, 4]);
assert.equal(peak, 2);
let loadCalls = 0;
let keepLoading = true;
await loadRestoreEntries([1, 2, 3, 4], async file => {
    loadCalls++; keepLoading = false; return {file};
}, () => keepLoading);
assert.equal(loadCalls, 1, 'Cancellation must stop scheduling new file reads');
const grouped = groupRestoreEntries([
    {sessionConfig: {id: 'a', order: 0}}, {sessionConfig: {id: 'b', order: 1}},
    {sessionConfig: {id: 'a', order: 2}},
], session => session.id);
assert.deepEqual(Array.from(grouped, group => Array.from(group, e => e.sessionConfig.order)), [[0, 2], [1]]);

// Real signal wait: events wake immediately, handlers/timers are released, and
// cancellation, shutdown and unsupported signals retain safe behavior.
({restorer, state} = make());
const listeners = new Map();
let signalId = 0;
const signalledApp = {
    connect: (signal, callback) => { listeners.set(++signalId, {signal, callback}); return signalId; },
    disconnect: id => listeners.delete(id), get_windows: () => [],
};
const signalWait = restorer._waitForRestoreEvent(signalledApp, 1000);
const readinessTimer = timerId;
assert.equal(listeners.size, 2);
listeners.values().next().value.callback();
assert.equal(await signalWait, true);
assert.equal(listeners.size, 0);
assert.equal(restorer._pendingReadinessWaits.size, 0);
assert.equal(timers.has(readinessTimer), false, 'Event completion must cancel the fallback timer');
const cancelWait = restorer._waitForRestoreEvent(signalledApp, 1000);
restorer.cancel();
assert.equal(await cancelWait, false);
assert.equal(listeners.size, 0);
({restorer, state} = make());
const closingWindow = {connect: signalledApp.connect, disconnect: signalledApp.disconnect};
const closingWait = restorer._waitForRestoreEvent({...signalledApp, get_windows: () => [closingWindow]}, 1000);
const closingSignal = [...listeners.values()].find(item => item.signal === 'unmanaging');
assert.ok(closingSignal);
closingSignal.callback();
assert.equal(await closingWait, true);
assert.equal(listeners.size, 0, 'Unmanaging releases all listeners before native disposal');
({restorer, state} = make());
const fallback = restorer._waitForRestoreEvent({connect() { throw Error('unsupported'); },
    get_windows() { throw Error('disposed'); }}, 1000);
timers.get(timerId).callback();
assert.equal(await fallback, true);
safe = false;
assert.equal(await restorer._waitForRestoreEvent(signalledApp, 1000), false);
safe = true;

// Late layouts share one final retry budget, remain available to callbacks,
// and are never retired on launch alone. Cancellation cannot finish the run.
({restorer, state} = make());
restorer._heldApplications = {};
restorer._timedOutApps = new Set();
restorer._deferredLayouts = [];
restorer._restoreOneSession = async () => [true, true];
restorer._defaultAppSystem = {lookup_app: () => ({get_state: () => 2, get_windows: () => [{}]})};
restorer._moveSession = {moveWindowsByShellApp: async () => false};
restorer._waitBeforeNextRestore = async delay => { now += delay * 1000; return safe; };
restorer._waitForRestoreEvent = async (_app, delay) => { now += delay * 1000; return safe; };
now = 0;
for (let i = 0; i < 5; i++) {
    const result = await restorer._restoreQueuedEntry({desktop_file_id: 'late.desktop'}, {deferLayout: true});
    assert.equal(result[0], false);
    assert.equal(result[2], true);
}
assert.equal(now, 5000000, 'Unmatched records must not each consume a ten-second retry');
const retryStarted = now;
restorer._retained = 0;
let retired = 0;
await restorer._reconcileDeferredLayouts(async () => retired++);
assert.equal(now - retryStarted, 10000000);
assert.equal(restorer._retained, 5);
assert.equal(retired, 0);
const lateConfig = {desktop_file_id: 'late.desktop', moved: true};
restorer._deferredLayouts = [{app: {}, sessionConfig: lateConfig}];
await restorer._reconcileDeferredLayouts(async config => { assert.equal(config, lateConfig); retired++; });
assert.equal(retired, 1, 'An event-completed layout may now retire its own record');

// Actual named-session pipeline: preregister expected windows once, reuse apps
// without eight-second per-window gaps, and keep eight seconds between native
// launches even when the next app is already known by the plan.
({restorer, state} = make());
Object.assign(restorer, {_restore_session_interval: 1000,
    _restoredApps: new Map(), _launchedFilesByApp: new Map(), _cmdAppIdMap: new Map(),
    _getProperGpuPref: () => 0});
const appStates = new Map([['a.desktop', 2], ['b.desktop', 2]]);
const nativeLaunchTimes = [];
const apps = new Map([...appStates].map(([id]) => [id, {
    get_id: () => id, get_name: () => id, get_state: () => appStates.get(id),
    get_windows: () => appStates.get(id) === 2 ? [{}] : [], get_app_info: () => ({}),
    launch: () => {
        assert.equal(state.get('restore-active-application'), id,
            'The actual launch must own the checkpoint after any earlier callback');
        nativeLaunchTimes.push(now); appStates.set(id, 2); return true;
    },
}]));
restorer._defaultAppSystem = {lookup_app: id => apps.get(id), get_running: () => []};
const order = [];
restorer._moveSession = {moveWindowsByShellApp: async (app, configs) => {
    const mapping = restoreSessionObject.restoringApps.get(app);
    assert.equal(mapping.saved_window_sessions.length, 3, 'Register the whole application group once');
    order.push(configs[0].order);
    configs[0].moved = true;
    return true;
}};
const namedRecords = Array.from({length: 6}, (_, order) => ({
    desktop_file_id: order % 2 ? 'b.desktop' : 'a.desktop', order,
}));
restorer._loadSessionContents = async () => new TextEncoder().encode(JSON.stringify({
    x_session_config_objects: namedRecords,
}));
restorer._waitBeforeNextRestore = async function (minimum = 1000, fixed = false) {
    const delay = fixed ? minimum : safety.namespace.remainingRestoreDelay(
        Math.max(minimum, this._restore_session_interval), this._entryStartedAt, now);
    now += delay * 1000;
    return safe && !this._destroyed;
};
restorer._waitForRestoreEvent = async (_app, delay) => { now += delay * 1000; return safe; };
now = 0;
assert.equal(await restorer.restoreSessionFromFile('/named'), true);
assert.deepEqual(order, [0, 2, 4, 1, 3, 5]);
assert.equal(now, 5000000, 'Six already-running windows use five one-second gaps, not forty seconds');
assert.equal(nativeLaunchTimes.length, 0);
order.length = 0;
appStates.set('a.desktop', 0); appStates.set('b.desktop', 0);
now = 0;
const queueBoundary = stubs['./compositorOperations.js'].compositorOperations;
const originalRun = queueBoundary.run;
queueBoundary.run = (operation, mayRun) => {
    state.set('restore-active-application', 'earlier-callback.desktop');
    return originalRun(operation, mayRun);
};
assert.equal(await restorer.restoreSessionFromFile('/named'), true);
queueBoundary.run = originalRun;
assert.equal(nativeLaunchTimes.length, 2);
assert.ok(nativeLaunchTimes[1] - nativeLaunchTimes[0] >= 8000000,
    'Actual application launches retain the conservative safety gap');
assert.equal(restoreSessionObject.restoringApps.size, 0, 'No late callbacks survive completion');

// Additional document requests use the launch gate too, even in a running app.
const documentApp = apps.get('a.desktop');
documentApp.get_app_info = () => ({get_id: () => 'editor.desktop', supports_files: () => true,
    get_supported_types: () => ['text/plain'], launch: () => { nativeLaunchTimes.push(now); return true; }});
const docRecords = [0, 1, 2].map(order => ({desktop_file_id: 'a.desktop', order,
    open_files: [`/synthetic/document-${order}.txt`]}));
restorer._loadSessionContents = async () => new TextEncoder().encode(JSON.stringify({x_session_config_objects: docRecords}));
appStates.set('a.desktop', 2);
nativeLaunchTimes.length = 0;
now = 0;
assert.equal(await restorer.restoreSessionFromFile('/documents'), true);
assert.equal(nativeLaunchTimes.length, 3);
for (let index = 1; index < nativeLaunchTimes.length; index++)
    assert.ok(nativeLaunchTimes[index] - nativeLaunchTimes[index - 1] >= 8000000,
        'Document launches must not bypass the safety gap');

// End-to-end previous-session late reconciliation retires only successful,
// unchanged records. One disposed app cannot strand other pending layouts.
files = [0, 1, 2].map(index => ({index, get_path: () => `/state/late-${index}.json`,
    get_parent: () => ({get_path: () => '/state/apps'}),
    query_info: () => ({get_modification_date_time: () => ({to_unix: () => index})}),
}));
removed.length = 0;
({restorer, state} = make());
const lateApp = {get_state: () => 2, get_windows: () => [],
    get_app_info: () => ({should_show: () => true})};
restorer._defaultAppSystem = {lookup_app: () => lateApp};
let rewritten = false;
restorer._loadSessionContents = async file => new TextEncoder().encode(JSON.stringify({
    desktop_file_id: 'late.desktop', windows_count: 3, index: file.index,
    window_title: rewritten && file.index === 1 ? 'New live state' : `Saved ${file.index}`,
}));
restorer._restoreQueuedEntry = async config => {
    rewritten = true;
    restorer._deferredLayouts.push({app: config.index === 2
        ? {get_state() { throw Error('disposed'); }, get_windows: () => []} : lateApp, sessionConfig: config});
    return [false, true, true];
};
restorer._moveSession = {moveWindowsByShellApp: async (_app, configs) => {
    configs[0].moved = true; return true;
}};
restorer._waitBeforeNextRestore = async () => true;
restorer._waitForRestoreEvent = async (_app, delay) => { now += delay * 1000; return safe; };
assert.equal(await restorer.restorePreviousSession(true, false), true);
assert.deepEqual(removed, ['/state/late-0.json']);
assert.match(state.get('restore-progress'), /1 records retained/);

// Cancellation while awaiting a late native result cannot retire records or
// clear the interrupted checkpoint, even if that native result is successful.
({restorer, state} = make());
let releaseLate;
restorer._heldApplications = {};
restorer._deferredLayouts = [{app: lateApp, sessionConfig: {desktop_file_id: 'late.desktop'}}];
restorer._moveSession = {moveWindowsByShellApp: () => new Promise(resolve => { releaseLate = resolve; }), destroy() {}};
let cancelledRetirements = 0;
const cancelling = restorer._reconcileDeferredLayouts(async () => cancelledRetirements++);
await Promise.resolve();
restorer.cancel();
releaseLate(true);
await cancelling;
assert.equal(cancelledRetirements, 0);
assert.equal(state.get('restore-active-application'), 'late.desktop');
console.log('Restore queue regressions passed');
