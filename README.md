# Audience Engine
Audience Engine with vector ranking on LLM embeddings.

## M4 Minimal Vertical Slice
This repo now includes a runnable minimal flow aligned to `docs/ARCHITECTURE_V3.md` and governance contracts:
1. Synthetic data generator
2. Feature mart snapshot builder
3. Embedding service (LangChain + Ollama)
4. Qdrant index creation + alias swap
5. Retrieval API (`POST /v1/retrieve`)
6. Policy gate (blacklist + frequency cap)
7. Export approved audience file
8. Integration runner script

## Quickstart
1. Start infra (`qdrant` + `ollama`) with `make dev-up`.
2. Install Python dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Run full slice:
   ```bash
   python -m pipelines.minimal_slice.run_flow
   ```
4. Start retrieval API:
   ```bash
   python -m uvicorn services.retrieval_api.app:app --host 0.0.0.0 --port 8000
   ```

PowerShell helper:
```powershell
./scripts/run_minimal_slice.ps1
```

Start API helper:
```powershell
./scripts/start_retrieval_api.ps1
```

## Generated Artifacts
Outputs are written under `data/minimal_slice/run/`:
- `synthetic_customers.jsonl`
- `feature_mart_snapshot.jsonl`
- `embeddings.jsonl`
- `approved_audience.jsonl`
- `run_summary.json`
