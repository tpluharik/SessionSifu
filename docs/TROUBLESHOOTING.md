# Troubleshooting

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

Privacy Recall is intentionally disabled by default. Enable it explicitly in
the manager, confirm the top-bar or tray control reports **Active**, then use
**Capture Now**. Check that the application is not matched by an exclusion.
GNOME entries are stored under `~/.config/sessionsifu/recall/`; portable builds
use the `recall/` folder below their platform-specific SessionSifu data path.

Turning Recall off pauses capture without deleting earlier entries. Use
**Delete All** in the manager to remove the timeline permanently.

Changing **Excluded applications** takes effect on existing history searches
immediately. Matching application names, window titles and opted-in file paths
are removed before results are built; the underlying entry expires through the
normal retention policy or can be removed with **Delete All**.

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

## Diagnostic logs

GNOME Shell extension messages are available in the user journal:

```sh
journalctl --user -b | grep -i sessionsifu
```

For a live extension error, inspect GNOME Shell messages around the time the
extension was enabled or a snapshot was requested.
