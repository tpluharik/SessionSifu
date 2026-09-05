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

// Matching the workspace is NOT proof that geometry/state was applied.
const saved = {windows_count: 1, window_title: 'test', desktop_number: 0};
const win = {get_title: () => 'test', get_workspace: () => ({index: () => 0})};
assert.equal(direct._getOneMatchedSavedWindow(win, [saved]), saved);
assert.equal(saved.moved, undefined);
console.log('Compositor serialization and layout regressions passed');
