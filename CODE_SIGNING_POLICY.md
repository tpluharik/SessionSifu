# Code signing policy

SessionSifu publishes reproducible release inputs from its public GitHub
repository. Windows code signing is intended to let users verify the publisher
and the exact automated build that produced a release; it is not a substitute
for source review, malware scanning or the project security policy.

Free code signing provided by SignPath.io, certificate by SignPath Foundation.

## Project and privacy statement

- Source repository: <https://github.com/tpluharik/SessionSifu>
- License: GNU GPL version 3, with upstream attribution recorded in
  [NOTICE](NOTICE)
- Security reports: [SECURITY.md](SECURITY.md)
- Local-data details: [docs/PRIVACY.md](docs/PRIVACY.md)

This program will not transfer any information to other networked systems unless
specifically requested by the user or the person installing or operating it.

Explicit network actions are limited to checking or downloading releases from
the official GitHub repository and to requests made by operating-system package
tools. Session state, Recall screenshots, OCR text and search queries stay on
the user's device. The complete inventory and retention rules are documented in
the privacy guide linked above.

## Roles and responsibilities

SessionSifu is currently maintained by one independent developer:

| Role | Member | Responsibility |
| --- | --- | --- |
| Author and committer | Tomas Pluharik (`tpluharik`) | Maintains source, tests and release automation |
| Reviewer | Tomas Pluharik (`tpluharik`) | Reviews release changes and external pull requests |
| Release approver | Tomas Pluharik (`tpluharik`) | Approves production signing requests and tagged releases |

External contributors submit changes through pull requests. They do not receive
release-signing credentials or direct approval rights. If the maintainer authors
a release change directly, automated cross-platform tests and security checks
form the independent verification boundary until another reviewer joins the
project. GitHub and SignPath accounts with release authority must use multi-
factor authentication.

## Signed artifact scope

Only the Windows executable produced by the tagged GitHub Actions release
workflow is eligible for the production certificate. Development builds, local
builds, pull-request artifacts, modified archives and files uploaded outside the
trusted workflow remain unsigned.

The signing service verifies the GitHub build origin. The signed executable is
then placed into the Windows archive before checksums, the GitHub Release and
package-manager metadata are published. Chocolatey submission consumes that
immutable signed release archive.

The release workflow must:

1. build from a signed `v*` tag on the public repository;
2. run all required tests on GitHub-hosted runners;
3. upload the unsigned artifact to GitHub Actions before requesting signing;
4. submit it through the official SignPath GitHub integration;
5. verify the returned Authenticode signature before packaging it;
6. publish checksums only after signing; and
7. keep service tokens in the protected GitHub `release` environment.

Until the SignPath Foundation application is approved and project identifiers
are provisioned, tagged releases withhold the Windows archive and the
Chocolatey/WinGet metadata derived from it. Linux, GNOME and macOS artifacts may
still be published with their signing status stated accurately. A Windows
release must never be unblocked with a self-signed certificate.

## Key custody and compromise response

The production private key is held by the signing service and is not exported
to the repository, maintainer workstation or GitHub runner. The CI API token is
limited to submitting requests for this project and signing policy.

Suspected credential, account or build-pipeline compromise pauses releases.
The maintainer revokes the affected token, disables the signing policy, records
the affected tags and hashes, publishes a security advisory when users may be
affected, and restores the workflow only after new credentials and a clean
build are verified. General release-key recovery is documented in
[docs/RELEASE_SECURITY.md](docs/RELEASE_SECURITY.md).
