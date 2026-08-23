# GNOME Shell symbolic icons

`sessionsifu-symbolic.svg` is the production monochrome yin-yang mark used by
the top-bar indicator. `autorestore-symbolic.svg`, `restore-symbolic.svg` and the
other local SVGs provide actions and state inside the extension UI.

The icons are kept as simple symbolic SVGs so GNOME Shell can recolor them and
they remain legible at panel size. The recording state is drawn as a separate
badge by the extension; it does not require a second full-color tray asset.

## Attribution

- `move-symbolic.svg`, `close-symbolic.svg`, `save-symbolic.svg`,
  `separator-symbolic.svg` and `choose-window-symbolic.svg` originated from
  public Iconduck assets retained by the inherited extension.
- `toggle-off-autorestore-symbolic.svg` and
  `toggle-on-autorestore-symbolic.svg` are based on GNOME Shell symbolic toggle
  artwork.
- SessionSifu-specific artwork and its license/design notes are documented in
  the [branding guide](../../../branding/README.md).

All redistributed assets ship under the licensing and attribution terms stated
in the project [NOTICE](../../../NOTICE) and extension
[LICENSE](../LICENSE).
