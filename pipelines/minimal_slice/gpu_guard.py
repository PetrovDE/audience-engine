import shutil
import subprocess


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


def ensure_gpu_available(context: str) -> None:
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
        "3) Verify service container visibility: run `docker compose "
        "--env-file infra/.env -f infra/docker-compose.dev.yml exec -T ollama "
        "nvidia-smi`.\n"
        "4) Confirm NVIDIA driver and NVIDIA Container Toolkit are installed."
    )
