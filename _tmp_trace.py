import copy
from games.orbit import engine
from games.orbit.ai import serving
from games.orbit.ai.state import action_key, observation
from games.orbit.ai.search import state_value

class CurrentStrong:
    name = 'current-strong'
    def choose(self, game, pid, rng, **kwargs):
        moves = sorted(engine.legal_moves(game, pid), key=action_key)
        return serving.choose_move(observation(game, pid), moves, None, 5000, 0).move if moves else None

class OnePly:
    def choose(self, game, pid, rng, **kwargs):
        moves = sorted(engine.legal_moves(game, pid), key=action_key)
        before = state_value(game, pid)
        vals = []
        for move in moves:
            after = copy.deepcopy(game)
            ok, err = engine.apply_move(after, pid, move)
            v = -99 if not ok else state_value(after, pid)-before
            if ok and engine.is_over(after): v += 10 if engine.winner(after)==pid else -10
            vals.append((v, move))
        return max(vals, key=lambda x:(x[0], action_key(x[1]))) if vals else None

g = engine.new_game(['a','b'], seed=59, configuration={'robot':2,'human':2,'animod':2})
for pid in list(g['order']):
    engine.apply_move(g,pid,{'action':'mulligan','card_ids':[]})
policies = {'a': OnePly(), 'b': CurrentStrong()}
for n in range(100):
    if engine.is_over(g): break
    pid = g['pending_pid'] if g.get('pending') else g['turn_pid']
    if pid is None: break
    result = policies[pid].choose(g,pid,None)
    move = result[1] if isinstance(result,tuple) else result
    print(n, pid, move, 'infl', g['influence'], 'res', [(p,g['players'][p]['credits'],g['players'][p]['zenithium'],len(g['players'][p]['captured'])) for p in g['order']], flush=True)
    ok, err = engine.apply_move(g,pid,move)
    if not ok: print('ILLEGAL',err); break
print('outcome',g['phase'],g.get('winner'), 'turns',g['turn_number'])
