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

export function isWindowCaptureSafe(metaWindow, actor = null, monitorCount = null) {
    try {
        const windowActor = actor ?? metaWindow?.get_compositor_private?.();
        if (!windowActor || !isWindowUsable(metaWindow, monitorCount) ||
            windowActor.is_destroyed?.() || windowActor.mapped === false ||
            windowActor.visible === false || metaWindow.minimized ||
            metaWindow.showing_on_its_workspace?.() === false)
            return false;

        const rect = metaWindow.get_frame_rect?.();
        return Boolean(rect) &&
            [rect.x, rect.y, rect.width, rect.height].every(Number.isFinite) &&
            rect.width > 0 && rect.height > 0 &&
            rect.width <= 32768 && rect.height <= 32768 &&
            rect.width * rect.height <= 64 * 1024 * 1024;
    } catch (_error) {
        return false;
    }
}

// Screen-area capture must never label another app's pixels as this window.
// Mutter returns this stack bottom-to-top; any overlapping window above the
// candidate makes the full rectangular preview unsafe to capture.
export function isWindowRegionUnobscured(metaWindow, stackingOrder) {
    try {
        const index = stackingOrder.indexOf(metaWindow);
        if (index < 0)
            return false;
        const rect = metaWindow.get_frame_rect();
        for (const other of stackingOrder.slice(index + 1)) {
            const actor = other.get_compositor_private?.();
            if (!actor || actor.visible === false || actor.mapped === false || other.minimized)
                continue;
            const above = other.get_frame_rect();
            if (rect.x < above.x + above.width && rect.x + rect.width > above.x &&
                rect.y < above.y + above.height && rect.y + rect.height > above.y)
                return false;
        }
        return true;
    } catch (_error) {
        return false;
    }
}
