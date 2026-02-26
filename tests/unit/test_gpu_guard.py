from pipelines.minimal_slice import gpu_guard


def test_ensure_gpu_available_fails_without_torch_or_nvidia(monkeypatch):
    monkeypatch.setattr(gpu_guard, "_torch_cuda_available", lambda: False)
    monkeypatch.setattr(gpu_guard, "_nvidia_smi_reports_gpu", lambda: False)

    try:
        gpu_guard.ensure_gpu_available("Embedding jobs/services")
    except RuntimeError as exc:
        message = str(exc)
        assert "requires an NVIDIA GPU" in message
        assert "torch.cuda.is_available() is false" in message
        assert "Remediation:" in message
        return
    assert False, "Expected RuntimeError when no GPU is available"


def test_ensure_gpu_available_passes_with_torch_cuda(monkeypatch):
    monkeypatch.setattr(gpu_guard, "_torch_cuda_available", lambda: True)
    monkeypatch.setattr(gpu_guard, "_nvidia_smi_reports_gpu", lambda: False)
    gpu_guard.ensure_gpu_available("Embedding jobs/services")


def test_ensure_gpu_available_passes_with_nvidia_smi(monkeypatch):
    monkeypatch.setattr(gpu_guard, "_torch_cuda_available", lambda: False)
    monkeypatch.setattr(gpu_guard, "_nvidia_smi_reports_gpu", lambda: True)
    gpu_guard.ensure_gpu_available("Embedding jobs/services")
