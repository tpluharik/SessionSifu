'use strict';

import Gio from 'gi://Gio';
import Meta from 'gi://Meta';
import Shell from 'gi://Shell';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';

import * as OpenWindowsTracker from './openWindowsTracker.js';

import * as Indicator from './indicator.js';
import * as Autostart from './ui/autostart.js';
import * as Autoclose from './ui/autoclose.js';
import {WindowTilingSupport} from './windowTilingSupport.js';
import * as WindowPicker from './utils/WindowPicker.js';

import {Extension, gettext as _} from 'resource:///org/gnome/shell/extensions/extension.js';

import * as Log from './utils/log.js';
import * as FileUtils from './utils/fileUtils.js';
import {prefsUtilsInit, prefsUtilsDestroy} from './utils/prefsUtils.js';


let _indicator;
let _autostartServiceProvider;
let _openWindowsTracker;
let _autoclose;
let _windowPickerServiceProvider;

export default class SessionSifuExtension extends Extension {

    constructor(metadata) {
        super(metadata);
    }

    enable() {
        // settings is needed by the initialization of some utils
        this._settings = this.getSettings('org.gnome.shell.extensions.sessionsifu');
        this._recallShortcutRegistered = false;

        this.initUtils();

        this._showIndicatorChangedId = this._settings.connect(
            'changed::show-indicator', () => this.showOrHideIndicator());
        this._recallIndicatorChangedId = this._settings.connect(
            'changed::recall-enabled', () => {
                this.showOrHideIndicator();
                this._syncRecallShortcut();
            });
        this._recallShortcutChangedId = this._settings.connect(
            'changed::recall-search-shortcut-enabled', () => this._syncRecallShortcut());
        this._recallAcceleratorChangedId = this._settings.connect(
            'changed::recall-search-shortcut', () => this._syncRecallShortcut());
        this.showOrHideIndicator();
        this._syncRecallShortcut();

        _autostartServiceProvider = new Autostart.AutostartServiceProvider();

        WindowTilingSupport.initialize();

        _openWindowsTracker = new OpenWindowsTracker.OpenWindowsTracker();
        _autoclose = new Autoclose.Autoclose();

        _windowPickerServiceProvider = new WindowPicker.WindowPickerServiceProvider();
        _windowPickerServiceProvider.enable();
    }

    initUtils() {
        prefsUtilsInit(this, this._settings);
        FileUtils.init(this);
    }

    showOrHideIndicator() {
        if (this._settings.get_boolean('show-indicator') ||
            this._settings.get_boolean('recall-enabled')) {
            if (!_indicator) {
                _indicator = new Indicator.AwsIndicator();
                Main.panel.addToStatusArea('SessionSifu', _indicator);
            }
        } else {
            this.hideIndicator();
        }
    }

    hideIndicator() {
        if (_indicator) {
            _indicator.destroy();
            _indicator = null;
        }
    }

    _syncRecallShortcut() {
        this._removeRecallShortcut();
        if (!this._settings.get_boolean('recall-search-shortcut-enabled') ||
            this._settings.get_strv('recall-search-shortcut').every(value => !value))
            return;
        try {
            Main.wm.addKeybinding(
                'recall-search-shortcut',
                this._settings,
                Meta.KeyBindingFlags.NONE,
                Shell.ActionMode.NORMAL | Shell.ActionMode.OVERVIEW | Shell.ActionMode.POPUP,
                () => {
                    try {
                        Gio.Subprocess.new(
                            [FileUtils.getManagerExecutable(), '--recall-search'],
                            Gio.SubprocessFlags.NONE);
                    } catch (error) {
                        Log.Log.getDefault().error(error, 'Could not open Privacy Recall search');
                    }
                });
            this._recallShortcutRegistered = true;
        } catch (error) {
            Log.Log.getDefault().error(error, 'Could not register Privacy Recall shortcut');
        }
    }

    _removeRecallShortcut() {
        if (!this._recallShortcutRegistered)
            return;
        try {
            Main.wm.removeKeybinding('recall-search-shortcut');
        } catch (error) {
            Log.Log.getDefault().error(error, 'Could not remove Privacy Recall shortcut');
        }
        this._recallShortcutRegistered = false;
    }

    disable() {

        this._removeRecallShortcut();

        this.hideIndicator();

        if (_autostartServiceProvider) {
            _autostartServiceProvider.disable();
            _autostartServiceProvider = null;
        }

        if (_openWindowsTracker) {
            _openWindowsTracker.destroy();
            _openWindowsTracker = null;
        }

        WindowTilingSupport.destroy();

        if (_autoclose) {
            _autoclose.destroy();
            _autoclose = null;
        }

        Log.Log.destroyDefault();

        if (_windowPickerServiceProvider) {
            _windowPickerServiceProvider.destroy();
            _windowPickerServiceProvider = null;
        }

        if (this._settings) {
            if (this._showIndicatorChangedId) {
                this._settings.disconnect(this._showIndicatorChangedId);
                this._showIndicatorChangedId = 0;
            }
            if (this._recallIndicatorChangedId) {
                this._settings.disconnect(this._recallIndicatorChangedId);
                this._recallIndicatorChangedId = 0;
            }
            if (this._recallShortcutChangedId) {
                this._settings.disconnect(this._recallShortcutChangedId);
                this._recallShortcutChangedId = 0;
            }
            if (this._recallAcceleratorChangedId) {
                this._settings.disconnect(this._recallAcceleratorChangedId);
                this._recallAcceleratorChangedId = 0;
            }
            this._settings = null;
        }

        prefsUtilsDestroy();

    }

}
