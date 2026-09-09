import copy, random, time
from games.orbit import engine
from games.orbit.ai import serving
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.state import action_key, observation
from games.orbit.cards import CARDS, PLANETS, FACTIONS
from games.orbit.effects import CARD_EFFECTS, TECH_EFFECTS

class Legacy:
    name='legacy'
    def choose(self,game,pid,rng,**kw):
        moves=sorted(engine.legal_moves(game,pid),key=action_key)
        return serving.choose_move(observation(game,pid),moves,None,0,0).move if moves else None

def direction(obs): return 1 if int(obs['seat'])==0 else -1
def pos_score(obs, planet):
    try: p=obs['influence'][PLANETS.index(planet)]
    except: return 0
    return 0 if p is None else direction(obs)*float(p)

def flat_effect(tasks):
    out=[]
    for t in tasks or []:
        if not isinstance(t,dict): continue
        out.append(t)
        for key in ('then',): out += flat_effect(t.get(key,[]))
        for b in t.get('branches',[]): out += flat_effect(b.get('tasks',[]))
    return out

def eff_score(obs, card_id, planet):
    s=0
    for t in flat_effect(CARD_EFFECTS.get(int(card_id),[])):
        k=t.get('type'); a=t.get('amount',0)
        if k in ('influence','influence_other'):
            target=t.get('planet')
            s += 0.52*float(a) if target is None else 0.7*float(a)*max(0.4, 1+0.18*pos_score(obs,target))
        elif k in ('split_influence',): s += 0.42*sum(t.get('amounts',[]))
        elif k in ('adjacent_three','two_adjacent','all_planets'): s += 0.38*float(a or t.get('center',0)+2*t.get('neighbor',0) or 2)
        elif k in ('credits','zenithium'): s += 0.018*float(a)
        elif k in ('mobilize','transfer','exile','exile_tier','exile_for_matching','optional_exile_each','take_board_bonus','draw_bonus','per_nonempty','per_tech_first','develop','leader'): s += {'mobilize':.18,'transfer':.2,'exile':.15,'exile_tier':.22,'exile_for_matching':.28,'optional_exile_each':.25,'take_board_bonus':.25,'draw_bonus':.18,'per_nonempty':.03,'per_tech_first':.07,'develop':.13,'leader':.16}.get(k,.12)
        elif k in ('choose_branch','optional','if_leader','if_credits','spend_tier','reset_planet','discard_hand'): s += .08
    return s

class Aggressive:
    def __init__(self, mode='a'): self.name='agg-'+mode; self.mode=mode
    def choose(self, game,pid,rng,**kw):
        obs=observation(game,pid); moves=sorted(engine.legal_moves(game,pid),key=action_key)
        if not moves: return None
        me=obs['players'][obs['seat']]; them=obs['players'][1-obs['seat']]
        scored=[]
        for m in moves:
            a=m.get('action'); s=0
            # choices first
            if a=='mulligan':
                costs=[CARDS[int(c)]['cost'] for c in m.get('card_ids',[])]
                # retain expensive cards, trade cheap only
                s=sum(5-c for c in costs)*(-1 if self.mode=='keep' else 1)*.01
            elif a in ('recruit','technology','leader'):
                c=CARDS[int(m['card_id'])]; p=c['planet']; pval=pos_score(obs,p)
                col=len(me['columns'][PLANETS.index(p)])
                if a=='recruit':
                    cost=max(0,c['cost']-col)
                    # action value dominated by race progress + rich effects
                    s=0.70 + 0.085*pval + 0.035*(col>0) - 0.012*cost + eff_score(obs,m['card_id'],p)
                    # thresholds: a recruit always adds one to this planet
                    if pval>=2.5: s += 1.2
                    if pval>=1.5: s += .28
                    # do not waste influence on already captured disc this turn
                    if obs['influence'][PLANETS.index(p)] is None: s -= 1
                elif a=='technology':
                    level=me['technology'][FACTIONS.index(c['faction'])]
                    s=.30 + .018*(5-level) + .02*level
                    # higher levels are often strong but technology burns z
                    if level==0: s += .08
                else:
                    s=.10 + ({'robot':.05,'human':.04,'animod':.12}[c['faction']])
                    if obs['leader']['owner']==obs['seat']: s += .15
            else:
                # choice actions
                if 'planet' in m:
                    p=m['planet']; pv=pos_score(obs,p)
                    # influence choices go where our disc is furthest toward capture;
                    # transfers/exiles go after opponent's fullest column.
                    task=(obs.get('pending') or {}).get('task') or {}; typ=task.get('type')
                    s += .4*pv
                    if typ in ('transfer','exile','exile_for_matching'):
                        s += 0.22*len(them['columns'][PLANETS.index(p)]) - .1*pv
                    if typ in ('influence','influence_other','split_influence'): s += .45*pv
                if 'planets' in m: s += sum(.3*pos_score(obs,p) for p in m['planets'])
                if m.get('accept') is True: s += .35
                elif m.get('accept') is False: s -= .05
                if 'tier' in m: s += .12*int(m.get('tier') or 0)
                if 'faction' in m:
                    f=m['faction']; s += .15*(5-me['technology'][FACTIONS.index(f)])
                if 'branch' in m:
                    labels=((obs.get('pending') or {}).get('task') or {}).get('branch_labels',[])
                    lab=(labels[m['branch']] if m['branch']<len(labels) else '') .lower()
                    if any(x in lab for x in ('influence','transfer','zenithium','leader')): s+=.18
                if 'bonus_area' in m:
                    vals=obs['planet_bonus'] if m['bonus_area']=='planet' else obs['technology_bonus']; idx=(PLANETS if m['bonus_area']=='planet' else FACTIONS).index(m['slot']); tok=vals[idx]
                    s += {1:.12,2:.15,3:.5,4:.25,5:.2,6:.2,7:.2,8:.25}.get(tok or 0,.1)
                if 'card_id' in m:
                    s -= .02*CARDS[int(m['card_id'])]['cost']
            scored.append((s,action_key(m),m))
        return max(scored,key=lambda x:(x[0],x[1]))[2]

