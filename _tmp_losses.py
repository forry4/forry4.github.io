from _tmp_variants import Simple,base,Legacy
from games.orbit.ai.selfplay import play_game
from games.orbit.ai.state import action_key
from games.orbit.ai.search import HeuristicPolicy
from games.orbit.ai.selfplay import board_configurations
d=base.copy();d.update({'recruit':.55,'pval':.08,'cost':.01,'tech':.30,'techlvl':.04,'leader':.05,'effects':.25});p=Simple('tech2',d);o=Legacy()
for i in range(32):
 c=board_configurations()[i%8]; seed=999+i*104729
 for swap in (0,1):
  ass=(p,o) if not swap else (o,p);ep=play_game(ass,seed=seed,configuration=c,max_decisions=800,turn_budget=None)
  cand_seat=0 if not swap else 1; won=ep.winner_seat==cand_seat
  if not won:
   print('LOSS',i,c,seed,'swap',swap,'winner',ep.winner_seat,'steps',len(ep.steps),'captures',[(s.actor_seat,s.action) for s in ep.steps if s.action.get('action') in ('recruit','technology','leader')][-15:])
