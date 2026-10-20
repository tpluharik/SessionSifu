'use strict';

export function managedExtensionDisposition(receipt, systemPresent, systemVersion, localVersion) {
    if (receipt?.mode !== 'apt-backed') return 'allow';
    if (!systemPresent) return 'system-removed';
    const version = value => /^(\d+)\.(\d+)\.(\d+)$/.exec(value ?? '')?.slice(1).map(Number);
    const system = version(systemVersion);
    const local = version(localVersion);
    if (!system || !local) return 'allow';
    for (let i = 0; i < 3; i++) {
        if (system[i] > local[i]) return 'system-newer';
        if (system[i] < local[i]) return 'allow';
    }
    return 'allow';
}
