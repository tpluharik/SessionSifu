'use strict';


export const MAX_WORKSPACE_INDEX = 35;

export function isValidWorkspaceIndex(index) {
    return Number.isInteger(index) && index >= 0 && index <= MAX_WORKSPACE_INDEX;
}

export function isWindowUsable(metaWindow, monitorCount = null) {
    try {
        if (!metaWindow || metaWindow._aboutToClose)
            return false;
        const monitor = metaWindow.get_monitor();
        const availableMonitors = monitorCount ?? global.display.get_n_monitors();
        return Boolean(metaWindow.get_compositor_private()) &&
            Boolean(metaWindow.get_workspace()) &&
            Number.isInteger(monitor) && monitor >= 0 &&
            Number.isInteger(availableMonitors) && monitor < availableMonitors;
    } catch (_error) {
        return false;
    }
}
