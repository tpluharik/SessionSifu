# Changelog

All notable SessionSifu changes are documented here.

## 2.5.2

- Fixed Recall previews being discarded whenever SessionSifu's manager or
  search window was visible. The built-in self-exclusion now suppresses only
  SessionSifu metadata, rather than the complete screenshot capture.
- Preserved fail-closed screenshot blocking for user-configured privacy
  exclusions such as messaging or password-manager applications.
- Reworded empty preview cards and screenshot settings to distinguish skipped
  or unavailable previews from intentional metadata-only capture.
- Added a standalone exclusion-policy regression test and updated privacy
  documentation.

## 2.5.1

- Added a live recording badge to the GNOME top-bar icon while Privacy Recall
  metadata or screenshot previews are being saved.
- Added matching saving feedback to the portable Windows, macOS, KDE and Linux
  tray icon, tooltip and Recall menu action.
- Made capture activity reference-counted and failure-safe so overlapping
  metadata/preview work cannot flicker or leave the indicator stuck on.
- Added GNOME activity-state and cross-platform tray integration regression
  checks to the release build.

## 2.5.0

- Removed shell interpretation from GNOME fallback restore. Saved applications
  now launch only through a bounded, validated argument array.
- Added Ed25519-signed, expiring stable update manifests with an embedded public
  key, rollback protection, repository confinement and size/SHA-256 checks.
- Migrated SessionSifu configuration directories to `0700` and files to `0600`.
- Closed Recall screenshot exclusion/lock timing gaps and purge previews when
  screenshot capture is disabled.
- Removed unbounded regular expressions and dynamic matching calls from GNOME
  Shell, and rate-limited state-changing D-Bus operations.
- Pinned GitHub Actions to immutable commits and portable build inputs to exact
  versions; expanded security and permission regression checks.
- Reduced sensitive restore/save logging and updated all security documentation.

## 2.4.0

- Replaced the single full-size Recall PNG with one bounded JPEG preview per
  connected display. A separate helper crops, downsizes and compresses the
  images after GNOME Shell completes its asynchronous desktop grab.
- Added application-window crops to metadata search results: matching app,
  window-title and opted-in file keywords now show the relevant window area
  from its display preview, without storing duplicate per-app images or using
  OCR.
- Added schema-1 Recall compatibility while emitting schema 2 with a bounded
  display manifest, private atomic preview replacement and complete cleanup of
  legacy, raw and per-display image files.
- Reduced Shell-side image work to one non-overlapping capture and moved image
  decoding/compression out of GNOME Shell's process.

## 2.3.3

- Fixed Recall **Capture Now** after an in-app or package upgrade by detecting
  the stale live D-Bus API, safely cycling only the SessionSifu extension and
  retrying capture after the current integration reconnects.
- Added a clear **Reload Integration** state instead of exposing the raw D-Bus
  `UnknownMethod` error when GNOME Shell still has older extension code loaded.
- Kept logout/login as a fallback only when GNOME rejects or cannot complete the
  live extension reload.

## 2.3.2

- Kept logging safe before GNOME preferences are initialized, so the real
  open-file performance smoke test behaves identically on clean Ubuntu 26.04
  release runners and installed desktops.
- Restored the Debian release path after the new Recall latency test exposed
  that pre-initialization edge case in CI.

## 2.3.1

- Made Recall metadata writes start immediately through GIO's asynchronous
  atomic-replacement API instead of waiting for a low-priority Shell idle slot.
- Reduced open-file discovery to bounded scans and removed redundant synchronous
  filesystem probes across hundreds of descriptors and recent-document entries.
- Made screenshot preview encoding independent from metadata completion, with
  overlap protection that drops a preview rather than delaying later snapshots.
- Cached sanitized Recall summaries and throttled retention pruning to avoid
  repeatedly reading and scanning the complete history during normal capture.
- Kept restore-time file validation, exclusion enforcement, private permissions
  and local-only screenshot handling unchanged.

## 2.3.0

- Replaced the unreliable Ubuntu extension-only Recall accelerator with a
  GNOME Custom Shortcut entry managed by both the app and the extension. The
  configured accelerator now launches the search surface through GNOME's
  standard media-keys service and remains customizable in SessionSifu.
