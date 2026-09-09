exec(open('_tmp_search2.py').read().split("oldv,oldp=")[0])
oldv,oldp=S.state_value,S._fast_action_score;S.state_value=value;S._fast_action_score=prior
try:
 p=SearchPolicy(InformationSetSearch(SearchConfig(simulations=48,time_limit=.06,max_depth=60,exploration=.8),opponent=Old()),name='s48')
 for seed in [177,999,20260908]:
  t=time.time();r=run_arena(p,Old(),pairs=2,seed=seed,max_decisions=800,turn_budget=None);print(seed,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
finally:S.state_value,S._fast_action_score=oldv,oldp
