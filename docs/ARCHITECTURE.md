# Architecture

This document describes the 3.5.19 runtime and release layout. User-facing
steps live in the [session restoration guide](RESTORE_GUIDE.md) and
[Privacy Recall guide](RECALL_GUIDE.md).

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

GNOME recovery processes all eligible groups sequentially, with an eight-second
inter-application delay and a 30-second readiness deadline. Historical records
are capped by the latest saved window count (maximum 32 per app). Windows owned
by an application still in `Shell.AppState.STARTING` are never mutated through
the immediate existing-window path; the indicator waits for the window's
shown/title settle callbacks. A shared queue owner prevents overlapping restores.
GSettings records progress and a flushed per-application checkpoint before launch.
After interruption, the global pause lasts ten minutes; a separate 24-hour hold
applies only to the in-flight application and can be bypassed manually.
Successful requests clear their application hold, and normal queue completion
clears the active checkpoint. Failed and deferred records are retained; cleanup
checks original bytes to avoid deleting live state rewritten during a wait.

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
manager. In 3.4.0, `PlanSession`/`PlanHistory` return a bounded application
summary and their selection variants accept only identities confirmed in the
restore preview.

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
Shell and D-Bus. `model.py` validates schema-3 session JSON and bounds window,
text and document collections. `storage.py` performs atomic same-directory
replacement, confines loads to SessionSifu-owned directories and retains the
five newest automatic snapshots. `controller.py` is the small application API
used by both the command line and the Qt manager.

`ui.py` provides the Windows, macOS and portable Linux manager. It uses
`QSystemTrayIcon`, offers named sessions and rolling history, saves at 30-second
through 30-minute intervals and exits through **Turn Off SessionSifu**. Slow or
privileged platform operations are delegated to adapters rather than embedded
in widget code.

`capsule.py` provides the shared Workspace Capsule boundary. Versioned manifests
are AES-GCM authenticated, written atomically below owner-private directories
with hashed filenames and never contain generated shell text. `preflight()`
resolves structured command arrays and effective permissions before launch.
Profile adapters are explicitly non-security boundaries and can no longer
launch; their manifests are retained for migration and data deletion. Signal
also ignores the former profile switch. The Flatpak
pilot requires an already installed application ID, assigns capsule-specific
XDG roots, resets broad host-filesystem grants and removes shared credential
agents without mutating global overrides. The Windows backend emits a
reviewable `.wsb` file with read-only host mappings. Capsule data deletion is
an explicit operation independent of manifest deletion.

Both managers populate capsule choices from `flatpak list --app` and retain
the immutable Flatpak application ID separately from its localized display
name. A bounded classifier assigns the encrypted manifest's application profile
from trusted ID/name metadata. The catalog contains no host executable fallback;
an empty or unavailable catalog is shown as unavailable and launch remains
fail-closed.

The selected profile is operational rather than cosmetic. The Flatpak command
builder adds a capsule home/XDG tree to every application and reviewed native
arguments for Firefox, Chromium-family browsers, VS Code and VSCodium. Argument
vectors remain structured; no application metadata is evaluated by a shell.

The GNOME top-bar and portable tray open capsule setup directly. A process
registry owned by the active manager records only successfully spawned capsule
children and drops them after their process exits. The UI refreshes this bounded
view periodically; it never performs global process enumeration. External
applications remain native compositor-managed windows rather than being
reparented into SessionSifu, which is not supported for independent Wayland
clients.

Before restore, both managers request a grouped plan and present every
application as an enabled checkbox. Cancellation or an empty selection launches
nothing. The identity set is applied before duplicate-app and document
validation, so the preview is an execution boundary rather than a cosmetic
summary.

`recall.py` provides the portable activity timeline. It stores a reduced JSON
shape rather than restorable process commands, writes through an atomic
same-directory replacement, rejects symbolic-link storage and applies bounded
retention. It applies the current exclusion list during capture and again before
constructing search summaries. The Qt timer starts only while its persisted
feature flag is true.

`content.py` is the accessibility-first enrichment layer. On Linux it matches
each saved window to its AT-SPI top-level window, then walks a strictly bounded
subtree and records names/text; sibling windows are not merged into one result.
It never opens document contents. All platforms derive
bounded re-entry targets from already observable files and URLs. Private
browsing, remote-display and explicitly protected contexts receive a protection
reason before persistent images are selected.

The GNOME capture file carries a temporary process identifier solely to locate
the matching AT-SPI application. The finalizer caps the accessibility pass at
1.5 seconds, 3,072 nodes and 512 KiB across the whole moment, and does not copy
the identifier into the encrypted record.

`api.py` implements the portable read-only integration API. The GNOME manager
provides the equivalent `--local-api-stdio` mode. Each accepts one bounded JSON
object per line through inherited stdin/stdout and deliberately implements no
launch, delete or update method. No TCP or Unix-domain socket is opened.

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

### 3.5 retrieval, restore and transfer layers

Recall decrypts into a bounded LRU record cache and an ephemeral in-memory FTS5
index. A signature of record names, sizes and modification times invalidates
the index and removes deleted cache entries when the vault changes. A reentrant
lock serializes index access across short-lived GTK/Qt worker threads. No
plaintext index or cache is persisted.

