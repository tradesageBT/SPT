# Start SPT — backend + frontend
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "Starting FastAPI backend on http://localhost:8000 ..."
$backend = Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$Root\backend'; uvicorn main:app --reload --host 0.0.0.0 --port 8000" -PassThru

Write-Host "Starting React frontend on http://localhost:5173 ..."
$frontend = Start-Process powershell -ArgumentList "-NoExit", "-Command",
    "cd '$Root\frontend'; npm run dev" -PassThru

Write-Host ""
Write-Host "SPT is running:"
Write-Host "  Frontend  -> http://localhost:5173"
Write-Host "  API docs  -> http://localhost:8000/docs"
Write-Host ""
Write-Host "Close the terminal windows to stop."
