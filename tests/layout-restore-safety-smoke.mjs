// Real layout/queue/safety modules; fake windows, clock and GLib only.
// Never imports GI, starts an application, queries the host or sends signals.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

class Signals {
    constructor() { this.handlers = new Map(); this.serial = 0; }
    connect(name, callback) { this.handlers.set(++this.serial, {name, callback}); return this.serial; }
    disconnect(id) { this.handlers.delete(id); }
    emit(name, ...args) {
        for (const [id, handler] of [...this.handlers])
            if (this.handlers.has(id) && handler.name === name) handler.callback(this, ...args);
    }
}
let now = 0;
let serial = 0;
const timers = new Map();
const glib = {
    PRIORITY_LOW: 0, SOURCE_REMOVE: false, SOURCE_CONTINUE: true,
    get_monotonic_time: () => now * 1000,
    timeout_add: (_priority, delay, callback) => {
        timers.set(++serial, {delay, due: now + delay, callback}); return serial;
    },
    Source: {remove: id => timers.delete(id)},
};
const workspaces = Array.from({length: 3}, (_, index) => ({index: () => index}));
const display = new Signals();
display.get_n_monitors = () => 2;
display.get_primary_monitor = () => 0;
const errors = [];
let app;
const context = vm.createContext({console, Date, Map, Set, WeakSet,
    global: {display, workspace_manager: {
        n_workspaces: workspaces.length, get_workspace_by_index: index => workspaces[index],
    }},
});
const base = new URL('../extension/sessionsifu@local/', import.meta.url);
const modules = {};
for (const name of ['windowSafety.js', 'compositorOperations.js', 'runtimeSafety.js']) {
    modules[`./${name}`] = new vm.SourceTextModule(await readFile(new URL(name, base), 'utf8'), {context});
    await modules[`./${name}`].link(() => { throw Error('Unexpected dependency'); });
    await modules[`./${name}`].evaluate();
}
const source = new vm.SourceTextModule(await readFile(new URL('moveSession.js', base), 'utf8'), {context});
await source.link(name => {
    if (modules[name]) return modules[name];
    const values = name === 'gi://GLib' ? {default: glib}
        : name === 'gi://Shell' ? {default: {
            AppSystem: {get_default: () => ({})},
            WindowTracker: {get_default: () => ({get_window_app: () => app})},
        }} : name === 'gi://Meta' ? {default: {MaximizeFlags: {BOTH: 3}}}
        : name === './constants.js' ? {shellVersion: 50}
        : name === './restoreSafety.js' ? {WINDOW_RESTORE_INTERVAL_MS: 750}
        : name === './windowTilingSupport.js' ? {WindowTilingSupport: {prepareToTile() {}}}
        : name === './ui/uiHelper.js' ? {ignoreWindows: () => false}
        : name === './utils/log.js' ? {Log: class {
            isDebug() { return false; } debug() {} info() {} destroy() {}
            error(error) { errors.push(error); }
        }} : name === './utils/fileUtils.js' ? {default_sessionName: 'synthetic'}
        : name === 'gi://Gio' ? {default: {}} : null;
    assert.ok(values, `Missing stub ${name}`);
    return new vm.SyntheticModule(Object.keys(values), function () {
        for (const [key, value] of Object.entries(values)) this.setExport(key, value);
    }, {context});
});
await source.evaluate();
const {MoveSession} = source.namespace;
const {compositorOperations: queue} = modules['./compositorOperations.js'].namespace;
const {configureLayoutSafety, beginMonitorChange, beginShutdown, cancelShutdown} =
    modules['./runtimeSafety.js'].namespace;
configureLayoutSafety(() => now);

class Window extends Signals {
    constructor() {
        super(); Object.assign(this, {actor: {}, maximized: true, monitor: 0,
            workspace: workspaces[0], native: [], fullscreen: false});
    }
    get_title() { return 'Fixture'; }
    get_wm_class() { return 'fixture'; }
    get_monitor() { return this.monitor; }
    get_workspace() { return this.workspace; }
    get_compositor_private() { return this.actor; }
    is_maximized() { return this.maximized; }
    is_fullscreen() { return this.fullscreen; }
    set_unmaximize_flags() {}
    unmaximize() { this.native.push('unmaximize'); }
    is_on_all_workspaces() { return false; }
    allows_move() { return true; }
    allows_resize() { return true; }
    get_work_area_current_monitor() { return {x: 0, y: 0, width: 1920, height: 1080}; }
    move_resize_frame() { this.native.push('resize'); }
    move_to_monitor(index) { this.native.push(`monitor:${index}`); }
    change_workspace_by_index(index) { this.native.push(`workspace:${index}`); this.workspace = workspaces[index]; }
}
async function flush() { for (let index = 0; index < 12; index++) await Promise.resolve(); }
async function tick(ms) {
    now += ms;
    for (const [id, timer] of [...timers]) {
        if (timers.has(id) && timer.due <= now) {
            const again = timer.callback();
            if (!again) timers.delete(id);
            else timer.due = now + timer.delay;
        }
    }
    await flush();
}
function fixture() {
    assert.equal(timers.size, 0, 'Previous case leaked a timeout');
    cancelShutdown(); configureLayoutSafety(() => now);
    const win = new Window();
    app = {get_windows: () => [win], get_name: () => 'Fixture'};
    const mover = new MoveSession();
    // Pacing itself is covered elsewhere. This fixture tests geometry waits.
    mover._waitForCompositor = async () => true;
    const saved = {window_title: 'Fixture', wm_class: 'fixture', windows_count: 1,
        desktop_number: 1, monitor_number: 0, window_state: {meta_maximized: false},
        window_position: {provider: 'Meta', x_offset: 0, y_offset: 0, width: 600, height: 400}};
    return {win, mover, saved};
}

