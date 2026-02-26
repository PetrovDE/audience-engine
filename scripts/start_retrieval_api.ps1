param(
  [string]$PythonExe = "python",
  [int]$Port = 8000
)

& $PythonExe -m uvicorn services.retrieval_api.app:app --host 0.0.0.0 --port $Port

