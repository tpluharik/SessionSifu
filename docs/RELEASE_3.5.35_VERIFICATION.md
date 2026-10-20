# SessionSifu 3.5.35 — release verification

Verified 20 October 2026. This record separates source/build evidence, signing
and actual distribution outcomes; no live restore or desktop restart was run.

## Source and CI

- Tag: `v3.5.35`, extension revision 69.
- Exact build source: `5000f85c6b06dbe9f43cda5dbbda9f58f1eb8e71`.
- [Cross-platform preflight](https://github.com/tpluharik/SessionSifu/actions/runs/39388288234): passed.
- [Build-only Snap preflight](https://github.com/tpluharik/SessionSifu/actions/runs/39388317703): passed; publication was gated off on main.
- [Tagged release workflow](https://github.com/tpluharik/SessionSifu/actions/runs/39448526243): passed.
- [Canonical immutable release](https://github.com/tpluharik/SessionSifu/releases/tag/v3.5.35): published, not draft/prerelease; API confirmed `immutable: true`.
- Protected `release` environment accepts `v*` tags, not main/PR branches.

The tag workflow passed all four platform test jobs, three portable bundles,
the GNOME Debian build, Ubuntu 24.04 dependency-generation compatibility and
the isolated Windows signing-policy job. A successful signing-policy job does
not imply a Windows certificate or asset exists.

## Exact public artifacts

All 12 entries in `SHA256SUMS` matched downloaded public assets. The public
inventory has 13 assets including the checksum file itself. Ten artifact
entries in JSON provenance matched sizes/digests and the exact source commit.
The overview SPDX document references four per-platform inventories containing
delivered file hashes and explicitly labelled build-environment packages.

Authoritative Debian artifact:

```text
sessionsifu_3.5.35_all.deb
bytes: 3838002
sha256: e606c3b9a801a554c30e7399e51fde9298708e2801c04c5a43dc59a7f94223ca
```

GitHub's cryptographic SLSA build attestation was verified with GitHub CLI
2.102.0, restricting repository, signer workflow, source tag, source commit
and hosted runners:

```sh
gh attestation verify sessionsifu_3.5.35_all.deb \
  --repo tpluharik/SessionSifu \
  --signer-workflow tpluharik/SessionSifu/.github/workflows/release.yml \
  --source-ref refs/tags/v3.5.35 \
  --source-digest 5000f85c6b06dbe9f43cda5dbbda9f58f1eb8e71 \
  --deny-self-hosted-runners
```

This is independently verifiable build-origin evidence; JSON provenance alone
is not equivalent. The temporary verification CLI's digest was checked against
the official vendor release/API checksum before it was executed.

## Signed channel bridge

The new legacy raw copy uses exactly the CI artifact bytes above; no local
rebuild was substituted. Ed25519 signatures on `latest.json`, `stable-v2.json`
and `portable-stable.json` verified against the embedded public key. All three
indexes expire at `2026-12-04T15:37:21Z` and can be renewed without rebuilding.
The old feed retains minimum client 2.5.0 and raw repository delivery; the v2
feed requires 3.5.35 and targets the immutable release asset.

The publication commit is `eff2dc9e1b58275315b423cc0514c9694d334e69`;
its tree was verified byte-identical to the locally signed publication tree
before a lease-checked, non-forced API publication. A subsequent metadata-only
change pins the legacy package URL to that exact commit: the main-branch raw
edge stalled on this network, while the commit-pinned URL downloaded all
3,838,002 bytes and matched the authoritative SHA-256. The v2 public package
download passed independently. No package rebuild or artifact replacement was
performed to work around delivery.

Builds/tests ran without key access through the release-key environment variable.
Manifest preparation was separate from a direct OpenSSL signing step. The
existing maintainer key was used for this release: isolated-machine/account and
passphrase-encrypted custody were not established or claimed by this task.

## Recovery and performance boundary

Program-only uninstall tests preserved exact recovery/Recall/preferences bytes
and private modes, rejected symlinked targets, and rolled back interrupted
renames. Adoption, caller/rate/teardown, signature/lifetime/URL, renewal/tampering,
actual-file inventory and LibreOffice ownership/deduplication regressions passed.
The actual authorization helper also passed on a disposable D-Bus with fake
capture counters, not a real compositor or screen recording.

Compositor serialization, native layout guards, capture/preview scheduling,
power policy, worker budgets and restore pacing were not changed. The command
filter took about 10 ms/10,000 ordinary argument lists; the 100-window synthetic
continuity run showed no slowdown. These are bounded synthetic checks, not
proof of native Wayland stability or quantified battery savings.

Forty-four expired payloads were recoverably archived after validity/grace;
current feed targets and unchanged Git history remain available. No personal
session, Recall, capsule, settings or manual-recovery data was removed or
rewritten. Legacy user installations offer an explicit ownership choice.

## Deliberately incomplete external provisioning

- Windows/Chocolatey: withheld because SignPath is not provisioned; no PFX
  fallback, unsigned production archive or fake signing-success claim.
- [Snap tag workflow](https://github.com/tpluharik/SessionSifu/actions/runs/39448526237): build succeeded; protected edge publication failed because Candid credentials are no longer valid. Renew credentials before retrying.
- PPA: not uploaded by the GitHub workflow; no new PPA availability claimed.
- Isolated/encrypted update-key custody, signing-service approval and Apple
  notarization require external operator action; repository changes alone
  cannot provide them.
