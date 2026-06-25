//! Determinized PUCT (ISMCTS) — port of `mcts.py`, deployed serving config (add_noise=false,
//! backup_lambda=0). Arena-based tree (Vec<Node> + index children) to avoid parent-pointer borrows.
//!
//! Value convention: leaf value in [-1, 1] from the perspective of the player to move at the leaf;
//! backups credit each edge by the acting player's identity (turns don't strictly alternate).

use crate::cards::LEVEL_OF;
use crate::engine::{self, State, N_ACTIONS, WIN_DRAW};
use crate::rng::Rng;
use std::collections::HashMap;

const EPS_PRIOR: f64 = 1e-3; // actions legal in a determinization but unseen at expansion

struct Node {
    to_play: usize,
    expanded: bool,
    p: Vec<f64>,
    n: Vec<i32>,
    w: Vec<f64>,
    children: HashMap<usize, usize>,
}

impl Node {
    fn new(to_play: usize) -> Self {
        Node {
            to_play,
            expanded: false,
            p: vec![0.0; N_ACTIONS],
            n: vec![0; N_ACTIONS],
            w: vec![0.0; N_ACTIONS],
            children: HashMap::new(),
        }
    }
}

/// Clone `s` and reshuffle the unseen pool (undealt deck + opponent blind reserves) per level.
pub fn determinize(s: &State, perspective: usize, rng: &mut Rng) -> State {
    let mut d = s.clone();
    let opp = 1 - perspective;
    for lvl in 0..3 {
        let mut pool: Vec<i32> = d.decks[lvl].clone();
        let blind_idx: Vec<usize> = (0..d.reserved[opp].len())
            .filter(|&i| d.reserved_blind[opp][i] && (LEVEL_OF[d.reserved[opp][i] as usize] - 1) as usize == lvl)
            .collect();
        for &i in &blind_idx {
            pool.push(d.reserved[opp][i]);
        }
        rng.shuffle(&mut pool);
        for &i in &blind_idx {
            d.reserved[opp][i] = pool.pop().unwrap();
        }
        d.decks[lvl] = pool;
    }
    d
}

pub struct Search {
    root_state: State,
    c_puct: f64,
    nodes: Vec<Node>,
}

impl Search {
    pub fn new(root: State, c_puct: f64) -> Self {
        let root_turn = root.turn;
        Search {
            root_state: root,
            c_puct,
            nodes: vec![Node::new(root_turn)],
        }
    }

    fn select(&self, idx: usize, acts: &[usize]) -> usize {
        let node = &self.nodes[idx];
        let mut total = 0i32;
        for &a in acts {
            total += node.n[a];
        }
        let sqrt_total = ((total + 1) as f64).sqrt();
        let mut best_a = acts[0];
        let mut best_u = f64::NEG_INFINITY;
        for &a in acts {
            let n = node.n[a];
            let q = if n > 0 { node.w[a] / (n as f64) } else { 0.0 };
            let p = if node.p[a] > 0.0 { node.p[a] } else { EPS_PRIOR };
            let u = q + self.c_puct * p * sqrt_total / (1.0 + n as f64);
            if u > best_u {
                best_u = u;
                best_a = a;
            }
        }
        best_a
    }

    fn backup(&mut self, path: &[(usize, usize)], value: f64, ref_player: usize) {
        for &(ni, a) in path {
            let v = if self.nodes[ni].to_play == ref_player { value } else { -value };
            self.nodes[ni].n[a] += 1;
            self.nodes[ni].w[a] += v;
        }
    }

    /// One simulation. `eval(leaf_state, seat, legal) -> (priors[N_ACTIONS], value)` evaluates a leaf
    /// (value from `seat`'s perspective). Terminals are backed up internally (eval not called).
    pub fn sim<F>(&mut self, rng: &mut Rng, eval: &F)
    where
        F: Fn(&State, usize, &[usize]) -> (Vec<f64>, f64),
    {
        let mut s = determinize(&self.root_state, self.root_state.turn, rng);
        let mut idx = 0usize;
        let mut path: Vec<(usize, usize)> = Vec::new();
        loop {
            if !self.nodes[idx].expanded {
                break;
            }
            let acts = engine::legal_actions(&s);
            let a = self.select(idx, &acts);
            path.push((idx, a));
            engine::apply(&mut s, a);
            if s.phase == engine::OVER {
                let v0 = if s.winner == WIN_DRAW {
                    0.0
                } else if s.winner == 0 {
                    1.0
                } else {
                    -1.0
                };
                self.backup(&path, v0, 0);
                return;
            }
            idx = match self.nodes[idx].children.get(&a) {
                Some(&c) => c,
                None => {
                    let c = self.nodes.len();
                    self.nodes.push(Node::new(s.turn));
                    self.nodes[idx].children.insert(a, c);
                    c
                }
            };
        }
        // leaf at idx (unexpanded)
        let legal = engine::legal_actions(&s);
        let (probs, value) = eval(&s, s.turn, &legal);
        self.nodes[idx].expanded = true;
        self.nodes[idx].p = probs;
        self.backup(&path, value, s.turn);
    }

    pub fn root_visits(&self) -> &[i32] {
        &self.nodes[0].n
    }
}
