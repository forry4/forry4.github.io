exec(open('_tmp_search2.py').read().split("oldv,oldp=")[0])
oldv,oldp=S.state_value,S._fast_action_score;S.state_value=value;S._fast_action_score=prior
try:
 for sims,tm,dep,expl in [(48,.06,60,.8),(96,.1,72,.8)]:
  p=SearchPolicy(InformationSetSearch(SearchConfig(simulations=sims,time_limit=tm,max_depth=dep,exploration=expl),opponent=Old()),name=f's{sims}')
  t=time.time();r=run_arena(p,Old(),pairs=2,seed=41,max_decisions=800,turn_budget=None);print(p.name,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
finally:S.state_value,S._fast_action_score=oldv,oldp
