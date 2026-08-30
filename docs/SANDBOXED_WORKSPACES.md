# Sandboxed workspaces and development options

This research note supports the [SessionSifu roadmap](../ROADMAP.md). It was
reviewed on 30 August 2026 against upstream platform documentation. It is a
product and architecture assessment, not a claim that capsule functionality is
already shipped.

## Product idea

A SessionSifu workspace capsule would combine:

- a restorable selection of applications, documents and windows;
- an optional separate profile for supported browsers, editors and tools;
- an explicit persistence boundary for capsule-owned data;
- a visible permission plan for files, network, devices, clipboard and host
  services; and
- an optional OS-enforced sandbox or virtual machine when the platform can
  provide one.

The first design rule is vocabulary. A separate `XDG_CONFIG_HOME`, browser
profile or editor data directory prevents accidental state mixing, but it does
not contain a malicious process. The interface must call this a **profile
capsule**. The word **sandboxed** is reserved for a boundary enforced by the OS
or a reviewed containment framework.

## Feasibility by platform

### Linux

Flatpak is the preferred security-labelled pilot. A Flatpak application runs
in an application sandbox; host files, network, devices, other processes and
D-Bus services are unavailable unless explicitly granted. XDG Desktop Portals
provide user-mediated file, URI, screenshot and related access without giving
blanket host access. Per-application data already has a defined location below
`~/.var/app/<app-id>`.

SessionSifu should initially orchestrate only installed Flatpak applications
and existing portal flows. It should not rewrite global overrides silently or
attempt to repackage arbitrary host binaries at runtime. A capsule launch plan
must distinguish static package permissions from permissions that can really be
tightened for that launch.

Bubblewrap is a possible lower-level building block, but its own maintainers
state that it constructs namespaces rather than supplying a complete security
policy. Mounts, D-Bus exposure, seccomp and session handling determine whether
the result is a real boundary. SessionSifu should therefore avoid a generic
“sandbox any command” feature. If a future reviewed backend uses bubblewrap, it
must require a patched version, use a fixed policy generated from structured
fields and pass adversarial filesystem/D-Bus tests.

Containers such as rootless Podman are useful for development tools and
services, but a general GUI desktop container needs display, audio, portals,
GPU and user-data bridges that can erase much of the intended isolation. They
are better suited to a later developer-workspace backend than the first
consumer capsule.

### Windows

Windows Sandbox is immediately useful as an export target. A `.wsb` file can
control networking, clipboard, vGPU, protected-client mode, mapped folders and
a logon command. The secure SessionSifu preset should disable network,
clipboard, audio/video input and writable host mappings by default. Windows
deletes the sandbox contents when it closes, so durable results must be
exported deliberately to a dedicated mapped folder.

MSIX-packaged desktop applications can opt into AppContainer. Microsoft also
documents new process-sandbox APIs that can grant AppContainer isolation,
selected read-only/read-write paths, network policy and desktop interaction
limits. Those APIs are explicitly experimental, have no public header and are
subject to change. They are a research backend for cooperative apps on Windows
11, not a production promise or a way to contain every existing Win32 app.

### macOS

Apple App Sandbox is an entitlement selected by the app developer and enforced
for that signed app. It limits file, network and hardware access, and forbids
several operations SessionSifu's full manager may need, including arbitrary
Apple Events and accessibility control. SessionSifu can sandbox its own future
components, but it cannot truthfully retrofit App Sandbox onto unrelated
third-party applications.

Apple's Virtualization framework is the clean system-supported path for a real
guest boundary. It can run macOS or Linux guests and expose controlled virtual
devices. A capsule built this way has higher startup, memory and disk costs and
needs separate guest provisioning, updates and licensing review. It belongs
behind an optional “virtual workspace” edition, not the default restore path.

## Recommended implementation sequence

### Phase 1: manifest and profile separation

Build the shared model before selecting a containment backend:

1. Versioned manifest with stable application IDs and structured arguments.
2. Explicit profile root, selected input files, export directory, network
   intent, persistence policy and requested backend.
3. Preflight capability negotiation with no silent fallback.
4. Separate secrets: never copy browser cookies, keychains, tokens or password
   stores as ordinary profile data.
5. Atomic encrypted storage, quotas, provenance and a one-click delete-data
   action.

This phase can ship useful profile capsules for documented cooperative apps
without making a security claim.

### Phase 2: Flatpak and Windows Sandbox pilots

