#!/usr/bin/gjs -m

import {
    recallExclusions,
    screenshotBlockingExclusions,
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

print('Recall privacy checks passed');
