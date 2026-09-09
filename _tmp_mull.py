from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
import time
for mv in [-.08,-.04,-.02,-.01,0,.01,.02,.04]:
 d=base.copy();d.update({'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'leader':.05,'effects':.25,'mull':mv});p=Simple(f'm{mv}',d);t=time.time();r=run_arena(p,Legacy(),pairs=16,seed=999,max_decisions=800,turn_budget=None);print(mv,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
