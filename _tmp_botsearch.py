from games.orbit import engine,bot
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.state import action_key,observation
from games.orbit.ai.search import HeuristicPolicy
from _tmp_prod_eval import Old
import time
class Search:
 name='bot-search'
 def choose(self,g,p,rng,**kw):
  m=bot.choose_fallback_move(g,p,rng.randrange(2**31)); return m
for seed in [41,177,999,20260908]:
 t=time.time();r=run_arena(Search(),Old(),pairs=4,seed=seed,max_decisions=800,turn_budget=None);print(seed,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
