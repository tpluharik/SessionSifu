'use strict';


export const runtimeSafety = {
    shutdownInProgress: false,
};

// No recurring timer: layout callers check the quiet period before touching
// Mutter. A generation change invalidates work queued before a hotplug, even
// if it does not acquire compositor ownership until after the quiet period.
export const layoutSafety = {
    generation: 0,
    blockedUntil: 0,
    now: () => Date.now(),
};

export function configureLayoutSafety(now) {
    layoutSafety.now = now;
    layoutSafety.generation++;
    layoutSafety.blockedUntil = 0;
}

export function beginMonitorChange() {
    layoutSafety.generation++;
    layoutSafety.blockedUntil = layoutSafety.now() + 1000;
}

export function mayRestoreLayout(generation = layoutSafety.generation) {
    return mayRestoreApplications() && generation === layoutSafety.generation &&
        layoutSafety.now() >= layoutSafety.blockedUntil;
}

export function beginShutdown() {
    runtimeSafety.shutdownInProgress = true;
    layoutSafety.generation++;
}

export function cancelShutdown() {
    runtimeSafety.shutdownInProgress = false;
}

export function mayRestoreApplications() {
    return !runtimeSafety.shutdownInProgress;
}
