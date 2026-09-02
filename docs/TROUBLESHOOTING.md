# Troubleshooting

## Wayland returns to a black screen while restoring a session

Upgrade to SessionSifu 3.5.9 or newer. Earlier releases could allow several
newly launched windows to change monitor, geometry, workspace and focus at the
same time. A crash-recovery directory could also retain older records with
changing window titles, making one login restore far more windows than were
actually open. On GNOME/Mutter this could terminate the compositor without an
application core dump.

Version 3.5.9 serializes and paces window changes, caps automatic recovery to
the newest saved window count, never forces focus across workspaces, clamps
geometry to the live monitor work area, and pauses automatic recovery for ten
minutes after an attempt. Manual restore stays available during this pause.
The pause prevents the same restore from immediately repeating if GNOME Shell
is restarted.

If the affected desktop cannot remain open long enough to update, disable the
extension from a text console, log back in, update SessionSifu, then enable the
integration again:

```sh
gnome-extensions disable sessionsifu@local
```

The fix does not delete named sessions or Recall history. After updating, use
the restore preview to deselect applications that you do not want to relaunch.

## The control panel does not open after an in-app update

Version 3.4.0 introduced several support modules, while an updater embedded in
older releases copied only the main launcher and Recall engine. A partially
applied update therefore failed at startup with
`ModuleNotFoundError: restore_journal`; session restoration and Recall
finalization were unavailable for the same reason.

Install SessionSifu 3.4.1 or newer from the complete Debian package. The repair
release keeps the restore journal in the two-file compatibility payload, so it
boots through the old update path, and its current updater installs every
support module before atomically activating the launcher. If the legacy updater
omitted optional modules, the Updates section displays **Repair Installation**
and accepts a signed package of the same version. Existing sessions and encrypted
Recall records under `~/.config/sessionsifu/` are not removed.

To confirm this exact failure before repairing, run:

```sh
journalctl --user -b --no-pager | grep -A4 -B2 'restore_journal'
```

## The extension does not exist

Open SessionSifu and select **Install & Enable**. The application installs the
extension bundle shipped inside the Debian package. Log out and back in if the
manager says a new login is required.

## The top-bar icon is missing after an upgrade

Open SessionSifu and select **Update Integration**. A per-user GNOME extension
overrides the system extension, so upgrading only the Debian files may leave an
older per-user copy active until SessionSifu replaces it. Log out and back in
after the replacement.

Check the installed integration with:

```sh
gnome-extensions info sessionsifu@local
```

## Automatic history is empty

Confirm that **Continuously save this desktop** is enabled. The first automatic
snapshot is created shortly after the extension starts. You can select **Save
Now** to test the capture path immediately.

Automatic files should appear in:

```sh
ls -l ~/.config/sessionsifu/history/
```

If the manager shows an integration-version warning, update the integration and
start a new login session before testing snapshots.

## Privacy Recall is empty

If **Capture Now** reports that `CaptureRecallNow` is unknown after an upgrade,
the application and the copy still loaded by GNOME Shell are different versions.
SessionSifu 2.5.0 and later reload the extension automatically when capture is
requested; the Integration row also exposes **Reload Integration**. Log out and
back in only if GNOME cannot complete that live reload.

Recall metadata should complete quickly even when open-file capture is enabled.
Optional JPEG encoding, OCR and encryption continue in separate helpers; under
sustained load SessionSifu may skip a preview while retaining the corresponding
searchable metadata snapshot. This is expected overload protection, not lost
history. Successful finalization moves records and previews into encrypted
`recall/vault/*.ssrec` and `*.ssimg` envelopes; temporary JSON/JPEG/PNG files are
removed whether finalization succeeds or fails. The **Capture diagnostics** row
shows the last state, reason, duration, preview count, vault size and key backend.

Privacy Recall is intentionally disabled by default. Enable it explicitly in
the manager, confirm the top-bar or tray control reports **Active**, then use
**Capture Now**. Check that the application is not matched by an exclusion.
GNOME entries are stored under `~/.config/sessionsifu/recall/`; portable builds
use the `recall/` folder below their platform-specific SessionSifu data path.

