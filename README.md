# SessionSifu for GNOME

SessionSifu saves and reconstructs a GNOME desktop: running applications,
windows, workspaces, monitors, geometry, maximized/fullscreen/minimized state,
sticky windows, focus and supported tiling relationships.

The initial release targets Ubuntu 26.04 LTS with GNOME Shell 50 and Wayland.
It consists of:

* a GNOME Shell 50 extension with a top-bar indicator;
* a GTK 4/libadwaita session manager;
* a command-line client;
* five-file rolling automatic session history;
* an opt-in login restore helper;
* a verified GitHub-backed update checker; and
* a self-contained Debian package.

## Important boundary

Linux does not expose a safe, universal API for serializing another program's
private memory. SessionSifu can relaunch an application and reconstruct its
windows. Tabs, unsaved documents, terminal processes and other internal content
are restored only when the application itself implements recovery. Browsers,
editors and many GNOME applications already do.

## Install

```sh
sudo apt install ./dist/sessionsifu_1.1.0_all.deb
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

Session data is stored under `~/.config/sessionsifu/`. Automatic snapshots are
written to `~/.config/sessionsifu/history/` every five minutes by default, and
only the five newest snapshots are retained. Session data contains
window titles, application identifiers, launch commands, working directories,
window geometry and process metadata. It stays local to the user. Checking for
software updates contacts the project's GitHub repository; a downloaded package
is opened only after its size and SHA-256 digest match the repository manifest.

## Build

Run `./packaging/build-deb.sh`. The script validates the Python, JavaScript,
desktop entries, JSON and GSettings schema before producing the package and the
GitHub update-channel manifest.

## Origin and license

SessionSifu is a GPL-3.0 derivative of Another Window Session Manager. See
`NOTICE` for attribution and provenance. Smart Auto Move NG was audited as an
alternative GNOME 50 foundation but no code from it is included in this release.
