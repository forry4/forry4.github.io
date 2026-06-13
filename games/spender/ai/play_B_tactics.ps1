# Playtest config B — deployed weights + opponent-aware tactics (rollout MCTS).
# Identical to play_A_volume.ps1 (deployed weights) EXCEPT four hand-tuned tactical
# features are switched on, so the only difference vs A is the new strategy:
#   contested_weight        prefer cards the opponent can also afford (shared-good)
#   block_efficiency_weight block the cheap, high-value cards (not any 3-pointer)
#   block_noble_weight      block cards that hand the opponent a noble they're near
#   noble_race_weight       rush nobles the opponent is also racing (claim first)
# Run from anywhere: .\play_B_tactics.ps1   (Ctrl+C to stop)
Set-Location (Resolve-Path "$PSScriptRoot\..\..\..")                    # repo root, so `games.spender` imports
$env:SPENDER_VALUE_MODEL = "none"                                       # rollout MCTS (card weights active)
$env:SPENDER_WEIGHTS = "games/spender/ai/weights.tactics.json"         # deployed weights + tactical features on
Write-Host "=== Config B: opponent-aware TACTICS (weights.tactics.json, rollout MCTS) ===" -ForegroundColor Green
uvicorn games.spender.main:app --reload
