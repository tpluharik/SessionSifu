import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';

const properties = new Map([
    ['OnBattery', false], ['Percentage', 100], ['ActiveProfile', 'balanced'],
]);
let disconnected = 0;
const Gio = {
    BusType: {SYSTEM: 0},
    DBusProxyFlags: {DO_NOT_AUTO_START: 1},
    DBusProxy: {new_for_bus_sync: (_bus, _flags, _info, _name, path) => ({
        get_cached_property: name => ({deepUnpack: () => properties.get(name)}),
        connect: () => path.length,
        disconnect: () => { disconnected++; },
    })},
};
const context = vm.createContext({console});
const source = new vm.SourceTextModule(await readFile(new URL(
    '../extension/sessionsifu@local/powerPolicy.js', import.meta.url), 'utf8'), {context});
await source.link(name => new vm.SyntheticModule(['default'], function () {
    this.setExport('default', Gio);
}, {context, identifier: name}));
await source.evaluate();

assert.equal(source.namespace.policy(300).recallInterval, 300);
properties.set('OnBattery', true);
properties.set('Percentage', 55);
let policy = source.namespace.policy(300);
assert.equal(policy.recallInterval, 900);
assert.equal(policy.snapshotInterval, 900);
assert.equal(policy.ocr, false);
assert.equal(policy.screenshots, true);
properties.set('Percentage', 15);
policy = source.namespace.policy(300);
assert.equal(policy.recallInterval, 1800);
assert.equal(policy.screenshots, false);
properties.set('Percentage', 8);
assert.equal(source.namespace.policy(300).critical, true);
properties.set('OnBattery', false);
properties.set('ActiveProfile', 'power-saver');
policy = source.namespace.policy(300);
assert.equal(policy.screenshots, false);
assert.equal(policy.ocr, false);
const stop = source.namespace.watch(() => {});
stop();
assert.equal(disconnected, 3);
console.log('Adaptive power policy checks passed');
