# OS profiles

`gamstcrew.os_profiles.profile()` reports OS, architecture, Python and accelerator hints. This is discovery only; a runtime must declare compatibility and readiness explicitly before it is used.

Profiles may additionally declare `lockfile` and `artifact` paths. The optional
`ProviderProfile.verify_artifacts(root)` helper verifies SHA-256 only when a
declared file exists under the supplied root; missing files remain explicitly
`unmeasured`, and a mismatch fails closed. Python metadata must use
`3.11`/`python 3.11`-style version syntax. Metadata alone is never presented as
installed or benchmark-accepted evidence.

## Profile manifests

`runtime-profiles.example.json` shows the required metadata shape. It is an
example only: `model_revision: manifest-pending` and the zero hash are not a
claim of installed weights or benchmark acceptance. A real profile must replace
both with a pinned revision and dependency-lock SHA256 before launch.

Launch also validates declared architecture metadata and verifies every
declared lockfile or artifact before starting a child process. A declared file
that is missing or mismatched fails closed; profiles without local artifacts
remain explicitly unmeasured and still require target-host acceptance.
When the host descriptor includes its Python version, launch compares the
major/minor pair with the profile's pinned Python metadata and rejects a
mismatch before spawning a child. A host descriptor without Python remains
backward-compatible and leaves that check unmeasured.
## Declarative profile catalog and diagnostics

Crew exposes `profile_catalog()`, `provider_compatibility()` and
`install_diagnostics()` for the five supported execution profiles: macOS
Apple Silicon, Linux CUDA, Linux CPU, Windows CPU/DirectML and Jetson ARM64.
Each provider reports `available`, `installed`, `runtime-compatible`,
`weight-ready` and `benchmark-accepted`. Diagnostics only inspect commands and
Python modules; they never install packages or download weights. Host
acceptance remains explicitly `unmeasured` until a target machine run is
attached.
