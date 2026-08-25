# Marketplace release inputs

SessionSifu generates submission-ready package definitions from the immutable
files produced by a tagged GitHub release:

```bash
python3 packaging/generate-marketplace-metadata.py \
  --asset-dir release-assets --output marketplace-metadata
```

The generator refuses missing or ambiguous artifacts and calculates every
checksum locally. Its output contains a WinGet multi-file manifest, Chocolatey
package source, an AUR `sessionsifu-bin` recipe and a dual-architecture Homebrew
Cask.

Generated definitions must be submitted through the maintainer's corresponding
store accounts. The Homebrew Cask is intentionally held until both macOS builds
are Developer ID-signed and notarized. See
[`docs/PUBLISHING.md`](../../docs/PUBLISHING.md) for channel status and policy.

The tag release workflow publishes the generated Chocolatey package only from
the protected `release` environment. It requires `CHOCOLATEY_API_KEY` and also
requires the Windows archive to have been Authenticode-signed using
`WINDOWS_CERTIFICATE_PFX_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD`.
