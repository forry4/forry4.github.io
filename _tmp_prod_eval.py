from games.orbit import engine
from games.orbit.ai import serving
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.state import action_key,observation
from games.orbit.cards import CARDS,FACTIONS,PLANETS
import time
def old_score(o,m):
 a=m.get('action');s=0;seat=int(o.get('seat',0));players=o.get('players',[{},{}]);me=players[seat];card_id=m.get('card_id');card=CARDS.get(int(card_id)) if card_id is not None else None
 if card:
  cols=me.get('columns',[]);p=card['planet'];
  try:pi=PLANETS.index(p);n=len(cols[pi])
  except:pi=0;n=0
  if a=='recruit':
   cost=max(0,int(card['cost'])-n);s+=.42*(1-cost/10);pos=o.get('influence',[None]*5)[pi]
   if pos is not None:s+=.16*float(pos)*(1 if seat==0 else -1)/4
   s+=.04*(n>0)
  elif a=='technology':
   try:lv=int(me.get('technology',[])[FACTIONS.index(card['faction'])])
   except:lv=0
   s+=.25+.035*(5-lv)
  elif a=='leader':s+=.13+{'robot':.05,'human':.04,'animod':.045}.get(card['faction'],0)
 elif a=='mulligan':s+=.012*sum(5-int(CARDS.get(int(c),{}).get('cost',5)) for c in m.get('card_ids',[]))
 if 'planet' in m:
  try:pos=o.get('influence',[None]*5)[PLANETS.index(m['planet'])];s+=.18*float(pos)*(1 if seat==0 else -1)/4 if pos is not None else 0
  except:pass
 for p in m.get('planets',[]):
  try:pos=o.get('influence',[None]*5)[PLANETS.index(p)];s+=.08*float(pos)*(1 if seat==0 else -1)/4 if pos is not None else 0
  except:pass
 if m.get('accept') is True:s+=.025
 if 'tier' in m:s+=.018*int(m.get('tier') or 0)
 if m.get('cost'):s+=.01*int(m['cost'])
 if m.get('branch') is not None:s-=.0005*int(m.get('branch') or 0)
 return s
class Old:
 name='old'
 def choose(self,g,p,rng,**kw):
  o=observation(g,p);ms=sorted(engine.legal_moves(g,p),key=action_key); seed=rng.randrange(2**31)
  vals=[(old_score(o,m),action_key(m),m) for m in ms];best=max(x[0] for x in vals);ties=[x for x in vals if abs(x[0]-best)<1e-12];ties.sort(key=lambda x:x[1]);return ties[serving._seeded_tie_index(seed,len(ties))][2]
class Prod:
 name='hard-v2'
 def choose(self,g,p,rng,**kw):
  ms=sorted(engine.legal_moves(g,p),key=action_key);return serving.choose_move(observation(g,p),ms,None,5000,rng.randrange(2**31)).move if ms else None
class ProdDet:
 name='hard-v2-det'
 def choose(self,g,p,rng,**kw):
  ms=sorted(engine.legal_moves(g,p),key=action_key)
  if not ms:return None
  vals=[(serving._score(observation(g,p),m),action_key(m),m) for m in ms]
  return max(vals,key=lambda x:(x[0],x[1]))[2]
if __name__ == '__main__':
 for seed in [41,177,999,20260908]:
  t=time.time();r=run_arena(ProdDet(),Old(),pairs=32,seed=seed,max_decisions=800,turn_budget=None);print(seed,r.wins,r.losses,r.score,r.as_dict()['pair_ci95'],round(time.time()-t,1),flush=True)