- Added an explicit **Browse Recall Snapshots…** action to the GNOME top-bar
  and portable tray menus.
- Added an optional, separately gated full-desktop PNG preview for GNOME Recall
  entries. Screenshots remain off by default, use private file permissions and
  are skipped while the session is locked or an excluded application is visible.
- Rebuilt the GTK Recall popup as a searchable screenshot-card browser. Search
  matches application names, window titles and separately opted-in file paths;
  it does not perform OCR.
- Added screenshot thumbnails to Recall results in the main manager and ensured
  screenshot assets are pruned and deleted with their metadata entries.
- Changing the excluded-app list now removes existing screenshot previews because
  pixels captured before a new exclusion cannot be safely redacted afterward.

## 2.2.1

- Fixed the GNOME/Ubuntu Recall search shortcut being silently unregistered
  whenever Recall capture was paused. Existing Recall history can now be
  opened from the shortcut independently of new capture.
- Added an in-app keyboard-capture editor for the GNOME shortcut and a direct
  **Open Search** test action. Changes are applied immediately by GNOME Shell.
- Re-register the GNOME keybinding when its accelerator changes and accept it
  while the overview or a Shell popup is open.
- Added a validated, editable cross-platform shortcut for Windows, macOS, KDE
  and portable Linux. Native registration and tray/local labels update without
  restarting SessionSifu.
- Added shortcut normalization and GSettings mutation regression tests.

## 2.2.0

- Applied application exclusions during every Recall query as well as capture,
  so newly excluded applications, their window titles and opted-in file paths
  are immediately redacted from existing history search results.
- Added a dedicated, keyboard-oriented Privacy Recall search popup to GNOME,
  KDE, Windows, macOS and portable Linux editions.
- Added the opt-in `Ctrl+Alt+Space` global Recall search shortcut while Recall
  is active: GNOME uses a Shell keybinding, Windows uses `RegisterHotKey`, macOS
  uses an exact modifier/key event monitor and Linux requests compositor access
  through the XDG GlobalShortcuts portal.
- Added tray/top-bar search actions and an application-local shortcut fallback.
- Kept stored Recall history searchable while new capture is paused.

## 2.1.0

- Added experimental Privacy Recall as a pure feature flag that is disabled by
  default on GNOME, KDE, Windows, macOS and portable Linux editions.
- Added bounded local activity timelines containing sanitized application,
  window, workspace, monitor and geometry metadata without screenshots,
  clipboard data, keystrokes or network upload.
- Added application exclusions, configurable one-hour through seven-day
  retention, searchable history, permanent deletion and a separate opt-in for
  full open-file paths.
- Added user-only Recall directories/files on POSIX platforms and atomic writes
  in the portable engine.
- Added persistent GNOME top-bar and portable tray status/pause controls while
  Recall capture is active.
- Kept screenshot capture, OCR and semantic indexing unavailable until
  OS-backed encryption and sensitive-content exclusion receive security review.

## 2.0.0

- Added a shared, validated session model and atomic five-snapshot storage for
  Windows, macOS, KDE Plasma and portable GNOME builds.
- Added a Win32 backend for application, document and window-geometry capture
  and restoration.
- Added a macOS backend using System Events and the public `open` command, with
  explicit Accessibility-permission diagnostics.
- Added a KDE Plasma 6 backend using `kdotool` for native Wayland window and
  virtual-desktop handling, with `wmctrl` fallback on X11.
- Added a generic Linux/GNOME portable fallback, while retaining the existing
  GNOME Shell 50 extension as the full-fidelity Wayland backend.
- Added a shared Qt manager and system-tray menu, portable command line, named
  sessions and configurable automatic snapshots.
- Added PyInstaller packaging for Windows x64, macOS arm64/x64 and Linux
  x64 alongside the existing GNOME Debian package.
- Added a GitHub Actions pipeline that tests all target operating systems,
  builds release artifacts and publishes tagged releases with SHA-256 sums.
- Added a public ten-item roadmap and expanded architecture, installation,
  privacy and contribution documentation for the new platform family.

## 1.3.1

- Fixed the GNOME top-bar icon appearing as a plain white circle.
- Rebuilt the symbolic yin-yang mark from Shell-safe filled paths without SVG
  masks or a closed outer ring, preserving the transparent half at 16 pixels.

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
