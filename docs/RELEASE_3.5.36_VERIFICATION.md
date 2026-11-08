# SessionSifu 3.5.36 verification

Scope: auditor recommendations 1–3 only. Preserve session/Recall/capsule formats,
encryption keys, historical recovery bytes, restore pacing and capture timers.
Snap credentials and expiry automation are not changed.

## Acceptance gates

- Pillow 13.0.0, cryptography 50.0.2, setuptools 84.1.0; unchanged other pins.
- Hash-locked build, runtime and auditing inputs; complete generated audit list.
- Image limits, invalid-format refusal, real spawned preparation, worker timeout,
  non-coercing child-PID guard and preservation of existing recovery images/OCR.
- Existing restore, compositor safety, encrypted archive, settings, update trust,
  installation ownership, package and documentation regressions.
- Cross-platform CI, frozen-worker smoke tests and vulnerability audit reports.
- Authoritative CI artifact, provenance/checksum and hosted-build attestation.
- Signed legacy/v2/portable feeds verified after publication.

## Status

Full isolated Debian build and package/update tests passed with Pillow 13.0.0,
cryptography 50.0.2 and setuptools 84.1.0. Existing portable (47), GNOME Recall
(20), audit/recovery (8), image-security (9), dependency-input (3), signature,
settings, static/docs, GJS and mocked compositor/restore regressions passed.
Resolved build, Snap runtime and auditor locks reported no known vulnerabilities
on the local Linux platform; hosted per-platform validation is still required.

The synthetic 100-window/100-iteration median was 0.357 ms load, 0.290 ms rule
application and 0.228 ms serialization. A 1280x800 JPEG visual-hash comparison
measured median 2.951 ms before / 2.887 ms after (20 warmed samples).
These are synthetic checks, not measured energy savings or native restore timing.

## Hosted preflight

The full [main workflow](https://github.com/tpluharik/SessionSifu/actions/runs/42464642652)
passed for source commit `9fe3746570147161fdbf7a38e5800c08183b1903`.
All four platform test jobs and dependency-audit jobs passed, as did Debian
builds on Ubuntu 26.04/24.04 and frozen Linux/Windows/ARM Mac/Intel Mac checks.
The 13 downloaded audit JSON reports contain no known advisory findings.
The source-build Python backends are also pinned/audited (Maturin 1.16.0 on Intel).

An earlier preflight caught an Intel-only frozen OpenSSL symbol collision.
It was corrected before tagging by static linkage, an explicit dynamic-library
rejection and real frozen encryption/signature/image-worker checks. No failed
candidate was published as a release. Direct GNOME-manager-import spawn also
passed locally without activating an application or using user storage.

## Publication and signed updates

The authoritative [tag workflow](https://github.com/tpluharik/SessionSifu/actions/runs/42465270710)
passed. [v3.5.36](https://github.com/tpluharik/SessionSifu/releases/tag/v3.5.36)
is public, immutable and not a prerelease. All 13 assets were downloaded through
the GitHub API/CLI; all 12 published checksums and 10 provenance entries matched.
The Debian package and checksum inventory passed GitHub attestation verification
with the exact repository/workflow, source digest/ref and hosted-runner restriction.

- Debian size: 3,841,266 bytes.
- SHA-256: `c5b0814691f10529a9ffa74a82f18f4f24746fd144046f1a7d436e5870e4698a`.
- Exact legacy mirror commit: `9d1cc93b6236aacc58fefadb011a34eb37424300`.
- All three public signed indexes verified with the unchanged embedded key.
- New feed validity: 8 November to 23 December 2026 (normal 45-day lifetime).
- Real 3.5.34 legacy and 3.5.35 bridge updater code fetched authenticated
  metadata and downloaded/size-hash-verified the Debian bytes with unchanged
  production timeouts and temporary caches only. No installer was invoked.
- The public portable index passed signature/lifetime/source checks and bound
  every one of the 13 downloaded assets to the signed hash/size/URL inventory.

GitHub's release-download gateway returned HTTP 504 from the FRA edge during
verification; the older release endpoint also timed out. Both native feeds
therefore use the already-supported immutable raw mirror of the same attested
Debian bytes. After the raw-content cache refreshed, both old native clients
passed end to end. No trust check or timeout was weakened.

The direct portable client reached its signed inventory but the subsequent
GitHub checksum download returned HTTP 504. Portable direct-client delivery is
therefore a coverage gap, not a claimed end-to-end pass; API/CLI download and
cryptographic binding of the actual bundle bytes did pass.

The post-tag commits contain only attested mirror bytes, separately signed
channel metadata and verification documentation, not rebuilt/replaced artifacts.
They intentionally skip redundant application builds; release source and all
platform gates were validated by the tag workflow above.

## External channels and runtime scope

The [Snap run](https://github.com/tpluharik/SessionSifu/actions/runs/42465270697)
built successfully but publication failed with invalid Candid credentials.
Credential repair (recommendation 4) was excluded. Windows/Chocolatey production
publication remains withheld without SignPath provisioning; macOS notarization
and isolated/encrypted signing-key custody remain external prerequisites.

GNOME continues to use distribution-managed Python libraries/security backports;
the PyPI upgrades apply to the frozen portable and Snap dependency locks.
No real desktop restore, logout, monitor mutation, local upgrade, key rotation,
historical recovery rewrite or destructive user-data migration was performed.
