# Privacy and local data

SessionSifu has no account, cloud service, analytics SDK, advertising channel or
telemetry upload. Its desktop observations are stored locally. Checking for
updates and downloading releases contacts GitHub; operating systems and package
tools may independently make their own network requests.

The Czech and English OCR models shipped since 3.1.9 are static local resources.
They do not contact a recognition service and no screenshot or recognized text
is transmitted for OCR.

## Data inventory

New optional surfaces in 3.4.0 follow the same local-only boundary:

- semantic search is off by default, loads only an explicit local model in
  forced offline mode and keeps its bounded document-vector cache in process
  memory rather than persisting embeddings;
- Ask history is extractive and cites its local source snapshots;
- MCP runs only with `--mcp-stdio`, inherits pipes, opens no listener and has
  read-only tools;
- explicit transfer uses Scrypt and AES-GCM, validates sizes/paths and
  re-encrypts Recall with the destination vault key; and
- bookmarks, collections, notes, OCR diagnostics and restore journals remain
  owner-private local data. Journals contain outcomes, not screenshots or a
  replayable shell command.

| Feature | Data | Default | Retention |
| --- | --- | --- | --- |
| Current GNOME state | Applications, process launch data, window titles, document paths and layout | Active with GNOME integration | Replaced as windows change |
| Automatic history | Complete restorable session | On | Five successful snapshots |
| Named sessions | Complete restorable session | User action | Until deleted |
| Portable sessions | Applications, executable/arguments, titles, documents and supported layout | User action/history timer | Named: until deleted; history: five |
| Privacy Recall vault | Encrypted app identity, title, time, layout, bounded accessibility text and optional document paths/OCR | Off | User retention plus 500-entry/30-day and storage-quota bounds |
| Recall previews | AES-GCM encrypted compressed display and eligible window images | Off, separate opt-in | Deleted with entry; changed exclusions delete affected entries |
| Workspace capsules | AES-GCM encrypted application IDs, selected backend/network policy and explicit folder mappings | User action | Until manifest deletion; separate profile data requires its own explicit deletion |
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
~/.config/sessionsifu/capsules/
~/.cache/sessionsifu/updates/
```

Portable editions:

- Windows: `%APPDATA%\SessionSifu`;
- macOS: `~/Library/Application Support/SessionSifu`;
- Linux: `${XDG_CONFIG_HOME:-~/.config}/sessionsifu-portable`.

Capsule filenames are hashes rather than plaintext capsule names. Capsule
manifests never include browser/editor credential databases, cookies or opaque
profile contents. A separate profile directory is created only when a reviewed
profile adapter launches; it remains local and is removed only by the explicit
**Delete profile data** action.

## Recall protections and limits

For the user-facing sequence behind these controls, see the
[Privacy Recall workflow](RECALL_GUIDE.md).

Recall is designed for data minimization, not invisible monitoring:

- capture and screenshot controls are off by default;
- capture state is visible in the top-bar/tray menu;
- application exclusions apply during capture and search and delete affected
  encrypted records when changed;
- observable website-domain exclusions apply when a browser exposes its URL;
- file paths are removed unless separately enabled;
- screenshots are skipped while locked; when a user-excluded application is
  visible, its metadata/window image and the shared display image are omitted,
  while unobscured allowed-window previews can still be saved;
- GNOME's cross-workspace preview cache is memory-only, limited to 64 previews
  and 64 MiB, and cleared on extension restart, disable or exclusion changes.
  Owner-private runtime staging files exist only while native screenshot output
  is transferred into memory. Cached images keep their original capture time
  and pass through the same sensitive-content filtering and encryption as live
  images when added to a Recall moment;
- OCR preprocessing uses a private temporary grayscale image that is deleted
  immediately after local Tesseract recognition; only the compact preview and
  accepted OCR words/coordinates enter the encrypted vault;
- SessionSifu's built-in self-exclusion removes its windows from searchable
  metadata but does not suppress display previews merely because the manager or
  Recall browser is open; user-configured exclusions suppress shared display
  previews without stopping safe per-window capture;
- screenshots, OCR and related-match ranking require separate opt-ins;
- likely passwords, payment-card numbers and security codes discard a capture
  when default-on sensitive filtering recognizes them;
- search creates an ephemeral in-memory SQLite FTS5 index and never uploads a
  query, preview or OCR result;
- supported Linux builds prefer bounded visible AT-SPI names/text before OCR;
  the adapter visits at most 384 accessibility nodes per matched window,
  records at most 64 KiB and never reads document contents through that path;
- the full GNOME integration keeps a process identifier only in its short-lived
  owner-private capture file so it can match an AT-SPI application; that identifier
  is omitted from the encrypted Recall record;
- recognized private-browsing, protected/DRM and remote-display contexts omit
  their individual image and suppress the shared display overview while other
  independently rendered eligible windows remain capturable;
- text search is indexed per window. A result exposes only that window's app,
  title, opted-in file targets and optional window-image OCR; full-display OCR
  is returned separately;
- accepted OCR words retain bounded normalized rectangles and confidence values
  inside the same AES-GCM record solely to highlight a matching word; the app
  writes neither plaintext coordinates nor rendered highlight images to disk;
- exact window previews are limited to 64 per capture, 960 pixels on the longest
  edge and quality-65 JPEG; display images use a 1,280-pixel/quality-70 bound;
- a shared desktop image is discarded if any excluded application is present;
  separately rendered images of eligible windows can still be retained on
  GNOME and portable editions;
- if an older shared screenshot contains an application that is now excluded,
  SessionSifu withholds the complete preview and its OCR even when another
  non-excluded window in the same entry remains searchable;
- timed pause controls, quota pruning, unchanged-frame deduplication and the
  capture status row make recording state and failures visible.

The optional stdio integration API is read-only and same-user. It returns
bounded search metadata and restore plans over inherited pipes, never image
bytes or encryption keys, and does not open a socket. As with the session D-Bus,
it is not a defense against malware already running as the same user.

Exclusions and sensitive detection are best effort. Generic Linux window APIs
do not reliably expose a browser's private-tab state, current URL or individual
password widgets. Rapid GNOME transitions are rechecked throughout capture and
discarded, but screenshots should remain off where display-wide capture is
unsuitable. Portable capture also depends on the platform's screen-recording
permission and may return metadata only when permission is denied. Minimized or
unmapped windows may not expose a renderable surface and therefore remain
searchable metadata without a window image.

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
