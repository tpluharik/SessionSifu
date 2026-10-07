// Exercise the real tracker's cleanup boundaries without changing the desktop.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

let safe = true;
const removed = [];
const restoreSessionObject = {};
const autocloseObject = {sessionClosedByUser: false};
const context = vm.createContext({console, Map, Set, WeakMap, WeakSet});
const source = new vm.SourceTextModule(await readFile(new URL(
    '../extension/sessionsifu@local/openWindowsTracker.js', import.meta.url), 'utf8'), {context});
await source.link(name => {
    const exports = name === './runtimeSafety.js' ? {
        mayRestoreApplications: () => safe,
        beginShutdown: () => { safe = false; },
        cancelShutdown: () => { safe = true; },
    } : name === './restoreSession.js' ? {restoreSessionObject}
        : name === './ui/autoclose.js' ? {autocloseObject}
        : name === './utils/fileUtils.js' ? {removeFile: path => removed.push(path)}
        : name === './utils/prefsUtils.js' ? {PrefsUtils: {}}
        : name === './windowTilingSupport.js' ? {WindowTilingSupport: {}}
        : name.includes('/extensions/extension.js') ? {Extension: {}}
        : name === 'gi://GLib' ? {default: {FileTest: {EXISTS: 1}, file_test: () => true,
            Source: {remove() {}}}}
        : name === 'gi://Shell' ? {default: {AppState: {STOPPED: 0}}}
        : name.startsWith('gi://') ? {default: {}} : {};
    return new vm.SyntheticModule(Object.keys(exports), function () {
        for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
    }, {context});
});
await source.evaluate();
const {OpenWindowsTracker} = source.namespace;
const handlers = new Map();
let signalId = 0;
const window = {get_title: () => 'sheet',
    connect: (name, callback) => { handlers.set(++signalId, {name, callback}); return signalId; },
    disconnect: id => handlers.delete(id)};
const app = {state: 1, get_name: () => 'LibreOffice',
    connect: (name, callback) => { handlers.set(++signalId, {name, callback}); return signalId; },
    disconnect: id => handlers.delete(id)};
const tracker = Object.assign(Object.create(OpenWindowsTracker.prototype), {
    _windowSessionRecords: new WeakMap(), _signals: [],
    _windowTracker: {get_window_app: () => app},
    _log: {debug() {}, error(error) { throw error; }},
    _meta_is_restarting: false,
});
tracker._connectSignalsToCleanUpSessionFile(window, '/state/libreoffice-startcenter', '123.json');
for (let index = 0; index < 20; index++)
    tracker._connectSignalsToCleanUpSessionFile(window, '/state/libreoffice-startcenter', '123.json');
assert.equal(handlers.size, 2, 'Repeated saves must not add cleanup callbacks');
tracker._connectSignalsToCleanUpSessionFile(window, '/state/libreoffice-calc', '123.json');
assert.deepEqual(removed, ['/state/libreoffice-startcenter/123.json']);
assert.equal(handlers.size, 2, 'WM_CLASS changes must reuse cleanup callbacks');

removed.length = 0;
safe = false;
tracker._cleanUpSessionFileByWindow(window, '/state/libreoffice-calc', '123.json');
assert.equal(removed.length, 0, 'Shutdown must preserve recovery data');
safe = true;
restoreSessionObject.activeRestorer = {};
tracker._cleanUpSessionFileByWindow(window, '/state/libreoffice-calc', '123.json');
assert.equal(removed.length, 0, 'Restore must protect queued recovery data');
restoreSessionObject.activeRestorer = null;
const closing = [...handlers.values()].find(item => item.name === 'unmanaging');
closing.callback();
assert.deepEqual(removed, ['/state/libreoffice-calc/123.json'],
    'Close must delete only the current record, not its directory or old path');

let cancelled = 0;
tracker._runningSaveCancelableMap = new Map([[window, {
    is_cancelled: () => false, cancel: () => cancelled++,
}]]);
tracker._saveSummaryCancellable = {cancel: () => cancelled++};
tracker._windowsAboutToSaveSet = new Set([window]);
tracker._summaryAboutToSave = true;
tracker._saveSessionByBatchTimeoutId = 1;
tracker._beginShutdown();
assert.equal(safe, false);
assert.equal(cancelled, 2);
assert.equal(tracker._windowsAboutToSaveSet.size, 0);
assert.equal(tracker._saveSessionByBatchTimeoutId, 0);
console.log('Window tracker shutdown, record migration and cleanup regressions passed');

const restoreActivity = {saving: true};
const saverSource = new vm.SourceTextModule(await readFile(new URL(
    '../extension/sessionsifu@local/continuousSaver.js', import.meta.url), 'utf8'), {context});
await saverSource.link(name => {
    const exports = name === './runtimeSafety.js' ? {mayRestoreApplications: () => safe}
        : name === './recallActivity.js' ? {restoreActivity}
        : name.startsWith('gi://') ? {default: {}} : {};
    return new vm.SyntheticModule(Object.keys(exports), function () {
        for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
    }, {context});
});
await saverSource.evaluate();
let snapshots = 0;
const saver = Object.assign(Object.create(saverSource.namespace.ContinuousSaver.prototype), {
    _settings: {get_boolean: () => true},
    _saver: {saveSessionAsync: async () => { snapshots++; return true; }},
    _prune() {}, _log: {error(error) { throw error; }},
});
safe = true;
assert.equal(await saver.saveNow(), false, 'Partial restore must not overwrite automatic history');
restoreActivity.saving = false;
safe = false;
assert.equal(await saver.saveNow(), false, 'Shutdown must not overwrite automatic history');
safe = true;
assert.equal(await saver.saveNow(), true);
assert.equal(snapshots, 1);
console.log('Automatic history keeps pre-restore and pre-shutdown recovery snapshots');
