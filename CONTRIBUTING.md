# Contributing to SessionSifu

SessionSifu targets Ubuntu 26.04 and GNOME Shell 50. Changes should preserve the
separation between the GNOME Shell extension, the unprivileged manager and the
Debian packaging layer.

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