def card_value(cid, obs, me, them):
    def walk(ts, mult=1.0):
        total=0.0
        for t in ts or []:
            k=t.get('type'); a=t.get('amount',0)
            if k=='influence':
                if t.get('planet'): total += .42*float(a)*(1+.14*pos_score(obs,t['planet']))
                else: total += .48*float(a)
            elif k=='influence_other': total += .45*float(a)
            elif k=='split_influence': total += .44*sum(t.get('amounts',[]))
            elif k=='adjacent_three': total += .42*(t.get('center',0)+2*t.get('neighbor',0))
            elif k=='two_adjacent': total += .42*2*float(a)
            elif k=='all_planets': total += .38*5*float(a)
            elif k=='credits': total += .028*float(a)
            elif k=='zenithium': total += .09*float(a)
            elif k=='per_tech_first': total += .055*sum(x>=1 for x in me['technology'])*float(a)
            elif k=='per_nonempty':
                owner=me if t.get('owner')=='self' else them
                total += .025*sum(bool(x) for x in owner['columns'])*float(a)
            elif k=='mobilize': total += .10*float(t.get('count',0))
            elif k=='transfer': total += .25*float(t.get('count',0))
            elif k=='exile': total += .20*float(t.get('count',0))
            elif k=='exile_tier': total += .28
            elif k=='exile_for_matching': total += .28*float(t.get('count',1))
            elif k=='optional_exile_each': total += .15*len(t.get('planets',[]))
            elif k=='draw_bonus': total += .16
            elif k=='develop': total += .18
            elif k=='leader': total += .28 + .08*(t.get('level',1)>=2)
            elif k=='take_board_bonus': total += .2
            elif k=='spend_tier': total += .5
            elif k=='discard_hand': total += .08
            elif k=='choose_branch': total += max(walk(b.get('tasks',[])) for b in t.get('branches',[])) if t.get('branches') else 0
            elif k=='optional': total += walk(t.get('then',[]))*.75
            elif k=='if_leader': total += walk(t.get('then',[]))*(1 if obs.get('leader',{}).get('owner')==obs.get('seat') else .2)
            elif k=='if_credits': total += walk(t.get('then',[]))*(1 if me['credits']>=t.get('amount',0) else 0)
            elif k in ('transfer_each',): total += .25*sum(bool(x) for x in them['columns'])
            elif k in ('reset_planet',): total += .2
        return total
    return walk(CARD_EFFECTS.get(int(cid),[]))

