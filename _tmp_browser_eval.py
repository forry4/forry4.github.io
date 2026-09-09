import time
from games.orbit import engine
from games.orbit.ai import serving
from games.orbit.ai.selfplay import run_arena
from games.orbit.ai.state import action_key, observation
from _tmp_prod_eval import old_score, ProdDet

class BrowserOld:
    name = 'browser-v1'
    def __init__(self): self._counts = {}
    def choose(self, game, pid, rng, **kw):
        obs = observation(game, pid)
        moves = sorted(engine.legal_moves(game, pid), key=action_key)
        if not moves: return None
        decision = self._counts.get(id(game), 0) + 1
        self._counts[id(game)] = decision
        votes = {}
        for index in range(4):
            seed = ((decision * 2654435761) ^ (index * 40503 + 1)) & 0xffffffff
            vals = [(old_score(obs, m), action_key(m), m) for m in moves]
            best = max(v[0] for v in vals)
            ties = sorted((v for v in vals if abs(v[0] - best) < 1e-12), key=lambda v: v[1])
            move = ties[serving._seeded_tie_index(seed, len(ties))][2]
            key = action_key(move)
            votes.setdefault(key, [0, move])[0] += 1
        ranked = sorted(votes.values(), key=lambda x: (-x[0], action_key(x[1])))
        return ranked[0][1]

if __name__ == '__main__':
    old = BrowserOld()
    total_w = total_l = 0
    for seed in [41,177,999,20260908]:
        t=time.time(); r=run_arena(ProdDet(), old, pairs=16, seed=seed, max_decisions=800, turn_budget=None)
        total_w += r.wins; total_l += r.losses
        print(seed, r.wins, r.losses, r.score, r.by_board, round(time.time()-t,1), flush=True)
    print('TOTAL',total_w,total_l,total_w/(total_w+total_l),flush=True)
