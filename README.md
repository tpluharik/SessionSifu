<p align="center">
  <img src="branding/sessionsifu-logo.svg" alt="SessionSifu — desktop session restoration" width="620">
</p>

<p align="center">
  <a href="https://github.com/sponsors/tpluharik"><img src="https://img.shields.io/badge/Sponsor-SessionSifu-EA4AAA?logo=githubsponsors&amp;logoColor=white" alt="Sponsor SessionSifu on GitHub"></a>
</p>

<p align="center">
  If SessionSifu makes your desktop easier to live with, you can support its continued development through <a href="https://github.com/sponsors/tpluharik">GitHub Sponsors</a>.
</p>

# SessionSifu 2

SessionSifu saves and reconstructs desktop layouts. It records running
applications, documents and windows, then can relaunch applications and rebuild
the supported parts of their layout.

Version 2.5.1 retains the full Ubuntu 26.04/GNOME Shell 50 integration and adds
portable editions for Windows, macOS, KDE Plasma 6 and other GNOME/Linux
desktops. The project is open source under GPL-3.0.

## Features

- Manual named sessions from the application or top-bar menu.
- Rolling automatic history containing the five newest desktop snapshots.
- Snapshot intervals of 30 seconds, 1, 5, 10, 15 or 30 minutes.
- Five minutes as the default interval.
- One-click restoration of an automatic or named session.
- Reopening of documents discovered from process descriptors, launch arguments
  or GNOME's recent-file database.
- Optional restoration of the previous desktop after login.
- GNOME top-bar indicator for common actions.
- A top-bar **Turn Off SessionSifu** action that disables the integration.
- GTK 4/libadwaita manager and command-line client.
- One-click, user-local in-app updates backed by this GitHub repository.
- Debian package containing the manager, extension, schema and integration
  files.
- Dedicated yin-yang application and GNOME top-bar icons.
- Shared Qt manager and tray menu for portable desktop builds.
- Native Win32 window enumeration and geometry restoration.
- macOS System Events integration with explicit Accessibility diagnostics.
- KDE Plasma 6 Wayland support through `kdotool`, with X11 fallback.
- A common, validated JSON session format across portable platforms.
- Automated multi-platform builds and tagged GitHub Releases.
- Experimental **Privacy Recall**, a disabled-by-default searchable timeline of
  sanitized application and window metadata with exclusions, bounded local
  retention and separately opted-in compressed display/app previews on full
  GNOME integration.
- A live recording badge on the GNOME top-bar or portable tray icon while a
  Privacy Recall snapshot is being written.

## Compatibility

| Edition | Initial supported target | Restoration level |
| --- | --- |
| GNOME full integration | Ubuntu 26.04, GNOME Shell 50 | Applications, documents, workspaces, monitors, geometry and window state on Wayland/X11 |
| GNOME portable | Other current GNOME/Linux desktops | Applications and documents; geometry when the compositor exposes it through X11 tools |
| KDE Plasma | Plasma 6 on Wayland or X11 | Applications, documents, geometry and virtual desktops when `kdotool` or `wmctrl` is available |
| Windows | Windows 10/11 x64 | Applications, documents and Win32 window geometry/state |
| macOS | macOS 12+, Apple silicon and Intel | Applications, documents and accessible window geometry after user permission |

GNOME Shell extensions are version-sensitive. SessionSifu metadata deliberately
declares Shell 50 rather than claiming untested compatibility with other major
GNOME releases. The portable GNOME edition exists for those systems without
loading private Shell code.

Platform security boundaries are respected. Windows virtual desktops, macOS
Spaces and native Wayland windows without a compositor integration are not
claimed as restored. See [ROADMAP.md](ROADMAP.md) for planned parity work.

## What is saved

SessionSifu records application identifiers, launch commands, process metadata,
window titles, workspace and monitor assignments, geometry, stacking/focus and
supported minimized, maximized, fullscreen, sticky and tiling state.

For each window, SessionSifu combines readable files exposed through
`/proc/<pid>/fd`, explicit paths or `file://` URIs in the process command line,
and an exact filename match from GNOME's `recently-used.xbel`. The most recently
modified matching bookmark is selected. This recovers documents from
applications such as LibreOffice that close the document descriptor after
loading it. Explicit and title-matched documents may live below hidden project
directories such as `~/.codex`; generic descriptor scanning still excludes
hidden application state, system resources, deleted files and special files.

