param(
  [string]$PythonExe = "python"
)

Write-Host "Running minimal vertical slice..."
& $PythonExe -m pipelines.minimal_slice.run_flow
exit $LASTEXITCODE
