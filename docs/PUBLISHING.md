# Publishing and distribution

SessionSifu is published by Tomas Pluharik under the same maintainer identity
used for the author's other open-source applications. This page distinguishes
channels that are available today from definitions that are ready for external
store review. It must not claim availability before a store has accepted and
published a package.

## Official release channel

Tagged releases at
[GitHub Releases](https://github.com/tpluharik/SessionSifu/releases) are the
canonical source for SessionSifu. The release workflow tests Ubuntu, Windows,
Apple-silicon macOS and Intel macOS, then publishes the GNOME Debian package,
four portable archives, a checksum file and a bundle of package-manager
submission metadata.

The repository, release notes and issue tracker remain the authoritative links
for every downstream package. Session and Privacy Recall data are never sent to
a package store.

## Ubuntu PPA

The full GNOME integration is deliberately limited to Ubuntu 26.04 with GNOME
Shell 50. The active PPA is:

```text
ppa:tpluharik77/sessionsifu
```

Its first clean Launchpad amd64 build passed on 25 August 2026. Installation is:

```sh
sudo add-apt-repository ppa:tpluharik77/sessionsifu
sudo apt update
sudo apt install sessionsifu
```

The PPA does not publish the full Shell extension for older Ubuntu/GNOME
combinations. Users of other current Linux desktops should use a portable or
Snap build instead.

Maintainer uploads are signed with the OpenPGP key registered on the Launchpad
account. The private signing key stays offline and is never stored in GitHub
Actions.

## Snap Store

The `sessionsifu` snap packages the portable KDE Plasma/general GNOME edition.
It requests classic confinement because it must enumerate user applications,
open user-selected documents, integrate with the desktop tray, use compositor
helpers where available and store encrypted local session history. These are
core functions, not optional conveniences that can truthfully operate inside a
strict sandbox.

The `sessionsifu` name is registered to the `tpluharik77` publisher. Revision 1
of version 3.2.3 was built successfully and uploaded on 25 August 2026. It is
available to the publisher in the Store dashboard but is not released to a
public channel: Canonical marked it as requiring manual classic-confinement
review.

The snap is built on tags and manual dispatches by
`.github/workflows/snapcraft-publish.yml`. A restricted, snap-specific Store
credential is installed as the `SNAPCRAFT_STORE_CREDENTIALS` GitHub secret and
is limited to the `sessionsifu` name and `edge` channel. Store credentials must
never be pasted into issues, logs or documentation. Public installation must
not be advertised until the classic-confinement request is approved and the
revision is released.

## WinGet, Chocolatey, AUR and Homebrew

`packaging/generate-marketplace-metadata.py` derives submission-ready
definitions from immutable GitHub Release assets and calculates their SHA-256
hashes locally. The generator produces:

- a WinGet multi-file manifest for `TomasPluharik.SessionSifu`;
- a Chocolatey package named `sessionsifu`;
- an AUR binary package named `sessionsifu-bin`; and
- a dual-architecture Homebrew Cask.

WinGet, Chocolatey and AUR definitions may be submitted after the matching tag
and release assets exist. The Homebrew Cask remains withheld until both macOS
archives are signed with an Apple Developer ID and notarized; publishing an
unsigned Cask would create a poor and misleading installation experience.

The preferred public-signing route is the SignPath Foundation open-source
program. It keeps the production key in managed hardware, verifies that the
artifact originated in the repository's GitHub-hosted workflow and returns the
signed artifact to the same run. The repository prerequisites are recorded in
the [code signing policy](../CODE_SIGNING_POLICY.md). The workflow integration
will be enabled only after SignPath approves the project and supplies its real
organization, project and policy identifiers; placeholder identifiers are not
committed.

The existing certificate-authority-issued PFX path remains a fallback. Tagged
Windows releases are blocked unless either the approved SignPath integration is
configured or the `release` GitHub environment contains both
`WINDOWS_CERTIFICATE_PFX_BASE64` and `WINDOWS_CERTIFICATE_PASSWORD`. The PFX
fallback decodes the certificate only into the runner's temporary directory,
signs and verifies `SessionSifu.exe`, rebuilds the ZIP and deletes the temporary
PFX. A development build from a branch may be unsigned, but it is never
submitted to Chocolatey.

After a tagged GitHub Release is created, the Chocolatey job regenerates its
package from the immutable release archives, packs it and submits it using
`CHOCOLATEY_API_KEY` from the same `release` environment. The API key and PFX
must be provisioned through GitHub's encrypted-secret UI or CLI input and must
never be committed or pasted into logs, issues or documentation.

The `release` environment and `CHOCOLATEY_API_KEY` secret were provisioned on
25 August 2026. A SignPath Foundation open-source application was submitted and
acknowledged by the service on the same date; it is awaiting external review.
The two PFX fallback secrets remain deliberately unset. A self-signed
certificate is not an acceptable substitute for public distribution.

SignPath onboarding still requires external approval. The maintainer must keep
multi-factor authentication enabled, submit the public repository and code-
signing-policy links, install the official SignPath GitHub App when requested,
and create a least-privilege CI submitter token. That token belongs in the
protected `release` environment as `SIGNPATH_API_TOKEN`; it must never be
pasted into issues, documentation or workflow output. Production workflow
changes are made only after the assigned identifiers and artifact configuration
are known and can be tested without guessing.

The generated metadata is attached to every tagged release so downstream
reviewers can reproduce its hashes. Account credentials and API keys belong in
the package store or encrypted repository secrets, never in the source tree.

## Promotion principles

Community announcements should be factual, low-frequency and relevant to the
discussion where they appear. They should identify Tomas as the individual
developer, link to the public source, clearly invite testers and contributors,
and mention the actual tested platform boundary. Do not present SessionSifu as
an official GNOME, KDE, Microsoft or Apple project, and do not post repetitive
links across unrelated communities.

Useful feedback includes the desktop/session type, compositor, display
topology, applications restored, expected result, actual result and whether
Privacy Recall was enabled. Screenshots and logs must be checked for private
window titles, paths or captured content before sharing.

## Maintainer release checklist

1. Run all unit, integration, packaging and metadata-generator tests.
2. Confirm every version field matches the proposed tag.
3. Push the release commit and signed tag to `main`.
4. Wait for all platform builds and inspect the release checksums.
5. Build and sign the Launchpad source upload from the exact tag.
6. Publish the Snap only after its confinement review permits the requested
   channel.
7. Generate downstream submissions from the final immutable assets; never reuse
   hashes from a draft or replaced upload.
8. Announce only channels that are actually downloadable.
