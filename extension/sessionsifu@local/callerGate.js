'use strict';

// Connection identity is supplied by D-Bus, never a caller-supplied PID. This
// is defence-in-depth against accidental/unrelated callers, not isolation from
// malware already able to own this user's manager name or change its code.
export class CallerGate {
    constructor(resolveOwner, now = () => Date.now()) {
        this._resolveOwner = resolveOwner;
        this._now = now;
        this._last = new Map();
        this._pending = 0;
        this._closed = false;
    }

    async allow(sender, operation, interval = 1000) {
        if (this._closed || typeof sender !== 'string' || !sender.startsWith(':') || this._pending >= 4)
            return false;
        const key = `${sender}:${operation}`;
        const now = this._now();
        if (this._last.has(key) && now - this._last.get(key) < interval) return false;
        if (this._last.size >= 64 && !this._last.has(key)) this._last.delete(this._last.keys().next().value);
        this._last.set(key, now);
        this._pending++;
        try {
            const owner = await this._resolveOwner();
            return !this._closed && owner === sender;
        } catch (_) {
            return false;
        } finally {
            this._pending--;
        }
    }

    close() {
        this._closed = true;
        this._last.clear();
    }
}
