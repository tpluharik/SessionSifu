# Competitive feature analysis

This analysis was refreshed on 25 August 2026 from product documentation and
public source repositories. It compares user workflows, not code quality or
security certification. “Local” means the core history can remain on the local
machine; it does not imply identical key protection or zero optional network
features.

## Ten adjacent approaches

| Product or approach | Visual timeline | Search/OCR | Resume or restore | Privacy controls | Useful lesson for SessionSifu |
| --- | --- | --- | --- | --- | --- |
| [Windows Recall](https://support.microsoft.com/en-US/Windows/Ai/Ai-Features/retrace-your-steps-with-recall) | Active-screen snapshots and timeline | Text and visual/related matching | Jump back to supported content; interact with detected text/images | Opt-in, app/site filters, sensitive filter, pause/delete, Windows Hello | Make timeline, capture state, filtering and return actions legible |
| [OpenRecall](https://github.com/openrecall/openrecall) | Cross-platform screenshot history | Local OCR and searchable history | Returns to a recorded moment rather than reconstructing a desktop | Open source and local-first | Keep a portable implementation and transparent storage model |
| [screenpipe](https://github.com/mediar-ai/screenpipe) | Local screen history, optionally audio | OCR plus accessibility-derived content; developer integrations | API/workflow oriented | Local-first controls vary by configured workflow | Prefer accessibility text before OCR and expose a narrow local API |
| [ActivityWatch](https://docs.activitywatch.net/en/latest/) | Activity/time events, not a full screenshot archive by default | Event/window-title queries | No complete session restoration | Open source, local data and watcher choice | Lightweight metadata remains valuable when images are unavailable |
| [TimeSnapper](https://timesnapper.com/) | Periodic screenshot journal | Visual review; product editions determine search depth | Evidence for recovering work, not window-layout replay | Local storage, retention choice and optional encryption | Make retention/storage understandable and browsing fast |
| [macOS Resume](https://support.apple.com/guide/mac-help/reopen-windows-apps-quickly-mchlp1039/mac) | No general visual history | No cross-app OCR timeline | Apps reopen their own windows/documents when they cooperate | Native OS/app state boundary | Prefer public app restoration APIs over memory inference |
| [KDE Plasma session management](https://docs.kde.org/stable5/en/plasma-workspace/kcontrol/kcmsmserver/) | No Recall-style screenshot timeline | No desktop-wide OCR timeline | Restores supported login-session applications | Desktop-native policy | Report compositor capability honestly and avoid private automation |
| [Another Window Session Manager](https://github.com/nlpsuge/gnome-shell-extension-another-window-session-manager) | Session snapshots, not visual history | Session metadata | Strong GNOME window/workspace restoration | Local extension state | Proven GNOME base; harden lifecycle and make restore previewable |
| [Smart Auto Move](https://github.com/khimaros/smart-auto-move) | No visual timeline | Window matching rather than content search | Rule-based placement of application windows | Local GNOME extension state | Stable identity matching is as important as raw geometry |
| [DMTCP](https://dmtcp.sourceforge.io/) / [CRIU](https://criu.org/Main_Page) | No user-oriented visual timeline | No desktop content search | Process checkpoint/restore under constrained conditions | Low-level, workload-specific boundary | Arbitrary memory restore is not a safe portable desktop promise |

The original Rewind/Limitless desktop recorder is intentionally not counted as
an active competitor: the original service ended in 2025. Its historical lesson
— powerful continuous capture can disappear with a service — still reinforces
SessionSifu's open format, local storage and absence of a mandatory account.

## Feature position in 3.4.0

SessionSifu is unusual because it combines two related but separate jobs:

1. a restorable session model for applications, opted-in files and supported
   window layout; and
2. an off-by-default encrypted visual history whose primary unit is an
   individual application window rather than only the active display.

Version 3.4.0 implements the P0, P1 and P2 priorities identified above:

- **Search quality:** bounded accessibility text is indexed before OCR, while
  Czech/English per-window OCR remains the fallback.
- **Return quality:** search results retain validated file, URL, VS Code and
  Obsidian targets.
- **Trustworthy capture:** every moment records expected, eligible, captured,
  missing, excluded and protected counts.
- **Privacy clarity:** recognized private/protected windows and the shared
  overview are withheld without cancelling safe independent window captures.
- **Safe restoration:** the user previews and deselects applications before any
  launch.
- **Extensibility without a daemon:** trusted tools get a read-only stdio API;
  there is no listening service or write-capable API method.
- **Genuine related search:** an explicitly selected local embedding model can
  rank concepts offline; the older lexical-overlap approximation was removed.
- **Diagnosable OCR:** every moment records OCR health and can be reindexed
  deliberately without rebuilding or exposing the entire vault.
- **Recoverable restoration:** an owner-private atomic journal records each
  restore action, outcome and retry source.
- **Timeline organization:** scene grouping, bookmarks, collections and notes
  make a long visual history navigable.
- **Return and layout quality:** LibreOffice/JetBrains/browser adapters and
  multi-monitor reconciliation improve return to a useful workspace.
- **Private interoperability:** cited local Ask, read-only MCP stdio and
  password-encrypted transfer archives expose useful workflows without a
  SessionSifu cloud account.

## Remaining competitive gaps after 3.4.0

The roadmap deliberately keeps these separate from shipped claims:

- an optional local *visual* embedding model (3.4.0 semantic ranking uses text
  exposed by metadata, accessibility or OCR);
- more public application/browser restoration APIs without private automation;
- user-previewable manual monitor mapping for unusual dock configurations;
- stronger portable native update signing/notarization; and
- complete accessibility, localization and keyboard-only review of every UI.

Audio history, keystroke/clipboard capture, covert monitoring and generic
process-memory checkpointing remain explicit non-goals. Feature parity is not a
reason to weaken SessionSifu's opt-in, local-only and bounded-data model.
