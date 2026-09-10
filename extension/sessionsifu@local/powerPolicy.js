'use strict';

import Gio from 'gi://Gio';


const UPOWER_NAME = 'org.freedesktop.UPower';
const UPOWER_PATH = '/org/freedesktop/UPower';
const UPOWER_INTERFACE = 'org.freedesktop.UPower';
const DISPLAY_PATH = '/org/freedesktop/UPower/devices/DisplayDevice';
const DEVICE_INTERFACE = 'org.freedesktop.UPower.Device';
const PROFILES_NAME = 'net.hadess.PowerProfiles';
const PROFILES_PATH = '/net/hadess/PowerProfiles';
const PROFILES_INTERFACE = 'net.hadess.PowerProfiles';

let initialized = false;
let upower = null;
let display = null;
let profiles = null;

function _proxy(name, path, iface) {
    try {
        return Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM, Gio.DBusProxyFlags.DO_NOT_AUTO_START,
            null, name, path, iface, null);
    } catch (_error) {
        return null;
    }
}

function _initialize() {
    if (initialized)
        return;
    initialized = true;
    upower = _proxy(UPOWER_NAME, UPOWER_PATH, UPOWER_INTERFACE);
    display = _proxy(UPOWER_NAME, DISPLAY_PATH, DEVICE_INTERFACE);
    profiles = _proxy(PROFILES_NAME, PROFILES_PATH, PROFILES_INTERFACE);
}

function _property(proxy, name, fallback) {
    try {
        return proxy?.get_cached_property(name)?.deepUnpack() ?? fallback;
    } catch (_error) {
        return fallback;
    }
}

export function state() {
    _initialize();
    const onBattery = Boolean(_property(upower, 'OnBattery', false));
    const percentage = Number(_property(display, 'Percentage', 100));
    const profile = String(_property(profiles, 'ActiveProfile', 'balanced'));
    return {
        onBattery,
        percentage: Number.isFinite(percentage) ? percentage : 100,
        powerSaver: profile === 'power-saver',
    };
}

export function policy(configuredInterval = 300) {
    const current = state();
    const critical = current.onBattery && current.percentage <= 10;
    const low = current.onBattery && current.percentage <= 20;
    return {
        ...current,
        critical,
        recallInterval: Math.max(configuredInterval,
            critical || low ? 1800 : current.onBattery ? 900 : configuredInterval),
        snapshotInterval: Math.max(configuredInterval,
            current.onBattery || current.powerSaver ? 900 : configuredInterval),
        screenshots: !critical && !low && !current.powerSaver,
        ocr: !current.onBattery && !current.powerSaver,
        workspacePassSeconds: current.onBattery || current.powerSaver ? 120 : 30,
        windowFreshSeconds: current.onBattery || current.powerSaver ? 300 : 60,
        previewQuality: current.onBattery || current.powerSaver ? 'storage' : null,
    };
}

export function watch(callback) {
    _initialize();
    const connections = [];
    for (const proxy of [upower, display, profiles]) {
        if (proxy)
            connections.push([proxy, proxy.connect('g-properties-changed', callback)]);
    }
    return () => {
        for (const [proxy, id] of connections) {
            try { proxy.disconnect(id); } catch (_error) {}
        }
    };
}
