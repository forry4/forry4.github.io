from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.search import HeuristicPolicy,RandomPolicy
import time
d=base.copy();d.update({'recruit':.55,'pval':.08,'cost':.0749,'tech':.1945,'techlvl':.0016,'leader':.0457,'effects':.6941,'tier':.059});p=Simple('e03',d)
for opp in [Legacy(),HeuristicPolicy(),RandomPolicy()]:
 t=time.time();r=run_arena(p,opp,pairs=32,seed=20260908,max_decisions=800,turn_budget=None);print(opp.name,r.wins,r.losses,r.score,r.as_dict()['pair_ci95'],round(time.time()-t,1),flush=True)
