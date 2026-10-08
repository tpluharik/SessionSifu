// Exercise the real tiling, geometry and shared queue modules without native UI.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

class Signals {
    constructor() { this.handlers = new Map(); this.serial = 0; }
    _init() {}
    connect(name, callback) {
        this.handlers.set(++this.serial, {name, callback});
        return this.serial;
    }
    disconnect(id) { this.handlers.delete(id); }
    emit(name, ...args) {
        for (const [id, handler] of [...this.handlers])
            if (handler.name === name && this.handlers.has(id)) handler.callback(this, ...args);
    }
}
const workspace = {};
class Window extends Signals {
    constructor(name, rect, area = {x: 0, y: 0, width: 1920, height: 1080}) {
        super();
        Object.assign(this, {name, rect, area, actor: {}, monitor: 0, workspace,
            resizes: [], raises: 0, resizable: true, movable: true, fullscreen: false});
    }
    get_title() { return this.name; }
    get_monitor() { return this.monitor; }
    get_workspace() { return this.workspace; }
    get_compositor_private() { return this.actor; }
    get_frame_rect() { return this.rect; }
    get_work_area_current_monitor() { return this.area; }
    allows_resize() { return this.resizable; }
    allows_move() { return this.movable; }
    is_fullscreen() { return this.fullscreen; }
    raise() {
        assert.ok(this.actor, 'Must not raise a destroyed partner');
        assert.ok(++this.raises < 4, 'Raised signals must not form a feedback loop');
        if (this.raiseError) throw Error('synthetic raise failure');
        this.emit('raised');
    }
    move_resize_frame(_user, x, y, width, height) {
        assert.ok(this.actor, 'Must not resize a destroyed partner');
        assert.ok([x, y, width, height].every(Number.isFinite) && width > 0 && height > 0);
        if (this.resizeError) throw Error('synthetic resize failure');
        this.resizes.push({x, y, width, height});
        this.rect = {x, y, width, height};
        this.emit('size-changed');
        this.resizeHook?.();
    }
    close() { this.actor = null; this.emit('unmanaging'); }
}
const display = new Signals();
display.get_n_monitors = () => 2;
const settings = new Map([['restore-window-tiling', true], ['raise-windows-together', true]]);
const apps = new Map();
const errors = [];
const context = vm.createContext({console, Map, Set, WeakSet,
    global: {display},});
const base = new URL('../extension/sessionsifu@local/', import.meta.url);
const modules = {};
for (const name of ['windowSafety.js', 'compositorOperations.js', 'runtimeSafety.js']) {
    modules[`./${name}`] = new vm.SourceTextModule(await readFile(new URL(name, base), 'utf8'), {context});
    await modules[`./${name}`].link(() => { throw Error('Unexpected dependency'); });
    await modules[`./${name}`].evaluate();
}
const tiling = new vm.SourceTextModule(await readFile(new URL('windowTilingSupport.js', base), 'utf8'), {context});
await tiling.link(name => {
    if (modules[name]) return modules[name];
    const exports = name === 'gi://Shell' ? {default: {AppSystem: {get_default: () => ({
        lookup_app: id => apps.get(id),
    })}}} : name === 'gi://Meta' ? {default: {GrabOp: {MOVING: 1}, Window: {$gtype: 1}}}
        : name === 'gi://GObject' ? {default: {registerClass: (_spec, klass) => klass,
            Object: Signals, SignalFlags: {RUN_LAST: 1},
            signal_handler_is_connected: (object, id) => object.handlers.has(id)}}
        : name === './utils/prefsUtils.js' ? {PrefsUtils: {getSettings: () => ({
            get_boolean: key => settings.get(key),
        })}} : name === './utils/log.js' ? {Log: class {
            error(error) { errors.push(error); } destroy() {}
        }} : null;
    assert.ok(exports, `Missing stub ${name}`);
    return new vm.SyntheticModule(Object.keys(exports), function () {
        for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
    }, {context});
});
await tiling.evaluate();
const {WindowTilingSupport: T} = tiling.namespace;
const queue = modules['./compositorOperations.js'].namespace.compositorOperations;
const {beginShutdown, cancelShutdown, configureLayoutSafety, beginMonitorChange} =
    modules['./runtimeSafety.js'].namespace;
