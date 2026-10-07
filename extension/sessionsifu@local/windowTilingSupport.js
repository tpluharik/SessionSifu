'use strict';

import Shell from 'gi://Shell';
import Meta from 'gi://Meta';
import GObject from 'gi://GObject';

import * as Log from './utils/log.js';
import {PrefsUtils} from './utils/prefsUtils.js';
import {isWindowUsable, pairedWindowGeometry} from './windowSafety.js';
import {mayRestoreApplications} from './runtimeSafety.js';
import {compositorOperations} from './compositorOperations.js';


// Singleton class, all methods are `static`
export class WindowTilingSupport {

    static initialize() {
        this._generation = (this._generation ?? 0) + 1;
        this._destroyed = false;
        this._log = new Log.Log();
        this._settings = PrefsUtils.getSettings();
        this._defaultAppSystem = Shell.AppSystem.get_default();

        this._signals = new WindowTilingSupportSignals();

        this._signalsConnectedMap = new Map();
        this._raisingWindows = new WeakSet();
        this._pendingRaises = new WeakSet();
        this._resizingWindows = new WeakSet();
        this._pendingResizeRequests = new Map();
        this._resizeGeneration = 0;

        this._grabbedWindowsAboutToUntileMap = new Map();

        this._grabOpBeginId = global.display.connect('grab-op-begin', this._grabOpBegin.bind(this));
        this._grabOpEndId = global.display.connect('grab-op-end', this._grabOpEnd.bind(this));

    }

    static prepareToTile(metaWindow, window_tiling) {
        if (!window_tiling || !this._isWindowUsable(metaWindow) ||
            !this._settings.get_boolean('restore-window-tiling'))
            return;
        try {
            const partner = this._getWindowAboutToResize(window_tiling, metaWindow);
            if (!this._pairIsUsable(metaWindow, partner))
                return;
            if (metaWindow._tile_match_awsm === partner && partner._tile_match_awsm === metaWindow)
                return;
            this._detachPair(metaWindow);
            this._detachPair(partner);
            metaWindow._tile_match_awsm = partner;
            partner._tile_match_awsm = metaWindow;
            this._connectWindowSignals(metaWindow);
            this._connectWindowSignals(partner);
            // Save both sides even when only one side had a restore record.
            this._signals.emit('window-tiled', metaWindow, partner);
            this._signals.emit('window-tiled', partner, metaWindow);
        } catch (error) {
            this._detachPair(metaWindow);
            this._log?.error(error);
        }
    }

    static _isWindowUsable(window) {
        return !this._destroyed && Boolean(this._settings) &&
            mayRestoreApplications() && isWindowUsable(window);
    }

    static _pairIsUsable(window, partner) {
        try {
            return window !== partner && this._isWindowUsable(window) &&
                this._isWindowUsable(partner) &&
                window.get_monitor() === partner.get_monitor() &&
                window.get_workspace() === partner.get_workspace();
        } catch (_error) {
            return false;
        }
    }

    static _connectWindowSignals(window) {
        if (this._signalsConnectedMap.has(window))
            return;
        const ids = {};
        this._signalsConnectedMap.set(window, ids);
        ids.raised = window.connect('raised', () => this._onRaised(window));
        ids.unmanaging = window.connect('unmanaging', () => this._detachPair(window));
    }

    static _queueOperation(operation, mayRun, finished) {
        const generation = this._generation;
        compositorOperations.run(operation, () =>
            generation === this._generation && !this._destroyed && mayRun()).then(
            () => finished(), error => {
                finished();
                this._log?.error(error);
            });
    }

    static _onRaised(window) {
        const partner = window._tile_match_awsm;
        const mayRun = () => this._pairIsUsable(window, partner) &&
            window._tile_match_awsm === partner && partner._tile_match_awsm === window &&
            this._settings.get_boolean('restore-window-tiling') &&
            this._settings.get_boolean('raise-windows-together');
        if (!mayRun() || this._raisingWindows.has(window) ||
            this._pendingRaises.has(window) || this._pendingRaises.has(partner))
            return;
        const pending = this._pendingRaises;
        pending.add(window);
        pending.add(partner);
        this._queueOperation(() => {
            // raise() synchronously emits raised; never enqueue its echo.
            this._raisingWindows.add(window);
            this._raisingWindows.add(partner);
            try {
                partner.raise();
            } finally {
                this._raisingWindows.delete(window);
                this._raisingWindows.delete(partner);
            }
        }, mayRun, () => {
            pending.delete(window);
            pending.delete(partner);
        });
    }

