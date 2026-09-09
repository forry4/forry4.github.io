from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
import time
mods={
'tech':{'recruit':.55,'pval':.08,'cost':.01,'tech':.25,'techlvl':.03,'leader':.05,'effects':.25},
'tech0':{'recruit':.55,'pval':.08,'cost':.01,'tech':.25,'techlvl':.03,'leader':.05,'effects':0},
'tech2':{'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'leader':.05,'effects':.25},
'techcol':{'recruit':.58,'pval':.1,'cost':.012,'col':.15,'tech':.25,'techlvl':.03,'leader':.03,'effects':.3},
'effect':{'recruit':.55,'pval':.12,'cost':.01,'tech':.1,'leader':.02,'effects':1.0},
'mix':{'recruit':.62,'pval':.12,'cost':.015,'col':.18,'tech':.18,'techlvl':.02,'leader':.02,'effects':.4},
'tempochase':{'recruit':.6,'pval':.10,'cost':.01,'col':.28,'tech':.18,'techlvl':.025,'leader':.02,'effects':.45,'cap':2.2,'near':.32},
}
for name,mm in mods.items():
 d=base.copy();d.update(mm);p=Simple(name,d)
 for seed in [41,177,999]:
  t=time.time();r=run_arena(p,Legacy(),pairs=16,seed=seed,max_decisions=800,turn_budget=None);print(name,seed,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