Turning Recall off pauses capture without deleting earlier entries. Use
per-card deletion, application/website/time deletion or **Delete All** in the
manager to remove the timeline permanently.

Changing **Excluded applications** takes effect immediately and deletes affected
encrypted entries because their pixels cannot be safely redacted. Website
filters apply only when the browser exposes an observable URL; private browsing
detection is not universally available on Linux.

If OCR results are absent, confirm **Capture screenshot previews** and **Index
screenshot text with local OCR** are both enabled and that `tesseract --version`
works. OCR applies to new captures and cannot be added retroactively. Search
accepts exact words, useful word prefixes and small OCR substitutions; a word
that Tesseract omitted entirely still cannot be found. SessionSifu 3.1.9 and
newer include verified Czech and English recognition data in the installation
and signed in-app update package; no separate `tesseract-ocr-ces` package is
needed. The models are selected together for mixed-language interfaces and run
locally. OCR is never inferred from the main Recall switch. If diagnostics report
the private fallback key, install/configure a Secret Service-compatible keyring
and restart SessionSifu before enabling visual capture.

For a system installation, verify the bundled models with:

```sh
tesseract --tessdata-dir /usr/share/sessionsifu/tessdata --list-langs
```

For an in-app user-local update, use
`~/.local/share/sessionsifu/tessdata` instead. The output should include `ces`
and `eng`. If the directory is absent, install/update to 3.1.9 or newer rather
than downloading an unverified model manually.

New captures normally contain display previews and a separate image for each
eligible open window. An individual card can still say that no preview is
available when the window was minimized/unmapped, the platform denied screen
recording, the 64-window safety limit was reached, or privacy checks discarded
its pixels. Older entries are not retroactively upgraded; they continue to use
an in-memory crop of their display preview. If every new entry is metadata-only,
check **Capture screenshot previews**, session-lock state, application
exclusions and the last **Capture diagnostics** reason.

Use **Browse N windows** on a Recall card to inspect each captured window
separately. The gallery lists linked window images first and display overviews
after them; Previous/Next does not decrypt images until they are selected.
Version 3.1.8 and newer preprocess a private OCR-only copy with grayscale contrast,
bounded upscaling and sharpening, then deletes it immediately. The compressed
encrypted preview itself is not enlarged. Version 3.1.7 and newer store
confidence-filtered OCR word coordinates with new
captures and outline the words matching the current query. Older captures keep
their searchable OCR text but cannot be highlighted retroactively because they
contain no word coordinates. A title/application/file match also has no visual
box unless the same query appears in the screenshot OCR.

The Recall browser searches automatically after a short typing pause. Results
are listed newest first; use application/date filters instead of a separate
timeline slider. **View screenshots** opens every window image belonging to the
saved moment and starts on the matched window. Less common copy and privacy
deletion actions are under **More**.

## The Recall search shortcut does not open

The shortcut is independent of Recall capture, so it can search existing
history while capture is paused. Open SessionSifu, ensure **Global Recall
search shortcut** is enabled, select **Change…**, press a combination not
already reserved by Ubuntu or another extension, and use **Open Search** to
verify the popup target. SessionSifu applies the setting immediately through
GNOME's standard Custom Shortcuts service. You can also verify the
**SessionSifu Recall Search** entry under Ubuntu **Settings → Keyboard → View
and Customize Shortcuts → Custom Shortcuts**.

On KDE/Wayland or general Linux, approve the XDG desktop-portal shortcut
request. On macOS, allow SessionSifu under **Privacy & Security → Input
Monitoring**. Windows reports a conflict when another program already owns the
shortcut. Portable editions accept Ctrl/Alt/Shift/Super plus Space, A-Z or 0-9.
The top-bar/tray **Browse Recall Snapshots…** action remains available as a
fallback.

## A capsule opens the existing Signal instance

Update to 3.5.15 or newer. Signal releases after 7.80 stopped honoring the
historical `--user-data-dir` switch, so SessionSifu now blocks Signal in the
legacy profile backend. All legacy profile-only launches are blocked because
they are not OS containers. Choose **Isolated Flatpak capsule**, enter `signal`
(or `org.signal.Signal`), and review the permission plan. The Flatpak must
already be installed; SessionSifu never replaces the official Signal package
or installs an unreviewed package silently.

