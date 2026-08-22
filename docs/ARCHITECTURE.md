# Architecture

SessionSifu 2 has a full GNOME runtime, a portable runtime shared by Windows,
macOS and Linux desktops, and platform-specific distribution layers.

## Trust boundaries

SessionSifu has no privileged service. The GNOME extension and both managers
run as the logged-in user; the Debian maintainer scripts only compile installed
schemas and refresh desktop metadata. The full integration trusts GNOME Shell,
Mutter, the user's session D-Bus and files below the user's configuration root.
Portable editions trust their platform window APIs and the current user's data
directory.

A session file crosses from data into application-launch configuration during
restore. It must therefore be treated as trusted active configuration, not as a
safe interchange format. The current GNOME fallback reconstructs some stored
commands through a shell and must be replaced with direct argument-vector
launching; see SS-2026-001 in the [security audit](SECURITY_AUDIT.md).

The session D-Bus is a same-user interface rather than an authorization
boundary. Any process permitted to use that bus and name can request operations.
Recall opt-ins and file modes reduce accidental disclosure but do not defend
against malware already executing as the same user. The complete data inventory
is in [PRIVACY.md](PRIVACY.md).

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
The extension calls `Gio.AppInfo.launch()` only when the desktop entry accepts
files or URIs and declares at least one non-scheme document MIME type. This
keeps saved paths away from protocol-only launchers while still reopening new
document groups after the first application window has launched.

Window restoration treats Mutter objects as short-lived. `windowSafety.js`
rejects windows without a compositor actor, workspace or valid monitor before
native state or geometry calls. The indicator serializes restore callbacks for
each window, while `moveSession.js` cancels monitor waits and delayed geometry
work as soon as `unmanaging` is emitted. Saved monitor, geometry and workspace
values are bounded before they reach Mutter. Maximized windows are not passed to
`move_resize_frame()` while their maximized state is being applied. Newly
created windows receive a 750-millisecond settle period before any saved state
is applied.

Previous-session files are restored through a paced queue rather than parallel
callbacks. A shared runtime safety gate stops launches and window operations as
soon as GNOME confirms logout, reboot or shutdown; canceling the end-session
dialog reopens the gate.

`continuousSaver.js` owns the rolling history timer. It reads the GSettings
interval, performs an initial save shortly after startup, prevents overlapping
saves and removes files older than the five newest successful snapshots.

`recallRecorder.js` owns a separate timer that cannot save unless the
disabled-by-default `recall-enabled` flag is true. Entries are sanitized before
writing: process IDs, commands, host/user data and desktop-file paths are
removed, full document paths require another opt-in, and matching excluded
applications are discarded. Files are limited to 2 MiB, queries to 100 results,
storage to 500 entries and retention to 30 days at the schema level. Recall
files use mode 0600 below a mode-0700 directory on POSIX systems.

Application exclusions are also re-evaluated while reading every entry. This
query-time filter removes the matching application's identity, title and file
paths before search text or result rows are constructed, so editing exclusions
redacts existing history immediately. The Ubuntu/GNOME shortcut is installed
as a dedicated GNOME Custom Shortcut while its option is enabled. Both the app
and extension synchronize the same owned settings path, so it launches the GTK
snapshot browser without relying on an extension-only grab or reading arbitrary
keyboard input.

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

## Portable core and manager

`portable/sessionsifu_portable/` is a Python package independent of GTK, GNOME
Shell and D-Bus. `model.py` validates schema-2 session JSON and bounds window,
text and document collections. `storage.py` performs atomic same-directory
replacement, confines loads to SessionSifu-owned directories and retains the
five newest automatic snapshots. `controller.py` is the small application API
used by both the command line and the Qt manager.

`ui.py` provides the Windows, macOS and portable Linux manager. It uses
`QSystemTrayIcon`, offers named sessions and rolling history, saves at 30-second
through 30-minute intervals and exits through **Turn Off SessionSifu**. Slow or
privileged platform operations are delegated to adapters rather than embedded
in widget code.

`recall.py` provides the portable activity timeline. It stores a reduced JSON
shape rather than restorable process commands, writes through an atomic
same-directory replacement, rejects symbolic-link storage and applies bounded
retention. It applies the current exclusion list during capture and again before
constructing search summaries. The Qt timer starts only while its persisted
feature flag is true.

`shortcut.py` validates and normalizes the editable cross-platform accelerator.
`hotkey.py` exposes that Recall popup shortcut on portable
targets. Windows uses `RegisterHotKey`; macOS uses Cocoa's modifier/key event
monitor; KDE/Wayland and other supporting Linux compositors use the user-mediated
XDG GlobalShortcuts portal. The helper reacts only to the configured exact
combination, does not record key text and is stopped when its shortcut option is
off. Search remains available while new Recall capture is paused.
The tray action and application-local shortcut remain available if a compositor
does not implement the portal or permission is declined.

