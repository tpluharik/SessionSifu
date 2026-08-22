'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

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

const MEDIA_KEYS_SCHEMA = 'org.gnome.settings-daemon.plugins.media-keys';
const CUSTOM_KEYBINDING_SCHEMA =
    'org.gnome.settings-daemon.plugins.media-keys.custom-keybinding';
const RECALL_SHORTCUT_PATH =
    '/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/sessionsifu-recall/';

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
        const accelerator = this._settings.get_strv('recall-search-shortcut')
            .find(value => value && value !== 'disabled');
        if (!this._settings.get_boolean('recall-search-shortcut-enabled') || !accelerator)
            return;
        try {
            const mediaKeys = Gio.Settings.new(MEDIA_KEYS_SCHEMA);
            const paths = mediaKeys.get_strv('custom-keybindings');
            if (!paths.includes(RECALL_SHORTCUT_PATH))
                mediaKeys.set_strv('custom-keybindings', [...paths, RECALL_SHORTCUT_PATH]);

            const shortcut = Gio.Settings.new_with_path(
                CUSTOM_KEYBINDING_SCHEMA, RECALL_SHORTCUT_PATH);
            shortcut.set_string('name', 'SessionSifu Recall Search');
            shortcut.set_string(
                'command', `${GLib.shell_quote(FileUtils.getManagerExecutable())} --recall-search`);
            shortcut.set_string('binding', accelerator);
            this._recallShortcutRegistered = true;
            Log.Log.getDefault().info(
                `Registered GNOME Recall shortcut ${accelerator} at ${RECALL_SHORTCUT_PATH}`);
        } catch (error) {
            Log.Log.getDefault().error(error, 'Could not register Privacy Recall shortcut');
        }
    }

    _removeRecallShortcut() {
        try {
            const mediaKeys = Gio.Settings.new(MEDIA_KEYS_SCHEMA);
            const paths = mediaKeys.get_strv('custom-keybindings');
            if (paths.includes(RECALL_SHORTCUT_PATH))
                mediaKeys.set_strv(
                    'custom-keybindings', paths.filter(path => path !== RECALL_SHORTCUT_PATH));

            const shortcut = Gio.Settings.new_with_path(
                CUSTOM_KEYBINDING_SCHEMA, RECALL_SHORTCUT_PATH);
            shortcut.set_string('binding', '');
            shortcut.set_string('command', '');
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
