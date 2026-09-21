//! Orbit simulation core. Python owns live rules; differential replay gates this port.
//! State is privileged. Policies must use the separate observation contract.
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::{BTreeMap, BTreeSet, VecDeque};
use std::sync::OnceLock;

pub mod serving;
pub mod tensors;
pub mod attention;
pub mod features;
pub mod search;
pub mod alphabeta;
pub(crate) mod clock;

#[cfg(target_arch = "wasm32")]
mod wasm;

pub const PLANETS: [&str; 5] = ["mercury", "venus", "terra", "mars", "jupiter"];
const CONTROL_POSITION: i32 = 4;

/// Influence discs PER PLANET. The box holds 20, four in each planet's colour, so a
/// planet can be captured at most four times and the fifth has nothing to take. Mirrors
/// `engine.DISCS_PER_PLANET`; across 189 archived BGA games the most any planet ever
/// yielded is exactly four.
const DISCS_PER_PLANET: u8 = 4;
pub const FACTIONS: [&str; 3] = ["robot", "human", "animod"];
fn s<'a>(v: &'a Value, k: &str) -> &'a str {
    v[k].as_str().unwrap_or("")
}
fn n(v: &Value, k: &str) -> i32 {
    v[k].as_i64().unwrap_or(0) as i32
}
fn nd(v: &Value, k: &str, default: i32) -> i32 {
    v[k].as_i64().map(|x| x as i32).unwrap_or(default)
}
fn b(v: &Value, k: &str) -> bool {
    v[k].as_bool().unwrap_or(false)
}
fn arr(v: &Value, k: &str) -> Vec<Value> {
    v[k].as_array().cloned().unwrap_or_default()
}
fn contains(v: &Value, k: &str, x: &str) -> bool {
    v[k].as_array().is_some_and(|a| a.contains(&json!(x)))
}
fn planet(x: &str) -> usize {
    PLANETS.iter().position(|p| *p == x).expect("planet")
}
fn faction(x: &str) -> usize {
    FACTIONS.iter().position(|p| *p == x).expect("faction")
}
fn influence(p: &str, amount: i32) -> Value {
    json!({"type":"influence","planet":p,"amount":amount,"target":"self"})
}

#[derive(Clone, Debug, Deserialize)]
pub struct Card {
    pub id: u16,
    pub name: String,
    pub planet: String,
    pub faction: String,
    pub cost: i32,
}
#[derive(Deserialize)]
pub struct Rules {
    pub rules: String,
    pub cards: BTreeMap<u16, Card>,
    pub bonus_pool: Vec<u16>,
    card_effects: BTreeMap<u16, Vec<Value>>,
    bonus_effects: BTreeMap<u16, Vec<Value>>,
    tech_effects: BTreeMap<String, Vec<Value>>,
}
pub fn rules() -> &'static Rules {
    static RULES: OnceLock<Rules> = OnceLock::new();
    RULES.get_or_init(|| {
        serde_json::from_str(include_str!("../data/rules.json")).expect("generated rules")
    })
}

