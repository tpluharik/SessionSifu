# SessionSifu for GNOME

SessionSifu saves and reconstructs a GNOME desktop: running applications,
windows, workspaces, monitors, geometry, maximized/fullscreen/minimized state,
sticky windows, focus and supported tiling relationships.

The initial release targets Ubuntu 26.04 LTS with GNOME Shell 50 and Wayland.
It consists of:

* a GNOME Shell 50 extension with a top-bar indicator;
* a GTK 4/libadwaita session manager;
* a command-line client;
* an opt-in login restore helper; and
* a self-contained Debian package.

## Important boundary

Linux does not expose a safe, universal API for serializing another program's
private memory. SessionSifu can relaunch an application and reconstruct its
windows. Tabs, unsaved documents, terminal processes and other internal content
are restored only when the application itself implements recovery. Browsers,
editors and many GNOME applications already do.

## Install

```sh
sudo apt install ./dist/sessionsifu_1.0.1_all.deb
```

Open **SessionSifu** from the application grid and select **Enable**. A
one-time logout/login can be required because Wayland cannot reload GNOME Shell
in place.

## Command line

```sh
sessionsifu --save Work
sessionsifu --restore Work
sessionsifu --list
```

Session data is stored under `~/.config/sessionsifu/`. It contains
window titles, application identifiers, launch commands, working directories,
window geometry and process metadata. It is local to the user and is not sent
anywhere.

## Build

Run `./packaging/build-deb.sh`. The script validates the Python, JavaScript,
desktop entries, JSON and GSettings schema before producing the package.

## Origin and license

SessionSifu is a GPL-3.0 derivative of Another Window Session Manager. See
`NOTICE` for attribution and provenance. Smart Auto Move NG was audited as an
alternative GNOME 50 foundation but no code from it is included in this release.
