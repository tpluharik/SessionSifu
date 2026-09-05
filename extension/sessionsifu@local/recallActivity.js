'use strict';

import GObject from 'gi://GObject';

const RecallActivity = GObject.registerClass({
    Signals: {
        'changed': {param_types: [GObject.TYPE_BOOLEAN]},
    },
}, class RecallActivity extends GObject.Object {
    _init() {
        super._init();
        this._operations = 0;
    }

    get saving() {
        return this._operations > 0;
    }

    begin() {
        this._operations++;
        if (this._operations === 1)
            this.emit('changed', true);
    }

    end() {
        if (this._operations === 0)
            return;
        this._operations--;
        if (this._operations === 0)
            this.emit('changed', false);
    }
});

export const recallActivity = new RecallActivity();
// Separate lifetime: Recall capture finishing must not clear restore status.
export const restoreActivity = new RecallActivity();
