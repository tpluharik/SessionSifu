import GObject from 'gi://GObject';


export const Signal = class {

    constructor() {

    }

    /**
     * Disconnect signal from an object without the below error / warning in `journalctl`:
     *
     * ../gobject/gsignal.c:2732: instance '0x55629xxxxxx' has no handler with id '11000'
     */
    disconnectSafely(obj, signalId) {
        if (!obj || !signalId)
            return false;

        try {
            // The object may already have been disposed by Mutter while an
            // extension disable or Shell shutdown is in progress.
            const matchedId = GObject.signal_handler_find(
                obj,
                GObject.SignalMatchType.ID,
                signalId,
                null, null, null, null);
            if (matchedId) {
                obj.disconnect(signalId);
                return true;
            }
        } catch (_error) {
            // Teardown must never escape into GNOME Shell's main loop.
        }
        return false;
    }

}
