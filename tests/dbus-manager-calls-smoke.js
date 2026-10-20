// Must run under dbus-run-session. Only synthetic counters; no Shell/capture.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import {ManagerCalls} from '../extension/sessionsifu@local/managerCalls.js';

if (!GLib.getenv('SESSIONSIFU_PRIVATE_BUS_TEST'))
    throw new Error('Run only in the isolated regression bus');
const loop = new GLib.MainLoop(null, false);
const address = GLib.getenv('DBUS_SESSION_BUS_ADDRESS');
if (!address?.startsWith('unix:path=/tmp/') && !address?.startsWith('unix:abstract=/tmp/'))
    throw new Error('Refusing to run against a non-temporary session bus');
const connect = () => Gio.DBusConnection.new_for_address_sync(address,
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.MESSAGE_BUS_CONNECTION, null, null);
const server = connect(), manager = connect(), unrelated = connect();
const gate = new ManagerCalls();
let captures = 0, failure = null;
const xml = '<node><interface name="org.example.SessionSifuTest"><method name="Capture"><arg type="s" direction="out"/></method><method name="List"><arg type="s" direction="out"/></method></interface></node>';
const object = Gio.DBusExportedObject.wrapJSObject(xml, {
    CaptureAsync(_args, invocation) { gate.invoke(invocation, 'capture', () => { captures++; return 'synthetic'; }); },
    ListAsync(_args, invocation) { gate.invoke(invocation, 'list', () => 'existing history; recording disabled'); },
});
object.export(server, '/org/example/SessionSifuTest');
function call(connection, method) {
    return new Promise((resolve, reject) => connection.call(server.get_unique_name(), '/org/example/SessionSifuTest',
        'org.example.SessionSifuTest', method, null, new GLib.VariantType('(s)'),
        Gio.DBusCallFlags.NO_AUTO_START, 2000, null, (bus, result) => {
            try { resolve(bus.call_finish(result).deepUnpack()[0]); } catch (error) { reject(error); }
        }));
}
async function denied(connection, method) {
    let rejected = false;
    try { await call(connection, method); } catch (error) { rejected = String(error).includes('AccessDenied'); }
    if (!rejected) throw new Error('Expected caller rejection');
}
const owner = Gio.bus_own_name_on_connection(manager, 'org.gnome.SessionSifu', Gio.BusNameOwnerFlags.NONE,
    () => {
        (async () => {
            await denied(unrelated, 'Capture');
            if (captures !== 0) throw new Error('Unrelated client reached capture');
            if (await call(manager, 'Capture') !== 'synthetic' || captures !== 1) throw new Error('Manager capture rejected');
            await denied(manager, 'Capture');
            if (!String(await call(manager, 'List')).includes('recording disabled')) throw new Error('Disabled recording must not hide old history');
            gate.close();
            await denied(manager, 'List');
            if (captures !== 1) throw new Error('Capture dispatched after teardown');
            print('Real private-bus sender authorization, rate limiting, history browsing and teardown passed');
        })().catch(error => { failure = error; }).finally(() => loop.quit());
    }, () => { failure = new Error('Could not own isolated test manager name'); loop.quit(); });
const timeout = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 10, () => {
    failure = new Error('Private-bus test timed out'); loop.quit(); return GLib.SOURCE_REMOVE;
});
loop.run();
GLib.Source.remove(timeout);
gate.close(); object.unexport(); Gio.bus_unown_name(owner);
for (const connection of [unrelated, manager, server]) connection.close_sync(null);
if (failure) throw failure;
