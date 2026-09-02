# Session restoration workflow

This guide describes the restoration behavior shipped in SessionSifu 3.5.17.
It covers named sessions, rolling automatic history and the optional previous-
desktop restore on GNOME, KDE Plasma, Windows, macOS and portable Linux.

## Choose the right kind of restore

| Source | Retention | Best use |
| --- | --- | --- |
| Named session | Until you delete it | A reusable work, study or project layout |
| Automatic history | Five newest completed snapshots | Recovering a recent desktop arrangement |
| Previous desktop | Latest logout/shutdown records | Rebuilding the last desktop after login |

All three restore application windows and supported public state. They are
separate from Privacy Recall: Recall is an opt-in visual/search history and does
not silently launch applications.

## Save a named session

1. Arrange the applications, workspaces and displays you want to keep.
2. Open SessionSifu, enter a name under **Save current desktop**, and choose
   **Save**. On GNOME you can also save from the top-bar menu.
3. Confirm that the new entry appears under **Saved sessions**.

Automatic history uses the interval selected in the manager and retains only
the five newest completed snapshots. A save already in progress is never
overlapped by another timer callback.

## Preview and restore

1. Select **Restore** beside a named session or automatic snapshot.
2. Review the application groups. Clear anything you do not want to launch or
   rearrange.
3. Confirm the preview. Canceling, or confirming an empty selection, launches
   nothing.

The preview is an execution boundary: only the selected application identities
may be restored. SessionSifu then handles one application group at a time and
paces window changes so a slow launcher cannot create concurrent compositor
work.

If an application is already running, SessionSifu reuses its matching windows
and applies the saved workspace, monitor, geometry and supported window state.
It does not open a duplicate instance merely to move an existing window. Saved
documents that are not already open may still be passed to an application that
declares support for their real file type.

## Restore the previous desktop after login

Enable **Restore previous desktop after login** only when you want automatic
recovery. SessionSifu waits for its startup delay, rejects helper and command-
only processes, then restores visible desktop applications through the same
bounded queue used by manual restoration.

If automatic retry protection is active after a desktop restart, use
**Restore previous desktop now** in the manager or **Restore Previous Desktop**
in the GNOME top-bar menu. This bypasses only the automatic retry timer; the
application, selection and compositor safety checks remain active.

Successfully handled previous-session records are retired after the restore.
Records that could not be handled remain available for another attempt. This
prevents old successful entries from accumulating into a large duplicate launch
burst on a later login.

## What can and cannot return

SessionSifu can restore observable application processes, supported local
documents and public window state. The exact geometry/workspace result depends
on the platform adapter and compositor capabilities documented in the main
[compatibility table](../README.md#compatibility).

Application-private memory is outside this boundary. Browser tabs, unsaved
editor buffers, terminal jobs, virtual desktops not exposed by the operating
system and protected application content return only when the application has
its own recovery feature or a supported SessionSifu deep-return adapter.

## Verify a restore

- Check that each selected application has either reopened or reused a matching
  existing window.
- On GNOME/KDE, verify workspace and display placement after all windows have
  finished opening; geometry is deliberately not applied in parallel.
- Confirm restored documents individually. An untitled or unobservable file
  cannot be reconstructed generically.
- If the result is incomplete, keep the saved session and collect the current-
  boot diagnostics before retrying.

See [Troubleshooting](TROUBLESHOOTING.md#restore-reports-success-but-windows-do-not-move-or-reopen)
for recovery steps and [Architecture](ARCHITECTURE.md) for the queue, validation
and platform boundaries.
