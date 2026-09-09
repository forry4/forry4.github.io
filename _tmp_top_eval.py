from _tmp_variants import Simple, base, Legacy
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.search import HeuristicPolicy, RandomPolicy
import time
mods={
 'tech':{'recruit':.55,'pval':.08,'cost':.01,'tech':.25,'techlvl':.03,'leader':.05,'effects':.25},
 'column':{'recruit':.7,'pval':.15,'cost':.02,'col':.3,'tech':.08,'leader':0,'effects':.3},
 'mix':{'recruit':.62,'pval':.12,'cost':.015,'col':.18,'tech':.18,'techlvl':.02,'leader':.02,'effects':.4},
 'tempochase':{'recruit':.6,'pval':.10,'cost':.01,'col':.28,'tech':.18,'techlvl':.025,'leader':.02,'effects':.45,'cap':2.2,'near':.32},
}
for name,m in mods.items():
 d=base.copy();d.update(m);p=Simple(name,d)
 for opp in [Legacy(),HeuristicPolicy(),RandomPolicy()]:
  t=time.time();r=run_arena(p,opp,pairs=16,seed=177,max_decisions=800,turn_budget=None);print(name,'vs',opp.name,r.wins,r.losses,r.score,r.pair_score,'t',round(time.time()-t,1),flush=True)
