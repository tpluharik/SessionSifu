# Security audit — 22 August 2026

## Executive summary

This review covered the SessionSifu 2.4.0 source tree corresponding to remote
commit `05d7ee1` and the equivalent local source tree. It found no embedded
secrets and no known vulnerabilities in the resolved Python runtime, GUI, build
or packaging dependencies. The package builds successfully, portable tests
pass, update parsing is bounded, Recall storage has explicit opt-ins, and the
release workflow uses read-only permissions except for the tag-only publisher.

The review also found two high-priority trust problems:

1. GNOME's legacy fallback restore path reconstructs saved arguments as a shell
   command. A tampered local session can execute shell syntax when restored.
2. The in-app updater verifies a SHA-256 value delivered by the same unsigned,
   mutable repository channel as the package. This detects corruption but does
   not provide an independent authenticity guarantee.

Four medium and two low-priority hardening findings are documented below. No
claim is made that these findings are exhaustive, and no open finding should be
interpreted as already fixed.

## Scope and method

Reviewed components:

- GTK manager and updater in `app/sessionsifu`;
- GNOME Shell 50 extension, D-Bus service, restore engine and Recall recorder;
- portable model, storage, Recall, hotkey and Windows/macOS/Linux adapters;
- Debian and PyInstaller packaging;
- GitHub Actions release workflow, committed update artifacts and manifests;
- user documentation, privacy statements and contributor guidance.

Executed checks:

- Bandit 1.9.4 across Python application, portable and packaging code;
- Semgrep 1.174.0 with the default and secret rule sets: 486 rules over 111
  tracked files and approximately 100% parsed source lines;
- `pip-audit` 2.10.1 against the core project and all declared optional GUI,
  platform and build dependencies;
- `detect-secrets` 1.5.0 over tracked files plus a targeted credential-pattern
  scan over Git history;
- Python compilation, portable unit tests, shell syntax validation, Debian
  package construction and package-content/permission inspection;
- manual data-flow review of commands, URLs, archive extraction, file paths,
  D-Bus methods, screenshots, exclusions, logging and release permissions.

The GNOME Shell integration smoke tests require GNOME's installed Shell test
resources and a disposable graphical session. Those resources were unavailable
to this non-destructive audit environment, so live compositor fuzzing and
end-to-end restore testing remain required before closing GNOME findings.

Severity describes impact and realistic prerequisites for this project:

- **High:** can execute code or compromise the update/release trust chain;
- **Medium:** can disclose sensitive desktop data or cause a persistent Shell
  availability problem under plausible conditions;
- **Low:** defence-in-depth issue within the already-compromised same-user
  boundary or limited diagnostic disclosure.

## Findings

### SS-2026-001 — Shell interpretation of saved GNOME commands

**Severity:** High  
**Status:** Open  
**Affected code:** `extension/sessionsifu@local/restoreSession.js` and
`template/launch-app.sh`

When no desktop application ID can be resolved, the restore engine joins the
saved `cmd` array with spaces, inserts it into a shell-script template, and
starts `bash -c`. Quotes, substitutions, separators and redirections inside a
modified session file are consequently interpreted by the shell. A session
file placed or altered below SessionSifu's session directory can run commands
as the logged-in user when that session is restored. Naturally captured command
arguments containing shell metacharacters can also restore incorrectly.

**Proposed fix:** remove the shell template and start a validated argument
vector directly with `Gio.Subprocess`. Require an absolute, regular executable;
cap argument count and length; reject control characters; and never fall back to
`sh`, `bash`, `cmd.exe`, PowerShell, `osascript`, or another interpreter because
of session contents. Treat legacy sessions containing only a command string as
untrusted and show a restore preview rather than executing them. Add adversarial
tests for quotes, `$()`, backticks, semicolons, newlines and leading options.

The portable base adapter is shell-free but still treats a stored executable
and its arguments as active configuration. Apply the same provenance warning,
executable allow-list/confirmation and restore preview on every platform.

### SS-2026-002 — Update checksum has no independent signature

**Severity:** High  
**Status:** Open  
**Affected code:** updater in `app/sessionsifu`, `updates/latest.json`

