# SessionSifu Portable

This package contains the shared SessionSifu 3 desktop application used by the
Windows, macOS, KDE Plasma and generic GNOME builds. See the repository README
for platform capabilities and installation artifacts.

The 3.0 manager includes encrypted visual Privacy Recall. It is off by default;
screenshots, open paths, OCR and related ranking require separate choices. Its
tray menu shows when capture is active and offers timed pauses. Application and
observable website exclusions redact matching activity from new captures
and delete affected older entries. Retention, encrypted quota, granular
deletion, the separate open-file-path opt-in and the
dedicated customizable search shortcut (`Ctrl+Alt+Space` by default) are
available on every portable target, including while new capture is paused.
KDE/Wayland and general Linux request the shortcut through the desktop portal;
Windows and macOS use their native shortcut APIs. Portable Qt builds can capture
a compressed display preview through the operating system's standard screen
permission path, encrypt it locally, index it with optional local OCR and reopen
an opted-in file from a result.

Vault keys prefer Windows Credential Locker, macOS Keychain and the available
Linux Secret Service/KWallet backend. A private application-data key is used
when no usable credential backend exists and remains authoritative for that
vault if the backend later becomes available.