- Add a Flatpak application resolver and portal-first document chooser.
- Present effective permissions before launch and compare them with the saved
  capsule contract.
- Generate deterministic `.wsb` files with safe defaults and a dedicated
  export folder.
- Add automated tests that prove denied resources remain denied.
- Record the backend and effective policy in restore journals and diagnostics.

### Phase 3: VM and developer workspaces

- Prototype Virtualization.framework guests on macOS and a compatible VM
  backend on Linux/Windows.
- Treat VM snapshots as backend-owned artifacts with version, disk-space and
  encryption checks.
- Evaluate rootless containers for terminals, IDE helper services and build
  tools before attempting general GUI applications.
- Add reproducible manifests and signed adapter metadata.

## Other high-value development options

Workspace capsules are only one growth path. The following can improve the
product with less platform risk:

1. **Application adapter SDK.** A declarative, signed adapter format for public
   restore APIs, with fixtures and compatibility tests.
2. **Synthetic compatibility lab.** Disposable GNOME/KDE VMs plus Windows and
   macOS runners that exercise multi-window, multi-monitor, sleep/login and
   crash recovery using generated content.
3. **Recall quality laboratory.** Published OCR/accessibility benchmarks for
   mixed scaling, dark mode, Czech/English text and protected windows.
4. **Workspace manifest diff.** Explain what changed between two sessions and
   allow selective restore of apps, documents, monitors or capsule data.
5. **Encrypted user-controlled sync.** Synchronize only encrypted archives to
   a location chosen by the user; no SessionSifu account or server-side keys.
6. **Local activity graph.** Connect related sessions, documents and Recall
   moments locally, with per-source deletion and exclusion propagation.
7. **Energy-aware recording.** Bound capture/OCR by battery, idle and thermal
   state without weakening privacy or silently changing retention.
8. **Accessibility and localization.** Complete keyboard, screen-reader,
   reduced-motion, high-contrast and contributor-owned translation coverage.

## Approaches not recommended

- **Generic process-memory checkpointing for desktop apps.** CRIU documents
  that complete X application restore is not currently supported because of
  display-server and GPU state. Wayland adds compositor-owned objects and
  permissions. This remains unsuitable as a portable desktop promise.
- **A hand-built sandbox command editor.** A single broad mount or unfiltered
  session bus can defeat the boundary. Users should select capabilities, not
  write containment arguments.
- **Writable home-directory sharing by default.** It would allow a compromised
  application to alter startup files, credentials and unrelated documents.
- **Copying whole application profiles.** Profiles frequently contain tokens,
  cookies, local keys and device-bound databases. Adapters must enumerate
  allowed state explicitly.
- **Silent fallback.** If a requested backend is missing or a permission cannot
  be enforced, launch stops or the user explicitly changes to profile-only
  mode.

## Completion criteria for a security-labelled capsule

A backend may be called sandboxed only when all of the following are true:

- its supported OS and minimum backend version are detected;
- the effective file, network, device, clipboard and IPC policy is previewed;
- requested denials are verified by automated negative tests;
- application launch uses structured arguments without a shell;
- host inputs default to read-only and writable exports are separate;
- secrets and unrelated profile data are excluded;
- capture, Recall and export exclusions are rechecked after asynchronous work;
- logs contain outcomes and policy identifiers but no document contents or
  credentials; and
- failure cannot degrade invisibly to an ordinary host process.

## Primary references

- [Flatpak sandbox permissions](https://docs.flatpak.org/en/latest/sandbox-permissions.html)
- [XDG Desktop Portal API](https://docs.flatpak.org/en/latest/portal-api-reference.html)
- [Bubblewrap security model and limitations](https://github.com/containers/bubblewrap#sandboxing)
- [Windows Sandbox configuration](https://learn.microsoft.com/windows/security/application-security/application-isolation/windows-sandbox/windows-sandbox-configure-using-wsb-file)
- [MSIX AppContainer apps](https://learn.microsoft.com/windows/msix/msix-container)
- [Windows experimental process-sandbox APIs](https://learn.microsoft.com/windows/win32/secauthz/createprocessinsandbox)
- [Apple App Sandbox](https://developer.apple.com/documentation/security/app-sandbox)
- [Apple Virtualization framework](https://developer.apple.com/documentation/virtualization)
- [CRIU checkpoint/restore design](https://criu.org/Checkpoint/Restore)
- [CRIU X application limitation](https://criu.org/X_applications)
