#!/usr/bin/gjs -m

import GLib from 'gi://GLib';
import * as SubprocessUtils from '../extension/sessionsifu@local/utils/subprocessUtils.js';

const executable = GLib.find_program_in_path('python3');
if (!executable)
    throw new Error('python3 executable is unavailable');
const marker = GLib.build_filenamev([
    GLib.get_tmp_dir(), `sessionsifu-security-${GLib.get_real_time()}`]);

const hostileArguments = [
    executable,
    '-c',
    'import time; time.sleep(1)',
    `$(touch ${marker})`,
    '`id`',
    '; echo injected',
    '| sh',
    `> ${marker}`,
];
const [, pid, key] = SubprocessUtils.spawnDirectArgv(hostileArguments);
if (!Number.isSafeInteger(pid) || !key.includes('\0'))
    throw new Error('Validated argv launch did not return a process identity');

for (const rejected of [
    [executable, 'line\nbreak'],
    ['/definitely/missing/sessionsifu-executable'],
    [],
]) {
    let failedClosed = false;
    try {
        SubprocessUtils.spawnDirectArgv(rejected);
    } catch (_) {
        failedClosed = true;
    }
    if (!failedClosed)
        throw new Error(`Unsafe argument vector was accepted: ${JSON.stringify(rejected)}`);
}

if (GLib.file_test(marker, GLib.FileTest.EXISTS))
    throw new Error('Saved arguments were interpreted as shell syntax');

print('security smoke checks passed');
