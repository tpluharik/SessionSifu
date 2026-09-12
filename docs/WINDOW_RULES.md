# Persistent window rules

SessionSifu 3.5.27 adds owner-private placement rules to portable Windows,
macOS, KDE and general Linux editions. A rule can override a matching window's
monitor, workspace and geometry whenever a saved session is restored. It does
not launch extra applications, inspect application memory or change documents.

## Create and manage rules

Open the portable manager's **Window rules** page, select a currently visible
window and choose an app-wide or title-specific rule. App-wide rules match the
exact application identity. A title-specific rule additionally requires its
saved text to occur in the current title and takes priority over an app-wide
rule.

The same operations are available from the command line:

```sh
sessionsifu-portable --window-rules
sessionsifu-portable --window-rule-app org.example.Editor \
  --window-rule-monitor HDMI-1 --window-rule-workspace 2 \
  --window-rule-geometry 80,60,1440,900
sessionsifu-portable --window-rule-delete RULE_KEY
```

Use the opaque key printed by `--window-rules` when deleting a rule. Supplying
`--window-rule-title` creates the narrower title match. Width and height must be
at least 64 pixels; all stored fields, rule count and file size are bounded.

## Storage and safety

Rules live in `window-rules.json` below the platform's normal SessionSifu data
directory. The file is written atomically with owner-only permissions on POSIX
systems. Symbolic links, oversized data and unsupported schemas are rejected.
Deleting SessionSifu data also deletes the rules.

Rules can only request state supported by the active adapter. Native Wayland
compositors may refuse absolute placement; macOS requires Accessibility
permission; Windows does not expose portable virtual-desktop placement. A
failed placement remains visible in the normal restore result and journal.
