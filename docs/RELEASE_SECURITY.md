# Release signing and recovery

SessionSifu 2.5.0 establishes the signed stable update channel. The manager
contains the Ed25519 public key also published as
`packaging/update-signing-public.pem`. The private key is never stored in Git,
the Debian package or GitHub Actions.

## Maintainer release procedure

Keep the private key in an owner-only directory and make an encrypted offline
backup. On the current maintainer workstation its expected path is:

```text
~/.config/sessionsifu-release/update-signing-private.pem
```

The directory must be `0700` and the key `0600`. Build and sign the release with:

```sh
SESSIONSIFU_UPDATE_SIGNING_KEY="$HOME/.config/sessionsifu-release/update-signing-private.pem" \
  ./packaging/build-deb.sh
openssl pkeyutl -verify -pubin -inkey packaging/update-signing-public.pem \
  -rawin -in updates/latest.json -sigfile updates/latest.json.sig
```

Inspect the generated version, channel, issue/expiry time, minimum version, URL,
size and SHA-256 before committing the package, manifest and signature together.
Do not put the private key in a repository secret merely to automate signing.

## Rotation

Key rotation needs a bridge release authenticated by the old key. That release
must embed the new public key and explicitly authorize its fingerprint in signed
metadata before later manifests use the new key. If the old private key is lost,
automatic continuity cannot be proven; publish a security notice and require a
manual package upgrade.

If compromise is suspected, stop publishing updates, revoke affected GitHub
credentials/tokens, preserve relevant logs, publish a private advisory draft,
generate a replacement key offline and prepare a manually installed recovery
release. Never silently replace the embedded key or ask users to bypass a failed
signature.

## Remaining release hardening

Workflow actions are full-SHA pinned and direct Python dependencies are exact-
version pinned. Per-platform transitive hash locks, SBOMs, provenance
attestations, Windows Authenticode and Apple notarization remain tracked in the
roadmap; none replaces the application update signature.
