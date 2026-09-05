#!/usr/bin/gjs -m

import {recallActivity, restoreActivity} from '../extension/sessionsifu@local/recallActivity.js';

const states = [];
const signalId = recallActivity.connect('changed', (_activity, saving) => states.push(saving));
recallActivity.begin();
recallActivity.begin();
if (!recallActivity.saving)
    throw new Error('Recall activity did not enter saving state');
recallActivity.end();
if (!recallActivity.saving)
    throw new Error('Nested Recall activity ended too early');
recallActivity.end();
recallActivity.end();
if (recallActivity.saving || JSON.stringify(states) !== JSON.stringify([true, false]))
    throw new Error(`Unexpected Recall activity transitions: ${JSON.stringify(states)}`);
recallActivity.disconnect(signalId);

restoreActivity.begin();
recallActivity.begin();
recallActivity.end();
if (!restoreActivity.saving || recallActivity.saving)
    throw new Error('Recall completion incorrectly cleared restore activity');
restoreActivity.end();
if (restoreActivity.saving)
    throw new Error('Restore activity remained active after completion');

print('Recall activity checks passed');
