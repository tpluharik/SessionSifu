# SessionSifu Shell extension

This GNOME Shell 50 extension is the Wayland-facing component of Session
Keeper. It records application and window metadata, exposes session operations
over D-Bus, reconstructs workspace layouts, and supplies the top-bar indicator.

Install the complete `sessionsifu` Debian package instead of copying
this directory by itself; the package also supplies the GTK manager and login
restore helper.

The implementation is derived from Another Window Session Manager by nlpsuge
and contributors at audited revision
`cf23fef152ce90692fc1df984f6fd945725334be`. See `LICENSE` and the package
`NOTICE` file.
