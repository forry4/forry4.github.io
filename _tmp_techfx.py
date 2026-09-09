from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
import time
mods={
'tech2':{'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'leader':.05,'effects':.25},
'fx1':{'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'techfx':.08,'leader':.05,'effects':.25},
'fx2':{'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'techfx':.18,'leader':.05,'effects':.25},
'fx3':{'recruit':.58,'pval':.10,'cost':.01,'tech':.26,'techlvl':.03,'techfx':.18,'leader':.05,'effects':.3},
'fx4':{'recruit':.60,'pval':.10,'cost':.012,'tech':.24,'techlvl':.03,'techfx':.3,'leader':.04,'effects':.35},
}
for name,mm in mods.items():
 d=base.copy();d.update(mm);p=Simple(name,d)
 for seed in [41,177,999]:
  t=time.time();r=run_arena(p,Legacy(),pairs=8,seed=seed,max_decisions=800,turn_budget=None); print(name,seed,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
