from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import run_arena
for name,mm in {'tech2':{'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'leader':.05,'effects':.25},'techcol':{'recruit':.58,'pval':.1,'cost':.012,'col':.15,'tech':.25,'techlvl':.03,'leader':.03,'effects':.3}}.items():
 d=base.copy();d.update(mm);p=Simple(name,d);r=run_arena(p,Legacy(),pairs=16,seed=999,max_decisions=800,turn_budget=None);print(name,r.wins,r.losses,r.by_board)
