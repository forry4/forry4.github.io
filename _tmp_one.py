from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.search import HeuristicPolicy,RandomPolicy
import time
d=base.copy();d.update({'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'leader':.05,'effects':.25});p=Simple('tech2',d)
for opp in [Legacy(),HeuristicPolicy(),RandomPolicy()]:
 t=time.time();r=run_arena(p,opp,pairs=32,seed=999,max_decisions=800,turn_budget=None);print(opp.name,r.wins,r.losses,r.score,r.as_dict()['pair_ci95'],round(time.time()-t,1),flush=True)
