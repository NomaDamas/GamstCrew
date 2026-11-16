from __future__ import annotations
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
    runtime = ProcessRuntime(tuple(argv), descriptor)
    await manager.register_process(name, runtime)
    return runtime
