'use strict';

import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {CallerGate} from './callerGate.js';

export class ManagerCalls {
    constructor() { this._gates = new Map(); this._closed = false; }

    invoke(invocation, operation, work) {
        if (this._closed) {
            invocation.return_dbus_error('org.gnome.SessionSifu.AccessDenied', 'Integration is stopping');
            return;
        }
        const connection = invocation.get_connection();
        let gate = this._gates.get(operation);
        if (!gate) {
            gate = new CallerGate(() => new Promise((resolve, reject) => {
                connection.call('org.freedesktop.DBus', '/org/freedesktop/DBus',
                    'org.freedesktop.DBus', 'GetNameOwner',
                    new GLib.Variant('(s)', ['org.gnome.SessionSifu']),
                    new GLib.VariantType('(s)'), Gio.DBusCallFlags.NO_AUTO_START,
                    500, null, (bus, result) => {
                        try { resolve(bus.call_finish(result).deepUnpack()[0]); }
                        catch (error) { reject(error); }
                    });
            }));
            this._gates.set(operation, gate);
        }
        gate.allow(invocation.get_sender(), operation).then(allowed => {
            if (!allowed || this._closed) {
                invocation.return_dbus_error('org.gnome.SessionSifu.AccessDenied',
                    'Request requires the active SessionSifu manager and is rate limited');
                return;
            }
            try { invocation.return_value(new GLib.Variant('(s)', [work()])); }
            catch (_) { invocation.return_dbus_error('org.gnome.SessionSifu.Failed', 'Request failed'); }
        }).catch(() => {});
    }

    close() {
        this._closed = true;
        for (const gate of this._gates.values()) gate.close();
        this._gates.clear();
    }
}
