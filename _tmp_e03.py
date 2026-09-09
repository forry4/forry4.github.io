from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
import time
d=base.copy();d.update({'recruit':.55,'pval':.08,'cost':.0749,'tech':.1945,'techlvl':.0016,'leader':.0457,'effects':.6941,'tier':.059});p=Simple('e03',d)
for seed in [41,177,999]:
 t=time.time();r=run_arena(p,Legacy(),pairs=32,seed=seed,max_decisions=800,turn_budget=None);print(seed,r.wins,r.losses,r.score,r.as_dict()['pair_ci95'],round(time.time()-t,1),flush=True)