// A 500ms timer alone does not authorize resizing a still-maximized window.
let {win, mover, saved} = fixture();
let pending = mover.moveWindowByMetaWindow(win, [saved]);
await flush();
assert.deepEqual(win.native, ['unmaximize']);
await tick(500);
assert.deepEqual(win.native, ['unmaximize']);
win.maximized = false;
await tick(500);
assert.equal(await pending, true);
assert.deepEqual(win.native, ['unmaximize', 'resize', 'workspace:1']);
assert.equal(saved.moved, true);

// Saved maximized/fullscreen states still restore placement without resizing.
for (const state of ['maximized', 'fullscreen']) {
    ({win, mover, saved} = fixture());
    if (state === 'maximized') saved.window_state.meta_maximized = true;
    if (state === 'fullscreen') { win.maximized = false; win.fullscreen = true; }
    assert.equal(await mover.moveWindowByMetaWindow(win, [saved]), true);
    assert.deepEqual(win.native, ['workspace:1']);
    assert.equal(saved.moved, true);
}

// An unresponsive unmaximize is bounded and retains the saved record.
({win, mover, saved} = fixture());
pending = mover.moveWindowByMetaWindow(win, [saved]);
await flush(); await tick(2000);
assert.equal(await pending, false);
assert.deepEqual(win.native, ['unmaximize']);
assert.equal(saved.moved, undefined);

// A delayed GLib dispatch cannot apply geometry beyond the settle deadline.
({win, mover, saved} = fixture());
pending = mover.moveWindowByMetaWindow(win, [saved]);
await flush(); win.maximized = false; await tick(2500);
assert.equal(await pending, false);
assert.deepEqual(win.native, ['unmaximize']);
assert.equal(saved.moved, undefined);

// Invalidate a live callback while waiting, not only before queue ownership.
for (const invalidate of ['mapping', 'monitor', 'fullscreen', 'close', 'shutdown', 'destroy']) {
    ({win, mover, saved} = fixture());
    let current = true;
    pending = mover.moveWindowByMetaWindow(win, [saved], () => current);
    await flush();
    if (invalidate === 'mapping') current = false;
    if (invalidate === 'monitor') beginMonitorChange();
    if (invalidate === 'fullscreen') win.fullscreen = true;
    if (invalidate === 'close') { mover.cancelWindow(win); win.actor = null; }
    if (invalidate === 'shutdown') beginShutdown();
    if (invalidate === 'destroy') mover.destroy();
    win.maximized = false;
    await tick(1000); // quiet period expired: the old generation must still fail
    assert.equal(await pending, false, invalidate);
    assert.deepEqual(win.native, ['unmaximize'], invalidate);
    assert.equal(saved.moved, undefined, invalidate);
}

// The app-group entrypoint carries the same guard through each await.
({win, mover, saved} = fixture());
let current = true;
pending = mover.moveWindowsByShellApp(app, [saved], () => {}, () => current);
await flush(); current = false; win.maximized = false; await tick(500);
assert.equal(await pending, false);
assert.deepEqual(win.native, ['unmaximize']);
assert.equal(saved.moved, undefined);

// Monitor-change confirmation must not proceed into geometry after hotplug.
({win, mover, saved} = fixture());
saved.monitor_number = 1;
pending = mover.moveWindowByMetaWindow(win, [saved]);
await flush(); beginMonitorChange(); win.monitor = 1; await tick(1000);
assert.equal(await pending, false);
assert.deepEqual(win.native, ['monitor:1']);
assert.equal(display.handlers.size, 0, 'Monitor waiter leaked display signals');
assert.equal(win.handlers.size, 0, 'Monitor waiter leaked window signals');

// Quiet-period requests do no native work; a fresh request later can recover.
({win, mover, saved} = fixture());
win.maximized = false;
beginMonitorChange();
assert.equal(await mover.moveWindowByMetaWindow(win, [saved]), false);
assert.deepEqual(win.native, []);
await tick(1000);
assert.equal(await mover.moveWindowByMetaWindow(win, [saved]), true);
assert.deepEqual(win.native, ['resize', 'workspace:1']);

// A request queued before hotplug stays invalid after the quiet period.
({win, mover, saved} = fixture());
win.maximized = false;
let release;
const blocker = queue.run(() => new Promise(resolve => { release = resolve; }));
await flush();
pending = mover.moveWindowByMetaWindow(win, [saved]);
beginMonitorChange(); await tick(1000); release(); await blocker;
assert.equal(await pending, false);
assert.deepEqual(win.native, []);

// Regression for validity checked only at entry: invalidate at the final await.
({win, mover, saved} = fixture());
current = true;
mover._restoreWindowStates = () => new Promise(resolve => { release = resolve; });
pending = mover.moveWindowByMetaWindow(win, [saved], () => current);
await flush(); current = false; release(true);
assert.equal(await pending, false);
assert.deepEqual(win.native, []);
assert.equal(saved.moved, undefined);
assert.equal(errors.length, 0);
assert.equal(timers.size, 0);

// A disposed getter must not escape the timer or hang compositor ownership.
({win, mover, saved} = fixture());
pending = mover.moveWindowByMetaWindow(win, [saved]);
await flush();
win.is_maximized = () => { throw Error('synthetic disposed window'); };
await tick(500);
assert.equal(await pending, false);
assert.equal(errors.length, 1);
assert.equal(timers.size, 0);
assert.equal(saved.moved, undefined);
console.log('Layout safety: settled unmaximize, bounded waits, cancellation, hotplug generations and cleanup passed');
