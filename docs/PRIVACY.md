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
| Privacy Recall vault | Encrypted app identity, title, time, layout and optional document paths/OCR | Off | User retention plus 500-entry/30-day and storage-quota bounds |
| Recall previews | AES-GCM encrypted compressed display images | Off, separate opt-in | Deleted with entry; changed exclusions delete affected entries |
| Update cache | Downloaded Debian package | Created after update download | Until replaced or manually cleared |
| Logs | Structural operational messages; failures may identify an application | System journal | Operating-system journal policy |

Named and automatic session JSON remains protected by operating-system access
controls rather than application encryption. Recall records, OCR and previews
are AES-256-GCM encrypted in version 3.0. GNOME prefers an OS credential-store
key and reports a degraded state if it must use a private `0600` fallback key.
Portable builds prefer Windows Credential Locker, macOS Keychain or the
available Linux Secret Service/KWallet backend. They retain an existing
owner-private key, and use one as a clearly documented fallback when no usable
credential backend exists. Full-disk encryption and a locked user account
remain recommended.

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
- application exclusions apply during capture and search and delete affected
  encrypted records when changed;
- observable website-domain exclusions apply when a browser exposes its URL;
- file paths are removed unless separately enabled;
- screenshots are skipped while locked or when an excluded application is
  detected before capture, after capture or after compression;
- SessionSifu's built-in self-exclusion removes its windows from searchable
  metadata but does not suppress display previews merely because the manager or
  Recall browser is open; user-configured exclusions still block previews;
- screenshots, OCR and related-match ranking require separate opt-ins;
- likely passwords, payment-card numbers and security codes discard a capture
  when default-on sensitive filtering recognizes them;
- search creates an ephemeral in-memory SQLite FTS5 index and never uploads a
  query, preview or OCR result;
- timed pause controls, quota pruning, unchanged-frame deduplication and the
  capture status row make recording state and failures visible.

Exclusions and sensitive detection are best effort. Generic Linux window APIs
do not reliably expose a browser's private-tab state, current URL or individual
password widgets. Rapid GNOME transitions are rechecked throughout capture and
discarded, but screenshots should remain off where display-wide capture is
unsuitable. Portable capture also depends on the platform's screen-recording
permission and may return metadata only when permission is denied.

## Deletion

Recall can delete one snapshot, everything from an application or observable
website, entries before a selected time, or the complete vault. Metadata, OCR
and preview ciphertext are removed together. Turning Recall off stops new
capture but intentionally retains existing entries. Named sessions remain until
explicitly deleted; automatic history rolls over after five successful saves.

Before manually deleting data, quit the portable application or turn off the
GNOME integration so an active timer does not immediately recreate state. Clear
the update cache independently if downloaded package copies should also be
removed.

Backups, filesystem snapshots, journal archives and synchronized home folders
are outside SessionSifu's control and may retain copies after local deletion.

## Sharing diagnostics safely

Do not publish decrypted Recall exports, session JSON or unredacted journal output. They can
contain application names, titles, commands, usernames and document paths. A
safe bug report should state versions and reproduction steps, then include only
the smallest sanitized error excerpt. Security concerns should use the private
path in [SECURITY.md](../SECURITY.md).
