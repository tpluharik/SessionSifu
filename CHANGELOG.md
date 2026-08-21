# Changelog

All notable SessionSifu changes are documented here.

## 1.3.0

- Introduced a dedicated SessionSifu identity based on interlocking yin-yang
  session and restoration shapes.
- Replaced the generic application and top-bar restore icons with matching
  SessionSifu artwork and added a reusable horizontal project logo.
- Added the generated visual concept to the branding sources for future design
  work.
- Prevented rapid automatic or manual snapshots created within the same second
  from overwriting each other by adding millisecond precision while retaining
  compatibility with existing history filenames.

## 1.2.3

- Paces previous-session launches instead of starting every saved application
  concurrently, reducing startup pressure on Wayland, portals and Electron's
  shared GPU process.
- Waits 750 milliseconds after a new window appears before restoring its
  monitor, workspace and geometry.
- Stops all pending application and window restoration after logout, reboot or
  shutdown is confirmed.
- Sends saved file paths only to desktop launchers that declare at least one
  real document MIME type; protocol-only launchers such as Signal are excluded.
- Corrects the previous-session startup delay to use seconds as shown in the
  preferences instead of interpreting the value as milliseconds.

## 1.2.2

- Fixed a GNOME Shell crash when a window closed while its saved maximization
  and geometry were being restored on Wayland.
- Rejects unmanaged windows, removed monitors, invalid geometry and excessive
  workspace indices before calling Mutter window operations.
- Serializes per-window restore callbacks and cancels monitor waits and delayed
  geometry work when a window closes or the extension is disabled.
- Stops recording incomplete windows without a WM class into a `null` session
  folder.

## 1.2.1

- Added document discovery from process arguments and GNOME's recent-file
  database, including explicit documents stored below hidden project folders.
- Added exact window-title matching and most-recent selection for duplicate
  filenames.
- Restores every unique document belonging to an application, including when
  the application is already running.
- Replaced the system-installer update handoff with verified, atomic user-local
  installation of the manager and GNOME integration.

## 1.2.0

- Added best-effort capture of readable regular files exposed by each window
  process and restoration through the application's desktop launcher.
- Added safety filtering for hidden state, system resources, deleted files and
  special descriptors, with a limit of 32 paths per process.
- Added **Turn Off SessionSifu** to the GNOME top-bar menu.
- Updated privacy, architecture and troubleshooting documentation.

## 1.1.1

- Added 30-second and 1-minute automatic snapshot intervals.
- Retained five minutes as the default interval.
- Expanded installation, upgrade, privacy, updater, troubleshooting,
  architecture and development documentation.

## 1.1.0

- Added continuous full-session snapshots with five-file rolling history.
- Added snapshot creation and history restoration to the GTK manager.
- Added a GitHub-backed update manifest and verified Debian package downloads.
- Added detection and replacement of older per-user GNOME integrations.

## 1.0.2

- Improved GNOME extension discovery on first installation.
- Queued extension enablement when GNOME Shell required a new login session.

## 1.0.0

- Initial SessionSifu release for Ubuntu 26.04 and GNOME Shell 50.
- Added the GTK manager, GNOME top-bar integration, session D-Bus API and Debian
  packaging around the inherited session engine.