The updater correctly restricts HTTPS URLs to this repository, bounds response
sizes, verifies the declared package size and SHA-256, validates payload
versions, and installs without root. However, both digest and package are read
from mutable `main` content. Compromise of the repository, maintainer account,
release workflow or trusted delivery channel can replace both values and ship a
new user executable. A checksum from the same channel proves consistency, not
publisher authenticity.

**Proposed fix:** sign a canonical manifest with an offline Ed25519 release key
whose public key is embedded in the application. Bind version, package hash,
size, immutable release URL, minimum supported version, expiry and channel into
the signature. Reject rollback and expired metadata. Prefer immutable tagged
release assets, publish Sigstore/GitHub artifact attestations and retain a
documented offline recovery/rotation procedure. Keep SHA-256 as an additional
integrity check.

### SS-2026-003 — Mutable release inputs

**Severity:** Medium  
**Status:** Open  
**Affected code:** `.github/workflows/release.yml`, `portable/pyproject.toml`

Eight workflow steps reference moving major-version tags such as
`actions/checkout@v6` and `actions/upload-artifact@v4`. Portable builds resolve
open-ended dependency ranges directly from package indexes. A compromised or
silently changed action/dependency can influence release artifacts. The
top-level token is read-only and the release job narrows write access to tagged
publishing, which limits but does not remove this risk.

**Proposed fix:** pin every action to a reviewed full commit SHA, keep a comment
with the human-readable release tag, and enable the repository policy requiring
SHA pins. Generate platform lock files with exact versions and hashes, install
with `--require-hashes --only-binary :all:`, and update them through reviewed
automation. Emit an SBOM and signed provenance for each artifact, separate build
from publication, and publish only artifacts whose digest is included in the
signed manifest. GitHub states that a full commit SHA is the only immutable
action reference; pip's secure-install guidance likewise recommends locally
pinned hashes.

