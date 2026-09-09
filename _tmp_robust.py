from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
import time
d=base.copy(); d.update({'recruit':.55,'pval':.08,'cost':.01,'tech':.25,'techlvl':.03,'leader':.05,'effects':.25})
p=Simple('tech',d)
for seed,pairs in [(41,32),(177,32),(999,32),(20260908,32)]:
 t=time.time(); r=run_arena(p,Legacy(),pairs=pairs,seed=seed,max_decisions=800,turn_budget=None); print(seed,r.wins,r.losses,r.score,r.pair_score,r.as_dict()['pair_ci95'], 't',round(time.time()-t,1),flush=True)
