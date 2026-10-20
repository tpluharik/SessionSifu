# Distribution security — 3.5.35

## Runtime invariants

This release does not change capture/preview timers, image budgets, worker
counts, restore pacing, native-operation serialization or monitor/layout guards.
Command filtering is a bounded in-memory pass over already-collected argv.
Caller checks are asynchronous, capped at four concurrent requests per operation,
and used only for external Recall control. No polling, subprocess or synchronous
authorization runs on GNOME's frame/capture path.

Tests use temporary directories, memory-backed settings, fake applications and
ephemeral signing keys. They must not restore a real desktop, signal processes,
log out, change a real monitor layout or consume historical recovery records.

## Installation ownership and uninstall (H1)

User updates record `apt-backed` or `standalone` ownership in the program's
`install-state.json`. Unknown historical installations remain `legacy` until
explicit adoption; a missing executable is not grounds to disable a standalone
installation. The manager offers Follow system updates / Keep standalone for
legacy adoption, with the same explicit choices available in the CLI. The
manager checks package status once in a background startup
task. Capture helpers do not query dpkg. A failed/timed-out query is unknown,
never treated as a removed package. Debian versions use dpkg comparison rules.

An APT-backed user extension pauses at its next enable/login if the system
manager is gone or a newer system extension exists. The manager retires the
shadowing program files and requests one fresh login. It does not reload live
Shell code or force a logout. Removing APT during an already-running login is
not an instantaneous capture-stop mechanism; explicitly disable the extension
first when an immediate stop is required.

`sessionsifu --remove-user-install --dry-run` previews the fixed program-only
allowlist. Without `--dry-run`, files are moved to owner-private
`~/.local/share/sessionsifu/uninstall-backups/program-*`; a manifest maps original
locations to backup entries. Rename failures roll back. Symlinked target paths
are refused. No session, Recall vault, capsule, settings or manual-recovery
directory belongs to the removal allowlist. Unrelated extensions are preserved.

Use `sessionsifu --install-ownership standalone` for an intentional user-only
installation, or `--install-ownership apt-backed` while the package is installed.
No package maintainer script searches or deletes home directories.

## Release trust (M1/M2/L1/L2/L3/L4)

Build/test jobs receive no signing keys or store secrets. Windows signing uses a
separate tag-only protected job and the SignPath service; the PFX export fallback
has been removed. Unprovisioned signing means withheld Windows/Chocolatey assets,
not an unsigned production fallback. Snap publication is separated from its
secret-free build and restricted to protected release tags. Classic confinement
is explicitly disclosed; strict confinement is not silently introduced.

Portable build dependencies, including transitive packages and build tools, are
version/hash-locked. Snap runtime dependencies use a runtime-only hash lock,
without introducing desktop build tools into the shipped snap. Checkouts do not persist credentials. Each platform publishes
an inventory of actual delivered file bytes and exact Python build-environment
packages; environment-only packages are labelled, not falsely called shipped.
The overview SBOM references these documents. Release artifacts receive GitHub
OIDC build attestations; JSON provenance alone is not cryptographic evidence.

CI produces the single authoritative Debian artifact. Offline preparation verifies
version, digest and provenance before generating unsigned metadata; the separate
OpenSSL signing step neither builds nor runs project tests. The legacy raw-channel
copy must be byte-identical to the CI release asset. A bridge retains the old
`latest.json` feed while 3.5.35+ uses `stable-v2.json` with restricted release URLs.
Portable bundles authenticate `portable-stable.json` before trusting release
checksums; known historical checksum directory prefixes remain supported.

Repository release immutability and protected tag environments must be enabled
and verified as repository settings, not inferred from YAML. An isolated signing
machine/account and passphrase-encrypted private key remain custody requirements;
code cannot establish those physical/administrative boundaries. Do not claim
SignPath, Snap or key-custody provisioning succeeded without external evidence.

## Recall callers and command metadata (L5/L6)

Capture/list/delete D-Bus calls require the active manager's connection identity
and are rate/concurrency limited. PID, executable-name and same-UID comparisons
are not sufficient authorization. This reduces unrelated caller access but does
not isolate against malware controlling this user's code, credentials or bus-name
ownership. Existing history stays browsable when recording is disabled.

New GNOME saves redact recognized credential flags, token URL parameters and URL
userinfo after resolving document ownership. Ordinary command arguments and file
paths are retained. If a command needs credentials, command-based replay is held
for manual input; a redacted placeholder is never launched. Valid desktop-entry
launches remain available. Old recovery bytes are deliberately not rewritten:
historical records may still contain credentials and should be handled privately.
Heuristic redaction cannot recognize every application's secret syntax.

## Renewal and archival (I1/I2)

`prepare-update-manifest.py --renew` verifies the unchanged package and provenance,
then changes only issue/expiry timestamps. Re-sign and publish the changed JSON
and detached signature together. Never disable expiration or rebuild a package
merely to renew its manifest. The mutable signed channel indexes can renew
without changing immutable release assets.

The unused bundled uinput-rule template is removed; no system udev rule or
user-configured ydotool close rule is removed. Only payloads older than the
45-day validity period plus a rollback grace interval are eligible for archival;
current feed targets remain available. Retired bytes and hashes are recoverable
from the release archive and unchanged Git history. This reduces the current
tree, not historical clone size; no history rewrite is performed.
