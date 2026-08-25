Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
Failed to create stream fd: Operation not permitted
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as OpenFiles from '../extension/sessionsifu@local/openFiles.js';


const home = GLib.get_home_dir();
const [thisFile] = GLib.filename_from_uri(import.meta.url);
if (!OpenFiles.isCandidatePath(`${home}/Documents/report.odt`))
    throw new Error('A normal document path was rejected');
if (OpenFiles.isCandidatePath(`${home}/.config/application/state.db`))
    throw new Error('Hidden application state was accepted as a document');
if (!OpenFiles.isCandidatePath(`${home}/.projects/report.odt`, true))
    throw new Error('An explicitly identified document in a hidden directory was rejected');
if (OpenFiles.isCandidatePath('/usr/lib/application/resource.dat'))
    throw new Error('A system resource was accepted as a document');
if (OpenFiles.isCandidatePath(`${home}/Documents/report.odt (deleted)`))
    throw new Error('A deleted file was accepted as restorable');
if (OpenFiles.OPEN_FILE_LIMIT !== 32)
    throw new Error('Unexpected open-file safety limit');
if (OpenFiles.OPEN_FD_SCAN_LIMIT !== 128)
    throw new Error('Unexpected descriptor scan safety limit');
if (OpenFiles.RECENT_FILE_SCAN_LIMIT !== 512)
    throw new Error('Unexpected recent-file safety limit');
const appInfo = (contentTypes, supportsFiles = false, supportsUris = true) => ({
    supports_files: () => supportsFiles,
    supports_uris: () => supportsUris,
    get_supported_types: () => contentTypes,
});
if (OpenFiles.appInfoSupportsDocumentFiles(appInfo(['x-scheme-handler/sgnl'])))
    throw new Error('A protocol-only launcher was accepted for document restoration');
if (!OpenFiles.appInfoSupportsDocumentFiles(appInfo(['text/plain'], true, false)))
    throw new Error('A document launcher was rejected');
if (!OpenFiles.appInfoSupportsDocumentFiles(appInfo([
    'x-scheme-handler/https',
    'application/pdf',
])))
    throw new Error('A launcher with a document MIME type was rejected');
if (OpenFiles.appInfoSupportsDocumentFiles(null))
    throw new Error('A missing launcher was accepted for document restoration');
const thisFileUri = Gio.File.new_for_path(thisFile).get_uri();
if (OpenFiles.pathFromArgument(thisFileUri) !== thisFile)
    throw new Error('A file URI from the application command line was not decoded');
// The source tree is normally in the developer's home and can therefore exercise
// the complete safety filter. Launchpad intentionally builds outside /home/buildd;
// the filter must reject that path, while URI decoding remains testable there.
if (OpenFiles.isCandidatePath(thisFile, true)) {
    const commandFiles = OpenFiles.commandLineFiles([
        '/usr/bin/document-editor',
        thisFileUri,
    ]);
    if (commandFiles.length !== 1 || commandFiles[0] !== thisFile)
        throw new Error('A file URI from the application command line was not captured');
}
const recent = OpenFiles.recentFileForWindow([
    {path: '/new/report.odt', basename: 'report.odt', modified: 2},
    {path: '/old/report.odt', basename: 'report.odt', modified: 1},
], 'report.odt — Document Editor');
if (recent !== '/new/report.odt')
    throw new Error('The most recent exact window-title match was not selected');

const [, statBytes] = GLib.file_get_contents('/proc/self/stat');
const selfPid = Number(new TextDecoder().decode(statBytes).split(' ', 1)[0]);
const startedUs = GLib.get_monotonic_time();
const resolver = new OpenFiles.OpenFileResolver();
const resolved = resolver.resolve(
    selfPid,
    [],
    'SessionSifu performance sentinel with no expected recent-document match');
const elapsedMs = (GLib.get_monotonic_time() - startedUs) / 1000;
if (resolved.length > OpenFiles.OPEN_FILE_LIMIT)
    throw new Error('Open-file discovery exceeded its result bound');
if (elapsedMs > 2000)
    throw new Error(`Open-file discovery exceeded its latency budget: ${elapsedMs} ms`);