At most 512 descriptors and 2,048 recent-file entries are examined, with at
most 32 paths saved per window. During restoration, each unique path is passed
only to a desktop launcher that declares a real document MIME type. Launchers
that register only URL schemes, such as Signal, never receive saved file paths.
Additional documents are sent even after the first application window has
started.

Linux does not provide a universal way to serialize another application's
private memory. SessionSifu can reopen an application and reconstruct its window
layout, but tabs, unsaved documents, terminal processes and other internal
content are restored only when that application provides its own recovery
support.

The same rule applies to Windows and macOS: SessionSifu records observable
process files and public window state, but it does not inspect or serialize
private application memory. Portable builds use `psutil` for best-effort
document discovery and pass only existing local files back to a relaunched
application.

Open-file restoration remains best effort when an application neither exposes a
file nor registers it with GNOME. Untitled or unsaved in-memory documents still
depend on the application's own crash-recovery behavior.

## Install or upgrade

### GNOME 50 full integration

Download `sessionsifu_2.5.1_all.deb` from the `updates/` directory, or build it
locally, then install it with:

```sh
sudo apt install ./sessionsifu_2.5.1_all.deb
```

When installing from this checkout, use:

```sh
sudo apt install ./dist/sessionsifu_2.5.1_all.deb
```

After installation:

1. Open **SessionSifu** from the application grid.
2. Select **Install & Enable** on a new installation, or **Update Integration**
   when upgrading an older per-user extension.
3. Log out and back in once when requested. Wayland cannot reload GNOME Shell
   extensions in place.
4. Confirm that the SessionSifu top-bar icon is visible.

### Windows, macOS, KDE and portable GNOME

Tagged releases attach these self-contained artifacts:

- `SessionSifu-2.5.1-windows-x64.zip`;
- `SessionSifu-2.5.1-macos-arm64.zip`;
- `SessionSifu-2.5.1-macos-x64.zip`; and
- `SessionSifu-2.5.1-linux-x64.tar.gz`.

Extract the matching archive and launch **SessionSifu**. macOS asks for
Accessibility permission the first time window geometry is inspected. On KDE
Plasma 6, install `kdotool` for native Wayland geometry and virtual-desktop
restoration; X11 can use `wmctrl`. Without those optional compositor helpers,
the portable Linux edition still stores its own sessions but reports
application-only capability rather than pretending that geometry was captured.

## Automatic session history

Automatic saving is enabled by default and creates the first snapshot shortly
after the GNOME integration starts. The default interval is five minutes. The
manager offers these choices:

- every 30 seconds;
- every minute;
- every 5 minutes;
- every 10 minutes;
- every 15 minutes; or
- every 30 minutes.

Only the five newest automatic snapshots are retained. A sixth successful save
removes the oldest file. Failed saves do not prune valid history. **Save Now**
can create a snapshot even when continuous saving is switched off.

Automatic history is stored in:

```text
~/.config/sessionsifu/history/
```

Use the **Automatic history** section in the manager to restore a snapshot.

## Top-bar controls

The SessionSifu top-bar menu provides save, restore and manager shortcuts. Its
**Turn Off SessionSifu** action disables the GNOME Shell integration, stopping
automatic snapshots and removing the top-bar icon. This is reversible: open the
SessionSifu manager from the application grid and select **Enable** to turn the
integration back on.

## Named sessions and login restoration

Arrange the desktop, enter a session name, and select **Save**. Named sessions
appear separately from rolling history and remain until explicitly deleted.

The **Restore previous desktop after login** switch is opt-in. When enabled,
SessionSifu waits for the configured startup delay, relaunches missing
applications one at a time and reconstructs the recorded layout after each new
window has had time to initialize. Applications already running are skipped to
avoid unnecessary duplicate instances. Confirming logout, reboot or shutdown
cancels any restore work still in progress.

## Updates

The manager's **Check for Updates** button reads `updates/latest.json` from this
repository. A newer Debian package is downloaded only from the SessionSifu
repository on `raw.githubusercontent.com`. Before installing it, the application
verifies:

- that the manifest version is valid;
- that the URL uses HTTPS and belongs to this repository;
- the declared package size;
- a 50 MiB maximum download size; and
- the package SHA-256 digest.

The checksum-verified package is extracted—not registered with `apt` or installed with
`dpkg -i`—and its application, desktop entry, autostart entry, icon and GNOME
extension are atomically installed below the current user's XDG directories and
`~/.local/bin`. No root privileges or system package manager are used. A logout
and login is still required to load a replaced GNOME Shell extension on Wayland.
The Debian package remains the supported initial installation method because it
provides SessionSifu's runtime dependencies.

