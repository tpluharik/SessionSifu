# SessionSifu roadmap

SessionSifu 2.0 establishes a shared session format, portable desktop manager,
platform adapters and release automation. The following eleven improvements are
ordered by safety and user impact rather than promised release date.

## 1. Signed and notarized release artifacts

Add Windows code signing, Apple Developer ID signing/notarization and Linux
artifact attestations. Keep SHA-256 sums and publish reproducible build metadata
so users can verify both origin and contents.

## 2. Verified native updates for portable editions

Extend the existing verified updater to Windows, macOS and portable Linux
bundles. Downloads must be repository-scoped, size-limited, checksum-verified,
atomic and rollback-capable without invoking a system package manager.

## 3. Standard Wayland session-management protocol

Adopt the standardized Wayland session-management protocol as support lands in
KWin, Mutter, Qt, GTK and applications. Prefer it over compositor-specific
automation, while retaining safe fallbacks for older desktops.

## 4. Application-specific document restoration

Add opt-in adapters for LibreOffice, VS Code, JetBrains IDEs and document-based
macOS applications. Use supported application APIs and recent-document stores
instead of guessing from titles whenever possible.

## 5. Stable multi-monitor topology mapping

Record monitor identity, scale, rotation and relative topology. Restore windows
conservatively when displays are missing or rearranged, with an interactive map
instead of moving windows off-screen.

## 6. Browser and terminal session bridges

Integrate browser profile/session APIs and terminal workspace exports where
available. Never capture private tabs, shell history or commands without an
explicit per-application opt-in.

## 7. Restore preview, diff and crash-safe journal

Show what applications, files and windows will change before restoration. Add
an append-only operation journal so interrupted restores can be inspected,
retried or rolled back without corrupting saved sessions.

## 8. Accessibility, localization and keyboard workflows

Complete screen-reader labels, full keyboard navigation, high-contrast icon
checks and localized user-facing text. Start with Czech, English and German and
provide a documented translation workflow.

## 9. Performance and security hardening

Move slow process and window inspection off UI/compositor threads, add bounded
parallelism and fuzz the JSON/update parsers. Introduce platform sandbox and
permission audits plus automated long-running capture/restore stress tests.

## 10. Encrypted export and optional user-controlled sync

Support portable encrypted session archives for backup or transfer between the
same user's devices. Sync must remain off by default, end-to-end encrypted and
independent of any mandatory hosted SessionSifu service.

## 11. Privacy-first local activity recall

Explore an optional, Recall-style activity timeline that helps users find and
resume earlier work through periodic desktop snapshots, on-device OCR and local
semantic search. The feature must be disabled by default and show a persistent,
unambiguous indicator whenever capture is active.

Design it around data minimization and a published threat model: let users
exclude applications, windows, websites, displays and private/incognito
contexts; detect and redact password fields and other sensitive content where
platform APIs permit; support an immediate pause control; and provide short,
configurable retention with deletion by time range, application or website.
Snapshots, extracted text and indexes must be encrypted at rest with keys held
in the operating-system credential store. Processing stays on the device by
default, with no advertising use, model-training upload or hidden telemetry.
Any export or synchronization requires a separate explicit opt-in, end-to-end
encryption and a clear preview of exactly what will leave the device. Security
review, storage quotas, crash-safe deletion and automated privacy regression
tests are release requirements rather than follow-up work.

SessionSifu 2.2 implements the first, metadata-only phase behind a feature flag
that is off by default. It provides exclusions, bounded retention, local search,
deletion, a dedicated keyboard search popup and an active/pause indicator
without screenshots, OCR or semantic indexing. Exclusions redact matching apps
from existing search results as well as new captures. Those higher-risk visual
features remain roadmap work until the encryption and security requirements
above are satisfied on every platform.

## Contributing to the roadmap

Use the repository's feature-request form to discuss scope and platform APIs
before implementation. A roadmap entry describes direction, not a promise to
bypass operating-system security boundaries or claim unsupported fidelity.
