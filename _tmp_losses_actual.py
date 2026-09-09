from _tmp_prod_eval import Old,ProdDet
from games.orbit.ai.selfplay import play_game,board_configurations
from games.orbit.ai.state import action_key
p=ProdDet();o=Old()
for i in range(16):
 c=board_configurations()[i%8];seed=41+i*104729
 for swap in (0,1):
  ep=play_game((p,o) if not swap else (o,p),seed=seed,configuration=c,max_decisions=800,turn_budget=None)
  cs=0 if not swap else 1
  if ep.winner_seat!=cs:
   print('LOSS',i,c,'swap',swap,'winner',ep.winner_seat,'steps',len(ep.steps))
   for st in ep.steps[:30]:
    if st.actor_seat==cs:print(' C',st.action)
    else: print(' O',st.action)
