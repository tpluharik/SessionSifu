# SessionSifu Portable

This package contains the shared SessionSifu 2 desktop application used by the
Windows, macOS, KDE Plasma and generic GNOME builds. See the repository README
for platform capabilities and installation artifacts.

The 2.3.2 manager includes experimental Privacy Recall. It is off by default and
records only sanitized app/window metadata after explicit opt-in. Its tray menu
shows when capture is active and can pause it immediately. Application
exclusions redact matching apps from both new captures and existing search
results. Retention, deletion, the separate open-file-path opt-in and the
dedicated customizable search shortcut (`Ctrl+Alt+Space` by default) are
available on every portable target, including while new capture is paused.
KDE/Wayland and general Linux request the shortcut through the desktop portal;
Windows and macOS use their native shortcut APIs.
