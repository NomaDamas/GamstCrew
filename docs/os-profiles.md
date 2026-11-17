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
