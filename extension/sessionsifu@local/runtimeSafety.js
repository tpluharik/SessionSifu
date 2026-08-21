'use strict';


export const runtimeSafety = {
    shutdownInProgress: false,
};

export function beginShutdown() {
    runtimeSafety.shutdownInProgress = true;
}

export function cancelShutdown() {
    runtimeSafety.shutdownInProgress = false;
}

export function mayRestoreApplications() {
    return !runtimeSafety.shutdownInProgress;
}
