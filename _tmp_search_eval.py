import copy,time,math
from games.orbit import engine
from games.orbit.ai import serving
from games.orbit.ai.state import action_key, observation
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.search import SearchPolicy, InformationSetSearch, SearchConfig
import games.orbit.ai.search as S
from games.orbit.cards import CARDS,PLANETS,FACTIONS

class Legacy:
 name='legacy'
 def choose(self,g,p,rng,**kw):
  m=sorted(engine.legal_moves(g,p),key=action_key)
  return serving.choose_move(observation(g,p),m,None,0,0).move if m else None

def prog(c):
 return max((max(c.count(p) for p in PLANETS)/3 if c else 0),len(set(c))/4,len(c)/5)

def value(g,p):
 if engine.is_over(g):
  return 1 if engine.winner(g)==p else -1 if engine.winner(g) else 0
 other=g['order'][1-g['order'].index(p)]; me=g['players'][p]; th=g['players'][other]; d=1 if g['order'][0]==p else -1
 v=1.4*(prog(me['captured'])-prog(th['captured']))
 for pl,x in g['influence'].items():
  if x is None: continue
  q=x*d
  # nonlinear urgency, with own positive and enemy negative
  v += .11*q + .06*(q*q*q/27)
  if q>=2: v += .18
  if q<=-2: v -= .18
 v += .05*(len(me['captured'])-len(th['captured']))
 v += .018*(sum(me['technology'].values())-sum(th['technology'].values()))
 v += .03*(len(me['row_bonuses'])-len(th['row_bonuses']))
 v += .025*(me['credits']-th['credits']) + .04*(me['zenithium']-th['zenithium'])
 v += .005*(sum(CARDS[c]['cost'] for c in me['hand'])-sum(CARDS[c]['cost'] for c in th['hand']))
 return math.tanh(v)

def prior(g,p,m):
 # current value of main action but make imminent influence/capture dominate
 d=1 if g['order'][0]==p else -1; s=0; a=m.get('action'); me=g['players'][p]
 if 'card_id' in m:
  c=CARDS[int(m['card_id'])]; q=g['influence'][c['planet']]; q=0 if q is None else q*d
  if a=='recruit':
   s=.20 + .08*q + .03*(len(me['columns'][c['planet']])>0) - .008*max(0,c['cost']-len(me['columns'][c['planet']]))
   if q>=3: s+=1.4
   elif q>=2:s+=.3
  elif a=='technology': s=.09+.015*(5-me['technology'][c['faction']])
  elif a=='leader': s=.06 + (.06 if c['faction']=='animod' else .03)
 if 'planet' in m:
  q=g['influence'].get(m['planet']); q=0 if q is None else q*d; s+=.30*q
  if q>=3:s+=1.2
 if 'planets' in m:s+=sum(.25*((g['influence'][x] or 0)*d) for x in m['planets'])
 if m.get('accept') is True:s+=.15
 if 'tier' in m:s+=.05*m['tier']
 if 'branch' in m:s+=.02*(1-m['branch'])
 return s

def trial(pairs=4):
 oldv,oldp=S.state_value,S._fast_action_score
 S.state_value=value; S._fast_action_score=prior
 try:
  for sims,tm,dep in [(16,.03,48),(32,.04,64),(64,.06,80),(96,.10,96)]:
   pol=SearchPolicy(InformationSetSearch(SearchConfig(simulations=sims,time_limit=tm,max_depth=dep,exploration=1.2),opponent=Legacy()),name=f's{ sims}')
   t=time.time(); r=run_arena(pol,Legacy(),pairs=pairs,seed=41,max_decisions=800,turn_budget=None)
   print(pol.name,r.wins,r.losses,r.score,r.pair_score,'time',time.time()-t,flush=True)
 finally:S.state_value,S._fast_action_score=oldv,oldp
if __name__=='__main__':trial()
