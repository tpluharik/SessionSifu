# Privacy and local data

SessionSifu has no account, cloud service, analytics SDK, advertising channel or
telemetry upload. Its desktop observations are stored locally. Checking for
updates and downloading releases contacts GitHub; operating systems and package
tools may independently make their own network requests.

## Data inventory

| Feature | Data | Default | Retention |
| --- | --- | --- | --- |
| Current GNOME state | Applications, process launch data, window titles, document paths and layout | Active with GNOME integration | Replaced as windows change |
| Automatic history | Complete restorable session | On | Five successful snapshots |
| Named sessions | Complete restorable session | User action | Until deleted |
| Portable sessions | Applications, executable/arguments, titles, documents and supported layout | User action/history timer | Named: until deleted; history: five |
| Privacy Recall metadata | Sanitized app identity, title, time and layout; document paths only with a separate opt-in | Off | User setting, bounded to 500 entries/30 days |
| Recall previews | Compressed display images on full GNOME integration | Off, separate opt-in | Deleted with entry; changing exclusions purges existing previews |
| Update cache | Downloaded Debian package | Created after update download | Until replaced or manually cleared |
| Logs | Operational messages; some current messages may contain desktop metadata | System journal | Operating-system journal policy |

Session and Recall data are not encrypted by SessionSifu. File permissions are
the current protection on Linux; device encryption and a locked user account
provide additional protection while the computer is off. Open finding
SS-2026-005 tracks stricter modes for all non-Recall session files.

## Storage locations

Full GNOME integration:

```text
~/.config/sessionsifu/currentSession/
~/.config/sessionsifu/history/
~/.config/sessionsifu/sessions/
~/.config/sessionsifu/recall/
~/.cache/sessionsifu/updates/
```

Portable editions:

- Windows: `%APPDATA%\SessionSifu`;
- macOS: `~/Library/Application Support/SessionSifu`;
- Linux: `${XDG_CONFIG_HOME:-~/.config}/sessionsifu-portable`.

## Recall protections and limits

Recall is designed for data minimization, not invisible monitoring:

- capture and screenshot controls are off by default;
- capture state is visible in the top-bar/tray menu;
- application exclusions apply during capture and search;
- file paths are removed unless separately enabled;
- screenshots are skipped while locked or when an excluded application is
  detected;
- screenshot previews stay local, are compressed and are never used for OCR in
  version 2.4;
- searches use metadata only and do not upload queries.

Exclusions are best effort. They match observable application identity, not
individual password fields, private tabs or sensitive regions inside an allowed
application. A timing gap in version 2.4 screenshot exclusions is documented as
SS-2026-004. Until it is fixed, do not enable screenshots on a desktop where an
excluded application may appear unexpectedly.

## Deletion

Use SessionSifu's Recall deletion control to remove Recall metadata and preview
files together. Turning Recall off stops new capture but intentionally retains
existing entries. Named sessions remain until explicitly deleted; automatic
history rolls over after five successful snapshots.

Before manually deleting data, quit the portable application or turn off the
GNOME integration so an active timer does not immediately recreate state. Clear
the update cache independently if downloaded package copies should also be
removed.

Backups, filesystem snapshots, journal archives and synchronized home folders
are outside SessionSifu's control and may retain copies after local deletion.

## Sharing diagnostics safely

Do not publish raw JSON, Recall images or unredacted journal output. They can
contain application names, titles, commands, usernames and document paths. A
safe bug report should state versions and reproduction steps, then include only
the smallest sanitized error excerpt. Security concerns should use the private
path in [SECURITY.md](../SECURITY.md).
