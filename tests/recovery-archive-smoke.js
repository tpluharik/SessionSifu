// Native GIO file-contract test, confined to a private temporary directory.
// Only the real archive method is loaded: no Shell, bus, app or window access.
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

const directory = GLib.dir_make_tmp('sessionsifu-recovery-test-XXXXXX');
const FileUtils = {current_session_path: directory};
const sourceFile = Gio.File.new_for_path(GLib.build_filenamev([
    ARGV[0], 'extension/sessionsifu@local/restoreSession.js',
]));
const [, sourceBytes] = sourceFile.load_contents(null);
const source = new TextDecoder().decode(sourceBytes);
const start = source.indexOf('    async _preserveRecoveryRecord(session) {');
const end = source.indexOf('    _persistRecordLedger()', start);
if (start < 0 || end < start) throw new Error('Archive method boundary not found');
const Archive = eval(`(class {${source.slice(start, end)}})`);
const instance = new Archive();
instance._loadSessionContents = async file => file.load_contents(null)[1];
const bytes = new TextEncoder().encode(JSON.stringify({window_title: 'Synthetic document', open_files: []}));
const key = GLib.compute_checksum_for_string(GLib.ChecksumType.SHA256, new TextDecoder().decode(bytes), -1);
const session = {_recovery_contents: bytes, _recovery_key: key};
const archive = Gio.File.new_for_path(`${directory}/manualRecovery/${key}.json`);
const loop = new GLib.MainLoop(null, false);
let failure;

async function check() {
    await instance._preserveRecoveryRecord(session);
    const [, saved] = archive.load_contents(null);
    if (saved.length !== bytes.length || !saved.every((byte, index) => byte === bytes[index]))
        throw new Error('Archived bytes changed');
    const mode = archive.query_info('unix::mode', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null)
        .get_attribute_uint32('unix::mode') & 0o777;
    if (mode !== 0o600) throw new Error(`Archive mode is ${mode}, expected owner-only`);
    const folderMode = archive.get_parent().query_info('unix::mode', Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null)
        .get_attribute_uint32('unix::mode') & 0o777;
    if (folderMode !== 0o700) throw new Error('Archive directory is not private');
    await instance._preserveRecoveryRecord(session); // Idempotent identical bytes.
    let rejected = false;
    try { await instance._preserveRecoveryRecord({...session, _recovery_contents: new Uint8Array([1, 2])}); }
    catch (_error) { rejected = true; }
    if (!rejected) throw new Error('Existing historical bytes could be overwritten');
    await instance._preserveRecoveryRecord({_recovery_contents: bytes, _recovery_key: '../escape'});
    print('Native archive: exact bytes, private modes, idempotence and no-overwrite checks passed');
}

check().catch(error => { failure = error; }).finally(() => loop.quit());
loop.run();
// Recoverable application data is never involved; remove only this fixture.
if (archive.query_exists(null)) archive.delete(null);
const folder = Gio.File.new_for_path(`${directory}/manualRecovery`);
if (folder.query_exists(null)) folder.delete(null);
Gio.File.new_for_path(directory).delete(null);
if (failure) throw failure;