Portable Windows, macOS and Linux builds are currently updated by downloading a
new checksummed artifact from the repository's Releases page. Native
verified in-app replacement for those bundles is roadmap item 2; the interface
does not silently invoke a system package manager.

## Command line

```sh
sessionsifu --save Work
sessionsifu --restore Work
sessionsifu --list

sessionsifu-portable --save Work
sessionsifu-portable --restore Work
sessionsifu-portable --save-history
sessionsifu-portable --diagnostics
```

The command-line client communicates with the GNOME Shell extension over the
user's session D-Bus. The `sessionsifu-portable` client instead selects the
Windows, macOS, KDE or Linux adapter at runtime and can run without GNOME.

## Security

Session files are active restore configuration: they contain executable and
argument information as well as document paths. Restore only sessions created
by your trusted local SessionSifu installation. Do not download, exchange or
restore JSON session files from another person. Version 2.5 launches fallback
commands directly from a bounded argument array and never passes saved session
text through a shell, but restore still intentionally launches the recorded
executable.

The in-app updater verifies an Ed25519 signature using a public key embedded in
the application, then validates channel, validity window, minimum/current
version, repository origin, size and SHA-256. Users upgrading from 2.4 or older
must install 2.5 manually once. The threat model and remediation record are
published in the [security audit](docs/SECURITY_AUDIT.md). Report suspected
vulnerabilities privately through the [security policy](SECURITY.md).

Security-sensitive users should keep Recall screenshots disabled until they
have reviewed the exclusion limitations, use full-disk encryption, keep their
login session locked, and avoid publishing raw SessionSifu JSON or journal
logs. See the complete [local-data and privacy guide](docs/PRIVACY.md).

## Data and privacy

Session data stays on the local computer under `~/.config/sessionsifu/`:

```text
~/.config/sessionsifu/
├── currentSession/   continuously observed current-window state
├── history/          five rolling automatic snapshots
└── sessions/         named sessions and their backups
```

Downloaded update packages are cached under
`~/.cache/sessionsifu/updates/`. Checking for updates contacts GitHub; session
files are never uploaded by SessionSifu.

SessionSifu does not encrypt these files. Version 2.5 migrates owned,
non-symlinked GNOME storage to `0700` directories and `0600` files. Treat the
account and device as the security boundary, enable device encryption, and do
not place the data directory in a broadly shared or synchronized location.

Portable session files remain local as well:

- Windows: `%APPDATA%\SessionSifu`;
- macOS: `~/Library/Application Support/SessionSifu`;
- Linux: `${XDG_CONFIG_HOME:-~/.config}/sessionsifu-portable`.

### Experimental Privacy Recall

Privacy Recall is a feature flag and is **off by default** on every platform.
Nothing is recorded and no Recall storage directory is created until the user
explicitly enables it in the manager. While active, the GNOME top-bar or
portable tray menu displays an active/pause control. While a capture is
actually being saved, the icon gains a temporary recording badge and its menu
status changes to **Privacy Recall: Saving…**.

Version 2.3 records sanitized observable metadata: application identity,
window title, time, workspace/monitor and geometry. Full paths of open files
and GNOME screenshot previews are separate opt-ins. It does not capture the
clipboard, keystrokes, microphone, shell history, browser history or private
application memory.
Users can exclude applications by name or identifier, choose a retention period
from one hour to seven days, search the local timeline and permanently delete
all entries from the manager. Exclusions are enforced both during capture and
during every search, so adding an exclusion immediately redacts that app's
identity, titles and opted-in file paths from older results.

The customizable `Ctrl+Alt+Space` default opens a separate, compact search
popup. It remains available for existing history while capture is paused and
can be changed or disabled independently. Ubuntu/GNOME uses the desktop's
native Custom Shortcuts service, Windows uses `RegisterHotKey`, macOS uses an exact Cocoa key-event
match, and KDE/Wayland or general Linux requests user approval through the XDG
GlobalShortcuts portal. SessionSifu does not log arbitrary keystrokes. A
**Browse Recall Snapshots…** top-bar/tray action is available on every edition.

Recall entries are bounded, written atomically, and stored with user-only
permissions where the platform supports POSIX modes:

- GNOME full integration: `~/.config/sessionsifu/recall/`;
- portable editions: the platform-specific SessionSifu data directory listed
  above, under `recall/`.

