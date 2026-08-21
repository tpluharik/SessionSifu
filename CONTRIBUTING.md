# Contributing to SessionSifu

SessionSifu targets Ubuntu 26.04 and GNOME Shell 50. Changes should preserve the
separation between the GNOME Shell extension, the unprivileged manager and the
Debian packaging layer.

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

A useful report includes the SessionSifu version, Ubuntu version, GNOME Shell
version, Wayland or X11 session type, installation method, extension state and
the smallest reliable sequence that reproduces the problem. For restoration
problems, say what was saved, what reopened and what did not. Attach only the
relevant log excerpt after removing personal information.

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
and package assembly.

For GNOME Shell changes, also verify extension enable/disable, the top-bar menu,
manual save and restore, logout/login activation and repeated restoration on a
real GNOME 50 session. Changes that touch Mutter operations must remain safe
when a target window closes midway through an asynchronous callback.

## Versioned release checklist

1. Update the application version, extension metadata, D-Bus ping, Debian
   control metadata, build script, tests, README, NOTICE and changelog.
2. Update the release note in `packaging/latest.json.in`.
3. Run `./packaging/build-deb.sh` exactly once after the final source change.
4. Confirm that `updates/latest.json` contains the size and SHA-256 digest of
   the generated package.
5. Commit the source, manifest and matching `updates/*.deb` together.

Do not edit `updates/latest.json` by hand; the build generates it from the
package bytes.

## Compatibility changes

GNOME Shell JavaScript APIs change between major releases. Do not add an
untested Shell version to `metadata.json`. A compatibility bump should be tested
with the top-bar indicator, D-Bus service, snapshot timer, manual restoration
and logout/login activation path.

## Privacy and security

Do not add telemetry or session upload behavior without explicit design review
and clear user consent. Update URLs must remain HTTPS URLs inside the official
SessionSifu GitHub repository, and package size and digest validation must not
be bypassed.

## Review and maintenance

Maintainers may request changes for compatibility, safety, privacy, packaging
or maintainability. A pull request can be closed when its scope no longer fits
the project, it duplicates another change or it cannot be made safe for GNOME
Shell. Constructive follow-up is always welcome, and disagreement should remain
focused on the technical decision rather than the people involved.
