import os
import shutil
import subprocess
from urllib.parse import urlparse

LOCAL_OLLAMA_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _torch_cuda_available() -> bool:
    try:
        import torch
    except Exception:
        return False
    try:
        return bool(torch.cuda.is_available())
    except Exception:
        return False


def _nvidia_smi_reports_gpu() -> bool:
    if shutil.which("nvidia-smi") is None:
        return False
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except Exception:
        return False

    if result.returncode != 0:
        return False

    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    return len(lines) > 0


def _ollama_host() -> str:
    raw = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").strip()
    if "://" not in raw:
        raw = f"http://{raw}"
    parsed = urlparse(raw)
    return (parsed.hostname or "localhost").lower()


def ensure_gpu_available(context: str) -> None:
    # When Ollama is external (for example host.docker.internal), GPU checks
    # should happen on the Ollama host, not in this local runtime.
    if _ollama_host() not in LOCAL_OLLAMA_HOSTS:
        return

    if _torch_cuda_available() or _nvidia_smi_reports_gpu():
        return

    raise RuntimeError(
        f"{context} requires an NVIDIA GPU but no GPU was detected. "
        "Preflight checks failed: torch.cuda.is_available() is false and "
        "nvidia-smi did not report any devices.\n"
        "Remediation:\n"
        "1) Verify host GPU visibility: run `nvidia-smi` on the host.\n"
        "2) Verify container passthrough: run `docker run --rm --gpus all "
        "nvidia/cuda:12.4.1-runtime-ubuntu22.04 nvidia-smi`.\n"
        "3) If Ollama runs externally, point `OLLAMA_BASE_URL` to that host "
        "(for example `http://host.docker.internal:11434` inside containers).\n"
        "4) Confirm NVIDIA driver and NVIDIA Container Toolkit are installed."
    )
