import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as Scripting from 'resource:///org/gnome/shell/ui/scripting.js';

Gio._promisify(Gio.DBusConnection.prototype, 'call', 'call_finish');

export const METRICS = {};

export async function run() {
    await Scripting.sleep(750);

    if (!Main.panel.statusArea['SessionSifu'])
        throw new Error('SessionSifu top-bar indicator was not created');

    const reply = await Gio.DBus.session.call(
        'org.gnome.Shell.Extensions.SessionSifu',
        '/org/gnome/Shell/Extensions/SessionSifu',
        'org.gnome.Shell.Extensions.SessionSifu.Control',
        'Ping',
        null,
        new GLib.VariantType('(s)'),
        Gio.DBusCallFlags.NONE,
        3000,
        null
    );

    const [message] = reply.deepUnpack();
    if (message !== 'SessionSifu 3.5.21 is ready')
        throw new Error(`Unexpected D-Bus response: ${message}`);
}

export function finish() {}
