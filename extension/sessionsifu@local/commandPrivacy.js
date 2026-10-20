'use strict';

// Linear, bounded work on metadata already collected for a save. Never parse a
// shell string or change argv used to resolve document ownership in memory.
const SECRET_FLAG = /^--?(?:password|passwd|passphrase|token|access[-_]token|refresh[-_]token|api[-_]?key|secret|client[-_]secret|authorization|auth)$/i;
const SECRET_QUERY = /([?&#](?:password|passwd|token|access_token|refresh_token|api_key|apikey|secret|client_secret|signature|sig)=)[^&#\s]*/gi;

export function sanitizeCommand(argv) {
    if (!Array.isArray(argv)) return {argv: null, requiresInput: false};
    let requiresInput = false;
    let nextSecret = false;
    const mysql = /^(?:mysql|mariadb)(?:\.exe)?$/i.test(String(argv[0] ?? '').split('/').pop());
    const clean = argv.slice(0, 4096).map((raw, index) => {
        const arg = String(raw);
        if (arg.length > 65536) {
            requiresInput = true;
            return '[REDACTED:OVERSIZED]';
        }
        if (nextSecret) {
            nextSecret = false;
            requiresInput = true;
            return '[REDACTED]';
        }
        const equal = arg.indexOf('=');
        if (SECRET_FLAG.test(equal < 0 ? arg : arg.slice(0, equal))) {
            requiresInput = true;
            if (equal >= 0) return `${arg.slice(0, equal)}=[REDACTED]`;
            nextSecret = true;
            return arg;
        }
        if (mysql && index > 0 && /^-p.+/.test(arg)) {
            requiresInput = true;
            return '-p[REDACTED]';
        }
        let result = arg.replace(SECRET_QUERY, (_match, key) => {
            requiresInput = true;
            return `${key}[REDACTED]`;
        });
        result = result.replace(/([a-z][a-z0-9+.-]{0,31}:\/\/)([^/\s?#]*)/gi, (match, scheme, authority) => {
            const at = authority.lastIndexOf('@');
            if (at < 0) return match;
            requiresInput = true;
            return `${scheme}[REDACTED]@${authority.slice(at + 1)}`;
        });
        return result;
    });
    return {argv: clean, requiresInput: requiresInput || argv.length > 4096};
}
