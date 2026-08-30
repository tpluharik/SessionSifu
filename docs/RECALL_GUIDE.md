# Privacy Recall workflow

Privacy Recall is SessionSifu's optional local visual timeline. It helps find a
previous application window by time, application, title, opted-in document path
or text recognized in that window's screenshot. It is disabled by default.

The [short visual walkthrough](media/recall-demo.mp4) uses synthetic content;
the animated preview also appears in the main README.

## Enable only what you need

Open **SessionSifu → Privacy Recall** and enable Recall. Metadata capture does
not automatically enable screenshots, file paths, OCR or related matching.
Choose each separately:

1. Enable screenshot previews if visual history is useful.
   Choose **Storage saver (960 px)**, **Readable text (1440 px)** or **High
   detail (1920 px)**. Higher levels make small text easier to inspect and
   recognize, but consume more of the encrypted local quota.
2. Enable local OCR only when screenshot text should become searchable.
3. Enable file paths only when reopening recorded documents is worth recording
   their locations.
4. Configure excluded applications and observable website domains before the
   first visual capture.
5. Choose a retention period and encrypted storage quota.

On supported Linux applications, 3.4.0 first indexes bounded text that the app
already exposes to the desktop accessibility interface. This does not open or
read document files. OCR remains the fallback for visible text that is not
accessible, and screenshot/OCR switches remain independent.

The top-bar or tray menu shows whether Recall is active, paused or currently
saving. **Pause** stops new captures for the chosen duration without deleting
existing history.

## Capture model

Each Recall moment contains bounded desktop metadata. When screenshots are
enabled, SessionSifu stores a compressed display overview and attempts a
separate image for every eligible open window. A window can remain
metadata-only when it is minimized, unmapped, closed during capture, excluded,
over the 64-window limit or unavailable through the platform capture API.
If a user-excluded application is visible, the shared display overview is not
stored because it could contain excluded pixels. Eligible non-excluded windows
continue to receive their own separately rendered previews and OCR indexes.
Recognized private-browsing and protected/remote-content windows are treated the
same way: their window image is omitted and the shared overview is withheld,
without cancelling independent captures of other eligible applications.

### GNOME workspaces and cached previews

From 3.5.8, GNOME session metadata includes all workspaces. Visual capture uses
only currently visible, unobscured screen regions; it never switches workspaces
or forces a hidden window to repaint. After a workspace/focus change settles,
SessionSifu retains eligible previews in a bounded memory cache. A later Recall
moment can reuse those previews for inactive, minimized or obscured windows.

To populate the cache, visit each workspace and bring each desired window to the
front once. A window that has not been visible since the extension was loaded
remains metadata-only. Cached previews are explicitly labeled with their
original capture time in the large viewer and gallery, and the capture summary
reports how many images came from the cache. Their OCR describes the retained
image, which can be older than the current session metadata.
Cached pixels are reused only while the window title still matches their source
context; a changed title/page requires a fresh visible capture.

The cache holds at most 64 previews / 64 MiB (16 MiB per source image) and is
cleared on extension reload/logout, Recall disable, screenshot disable, exclusion
changes or deletion of all history. Short-lived native screenshot staging files use
the owner-private runtime directory and are removed after loading into memory.
Saved Recall previews still pass through normal compression, privacy filtering,
OCR and authenticated encryption.

GNOME image processing, OCR, encryption and indexing run outside GNOME Shell.
The encrypted vault stores the accepted preview and OCR coordinates; the
private OCR working image is deleted immediately after recognition.

## Search and browse

Version 3.4.0 adds a timeline scrubber and groups adjacent near-identical
screens into scenes when **Group similar scenes** is enabled. Open a scene to
browse every separately captured window in the filmstrip. Bookmarks,
collections and notes are stored inside the encrypted moment and are searchable
locally.

**Related search** now requires a user-selected local SentenceTransformers
model directory. It never downloads a model. If the optional runtime/model is
missing, diagnostics explain the issue and normal title/file/accessibility/OCR
search continues.

Use **OCR diagnostics** to inspect indexing and **Reindex OCR** to process only
the selected encrypted moment. This does not recapture the screen or weaken
app/site exclusions. **Ask history** returns a local extractive summary with the
exact saved moments used as evidence.