The Flatpak capsule uses separate config, data, cache and state paths and
cannot fall back to the host executable. It may therefore show Signal's first
run/linking screen. This is expected and proves it did not reuse the existing
local Signal identity. It is not network anonymity: use **Require offline
launch** to deny networking, understanding that Signal cannot communicate in
that mode.

## A restored application does not reopen its document

SessionSifu checks process descriptors, explicit process arguments and GNOME's
recent-file database. The filename must appear in the window title for the
recent-file fallback. Files absent from all three sources cannot be observed;
check whether the application provides its own reopen or crash-recovery option.

Untitled and unsaved in-memory documents, deleted files and applications whose
desktop entry does not declare a document MIME type cannot be restored
generically. Protocol-only launchers are deliberately excluded even when their
command line contains `%U`.

## SessionSifu was turned off from the top bar

Open SessionSifu from the application grid and select **Enable**. If GNOME says
a new login is required, log out and back in once.

## GNOME Shell or Wayland restarted during restoration

Upgrade to SessionSifu 1.2.3 or newer and select **Update Integration**, then
log out and back in. Version 1.2.3 retains the stale-window safeguards from
1.2.2, paces application launches, waits for new windows to initialize and
stops restore work as soon as logout, reboot or shutdown is confirmed.

If a restart still occurs, capture the current-boot journal before logging out:

```sh
journalctl --user -b -o short-iso _COMM=gnome-shell
```

Include the lines containing `GNOME Shell crashed` and the following stack trace
in a bug report.

## Restoration reopens windows but not their content

This is expected for applications that do not expose recovery support.
SessionSifu reconstructs processes and GNOME window state; application-private
state such as browser tabs, editor buffers or terminal jobs remains the
application's responsibility.

## An update check fails

Confirm that GitHub and `raw.githubusercontent.com` are reachable. SessionSifu
rejects redirects outside the official repository, oversized packages and any
package whose size or SHA-256 digest differs from `updates/latest.json`.

In-app updates require `dpkg-deb` to extract the verified archive, but do not
use the package manager to install it. Updated files are placed below
`~/.local/bin`, `~/.local/share` and `~/.config/autostart`. Install the Debian
package manually once if the initial runtime dependencies are not present.

Version 2.5 authenticates the manifest with Ed25519 before checking package
origin, size and SHA-256. Never bypass a signature, expiry or rollback error.
Versions 2.4 and older need one manual 2.5 package installation because they do
not understand the signed update channel.

## Version 3.0.1 does not start after an in-app update

Version 3.0.1's user-local updater omitted the new Recall engine module, so the
launcher can exit with `ModuleNotFoundError: recall_engine`. Install 3.1.1 from
the GitHub Release with `sudo apt install ./sessionsifu_3.1.1_all.deb`; this
recovery does not remove saved sessions or Recall history. Version 3.1.1 installs
its private Python module before activating the launcher and tests the resulting
user-local program during every Debian build.

## A session came from another computer or person

Do not restore it. Session JSON contains executable and argument information and
must be treated as active configuration. Version 2.5 no longer interprets saved
arguments as shell syntax, but restore still executes the recorded program. Use
only sessions produced by the trusted local installation. If a
foreign session was copied into `~/.config/sessionsifu/sessions/`, move it out
without opening/restoring it and report unexpected behavior through
[SECURITY.md](../SECURITY.md).

## Check local data permissions

Version 2.5 migrates all owned POSIX SessionSifu directories to `0700` and
regular files to `0600`, without following symlinks. Keep the data below your
private home configuration directory and use device encryption. Avoid recursive
permission commands: they
can damage ownership or make data more accessible. See [PRIVACY.md](PRIVACY.md)
for the complete storage map and deletion guidance.

## Diagnostic logs

GNOME Shell extension messages are available in the user journal:

```sh
journalctl --user -b | grep -i sessionsifu
```

For a live extension error, inspect GNOME Shell messages around the time the
extension was enabled or a snapshot was requested.
