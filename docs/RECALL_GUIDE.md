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

The top-bar or tray menu shows whether Recall is active, paused or currently
saving. **Pause** stops new captures for the chosen duration without deleting
existing history.

## Capture model

Each Recall moment contains bounded desktop metadata. When screenshots are
enabled, SessionSifu stores a compressed display overview and attempts a
separate image for every eligible open window. A window can remain
metadata-only when it is minimized, unmapped, closed during capture, excluded,
over the 64-window limit or unavailable through the platform capture API.

GNOME image processing, OCR, encryption and indexing run outside GNOME Shell.
The encrypted vault stores the accepted preview and OCR coordinates; the
private OCR working image is deleted immediately after recognition.

## Search and browse

Open **Browse Recall Snapshots…** from the top-bar/tray menu, or use the
customizable search shortcut (`Ctrl+Alt+Space` by default).

- Enter a title, application, opted-in filename or visible screenshot word.
- Narrow results by application or date when needed.
- **Visual** mode uses screenshot cards; **Compact** mode favors denser text.
  The choice is remembered. Selecting a result keeps a large preview visible
  beside the result list.
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
  highlight.
- Each preview clearly identifies an exact window image, display-overview
  fallback, metadata-only capture, disabled screenshots or compositor limits.
- **Open** asks the recorded application to reopen that window's validated file
  or observable URL when the platform and application support it.

Search rebuilds an ephemeral in-memory index. Queries, decrypted text and
rendered highlights are not written to a persistent search database.

## Czech and English OCR

Version 3.2.1 ships pinned Czech and English fast Tesseract models in the Debian
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
