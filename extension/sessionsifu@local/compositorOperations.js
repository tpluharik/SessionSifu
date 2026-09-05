'use strict';

// One queue for ALL SessionSifu clients of the compositor, not one per UI
// object. Never release an in-flight native screenshot on a JS timeout: its
// callback still owns the render operation and output stream.
export class CompositorOperations {
    constructor() {
        this._tail = Promise.resolve();
    }

    run(operation, mayRun = () => true) {
        const result = this._tail.then(() => mayRun() ? operation() : false);
        this._tail = result.then(() => undefined, () => undefined);
        return result;
    }
}

export const compositorOperations = new CompositorOperations();
