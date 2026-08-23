# SessionSifu update channel

`latest.json`, `latest.json.sig` and the referenced Debian package are generated
by `packaging/build-deb.sh`. The application verifies the Ed25519 signature
before trusting the version, validity window, minimum version, repository URL,
declared size or SHA-256 digest.

The package contains the manager, Recall engine, GNOME integration and pinned
Czech/English OCR resources. A user-local update validates the complete payload
and atomically activates it below the user's XDG directories; it does not call
`apt` or `dpkg -i`. The Debian package remains the initial installation path for
runtime dependencies.

Windows, macOS and portable Linux bundles are published as GitHub Release
artifacts by `.github/workflows/release.yml`; their native in-app replacement is
planned and is not implied by this GNOME update channel.
