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

## A restored application does not reopen its document

Open-file capture works only while the application exposes the file through
`/proc/<pid>/fd`. Some applications close the descriptor after reading and keep
the document only in private memory; SessionSifu cannot observe that state.
Check whether the application provides its own reopen, recent-file or crash
recovery option.

SessionSifu also intentionally ignores hidden state, system resources, deleted
files and applications whose desktop entry does not accept file or URI
arguments.

## SessionSifu was turned off from the top bar

Open SessionSifu from the application grid and select **Enable**. If GNOME says
a new login is required, log out and back in once.

## Restoration reopens windows but not their content

This is expected for applications that do not expose recovery support.
SessionSifu reconstructs processes and GNOME window state; application-private
state such as browser tabs, editor buffers or terminal jobs remains the
application's responsibility.

## An update check fails

Confirm that GitHub and `raw.githubusercontent.com` are reachable. SessionSifu
rejects redirects outside the official repository, oversized packages and any
package whose size or SHA-256 digest differs from `updates/latest.json`.

## Diagnostic logs

GNOME Shell extension messages are available in the user journal:

```sh
journalctl --user -b | grep -i sessionsifu
```

For a live extension error, inspect GNOME Shell messages around the time the
extension was enabled or a snapshot was requested.
