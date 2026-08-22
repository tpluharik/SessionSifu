# Security policy

SessionSifu restores applications and documents, runs inside GNOME Shell on
the full-integration edition, and optionally records a local visual timeline.
Security and privacy reports are therefore treated as product issues, not only
code-quality reports.

## Reporting a vulnerability

Use GitHub's private vulnerability-reporting form:

<https://github.com/tpluharik/SessionSifu/security/advisories/new>

Please include the affected edition and version, operating system and desktop,
required settings, the smallest reproduction, impact, and whether the issue
requires a locally modified session file. Do not attach real session JSON,
Recall screenshots, window titles, document paths, tokens, or crash dumps
without first removing private data.

If private reporting is unavailable, open a minimal public issue stating that
you have a security concern and ask the maintainer for a private contact path.
Do not publish working exploit instructions before a fix is available.

## Supported versions

Security fixes are made on `main` and shipped in the newest release. Older
packages in `updates/` remain for release history and should not be treated as
supported security branches.

## Current security model

- SessionSifu runs with the logged-in user's privileges. It has no daemon or
  privileged service.
- GNOME control methods are exposed only on the user's session D-Bus. Other
  processes running as that user may be able to call them.
- Named sessions and automatic history contain launch commands, window titles,
  document paths, and other sensitive desktop metadata. They are not encrypted.
- Recall is disabled by default. Screenshot previews and open-file paths have
  separate opt-ins. Recall storage is local and is not uploaded by SessionSifu.
- A restorable session is active configuration, not a passive interchange
  document. Restore only sessions created by a trusted SessionSifu installation;
  do not restore downloaded or shared JSON files.
- Version 2.5+ verifies an Ed25519-signed, expiring manifest with an application-
  embedded public key before trusting version, URL, size or SHA-256. Versions
  2.4 and older require one manual upgrade to enter the signed channel.
- Session state is stored in owner-only directories/files on POSIX systems.

The same-user boundary is not a defence against malware already running as the
user. The project still uses private files, bounded parsing, symlink checks,
atomic replacement, explicit opt-ins, and least-privilege release tokens to
reduce accidental disclosure and limit the damage from malformed data.

## Disclosure and remediation

The maintainer will validate the report, identify affected versions, prepare a
focused fix and regression test, and credit the reporter if requested. Release
notes should describe impact and required user action without exposing private
report details prematurely. Coordinated disclosure is preferred.

The latest public review and open remediation plan are in
[docs/SECURITY_AUDIT.md](docs/SECURITY_AUDIT.md). That document is a point-in-time
assessment, not a guarantee that the software has no vulnerabilities.