    static _grabOpBegin(display, grabbedWindow, grabOp) {
        // Fix `JS ERROR: TypeError: grabbedWindow is null` while `grab-op-begin` by `dash to panel`,
        // who emits nullish grabbedWindow.
        this._stopResize();
        if (!this._isWindowUsable(grabbedWindow)) return;

        // Check if the grabbed window has been in a tiling state with another window
        const windowAboutToResize = grabbedWindow._tile_match_awsm;
        if (!this._pairIsUsable(grabbedWindow, windowAboutToResize) ||
            windowAboutToResize._tile_match_awsm !== grabbedWindow)
            return;

        // When position changed
        if (grabOp === Meta.GrabOp.MOVING) {
            const rect = grabbedWindow.get_frame_rect();
            const oldGrabbedWindowRect = {x: rect.x, y: rect.y,
                width: rect.width, height: rect.height};
            this._grabbedWindowsAboutToUntileMap.set(grabbedWindow, oldGrabbedWindowRect);
            return;
        }

        if (!this._settings.get_boolean('restore-window-tiling')) return;

        this._sizeChangedWindow = grabbedWindow;
        this._sizeChangedId = grabbedWindow.connect('size-changed', () =>
            this._queuePartnerResize(grabbedWindow, windowAboutToResize));
    }

    static _queuePartnerResize(window, partner) {
        const resizeGeneration = this._resizeGeneration;
        const mayRun = () => resizeGeneration === this._resizeGeneration &&
            this._sizeChangedWindow === window && this._pairIsUsable(window, partner) &&
            window._tile_match_awsm === partner && partner._tile_match_awsm === window &&
            this._settings.get_boolean('restore-window-tiling') &&
            !window.is_fullscreen?.() && !partner.is_fullscreen?.() &&
            partner.allows_move?.() !== false && partner.allows_resize?.() !== false;
        if (!mayRun() || this._resizingWindows.has(window) ||
            this._resizingWindows.has(partner) || this._pendingResizeRequests.has(window))
            return;
        const request = {resizeGeneration};
        this._pendingResizeRequests.set(window, request);
        this._queueOperation(() => {
            // Read current geometry after acquiring ownership; coalesce noisy
            // size signals instead of replaying stale rectangles one by one.
            const current = partner.get_frame_rect();
            const geometry = pairedWindowGeometry(partner.get_work_area_current_monitor(),
                window.get_frame_rect(), current);
            if (!geometry || !mayRun() ||
                ['x', 'y', 'width', 'height'].every(key => current[key] === geometry[key]))
                return;
            this._resizingWindows.add(window);
            this._resizingWindows.add(partner);
            try {
                partner.move_resize_frame(false,
                    geometry.x, geometry.y, geometry.width, geometry.height);
            } finally {
                this._resizingWindows.delete(window);
                this._resizingWindows.delete(partner);
            }
        }, mayRun, () => {
            if (this._pendingResizeRequests.get(window) === request)
                this._pendingResizeRequests.delete(window);
        });
    }

    static _stopResize() {
        this._resizeGeneration++;
        this._disconnectObjectSignal(this._sizeChangedWindow, this._sizeChangedId);
        this._sizeChangedId = 0;
        this._sizeChangedWindow = null;
        this._pendingResizeRequests?.clear();
    }

