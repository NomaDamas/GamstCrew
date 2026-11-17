from __future__ import annotations
from pathlib import Path
from .manager import RuntimeManager
from .process_runtime import ProcessRuntime
from .registry import read_profiles
from .os_profiles import profile


async def launch_profile(manager: RuntimeManager, profiles_path, name, argv):
    """Launch a provider only after profile metadata and host compatibility validate."""
    descriptors = {item.name: item for item in read_profiles(profiles_path)}
    if name not in descriptors:
        raise KeyError(f"unknown runtime profile: {name}")
    descriptor = descriptors[name]
    descriptor.validate_for(profile().descriptor())
    # A declared lock/artifact is part of launch identity.  Metadata-only
    # profiles remain explicitly unmeasured, but a declared file must exist
    # and match before a child process is started.
    checks = descriptor.verify_artifacts(Path(profiles_path).parent)
    for field, status in checks.items():
        if status in ("missing", "mismatch"):
            raise RuntimeError(f"{name} {field} verification failed: {status}")
    runtime = ProcessRuntime(tuple(argv), descriptor)
    await manager.register_process(name, runtime)
    return runtime
