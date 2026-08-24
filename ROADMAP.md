# SessionSifu roadmap

This roadmap describes product direction after 3.2.0. It is ordered by user
impact, privacy risk and platform feasibility; it is not a release-date promise.
Operating-system security boundaries take precedence over feature parity.

Status labels used below:

- **Shipped** — available in the current stable source and signed update;
- **Next** — intended for the next focused development cycle;
- **Planned** — accepted direction that still needs design or platform work;
- **Research** — useful goal without a dependable cross-platform API yet.

## Shipped foundation — 3.2.0

SessionSifu currently provides:

- GNOME Shell 50 session capture and restoration for Ubuntu 26.04;
- named sessions and five-entry rolling automatic history;
- best-effort document reopening and conservative window-layout restoration;
- portable Windows, macOS, KDE Plasma and generic Linux managers;
- signed, repository-scoped user-local updates for the GNOME edition;
- Privacy Recall as an off-by-default, encrypted local visual timeline;
- separately captured and searchable images for up to 64 eligible windows;
- per-window OCR search, screenshot word highlighting and gallery navigation;
- adaptive master-detail Recall browsing with a large preview, every captured
  window in a filmstrip, compact/visual layouts, keyboard zoom and OCR match
  navigation;
- bounded 960, 1440 and 1920-pixel screenshot quality profiles shared across
  the GNOME and portable editions;
- app/site exclusions, timed pauses, quotas, capture diagnostics and granular
  deletion; and
- pinned Czech and English OCR data in installation and update artifacts.

The [feature overview](README.md#features),
[architecture](docs/ARCHITECTURE.md), and
[privacy guide](docs/PRIVACY.md) define the exact shipped boundary.

## 1. Recall correctness and capture health — Next

Make capture failures and weak OCR easier to understand without exposing user
content in logs.

- Show per-capture counts for eligible, captured, excluded, unavailable and
  OCR-indexed windows.
- Add a local OCR diagnostics view with active language models, Tesseract
  version, recognition duration and confidence distribution.
- Build a synthetic Czech/English UI-text corpus covering scaling, dark mode,
  small fonts and mixed-language windows.
- Add an explicit retry for metadata-only or partially captured moments without
  silently weakening exclusions.

Completion means users can distinguish permission, compositor, exclusion,
timeout and recognition problems from the UI alone.

## 2. Restore preview and crash-safe journal — Next

Add a dry-run page showing which applications, files and windows will be
started, reused, moved or skipped. Record restoration operations in a bounded
owner-private journal so interrupted restores can be inspected and safely
retried.

Completion requires no saved command to reach a shell, no automatic overwrite
of a newer desktop state, and a clear partial-success report.

## 3. Application-specific document adapters — Planned

Add opt-in adapters for applications whose public APIs can restore more than a
generic file launch, beginning with LibreOffice, VS Code and JetBrains IDEs.
Document-based macOS applications should use supported restoration APIs where
available.

Adapters must declare exactly what they observe and restore. Unsaved buffers,
private tabs and terminal commands remain the application's responsibility
unless an explicit, reviewed integration exists.

## 4. Stable multi-monitor topology mapping — Planned

Record monitor identity, scale, rotation and relative topology, then reconcile
saved layouts when displays are missing, renamed or rearranged. Provide a
previewable mapping instead of moving windows off-screen.

Completion requires tests for docking/undocking, mixed scaling, portrait
rotation and a single-display fallback.

## 5. Verified native updates for portable editions — Planned

Extend the signed update model to Windows, macOS and portable Linux artifacts.
Every implementation must be repository-scoped, size-limited,
signature/checksum verified, atomic and rollback-capable without invoking a
system package manager.

The current GNOME `.deb` updater is the reference design; portable editions
continue to use checksummed GitHub Release downloads until this milestone is
complete.

## 6. Release trust and reproducibility — Planned

Add Windows Authenticode signing, Apple Developer ID signing/notarization,
Linux provenance attestations, SBOMs and fully hashed transitive dependency
locks. Publish enough metadata to audit which source tree produced every
artifact.

These controls complement, rather than replace, SessionSifu's Ed25519 update
signature and pinned CI actions.

## 7. Standard Wayland session management — Research

Adopt a standardized Wayland session-management protocol when dependable
support exists across compositors, toolkits and applications. Prefer that path
over compositor automation while retaining truthful capability reporting and
safe fallbacks.

Until then, GNOME full integration uses its version-matched Shell extension and
KDE Plasma uses `kdotool` where available. Generic Wayland builds do not claim
window geometry they cannot observe.

## 8. Browser and terminal cooperation — Research

Explore browser profile/session and terminal workspace APIs that can restore
user-selected state. Private/incognito content, shell history, commands and
terminal output must never be captured by inference or enabled through the
general Recall switch.

Any integration requires a separate per-application opt-in, a data preview and
a documented deletion path.

## 9. Accessibility, localization and keyboard workflows — Planned

Complete screen-reader labels, keyboard-only operation, focus order, reduced
motion and high-contrast checks. Introduce a translation workflow beginning
with English, Czech and German, including localized OCR diagnostics rather than
localized model assumptions.

The manager, Recall search popup, tray/top-bar menus and restore preview must be
usable without a pointer.

## 10. Encrypted export and user-controlled sync — Planned

Support portable encrypted archives for backup or transfer between the same
user's devices. Export and sync stay off by default, require an explicit
destination and key decision, preview the included data, and never depend on a
mandatory SessionSifu cloud account.

Cross-device import must treat session launch data as active configuration and
require review before restoration.

## Continuous engineering gates

Every roadmap item remains subject to these release gates:

- no telemetry, advertising use or hidden upload of session/Recall data;
- screenshot, OCR, file-path and related-match controls remain separate opt-ins;
- bounded parsing, capture, retention, memory and subprocess execution;
- exclusion and lock-state checks before and after asynchronous image work;
- regression tests for GNOME Shell stability and applications closing during
  capture or restoration;
- private local permissions, symlink rejection and atomic replacement; and
- documentation that distinguishes tested support from best effort.

The open hardening record is maintained in
[docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md).

## Explicit non-goals

SessionSifu does not plan to serialize arbitrary application memory, bypass
Wayland/macOS permission models, capture audio or keystrokes, restore private
browser tabs by inference, or provide covert employee monitoring. “Recall-like”
means a user-controlled local activity aid, not feature parity at the cost of
privacy.

## Contributing to the roadmap

Use the repository's
[feature-request form](https://github.com/tpluharik/SessionSifu/issues/new?template=feature_request.yml)
to discuss scope and platform APIs before implementation. Useful proposals
include a concrete workflow, affected platforms, permission boundary, failure
behavior and a testable completion condition.