The portable model intentionally records only observable state. Process files
are restricted to readable regular files below the user's home directory,
hidden state paths are excluded and each window is capped at 32 files.

## Platform adapters

- `windows.py` enumerates visible top-level windows with Win32 `EnumWindows`,
  records process identity through `psutil`, and restores safe geometry and
  minimized/maximized state using public User32 calls. Windows virtual desktops
  remain outside the current public adapter.
- `macos.py` uses JavaScript for Automation with System Events to inspect and
  position accessible application windows. Applications and files are opened
  through `/usr/bin/open`; the user must grant Accessibility permission. Spaces
  are not manipulated through private APIs.
- `linux.py` provides three runtime profiles. KDE Plasma 6 uses `kdotool`, which
  executes KWin scripts over D-Bus and works on native Wayland. X11 desktops use
  `wmctrl`. General GNOME uses that portable fallback and directs GNOME 50 users
  to the bundled extension for full Wayland fidelity.
- `base.py` centralizes capability reporting, bounded document discovery and
  shell-free application launches. An adapter reports unsupported geometry or
  workspace features instead of fabricating restored state.

## Local storage

Named and automatic session files are JSON. They are kept below the XDG user
configuration directory, normally `~/.config/sessionsifu/`. Update packages use
the XDG cache directory, normally `~/.cache/sessionsifu/updates/`.

Recall already enforces `0700` directories and `0600` files. The inherited
GNOME session writer currently creates other directories/files with broader
modes and relies on a non-traversable parent. That is not the target security
design: SS-2026-005 requires an ownership-checked migration to `0700`/`0600`
throughout SessionSifu storage.

Automatic snapshot filenames use UTC timestamps in the form
`auto-YYYYMMDD-HHMMSS.json`. Only filenames matching that pattern can be listed
or restored through the automatic-history D-Bus methods.

Portable storage uses schema-2 JSON under `%APPDATA%/SessionSifu` on Windows,
`~/Library/Application Support/SessionSifu` on macOS and the XDG configuration
directory on Linux. Portable snapshot names include microseconds to prevent
rapid captures from overwriting one another. The portable schema is separate
from the inherited GNOME extension format; an explicit migration layer will be
required before files can be exchanged between those engines.

Session JSON can contain an `open_files` array on each saved window object. This
is best-effort metadata rather than a promise that every application's internal
document state can be observed.

Privacy Recall data is separate from named/restorable sessions. Version 2.4 can
store one bounded JPEG preview per display on the full GNOME integration only,
behind a second opt-in. Capture is skipped on the lock screen and whenever an
excluded application is visible. Preview files use mode 0600 and are removed
with their metadata. Search remains metadata-based and does not perform OCR;
when a keyword matches an app, title or opted-in file, GTK crops that window's
geometry from the corresponding display preview in memory. Portable editions
stay metadata-only pending cross-platform security review.

Changing the exclusion list purges existing screenshot previews while preserving
metadata because previously captured pixels cannot be retroactively redacted.

Recall's hot path uses compact atomic asynchronous writes. Open-file discovery is
bounded and avoids redundant target probes; paths are validated before restore.
GNOME Shell performs one asynchronous desktop grab and never overlaps another
Recall image capture. The unprivileged manager helper loads that temporary PNG
once, crops every display, downsizes the longest edge to at most 1,280 pixels and
writes quality-70 JPEG previews through private temporary files. Summary parsing
and decoded search images are bounded caches, and retention scans run at most
every five minutes unless the retention setting changes.

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

SHA-256 currently protects integrity only relative to that manifest. Because
the package and digest share one unsigned mutable channel, neither proves an
independent publisher identity. SS-2026-002 specifies signed, expiring,
rollback-resistant metadata and immutable release assets as the required
replacement.

## Multi-platform release pipeline

`.github/workflows/release.yml` runs the portable model/storage tests on Ubuntu
26.04, Windows 2025, Apple-silicon macOS and Intel macOS. PyInstaller then
creates Windows x64, macOS arm64/x64 and Linux x64 desktop bundles. A separate
Ubuntu job runs the full GNOME validation and Debian build.

Pushes and pull requests retain build artifacts for inspection. An existing
`v*` tag additionally downloads all job artifacts, generates `SHA256SUMS` and
creates one GitHub Release. Signing, Apple notarization and artifact attestation
are deliberately tracked as roadmap work rather than implied by the pipeline.

Workflow permissions are read-only except for the tag publisher. Action
references and Python build dependencies are not yet immutable; pinning full
action SHAs and hashed dependency locks is tracked as SS-2026-003.
