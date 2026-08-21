import Gio from 'gi://Gio';
import GLib from 'gi://GLib';

import * as Scripting from 'resource:///org/gnome/shell/ui/scripting.js';

export const METRICS = {};

export async function run() {
    await Scripting.sleep(750);

    const executable = GLib.getenv('SESSION_SIFU_GUI');
    if (!executable)
        throw new Error('SESSION_SIFU_GUI is not set');

    const launcher = new Gio.SubprocessLauncher({flags: Gio.SubprocessFlags.NONE});
    launcher.setenv('GDK_BACKEND', 'wayland', true);
    launcher.setenv('WAYLAND_DISPLAY', 'gnome-shell-test-display', true);
    launcher.unsetenv('DISPLAY');
    const process = launcher.spawnv([executable]);

    await Scripting.sleep(1500);

    const windows = global.get_window_actors();
    const window = windows.find(actor =>
        actor.metaWindow.get_title() === 'SessionSifu');
    if (!window) {
        const titles = windows.map(actor => actor.metaWindow.get_title());
        process.force_exit();
        throw new Error(`SessionSifu GTK window was not created; visible titles: ${titles.join(', ')}`);
    }

    process.force_exit();
}

export function finish() {}
