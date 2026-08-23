# Architecture

SessionSifu 3 has a full GNOME runtime, a portable runtime shared by Windows,
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
safe interchange format. Version 2.5 validates argument count, byte length,
control characters and executable availability, then calls `Gio.Subprocess`
directly. Saved text is never reconstructed as shell syntax.

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

The manager verifies the update manifest's Ed25519 signature against an embedded
public key. It rejects wrong channels, expiry, rollbacks and incompatible
minimum versions, then downloads the package and verifies origin, size and
SHA-256. It uses `dpkg-deb --extract` only as an archive reader, validates
the expected payload, then installs the manager and its Recall engine together
below `~/.local/share/sessionsifu/app`, followed by desktop files, icon,
extension bundle and extension below the user's XDG directories. The
`~/.local/bin/sessionsifu` launcher is atomically replaced only after its
dependencies are present. The real-package regression test executes that
launcher after every Debian build. The updater never invokes `apt`, `dpkg -i`,
PackageKit or Ubuntu Software.

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

All POSIX SessionSifu state uses `0700` directories and `0600` files. The GTK
manager performs a bounded startup migration only below an owned, non-symlinked
configuration root; the Shell writer also enforces private modes after each
atomic save and backup.

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

Privacy Recall data is separate from named/restorable sessions. Version 3.0
moves persistent entries into an AES-GCM vault. GNOME Shell writes a short-lived
private metadata/image capture and invokes the unprivileged manager finalizer;
the finalizer applies domain/sensitive policy, optional per-window OCR, deduplication,
authenticated encryption, retention and quota pruning, then removes plaintext
temporary files. GNOME stores one encrypted image per display plus up to 64
independently rendered window images. Portable Qt builds use the native window
handle where available and fall back to a bounded screen crop after user
permission.

Search decrypts bounded records into process memory and creates separate
ephemeral SQLite FTS5 tables for individual windows and display-wide OCR. Each
window row has a stable record/window identity and independently weighted
application, title, opted-in file and window-OCR fields; optional related matching adds
local token-similarity candidates and the focused window receives a small rank
boost. An empty query remains a desktop-level chronological timeline.
Persistent plaintext OCR or search indexes are never created. Each window row
links directly to its encrypted preview. GNOME also stores display geometry so
the GTK browser can crop a display image in memory for older/fallback records.
The portable Qt browser follows the same exact-window-first model. Reopen
actions use only that window's validated file or observable URL targets.

Changing exclusions deletes affected vault records because previously captured
pixels cannot be reliably redacted. As an additional query-time boundary, a
legacy record containing both an excluded and non-excluded application may
return the non-excluded window's metadata, but its shared display preview and
OCR are withheld so pixels from the excluded application cannot leak.

Recall's hot path uses compact atomic asynchronous writes. Open-file discovery is
bounded and avoids redundant target probes; paths are validated before restore.
GNOME Shell performs one asynchronous desktop grab, then serializes compositor
window actors into private streams without starting overlapping captures. The
unprivileged manager helper downsizes displays to at most 1,280 pixels/quality
70 and windows to 960 pixels/quality 65 through private temporary files.
Encryption, OCR, FTS and decoded images execute outside GNOME Shell. Capture status contains
only structural diagnostics such as duration, preview count, skip reason and
vault size.

## Debian package and update channel

`packaging/build-deb.sh` assembles the manager, desktop files, extension,
compiled schema, extension bundle, documentation and package metadata. It copies
the result into `updates/` and generates `updates/latest.json` from the final
package size and SHA-256 digest.

The signed manifest and package live on the same `main` revision. The updater accepts
only HTTPS package URLs under `tpluharik/SessionSifu` on
`raw.githubusercontent.com`. The Debian package remains necessary for initial
dependency installation; later application updates are unprivileged and local
to the user.

`latest.json.sig` authenticates the exact manifest bytes with a dedicated
Ed25519 release key whose public half is embedded in the manager and published
with the package. The manifest binds stable channel, issue/expiry time, minimum
and target versions, URL, size and SHA-256. The private key remains outside the
repository and CI. SHA-256 remains a second integrity layer.

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
references are pinned to reviewed full commit SHAs and direct Python build
inputs are exact-version pinned. Fully hashed per-platform transitive locks,
SBOMs and provenance attestations remain roadmap work.