#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Player {
    pub credits: i32,
    pub zenithium: i32,
    pub hand: Vec<u16>,
    pub columns: [Vec<u16>; 5],
    pub technology: [i32; 3],
    pub row_bonuses: Vec<i32>,
    pub captured: Vec<usize>,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Leader {
    pub owner: Option<usize>,
    pub level: i32,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
pub struct Pending {
    pub source: String,
    pub queue: Vec<Value>,
    pub context: Value,
}
#[derive(Clone, Debug, Serialize, Deserialize, PartialEq)]
#[serde(deny_unknown_fields)]
pub struct State {
    pub schema: u32,
    pub phase: String,
    pub players: [Player; 2],
    pub turn_pid: Option<usize>,
    pub turn_number: u32,
    pub influence: [Option<i32>; 5],
    pub captured_this_turn: Vec<usize>,
    pub leader: Leader,
    pub board_sides: [i32; 3],
    pub planet_bonus: [Option<u16>; 5],
    pub technology_bonus: [Option<u16>; 3],
    pub agent_deck: Vec<u16>,
    pub agent_discard: Vec<u16>,
    pub bonus_deck: Vec<u16>,
    pub bonus_discard: Vec<u16>,
    pub mulligan_done: Vec<usize>,
    pub pending: Option<Pending>,
    pub pending_pid: Option<usize>,
    pub winner: Option<usize>,
}

/// RNG belongs to the simulation, never the observation. Scripted shuffles are
/// complete post-shuffle piles (top at the end), checked against the input multiset.
#[derive(Clone)]
pub struct Chance {
    rng: u64,
    tape: VecDeque<Vec<u16>>,
    strict: bool,
    pub consumed: usize,
}
impl Chance {
    pub fn seeded(seed: u64) -> Self {
        Self {
            rng: seed,
            tape: VecDeque::new(),
            strict: false,
            consumed: 0,
        }
    }
    pub fn scripted(tape: Vec<Vec<u16>>) -> Self {
        Self {
            rng: 0,
            tape: tape.into(),
            strict: true,
            consumed: 0,
        }
    }
    pub fn remaining(&self) -> usize {
        self.tape.len()
    }
    fn next(&mut self) -> u64 {
        self.rng = self.rng.wrapping_add(0x9e3779b97f4a7c15);
        let mut z = self.rng;
        z = (z ^ (z >> 30)).wrapping_mul(0xbf58476d1ce4e5b9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94d049bb133111eb);
        z ^ (z >> 31)
    }
    pub fn index(&mut self, upper: usize) -> usize {
        assert!(upper > 0);
        let u = upper as u64;
        let threshold = u.wrapping_neg() % u;
        loop {
            let x = self.next();
            if x >= threshold {
                return (x % u) as usize;
            }
        }
    }
    fn shuffle(&mut self, pile: &mut Vec<u16>) {
        if self.strict {
            let replacement = self.tape.pop_front().expect("missing scripted shuffle");
            let mut a = pile.clone();
            let mut z = replacement.clone();
            a.sort();
            z.sort();
            assert_eq!(a, z, "scripted shuffle changed the inventory");
            *pile = replacement;
        } else {
            for i in (1..pile.len()).rev() {
                let j = self.index(i + 1);
                pile.swap(i, j);
            }
        }
        self.consumed += 1;
    }
}

impl State {
    /// Allowlisted policy input, matching Python ai.state.observation. Never
    /// expose a serialized State to a policy, including after game over.
    #[cfg(test)]
    fn observation_serde(&self, seat: usize) -> Value {
        assert!(seat < 2);
        let state = serde_json::to_value(self).unwrap();
        let mut result = json!({});
        for key in [
            "schema",
            "phase",
            "turn_pid",
            "turn_number",
            "influence",
            "captured_this_turn",
            "leader",
            "board_sides",
            "planet_bonus",
            "technology_bonus",
            "agent_discard",
            "bonus_discard",
            "mulligan_done",
            "pending_pid",
            "winner",
        ] {
            result[key] = state[key].clone();
        }
        result["seat"] = json!(seat);
        let mut players = vec![];
        for index in 0..2 {
            let mut player = json!({});
            for key in [
                "credits",
                "zenithium",
                "columns",
                "technology",
                "row_bonuses",
                "captured",
            ] {
                player[key] = state["players"][index][key].clone();
            }
            player["hand_count"] = json!(self.players[index].hand.len());
            if index == seat {
                let mut hand = self.players[index].hand.clone();
                hand.sort();
                player["hand"] = json!(hand);
            }
            players.push(player);
        }
        result["players"] = json!(players);
        result["agent_deck_count"] = json!(self.agent_deck.len());
        result["bonus_deck_count"] = json!(self.bonus_deck.len());
        result["pending"] = Value::Null;
        if let Some(pending) = &self.pending {
            if self.pending_pid == Some(seat) {
                let current = &pending.queue[0];
                let mut task = json!({});
                for key in [
                    "type",
                    "amount",
                    "target",
                    "planet",
                    "exclude",
                    "restriction",
                    "distinct_from",
                    "selected",
                    "amounts",
                    "label",
                    "cost",
                    "count",
                    "done",
                    "used",
                    "owner",
                    "distinct",
                    "reward",
                    "faction",
                    "discount",
                    "lowest",
                    "tiers",
                    "planets",
                    "index",
                    "center",
                    "neighbor",
                    "influence_each",
                    "require_full",
                    "one_at_a_time",
                    "options",
                    "branch_labels",
                ] {
                    if let Some(v) = current.get(key) {
                        task[key] = v.clone();
                    }
                }
                if let Some(branches) = current["branches"].as_array() {
                    if !branches.is_empty() {
                        task["branch_labels"] = json!(branches
                            .iter()
                            .map(|v| v["label"].clone())
                            .collect::<Vec<_>>());
                    }
                }
                result["pending"] = json!({"source":pending.source,"task":task,"last_planet":pending.context["last_planet"]});
            } else {
                result["pending"] = json!({"source":pending.source,"waiting":true});
            }
        }
        let mut moves = self.legal_moves(seat);
        moves.sort_by_key(|v| serde_json::to_string(v).unwrap());
        result["legal_moves"] = json!(moves);
        result
    }

    /// Build the allowlisted observation directly from the privileged state.
    /// This deliberately mirrors `observation_serde` field-for-field, but
    /// avoids serializing the hidden deck, hands and pending queues before
    /// copying the public projection back out.  Keep the two implementations
    /// The whole pending chain, as data a search can rebuild a position from.
    ///
    /// WHY THIS IS NOT A LEAK, which is the only question that matters about a
    /// function handing private-looking state to a client. Every task in the
    /// queue is generated from the played card's STATIC effect program, which is
    /// public card text in structured form and already ships to the browser in
    /// `orbit-model.json`. The only fields tasks accumulate during resolution
    /// are planets (`selected`, `used`), counters (`done`, `index`, `count`) and
    /// `options`, which is the legal-move list the client is handed anyway. The
    /// context holds exactly one key, `last_planet`, which the redacted
    /// observation already exposes. `the_pending_chain_carries_no_hidden_cards`
    /// holds that to real positions rather than to this paragraph.
    ///
    /// WHY IT IS SEPARATE FROM `observation`. The observation is the frozen
    /// policy input: its key set is asserted in three places, it is stored in
    /// game history and compared for equality, and it feeds the encoder. Adding
    /// a key there is a schema change with a migration. This is handed to the
    /// search ALONGSIDE the observation instead, so the reconstructing caller
    /// merges the two and nothing else moves.
    pub fn pending_chain(&self) -> Value {
        match &self.pending {
            None => Value::Null,
            Some(pending) => json!({
                "source": pending.source,
                "queue": pending.queue,
                "context": pending.context,
            }),
        }
    }

    /// in parity tests below whenever this contract changes.
    /// Discs still available for `p`, DERIVED from what both seats have taken rather
    /// than stored. Keeping it out of the struct keeps the observation contract, the
    /// encoder and the trained model untouched -- and a derived count cannot drift out
    /// of step with the captures it is computed from.
    fn discs_left(&self, p: usize) -> u8 {
        let taken: usize = self
            .players
            .iter()
            .map(|player| player.captured.iter().filter(|c| **c == p).count())
            .sum();
        DISCS_PER_PLANET.saturating_sub(taken.min(255) as u8)
    }

    pub fn observation(&self, seat: usize) -> Value {
        assert!(seat < 2);
        let mut result = json!({
            "schema": self.schema,
            "phase": self.phase,
            "turn_pid": self.turn_pid,
            "turn_number": self.turn_number,
            "influence": self.influence,
            "captured_this_turn": self.captured_this_turn,
            "leader": {"owner": self.leader.owner, "level": self.leader.level},
            "board_sides": self.board_sides,
            "planet_bonus": self.planet_bonus,
            "technology_bonus": self.technology_bonus,
            "agent_discard": self.agent_discard,
            "bonus_discard": self.bonus_discard,
            "mulligan_done": self.mulligan_done,
            "pending_pid": self.pending_pid,
            "winner": self.winner,
            "seat": seat,
        });
        let mut players = Vec::with_capacity(2);
        for index in 0..2 {
            let source = &self.players[index];
            let mut player = json!({
                "credits": source.credits,
                "zenithium": source.zenithium,
                "columns": source.columns,
                "technology": source.technology,
                "row_bonuses": source.row_bonuses,
                "captured": source.captured,
                "hand_count": source.hand.len(),
            });
            if index == seat {
                let mut hand = source.hand.clone();
                hand.sort();
                player["hand"] = json!(hand);
            }
            players.push(player);
        }
        result["players"] = json!(players);
        result["agent_deck_count"] = json!(self.agent_deck.len());
        result["bonus_deck_count"] = json!(self.bonus_deck.len());
        result["pending"] = Value::Null;
        if let Some(pending) = &self.pending {
            if self.pending_pid == Some(seat) {
                let current = &pending.queue[0];
                let mut task = json!({});
                for key in [
                    "type",
                    "amount",
                    "target",
                    "planet",
                    "exclude",
                    "restriction",
                    "distinct_from",
                    "selected",
                    "amounts",
                    "label",
                    "cost",
                    "count",
                    "done",
                    "used",
                    "owner",
                    "distinct",
                    "reward",
                    "faction",
                    "discount",
                    "lowest",
                    "tiers",
                    "planets",
                    "index",
                    "center",
                    "neighbor",
                    "influence_each",
                    "require_full",
                    "one_at_a_time",
                    "options",
                    "branch_labels",
                ] {
                    if let Some(v) = current.get(key) {
                        task[key] = v.clone();
                    }
                }
                if let Some(branches) = current["branches"].as_array() {
                    if !branches.is_empty() {
                        task["branch_labels"] = json!(branches
                            .iter()
                            .map(|v| v["label"].clone())
                            .collect::<Vec<_>>());
                    }
                }
                result["pending"] = json!({
                    "source": pending.source,
                    "task": task,
                    "last_planet": pending.context["last_planet"]
                });
            } else {
                result["pending"] = json!({"source": pending.source, "waiting": true});
            }
        }
        let mut moves = self.legal_moves(seat);
        moves.sort_by_key(|v| serde_json::to_string(v).unwrap());
        result["legal_moves"] = json!(moves);
        result
    }

    pub fn new(seed: u64, board_sides: [i32; 3]) -> (Self, Chance) {
        assert!(board_sides.iter().all(|s| (1..=2).contains(s)));
        let p = Player {
            credits: 12,
            zenithium: 1,
            hand: vec![],
            columns: Default::default(),
            technology: [0; 3],
            row_bonuses: vec![],
            captured: vec![],
        };
        let mut c = Chance::seeded(seed);
        let mut g = Self {
            schema: 1,
            phase: "mulligan".into(),
            players: [p.clone(), p],
            turn_pid: None,
            turn_number: 0,
            influence: [Some(0), Some(0), Some(-1), Some(0), Some(0)],
            captured_this_turn: vec![],
            leader: Leader {
                owner: None,
                level: 0,
            },
            board_sides,
            planet_bonus: [None; 5],
            technology_bonus: [None; 3],
            agent_deck: rules().cards.keys().copied().collect(),
            agent_discard: vec![],
            bonus_deck: rules().bonus_pool.clone(),
            bonus_discard: vec![],
            mulligan_done: vec![],
            pending: None,
            pending_pid: None,
            winner: None,
        };
        c.shuffle(&mut g.agent_deck);
        c.shuffle(&mut g.bonus_deck);
        g.draw_to(0, 4, &mut c);
        g.draw_to(1, 4, &mut c);
        for v in &mut g.planet_bonus {
            *v = g.bonus_deck.pop();
        }
        for v in &mut g.technology_bonus {
            *v = g.bonus_deck.pop();
        }
        (g, c)
    }
    pub fn actor(&self) -> Option<usize> {
        if self.phase == "over" {
            None
        } else if self.phase == "mulligan" {
            (0..2).find(|p| !self.mulligan_done.contains(p))
        } else if self.pending.is_some() {
            self.pending_pid
        } else {
            self.turn_pid
        }
    }
    fn resource(&self, pid: usize, key: &str) -> i32 {
        match key {
            "credits" => self.players[pid].credits,
            "zenithium" => self.players[pid].zenithium,
            _ => panic!("unknown resource {key}"),
        }
    }
    fn add_resource(&mut self, pid: usize, key: &str, amount: i32) {
        match key {
            "credits" => self.players[pid].credits += amount,
            "zenithium" => self.players[pid].zenithium += amount,
            _ => panic!("unknown resource {key}"),
        }
    }
    fn queue(&mut self, tasks: Vec<Value>, actor: usize) {
        if tasks.is_empty() || self.phase == "over" {
            return;
        }
        let pending = self.pending.as_mut().expect("pending queue");
        let prepared = tasks.into_iter().map(|mut t| {
            if t.get("actor").is_none() {
                t["actor"] = json!(actor);
            }
            t
        });
        pending.queue.splice(0..0, prepared);
    }

    /// Bonus effects are internal tasks.  The Python authority keeps that
    /// marker so a later ``different_from_previous`` choice can distinguish a
    /// bonus movement from the card/technology movement that caused it.
    fn mark_bonus(tasks: Vec<Value>) -> Vec<Value> {
        tasks
            .into_iter()
            .map(|mut task| {
                task["_bonus"] = json!(true);
                task
            })
            .collect()
    }

    /// Match the two queue-shape corrections observed in the BGA co-walk.
    /// They are deliberately narrow: ordinary bonus insertion remains the
    /// normal front-of-queue operation.
    fn adjust_influence_queue(&mut self, task: &Value, planet_name: &str, amount: i32, bonus_len: usize) {
        let nonbonus = !b(task, "_bonus");
        if nonbonus
            && amount == 1
            && bonus_len > 0
            && self
                .pending
                .as_ref()
                .is_some_and(|p| p.queue.first().is_some_and(|t| b(t, "_bonus")))
            && self.pending.as_ref().is_some_and(|p| {
                p.queue[1..].iter().any(|t| s(t, "type") == "adjacent_three")
            })
        {
            let pending = self.pending.as_mut().expect("pending queue");
            let moved: Vec<_> = pending.queue.drain(..bonus_len).collect();
            pending.queue.extend(moved);
        }
        if nonbonus
            && amount == 2
            && self.pending.as_ref().is_some_and(|p| {
                p.queue.first().is_some_and(|t| s(t, "type") == "adjacent_three")
                    && self.influence[planet(planet_name)].is_some_and(|v| v.abs() == CONTROL_POSITION - 1)
            })
        {
            let pending = self.pending.as_mut().expect("pending queue");
            for index in 1..pending.queue.len() {
                let candidate = &pending.queue[index];
                if s(candidate, "type") == "influence"
                    && n(candidate, "amount") == 1
                    && !b(candidate, "_bonus")
                    && s(candidate, "planet").is_empty()
                {
                    let candidate = pending.queue.remove(index);
                    pending.queue.insert(0, candidate);
                    break;
                }
            }
        }
    }
    fn draw_agent(&mut self, chance: &mut Chance) -> Option<u16> {
        if self.agent_deck.is_empty() {
            if self.agent_discard.is_empty() {
                return None;
            }
            chance.shuffle(&mut self.agent_discard);
            self.agent_deck = std::mem::take(&mut self.agent_discard);
        }
        self.agent_deck.pop()
    }
    fn draw_to(&mut self, pid: usize, limit: usize, c: &mut Chance) {
        while self.players[pid].hand.len() < limit {
            if let Some(card) = self.draw_agent(c) {
                self.players[pid].hand.push(card);
            } else {
                break;
            }
        }
    }
    fn draw_bonus(&mut self, c: &mut Chance) -> Option<u16> {
        if self.bonus_deck.is_empty() {
            if self.bonus_discard.is_empty() {
                return None;
            }
            c.shuffle(&mut self.bonus_discard);
            self.bonus_deck = std::mem::take(&mut self.bonus_discard);
        }
        self.bonus_deck.pop()
    }
    fn award_bonus(&mut self, pid: usize, token: u16) {
        self.bonus_discard.push(token);
        self.queue(Self::mark_bonus(rules().bonus_effects[&token].clone()), pid);
    }
    fn gain_leader(&mut self, pid: usize, level: i32) {
        self.leader.level = if level >= 2 {
            2
        } else if self.leader.owner == Some(pid) {
            (self.leader.level + 1).min(2)
        } else {
            1
        };
        self.leader.owner = Some(pid);
    }
    fn check_victory(&mut self) -> bool {
        for pid in 0..2 {
            let caps = &self.players[pid].captured;
            let mut counts = [0; 5];
            for p in caps {
                counts[*p] += 1;
            }
            if caps.len() >= 5
                || counts.iter().any(|c| *c >= 3)
                || counts.iter().filter(|c| **c > 0).count() >= 4
            {
                self.phase = "over".into();
                self.winner = Some(pid);
                self.pending = None;
                self.pending_pid = None;
                return true;
            }
        }
        false
    }
    fn gain_influence(&mut self, pid: usize, p: usize, amount: i32) -> Vec<Value> {
        let dir = if pid == 0 { 1 } else { -1 };
        for _ in 0..amount.max(0) {
            let Some(pos) = self.influence[p] else {
                break;
            };
            let pos = pos + dir;
            self.influence[p] = Some(pos);
            if pos.abs() >= 4 {
                self.players[pid].captured.push(p);
                self.captured_this_turn.push(p);
                self.influence[p] = None;
                if self.pending.is_none() && self.check_victory() {
                    return vec![];
                }
                if let Some(token) = self.planet_bonus[p].take() {
                    self.bonus_discard.push(token);
                    return Self::mark_bonus(rules().bonus_effects[&token].clone());
                }
                break;
            }
        }
        vec![]
    }
    fn top_candidates(&self, pid: usize, owner: &str, task: &Value) -> Vec<usize> {
        let who = if owner == "self" { pid } else { 1 - pid };
        (0..5)
            .filter(|p| {
                !self.players[who].columns[*p].is_empty()
                    && PLANETS[*p] != s(task, "exclude")
                    && !(b(task, "distinct") && contains(task, "used", PLANETS[*p]))
            })
            .collect()
    }
    fn eligible(&self, pid: usize, task: &Value) -> Vec<usize> {
        let dir = if pid == 0 { 1 } else { -1 };
        let last = self
            .pending
            .as_ref()
            .map(|v| {
                if b(task, "different_from_previous") {
                    s(&v.context, "last_nonbonus_planet")
                } else {
                    s(&v.context, "last_planet")
                }
            })
            .unwrap_or("");
        (0..5)
            .filter(|p| {
                let name = PLANETS[*p];
                let Some(pos) = self.influence[*p] else {
                    return false;
                };
                name != s(task, "exclude")
                    && !contains(task, "distinct_from", name)
                    && !(s(task, "type") == "influence_other" && name == last)
                    && match s(task, "restriction") {
                        "middle" => pos == 0,
                        "opponent_side" | "dominated" => pos * dir < 0,
                        _ => true,
                    }
            })
            .collect()
    }
    fn can_pay(&self, pid: usize, cost: &Value) -> bool {
        let r = s(cost, "resource");
        if r == "leader" {
            return self.leader.owner == Some(pid);
        }
        let r = r.strip_suffix("_to_opponent").unwrap_or(r);
        self.resource(pid, r) >= nd(cost, "amount", 1)
    }
    fn pay(&mut self, pid: usize, cost: &Value) -> bool {
        if !self.can_pay(pid, cost) {
            return false;
        }
        let r = s(cost, "resource");
        if r == "leader" {
            self.leader = Leader { owner: Some(1 - pid), level: 1 };
            return true;
        }
        let base = r.strip_suffix("_to_opponent").unwrap_or(r);
        let amount = nd(cost, "amount", 1);
        self.add_resource(pid, base, -amount);
        if base != r {
            self.add_resource(1 - pid, base, amount);
        }
        true
    }
    fn develop(&mut self, pid: usize, f: usize, discount: i32) -> bool {
        let level = self.players[pid].technology[f];
        let cost = (level + 1 - discount).max(0);
        if level >= 5 || self.players[pid].zenithium < cost {
            return false;
        }
        self.players[pid].zenithium -= cost;
        self.players[pid].technology[f] += 1;
        let mut tasks = vec![];
        for l in (1..=level + 1).rev() {
            tasks.extend(
                rules().tech_effects[&format!("{}/{}/{}", FACTIONS[f], self.board_sides[f], l)]
                    .clone(),
            );
            if l == 2 && self.technology_bonus[f].is_some() {
                tasks.push(json!({"type":"fixed_bonus","faction":FACTIONS[f]}));
            }
        }
        tasks.push(json!({"type":"row_bonus_check"}));
        self.queue(tasks, pid);
        true
    }
    fn discard_top(&mut self, pid: usize, p: usize) -> u16 {
        let id = self.players[pid].columns[p].pop().expect("top card");
        self.agent_discard.push(id);
        id
    }
    fn transfer(&mut self, pid: usize, p: usize) -> u16 {
        let id = self.players[1 - pid].columns[p].pop().expect("top card");
        self.players[pid].columns[p].push(id);
        id
    }
    fn possible(&self, pid: usize, task: &Value) -> bool {
        match s(task, "type") {
            "transfer" => !self.top_candidates(pid, "opponent", &json!({})).is_empty(),
            "influence" | "influence_other" => {
                if !s(task, "planet").is_empty() {
                    self.influence[planet(s(task, "planet"))].is_some()
                } else {
                    !self.eligible(pid, task).is_empty()
                }
            }
            _ => true,
        }
    }
    fn choices(&self, task: &Value) -> Vec<Value> {
        let pid = n(task, "actor") as usize;
        let kind = s(task, "type");
        let planets = |ps: Vec<usize>| {
            ps.into_iter()
                .map(|p| json!({"action":"choose","planet":PLANETS[p]}))
                .collect()
        };
        match kind {
            "influence" | "influence_other" => planets(self.eligible(pid, task)),
            "split_influence" => planets(
                (0..5)
                    .filter(|p| !contains(task, "selected", PLANETS[*p]))
                    .collect(),
            ),
            "optional" => {
                let mut result = vec![json!({"action":"choose","accept":false})];
                if arr(task, "then")
                    .first()
                    .is_none_or(|t| self.possible(pid, t))
                {
                    result.push(json!({"action":"choose","accept":true}));
                }
                result
            }
            "choose_branch" => {
                let branches = arr(task, "branches");
                let mut opts: Vec<_> = branches
                    .iter()
                    .enumerate()
                    .filter(|(_, v)| {
                        arr(v, "tasks")
                            .first()
                            .is_none_or(|t| self.possible(pid, t))
                    })
                    .map(|(i, _)| i)
                    .collect();
                if opts.is_empty() {
                    opts = (0..branches.len()).collect();
                }
                opts.iter()
                    .map(|i| json!({"action":"choose","branch":i}))
                    .collect()
            }
            "exile" | "exile_for_matching" => {
                let owner = if s(task, "owner").is_empty() {
                    if kind == "exile_for_matching" {
                        "self"
                    } else {
                        "opponent"
                    }
                } else {
                    s(task, "owner")
                };
                planets(self.top_candidates(pid, owner, task))
            }
            "transfer" => planets(self.top_candidates(pid, "opponent", &json!({}))),
            "discard_hand" => self.players[pid]
                .hand
                .iter()
                .map(|id| json!({"action":"choose","card_id":id}))
                .collect(),
            "develop" => {
                let p = &self.players[pid];
                (0..3)
                    .filter(|f| {
                        (s(task, "faction").is_empty() || s(task, "faction") == FACTIONS[*f])
                            && (!b(task, "lowest")
                                || p.technology[*f] == *p.technology.iter().min().unwrap())
                            && p.technology[*f] < 5
                            && p.zenithium >= (p.technology[*f] + 1 - n(task, "discount")).max(0)
                    })
                    .map(|f| json!({"action":"choose","faction":FACTIONS[f]}))
                    .collect()
            }
            "exile_tier" => {
                let size = self.players[pid].columns[planet(s(task, "planet"))].len();
                let opts: Vec<_> = [2, 4, 7]
                    .into_iter()
                    .filter(|t| size >= *t)
                    .map(|t| json!({"action":"choose","tier":t}))
                    .collect();
                if opts.is_empty() {
                    vec![json!({"action":"choose","tier":0})]
                } else {
                    opts
                }
            }
            "spend_tier" => {
                let amount = self.resource(pid, s(task, "resource"));
                let mut opts: Vec<_> = arr(task, "tiers")
                    .iter()
                    .filter(|v| v[0].as_i64().unwrap() <= amount as i64)
                    .map(|v| json!({"action":"choose","cost":v[0],"amount":v[1]}))
                    .collect();
                opts.push(json!({"action":"choose","cost":0,"amount":0}));
                opts
            }
            "reset_planet" => planets(
                (0..5)
                    .filter(|p| self.influence[*p].is_some_and(|v| v != 0))
                    .collect(),
            ),
            "take_board_bonus" => {
                let mut opts: Vec<_> = (0..5)
                    .filter(|p| self.planet_bonus[*p].is_some())
                    .map(|p| json!({"action":"choose","bonus_area":"planet","slot":PLANETS[p]}))
                    .collect();
                opts.extend((0..3).filter(|f| self.technology_bonus[*f].is_some()).map(
                    |f| json!({"action":"choose","bonus_area":"technology","slot":FACTIONS[f]}),
                ));
                opts
            }
            "optional_exile_each" => {
                let p = planet(task["planets"][n(task, "index") as usize].as_str().unwrap());
                let mut opts = vec![json!({"action":"choose","accept":false})];
                if !self.players[pid].columns[p].is_empty() {
                    opts.push(json!({"action":"choose","accept":true}));
                }
                opts
            }
            "two_adjacent" => (0..4)
                .flat_map(|p| {
                    [
                        json!({"action":"choose","planets":[PLANETS[p],PLANETS[p+1]]}),
                        json!({"action":"choose","planets":[PLANETS[p+1],PLANETS[p]]}),
                    ]
                })
                .collect(),
            "adjacent_three" => planets((1..4).collect()),
            _ => panic!("unknown choice {kind}"),
        }
    }
    pub fn legal_moves(&self, pid: usize) -> Vec<Value> {
        if pid > 1 || self.phase == "over" {
            return vec![];
        }
        if self.phase == "mulligan" {
            if self.mulligan_done.contains(&pid) {
                return vec![];
            }
            let mut hand = self.players[pid].hand.clone();
            hand.sort();
            let mut subsets = vec![];
            for mask in 0..(1usize << hand.len()) {
                let selected: Vec<_> = hand
                    .iter()
                    .enumerate()
                    .filter(|(i, _)| mask & (1 << i) != 0)
                    .map(|(_, v)| *v)
                    .collect();
                subsets.push(selected);
            }
            subsets.sort_by(|a, b| a.len().cmp(&b.len()).then(a.cmp(b)));
            return subsets
                .into_iter()
                .map(|v| json!({"action":"mulligan","card_ids":v}))
                .collect();
        }
        if let Some(pending) = &self.pending {
            if self.pending_pid != Some(pid) {
                return vec![];
            }
            let task = &pending.queue[0];
            let stored = arr(task, "options");
            return if stored.is_empty() {
                self.choices(task)
            } else {
                stored
            };
        }
        if self.turn_pid != Some(pid) {
            return vec![];
        }
        let p = &self.players[pid];
        let mut moves = vec![];
        for id in &p.hand {
            let c = &rules().cards[id];
            if p.credits >= (c.cost - p.columns[planet(&c.planet)].len() as i32).max(0) {
                moves.push(json!({"action":"recruit","card_id":id}));
            }
            let level = p.technology[faction(&c.faction)] + 1;
            if level <= 5 && p.zenithium >= level {
                moves.push(json!({"action":"technology","card_id":id}));
            }
            moves.push(json!({"action":"leader","card_id":id}));
        }
        moves
    }
    fn finish_turn(&mut self, c: &mut Chance) {
        let pid = self.turn_pid.unwrap();
        // BGA drains the already-open effect chain and resets captured discs
        // before declaring a win.  Do not refill the hand or start the next
        // turn after that terminal boundary.
        let victory_pending = (0..2).any(|seat| {
            let captured = &self.players[seat].captured;
            let mut counts = [0; 5];
            for p in captured {
                counts[*p] += 1;
            }
            captured.len() >= 5
                || counts.iter().any(|count| *count >= 3)
                || counts.iter().filter(|count| **count > 0).count() >= 4
        });
        if victory_pending {
            let refilled: Vec<usize> = std::mem::take(&mut self.captured_this_turn);
            for p in refilled {
                if self.influence[p].is_none() && self.discs_left(p) > 0 {
                    self.influence[p] = Some(0);
                }
            }
            self.pending = None;
            self.pending_pid = None;
            self.check_victory();
            return;
        }
        let limit = if self.leader.owner == Some(pid) {
            if self.leader.level >= 2 {
                6
            } else {
                5
            }
        } else {
            4
        };
        self.draw_to(pid, limit, c);
        let refilled: Vec<usize> = std::mem::take(&mut self.captured_this_turn);
        for p in refilled {
            if self.influence[p].is_none() && self.discs_left(p) > 0 {
                self.influence[p] = Some(0);
            }
        }
        self.pending = None;
        self.pending_pid = None;
        self.turn_number += 1;
        self.turn_pid = Some(1 - pid);
        if self.players[1 - pid].hand.is_empty() {
            let limit = if self.leader.owner == Some(1 - pid) {
                if self.leader.level >= 2 {
                    6
                } else {
                    5
                }
            } else {
                4
            };
            self.draw_to(1 - pid, limit, c);
        }
        if self.players[1 - pid].hand.is_empty()
            && self.agent_deck.is_empty()
            && self.agent_discard.is_empty()
        {
            self.phase = "over".into();
            self.winner = None;
        }
    }
    fn begin(&mut self, pid: usize, source: &str) {
        self.pending = Some(Pending {
            source: source.into(),
            queue: vec![],
            context: json!({}),
        });
        self.pending_pid = Some(pid);
    }
    /// Invalid legal-move requests do not mutate either state or chance.
    /// Only trusted, validated states enter this simulator (not the live server).
    pub fn apply(&mut self, pid: usize, mv: &Value, chance: &mut Chance) -> Result<(), String> {
        self.apply_inner(pid, mv, chance, true)
    }

    /// Apply a move selected from this state's legal-move list. Search already
    /// owns that list, so repeating the full JSON legal-move construction here
    /// only burns CPU; the public `apply` path above remains validating.
    pub(crate) fn apply_search(
        &mut self,
        pid: usize,
        mv: &Value,
        chance: &mut Chance,
    ) -> Result<(), String> {
        self.apply_inner(pid, mv, chance, false)
    }

    fn apply_inner(
        &mut self,
        pid: usize,
        mv: &Value,
        chance: &mut Chance,
        validate: bool,
    ) -> Result<(), String> {
        if validate && !self.legal_moves(pid).contains(mv) {
            return Err("Illegal move".into());
        }
        if self.phase == "mulligan" {
            for id in arr(mv, "card_ids") {
                let id = id.as_u64().unwrap() as u16;
                let i = self.players[pid]
                    .hand
                    .iter()
                    .position(|v| *v == id)
                    .unwrap();
                self.players[pid].hand.remove(i);
                self.agent_discard.push(id);
            }
            self.draw_to(pid, 4, chance);
            self.mulligan_done.push(pid);
            if self.mulligan_done.len() == 2 {
                self.phase = "play".into();
                self.turn_pid = Some(0);
                self.turn_number = 1;
            }
            return Ok(());
        }
        if self.pending.is_some() {
            self.apply_choice(mv);
        } else {
            let id = n(mv, "card_id") as u16;
            let card = &rules().cards[&id];
            let i = self.players[pid]
                .hand
                .iter()
                .position(|v| *v == id)
                .unwrap();
            self.players[pid].hand.remove(i);
            self.begin(pid, &card.name);
            match s(mv, "action") {
                "recruit" => {
                    let p = planet(&card.planet);
                    self.players[pid].credits -=
                        (card.cost - self.players[pid].columns[p].len() as i32).max(0);
                    self.players[pid].columns[p].push(id);
                    let mut tasks = vec![influence(&card.planet, 1)];
                    tasks.extend(rules().card_effects[&id].clone());
                    self.queue(tasks, pid);
                }
                "technology" => {
                    self.agent_discard.push(id);
                    assert!(self.develop(pid, faction(&card.faction), 0));
                }
                "leader" => {
                    self.agent_discard.push(id);
                    let reward = match card.faction.as_str() {
                        "robot" => json!({"type":"zenithium","amount":1,"target":"self"}),
                        "human" => json!({"type":"credits","amount":3,"target":"self"}),
                        _ => json!({"type":"mobilize","count":2,"influence_each":false}),
                    };
                    self.queue(vec![json!({"type":"leader","level":1}), reward], pid);
                }
                _ => unreachable!(),
            }
        }
        if self.phase != "over" {
            self.drain(chance);
        }
        Ok(())
    }

    fn apply_choice(&mut self, mv: &Value) {
        let mut task = self.pending.as_mut().unwrap().queue.remove(0);
        task.as_object_mut().unwrap().remove("options");
        let pid = n(&task, "actor") as usize;
        let kind = s(&task, "type").to_owned();
        let mut rewards = vec![];
        let mut keep = false;
        match kind.as_str() {
            "influence" | "influence_other" => {
                let p = s(mv, "planet");
                self.pending.as_mut().unwrap().context["last_planet"] = json!(p);
                if !b(&task, "_bonus") {
                    self.pending.as_mut().unwrap().context["last_nonbonus_planet"] = json!(p);
                }
                let who = if s(&task, "target") == "opponent" {
                    1 - pid
                } else {
                    pid
                };
                let bonus = self.gain_influence(who, planet(p), n(&task, "amount"));
                let bonus_len = bonus.len();
                self.queue(bonus, who);
                self.adjust_influence_queue(&task, p, n(&task, "amount"), bonus_len);
            }
            "split_influence" => {
                let mut selected = arr(&task, "selected");
                let index = selected.len();
                let p = s(mv, "planet");
                selected.push(json!(p));
                task["selected"] = json!(selected);
                self.pending.as_mut().unwrap().context["last_planet"] = json!(p);
                if !b(&task, "_bonus") {
                    self.pending.as_mut().unwrap().context["last_nonbonus_planet"] = json!(p);
                }
                rewards = self.gain_influence(
                    pid,
                    planet(p),
                    task["amounts"][index].as_i64().unwrap() as i32,
                );
                keep = selected.len() < arr(&task, "amounts").len();
            }
            "optional" => {
                if b(mv, "accept") && self.pay(pid, &task["cost"]) {
                    rewards = arr(&task, "then");
                }
            }
            "choose_branch" => {
                rewards = arr(&task["branches"][n(mv, "branch") as usize], "tasks");
            }
            "exile" | "exile_for_matching" => {
                let owner = if s(&task, "owner").is_empty() {
                    if kind == "exile_for_matching" {
                        "self"
                    } else {
                        "opponent"
                    }
                } else {
                    s(&task, "owner")
                };
                let p = s(mv, "planet");
                let id = self.discard_top(if owner == "self" { pid } else { 1 - pid }, planet(p));
                task["done"] = json!(n(&task, "done") + 1);
                let mut used = arr(&task, "used");
                used.push(json!(p));
                task["used"] = json!(used);
                let reward = s(&task, "reward");
                if reward == "matching_influence" || kind == "exile_for_matching" {
                    rewards
                        .push(json!({"type":"influence","planet":p,"amount":nd(&task,"amount",1)}));
                } else if reward == "card_cost" {
                    rewards.push(
                        json!({"type":"credits","amount":rules().cards[&id].cost,"target":"self"}),
                    );
                }
                keep = n(&task, "done") < nd(&task, "count", 1);
                if !keep && task["reward"].is_object() {
                    rewards.insert(0,json!({"type":task["reward"]["resource"],"amount":task["reward"]["amount"],"target":"self"}));
                }
            }
            "transfer" => {
                let p = s(mv, "planet");
                let id = self.transfer(pid, planet(p));
                task["done"] = json!(n(&task, "done") + 1);
                match s(&task, "reward") {
                    "matching_influence" => rewards.push(influence(p, 1)),
                    "card_cost" => rewards.push(
                        json!({"type":"credits","amount":rules().cards[&id].cost,"target":"self"}),
                    ),
                    _ => (),
                }
                keep = n(&task, "done") < n(&task, "count");
            }
            "discard_hand" => {
                let id = n(mv, "card_id") as u16;
                let i = self.players[pid]
                    .hand
                    .iter()
                    .position(|v| *v == id)
                    .unwrap();
                self.players[pid].hand.remove(i);
                self.agent_discard.push(id);
                match s(&task, "reward") {
                    "matching_influence" => rewards.push(influence(&rules().cards[&id].planet, 1)),
                    "card_cost" => rewards.push(
                        json!({"type":"credits","amount":rules().cards[&id].cost,"target":"self"}),
                    ),
                    _ => (),
                }
                if s(&task, "count") == "all" {
                    keep = !self.players[pid].hand.is_empty();
                } else {
                    task["done"] = json!(n(&task, "done") + 1);
                    keep = n(&task, "done") < n(&task, "count");
                }
            }
            "develop" => {
                self.develop(pid, faction(s(mv, "faction")), n(&task, "discount"));
            }
            "exile_tier" => {
                let tier = n(mv, "tier");
                if tier > 0 {
                    let p = planet(s(&task, "planet"));
                    // BGA can leave a stale tier prompt after the planet has
                    // already been captured.  The prompt still awards its
                    // printed reward, but emits no discard packets.
                    if self.influence[p].is_some() {
                        for _ in 0..tier {
                            self.discard_top(pid, p);
                        }
                    }
                    let amount = if s(&task, "reward") == "zenithium" {
                        tier
                    } else {
                        match tier {
                            2 => 1,
                            4 => 2,
                            7 => 3,
                            _ => unreachable!(),
                        }
                    };
                    let mut reward = json!({"type":task["reward"],"amount":amount,"target":"self"});
                    if s(&task, "reward") == "influence" {
                        reward["planet"] = task["planet"].clone();
                    }
                    rewards.push(reward);
                }
            }
            "spend_tier" => {
                if n(mv, "cost") != 0 {
                    self.add_resource(pid, s(&task, "resource"), -n(mv, "cost"));
                    rewards.push(
                        json!({"type":"influence","amount":mv["amount"],"exclude":task["exclude"]}),
                    );
                }
            }
            "reset_planet" => {
                self.influence[planet(s(mv, "planet"))] = Some(0);
            }
            "take_board_bonus" => {
                let token = if s(mv, "bonus_area") == "planet" {
                    self.planet_bonus[planet(s(mv, "slot"))].take()
                } else {
                    self.technology_bonus[faction(s(mv, "slot"))].take()
                };
                self.award_bonus(pid, token.unwrap());
            }
            "optional_exile_each" => {
                let i = n(&task, "index") as usize;
                let ps = arr(&task, "planets");
                let p = ps[i].as_str().unwrap();
                if b(mv, "accept") && !self.players[pid].columns[planet(p)].is_empty() {
                    self.discard_top(pid, planet(p));
                    rewards.push(if s(&task, "reward") == "influence" {
                        influence(p, 1)
                    } else {
                        json!({"type":"zenithium","amount":1,"target":"self"})
                    });
                }
                task["index"] = json!(i + 1);
                keep = i + 1 < ps.len();
            }
            "two_adjacent" => {
                rewards = arr(mv, "planets")
                    .iter()
                    .map(|p| influence(p.as_str().unwrap(), n(&task, "amount")))
                    .collect();
            }
            "adjacent_three" => {
                let i = planet(s(mv, "planet"));
                rewards = vec![
                    influence(PLANETS[i], n(&task, "center")),
                    influence(PLANETS[i - 1], n(&task, "neighbor")),
                    influence(PLANETS[i + 1], n(&task, "neighbor")),
                ];
            }
            _ => panic!("unknown choice {kind}"),
        }
        if keep && self.phase != "over" {
            self.pending.as_mut().unwrap().queue.insert(0, task);
        }
        self.queue(rewards, pid);
    }

    fn drain(&mut self, c: &mut Chance) {
        while self.phase != "over" && self.pending.as_ref().is_some_and(|p| !p.queue.is_empty()) {
            let task = self.pending.as_ref().unwrap().queue[0].clone();
            let pid = n(&task, "actor") as usize;
            let kind = s(&task, "type");
            self.pending_pid = Some(pid);
            if kind == "optional" && !self.can_pay(pid, &task["cost"]) {
                self.pending.as_mut().unwrap().queue.remove(0);
                continue;
            }
            if matches!(
                kind,
                "influence"
                    | "influence_other"
                    | "split_influence"
                    | "optional"
                    | "choose_branch"
                    | "exile"
                    | "exile_for_matching"
                    | "transfer"
                    | "discard_hand"
                    | "develop"
                    | "exile_tier"
                    | "spend_tier"
                    | "reset_planet"
                    | "take_board_bonus"
                    | "optional_exile_each"
                    | "two_adjacent"
                    | "adjacent_three"
            ) {
                if kind == "exile" && b(&task, "require_full") && n(&task, "done") == 0 {
                    let who = if s(&task, "owner") == "self" {
                        pid
                    } else {
                        1 - pid
                    };
                    let available: usize = (0..5)
                        .filter(|p| PLANETS[*p] != s(&task, "exclude"))
                        .map(|p| self.players[who].columns[p].len())
                        .sum();
                    if available < (n(&task, "count") as usize) {
                        self.pending.as_mut().unwrap().queue.remove(0);
                        continue;
                    }
                }
                if kind == "influence" && !s(&task, "planet").is_empty() {
                    self.pending.as_mut().unwrap().queue.remove(0);
                    let who = if s(&task, "target") == "opponent" {
                        1 - pid
                    } else {
                        pid
                    };
                    let p = s(&task, "planet");
                    if !b(&task, "_bonus") {
                        self.pending.as_mut().unwrap().context["last_nonbonus_planet"] = json!(p);
                    }
                    self.pending.as_mut().unwrap().context["last_planet"] = json!(p);
                    let bonus =
                        self.gain_influence(who, planet(p), n(&task, "amount"));
                    self.queue(bonus, who);
                    continue;
                }
                let moves = self.choices(&task);
                if !moves.is_empty() {
                    self.pending.as_mut().unwrap().queue[0]["options"] = json!(moves);
                    return;
                }
                self.pending.as_mut().unwrap().queue.remove(0);
                continue;
            }
            self.pending.as_mut().unwrap().queue.remove(0);
            match kind {
                "credits" | "zenithium" => {
                    let who = if s(&task, "target") == "opponent" {
                        1 - pid
                    } else {
                        pid
                    };
                    self.add_resource(who, kind, n(&task, "amount"));
                }
                "leader" => self.gain_leader(pid, nd(&task, "level", 1)),
                "if_leader" => {
                    if self.leader.owner == Some(pid) {
                        self.queue(arr(&task, "then"), pid);
                    }
                }
                "if_credits" => {
                    if self.players[pid].credits >= n(&task, "amount") {
                        self.queue(arr(&task, "then"), pid);
                    }
                }
                "draw_bonus" => {
                    if let Some(token) = self.draw_bonus(c) {
                        self.award_bonus(pid, token);
                    }
                }
                "fixed_bonus" => {
                    if let Some(token) = self.technology_bonus[faction(s(&task, "faction"))].take()
                    {
                        self.award_bonus(pid, token);
                    }
                }
                "mobilize" => {
                    let count = if b(&task, "influence_each") {
                        1
                    } else {
                        n(&task, "count")
                    };
                    for _ in 0..count {
                        let Some(id) = self.draw_agent(c) else {
                            break;
                        };
                        let p = planet(&rules().cards[&id].planet);
                        self.players[pid].columns[p].push(id);
                        if b(&task, "influence_each") {
                            let mut tasks = vec![influence(PLANETS[p], 1)];
                            if n(&task, "count") > 1 {
                                let mut next = task.clone();
                                next["count"] = json!(n(&task, "count") - 1);
                                tasks.push(next);
                            }
                            self.queue(tasks, pid);
                        }
                    }
                }
                "transfer_each" => {
                    for p in arr(&task, "planets") {
                        let p = planet(p.as_str().unwrap());
                        if !self.players[1 - pid].columns[p].is_empty() {
                            self.transfer(pid, p);
                        }
                    }
                }
                "steal" => {
                    let amount =
                        n(&task, "amount").min(self.resource(1 - pid, s(&task, "resource")));
                    self.add_resource(1 - pid, s(&task, "resource"), -amount);
                    self.add_resource(pid, s(&task, "resource"), amount);
                }
                "per_tech_first" => {
                    let count = self.players[pid]
                        .technology
                        .iter()
                        .filter(|v| **v >= 1)
                        .count() as i32;
                    self.add_resource(pid, s(&task, "resource"), count * n(&task, "amount"));
                }
                "per_nonempty" => {
                    let who = if s(&task, "owner") == "self" {
                        pid
                    } else {
                        1 - pid
                    };
                    let count = self.players[who]
                        .columns
                        .iter()
                        .filter(|v| !v.is_empty())
                        .count() as i32;
                    self.players[pid].credits += count * n(&task, "amount");
                }
                "all_planets" => self.queue(
                    PLANETS
                        .iter()
                        .rev()
                        .map(|p| influence(p, n(&task, "amount")))
                        .collect(),
                    pid,
                ),
                "row_bonus_check" => {
                    let mut rewards = vec![];
                    for level in 1..=3 {
                        if !self.players[pid].row_bonuses.contains(&level)
                            && self.players[pid].technology.iter().all(|v| *v >= level)
                        {
                            self.players[pid].row_bonuses.push(level);
                            rewards
                                .push(json!({"type":"influence","amount":level,"target":"self"}));
                        }
                    }
                    self.queue(rewards, pid);
                }
                _ => panic!("unknown automatic task {kind}"),
            }
        }
        if self.phase != "over" && self.pending.as_ref().is_some_and(|p| p.queue.is_empty()) {
            self.finish_turn(c);
        }
    }

    pub fn validate(&self) -> Result<(), String> {
        if self.schema != 1 || !["mulligan", "play", "over"].contains(&self.phase.as_str()) {
            return Err("schema/phase".into());
        }
        if self
            .turn_pid
            .into_iter()
            .chain(self.pending_pid)
            .chain(self.winner)
            .chain(self.leader.owner)
            .chain(self.mulligan_done.iter().copied())
            .any(|p| p > 1)
        {
            return Err("seat".into());
        }
        if !self.board_sides.iter().all(|s| (1..=2).contains(s)) {
            return Err("board side".into());
        }
        let mut cards = self.agent_deck.clone();
        cards.extend(&self.agent_discard);
        for p in &self.players {
            cards.extend(&p.hand);
            for col in &p.columns {
                cards.extend(col);
            }
            if p.credits < 0
                || p.zenithium < 0
                || p.technology.iter().any(|l| !(0..=5).contains(l))
                || p.captured.iter().any(|v| *v >= 5)
            {
                return Err("player range".into());
            }
        }
        cards.sort();
        if cards != rules().cards.keys().copied().collect::<Vec<_>>() {
            return Err("Agent conservation".into());
        }
        let mut bonuses = self.bonus_deck.clone();
        bonuses.extend(&self.bonus_discard);
        bonuses.extend(self.planet_bonus.iter().flatten());
        bonuses.extend(self.technology_bonus.iter().flatten());
        let mut expected = rules().bonus_pool.clone();
        bonuses.sort();
        expected.sort();
        if bonuses != expected {
            return Err("bonus conservation".into());
        }
        if self
            .influence
            .iter()
            .flatten()
            .any(|p| !(-3..=3).contains(p))
        {
            return Err("influence range".into());
        }
        if self.pending.is_some()
            && (self.pending_pid.is_none() || self.pending.as_ref().unwrap().queue.is_empty())
        {
            return Err("pending ownership".into());
        }
        Ok(())
    }
}

impl State {
    /// Rebuild a simulatable world from one seat's observation.
    ///
    /// This is the browser's entry point: Phase 5 hands a worker an observation,
    /// never a privileged `State`, so a search that needs a simulator has to
    /// reconstruct one. Every mechanical field is public in the observation
    /// except the agent deck, the bonus reserve and the opposing hand, and those
    /// three are dealt here from the unseen multiset so the conservation the
    /// search's own determinizer checks already holds. The result is therefore
    /// ONE sample from the seat's information set, not the true world; the
    /// search resamples it per simulation.
    ///
    /// A pending chain is refused rather than guessed. The observation exposes
    /// only `queue[0]` through a key whitelist, so the rest of the chain and its
    /// context cannot be rebuilt, and a search over an invented continuation
    /// would be searching a game that does not exist. Callers fall back to the
    /// ranker for those decisions.
    pub fn from_observation(observation: &Value, seed: u64) -> Result<Self, String> {
        let seat = observation["seat"].as_u64().ok_or("Observation has no seat")? as usize;
        if seat > 1 {
            return Err("Observation seat is out of range".into());
        }
        // A PENDING CHAIN IS RECONSTRUCTABLE WHEN THE CALLER SUPPLIES IT.
        //
        // Until 2026-09-13 this was an unconditional refusal, and it was the
        // single largest hole in the served bot: the observation redacts the
        // queue to its first task, so the Expert could not rebuild the position
        // and handed every effect-resolution choice to the 1-ply ranker instead
        // of searching it. That is **45.0% of all decisions with a real choice**
        // (10,537 of 23,394 over 300 games). The search never saw them, and the
        // plan it formed when it played the card was discarded by a different
        // policy two plies later in the same turn.
        //
        // `pending_chain()` is the missing half, and a caller that does not pass
        // it gets the old refusal -- so an old worker against a new build, or a
        // new worker against an old build, both degrade to exactly today's
        // behaviour rather than breaking.
        let pending_full = observation.get("pending_full").unwrap_or(&Value::Null);
        if !observation["pending"].is_null() && pending_full.is_null() {
            return Err("Pending chains are not reconstructable from an observation".into());
        }
        let mut value = json!({});
        for key in [
            "schema","phase","turn_pid","turn_number","influence","captured_this_turn","leader",
            "board_sides","planet_bonus","technology_bonus","agent_discard","bonus_discard",
            "mulligan_done","pending_pid","winner",
        ] {
            value[key] = observation
                .get(key)
                .ok_or_else(|| format!("Observation is missing {key}"))?
                .clone();
        }
        value["pending"] = pending_full.clone();
        let observed = observation["players"]
            .as_array()
            .ok_or("Observation has no players")?;
        if observed.len() != 2 {
            return Err("Observation must carry both seats".into());
        }
        let mut players = vec![];
        for (index, source) in observed.iter().enumerate() {
            let mut player = json!({});
            for key in ["credits", "zenithium", "columns", "technology", "row_bonuses", "captured"] {
                player[key] = source
                    .get(key)
                    .ok_or_else(|| format!("Observation player is missing {key}"))?
                    .clone();
            }
            player["hand"] = if index == seat {
Value::Array(source["hand"].as_array().ok_or("Observation hides the observer's own hand")?.clone())
            } else {
                json!([])
            };
            players.push(player);
        }
        value["players"] = json!(players);
        value["agent_deck"] = json!([]);
        value["bonus_deck"] = json!([]);
        let mut state: State = serde_json::from_value(value).map_err(|err| format!("Observation does not describe a state: {err}"))?;

        // Deal the three hidden pools from what this seat provably cannot see.
        let mut known: BTreeSet<u16> = state.players[seat].hand.iter().copied().collect();
        known.extend(state.agent_discard.iter().copied());
        for player in &state.players {
            for column in &player.columns {
                known.extend(column.iter().copied());
            }
        }
        let mut unseen: Vec<u16> = rules().cards.keys().filter(|id| !known.contains(id)).copied().collect();
        let hand = observation["players"][1 - seat]["hand_count"].as_u64().ok_or("Observation has no opposing hand count")? as usize;
        let deck = observation["agent_deck_count"].as_u64().ok_or("Observation has no agent deck count")? as usize;
        if unseen.len() != hand + deck {
            return Err("Observation agent conservation mismatch".into());
        }
        let mut chance = Chance::seeded(seed);
        chance.shuffle(&mut unseen);
        state.players[1 - seat].hand = unseen.drain(..hand).collect();
        state.agent_deck = unseen;

        let mut bonuses = rules().bonus_pool.clone();
        bonuses.sort();
        for id in state
            .bonus_discard
            .iter()
            .copied()
            .chain(state.planet_bonus.iter().chain(state.technology_bonus.iter()).filter_map(|x| *x))
        {
            let index = bonuses.iter().position(|b| *b == id).ok_or("Observation bonus conservation mismatch")?;
            bonuses.remove(index);
        }
        if bonuses.len() != observation["bonus_deck_count"].as_u64().ok_or("Observation has no bonus reserve count")? as usize {
            return Err("Observation bonus reserve mismatch".into());
        }
        chance.shuffle(&mut bonuses);
        state.bonus_deck = bonuses;
        Ok(state)
    }
}


#[cfg(test)]
mod observation_reconstruction {
    use super::*;

    #[test]
    fn direct_observation_matches_serialized_projection() {
        let (mut state, mut chance) = State::new(808, [2, 1, 2]);
        for step in 0..160 {
            for view in 0..2 {
                assert_eq!(
                    state.observation(view),
                    state.observation_serde(view),
                    "observation drift at step {step}, seat {view}"
                );
            }
            let Some(seat) = state.actor() else { break };
            let moves = state.legal_moves(seat);
            let mv = moves[chance.index(moves.len())].clone();
            state.apply(seat, &mv, &mut chance).unwrap();
        }
    }

    #[test]
    fn rebuilt_world_matches_every_public_field_and_the_legal_moves() {
        let (mut state, mut chance) = State::new(404, [1, 2, 1]);
        let mut checked = 0;
        for step in 0..160 {
            let Some(seat) = state.actor() else { break };
            for view in 0..2 {
                let obs = state.observation(view);
                match State::from_observation(&obs, 77 + step) {
                    Err(error) => {
                        // The only sanctioned refusal is a pending chain, which
                        // the observation redacts down to its first task.
                        assert!(!obs["pending"].is_null(), "unexpected refusal: {error}");
                    }
                    Ok(world) => {
                        assert!(obs["pending"].is_null());
                        // Public mechanics must survive verbatim.
                        assert_eq!(world.phase, state.phase);
                        assert_eq!(world.turn_pid, state.turn_pid);
                        assert_eq!(world.turn_number, state.turn_number);
                        assert_eq!(world.influence, state.influence);
                        assert_eq!(world.captured_this_turn, state.captured_this_turn);
                        assert_eq!(world.leader, state.leader);
                        assert_eq!(world.board_sides, state.board_sides);
                        assert_eq!(world.planet_bonus, state.planet_bonus);
                        assert_eq!(world.technology_bonus, state.technology_bonus);
                        assert_eq!(world.agent_discard, state.agent_discard);
                        assert_eq!(world.bonus_discard, state.bonus_discard);
                        assert_eq!(world.mulligan_done, state.mulligan_done);
                        assert_eq!(world.winner, state.winner);
                        for index in 0..2 {
                            assert_eq!(world.players[index].credits, state.players[index].credits);
                            assert_eq!(world.players[index].zenithium, state.players[index].zenithium);
                            assert_eq!(world.players[index].columns, state.players[index].columns);
                            assert_eq!(world.players[index].technology, state.players[index].technology);
                            assert_eq!(world.players[index].row_bonuses, state.players[index].row_bonuses);
                            assert_eq!(world.players[index].captured, state.players[index].captured);
                            // Counts are public even where identity is not.
                            assert_eq!(world.players[index].hand.len(), state.players[index].hand.len());
                        }
                        assert_eq!(world.agent_deck.len(), state.agent_deck.len());
                        assert_eq!(world.bonus_deck.len(), state.bonus_deck.len());
                        // The observer's own hand is known exactly; the opponent's is not.
                        let mut mine = world.players[view].hand.clone();
                        let mut real = state.players[view].hand.clone();
                        mine.sort();
                        real.sort();
                        assert_eq!(mine, real);
                        // The search branches on this list, so the same options
                        // must be offered. Order cannot match and must not be
                        // asserted: the observation sorts the observer's hand,
                        // so draw order is not recoverable -- and is not public
                        // either. The search sorts moves before expanding them.
                        let key = |mut m: Vec<Value>| {
                            m.sort_by_key(|v| serde_json::to_string(v).unwrap());
                            m
                        };
                        assert_eq!(key(world.legal_moves(view)), key(state.legal_moves(view)));
                        // No card exists twice across the rebuilt world.
                        let mut seen = BTreeSet::new();
                        for id in world.players.iter().flat_map(|p| p.hand.iter().chain(p.columns.iter().flatten()))
                            .chain(world.agent_deck.iter()).chain(world.agent_discard.iter()) {
                            assert!(seen.insert(*id), "card {id} duplicated by reconstruction");
                        }
                        checked += 1;
                    }
                }
            }
            let moves = state.legal_moves(seat);
            let mv = moves[chance.index(moves.len())].clone();
            state.apply(seat, &mv, &mut chance).unwrap();
        }
        assert!(checked > 40, "too few reconstructable positions exercised: {checked}");
    }

    #[test]
    fn reconstruction_cannot_see_the_opposing_hand() {
        let (mut state, mut chance) = State::new(91, [2, 1, 2]);
        for _ in 0..12 {
            let Some(seat) = state.actor() else { break };
            let moves = state.legal_moves(seat);
            let mv = moves[chance.index(moves.len())].clone();
            state.apply(seat, &mv, &mut chance).unwrap();
        }
        let seat = 0;
        let obs = state.observation(seat);
        if obs["pending"].is_null() {
            let mut swapped = state.clone();
            // Permute everything this seat cannot legally see.
            swapped.agent_deck.reverse();
            swapped.bonus_deck.reverse();
            let card = swapped.agent_deck.pop().unwrap();
            let old = std::mem::replace(&mut swapped.players[1].hand[0], card);
            swapped.agent_deck.push(old);
            assert_eq!(swapped.observation(seat), obs, "hidden change altered the observation");
            let a = State::from_observation(&obs, 5).unwrap();
            let b = State::from_observation(&swapped.observation(seat), 5).unwrap();
            assert_eq!(a, b, "reconstruction depends on unseen state");
        }
    }
}

#[cfg(test)]
mod pending_reconstruction {
    use super::*;
    use std::collections::BTreeSet;

    /// Walk a real game with the shipped ranker and hand each position to `f`.
    fn walk(seed: u64, steps: usize, mut f: impl FnMut(&State, usize)) {
        let sides = [1 + ((seed >> 3) & 1) as i32, 2, 1];
        let (mut state, mut chance) = State::new(seed, sides);
        for _ in 0..steps {
            let Some(actor) = state.actor() else { return };
            let legal = state.legal_moves(actor);
            if legal.is_empty() {
                return;
            }
            f(&state, actor);
            let observation = state.observation(actor);
            let best = (0..legal.len())
                .max_by(|&a, &b| {
                    crate::serving::action_score(&observation, &legal[a])
                        .partial_cmp(&crate::serving::action_score(&observation, &legal[b]))
                        .unwrap_or(std::cmp::Ordering::Equal)
                })
                .unwrap();
            if state.apply(actor, &legal[best], &mut chance).is_err() {
                return;
            }
        }
    }

    /// The observation as the search receives it: the frozen policy input with
    /// the chain alongside, merged by the caller. This mirrors exactly what the
    /// browser worker and the arena do.
    fn searchable_observation(state: &State, seat: usize) -> Value {
        let mut observation = state.observation(seat);
        observation["pending_full"] = state.pending_chain();
        observation
    }

    #[test]
    fn a_pending_chain_round_trips_and_offers_the_same_moves() {
        let mut reconstructed = 0;
        for seed in [7u64, 77, 404, 1234, 99_991] {
            walk(seed, 400, |state, actor| {
                if state.pending.is_none() {
                    return;
                }
                let world = State::from_observation(&searchable_observation(state, actor), 5)
                    .expect("a chain supplied alongside the observation must rebuild");
                // THE INVARIANT THAT MATTERS. A world whose pending chain came
                // back subtly different would still search, still return a move,
                // and still be validated by the room -- it would just be
                // answering a different question. Legal-move identity is what
                // makes the reconstruction usable rather than merely present.
                assert_eq!(
                    world.legal_moves(actor),
                    state.legal_moves(actor),
                    "seed {seed}: the rebuilt chain offers different moves"
                );
                assert_eq!(
                    world.pending.as_ref().map(|p| &p.queue),
                    state.pending.as_ref().map(|p| &p.queue),
                    "seed {seed}: the queue did not survive the round trip"
                );
                assert_eq!(world.pending_pid, state.pending_pid);
                reconstructed += 1;
            });
        }
        assert!(
            reconstructed > 50,
            "only {reconstructed} pending positions reached; this test would prove little"
        );
    }

    /// THE LEAK GATE. The chain is public card text plus planets and counters --
    /// that is the whole argument for sending it, and an argument is not a
    /// guard. A future effect that embedded a DRAWN card id in its task would
    /// hand the opponent's hand or the deck order to the client, silently, and
    /// every other test here would still pass.
    #[test]
    fn the_pending_chain_carries_no_hidden_cards() {
        fn scan(value: &Value, out: &mut Vec<u64>) {
            match value {
                Value::Number(number) => {
                    if let Some(found) = number.as_u64() {
                        out.push(found);
                    }
                }
                Value::Array(items) => items.iter().for_each(|item| scan(item, out)),
                Value::Object(map) => map.values().for_each(|item| scan(item, out)),
                Value::String(text) => {
                    if let Ok(found) = text.parse::<u64>() {
                        out.push(found);
                    }
                }
                _ => {}
            }
        }

        let mut checked = 0;
        for seed in [7u64, 77, 404, 1234, 99_991] {
            walk(seed, 400, |state, actor| {
                let chain = state.pending_chain();
                if chain.is_null() {
                    return;
                }
                // Everything this seat provably cannot see.
                let mut hidden: BTreeSet<u16> =
                    state.players[1 - actor].hand.iter().copied().collect();
                hidden.extend(state.agent_deck.iter().copied());
                hidden.extend(state.bonus_deck.iter().copied());

                let mut found: Vec<u64> = Vec::new();
                scan(&chain, &mut found);
                for value in found {
                    if value > u16::MAX as u64 {
                        continue;
                    }
                    let id = value as u16;
                    // AGENT CARDS ONLY, and the exclusion is forced rather than
                    // convenient. Bonus token ids are 1..=8, which is the same
                    // value space as a task's `amount`, `index` and planet
                    // indices -- the first cut of this gate flagged a literal
                    // `3` in a chain as "bonus token 3 is in the hidden deck",
                    // which is unfalsifiable by value alone. Agent ids are
                    // 101..=518 and share their space with nothing, so a hit
                    // there is a real leak. Bonus tokens cannot leak through a
                    // chain by construction: a token enters the queue as its
                    // EFFECT PROGRAM, never as its id, and the two face-up rows
                    // are already public.
                    if !rules().cards.contains_key(&id) {
                        continue;
                    }
                    assert!(
                        !hidden.contains(&id),
                        "seed {seed}: the pending chain names card {id}, which is hidden from \
                         seat {actor} -- sending it would leak the deck or the opposing hand"
                    );
                }
                checked += 1;
            });
        }
        assert!(checked > 50, "only {checked} chains inspected; this gate would prove little");
    }

    /// A caller that does not supply the chain must get the OLD refusal, which
    /// is what lets a new build and an old worker meet in either order without
    /// a coupled deploy.
    #[test]
    fn an_observation_without_the_chain_is_still_refused() {
        let mut refused = 0;
        for seed in [77u64, 404, 1234] {
            walk(seed, 400, |state, actor| {
                if state.pending.is_none() {
                    return;
                }
                assert!(
                    State::from_observation(&state.observation(actor), 5).is_err(),
                    "a bare observation must not silently rebuild a chain"
                );
                refused += 1;
            });
        }
        assert!(refused > 20, "only {refused} positions exercised the refusal");
    }

    /// A position with no chain must be unaffected -- the merge adds a null and
    /// nothing else changes.
    #[test]
    fn a_position_without_a_chain_rebuilds_exactly_as_before() {
        let mut checked = 0;
        for seed in [77u64, 404] {
            walk(seed, 300, |state, actor| {
                if state.pending.is_some() {
                    return;
                }
                let with = State::from_observation(&searchable_observation(state, actor), 11);
                let without = State::from_observation(&state.observation(actor), 11);
                match (with, without) {
                    (Ok(left), Ok(right)) => {
                        assert_eq!(left, right, "the merged null changed the rebuild")
                    }
                    (Err(_), Err(_)) => {}
                    _ => panic!("the merge changed whether the rebuild succeeds"),
                }
                checked += 1;
            });
        }
        assert!(checked > 50);
    }
}
