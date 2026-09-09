exec(open('_tmp_search2.py').read().split("oldv,oldp=")[0])
class Full:
 name='full'
 def choose(self,g,p,rng,**kw):
  ms=sorted(engine.legal_moves(g,p),key=action_key);b=value(g,p);arr=[]
  for m in ms:
   a=copy.deepcopy(g);ok,_=engine.apply_move(a,p,m);v=-99 if not ok else value(a,p)
   arr.append((v,action_key(m),m))
  return max(arr,key=lambda x:(x[0],x[1]))[2]
for seed in [41,177,999,20260908]:
 t=time.time();r=run_arena(Full(),Old(),pairs=4,seed=seed,max_decisions=800,turn_budget=None);print(seed,r.wins,r.losses,r.score,round(time.time()-t,1),flush=True)
