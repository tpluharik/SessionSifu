// Run actual recorder lifecycle methods without accessing the host compositor.
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

function signals() {
    const callbacks = new Map();
    let next = 0;
    return {
        connect: (name, callback) => { callbacks.set(++next, {name, callback}); return next; },
        disconnect: id => callbacks.delete(id),
        emit: name => { for (const item of callbacks.values()) if (item.name === name) item.callback(); },
        callbacks,
    };
}
let now = 0;
let safe = true;
let reads = 0;
let timerId = 0;
const timers = new Map();
const activity = Object.assign(signals(), {saving: false});
const overview = Object.assign(signals(), {visible: false});
const layoutManager = signals();
const workspace = signals();
const display = signals();
const settings = Object.assign(signals(), {
    get_boolean: () => true, get_int64: () => 0, get_int: () => 60,
});
const context = vm.createContext({console, Date, Map, Set,
    global: {workspace_manager: workspace, display,
        get_window_actors: () => { reads++; return []; }},
});
const source = new vm.SourceTextModule(await readFile(new URL(
    '../extension/sessionsifu@local/recallRecorder.js', import.meta.url), 'utf8'), {context});
const stubs = {
    'gi://GLib': {default: {get_monotonic_time: () => now,
        timeout_add: (_priority, delay, callback) => {
            timers.set(++timerId, {delay, callback}); return timerId;
        }, timeout_add_seconds: () => ++timerId,
        Source: {remove: id => timers.delete(id)},
    }},
    'resource:///org/gnome/shell/ui/main.js': {
        overview, layoutManager, sessionMode: {isLocked: false}, modalCount: 0,
    },
    './recallActivity.js': {recallActivity: {}, restoreActivity: activity},
    './runtimeSafety.js': {mayRestoreApplications: () => safe},
    './compositorOperations.js': {compositorOperations: {}},
    './windowSafety.js': {isWindowCaptureSafe() {}, isWindowRegionUnobscured() {}},
    './recallPrivacy.js': {recallExclusions() {}, screenshotBlockingExclusions() {}, screenshotCaptureMode() {}},
    './recallWorkspaceCache.js': {clearPreviewCache() {}},
    './utils/log.js': {Log: class {}},
};
await source.link(name => {
    const exports = stubs[name] ?? (name.startsWith('gi://') ? {default: {}} : {});
    return new vm.SyntheticModule(Object.keys(exports), function () {
        for (const [key, value] of Object.entries(exports)) this.setExport(key, value);
    }, {context});
});
await source.evaluate();
const recorder = new source.namespace.RecallRecorder(settings);
assert.equal(recorder._mayCaptureWorkspace(), true);
activity.saving = true;
activity.emit('changed');
assert.equal(recorder._mayCaptureWorkspace(), false);
await recorder._captureVisibleWorkspaceCache();
assert.equal(reads, 0, 'Restore must suppress compositor access, not just output files');
const before = recorder._screenshotGeneration;
activity.saving = false;
activity.emit('changed');
assert.ok(recorder._screenshotGeneration > before, 'Old queued captures must be invalidated');
assert.equal(recorder._mayCaptureWorkspace(), false, 'Restore completion needs settle time');
now += 2500 * 1000;
assert.equal(recorder._mayCaptureWorkspace(), true, 'Capture must resume automatically');
const generation = recorder._screenshotGeneration;
layoutManager.emit('monitors-changed');
assert.ok(recorder._screenshotGeneration > generation);
assert.equal(recorder._mayCaptureWorkspace(), false);
display.emit('notify::focus-window');
assert.equal(timers.get(recorder._workspaceCacheTimeoutId).delay, 2500,
    'Focus events must not shorten the display-change settle period');
now += 2500 * 1000;
assert.equal(recorder._mayCaptureWorkspace(), true);
safe = false;
assert.equal(recorder._mayCaptureWorkspace(), false);
assert.equal(await recorder.saveNow(), false, 'Shutdown must prevent metadata work too');
recorder.destroy();
assert.equal(activity.callbacks.size, 0);
assert.equal(layoutManager.callbacks.size, 0);
assert.equal(timers.size, 0);
safe = true;
assert.equal(await recorder.saveNow(), false, 'Late callbacks after disable must be harmless');
console.log('Recall restore, display-change and shutdown lifecycle regressions passed');
