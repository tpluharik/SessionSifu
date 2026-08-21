import {
    MAX_WORKSPACE_INDEX,
    isValidWorkspaceIndex,
    isWindowUsable,
} from '../extension/sessionsifu@local/windowSafety.js';


function fakeWindow({monitor = 0, actor = {}, workspace = {}, closing = false} = {}) {
    return {
        _aboutToClose: closing,
        get_monitor: () => monitor,
        get_compositor_private: () => actor,
        get_workspace: () => workspace,
    };
}

if (!isWindowUsable(fakeWindow(), 1))
    throw new Error('A managed window on an existing monitor was rejected');
if (isWindowUsable(fakeWindow({monitor: -1}), 1))
    throw new Error('An unmanaged window with monitor -1 was accepted');
if (isWindowUsable(fakeWindow({monitor: 1}), 1))
    throw new Error('A window on a removed monitor was accepted');
if (isWindowUsable(fakeWindow({actor: null}), 1))
    throw new Error('A window without a compositor actor was accepted');
if (isWindowUsable(fakeWindow({workspace: null}), 1))
    throw new Error('A window without a workspace was accepted');
if (isWindowUsable(fakeWindow({closing: true}), 1))
    throw new Error('A closing window was accepted');
if (isWindowUsable({get_monitor: () => { throw new Error('disposed'); }}, 1))
    throw new Error('A disposed window was accepted');

if (!isValidWorkspaceIndex(0) || !isValidWorkspaceIndex(MAX_WORKSPACE_INDEX))
    throw new Error('A safe workspace index was rejected');
if (isValidWorkspaceIndex(-1) || isValidWorkspaceIndex(MAX_WORKSPACE_INDEX + 1))
    throw new Error('An unsafe workspace index was accepted');