    static _grabOpEnd(display, grabbedWindow, grabOp) {
        // grabbedWindow is null, tested on Fedora 35 with Gnome 41.6 and Wayland,
        // by clicking the indicator show and then hide the popup menu
        this._stopResize();
        if (!grabbedWindow) return;

        const oldGrabbedWindowRect = this._grabbedWindowsAboutToUntileMap?.get(grabbedWindow);
        this._grabbedWindowsAboutToUntileMap?.delete(grabbedWindow);
        if (!oldGrabbedWindowRect || !this._isWindowUsable(grabbedWindow))
            return;
        const currentRect = grabbedWindow.get_frame_rect();
        // Untile if any of x, y, width and height changed
        if (oldGrabbedWindowRect &&
            (oldGrabbedWindowRect.x !== currentRect.x
            || oldGrabbedWindowRect.y !== currentRect.y
            || oldGrabbedWindowRect.width !== currentRect.width
            || oldGrabbedWindowRect.height !== currentRect.height))
        {
            this._detachPair(grabbedWindow);
        }

    }

    static _getWindowAboutToResize(window_tiling, source) {
        const window_tile_for = window_tiling?.window_tile_for;
        if (!window_tile_for?.desktop_file_id) return null;
        const shellApp = this._defaultAppSystem.lookup_app(window_tile_for.desktop_file_id);
        if (!shellApp) return null;
        const windows = shellApp.get_windows().filter(window =>
            window !== source && this._isWindowUsable(window));
        if (!windows || !windows.length) return null;

        let windowAboutToResize = null;
        if (windows.length === 1) {
            windowAboutToResize = windows[0];
        } else {
            // Get one window by matching title
            for (const win of windows) {
                if (win.get_title() === window_tile_for.window_title) {
                    windowAboutToResize = win;
                    break;
                }
            }
        }

        return windowAboutToResize;
    }

    static connect(signal, func) {
        return this._signals.connect(signal, func);
    }

    static disconnect(id) {
        this._signals.disconnect(id);
    }

    static _detachPair(window) {
        if (!window) return;
        const partner = window._tile_match_awsm;
        const reciprocal = partner && partner._tile_match_awsm === window;
        delete window._tile_match_awsm;
        if (reciprocal)
            delete partner._tile_match_awsm;
        if (this._sizeChangedWindow === window || this._sizeChangedWindow === partner)
            this._stopResize();
        for (const member of reciprocal ? [window, partner] : [window]) {
            this._grabbedWindowsAboutToUntileMap?.delete(member);
            const ids = this._signalsConnectedMap?.get(member);
            if (ids) {
                this._disconnectObjectSignal(member, ids.raised);
                this._disconnectObjectSignal(member, ids.unmanaging);
                this._signalsConnectedMap.delete(member);
            }
        }
        if (reciprocal && this._isWindowUsable(window) && this._isWindowUsable(partner))
            this._signals?.emit('window-untiled', window, partner);
    }

    static _disconnectObjectSignal(object, id) {
        if (!object || !id)
            return;
        try {
            if (GObject.signal_handler_is_connected(object, id))
                object.disconnect(id);
        } catch (_error) {
            // Shell objects may already be disposed during compositor exit.
        }
    }

    static destroy() {
        this._destroyed = true;
        this._generation++;
        this._stopResize();
        for (const window of [...this._signalsConnectedMap.keys()])
            this._detachPair(window);

        if (this._grabbedWindowsAboutToUntileMap) {
            this._grabbedWindowsAboutToUntileMap.clear();
            this._grabbedWindowsAboutToUntileMap = null;
        }

        if (this._grabOpBeginId) {
            this._disconnectObjectSignal(global.display, this._grabOpBeginId);
            this._grabOpBeginId = 0;
        }

        if (this._grabOpEndId) {
            this._disconnectObjectSignal(global.display, this._grabOpEndId);
            this._grabOpEndId = 0;
        }
        this._settings = null;
        this._defaultAppSystem = null;
        this._signals = null;
        this._log?.destroy();
        this._log = null;
    }


}

const WindowTilingSupportSignals = GObject.registerClass({
    Signals: {
        'window-tiled': {
            param_types: [Meta.Window.$gtype, Meta.Window.$gtype],
            flags: GObject.SignalFlags.RUN_LAST,
        },
        'window-untiled': {
            param_types: [Meta.Window.$gtype, Meta.Window.$gtype],
            flags: GObject.SignalFlags.RUN_LAST,
        },
    }
}, class WindowTilingSupportSignals extends GObject.Object{

    _init() {
        super._init();
    }


});
