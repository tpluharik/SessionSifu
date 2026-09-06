'use strict';

// One queue for ALL SessionSifu clients of the compositor, not one per UI
// object. Never release an in-flight native screenshot on a JS timeout: its
// callback still owns the render operation and output stream.
export class CompositorOperations {
    constructor() {
        this._tail = Promise.resolve();
        this._pending = new Set();
        this._unhealthy = false;
        this._schedule = null;
    }

    configureWatchdog(schedule, cancel, milliseconds = 120000) {
        this._schedule = schedule;
        this._cancel = cancel;
        this._deadline = milliseconds;
    }

    run(operation, mayRun = () => true) {
        if (this._unhealthy)
            return Promise.reject(new Error('Compositor operation is still pending; restore/capture paused safely.'));
        const request = {cancelled: false};
        const result = new Promise((resolve, reject) => {
            request.resolve = resolve;
            request.reject = reject;
        });
        this._pending.add(request);
        const native = this._tail.then(async () => {
            if (request.cancelled || !mayRun())
                return false;
            let timer = null;
            if (this._schedule) {
                timer = this._schedule(() => {
                    timer = null;
                    this._unhealthy = true;
                    for (const pending of this._pending) {
                        pending.cancelled = true;
                        pending.reject(new Error('Compositor operation timed out; queued work cancelled. Native operation remains isolated until its callback returns.'));
                    }
                }, this._deadline);
            }
            try {
                return await operation();
            } finally {
                if (timer !== null)
                    this._cancel(timer);
                this._unhealthy = false;
            }
        });
        // Only native completion releases ownership. A deadline must NEVER
        // permit a second screenshot/layout operation to overlap a hung one.
        this._tail = native.then(() => undefined, () => undefined);
        native.then(request.resolve, request.reject).finally(() => this._pending.delete(request));
        return result;
    }
}

export const compositorOperations = new CompositorOperations();