let now = 0;
configureLayoutSafety(() => now);
const {pairedWindowGeometry} = modules['./windowSafety.js'].namespace;
const plain = value => JSON.parse(JSON.stringify(value));
async function drain() {
    await queue._tail;
    for (let index = 0; index < 4; index++) await Promise.resolve();
}
async function blockQueue() {
    let release;
    queue.run(() => new Promise(resolve => { release = resolve; }));
    await Promise.resolve();
    assert.ok(release);
    return release;
}
function pair(a, b) {
    apps.set(b.name, {get_windows: () => [b]});
    T.prepareToTile(a, {window_tile_for: {desktop_file_id: b.name, window_title: b.name}});
    assert.equal(a._tile_match_awsm, b);
    assert.equal(b._tile_match_awsm, a);
}
function freshPair(area) {
    if (T._settings) T.destroy();
    cancelShutdown();
    configureLayoutSafety(() => now);
    settings.set('restore-window-tiling', true);
    settings.set('raise-windows-together', true);
    T.initialize();
    const a = new Window('left', {x: 0, y: 0, width: 800, height: 700}, area);
    const b = new Window('right', {x: 800, y: 0, width: 800, height: 700}, area);
    pair(a, b);
    return {a, b};
}

const area = {x: 0, y: 0, width: 1920, height: 1080};
assert.equal(pairedWindowGeometry(area,
    {x: 0, y: 0, width: 1900, height: 700}, {x: 800, y: 0, width: 800, height: 700}), null);
assert.deepEqual(plain(pairedWindowGeometry({x: 1000, y: 0, width: 1920, height: 1080},
    {x: 1900, y: 0, width: 700, height: 700}, {x: 1000, y: 0, width: 800, height: 700})),
{x: 1000, y: 0, width: 900, height: 700});
assert.deepEqual(plain(pairedWindowGeometry({x: -1920, y: 0, width: 1920, height: 1080},
    {x: -1920, y: 0, width: 1000, height: 700}, {x: -1120, y: 0, width: 800, height: 700})),
{x: -920, y: 0, width: 600, height: 700});
for (const width of [-1, 0, NaN, Infinity, 1.5, 32769])
    assert.equal(pairedWindowGeometry(area, {x: 0, y: 0, width, height: 700},
        {x: 800, y: 0, width: 800, height: 700}), null);
assert.equal(pairedWindowGeometry({...area, x: 2147483600},
    {x: 2147483600, y: 0, width: 100, height: 700},
    {x: 2147483650, y: 0, width: 100, height: 700}), null);
assert.deepEqual(plain(pairedWindowGeometry(area,
    {x: 0, y: 0, width: 1000, height: 700}, {x: 800, y: -100, width: 1500, height: 1400})),
{x: 1000, y: 0, width: 920, height: 1080});
console.log('Paired geometry rejects crossed/invalid edges and handles offset monitors');

let {a, b} = freshPair();
for (let index = 0; index < 20; index++) pair(a, b);
assert.equal(a.handlers.size, 2);
assert.equal(b.handlers.size, 2);
assert.equal(T._signalsConnectedMap.size, 2);
apps.set('self', {get_windows: () => [a]});
assert.equal(T._getWindowAboutToResize({window_tile_for: {desktop_file_id: 'self'}}, a), null);
assert.equal(T._getWindowAboutToResize({}, a), null);
assert.equal(T._pairIsUsable(a, a), false);
b.monitor = 1;
assert.equal(T._pairIsUsable(a, b), false);
b.monitor = 0;
b.workspace = {};
assert.equal(T._pairIsUsable(a, b), false);
b.workspace = workspace;

let release = await blockQueue();
T._grabOpBegin(display, a, 2);
for (let index = 0; index < 20; index++) {
    a.rect.width = 900 + index;
    a.emit('size-changed');
}
assert.equal(T._pendingResizeRequests.size, 1);
assert.equal(b.resizes.length, 0, 'Resize must wait behind a native capture');
a.rect.width = 1000;
b.resizeHook = () => a.emit('size-changed');
release();
await drain();
assert.deepEqual(b.resizes, [{x: 1000, y: 0, width: 600, height: 700}]);
assert.equal(T._pendingResizeRequests.size, 0);
a.rect.width = 1900;
a.emit('size-changed');
await drain();
assert.equal(b.resizes.length, 1, 'Crossed edges must not invoke native resize');
T._grabOpEnd(display, a, 2);

// Real resize on a monitor left of the primary monitor.
({a, b} = freshPair({x: -1920, y: 0, width: 1920, height: 1080}));
a.rect.x = -1920;
b.rect.x = -1120;
T._grabOpBegin(display, a, 2);
a.rect.width = 1000;
a.emit('size-changed');
await drain();
assert.deepEqual(b.resizes, [{x: -920, y: 0, width: 600, height: 700}]);