class Tactical(Aggressive):
    def __init__(self, variant='v1'): self.name='tac-'+variant; self.variant=variant
    def choose(self, game,pid,rng,**kw):
        obs=observation(game,pid); moves=sorted(engine.legal_moves(game,pid),key=action_key)
        if not moves:return None
        me=obs['players'][obs['seat']]; them=obs['players'][1-obs['seat']]
        out=[]
        for m in moves:
            a=m.get('action'); s=0
            task=(obs.get('pending') or {}).get('task') or {}; typ=task.get('type')
            if a=='mulligan':
                # retain expensive cards; discard cards that are low value
                disc=m.get('card_ids',[])
                s = sum((CARDS[int(c)]['cost']*.01 - card_value(c,obs,me,them)*.08) for c in disc)
            elif a in ('recruit','technology','leader'):
                c=CARDS[int(m['card_id'])]; pi=PLANETS.index(c['planet']); pval=pos_score(obs,c['planet']); col=len(me['columns'][pi]); cost=max(0,c['cost']-col)
                if a=='recruit':
                    s=0.42 + 0.15*pval + .04*(col>0) - .012*cost + card_value(c['id'],obs,me,them)
                    # immediate capture is decisive; account for card's own +1
                    if pval >= 3: s += 2.2
                    elif pval >= 2: s += .45
                    if obs['influence'][pi] is None: s -= 1.5
                elif a=='technology':
                    f=c['faction']; level=me['technology'][FACTIONS.index(f)]; side=obs['board_sides'][FACTIONS.index(f)]
                    nxt=level+1
                    tech=TECH_EFFECTS.get((f,side,nxt),[])
                    s=.13 + .08*walktech(tech,obs,me,them) - .02*level
                    if level==0:s+=.04
                else:
                    s=.08 + ({'robot':.10,'human':.07,'animod':.22}[c['faction']]) + (.2 if obs['leader']['owner']==obs['seat'] else 0)
                    # leader gives a useful hand limit but costs one card tempo
                    if c['faction']=='animod': s += .09
            else:
                if 'planet' in m:
                    p=m['planet']; pv=pos_score(obs,p); s += (.8 if typ in ('influence','influence_other','split_influence') else .2)*pv
                    amt=float(task.get('amount',1) or 1)
                    if typ in ('influence','influence_other','split_influence') and pv+amt>=4: s += 2.4
                    if typ in ('transfer','exile','exile_for_matching'): s += .35*len(them['columns'][PLANETS.index(p)]) - .15*pv
                if 'planets' in m: s += sum(.65*pos_score(obs,p) for p in m['planets'])
                if m.get('accept') is True: s += .36
                if m.get('accept') is False: s -= .02
                if 'tier' in m: s += .18*int(m['tier'])
                if 'faction' in m:
                    f=m['faction']; lv=me['technology'][FACTIONS.index(f)]; s += .2*(5-lv)
                if 'branch' in m:
                    labels=((obs.get('pending') or {}).get('task') or {}).get('branch_labels',[]); lab=(labels[m['branch']] if m['branch']<len(labels) else '').lower()
                    s += .45 if 'influence' in lab or 'transfer' in lab else .30 if 'zenithium' in lab or 'leader' in lab else .12
                if 'bonus_area' in m:
                    vals=obs['planet_bonus'] if m['bonus_area']=='planet' else obs['technology_bonus']; idx=(PLANETS if m['bonus_area']=='planet' else FACTIONS).index(m['slot']); tok=vals[idx]
                    s += {1:.15,2:.18,3:.6,4:.28,5:.24,6:.3,7:.28,8:.3}.get(tok or 0,.1)
                if 'card_id' in m: s -= .035*CARDS[int(m['card_id'])]['cost']
            out.append((s,action_key(m),m))
        return max(out,key=lambda x:(x[0],x[1]))[2]

def walktech(ts,obs,me,them):
    # same coarse values as card programs, sufficient to rank a tech advance
    total=0
    for t in ts or []:
        k=t.get('type'); a=t.get('amount',0)
        if k in ('influence','influence_other'): total += .5*float(a)
        elif k=='split_influence': total += .45*sum(t.get('amounts',[]))
        elif k=='mobilize': total += .12*float(t.get('count',0))
        elif k in ('two_adjacent','adjacent_three','all_planets'): total += .5*float(a or t.get('center',0)+2*t.get('neighbor',0) or 2)
        elif k in ('credits','zenithium'): total += .08*float(a)
        elif k in ('transfer','exile','steal'): total += .2*float(t.get('count',t.get('amount',1)))
        elif k=='draw_bonus': total += .16
    return total

def test(pairs=4, seed=41):
    for pol in [Aggressive('a'),Aggressive('keep'),Tactical('v1')]:
        t=time.time(); r=run_arena(pol,Legacy(),pairs=pairs,seed=seed,max_decisions=800,turn_budget=None)
        print(pol.name,r.as_dict(), 'elapsed',time.time()-t,flush=True)

if __name__=='__main__': test()
