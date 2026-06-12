# Playtest config B — high-value targeting, rollout MCTS (same search as A, only targeting differs).
# Run from anywhere: .\play_B_targeting.ps1   (Ctrl+C to stop)
Set-Location $PSScriptRoot
$env:SPENDER_VALUE_MODEL = "none"                                       # rollout MCTS (card weights active)
$env:SPENDER_WEIGHTS = "games/spender/weights.targeting.json"           # high-value targeting weights
Write-Host "=== Config B: HIGH-VALUE targeting (weights.targeting.json, rollout MCTS) ===" -ForegroundColor Magenta
uvicorn games.spender.main:app --reload
