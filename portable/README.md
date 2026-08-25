# SessionSifu Portable

This package contains the shared SessionSifu 3 desktop application used by the
Windows, macOS, KDE Plasma and generic GNOME builds. See the repository README
for platform capabilities and installation artifacts.

The current 3.4.0 manager includes encrypted visual Privacy Recall. It is off by default;
screenshots, open paths, OCR and related ranking require separate choices. Its
tray menu shows when capture is active and offers timed pauses. Application and
observable website exclusions redact matching activity from new captures
and delete affected older entries. Retention, encrypted quota, granular
deletion, the separate open-file-path opt-in and the
dedicated customizable search shortcut (`Ctrl+Alt+Space` by default) are
available on every portable target, including while new capture is paused.
The large screenshot viewer accepts two-finger panning, native pinch zoom and
Ctrl+scroll zoom while preserving the current position in the image.
KDE/Wayland and general Linux request the shortcut through the desktop portal;
Windows and macOS use their native shortcut APIs. Portable Qt builds capture a
bounded display preview plus up to 64 compressed images mapped to eligible open
windows through the operating system's standard screen-permission path. A
native window image is preferred; a geometry crop is used when the platform
does not expose one. Images are encrypted locally, optional OCR is indexed per
window, and a result can reopen its opted-in file. Minimized/unmapped windows
may remain metadata-only.

Version 3.4.0 adds accessibility-first text indexing on supported Linux
desktops, protected/private-context redaction, capture-completeness diagnostics,
deep file/editor/URL return targets and a restore preview that lets the user
uncheck applications before launch. A read-only local integration API is
available with `--local-api-stdio`; it uses inherited pipes and never listens
on a network port.

Version 3.4.0 bundles the pinned Czech and English Tesseract language models in
portable artifacts. OCR still requires a compatible local Tesseract executable;
the language data itself is no longer a separate download.

Vault keys prefer Windows Credential Locker, macOS Keychain and the available
Linux Secret Service/KWallet backend. A private application-data key is used
when no usable credential backend exists and remains authoritative for that
vault if the backend later becomes available.
