import time
from _tmp_eval import Legacy, pos_score, card_value
from games.orbit import engine
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.state import action_key, observation
from games.orbit.cards import CARDS,PLANETS,FACTIONS
from games.orbit.effects import TECH_EFFECTS

class Simple:
 def __init__(self,name,weights): self.name=name; self.w=weights
 def choose(self,g,p,rng,**kw):
  o=observation(g,p); ms=sorted(engine.legal_moves(g,p),key=action_key); me=o['players'][o['seat']]; them=o['players'][1-o['seat']]; d=1 if o['seat']==0 else -1
  vals=[]
  for m in ms:
   a=m.get('action');s=0
   if a=='mulligan':
    s=sum((5-CARDS[int(c)]['cost'])*self.w['mull'] for c in m.get('card_ids',[]))
   elif a in ('recruit','technology','leader'):
    c=CARDS[int(m['card_id'])]; pv=pos_score(o,c['planet']); col=len(me['columns'][PLANETS.index(c['planet'])]); cost=max(0,c['cost']-col)
    if a=='recruit':
     s=self.w['recruit'] + self.w['pval']*pv - self.w['cost']*cost + self.w['col']*(col>0) + self.w['effects']*card_value(c['id'],o,me,them)
     if pv>=3:s+=self.w['cap']
     if pv>=2:s+=self.w['near']
    elif a=='technology':
     level=me['technology'][FACTIONS.index(c['faction'])]
     s=self.w['tech'] + self.w['techlvl']*(5-level)
     side=o['board_sides'][FACTIONS.index(c['faction'])]
     if self.w.get('techfx',0):
      s += self.w['techfx']*tech_effect_value(TECH_EFFECTS.get((c['faction'],side,level+1),[]),o,me,them)
    else:
     s=self.w['leader'] + self.w['animod']*(c['faction']=='animod') + self.w['leaderhold']*(o['leader']['owner']==o['seat'])
   else:
    task=(o.get('pending') or {}).get('task') or {}; typ=task.get('type')
    if 'planet' in m:
     pv=pos_score(o,m['planet']);s+=self.w['choice']*pv
     if typ in ('transfer','exile','exile_for_matching'): s+=self.w['deny']*len(them['columns'][PLANETS.index(m['planet'])])-self.w['choice_opp']*pv
     if typ in ('influence','influence_other','split_influence') and pv+(task.get('amount') or 1)>=4:s+=self.w['capchoice']
    if 'planets' in m:s+=self.w['choice']*sum(pos_score(o,x) for x in m['planets'])
    if m.get('accept') is True:s+=self.w['accept']
    if m.get('accept') is False:s+=self.w['decline']
    if 'tier' in m:s+=self.w['tier']*int(m['tier'])
    if 'faction' in m:s+=self.w['faction']*(5-me['technology'][FACTIONS.index(m['faction'])])
    if 'branch' in m:
     labels=((o.get('pending') or {}).get('task') or {}).get('branch_labels',[]); lab=(labels[m['branch']] if m['branch']<len(labels) else '').lower();s+=self.w['branch_influence'] if any(x in lab for x in ('influence','transfer')) else self.w['branch_resource']
    if 'bonus_area' in m:
     bonus_vals=o['planet_bonus'] if m['bonus_area']=='planet' else o['technology_bonus']; idx=(PLANETS if m['bonus_area']=='planet' else FACTIONS).index(m['slot']); tok=bonus_vals[idx];s+=self.w['bonus']*{1:1,2:1.2,3:4,4:2,5:1.5,6:2,7:2,8:2}.get(tok or 0,0)
    if 'card_id' in m:s-=self.w['discard']*CARDS[int(m['card_id'])]['cost']
   vals.append((s,action_key(m),m))
  return max(vals,key=lambda x:(x[0],x[1]))[2]

base={'recruit':.7,'pval':.1,'cost':.01,'col':.03,'effects':0,'cap':2,'near':.2,'tech':.2,'techlvl':.01,'leader':.05,'animod':.05,'leaderhold':.1,'mull':.01,'choice':.4,'choice_opp':.1,'deny':.2,'capchoice':2,'accept':.2,'decline':-.02,'tier':.1,'faction':.1,'branch_influence':.2,'branch_resource':.1,'bonus':.1,'discard':.02}

def tech_effect_value(tasks, o, me, them):
 s=0
 for t in tasks or []:
  k=t.get('type');a=t.get('amount',0)
  if k in ('influence','influence_other'): s+=.7*float(a)
  elif k=='split_influence': s+=.65*sum(t.get('amounts',[]))
  elif k in ('two_adjacent','adjacent_three','all_planets'): s+=.6*float(a or t.get('center',0)+2*t.get('neighbor',0) or 2)
  elif k in ('credits','zenithium'): s+=.09*float(a)
  elif k=='mobilize': s+=.12*float(t.get('count',0))
  elif k in ('transfer','exile','steal'): s+=.25*float(t.get('count',t.get('amount',1)))
  elif k=='draw_bonus': s+=.18
 return s
variants=[]
for name,mods in [
 ('rush',{'recruit':.9,'pval':.3,'cost':.02,'tech':.05,'leader':.0,'effects':0}),
 ('cheap',{'recruit':.8,'pval':.2,'cost':.08,'tech':.05,'leader':-.05,'effects':0}),
 ('effect',{'recruit':.55,'pval':.12,'cost':.01,'tech':.1,'leader':.02,'effects':1.0}),
 ('rush-effect',{'recruit':.75,'pval':.25,'cost':.04,'tech':.05,'leader':-.02,'effects':.35}),
 ('tech',{'recruit':.55,'pval':.08,'cost':.01,'tech':.25,'techlvl':.03,'leader':.05,'effects':.25}),
 ('deny',{'recruit':.75,'pval':.15,'cost':.02,'tech':.08,'leader':0,'effects':.1,'deny':.5}),
 ('column',{'recruit':.7,'pval':.15,'cost':.02,'col':.3,'tech':.08,'leader':0,'effects':.3}),
 ('conserve',{'recruit':.65,'pval':.15,'cost':.02,'tech':.12,'leader':.08,'effects':.4,'cap':1.5}),
 ]:
 d=base.copy(); d.update(mods); variants.append(Simple(name,d))
if __name__=='__main__':
 for pol in variants:
  t=time.time();r=run_arena(pol,Legacy(),pairs=8,seed=41,max_decisions=800,turn_budget=None); print(pol.name,r.wins,r.losses,r.score,r.pair_score,r.by_board, 't',round(time.time()-t,1),flush=True)
