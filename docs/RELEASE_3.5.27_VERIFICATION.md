# SessionSifu 3.5.27 release verification

This record reflects the public state verified on 26 September 2026. It
distinguishes the immutable tagged release from the separately signed GNOME
in-app update channel.

## Source and workflows

- Release tag: [`v3.5.27`](https://github.com/tpluharik/SessionSifu/releases/tag/v3.5.27)
- Tagged source commit: `1dd810571c3ef61406bf1f962d851125579b09c8`
- Signed-channel commit: `0d97ed7809b392b31c56c53002b2aebaf1b18ca8`
- Publication time: 12 September 2026 at 07:12:57 UTC
- Cross-platform tests and the tag release workflow completed successfully.

## GitHub Release assets

| Asset | SHA-256 |
| --- | --- |
| `SessionSifu-3.5.27-linux-x64.tar.gz` | `2f4bd0a31e9e2d0e31681e83d89e8615360affc2596e66cb4b0df783c5b324cd` |
| `SessionSifu-3.5.27-macos-arm64.zip` | `c04be9f1c4aecd2424cd00dc4be423d6fa4e566431d0d88b807192b709c1186e` |
| `SessionSifu-3.5.27-macos-x64.zip` | `267ada8c77a32229e3101221b1ee412064ab681aac8c641b53faee10488223d8` |
| `sessionsifu_3.5.27_all.deb` | `1be323c16e6dcb9f2a446e4084a43a7af1429a146c7980f5d501cabda42f656b` |
| `SessionSifu-3.5.27-marketplace-metadata.tar.gz` | `b8d7f3862d84c89d2f4fec9eaf48a3221677c977c44529dda1f1e024c2e778e0` |
| `SessionSifu-3.5.27.spdx.json` | `88f53a49121cf224031e8f8385af094c1fc94df09ddaae7589dcf095cb7b9095` |
| `SessionSifu-3.5.27.provenance.json` | `d010a4f37460b94e98613b942933311daf032809ddcc49ba79ce3bf40391faee` |

`SHA256SUMS` in the release is the canonical machine-readable copy. The
Windows x64 build passed its test job but was not attached because no production
Authenticode signature was available. Consequently, Chocolatey publication was
also skipped. This is an intentional signing-policy gate, not a missing-file
claim.

## Signed GNOME update channel

The GNOME manager reads `updates/latest.json` and its detached Ed25519 signature
from `main`. The 3.5.27 manifest was generated with the offline release key,
committed together with its exact package, and then re-verified through the
public URLs.

- Version: `3.5.27`
- Issued: 12 September 2026 at 07:17:47 UTC
- Expires: 27 October 2026 at 07:17:47 UTC
- Package size: 3,803,172 bytes
- Package SHA-256: `85564b1a0c9f2abd28598cfc2a8e3ef8271aa73c7c6815f7b888cb5b7d0236c2`

The in-app package hash differs from the tag-release Debian hash because it is a
separate later build committed with the signed manifest. Both contain version
3.5.27; neither hash should be substituted for the other.

## Verification boundaries

The SPDX document enumerates declared portable dependencies; it is not a full
per-platform transitive lock. The provenance JSON records the source commit and
artifact hashes but is not yet a cryptographically signed attestation. macOS
archives are not notarized, and no Windows release archive was published.
