from _tmp_variants import Simple,base
from games.orbit import engine
from games.orbit.ai.serving import choose_move,_score
from games.orbit.ai.state import observation,action_key
import random
d=base.copy();d.update({'recruit':.55,'pval':.08,'cost':.0749,'tech':.1945,'techlvl':.0016,'leader':.0457,'effects':.6941,'tier':.059});p=Simple('e03',d)
for seed in range(20):
 g=engine.new_game(['a','b'],seed=seed)
 for pid in list(g['order']):
  m={'action':'mulligan','card_ids':[]};engine.apply_move(g,pid,m)
 for _ in range(20):
  if engine.is_over(g):break
  pid=g['pending_pid'] if g.get('pending') else g['turn_pid'];legal=sorted(engine.legal_moves(g,pid),key=action_key);obs=observation(g,pid)
  a=p.choose(g,pid,None)
  vals=[(_score(obs,m),action_key(m),m) for m in legal]
  b=max(vals,key=lambda x:(x[0],x[1]))[2]
  if a!=b: print('DIFF',seed,pid,a,b,[(m, round(__import__('games.orbit.ai.serving',fromlist=['_score'])._score(obs,m),3)) for m in legal]); raise SystemExit
  engine.apply_move(g,pid,a)
print('all-match')
