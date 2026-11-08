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

Publication and signature verification are pending hosted validation.
No real desktop restore, logout, monitor mutation or local upgrade is performed.
