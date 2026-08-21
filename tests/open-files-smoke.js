import GLib from 'gi://GLib';

import * as OpenFiles from '../extension/sessionsifu@local/openFiles.js';


const home = GLib.get_home_dir();
if (!OpenFiles.isCandidatePath(`${home}/Documents/report.odt`))
    throw new Error('A normal document path was rejected');
if (OpenFiles.isCandidatePath(`${home}/.config/application/state.db`))
    throw new Error('Hidden application state was accepted as a document');
if (OpenFiles.isCandidatePath('/usr/lib/application/resource.dat'))
    throw new Error('A system resource was accepted as a document');
if (OpenFiles.isCandidatePath(`${home}/Documents/report.odt (deleted)`))
    throw new Error('A deleted file was accepted as restorable');
if (OpenFiles.OPEN_FILE_LIMIT !== 32)
    throw new Error('Unexpected open-file safety limit');
if (OpenFiles.OPEN_FD_SCAN_LIMIT !== 512)
    throw new Error('Unexpected descriptor scan safety limit');
