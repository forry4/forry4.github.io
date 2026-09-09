exec(open('_tmp_search2.py').read().split("oldv,oldp=")[0])
oldv,oldp=S.state_value,S._fast_action_score;S.state_value=value;S._fast_action_score=prior
try:
 p=SearchPolicy(InformationSetSearch(SearchConfig(simulations=24,time_limit=.03,max_depth=40,exploration=.8),opponent=Old()),name='s24')
 for seed in [41,177,999,20260908]:
  t=time.time();r=run_arena(p,Old(),pairs=4,seed=seed,max_decisions=800,turn_budget=None);print(seed,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
finally:S.state_value,S._fast_action_score=oldv,oldp
