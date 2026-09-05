# Session restoration workflow

This guide describes the restoration behavior shipped in SessionSifu 3.5.20.
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
paced queue used by manual restoration. On GNOME/Wayland, the queue continues
through all eligible application groups, with eight seconds between groups.
Previous-desktop records are deduplicated and capped at the newest recorded
window count, with a defensive maximum of 32 records per application. Excess
and unavailable records remain on disk. A launched application has up to
30 seconds to become running with a window; timeouts retain its records and
do not block subsequent applications. Named manual sessions retain their
selected records rather than using the historical-record pruning rules.

If automatic retry protection is active after a desktop restart, use
**Restore previous desktop now** in the manager or **Restore Previous Desktop**
in the GNOME top-bar menu. This bypasses only the automatic retry timer; the
application, selection and compositor safety checks remain active.

Successfully handled previous-session records are retired after the restore.
Records that could not be handled remain available for another attempt. This
prevents old successful entries from accumulating into a large duplicate launch
burst on a later login. A record updated during recovery is not deleted.
The queue records the application in flight before launching it. After an
interruption, automatic recovery pauses for ten minutes and holds that specific
application for 24 hours; other applications remain eligible at the next login.
Legacy timestamps from before this checkpoint mechanism use only the ten-minute
pause, so yesterday's marker cannot block today's desktop. Expiry permits the
next requested restore; it does not launch a retry timer in the background.

The manager's **Restore progress** row updates while the queue runs and reports
paused, interrupted, failed and finished attempts. The final count includes
unavailable, deferred and failed records. Queue completion confirms that launch
requests were processed; it does not prove that an application recovered every
document or private state. A second restore request cannot overlap the active
queue. Disabling the integration cancels pending restore work.

### GNOME compositor-operation coordination

Version 3.5.20 uses one shared queue for SessionSifu launch requests, window
placement and native Recall screenshots, including requests from separate UI
and restore objects. A screenshot keeps its slot until its native callback
returns; JavaScript does not pretend a timed-out native operation has ended.
Privacy and window-lifetime checks run again when queued work actually starts.
This serializes SessionSifu's own operations, not every application's rendering
or other GNOME extensions.

New-window callbacks wait for RUNNING state (at most 30 seconds) and cannot
reuse mappings from an expired restore. A previous-session record is retained
if no matching window layout can be applied. Normal restore and Recall options
remain unchanged; this update does not disable automatic restoration.

The September 5 report showed GNOME Shell shutting down during restoration,
followed by client display-connection failures and an AMD driver use-after-free
warning during teardown. Those later errors do not establish the initiating
cause. The concurrency and lifecycle defects above are regression-tested, but
the tests do not prove the hardware-specific shutdown is eliminated. No live
crash reproduction or kernel configuration changes are part of release testing.

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
