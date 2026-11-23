"""Hardware-aware, explicit GAMST role installation and profile generation."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import ssl
import subprocess
import sys
import urllib.request

from .diagnostics import Requirement, check as diagnose
from .host_limits import HOST_LIMIT_MODES
from .os_profiles import profile as os_profile
from .registry import BASE, GOALS, ROLES, TIERS, Weight
from .resources import ResourceCapacity, ResourceRequest

PROFILE_VERSION = 1
DEFAULT_PREFIX = Path.home() / ".local" / "share" / "gamst"
DEFAULT_PROFILE = Path.home() / ".config" / "gamst" / "profile.json"


class SetupError(RuntimeError):
    """A plan or host cannot be applied without changing its meaning."""


def _run(args):
    command = [str(arg) for arg in args]
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as error:
        detail = (error.stderr or error.stdout or "").strip()[-4000:]
        raise SetupError(f"command failed ({error.returncode}): {command[0]}\n{detail}") from error


def _memory_bytes():
    try:
        if platform.system() == "Darwin":
            return int(subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True).strip())
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def _cuda_bytes():
    command = shutil.which("nvidia-smi")
    if not command:
        return 0
    try:
        result = subprocess.run(
            [command, "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            check=True, capture_output=True, text=True, timeout=5,
        )
        sizes = [int(line.strip()) * 1024 ** 2 for line in result.stdout.splitlines() if line.strip()]
        return max(sizes, default=0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return 0


def detect_hardware():
    """Read host capacity only; never capture media or change host settings."""
    runtime = os_profile()
    accelerator = runtime.accelerator
    vram = _cuda_bytes()
    if accelerator == "cuda-possible":
        accelerator = "cuda" if vram else "cpu"
    if accelerator == "mps":
        tier = "apple-mps"
    elif accelerator == "cuda":
        tier = "cuda-ge80gb" if vram >= 80 * 1024 ** 3 else "cuda-ge24gb" if vram >= 24 * 1024 ** 3 else "cuda-lt24gb"
    else:
        tier = "cpu-only"
    return {
        "os": runtime.os,
        "arch": runtime.arch,
        "python": runtime.python,
        "accelerator": accelerator,
        "tier": tier,
        "ram_bytes": _memory_bytes(),
        "vram_bytes": vram,
        "disk_free_bytes": shutil.disk_usage(Path.home()).free,
    }


def _normalize_hardware(value):
    if value is None:
        return detect_hardware()
    if not isinstance(value, dict):
        raise ValueError("hardware must be an object")
    result = dict(value)
    tier = result.get("tier")
    if tier not in TIERS:
        raise ValueError("hardware tier must be one of " + ", ".join(TIERS))
    result.setdefault("accelerator", "mps" if tier == "apple-mps" else "cuda" if tier.startswith("cuda-") else "cpu")
    result.setdefault("os", platform.system().lower())
    result.setdefault("arch", platform.machine().lower())
    result.setdefault("python", platform.python_version())
    for key in ("ram_bytes", "vram_bytes", "disk_free_bytes"):
        result.setdefault(key, 0)
        if type(result[key]) is not int or result[key] < 0:
            raise ValueError(key + " must be a non-negative integer")
    return result


def _parse_override(item):
    if not isinstance(item, str) or "=" not in item:
        raise ValueError("override must have the form role=model")
    role, model = item.split("=", 1)
    if role not in ROLES or not model:
        raise ValueError("unknown override role or empty model: " + role)
    return role, model


def _custom_candidate(role_id, specification):
    if role_id != "vision.detect" or not specification.startswith("custom:"):
        return None
    raw = specification[len("custom:"):]
    path = Path(raw).expanduser()
    if not path.is_absolute() or not path.is_file():
        raise ValueError("custom detection requires an existing absolute checkpoint path")
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    candidate = copy.deepcopy(ROLES[role_id].candidates["custom"])
    object.__setattr__(candidate, "weights", (Weight(path.name, path.as_uri(), digest.hexdigest(), path.stat().st_size, "measured local file"),))
    return candidate


def _closure(role_ids):
    selected = set(role_ids)
    pending = list(role_ids)
    while pending:
        role_id = pending.pop()
        if role_id not in ROLES:
            raise ValueError("unknown role: " + role_id)
        for dependency in ROLES[role_id].dependencies:
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    return sorted(selected)


def _device(candidate, hardware):
    accelerator = hardware["accelerator"]
    if accelerator in candidate.devices:
        return accelerator
    if "cpu" in candidate.devices:
        return "cpu"
    return accelerator


def _version_tuple(value):
    match = re.match(r"^(\d+)\.(\d+)", str(value))
    return tuple(int(part) for part in match.groups()) if match else (0, 0)


def make_plan(goals, overrides=(), hardware=None):
    """Resolve goals, dependencies and model overrides without installing anything."""
    if isinstance(goals, str):
        goals = [part for part in goals.split(",") if part]
    if isinstance(overrides, dict):
        overrides = [role + "=" + model for role, model in overrides.items()]
    goals = list(goals)
    if not goals:
        raise ValueError("at least one goal is required")
    unknown = set(goals) - set(GOALS)
    if unknown:
        raise ValueError("unknown goals: " + ", ".join(sorted(unknown)))
    parsed_overrides = dict(_parse_override(item) for item in overrides)
    role_ids = {role for goal in goals for role in GOALS[goal]} | set(parsed_overrides)
    role_ids = _closure(role_ids)
    host = _normalize_hardware(hardware)
    warnings = []
    roles = {}
    install = {}

    for role_id in role_ids:
        role = ROLES[role_id]
        override = parsed_overrides.get(role_id)
        model = override or role.defaults[host["tier"]]
        custom = _custom_candidate(role_id, model) if override else None
        if custom is not None:
            candidate = custom
            model = "custom"
        else:
            if model not in role.candidates:
                raise ValueError(f"unknown model {model!r} for {role_id}; choose from {', '.join(role.candidates)}")
            candidate = role.candidates[model]
        device = _device(candidate, host)
        diagnostic = diagnose(
            Requirement(python_minor=_version_tuple(candidate.python)[1], accelerator=None),
            python_version=_version_tuple(host["python"]), arch=host["arch"],
            os_name=host["os"], accelerator=host["accelerator"],
        )
        if diagnostic.status == "incompatible":
            warnings.append(f"{role_id}: {model} requires Python {candidate.python} or newer; host has {host['python']}")
        if device not in candidate.devices:
            warnings.append(f"{role_id}: {model} does not support {host['accelerator']}; supported devices: {', '.join(candidate.devices)}")
        if host["accelerator"] == "cuda" and candidate.min_vram_bytes > host["vram_bytes"]:
            warnings.append(f"{role_id}: {model} requires at least {candidate.min_vram_bytes / 1024 ** 3:g} GiB VRAM; detected {host['vram_bytes'] / 1024 ** 3:g} GiB")
        if model == "qwen3.5.9b" and host["accelerator"] != "cuda":
            warnings.append("vision.semantic_scene: Qwen3.5-9B requires CUDA with at least 24 GiB VRAM")
        if not candidate.automatic:
            warnings.append(f"{role_id}: {model} needs its documented manual preparation; apply will refuse an incomplete bundle")
        if any(weight.sha256 is None or weight.url is None for weight in candidate.weights):
            warnings.append(f"{role_id}: {model} has unpinned weights or no source URL; apply requires pinned downloadable files")
        if role.capture_fps:
            warnings.append(f"{role_id}: tossed-coin rotation requires >= {role.capture_fps} fps capture; about 240 fps is recommended for 36-40 turns/s")

        selection = candidate.as_dict()
        device_models = {"qwen3.asr_1_7b", "nemotron3", "video_depth.large", "factorizephys", "smolvlm.500m"}
        if "device" in selection["config"] or model in device_models:
            selection["config"]["device"] = device
        selection.update({"model": model, "role": role_id})
        roles[role_id] = selection

        if candidate.packages:
            environment = candidate.environment or candidate.id
            entry = install.setdefault(environment, {
                "environment": environment,
                "python": candidate.python,
                "packages": list(BASE),
                "roles": [],
                "models": [],
            })
            for package in candidate.packages:
                if package not in entry["packages"]:
                    entry["packages"].append(package)
            entry["roles"].append(role_id)
            entry["models"].append(model)

    ram = sum(item["resources"]["ram_bytes"] for item in roles.values())
    vram = sum(item["resources"]["vram_bytes"] for item in roles.values())
    disk = sum(item["resources"]["disk_bytes"] + sum(weight["size_bytes"] for weight in item["weights"]) for item in roles.values())
    ResourceCapacity(ram_bytes=host["ram_bytes"], vram_bytes=host["vram_bytes"])
    ResourceRequest(ram_bytes=ram, vram_bytes=vram)
    if host["ram_bytes"] and ram > host["ram_bytes"]:
        warnings.append(f"plan reserves {ram / 1024 ** 3:.1f} GiB RAM, above detected {host['ram_bytes'] / 1024 ** 3:.1f} GiB")
    if host["accelerator"] == "cuda" and host["vram_bytes"] and vram > host["vram_bytes"]:
        warnings.append(f"plan reserves {vram / 1024 ** 3:.1f} GiB VRAM, above detected {host['vram_bytes'] / 1024 ** 3:.1f} GiB")
    if host["disk_free_bytes"] and disk > host["disk_free_bytes"]:
        warnings.append(f"plan needs about {disk / 1024 ** 3:.1f} GiB disk, above available {host['disk_free_bytes'] / 1024 ** 3:.1f} GiB")
    if "accounting" not in HOST_LIMIT_MODES:
        raise AssertionError("accounting host-limit mode disappeared")
    return {
        "version": PROFILE_VERSION,
        "hardware": host,
        "goals": goals,
        "roles": roles,
        "install": list(install.values()),
        "totals": {"ram_bytes": ram, "vram_bytes": vram, "disk_bytes": disk},
        "warnings": list(dict.fromkeys(warnings)),
        "host_limits": "accounting; setup does not claim cgroup or OS enforcement",
    }


def _validate_plan(plan):
    if not isinstance(plan, dict) or plan.get("version") != PROFILE_VERSION:
        raise SetupError("plan must be a version 1 object")
    if not isinstance(plan.get("roles"), dict) or not plan["roles"]:
        raise SetupError("plan has no roles")
    host = _normalize_hardware(plan.get("hardware"))
    for role_id, selection in plan["roles"].items():
        if role_id not in ROLES or not isinstance(selection, dict):
            raise SetupError("plan contains an unknown role")
        model = selection.get("model")
        if model not in ROLES[role_id].candidates:
            raise SetupError(f"plan contains unknown model {model!r} for {role_id}")
        candidate = ROLES[role_id].candidates[model]
        if model != "custom" and selection.get("packages") != list(candidate.packages):
            raise SetupError(f"planned packages differ from the registry for {role_id}")
        if model != "custom" and selection.get("weights") != [weight.as_dict() for weight in candidate.weights]:
            raise SetupError(f"planned weights differ from the registry for {role_id}")
        if not candidate.automatic:
            raise SetupError(f"{role_id}: {model} requires documented manual preparation, not automatic apply")
        for weight in candidate.weights:
            if not weight.url or not weight.sha256:
                raise SetupError(f"{role_id}: {model} has no complete pinned download; provision it explicitly")
        if _version_tuple(host["python"]) < _version_tuple(candidate.python):
            raise SetupError(f"{role_id}: Python {candidate.python}+ is required")
    expected_install = {}
    for role_id, selection in plan["roles"].items():
        packages = selection.get("packages") or []
        if not packages:
            continue
        environment = selection.get("environment")
        entry = expected_install.setdefault(environment, {
            "environment": environment, "python": selection.get("python"),
            "packages": list(BASE), "roles": [], "models": [],
        })
        for package in packages:
            if package not in entry["packages"]:
                entry["packages"].append(package)
        entry["roles"].append(role_id)
        entry["models"].append(selection["model"])
    if plan.get("install") != list(expected_install.values()):
        raise SetupError("planned install environments differ from the selected roles")
    return plan


def _sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def download_weight(weight, destination):
    """Atomically download one file, refusing every digest or size mismatch."""
    destination = Path(destination)
    expected = weight.get("sha256")
    url = weight.get("url")
    if not expected or not re.fullmatch(r"[0-9a-f]{64}", expected) or not url:
        raise SetupError("a pinned URL and lowercase SHA256 are required")
    name = weight.get("name")
    if not isinstance(name, str) or Path(name).name != name:
        raise SetupError("weight name must be a plain filename")
    if destination.exists():
        actual = _sha256(destination)
        if actual != expected:
            raise SetupError(f"{name}: existing file sha256 mismatch (expected {expected}, got {actual})")
        return {"name": name, "path": str(destination), "sha256": actual, "bytes": destination.stat().st_size, "cached": True}
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".partial")
    temporary.unlink(missing_ok=True)
    try:
        try:
            import certifi
            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()
        digest = hashlib.sha256()
        size = 0
        with urllib.request.urlopen(url, timeout=120, context=context) as response, temporary.open("wb") as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                output.write(block)
                digest.update(block)
                size += len(block)
        actual = digest.hexdigest()
        expected_size = weight.get("size_bytes")
        if weight.get("size_source") == "pinned source bytes" and size != expected_size:
            raise SetupError(f"{name}: expected {expected_size} bytes, got {size}")
        if actual != expected:
            raise SetupError(f"{name}: sha256 mismatch (expected {expected}, got {actual})")
        temporary.replace(destination)
        return {"name": name, "path": str(destination), "sha256": actual, "bytes": size, "cached": False}
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _install_environment(entry, prefix):
    environment = entry["environment"]
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{0,63}", environment):
        raise SetupError("unsafe environment name")
    expected_packages = list(entry["packages"])
    if any(not isinstance(package, str) or package.startswith("-") or "\n" in package for package in expected_packages):
        raise SetupError("unsafe package requirement")
    target = prefix / "venvs" / environment
    python = target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    marker = target / ".gamstcrew-install.json"
    desired = {"packages": expected_packages}
    if marker.exists() and json.loads(marker.read_text()) == desired and python.is_file():
        return str(python), "cached"
    if not python.is_file():
        required = entry["python"]
        base_python = sys.executable if _version_tuple(platform.python_version()) >= _version_tuple(required) else shutil.which("python" + required)
        if not base_python:
            raise SetupError(f"Python {required}+ is required to create {environment}")
        _run([base_python, "-m", "venv", target])
    _run([python, "-m", "pip", "install", "--disable-pip-version-check", "--no-input", *expected_packages])
    marker.write_text(json.dumps(desired, sort_keys=True), encoding="utf-8")
    return str(python), "installed"


def _install_source(source, prefix, model):
    if not source:
        return None
    if set(source) != {"url", "revision"} or not re.fullmatch(r"[0-9a-f]{40}", source["revision"]):
        raise SetupError("source requires a URL and full pinned revision")
    target = prefix / "sources" / model
    if target.exists():
        if not (target / ".git").is_dir():
            raise SetupError(f"source directory exists but is not a checkout: {target}")
        actual = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
        if actual != source["revision"]:
            raise SetupError(f"existing {model} checkout is not at the planned revision")
        return str(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    _run(["git", "clone", "--no-checkout", source["url"], target])
    try:
        _run(["git", "-C", target, "checkout", "--detach", source["revision"]])
    except BaseException:
        shutil.rmtree(target)
        raise
    return str(target)


def _role_config(selection, weight_paths, source_dir):
    model = selection["model"]
    config = copy.deepcopy(selection.get("config") or {})
    first = next(iter(weight_paths), None)
    if model.startswith("rfdetr.") or model == "custom":
        config.update(path=first["path"], sha256=first["sha256"])
    elif model.startswith("yoloe."):
        checkpoint = next(item for item in weight_paths if item["name"].startswith("yoloe-"))
        encoder = next(item for item in weight_paths if item["name"] == "mobileclip2_b.ts")
        config.update(checkpoint_path=checkpoint["path"], checkpoint_sha256=checkpoint["sha256"],
                      encoder_path=encoder["path"], encoder_sha256=encoder["sha256"],
                      runtime_root=str(Path(checkpoint["path"]).parent))
    elif model.startswith("mediapipe.") or model in ("silero.vad", "yamnet", "depth_anything_v2.small"):
        config.update(path=first["path"], sha256=first["sha256"])
    elif model == "faster_whisper.small":
        config["model_path"] = str(Path(first["path"]).parent)
    elif model == "nemotron3":
        config["path"] = str(Path(first["path"]).parent)
    elif model == "video_depth.large":
        config.update(path=first["path"], sha256=first["sha256"], source_dir=source_dir)
    elif model == "factorizephys":
        config.update(checkpoint_path=first["path"], checkpoint_sha256=first["sha256"], source_dir=source_dir)
    return config


def apply_plan(plan, *, prefix=None, profile_path=None):
    """Apply exactly a validated plan and atomically write the shared GAMST profile."""
    _validate_plan(plan)
    prefix = Path(prefix or DEFAULT_PREFIX).expanduser().absolute()
    profile_path = Path(profile_path or DEFAULT_PROFILE).expanduser().absolute()
    prefix.mkdir(parents=True, exist_ok=True)
    pythons = {}
    environments = []
    for entry in plan.get("install", []):
        python, status = _install_environment(entry, prefix)
        pythons[entry["environment"]] = python
        environments.append({"environment": entry["environment"], "python": python, "status": status})

    profile_roles = {}
    artifacts = []
    for role_id, selection in plan["roles"].items():
        model = selection["model"]
        model_dir = prefix / "models" / model.replace(".", "-")
        downloaded = []
        for weight in selection.get("weights", []):
            result = download_weight(weight, model_dir / weight["name"])
            downloaded.append(result)
            artifacts.append(result)
        source_dir = _install_source(selection.get("source"), prefix, model.replace(".", "-"))
        config = _role_config(selection, downloaded, source_dir)
        profile_roles[role_id] = {
            "model": model,
            "provider_profile": selection.get("provider_profile"),
            "python": pythons.get(selection.get("environment")),
            "config": config,
        }

    existing = {"version": PROFILE_VERSION, "hardware": plan["hardware"], "roles": {}}
    if profile_path.exists():
        value = json.loads(profile_path.read_text(encoding="utf-8"))
        if value.get("version") != PROFILE_VERSION or not isinstance(value.get("roles"), dict):
            raise SetupError("existing profile is not a version 1 GAMST profile")
        existing = value
    existing["hardware"] = plan["hardware"]
    existing["roles"].update(profile_roles)
    profile_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = profile_path.with_name(profile_path.name + ".tmp")
    temporary.write_text(json.dumps(existing, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(profile_path)
    return {"profile": str(profile_path), "prefix": str(prefix), "roles": profile_roles,
            "environments": environments, "artifacts": artifacts}


def format_plan(plan):
    lines = [f"Hardware: {plan['hardware']['tier']} ({plan['hardware']['accelerator']})", "Roles:"]
    for role_id, selection in plan["roles"].items():
        lines.append(f"  {role_id}: {selection['model']} [{selection.get('provider_profile') or 'direct GAMST adapter'}]")
    if plan["install"]:
        lines.append("Install:")
        for entry in plan["install"]:
            lines.append(f"  {entry['environment']} (Python {entry['python']}+): {', '.join(entry['packages'])}")
    totals = plan["totals"]
    lines.append("Totals (planning reservations):")
    lines.append(f"  disk {totals['disk_bytes'] / 1024 ** 3:.2f} GiB; RAM {totals['ram_bytes'] / 1024 ** 3:.2f} GiB; VRAM {totals['vram_bytes'] / 1024 ** 3:.2f} GiB")
    if plan["warnings"]:
        lines.append("Warnings:")
        lines.extend("  - " + warning for warning in plan["warnings"])
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m gamstcrew.setup", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan_parser = subparsers.add_parser("plan", help="select roles and show the explicit install plan")
    plan_parser.add_argument("--goals", required=True, help="comma-separated goals: " + ", ".join(GOALS))
    plan_parser.add_argument("--override", action="append", default=[], metavar="ROLE=MODEL")
    plan_parser.add_argument("--json", action="store_true")
    apply_parser = subparsers.add_parser("apply", help="install only a saved plan")
    apply_parser.add_argument("plan", type=Path)
    apply_parser.add_argument("--prefix", type=Path)
    apply_parser.add_argument("--profile", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            plan = make_plan(args.goals, args.override)
            print(json.dumps(plan, indent=2) if args.json else format_plan(plan))
        else:
            result = apply_plan(json.loads(args.plan.read_text(encoding="utf-8")), prefix=args.prefix, profile_path=args.profile)
            print(json.dumps(result, indent=2))
        return 0
    except (OSError, ValueError, SetupError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        print(f"setup: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
