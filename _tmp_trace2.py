from _tmp_eval import Tactical, Legacy
from games.orbit import engine
from games.orbit.ai.state import action_key
g=engine.new_game(['a','b'],seed=59,configuration={'robot':2,'human':2,'animod':2})
p={'a':Tactical('v1'),'b':Legacy()}
for pid in list(g['order']): engine.apply_move(g,pid,{'action':'mulligan','card_ids':[]})
for n in range(120):
 if engine.is_over(g): break
 pid=g['pending_pid'] if g.get('pending') else g['turn_pid']; m=p[pid].choose(g,pid,None)
 print(n,pid,m,'infl',g['influence'],'cap',[(x,len(g['players'][x]['captured'])) for x in g['order']])
 ok,e=engine.apply_move(g,pid,m)
 if not ok: print('BAD',e);break
print('result',g['phase'],g.get('winner'),g['turn_number'])
