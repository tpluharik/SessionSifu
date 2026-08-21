'use strict';

/**
 * Get the stable Wayland window id.
 *
 * @returns stable window id
 */
export const getStableWindowId = function(metaWindow) {
    return metaWindow.get_id();
}

export const isSurfaceActor = function(clutterActor) {
    const className = clutterActor.constructor.$gtype.name;
    // GNOME Shell 50 uses MetaSurfaceActorWayland.
    return className.startsWith('MetaSurfaceActor');
}
