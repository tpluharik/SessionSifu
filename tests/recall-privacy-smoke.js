#!/usr/bin/gjs -m

import {
    recallExclusions,
    screenshotBlockingExclusions,
    screenshotCaptureMode,
} from '../extension/sessionsifu@local/recallPrivacy.js';

const metadata = recallExclusions([' SessionSifu ', 'Signal', 'signal', 'Whatsie']);
if (JSON.stringify(metadata) !== JSON.stringify(['sessionsifu', 'signal', 'whatsie']))
    throw new Error(`Unexpected normalized exclusions: ${JSON.stringify(metadata)}`);

const blockers = screenshotBlockingExclusions([
    'SessionSifu', 'org.gnome.SessionSifu', 'org.gnome.SessionSifu.desktop',
    'Signal', 'Whatsie',
]);
if (JSON.stringify(blockers) !== JSON.stringify(['signal', 'whatsie']))
    throw new Error(`Unexpected screenshot blockers: ${JSON.stringify(blockers)}`);

if (screenshotBlockingExclusions(['SessionSifu']).length !== 0)
    throw new Error('The built-in self-exclusion still suppresses screenshots');

if (screenshotCaptureMode(false) !== 'all')
    throw new Error('Normal Recall captures must include window and display previews');
if (screenshotCaptureMode(true) !== 'windows-only')
    throw new Error('An excluded app must suppress only the shared display preview');

print('Recall privacy checks passed');
