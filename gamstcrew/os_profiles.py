from __future__ import annotations
import platform

def profile():
    system=platform.system().lower(); machine=platform.machine().lower()
    accelerator='mps' if system=='darwin' and machine in ('arm64','aarch64') else 'cuda-possible' if system=='linux' else 'cpu'
    return {'os':system,'arch':machine,'accelerator':accelerator,'python':platform.python_version()}