OCR typo fallback uses a memory-only dictionary of unique bounded OCR tokens,
grouped by length, rather than rescanning the full raw OCR corpus for every
query. Optional semantic ranking is a second, separately enabled retrieval
pass: `semantic.py` accepts only an explicit regular local model directory,
forces model runtimes offline, rejects remote code and bounds documents and
vector dimensions. Document vectors are cached by record/window key plus a
content digest and are recomputed only when content changes. Embeddings are not
persisted.

OCR diagnostics live inside the encrypted record. Reindexing decrypts only the
selected record's bounded images, replaces its OCR text/boxes atomically and
does not change capture exclusions. Visual hashes group adjacent near-identical
moments; annotations are encrypted in the same authenticated record.

Restore operations are recorded in owner-private JSON journals. A journal is
written as `in-progress` before launch and atomically finished with per-action
states. Retry resolves only a still-present named/history source; it never
replays a raw command from the journal.

The optional MCP surface is JSON-RPC over inherited stdin/stdout. It lists only
search, cited Ask, restore preview, journal inspection and diagnostics. There is
no socket and no write/launch/delete/update method.

Transfer archives use Scrypt-derived AES-256-GCM, bounded ZIP members and path
validation. Recall payloads are re-encrypted with the destination vault key on
import. The passphrase is requested interactively and never stored.

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

Portable storage uses schema-3 JSON under `%APPDATA%/SessionSifu` on Windows,
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
window previews. Version 3.5.14 uses serialized screenshot-area requests only for
unobscured windows on the active workspace. A 64-entry / 64-MiB memory cache
retains previously visible windows across workspace changes; source images over
16 MiB are not cached. Native screenshot staging is private and short-lived in
the user runtime directory. The cache is cleared on extension lifecycle and
privacy-policy changes and is not a persistent plaintext image store.
Snapshots reuse cached pixels by stable window ID, preserve the original image
timestamp and expose live/cached completeness separately. Hidden-window actor
painting and programmatic workspace switching are not used. Portable Qt builds use the native window
handle where available and fall back to a bounded screen crop after user
permission.

Search decrypts bounded records into process memory and creates separate
ephemeral SQLite FTS5 tables for individual windows and display-wide OCR. Each
window row has a stable record/window identity and independently weighted
application, title, opted-in file, accessible-text and window-OCR fields.
Accessible application text ranks ahead of OCR because it preserves characters
without image recognition; OCR remains available for apps that expose no text.
Exact FTS candidates
are supplemented by a bounded, recent-first in-memory scan for OCR prefixes
and small recognition substitutions; optional related matching adds local
token-similarity candidates and the focused window receives a small rank
boost. An empty query remains a desktop-level chronological timeline whose
gallery can navigate each linked window image independently.
OCR runs in Tesseract sparse-layout TSV mode. The storage image remains a
compact JPEG, but recognition receives a temporary `0600` grayscale copy with
automatic contrast, bounded 3× Lanczos upscaling, sharpening and a 180-DPI hint.
That working image is deleted immediately after Tesseract exits and is never
encrypted or retained because the vault already contains the source preview.
Version 3.4.0 bundles pinned Czech and English fast Tesseract models and their
TSV configuration. The engine locates the signed resources in the system,
user-local, source or frozen portable layout and selects `ces+eng` together.
It falls back to installed locale models only when a bundled resource is not
available.
Only words meeting the confidence floor enter the index; their text, confidence
and normalized image rectangle are stored inside the encrypted record. Search
returns at most 64 matching
rectangles for the selected window/display, and GTK/Qt draw them over the
CONTAIN-fitted image without creating a modified screenshot on disk.
Persistent plaintext OCR or search indexes are never created. Each window row
links directly to its encrypted preview. GNOME also stores display geometry so
the GTK browser can crop a display image in memory for older/fallback records.
The portable Qt browser follows the same exact-window-first model. Reopen
actions use only that window's validated file or observable URL targets.

The GTK and Qt search surfaces debounce text entry for 250 ms and execute vault
search on a worker thread. Query generations prevent an older result from
replacing a newer request, and rapid typing retains only the newest pending
request. The interfaces render 24 results initially. Compact mode performs no
preview decryption; Visual mode decodes one bounded thumbnail per visible
result, while full screenshots are loaded only for the selected detail image.
Window results retain the full non-excluded window list for gallery navigation,
while `matched_window` remains the authoritative target for rank, preview
selection, highlighting and reopening.

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
Encryption, OCR, FTS and decoded images execute outside GNOME Shell. Capture
status contains only structural diagnostics such as duration,
expected/eligible/captured/missing/protected window counts, preview count, skip
reason and vault size.

## Debian package and update channel

`packaging/build-deb.sh` assembles the manager, desktop files, extension,
compiled schema, extension bundle, pinned Czech/English OCR resources,
documentation and package metadata. It copies
the result into `updates/` and generates `updates/latest.json` from the final
package size and SHA-256 digest.

The signed manifest and package live on the same `main` revision. The updater accepts
only HTTPS package URLs under `tpluharik/SessionSifu` on
`raw.githubusercontent.com`. The Debian package remains necessary for initial
dependency installation; later application updates are unprivileged and local
to the user. A user-local update validates all Czech/English model and TSV files,
then atomically replaces `~/.local/share/sessionsifu/tessdata` before activating
the new launcher.

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