Encrypted export/import is available from the portable manager and the
`--export-archive` / `--import-archive` options. Archives require a passphrase
of at least 12 characters, are authenticated and size bounded, and Recall is
re-encrypted for the destination device.

Open **Browse Recall Snapshots…** from the top-bar/tray menu, or use the
customizable search shortcut (`Ctrl+Alt+Space` by default).

- Enter a title, application, opted-in filename or visible screenshot word.
- Narrow results by application or date when needed.
- **Visual** mode uses screenshot cards; **Compact** mode favors denser text.
  The choice is remembered. Selecting a result keeps a large preview visible
  beside the result list. The first 24 results are rendered immediately; use
  **Load 24 more results** to extend the list without decoding the entire
  encrypted image history at once.
- The filmstrip below the preview contains every separately captured window,
  followed by the display overview. A single click selects a window, a double
  click or Space opens the full gallery, and the arrow keys move between
  images.
- **Fit**, **100%** and **Zoom to match** control screenshot size. `+`, `-` and
  `0` provide equivalent keyboard controls.
- On a touchpad, use two fingers to pan an enlarged screenshot and pinch to
  zoom. `Ctrl` plus two-finger vertical scrolling is the zoom fallback on
  systems that do not expose native pinch events. Zooming preserves the
  current center instead of jumping back to the image origin.
- OCR results show a match counter. **Previous match** and **Next match** move
  through recognized occurrences, center the selected word and pulse its
  highlight. The result card and large detail viewer use the same matched
  screenshot and OCR coordinates; selecting a result opens that screenshot
  directly before the rest of the filmstrip.
- Each preview clearly identifies an exact window image, display-overview
  fallback, metadata-only capture, disabled screenshots or compositor limits.
- Capture details show how many windows were expected, eligible, captured,
  missing, excluded or protected, so a partial moment is not mistaken for a
  complete desktop record.
- **Open** asks the recorded application to reopen that window's validated file
  or observable URL when the platform and application support it.

Search reuses a bounded ephemeral in-memory index until the encrypted vault
changes. Queries run outside the interface thread, and stale results from rapid
typing are discarded. Queries, decrypted text, vector caches and rendered
highlights are not written to a persistent search database.

## Czech and English OCR

Version 3.4.0 ships pinned Czech and English fast Tesseract models in the Debian
package, signed in-app update and portable artifacts. SessionSifu selects both
models together so mixed-language application interfaces can be searched.
Recognition is local; the model never sends screenshots or text to a service.

OCR applies only while the OCR option is enabled and only to new captures. It
does not retroactively process older metadata-only or screenshot-only moments.
Small fonts, antialiasing, unusual typefaces and low contrast can still cause
missed or inaccurate words.

## Exclude and delete

Changing the excluded-application list removes affected encrypted records
because previously stored pixels cannot be reliably redacted. Website filters
work only when the browser exposes an observable URL.

Use the result menu or manager to delete one moment, an application's history,
a website, entries before a selected time or the entire vault. Turning Recall
off stops capture but intentionally keeps existing history until it is deleted.

## Important limits

SessionSifu does not capture audio, clipboard contents, keystrokes, shell
history or arbitrary application memory. Sensitive-text detection and website
filtering are best-effort safeguards, not guarantees. Keep screenshots off for
workflows where display capture itself is inappropriate, and use full-disk
encryption plus a locked user session.

For failure-specific checks, see [Troubleshooting](TROUBLESHOOTING.md). For the
complete data inventory and deletion semantics, see
[Privacy and local data](PRIVACY.md).

## Restore preview and local integrations

Restoring a named or automatic session now opens a preview first. Every
application is selected by default and can be unchecked; Cancel and an empty
selection launch nothing. The preview lists window, open-file and deep-link
counts without executing the saved configuration.

Trusted desktop launchers can use `sessionsifu --local-api-stdio` (or
`sessionsifu-portable --local-api-stdio`) for bounded status, Recall search and
restore-plan queries. The protocol is one JSON object per line on inherited
stdin/stdout. It does not listen on a network socket and intentionally has no
restore, delete, update or raw-image method; see the
[architecture](ARCHITECTURE.md) for the trust boundary.
