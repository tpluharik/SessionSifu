import {
    MAX_WORKSPACE_INDEX,
    isValidWorkspaceIndex,
    isWindowCaptureSafe,
    isWindowRegionUnobscured,
    isWindowUsable,
} from '../extension/sessionsifu@local/windowSafety.js';


function fakeWindow({
    monitor = 0,
    actor = {},
    workspace = {},
    closing = false,
    minimized = false,
    showing = true,
    rect = {x: 0, y: 0, width: 800, height: 600},
} = {}) {
    return {
        _aboutToClose: closing,
        minimized,
        get_monitor: () => monitor,
        get_compositor_private: () => actor,
        get_workspace: () => workspace,
        get_frame_rect: () => rect,
        showing_on_its_workspace: () => showing,
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

const visibleActor = {mapped: true, visible: true, is_destroyed: () => false};
if (!isWindowCaptureSafe(fakeWindow({actor: visibleActor}), visibleActor, 1))
    throw new Error('A visible managed window was rejected for safe capture');
if (isWindowCaptureSafe(fakeWindow({actor: {...visibleActor, mapped: false}}),
    {...visibleActor, mapped: false}, 1))
    throw new Error('An unmapped window was accepted for capture');
if (isWindowCaptureSafe(fakeWindow({actor: visibleActor, minimized: true}), visibleActor, 1))
    throw new Error('A minimized window was accepted for capture');
if (isWindowCaptureSafe(fakeWindow({actor: visibleActor, showing: false}), visibleActor, 1))
    throw new Error('An off-workspace window was accepted for capture');
if (isWindowCaptureSafe(fakeWindow({actor: visibleActor, rect: {x: 0, y: 0, width: 0, height: 1}}),
    visibleActor, 1))
    throw new Error('A zero-area window was accepted for capture');

if (!isValidWorkspaceIndex(0) || !isValidWorkspaceIndex(MAX_WORKSPACE_INDEX))
    throw new Error('A safe workspace index was rejected');
if (isValidWorkspaceIndex(-1) || isValidWorkspaceIndex(MAX_WORKSPACE_INDEX + 1))
    throw new Error('An unsafe workspace index was accepted');

const back = fakeWindow({actor: visibleActor});
const front = fakeWindow({actor: visibleActor, rect: {x: 20, y: 20, width: 400, height: 300}});
const separate = fakeWindow({actor: visibleActor, rect: {x: 900, y: 0, width: 400, height: 300}});
if (isWindowRegionUnobscured(back, [back, front]))
    throw new Error('An overlapped window was accepted for screen-area capture');
if (!isWindowRegionUnobscured(front, [back, front]))
    throw new Error('The unobscured top window was rejected');
if (!isWindowRegionUnobscured(back, [back, separate]))
    throw new Error('A non-overlapping window was rejected');
if (isWindowRegionUnobscured(back, [front]))
    throw new Error('A window missing from the current stack was accepted');
