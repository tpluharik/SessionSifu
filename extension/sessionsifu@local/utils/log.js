'use strict';

import {PrefsUtils} from './prefsUtils.js';


export const Log = class {

    constructor() {
    }

    isDebug() {
        // Utility modules are also exercised before the extension preferences
        // singleton exists (for example by package smoke tests). Logging must
        // remain optional in that state instead of aborting the caller.
        return PrefsUtils?.isDebug?.() ?? false;
    }

    isVerboseLogging() {
        return PrefsUtils?.isVerboseLogging?.() ?? false;
    }

    debug(logContent) {
        if (this.isDebug()) {
            log(`[DEBUG  ][SessionSifu] ${logContent}`);
        }
    }

    error(e, logContent) {
        if (!(e instanceof Error)) {
            e = new Error(e);
        }
        logError(e, `[ERROR  ][SessionSifu] ${logContent}`);
    }

    info(logContent) {
        if (this.isVerboseLogging()) {
            log(`[INFO   ][SessionSifu] ${logContent}`);
        }
    }

    warn(logContent) {
        log(`[WARNING][SessionSifu] ${logContent}`);
    }

    destroy() {

    }

    // Return a singleton instance
    static getDefault() {
        if (!Log._default) {
            Log._default = new Log();
        }
        return Log._default;
    }

    static destroyDefault() {
        if (Log._default) {
            Log._default.destroy();
            delete Log._default;
        }
    }

}
