# SessionSifu roadmap

This roadmap describes the product after version 3.5.13. It separates shipped
behavior from future work; it is not a release-date promise. Privacy and
operating-system security boundaries take precedence over feature parity.

## Shipped foundation — 3.5.13

SessionSifu now combines session restoration with an encrypted, opt-in visual
history on GNOME 50, KDE Plasma, general Linux, Windows and macOS:

- named sessions and five-entry rolling automatic session history;
- up to 64 separately captured application-window screenshots per Recall
  moment, display overviews, local Czech/English OCR and exact-word highlights;
- GNOME cross-workspace preview reuse with a bounded memory-only cache, original
  capture timestamps and no unsafe hidden-window repainting or workspace jumps;
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
- direct Workspace Capsule setup from both tray implementations, with saved
  environment selection, save-before-launch validation, reviewed Signal
  profile support and a scoped live monitor of launched applications.

The session, Recall and retrieval foundations were delivered incrementally
through 3.5.13. The user-visible workflow and underlying data model remain
consistent across supported editions, while platform adapters report their
real capabilities instead of implying parity.

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

## Workspace capsules shipped — 3.5.6

The first **workspace capsule** foundation is now shipped: a saved launch plan
that can optionally carry a dedicated application profile, explicit resource
permissions and a reproducible launch manifest. “Capsule” is an umbrella UX,
not a claim that every mode is a security sandbox.

Three visibly different modes are presented:

| Mode | User promise | Isolation level |
| --- | --- | --- |
| Profile capsule | Reopen selected applications with separate supported profiles and workspace data | Convenience boundary; not a security sandbox |
| Sandboxed capsule | Launch compatible applications with deny-by-default access and explicit files/network/devices | OS-enforced where the selected backend supports it |
| Virtual workspace | Boot a disposable or persistent guest workspace and restore its SessionSifu manifest | VM boundary; higher storage and startup cost |

The detailed feasibility and threat-model study is in
[Sandboxed workspaces](docs/SANDBOXED_WORKSPACES.md). Any implementation must
show the selected backend, effective permissions, persistent paths and known
escape hatches before launch. Unsupported controls fail closed; SessionSifu
must never silently relabel an ordinary process as sandboxed.

### Delivered capsule foundation

- versioned AES-GCM-encrypted manifests with hashed filenames, atomic writes,
  private directories, ownership checks, symlink rejection and bounded input;
- a visible fail-closed preflight that reports the real backend, boundary,
  commands, warnings and effective network/file/clipboard permissions;
- structured argument arrays only—capsule launches never use a shell;
- reviewed browser/editor profile adapters labelled as convenience separation;
- independent-instance launches for reviewed adapters, with Firefox
  no-remote, browser/editor new-window requests and per-capsule profile roots;
- a Linux pilot for already-installed Flatpak application IDs, including an
  optional per-launch network-off request and portal-only file policy;
- a reviewable Windows Sandbox `.wsb` exporter with clipboard, audio/video,
  printers and writable host mappings disabled; and
- explicit deletion of capsule manifests separately from profile data.

The GTK and Qt applications expose creation, review and launch. The command
line additionally supports listing, deleting and `.wsb` export for automation.

### Next P0 — validation and adapter hardening

1. Introduce a small adapter contract for cooperative applications to export
   and import public state. An adapter declares its supported versions and
   receives only user-approved files or URLs.
2. Add automated end-to-end negative tests proving that denied
   files, network access and host services remain unavailable for every
   security-labelled backend.
3. Add explicit encrypted-storage quotas, manifest export redaction and
   migration/recovery diagnostics without ever copying profile credentials.
4. Apply existing Recall app/site exclusions before a future capsule capture
   can associate session or visual-history records with a capsule.
5. Add a human-readable preflight diff between the saved policy and effective
   platform capabilities before updating an existing capsule.

### Next P1 — useful platform expansion

1. Add Flatpak portal document grants selected from the capsule interface and
   display package-level permissions separately from per-launch restrictions.
2. Expand profile adapters only where the application publishes a stable,
   documented profile interface; add adapter/version compatibility diagnostics.
3. Add Windows Sandbox provisioning and explicit export folders without ever
   making a host mapping writable by default.
4. **macOS virtual-workspace prototype:** evaluate Apple's Virtualization
   framework for an optional Linux or macOS guest capsule. SessionSifu does not
   claim that macOS App Sandbox can be imposed on arbitrary third-party apps.

### P2 — reproducible and portable workspaces

1. Add a human-readable workspace manifest with application IDs, minimum
   versions, document roles, monitor intent and hashes for SessionSifu-owned
   configuration—never bundled credentials or opaque application databases.
2. Add preview/diff before import, restore or capsule update, with an auditable
   explanation of files, permissions and applications that will change.
3. Support user-chosen encrypted synchronization of capsule manifests and
   exports. There will be no mandatory account, hidden upload or automatic
   merging of decrypted data.
4. Add signed community adapter packages with a narrow declarative schema;
   executable third-party hooks remain disabled unless separately reviewed and
   trusted by the user.
5. Add suspend/resume only for VM backends that expose supported snapshots.
   Generic desktop-process checkpointing is not a substitute: CRIU does not
   currently support complete X application restoration and Wayland/GPU state
   is an even stronger boundary.

### P3 — exploration after the capsule foundation

- A local activity graph connecting sessions, Recall moments, documents and
  capsule launches without creating a cloud identity graph.
- Optional local visual embeddings after a published quality, memory and model
  provenance benchmark.
- A contributor SDK and compatibility laboratory using synthetic applications,
  fake documents and disposable VMs.
- Accessibility-first natural-language actions that always resolve to a visible
  restore/capsule preview before execution.
- Energy-aware capture scheduling based on idle state, battery policy and
  thermal pressure while preserving the user's retention settings.

## Other planned work

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

## Platform boundary summary

| Platform | Practical near-term backend | Deliberate limitation |
| --- | --- | --- |
| Linux | Flatpak plus XDG portals for packaged apps; isolated cooperative profiles elsewhere | Raw bubblewrap policy is not exposed as a casual “secure” toggle; policy construction is security-critical |
| Windows | Reviewable Windows Sandbox files; MSIX/AppContainer experiments for cooperative apps | The new process-sandbox API is experimental and Windows Sandbox deletes guest contents on close |
| macOS | Separate cooperative profiles and optional Virtualization.framework guests | App Sandbox is chosen and signed by an app's developer; SessionSifu cannot retrofit it onto arbitrary apps |
| All platforms | Encrypted manifests, explicit exports and public application adapters | No arbitrary process-memory serialization, invisible credential copying or silent privilege fallback |

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

SessionSifu also does not market environment-variable profile separation as a
security boundary, grant a sandbox broad home-directory access for convenience,
or promise transparent checkpoint/restore of arbitrary graphical applications.

Discuss future scope with the repository's
[feature-request form](https://github.com/tpluharik/SessionSifu/issues/new?template=feature_request.yml).