SessionSifu never uploads Recall data. Full GNOME integration can optionally
store a private, downscaled JPEG preview for each connected display. Preview
capture is off by default and is skipped while the session is locked or an
excluded application is visible. The search browser shows all display previews
for timeline browsing; after an app, title or opted-in file keyword matches, it
crops the relevant application windows from their display preview in memory.
No duplicate per-application images are stored. Search uses sanitized metadata,
not OCR or semantic indexing. Portable editions remain metadata-only.

Changing the excluded-app list deletes existing screenshot previews while
retaining their searchable metadata. Pixels captured before a new exclusion
cannot be reliably redacted after the fact.

Recall capture is designed to stay out of the desktop's critical path. Version
2.5.1 performs one asynchronous Shell grab, then uses a separate unprivileged
process to crop displays, cap the longest edge at 1,280 pixels and encode JPEGs
at quality 70. Metadata writes start immediately and history summaries are
cached. If preview encoding is still busy at the next capture, SessionSifu
preserves the metadata snapshot and skips only that preview.

Because saved launch commands, open-file paths and window titles may contain
sensitive information, protect backups of the SessionSifu configuration
directory as you would other personal application data.

## Troubleshooting

If the manager reports that `sessionsifu@local` does not exist, or the top-bar
icon is absent after an upgrade, open SessionSifu and select **Install & Enable**
or **Update Integration**, then log out and back in. A per-user extension takes
precedence over the system copy, so SessionSifu explicitly upgrades that copy.

See [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) for diagnostic commands
and recovery steps.

## Build and test

Run:

```sh
./packaging/build-deb.sh
```

The build validates Python and JavaScript syntax, desktop entries, JSON, the
GSettings schema, D-Bus declarations, update parsing and static integration
requirements. It produces:

```text
dist/sessionsifu_2.5.1_all.deb
updates/sessionsifu_2.5.1_all.deb
updates/latest.json
updates/latest.json.sig
```

The update package, manifest and Ed25519 signature are committed together. A
release build signs only when `SESSIONSIFU_UPDATE_SIGNING_KEY` points to the
offline private key; contributor builds never need that key.

For development and release details, see [CONTRIBUTING.md](CONTRIBUTING.md).
For component boundaries, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Maintainers must follow the [release signing and recovery guide](docs/RELEASE_SECURITY.md).

Portable core tests can be run without a graphical desktop:

```sh
python3 tests/test_portable.py
```

`.github/workflows/release.yml` repeats them on Ubuntu, Windows, Apple silicon
and Intel macOS, then builds the four portable bundles and GNOME Debian package.
A pushed `v2.5.1` tag publishes the artifacts and `SHA256SUMS` as a GitHub
Release; ordinary pushes and pull requests build and retain test artifacts only.

## Roadmap

The public [SessionSifu roadmap](ROADMAP.md) contains eleven scoped improvements
covering signed builds, native portable updates, Wayland protocol support,
application-specific document restoration, monitor mapping, browser and
terminal integrations, recovery previews, accessibility/localization,
performance/security, optional encrypted export and privacy-first local
activity recall.

## Community and development

SessionSifu is publicly readable and developed in the open. Direct repository
writes remain restricted to maintainers, while everyone is welcome to
participate through issues, comments, forks and pull requests. Testers on
Ubuntu/GNOME, KDE Plasma, Windows and macOS are especially welcome.

- [Report a bug](https://github.com/tpluharik/SessionSifu/issues/new?template=bug_report.yml)
- [Suggest a feature](https://github.com/tpluharik/SessionSifu/issues/new?template=feature_request.yml)
- [Contribution guide](CONTRIBUTING.md)
- [Code of conduct](CODE_OF_CONDUCT.md)
- [Security policy and private reporting](SECURITY.md)
- [Security audit and remediation plan](docs/SECURITY_AUDIT.md)
- [Privacy and local-data guide](docs/PRIVACY.md)

The current 2.5.1 release establishes the shared platform architecture while
preserving the mature GNOME 50 backend. Compatibility claims are added only
after hands-on testing; reports from configurations not listed in the table are
useful, but are treated as best-effort until support is documented here.

SessionSifu stores session state locally and does not include telemetry. New
contributions must preserve that privacy model, avoid blocking GNOME Shell's
main loop and keep all Mutter window operations guarded against windows that
close or become unmanaged during restoration.

## Origin and license

SessionSifu is a GPL-3.0 derivative of Another Window Session Manager. Original
copyright remains with its authors and contributors. See [NOTICE](NOTICE) for
the audited upstream revision and attribution. Smart Auto Move NG was evaluated
as an alternative foundation, but its source code is not included.
