from __future__ import annotations
import json
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

    def validate_for(self, host: dict):
        if host.get("os") not in self.runtime and self.runtime != "any":
            raise RuntimeError(f"{self.name} is not compatible with {host.get('os')}")
        if self.accelerator not in ("any", host.get("accelerator")) and not (
            self.accelerator == "cuda" and host.get("accelerator") == "cuda-possible"
        ):
            raise RuntimeError(f"{self.name} requires accelerator {self.accelerator}")
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
                    for key in (*required, "artifact_sha256")
                    if key in item
                }
            )
        )
    return profiles
