'use strict';

const SELF_IDENTITIES = new Set([
    'sessionsifu',
    'org.gnome.sessionsifu',
    'org.gnome.sessionsifu.desktop',
]);

export function recallExclusions(values = []) {
    return [...new Set(['sessionsifu', ...values]
        .map(value => String(value).trim().toLowerCase().slice(0, 256))
        .filter(value => value))];
}

export function screenshotBlockingExclusions(values = []) {
    // SessionSifu is always omitted from its own metadata to avoid recursive
    // search noise. That built-in self-exclusion must not suppress every
    // screenshot while the manager or Recall browser is open. Explicit
    // privacy exclusions still suppress shared display previews.
    return recallExclusions(values).filter(value => !SELF_IDENTITIES.has(value));
}

export function screenshotCaptureMode(excludedApplicationVisible = false) {
    // An excluded window must suppress only the shared desktop image. Saved
    // metadata already omits excluded applications, so the window renderer can
    // safely retain previews belonging to the remaining allowed applications.
    return excludedApplicationVisible ? 'windows-only' : 'all';
}
