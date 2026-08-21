# SessionSifu for GNOME 50

SessionSifu saves and reconstructs a GNOME desktop layout. It records running
applications and their windows, then can relaunch those applications and place
their windows back on the saved workspaces and monitors.

Version 1.1.1 targets Ubuntu 26.04 with GNOME Shell 50. The project is open
source under GPL-3.0.

## Features

- Manual named sessions from the application or top-bar menu.
- Rolling automatic history containing the five newest desktop snapshots.
- Snapshot intervals of 30 seconds, 1, 5, 10, 15 or 30 minutes.
- Five minutes as the default interval.
- One-click restoration of an automatic or named session.
- Optional restoration of the previous desktop after login.
- GNOME top-bar indicator for common actions.
- GTK 4/libadwaita manager and command-line client.
- In-app update checks backed by this GitHub repository.
- Debian package containing the manager, extension, schema and integration
  files.

## Compatibility

| Component | Supported target |
| --- | --- |
| Distribution | Ubuntu 26.04 and compatible Debian-based systems |
| Desktop | GNOME Shell 50 |
| Display protocol | Wayland is the primary target; X11 code paths are retained |
| Package architecture | Architecture-independent Debian package |

GNOME Shell extensions are version-sensitive. SessionSifu metadata deliberately
declares Shell 50 rather than claiming untested compatibility with other major
GNOME releases.

## What is saved

SessionSifu records application identifiers, launch commands, process metadata,
window titles, workspace and monitor assignments, geometry, stacking/focus and
supported minimized, maximized, fullscreen, sticky and tiling state.

Linux does not provide a universal way to serialize another application's
private memory. SessionSifu can reopen an application and reconstruct its window
layout, but tabs, unsaved documents, terminal processes and other internal
content are restored only when that application provides its own recovery
support.

## Install or upgrade

Download `sessionsifu_1.1.1_all.deb` from the `updates/` directory, or build it
locally, then install it with:

```sh
sudo apt install ./sessionsifu_1.1.1_all.deb
```

When installing from this checkout, use:

```sh
sudo apt install ./dist/sessionsifu_1.1.1_all.deb
```

After installation:

1. Open **SessionSifu** from the application grid.
2. Select **Install & Enable** on a new installation, or **Update Integration**
   when upgrading an older per-user extension.
3. Log out and back in once when requested. Wayland cannot reload GNOME Shell
   extensions in place.
4. Confirm that the SessionSifu top-bar icon is visible.

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

## Named sessions and login restoration

Arrange the desktop, enter a session name, and select **Save**. Named sessions
appear separately from rolling history and remain until explicitly deleted.

The **Restore previous desktop after login** switch is opt-in. When enabled,
SessionSifu waits for the configured startup delay, relaunches missing
applications and reconstructs the recorded layout. Applications already running
are skipped to avoid unnecessary duplicate instances.

## Updates

The manager's **Check for Updates** button reads `updates/latest.json` from this
repository. A newer Debian package is downloaded only from the SessionSifu
repository on `raw.githubusercontent.com`. Before opening Ubuntu's installer,
the application verifies:

- that the manifest version is valid;
- that the URL uses HTTPS and belongs to this repository;
- the declared package size;
- a 50 MiB maximum download size; and
- the package SHA-256 digest.

Installation still requires approval in Ubuntu's system installer. SessionSifu
does not silently elevate privileges.

## Command line

```sh
sessionsifu --save Work
sessionsifu --restore Work
sessionsifu --list
```

The command-line client communicates with the GNOME Shell extension over the
user's session D-Bus. The GNOME integration must therefore be loaded.

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

Because saved launch commands, paths and window titles may contain sensitive
information, protect backups of the SessionSifu configuration directory as you
would other personal application data.

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
dist/sessionsifu_1.1.1_all.deb
updates/sessionsifu_1.1.1_all.deb
updates/latest.json
```

The update package and manifest are committed together so the manifest digest
always identifies the exact downloadable package.

For development and release details, see [CONTRIBUTING.md](CONTRIBUTING.md).
For component boundaries, see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Origin and license

SessionSifu is a GPL-3.0 derivative of Another Window Session Manager. Original
copyright remains with its authors and contributors. See [NOTICE](NOTICE) for
the audited upstream revision and attribution. Smart Auto Move NG was evaluated
as an alternative foundation, but its source code is not included.
