# Contributing to SessionSifu

SessionSifu 2 targets Ubuntu 26.04/GNOME Shell 50, KDE Plasma 6, Windows and
macOS. Changes should preserve the separation between the GNOME Shell
extension, portable core, platform adapters, unprivileged managers and
distribution layers.

## Ways to participate

You do not need to write code to help SessionSifu. Testing session capture and
restoration, confirming bugs on different hardware, improving documentation
and reviewing user-interface wording are all useful contributions.

- Use the [bug report form](https://github.com/tpluharik/SessionSifu/issues/new?template=bug_report.yml)
  for reproducible failures or regressions.
- Use the [feature request form](https://github.com/tpluharik/SessionSifu/issues/new?template=feature_request.yml)
  for proposed behavior or workflow changes.
- Search existing issues before opening a new one and add useful confirmation
  to an existing report when possible.
- Keep logs and session files free of private window titles, document paths,
  usernames, tokens and other personal information.

All participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Bug reports

A useful report includes the SessionSifu edition and version, operating system,
desktop/compositor where applicable, display session, installation method,
integration state and the smallest reliable sequence that reproduces the
problem. For restoration problems, say what was saved, what reopened and what
did not. Attach only the relevant log excerpt after removing personal
information.

## Pull requests

1. Open an issue before starting a large behavioral or architectural change so
   the intended scope can be agreed first.
2. Fork the repository and create a focused branch with one logical change.
3. Add or update tests for behavior changes and update user documentation when
   the visible workflow changes.
4. Run the canonical validation command below.
5. Open a pull request explaining the problem, the chosen solution, manual
   GNOME checks performed and any known limitations.

Keep pull requests small enough to review. Do not commit local session data,
crash dumps, credentials, editor state or unrelated generated files.

## Local validation

Install the build-time tools used by `packaging/build-deb.sh`, including Python
3, GJS, Node.js, `desktop-file-validate`, `glib-compile-schemas`, `zip` and
`dpkg-deb`. Then run:

```sh
./packaging/build-deb.sh
```

The script is the canonical validation entry point. It checks source syntax,
desktop files, schema lookup, D-Bus method declarations, update-manifest safety
portable storage/model behavior and package assembly.

Portable-only work can be checked quickly with:

```sh
python3 tests/test_portable.py
python3 -m compileall -q portable/sessionsifu_portable packaging/build-portable.py
```

The exact direct release inputs are mirrored in
`portable/security-audit-requirements.txt` for `pip-audit`. Update it in the same
change as `portable/pyproject.toml`; transitive hash locks remain roadmap work.

For GNOME Shell changes, also verify extension enable/disable, the top-bar menu,
manual save and restore, logout/login activation and repeated restoration on a
real GNOME 50 session. Changes that touch Mutter operations must remain safe
when a target window closes midway through an asynchronous callback.

## Versioned release checklist

1. Update the application version, extension metadata, D-Bus ping, Debian
   control metadata, build script, tests, README, NOTICE and changelog.
2. Update the release note in `packaging/latest.json.in`.
3. Run the final build with `SESSIONSIFU_UPDATE_SIGNING_KEY` pointing to the
   offline Ed25519 private key; contributor/test builds omit it.
4. Verify `updates/latest.json.sig` with the published public key and confirm
   the manifest version, expiry, size and SHA-256.
5. Commit source, matching package, manifest and signature together.

Do not edit `updates/latest.json` by hand; the build generates it from the
package bytes. Follow [docs/RELEASE_SECURITY.md](docs/RELEASE_SECURITY.md) for
key storage, rotation and compromise recovery.

## Compatibility changes

GNOME Shell JavaScript APIs change between major releases. Do not add an
untested Shell version to `metadata.json`. A compatibility bump should be tested
with the top-bar indicator, D-Bus service, snapshot timer, manual restoration
and logout/login activation path.

Windows code must use documented Win32 APIs and be tested on an actual Windows
runner. macOS code must avoid private Spaces APIs, state its Accessibility
requirements and be tested on both architecture jobs. KDE Wayland window
operations must remain behind the `kdotool` capability check. A generic Linux
fallback must never claim geometry that its compositor did not expose.

For release-pipeline changes, validate the workflow YAML, keep permissions at
read-only except for the tag release job and never execute pull-request code
with a write-capable token.

## Privacy and security

Do not add telemetry or session upload behavior without explicit design review
and clear user consent. Update URLs must remain HTTPS URLs inside the official
SessionSifu GitHub repository, and package size and digest validation must not
be bypassed.

Read [SECURITY.md](SECURITY.md), the current
[security audit](docs/SECURITY_AUDIT.md), and the
[privacy data map](docs/PRIVACY.md) before changing capture, restore, updates,
D-Bus, storage, logging or release automation. Security fixes should reference
the applicable audit identifier and change its status only after regression and
platform tests pass.

Security-sensitive pull requests must also demonstrate that:

- stored session strings never reach a shell or interpreter; launch APIs receive
  a bounded argument vector and validated executable;
- files stay inside an owned, non-symlinked SessionSifu root and private data is
  created with user-only permissions;
- JSON, D-Bus and settings inputs have type, size, collection and allow-list
  validation at the runtime boundary, even if the UI already validates them;
- screenshot exclusions and lock state are checked across asynchronous capture,
  encoding and publication, with temporary files removed on a race;
- network redirects, response sizes, versions and hashes fail closed, while
  publisher signatures and rollback protection are not replaced by a checksum;
- workflow actions use reviewed full commit SHAs and build dependencies use
  reviewed exact versions/hashes;
- logs and test fixtures do not contain real titles, paths, commands, tokens or
  Recall pixels.

Run Bandit/Semgrep or an equivalent static review, a dependency advisory scan,
secret detection and the canonical build for security-related changes. Include
tool versions and explain false-positive triage in the pull request rather than
silencing findings without a comment.

## Review and maintenance

Maintainers may request changes for compatibility, safety, privacy, packaging
or maintainability. A pull request can be closed when its scope no longer fits
the project, it duplicates another change or it cannot be made safe for GNOME
Shell. Constructive follow-up is always welcome, and disagreement should remain
focused on the technical decision rather than the people involved.
