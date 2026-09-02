# SessionSifu documentation

This index describes the current 3.5.17 behavior. Start with the main
[README](../README.md) for installation and compatibility.

## Using SessionSifu

- [Session restoration workflow](RESTORE_GUIDE.md) — named sessions,
  automatic history, previous-desktop recovery, restore preview and platform
  boundaries.
- [Privacy Recall workflow](RECALL_GUIDE.md) — enable, capture, search, browse,
  reopen, pause and delete Recall moments.
- [Troubleshooting](TROUBLESHOOTING.md) — integration, update, restoration,
  screenshot, OCR and shortcut diagnostics.
- [Privacy and local data](PRIVACY.md) — collected fields, storage, encryption,
  exclusions, retention and deletion.

## Design and assurance

- [Architecture](ARCHITECTURE.md) — GNOME/portable components, storage,
  capture/search pipeline and release channel.
- [Recall performance](PERFORMANCE.md) — measured bottlenecks, memory-only
  caches, invalidation rules and regression targets.
- [Recall research and product decisions](RECALL_RESEARCH.md) — comparison
  baseline, feedback themes and deliberate differences from other products.
- [Competitive feature analysis](COMPETITIVE_ANALYSIS.md) — ten adjacent
  products/approaches, feature gaps and the priorities shipped in 3.4.0.
- [Sandboxed workspaces and development options](SANDBOXED_WORKSPACES.md) —
  shipped 3.5.6 capsule foundation, platform feasibility, threat boundaries and
  remaining capsule phases.
- [Security audit](SECURITY_AUDIT.md) — findings, remediation and remaining
  hardening work.
- [Release signing and recovery](RELEASE_SECURITY.md) — maintainer procedure,
  key rotation and compromise response.
- [Code signing policy](../CODE_SIGNING_POLICY.md) — signed artifact scope,
  trusted build requirements, roles and privacy statement.
- [Publishing and distribution](PUBLISHING.md) — GitHub Releases, Ubuntu PPA,
  Snap Store and community package-manager submission status.
- [Roadmap](../ROADMAP.md) — shipped foundation, quality priorities, workspace
  capsules, longer-term research and explicit non-goals.

## Project references

- [Contributing](../CONTRIBUTING.md)
- [Security policy](../SECURITY.md)
- [Code of conduct](../CODE_OF_CONDUCT.md)
- [Brand assets](../branding/README.md)
- [Bundled OCR provenance](../ocr/README.md)

Documentation should describe tested behavior, identify best-effort platform
boundaries and never use real Recall screenshots or session data as examples.
