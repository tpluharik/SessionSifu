# Architecture

SessionSifu is split into three runtime layers and one distribution layer.

## GNOME Shell extension

`extension/sessionsifu@local/` runs inside GNOME Shell. It can inspect Shell and
Mutter window objects, maintain current-window state, capture complete session
files, restore layouts and provide the top-bar indicator.

`continuousSaver.js` owns the rolling history timer. It reads the GSettings
interval, performs an initial save shortly after startup, prevents overlapping
saves and removes files older than the five newest successful snapshots.

The extension exports `org.gnome.Shell.Extensions.SessionSifu.Control` on the
session D-Bus. The interface supports health checks, named-session operations,
automatic history operations, previous-session restoration and opening the
manager.

## GTK manager

`app/sessionsifu` is an unprivileged Python GTK 4/libadwaita application. It
configures GSettings and calls the extension over D-Bus. It does not duplicate
Mutter window-management logic.

The manager also checks the repository update manifest in a background thread,
downloads a newer package to the user's cache, verifies it and asks the desktop
to open the package with Ubuntu's installer.

## Local storage

Named and automatic session files are JSON. They are kept below the XDG user
configuration directory, normally `~/.config/sessionsifu/`. Update packages use
the XDG cache directory, normally `~/.cache/sessionsifu/updates/`.

Automatic snapshot filenames use UTC timestamps in the form
`auto-YYYYMMDD-HHMMSS.json`. Only filenames matching that pattern can be listed
or restored through the automatic-history D-Bus methods.

## Debian package and update channel

`packaging/build-deb.sh` assembles the manager, desktop files, extension,
compiled schema, extension bundle, documentation and package metadata. It copies
the result into `updates/` and generates `updates/latest.json` from the final
package size and SHA-256 digest.

The manifest and package live on the same `main` revision. The updater accepts
only HTTPS package URLs under `tpluharik/SessionSifu` on
`raw.githubusercontent.com`.
