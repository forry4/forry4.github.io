import math,time,random,copy
from games.orbit import engine
from games.orbit.ai import serving
from games.orbit.ai.state import action_key,observation
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.search import SearchPolicy,InformationSetSearch,SearchConfig
import games.orbit.ai.search as S
from games.orbit.cards import CARDS,PLANETS,FACTIONS

def old_score(o,m):
 a=m.get('action');s=0;seat=int(o.get('seat',0));me=o['players'][seat];cid=m.get('card_id');c=CARDS.get(int(cid)) if cid is not None else None
 if c:
  try:pi=PLANETS.index(c['planet']);n=len(me['columns'][pi])
  except:pi=0;n=0
  if a=='recruit':s+=.42*(1-max(0,c['cost']-n)/10)+.16*float(o['influence'][pi] or 0)*(1 if seat==0 else -1)/4+.04*(n>0)
  elif a=='technology':s+=.25+.035*(5-me['technology'][FACTIONS.index(c['faction'])])
  elif a=='leader':s+=.13+{'robot':.05,'human':.04,'animod':.045}.get(c['faction'],0)
 elif a=='mulligan':s+=.012*sum(5-CARDS.get(int(x),{}).get('cost',5) for x in m.get('card_ids',[]))
 for key,mul in [('planet',.18),('planets',.08)]:
  xs=[m[key]] if key=='planet' and key in m else m.get(key,[])
  for p in xs:
   try:pos=o['influence'][PLANETS.index(p)];s+=mul*float(pos or 0)*(1 if seat==0 else -1)/4
   except:pass
 if m.get('accept') is True:s+=.025
 if 'tier' in m:s+=.018*int(m['tier'] or 0)
 if m.get('cost'):s+=.01*int(m['cost'])
 if 'branch' in m:s-=.0005*int(m['branch'] or 0)
 return s
class Old:
 name='old'
 def choose(self,g,p,rng,**kw):
  ms=sorted(engine.legal_moves(g,p),key=action_key);o=observation(g,p);v=[(old_score(o,m),action_key(m),m) for m in ms];best=max(x[0] for x in v);t=[x for x in v if abs(x[0]-best)<1e-12];t.sort(key=lambda x:x[1]);return t[rng.randrange(len(t))][2]
def prog(c):return max((max(c.count(p) for p in PLANETS)/3 if c else 0),len(set(c))/4,len(c)/5)
def value(g,p):
 if engine.is_over(g):return 1 if engine.winner(g)==p else -1 if engine.winner(g) else 0
 o=g['order'][1-g['order'].index(p)];me=g['players'][p];th=g['players'][o];d=1 if g['order'][0]==p else -1
 v=1.4*(prog(me['captured'])-prog(th['captured']))
 for x in g['influence'].values():
  if x is None:continue
  q=x*d;v+=.11*q+.06*q*q*q/27+(0.18 if q>=2 else -.18 if q<=-2 else 0)
 v+=.05*(len(me['captured'])-len(th['captured']))+.018*(sum(me['technology'].values())-sum(th['technology'].values()))+.03*(len(me['row_bonuses'])-len(th['row_bonuses']))+.02*(me['credits']-th['credits'])+.03*(me['zenithium']-th['zenithium'])
 return math.tanh(v)
def prior(g,p,m):
 d=1 if g['order'][0]==p else -1;s=0;a=m.get('action');me=g['players'][p]
 if 'card_id' in m:
  c=CARDS[int(m['card_id'])];q=(g['influence'][c['planet']] or 0)*d
  if a=='recruit':s=.2+.08*q-.01*max(0,c['cost']-len(me['columns'][c['planet']]))+(.3 if q>=2 else 0)+(1.5 if q>=3 else 0)
  elif a=='technology':s=.12+.02*(5-me['technology'][c['faction']])
  else:s=.05
 if 'planet' in m:s+=.25*(g['influence'].get(m['planet']) or 0)*d
 if 'planets' in m:s+=.2*sum((g['influence'].get(x) or 0)*d for x in m['planets'])
 if m.get('accept') is True:s+=.1
 if 'tier' in m:s+=.05*m['tier']
 return s
oldv,oldp=S.state_value,S._fast_action_score;S.state_value=value;S._fast_action_score=prior
try:
 for sims,tm,dep,expl in [(8,.01,24,1.0),(16,.02,32,1.0),(24,.03,40,.8),(32,.04,48,.8)]:
  p=SearchPolicy(InformationSetSearch(SearchConfig(simulations=sims,time_limit=tm,max_depth=dep,exploration=expl),opponent=Old()),name=f's{sims}')
  t=time.time();r=run_arena(p,Old(),pairs=4,seed=41,max_decisions=800,turn_budget=None);print(p.name,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
finally:S.state_value,S._fast_action_score=oldv,oldp
