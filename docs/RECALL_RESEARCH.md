# Recall research and product decisions

This note records the external products and user feedback considered for
SessionSifu's Privacy Recall design. It is a design reference, not a claim of
feature parity.

## Windows Recall baseline

Microsoft Recall periodically records visible screen activity, associates it
with time and applications, indexes recognized text, presents a chronological
timeline and can return to the captured application or content. Its current
design is opt-in, local, encrypted and protected by Windows Hello. Microsoft
also provides app/site filters, pause controls and retroactive deletion.

- [Microsoft Recall user guide](https://support.microsoft.com/en-us/windows/retrace-your-steps-with-recall-aa03f8a0-a78b-4b3e-b0a1-2eb8ac48701c)
- [Filtering apps, websites and sensitive information](https://support.microsoft.com/en-US/Windows/ai/ai-features/filtering-apps-websites-and-sensitive-information-in-recall)
- [Recall security and privacy architecture](https://blogs.windows.com/windowsexperience/2024/09/27/update-on-recall-security-and-privacy-architecture/)

Windows Recall's screen-history model is not the same as saving every open
window. SessionSifu keeps the chronological desktop context but additionally
links a separately captured image to every eligible renderable window. This
makes an individual window the primary search and preview unit.

## Repeated feedback themes

Independent reviews and user discussions repeatedly identify three practical
problems: search can be broad or inaccurate, small/weak thumbnails make visual
recognition harder, and users cannot safely assume that automatic sensitive
content filtering catches everything. Reviewers also noted that recording or
filter status needs to say clearly what is happening rather than merely showing
a generic state.

- [Ars Technica: what Recall fixed and what remains](https://arstechnica.com/gadgets/2025/04/in-depth-with-windows-11-recall-and-what-microsoft-has-and-hasnt-fixed/)
- [Laptop Mag: extended Recall review](https://www.laptopmag.com/laptops/windows-laptops/life-with-microsoft-recall-i-spent-weeks-testing-windows-11s-most-controversial-feature/)
- [PCWorld: sensitive information filter test](https://www.pcworld.com/article/2870013/windows-recall-still-screenshots-sensitive-data-at-times-test-shows.html)
- [Windows 11 community discussion about real-world Recall use](https://www.reddit.com/r/Windows11/comments/1u9kok7/is_there_anyone_here_who_uses_windows_recall_do/)

SessionSifu's corresponding decisions are:

- index title, application, opted-in files and OCR per window rather than only
  searching one desktop-wide text blob;
- show the exact encrypted window image when available and retain a display
  crop only as a compatibility fallback;
- keep screenshot capture, OCR and related matching as separate opt-ins;
- treat sensitive detection as a best-effort discard guard, never as a privacy
  guarantee;
- keep visible active/saving/paused state, bounded retention and granular
  deletion; and
- apply exclusions both when recording and when searching old history.

## Open alternatives

[OpenRecall](https://github.com/openrecall/openrecall) demonstrates a
cross-platform local-first approach based on periodic screenshots, OCR and
semantic search. [Screenpipe](https://docs.screenpi.pe/vs-recall) combines local
screen/audio history with OCR, accessibility-derived text and an API-oriented
automation model. Both show the usefulness of local processing and searchable
visual history, but they also reinforce the cost and privacy exposure of a
continuous raw capture stream.

SessionSifu therefore uses shorter-lived plaintext intermediates, authenticated
encryption at rest, explicit size/count/retention limits, no cloud model, no
audio, no clipboard or keystroke capture, and no persistent plaintext search
database. Accessibility-derived content could improve accuracy in the future,
but only behind a separate permission and with an explicit per-application
policy.

## Platform implementation boundary

On GNOME, `Shell.Screenshot` supplies the display image while Mutter's
`Meta.WindowActor` render content supplies occlusion-free per-window images.
The relevant platform APIs are:

- [GNOME Shell focused-window screenshot API](https://gnome.pages.gitlab.gnome.org/gnome-shell/shell/method.Screenshot.screenshot_window.html)
- [Mutter `Meta.WindowActor.paint_to_content`](https://gnome.pages.gitlab.gnome.org/mutter/meta/method.WindowActor.paint_to_content.html)
- [GNOME Shell texture composition](https://gnome.pages.gitlab.gnome.org/gnome-shell/shell/type_func.Screenshot.composite_to_stream.html)

Window actors can preserve the last rendered frame even when obscured, but a
minimized, destroyed or not-yet-mapped window may have no capturable surface.
Such a window remains in searchable metadata and is shown without an exact
preview. Portable builds similarly depend on native screen-recording permission
and window-handle support.
