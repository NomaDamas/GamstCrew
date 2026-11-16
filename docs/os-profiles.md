# OS profiles

`gamstcrew.os_profiles.profile()` reports OS, architecture, Python and accelerator hints. This is discovery only; a runtime must declare compatibility and readiness explicitly before it is used.

## Profile manifests

`runtime-profiles.example.json` shows the required metadata shape. It is an
example only: `model_revision: manifest-pending` and the zero hash are not a
claim of installed weights or benchmark acceptance. A real profile must replace
both with a pinned revision and dependency-lock SHA256 before launch.
