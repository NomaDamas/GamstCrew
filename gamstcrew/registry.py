from __future__ import annotations
import json
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    runtime: str
    python: str
    accelerator: str
    provider: str
    model_revision: str
    license: str
    lock_sha256: str
    artifact_sha256: str | None = None
    lockfile: str | None = None
    artifact: str | None = None
    arch: str | None = None

    def verify_artifacts(self, root=None):
        """Verify declared files when a profile ships them; metadata alone is not evidence."""
        base = Path(root) if root is not None else Path.cwd()
        checks = {}
        for field, expected in (("lockfile", self.lock_sha256), ("artifact", self.artifact_sha256)):
            path = getattr(self, field)
            if not path:
                checks[field] = "unmeasured"
                continue
            candidate = (base / path).resolve()
            if base.resolve() not in candidate.parents and candidate != base.resolve():
                raise ValueError(f"{field} path escapes profile root")
            if not candidate.is_file():
                checks[field] = "missing"
                continue
            digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
            checks[field] = "verified" if digest == expected else "mismatch"
            if digest != expected:
                raise ValueError(f"{field} sha256 mismatch")
        return checks

    def validate_for(self, host: dict):
        if host.get("os") not in self.runtime and self.runtime != "any":
            raise RuntimeError(f"{self.name} is not compatible with {host.get('os')}")
        if self.accelerator not in ("any", host.get("accelerator")) and not (
            self.accelerator == "cuda" and host.get("accelerator") == "cuda-possible"
        ):
            raise RuntimeError(f"{self.name} requires accelerator {self.accelerator}")
        if self.arch not in (None, "any"):
            host_arch = str(host.get("arch", "")).lower()
            allowed = {part.strip().lower() for part in str(self.arch).split(",") if part.strip()}
            if host_arch not in allowed:
                raise RuntimeError(f"{self.name} requires architecture {self.arch}")
        match = re.fullmatch(r"(?:python)?\s*(\d+)\.(\d+)(?:\.(\d+))?", self.python)
        if not match:
            raise ValueError(f"{self.name} has invalid python version metadata")
        host_python = host.get("python")
        if host_python is not None:
            host_match = re.fullmatch(
                r"(?:python)?\s*(\d+)\.(\d+)(?:\.(\d+))?", str(host_python)
            )
            if host_match is None:
                raise ValueError("host has invalid python version metadata")
            required = (int(match.group(1)), int(match.group(2)))
            actual = (int(host_match.group(1)), int(host_match.group(2)))
            if actual != required:
                raise RuntimeError(
                    f"{self.name} requires Python {required[0]}.{required[1]}, "
                    f"got {actual[0]}.{actual[1]}"
                )
        return True


def read_profiles(path):
    payload = json.loads(Path(path).read_text())
    if not isinstance(payload, list) or not payload or len(payload) > 128:
        raise ValueError("profiles must be a bounded non-empty list")
    profiles = []
    names = set()
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("profile must be an object")
        required = (
            "name",
            "runtime",
            "python",
            "accelerator",
            "provider",
            "model_revision",
            "license",
            "lock_sha256",
        )
        if any(not isinstance(item.get(key), str) or not item[key] for key in required):
            raise ValueError("profile metadata is incomplete")
        if len(item["lock_sha256"]) != 64 or any(
            c not in "0123456789abcdef" for c in item["lock_sha256"]
        ):
            raise ValueError("invalid lock sha256")
        if item["name"] in names:
            raise ValueError("duplicate provider profile")
        names.add(item["name"])
        profiles.append(
            ProviderProfile(
                **{
                    key: item[key]
                    for key in (*required, "artifact_sha256", "lockfile", "artifact", "arch")
                    if key in item
                }
            )
        )
    return profiles
