//! HOW BIG IS THE PRIZE, AND DID THE RANKER FIX TAKE? Measured PAIRED.
//!
//! The first cut of this probe compared a run of the old ranker against a run
//! of the new one and the headline barely moved -- which was the probe's fault,
//! not the fix's. Changing the policy changes the GAMES, so the two runs were
//! scored over different positions: "contestable" fell from 58.5% to 51.7% and
//! match-point threats from 271 to 204 precisely BECAUSE the new ranker blocks
//! more, and a rate whose denominator moves with the treatment cannot be read.
//!
//! So both rankers are now scored on the SAME positions. The walk is driven by
//! one fixed policy and at every planet choice both rankings are computed, the
//! old one recovered by subtracting the new planet term and adding the old.
//! That is the same paired-comparison discipline the arenas use, at probe cost.
//!
//! AND THE BLUNDER IS DEFINED SHARPLY. "Declined a contested planet" is not a
//! mistake -- taking your own capture, or ignoring a threat that is worth
//! nothing, is usually right. The unambiguous error is: the opponent is ONE
//! influence from a capture that ENDS THE GAME, blocking it is legal, the seat
//! has no winning capture of its own available, and the ranker plays elsewhere.
use orbit_core::search::capture_gain;
use orbit_core::serving::action_score;
use orbit_core::State;
use serde_json::Value;

// IMPORTED, never retyped. The first cut of this probe hardcoded
// ["terra","mars","mercury","venus","jupiter"]; the real order is
// ["mercury","venus","terra","mars","jupiter"], so every `toward` read a
// DIFFERENT planet's disc than the one the move named and every blunder figure
// it produced was noise. It did not crash and the output looked entirely
// plausible -- two planets at the same distance simply scored 1.76 apart, which
// is what finally gave it away.
use orbit_core::PLANETS;
const CHOICE: f64 = 0.4;
const THREAT: f64 = 0.8;
const CONTEST_REACH: f64 = 3.0;
const CAPTURE: f64 = 1.0;

fn planet_index(name: &str) -> Option<usize> {
    PLANETS.iter().position(|p| *p == name)
}

/// The disc's signed distance in `seat`'s favour, or None while it is off the
/// board after a capture this turn.
fn toward(state: &State, planet: usize, seat: usize) -> Option<f64> {
    let dir = if seat == 0 { 1.0 } else { -1.0 };
    state.influence[planet].map(|pos| pos as f64 * dir)
}

fn influence_task(observation: &Value) -> bool {
    matches!(
        observation["pending"]["task"]["type"].as_str().unwrap_or(""),
        "influence" | "influence_other" | "split_influence"
    )
}

/// `new_term - old_term` for one planet choice, so the OLD ranking can be
/// recovered from the shipped `action_score` without keeping a second copy of
/// the whole function in step.
fn planet_term_delta(observation: &Value, state: &State, planet: usize, seat: usize) -> f64 {
    let Some(t) = toward(state, planet, seat) else { return 0.0 };
    let influence = influence_task(observation);
    // Term one: what the planet is worth. Old = the seat's own signed progress,
    // victory-blind and NEGATIVE on a contested planet.
    let old_choice = CHOICE * t;
    let new_choice = if influence && t < 0.0 {
        THREAT * capture_gain(observation, 1 - seat, planet) * (-t / CONTEST_REACH).min(1.0)
    } else {
        CHOICE * t
    };
    // Term two: the capture bonus. Old = a FLAT 2.0 for any capture at all.
    let amount = observation["pending"]["task"]["amount"]
        .as_f64()
        .unwrap_or(1.0)
        .max(1.0);
    let (old_capture, new_capture) = if influence && t + amount >= 4.0 {
        (2.0, CAPTURE * capture_gain(observation, seat, planet))
    } else {
        (0.0, 0.0)
    };
    (new_choice + new_capture) - (old_choice + old_capture)
}

/// Would capturing `planet` end the game for `who`? `capture_gain` returns the
/// winning sentinel exactly then.
fn capture_wins(observation: &Value, who: usize, planet: usize) -> bool {
    capture_gain(observation, who, planet) >= 2.2
}

#[derive(Default)]
struct Tally {
    blunders: u64,
}

