from __future__ import annotations
import platform
from dataclasses import dataclass


@dataclass(frozen=True)
class RuntimeProfile:
    name: str
    os: str
    arch: str
    accelerator: str
    python: str
    supports_cuda: bool
    supports_mps: bool

    def descriptor(self):
        return {
            "name": self.name,
            "os": self.os,
            "arch": self.arch,
            "accelerator": self.accelerator,
            "python": self.python,
            "supports_cuda": self.supports_cuda,
            "supports_mps": self.supports_mps,
        }


def profile():
    system = platform.system().lower()
    machine = platform.machine().lower()
    is_mac_arm = system == "darwin" and machine in ("arm64", "aarch64")
    is_linux = system == "linux"
    return RuntimeProfile(
        name="mac-lightweight"
        if is_mac_arm
        else "linux-cuda-capable"
        if is_linux
        else system + "-" + machine,
        os=system,
        arch=machine,
        accelerator="mps" if is_mac_arm else "cuda-possible" if is_linux else "cpu",
        python=platform.python_version(),
        supports_cuda=is_linux,
        supports_mps=is_mac_arm,
    )


def require_profile(descriptor, *, required_os=None, required_accelerator=None):
    if not isinstance(descriptor, dict):
        raise ValueError("runtime descriptor must be an object")
    if required_os and descriptor.get("os") != required_os:
        raise RuntimeError(
            f"runtime requires {required_os}, got {descriptor.get('os')}"
        )
    if required_accelerator and descriptor.get("accelerator") != required_accelerator:
        raise RuntimeError(
            f"runtime requires {required_accelerator}, got {descriptor.get('accelerator')}"
        )
    return descriptor
