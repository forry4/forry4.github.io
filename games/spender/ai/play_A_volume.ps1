# Playtest config A — current targeting (volume), rollout MCTS.
# Run from anywhere: .\play_A_volume.ps1   (Ctrl+C to stop)
Set-Location (Resolve-Path "$PSScriptRoot\..\..\..")  # repo root, so `games.spender` imports
$env:SPENDER_VALUE_MODEL = "none"                  # disable value-leaf -> rollout MCTS (card weights active)
Remove-Item Env:SPENDER_WEIGHTS -ErrorAction SilentlyContinue  # use the deployed weights
Write-Host "=== Config A: VOLUME targeting (deployed weights, rollout MCTS) ===" -ForegroundColor Cyan
uvicorn games.spender.main:app --reload
