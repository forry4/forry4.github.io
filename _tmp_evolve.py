from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
import random,time
r=random.Random(20260908)
base_mod={'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'leader':.05,'effects':.25}
mods={'tech2':base_mod}
for i in range(15):
 m=base_mod.copy()
 for k,lo,hi in [('recruit',.42,.72),('pval',.02,.20),('cost',0,.09),('col',0,.35),('tech',.16,.42),('techlvl',.0,.07),('leader',-.05,.13),('effects',.05,.7),('cap',1.2,3.2),('near',.0,.45),('choice',.15,.7),('accept',.03,.5),('tier',.03,.3)]:
  if r.random()<.55:m[k]=round(r.uniform(lo,hi),4)
 mods[f'e{i:02}']=m
for name,m in mods.items():
 d=base.copy();d.update(m);p=Simple(name,d);scores=[];t=time.time()
 for seed in [41,177,999]:
  rr=run_arena(p,Legacy(),pairs=4,seed=seed,max_decisions=800,turn_budget=None);scores.append(rr.score)
 print(name,round(sum(scores)/len(scores),4),scores,m,round(time.time()-t,1),flush=True)
