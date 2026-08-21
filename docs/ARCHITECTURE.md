# Architecture

SessionSifu is split into three runtime layers and one distribution layer.

## GNOME Shell extension

`extension/sessionsifu@local/` runs inside GNOME Shell. It can inspect Shell and
Mutter window objects, maintain current-window state, capture complete session
files, restore layouts and provide the top-bar indicator.

`openFiles.js` combines three sources: `/proc/<pid>/fd`, explicit file arguments
in the process command line, and the per-user `recently-used.xbel` bookmark
file parsed by `GLib.BookmarkFile`. Recent entries are matched by exact basename
against the window title and ranked by modification time. Generic descriptor
scanning excludes hidden state, while explicitly launched or title-matched
documents may reside below hidden directories. At most 512 descriptors, 2,048
recent entries and 32 resulting paths per window are processed.

At restoration time every path is revalidated and deduplicated per application.
When a desktop entry supports files or URIs, the extension calls
`Gio.AppInfo.launch()` for each new group of files, including after the first
window has launched or when the application is already running.

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

The manager checks the repository update manifest in a background thread,
downloads a newer package to the user's cache and verifies its origin, size and
SHA-256 digest. It uses `dpkg-deb --extract` only as an archive reader, validates
the expected payload, then atomically installs the manager, desktop files, icon,
extension bundle and extension below the user's XDG directories and
`~/.local/bin`. It never invokes `apt`, `dpkg -i`, PackageKit or Ubuntu Software.

## Local storage

Named and automatic session files are JSON. They are kept below the XDG user
configuration directory, normally `~/.config/sessionsifu/`. Update packages use
the XDG cache directory, normally `~/.cache/sessionsifu/updates/`.

Automatic snapshot filenames use UTC timestamps in the form
`auto-YYYYMMDD-HHMMSS.json`. Only filenames matching that pattern can be listed
or restored through the automatic-history D-Bus methods.

Session JSON can contain an `open_files` array on each saved window object. This
is best-effort metadata rather than a promise that every application's internal
document state can be observed.

## Debian package and update channel

`packaging/build-deb.sh` assembles the manager, desktop files, extension,
compiled schema, extension bundle, documentation and package metadata. It copies
the result into `updates/` and generates `updates/latest.json` from the final
package size and SHA-256 digest.

The manifest and package live on the same `main` revision. The updater accepts
only HTTPS package URLs under `tpluharik/SessionSifu` on
`raw.githubusercontent.com`. The Debian package remains necessary for initial
dependency installation; later application updates are unprivileged and local
to the user.
