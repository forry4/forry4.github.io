from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
import time
mods={
'base':{},
'choicehi':{'choice':.8,'capchoice':3},
'choicelo':{'choice':.2,'capchoice':2},
'caphi':{'capchoice':4},
'acceptlo':{'accept':.05},
'accepthi':{'accept':.6},
'tierhi':{'tier':.25},
'denyhi':{'deny':.6,'choice_opp':.2},
'branch':{'branch_influence':.6,'branch_resource':.3},
'bonus':{'bonus':.5},
'all':{'choice':.8,'capchoice':3,'accept':.5,'tier':.2,'deny':.5,'choice_opp':.15,'branch_influence':.5,'branch_resource':.25,'bonus':.3},
}
for name,mm in mods.items():
 d=base.copy();d.update({'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'leader':.05,'effects':.25});d.update(mm);p=Simple(name,d);t=time.time();r=run_arena(p,Legacy(),pairs=8,seed=999,max_decisions=800,turn_budget=None);print(name,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