References: [GitHub secure use](https://docs.github.com/en/actions/reference/security/secure-use),
[pip secure installs](https://pip.pypa.io/en/stable/topics/secure-installs/).

### SS-2026-004 — Screenshot exclusion time-of-check gap

**Severity:** Medium  
**Status:** Open  
**Affected code:** `extension/sessionsifu@local/recallRecorder.js`

Recall skips image capture when an excluded application is visible before the
asynchronous desktop grab. It does not repeat that visibility check after the
grab and before publishing compressed JPEGs. An excluded application that
appears during that interval can be present in the stored full-display preview.
Changing exclusions later purges previews, but it cannot prevent the initial
write. Application matching is also best effort and cannot identify sensitive
content inside a permitted application.

**Proposed fix:** take a generation-stamped exclusion snapshot, check visibility
immediately before capture, immediately after capture, and again before each
atomic publish. Delete raw and compressed temporary files on any mismatch. Add
a compositor-session lock check at the same points, test rapid app open/close
races, and consider per-window capture/redaction where GNOME permits it. The UI
must continue to state that exclusions are best effort, not a password-field or
incognito detector.

### SS-2026-005 — GNOME session metadata is not consistently private

**Severity:** Medium  
**Status:** Open  
**Affected code:** `extension/sessionsifu@local/saveSession.js`

Named, history and continuously observed session directories are created with
mode `0744`; observed JSON files on the audited installation had mode `0664`.
The top directory currently lacks group/other execute permission, which blocks
ordinary traversal, but the nested data includes window titles, commands and
document paths and should not depend on a parent-directory accident for
confidentiality. Recall correctly uses `0700` directories and `0600` files.

**Proposed fix:** make every SessionSifu configuration directory `0700` and
every JSON/temporary/backup file `0600`, use private/no-follow creation flags,
and migrate existing content on startup. Verify ownership before changing a
tree, reject symlinked roots, fsync before atomic replacement where durability
matters, and add package/runtime tests that inspect actual modes under a
permissive umask.

### SS-2026-006 — User regex can block GNOME Shell

**Severity:** Medium  
**Status:** Open  
**Affected code:** `extension/sessionsifu@local/closeSession.js`

Close-window keyword rules compile and execute an unrestricted user-provided
regular expression synchronously inside GNOME Shell. Catastrophic backtracking
can block the compositor. The stored `method` and `compareWith` values are also
used for dynamic prototype lookups without a runtime allow-list, so malformed
settings can throw during a close operation.

**Proposed fix:** replace regex mode with bounded literal/glob matching, or use a
linear-time engine outside the Shell process. Enforce short input limits and
explicit allow-lists for methods and window fields at both settings-write and
runtime-read boundaries. Catch malformed legacy data, disable the offending
rule, and add pathological-pattern performance tests.

### SS-2026-007 — Broad same-user D-Bus control surface

**Severity:** Low  
**Status:** Accepted boundary; hardening open  
**Affected code:** `extension/sessionsifu@local/ui/autostart.js`

Any process able to access the user's session bus and SessionSifu name can call
save, restore, delete, Recall capture/list/delete and manager methods. This does
not cross the operating-system user boundary, and same-user malware already has
many equivalent capabilities, but it gives accidental or sandbox-escaped
clients a convenient control surface.

**Proposed fix:** document the boundary, split read-only and state-changing
interfaces, rate-limit capture/restore requests, and require an interactive
confirmation for destructive or application-launching calls not initiated by
the manager/top-bar UI. Keep parameter validation at every D-Bus entry point.

### SS-2026-008 — Diagnostic logs contain desktop metadata

**Severity:** Low  
**Status:** Open  
**Affected code:** GNOME extension logging and restore diagnostics

Normal and failure logs can include application names, window titles, command
lines and session paths. The user journal is not a public network channel, but
logs are commonly attached to bug reports and can outlive the session data.

**Proposed fix:** make normal logs structural and identifier-free, place paths,
titles and commands behind an explicit temporary debug mode, redact home paths
and URI query/fragment data, cap logged strings, and add a one-click sanitized
diagnostic export. Documentation must continue to warn users not to publish raw
session files or journals.

## Scanner results and triage

- **Bandit:** 12 low-confidence-context subprocess/import warnings; all Python
  process calls use argument arrays and `shell=False`. The stored-argument trust
  issue is nevertheless covered by SS-2026-001.
- **Semgrep:** 12 findings: eight mutable-action references (SS-2026-003), two
  dynamic `urllib` calls, one regex concern (SS-2026-006), and one object-assign
  warning. The updater validates both manifest and final redirect host/path, so
  the generic `file://` warning was not confirmed. Object assignment consumes
  local GSettings JSON; runtime schema allow-listing remains part of
  SS-2026-006.
- **Dependency audit:** no known vulnerabilities in the newest versions
  resolved for `psutil`, PySide6, dbus-next, PyObjC Cocoa, PyInstaller, Pillow,
  setuptools or wheel as of the audit date. This is not reproducible until
  versions and hashes are locked.
- **Secrets:** no current tracked secret candidates and no targeted credential
  pattern matches in Git history. Generated binary packages were excluded from
  entropy scanning and inspected as Debian archives instead.

## Positive controls retained

- Recall is off by default; file paths and screenshots require separate opt-ins.
- Recall parsing, result counts, file sizes, retention and image dimensions are
  bounded; Recall files use private modes and symlinks are rejected.
- Update URLs are HTTPS and repository-scoped; redirects, size, hash, payload
  version and required files are checked before unprivileged installation.
- Portable storage validates schema and collection bounds, confines loads to
  owned directories, rejects symlink session files and writes atomically.
- Restore application launch is gated during logout/reboot and window geometry
  is bounded before Mutter calls.
- The workflow declares read-only contents permission globally and grants write
  only to the tag release job.

## Remediation order

1. Remove shell-based restore and add malicious-session regression tests.
2. Change all session storage to private modes and migrate existing files.
3. Pin CI actions/dependencies and produce SBOM/provenance.
4. Design and deploy signed, rollback-resistant update metadata.
5. Close the Recall exclusion race and add privacy stress tests.
6. Remove or isolate unbounded regex matching from GNOME Shell.
7. Reduce D-Bus and diagnostic-log exposure.
8. Re-run static/dependency/secret scans plus live GNOME, Windows and macOS
   adversarial tests; record fixed versions beside each finding.

Closing a finding requires a focused code change, regression test, manual
platform validation where applicable, and release note. Documentation-only
changes do not change a finding's status.
