# SessionSifu Shell extension

This GNOME Shell 50 extension is the compositor-facing component of
SessionSifu. It records bounded application/window metadata, captures eligible
window surfaces for opt-in Recall, exposes session operations over D-Bus,
reconstructs workspace layouts and supplies the top-bar indicator.

Use the complete `sessionsifu` Debian package for the initial installation; it
also supplies the GTK manager and login restore helper. Later verified in-app
updates install this extension and the manager into the user's local data
directories without root access. OCR, encryption, search indexing and preview
decoding stay in the unprivileged manager rather than GNOME Shell.

The implementation is derived from Another Window Session Manager by nlpsuge
and contributors at audited revision
`cf23fef152ce90692fc1df984f6fd945725334be`. See `LICENSE` and the package
`NOTICE` file.