fn main() {
    let games: u64 = std::env::args().nth(1).and_then(|a| a.parse().ok()).unwrap_or(60);

    let mut decisions = 0u64;
    let mut forced = 0u64;
    let mut pending_decisions = 0u64;
    let mut planet_decisions = 0u64;
    let mut match_point = 0u64; // blocking a game-ending capture was legal...
    let mut had_own_win = 0u64; // ...and taking the game outright was too
    let mut old = Tally::default();
    let mut new = Tally::default();

    for seed in 0..games {
        let sides = [1 + ((seed >> 3) & 1) as i32, 2, 1];
        let (mut state, mut chance) = State::new(seed.wrapping_mul(2_654_435_761), sides);
        let mut steps = 0u32;
        while let Some(actor) = state.actor() {
            steps += 1;
            if steps > 4000 {
                break;
            }
            let legal = state.legal_moves(actor);
            if legal.is_empty() {
                break;
            }
            let observation = state.observation(actor);
            let scores: Vec<f64> =
                legal.iter().map(|mv| action_score(&observation, mv)).collect();
            let pick = |adjust: &dyn Fn(usize) -> f64| -> usize {
                (0..legal.len())
                    .max_by(|&a, &b| {
                        (scores[a] + adjust(a))
                            .partial_cmp(&(scores[b] + adjust(b)))
                            .unwrap_or(std::cmp::Ordering::Equal)
                    })
                    .unwrap()
            };
            let zero = |_: usize| 0.0;
            let best_new = pick(&zero);

            if legal.len() < 2 {
                forced += 1;
            } else {
                decisions += 1;
                if state.pending.is_some() {
                    pending_decisions += 1;
                }
                let planets: Vec<Option<usize>> = legal
                    .iter()
                    .map(|mv| mv.get("planet").and_then(Value::as_str).and_then(planet_index))
                    .collect();
                if planets.iter().all(Option::is_some) && influence_task(&observation) {
                    planet_decisions += 1;
                    // Recover the OLD ranking on this same position.
                    let to_old = |i: usize| -> f64 {
                        planets[i]
                            .map(|p| -planet_term_delta(&observation, &state, p, actor))
                            .unwrap_or(0.0)
                    };
                    let best_old = pick(&to_old);

                    // The unambiguous blunder: a legal block on a capture that
                    // would END THE GAME for the opponent, one step away.
                    let blocking: Vec<usize> = planets
                        .iter()
                        .filter_map(|p| *p)
                        .filter(|p| {
                            toward(&state, *p, actor) == Some(-3.0)
                                && capture_wins(&observation, 1 - actor, *p)
                        })
                        .collect();
                    if !blocking.is_empty() {
                        match_point += 1;
                        // Taking the game yourself beats blocking; exclude it so
                        // the blunder count is not padded with correct play.
                        // A CAPTURE IS `toward + amount >= 4`, NOT `toward >= 3`.
                        // The first cut of this exclusion ignored the task's
                        // amount, so all four remaining "blunders" at 120 games
                        // were the bot TAKING THE GAME with a two-influence task
                        // from distance two -- correct play, counted as an error.
                        let amount = observation["pending"]["task"]["amount"]
                            .as_f64()
                            .unwrap_or(1.0)
                            .max(1.0);
                        let own_win = planets.iter().filter_map(|p| *p).any(|p| {
                            toward(&state, p, actor).is_some_and(|t| t + amount >= 4.0)
                                && capture_wins(&observation, actor, p)
                        });
                        if own_win {
                            had_own_win += 1;
                        } else {
                            if !blocking.contains(&planets[best_old].unwrap()) {
                                old.blunders += 1;
                            }
                            if !blocking.contains(&planets[best_new].unwrap()) {
                                new.blunders += 1;
                                if std::env::var("PROBE_DUMP").is_ok() && new.blunders <= 6 {
                                    let task = &observation["pending"]["task"];
                                    println!(
                                        "
  [blunder {}] seat {actor}  task={}  target={}  amount={}",
                                        new.blunders,
                                        task["type"].as_str().unwrap_or("?"),
                                        task["target"].as_str().unwrap_or("self"),
                                        task["amount"],
                                    );
                                    for (i, mv) in legal.iter().enumerate() {
                                        let Some(p) = planets[i] else { continue };
                                        println!(
                                            "      {:<9} toward={:>5.1}  theirGain={:.3}  myGain={:.3}  score={:+.3}{}",
                                            PLANETS[p],
                                            toward(&state, p, actor).unwrap_or(f64::NAN),
                                            capture_gain(&observation, 1 - actor, p),
                                            capture_gain(&observation, actor, p),
                                            scores[i],
                                            if i == best_new { "   <-- CHOSEN" }
                                            else if blocking.contains(&p) { "   (the block)" }
                                            else { "" },
                                        );
                                        if mv.get("planet").is_none() {
                                            println!("        (move has no planet field: {mv})");
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }

            if state.apply(actor, &legal[best_new], &mut chance).is_err() {
                break;
            }
        }
    }

    let pct = |n: u64, d: u64| if d == 0 { 0.0 } else { 100.0 * n as f64 / d as f64 };
    let judged = match_point - had_own_win;
    println!("over {games} games, both rankers scored on the SAME positions");
    println!();
    println!("  real decisions (2+ legal moves)     : {decisions}");
    println!("  forced (no policy involved)         : {forced}");
    println!(
        "  inside a pending chain              : {pending_decisions}  ({:.1}%)  <- NOT searched by the Expert",
        pct(pending_decisions, decisions)
    );
    println!(
        "  influence planet choices            : {planet_decisions}  ({:.1}%)",
        pct(planet_decisions, decisions)
    );
    println!();
    println!("  positions where blocking a GAME-ENDING capture was legal:");
    println!("      total                           : {match_point}");
    println!("      excluded (own win available)    : {had_own_win}");
    println!("      judged                          : {judged}");
    println!();
    println!(
        "      old ranker played elsewhere     : {}  ({:.1}% of judged)",
        old.blunders,
        pct(old.blunders, judged)
    );
    println!(
        "      new ranker played elsewhere     : {}  ({:.1}% of judged)",
        new.blunders,
        pct(new.blunders, judged)
    );
}