// Each invalidation happens AFTER the request has entered the shared queue.
for (const invalidate of [
    () => b.close(),
    () => { b.actor = null; },
    () => { b.monitor = 1; },
    () => { b.workspace = {}; },
    () => { b.resizable = false; },
    () => { b.fullscreen = true; },
    () => beginShutdown(),
    () => settings.set('restore-window-tiling', false),
    () => T._grabOpEnd(display, a, 2),
    () => T._grabOpBegin(display, null, 2),
    () => T.destroy(),
]) {
    ({a, b} = freshPair());
    release = await blockQueue();
    T._grabOpBegin(display, a, 2);
    a.rect.width = 1000;
    a.emit('size-changed');
    invalidate();
    release();
    await drain();
    assert.equal(b.resizes.length, 0, 'Invalidated request touched the compositor');
}
console.log('Resize bursts coalesce; closed, stale, shutdown and disabled requests never run');

// Hotplug invalidates native work even if monitor count/pair identity stay the
// same and the queued operation starts after the quiet period has expired.
for (const action of ['resize', 'raise']) {
    ({a, b} = freshPair());
    release = await blockQueue();
    if (action === 'resize') {
        T._grabOpBegin(display, a, 2);
        a.rect.width = 1000;
        a.emit('size-changed');
    } else {
        a.emit('raised');
    }
    beginMonitorChange();
    now += 1000;
    release();
    await drain();
    assert.equal(b.resizes.length + b.raises, 0, 'Pre-hotplug tiling work must remain invalid');
}
({a, b} = freshPair());
beginMonitorChange();
a.emit('raised');
await drain();
assert.equal(b.raises, 0, 'No paired raise during the monitor quiet period');
now += 1000;
a.emit('raised');
await drain();
assert.equal(b.raises, 1, 'Fresh paired work resumes after the quiet period');

({a, b} = freshPair());
release = await blockQueue();
a.emit('raised');
b.emit('raised');
assert.equal(a.raises + b.raises, 0);
release();
await drain();
assert.equal(b.raises, 1);
assert.equal(a.raises, 0, 'Partner raised signal must not recurse');
b.emit('raised');
await drain();
assert.equal(a.raises, 1, 'Both sides of a pair must have live raised handlers');

// Old callbacks must not keep raising a partner that was replaced.
release = await blockQueue();
a.emit('raised');
const c = new Window('replacement', {x: 800, y: 0, width: 800, height: 700});
pair(a, c);
assert.equal(b._tile_match_awsm, undefined);
assert.equal(b.handlers.size, 0);
release();
await drain();
assert.equal(b.raises, 1);
a.emit('raised');
await drain();
assert.equal(c.raises, 1);
c.close();
assert.equal(a._tile_match_awsm, undefined);
assert.equal(a.handlers.size, 0);
assert.equal(T._signalsConnectedMap.size, 0);

// A destroy/initialize cycle cannot resurrect queued native operations.
({a, b} = freshPair());
release = await blockQueue();
a.emit('raised');
T._grabOpBegin(display, a, 2);
a.rect.width = 1000;
a.emit('size-changed');
T.destroy();
T.initialize();
release();
await drain();
assert.equal(b.raises, 0);
assert.equal(b.resizes.length, 0);
assert.equal(a.handlers.size + b.handlers.size, 0);
console.log('Pair replacement, unmanaging and re-enable invalidate old signals and requests');

// Moving one pair must not disconnect the raised handlers of other pairs.
({a, b} = freshPair());
const otherLeft = new Window('other-left', {x: 0, y: 0, width: 800, height: 700});
const otherRight = new Window('other-right', {x: 800, y: 0, width: 800, height: 700});
pair(otherLeft, otherRight);
T._grabOpBegin(display, a, 1);
a.rect.x = 20;
T._grabOpEnd(display, a, 1);
assert.equal(a._tile_match_awsm, undefined);
assert.equal(b.handlers.size, 0);
otherLeft.emit('raised');
await drain();
assert.equal(otherRight.raises, 1);
assert.equal(errors.length, 0, 'Normal safety paths must not emit errors');

// Exceptions must release recursion guards and leave the shared queue usable.
({a, b} = freshPair());
b.raiseError = true;
a.emit('raised');
await drain();
assert.equal(errors.length, 1);
b.raiseError = false;
a.emit('raised');
await drain();
assert.equal(b.raises, 2);
T._grabOpBegin(display, a, 2);
a.rect.width = 1000;
b.resizeError = true;
a.emit('size-changed');
await drain();
assert.equal(errors.length, 2);
b.resizeError = false;
a.emit('size-changed');
await drain();
assert.equal(b.resizes.length, 1);
assert.equal(T._resizingWindows.has(a), false);
assert.equal(T._raisingWindows.has(b), false);
assert.equal(await queue.run(() => 42), 42);
T.destroy();
assert.equal(display.handlers.size, 0);
console.log('Native failures clear recursion guards and leave no display/window handlers');
