# Resume the v4 feature-enriched AZ training after a reboot (H2/H2N/H2R league mix).
# Run from PowerShell in this folder:   .\resume_v4.ps1
# It --resumes from checkpoints_v4_features (last completed iteration + 300k buffer),
# logs live to train_v4.log, and runs to iter 120. Ctrl-C to stop cleanly.
$env:PYTHONUNBUFFERED      = "1"
$env:OMP_NUM_THREADS       = "1"
$env:OPENBLAS_NUM_THREADS  = "1"
$env:MKL_NUM_THREADS       = "1"
$env:NUMEXPR_NUM_THREADS   = "1"
$env:VECLIB_MAXIMUM_THREADS = "1"

Set-Location "C:\Users\Forrest\forrestm_projects-ai"
$py = "C:\Users\Forrest\forrestm_projects\.venv\Scripts\python.exe"

& $py -m games.spender.ai.az.train_az `
  --iters 120 --games 400 --sims 512 --workers 10 `
  --train-steps 600 --batch-size 1024 --lr 1e-3 --buffer 300000 `
  --gate-games 80 --gate-sims 128 --gate-threshold 0.55 `
  --reward-shaping 0.5 --shaping-scale 6.0 --temperature 1.0 --temp-moves 20 --dirichlet-eps 0.35 `
  --league --self-frac 0.4 --heur-frac 0.4 --league-frac 0.2 --heur-variants H2,H2N,H2R `
  --opp-iters 30 --opp-sims 96 --pool-size 6 `
  --arena-every 10 --arena-games 100 --arena-sims 128 --arena-opp H2 `
  --out games/spender/ai/az/checkpoints_v4_features --resume `
  2>&1 | Tee-Object -FilePath "games\spender\ai\az\checkpoints_v4_features\train_v4.log"
