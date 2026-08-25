# SessionSifu roadmap

This roadmap describes the product after version 3.5.0. It separates shipped
behavior from future work; it is not a release-date promise. Privacy and
operating-system security boundaries take precedence over feature parity.

## Shipped foundation — 3.4.0

SessionSifu now combines session restoration with an encrypted, opt-in visual
history on GNOME 50, KDE Plasma, general Linux, Windows and macOS:

- named sessions and five-entry rolling automatic session history;
- up to 64 separately captured application-window screenshots per Recall
  moment, display overviews, local Czech/English OCR and exact-word highlights;
- optional strictly offline semantic embedding search. The model is selected
  by the user, is never downloaded during capture/search and related search is
  independently off by default;
- per-image OCR diagnostics and explicit reindexing of a selected moment;
- crash-safe, owner-private restore journals with per-action outcomes and retry;
- a scrubber-style timeline, near-duplicate scene grouping and full window
  filmstrips with touchpad panning/pinch zoom;
- encrypted bookmarks, collections and private notes;
- deep-return adapters for LibreOffice, JetBrains IDEs, VS Code, Obsidian and
  observable browser URLs, in addition to validated generic files;
- monitor identity/topology capture and bounded geometry reconciliation when
  displays are reordered, replaced or removed;
- local extractive “Ask history” answers with explicit snapshot citations;
- an opt-in, read-only MCP server over inherited stdio only—no listener and no
  launch, delete, update or other write-capable tool;
- password-encrypted, size-bounded export/import of sessions and Recall data,
  re-encrypted with the destination device's local vault key; and
- existing app/site exclusions, protected-context redaction, pause controls,
  quotas, granular deletion, restore preview and signed GNOME updates.

These P0, P1 and P2 items were selected from the competitive analysis and
shipped together in 3.4.0 so the user-visible workflow and the underlying data
model remain consistent across supported editions.

## Search responsiveness shipped — 3.5.0

- bounded process-memory caches for decrypted records, FTS rows, OCR typo
  tokens and optional semantic document vectors;
- automatic index invalidation after encrypted records change;
- background GTK/Qt queries with stale-generation suppression; and
- 24-result incremental rendering, compact-mode image avoidance and one
  downscaled thumbnail per visible visual result.

The cache is an optimization, not a new storage format: no plaintext search
database or embedding file is written.

## Next: quality and trust

1. Build a synthetic multilingual OCR benchmark covering mixed scaling, small
   fonts, dark mode and common application chrome; publish regressions without
   including user screenshots.
2. Add previewable monitor-mapping controls for unusual docks, portrait
   displays and mixed-scale layouts instead of relying only on automatic
   matching.
3. Expand application adapters only where a documented public restoration API
   exists; browser and terminal integrations remain separate opt-ins.
4. Complete screen-reader labels, focus order, high-contrast and reduced-motion
   review in the GTK and Qt Recall browsers.
5. Add signed/notarized native portable updates, SBOMs and provenance for
   Windows, macOS and Linux artifacts.

## Planned and research

- Adopt a standard Wayland session-management protocol when it is implemented
  dependably across compositors and toolkits.
- Evaluate an optional local visual embedding model separately from text
  embeddings; it must preserve the same exclusion and deletion semantics.
- Add a preview/diff step before importing a transfer archive and before retrying
  a restore after the source session changed.
- Explore user-controlled synchronization of encrypted archives. There will be
  no mandatory SessionSifu account or implicit cloud upload.
- Expand localization from English/Czech to German and other contributor-owned
  translations.

## Continuous engineering gates

- no telemetry, advertising use, hidden upload, audio, keystroke or clipboard
  capture;
- screenshots, OCR, semantic search, file paths, MCP and transfer remain
  distinct opt-ins;
- bounded parsing, image work, retention, memory and subprocess execution;
- exclusions and lock state checked before and after asynchronous capture;
- private permissions, symlink rejection, authenticated encryption and atomic
  replacement for user data;
- restore commands never pass through a shell; and
- docs and diagnostics distinguish tested support from best effort.

## Explicit non-goals

SessionSifu does not serialize arbitrary process memory, bypass Wayland/macOS
permissions, infer private browser tabs or restore terminal commands. A
Recall-like local aid is not permission for covert employee monitoring.

Discuss future scope with the repository's
[feature-request form](https://github.com/tpluharik/SessionSifu/issues/new?template=feature_request.yml).
