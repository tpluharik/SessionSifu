# Release signing and recovery

SessionSifu 2.5.0 establishes the signed stable update channel. The manager
contains the Ed25519 public key also published as
`packaging/update-signing-public.pem`. The private key is never stored in Git,
the Debian package or GitHub Actions.

## Maintainer release procedure

Use a passphrase-encrypted Ed25519 private key on an isolated signing machine or
account, with an encrypted offline backup. A hardware-backed signer is preferable
when available. Existing key custody is an external prerequisite, not something
a repository change can establish. The historical key location was:

```text
~/.config/sessionsifu-release/update-signing-private.pem
```

The directory must be `0700` and the key `0600`. Do not expose a key path or
passphrase to build/test processes. Since 3.5.35 the build script refuses the
legacy signing-key environment variable before running any project tests.

1. Build/test in CI and publish the authoritative tag artifacts with build
   attestations and per-platform inventories. Enable immutable releases.
2. Download all assets, verify `SHA256SUMS`, version, commit and provenance.
   Verify the Debian artifact's GitHub attestation against this repository and
   the reviewed release workflow/ref, not just an arbitrary valid attestation:

```sh
gh attestation verify /verified/release/sessionsifu_3.5.35_all.deb \
  --repo tpluharik/SessionSifu \
  --signer-workflow tpluharik/SessionSifu/.github/workflows/release.yml
```

3. On the preparation system, run `packaging/prepare-update-manifest.py` with
   `--version`, `--deb`, `--release-dir`, the reviewed `--source-commit` and
   `--output-dir`. This step verifies existing bytes and reads no private key.
4. Review the unsigned JSON on the isolated signing system. Sign each of
   `latest.json`, `stable-v2.json` and `portable-stable.json` directly with
   OpenSSL; do not run project code or tests with signing-key access:

```sh
openssl pkeyutl -sign -rawin -inkey /isolated/encrypted-update-key.pem \
  -in /reviewed/stable-v2.json -out /reviewed/stable-v2.json.sig
openssl pkeyutl -verify -pubin -inkey packaging/update-signing-public.pem \
  -rawin -in /reviewed/stable-v2.json -sigfile /reviewed/stable-v2.json.sig
```

Encrypted PEM prompts for its passphrase. Never put a passphrase in argv, a
build environment or logs. Encrypt an existing key only with a separately
verified backup and operator-controlled passphrase; do not overwrite the only
working key as an automated release step. Never upload the key to CI.

5. Commit the signed indexes and their signatures together. The legacy
   `updates/sessionsifu_3.5.35_all.deb` copy must be byte-identical to the CI
   release artifact. Older clients keep using `latest.json`; bridge clients
   use `stable-v2.json` and authenticated release asset URLs. Verify the public
   signatures, package hashes/sizes and all three feeds after pushing.

Historical pre-3.5.35 tag/in-app differences are documented in the
[3.5.27 verification record](RELEASE_3.5.27_VERIFICATION.md); they do not describe
the new authoritative-build procedure.

## Renewal without a rebuild

Before a signed index expires, re-download and verify the same release artifact
and provenance. Run the preparation tool with the original arguments plus
`--renew /previous/stable-v2.json`. It requires the existing version, hash and
size and changes only `issued_at`/`expires_at`. Sign and publish the renewed
JSON/signature together. Repeat for `latest.json` and renew the portable index
from the same immutable asset inventory. No package rebuild or disabled expiry
check is needed. Use the manifest's recorded expiry for an operator reminder;
no automatic scheduler or unapproved signing job is installed by this release.

Confirm that the package contains `ces.traineddata`, `eng.traineddata`, the TSV
configuration, provenance README and Apache-2.0 license under
`/usr/share/sessionsifu/tessdata/`. The static checks bind these vendored files
to their reviewed SHA-256 digests, and the user-local package test verifies that
the updater copies them before activating the launcher.

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

Workflow actions are full-SHA pinned and release Python dependencies are
transitively hash-locked in `packaging/requirements.lock`. Exact file inventories,
build-environment package inventories and OIDC attestations complement JSON
provenance. Windows service provisioning, isolated/encrypted key custody,
renewed Snap Store credentials and Apple notarization require external evidence;
none should be claimed from source or a successful Linux build alone.
