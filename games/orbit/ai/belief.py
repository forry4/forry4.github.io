"""Hidden-state sampling for Orbit information-set search.

``sample_hidden`` remains the deliberately small current-observation prior used
by the Phase 1 conservation tests.  ``HistoryBelief`` is the Phase 2 layer on
top: it carries particles forward between observations and conditions them on
publicly identified opponent actions.  It is still an approximate particle
belief, not an exact Bayesian posterior.  In particular, an unknown mulligan
is re-poolled rather than pretending that its discarded identities were seen.

The module never accepts a privileged game dictionary.  A policy can therefore
use a belief without accidentally learning the true opponent hand or deck.
"""
from __future__ import annotations

from dataclasses import dataclass
from collections import Counter
import copy
import math
import random
from typing import Callable

from ..cards import BONUS_POOL, CARDS
from .state import SCHEMA_VERSION, rules_fingerprint


def sample_hidden(observation: dict, rng: random.Random) -> dict:
    me = observation["seat"]
    known = list(observation["players"][me]["hand"]) + list(observation["agent_discard"])
    for player in observation["players"]:
        for column in player["columns"]:
            known.extend(column)
    if len(set(known)) != len(known) or not set(known) <= set(CARDS):
        raise ValueError("Inconsistent observed Agent inventory")
    unseen = sorted(set(CARDS) - set(known))
    hand_count = observation["players"][1 - me]["hand_count"]
    if len(unseen) != hand_count + observation["agent_deck_count"]:
        raise ValueError("Observed Agent counts do not conserve the deck")
    rng.shuffle(unseen)
    visible = list(observation["bonus_discard"])
    visible += [v for v in observation["planet_bonus"] + observation["technology_bonus"] if v is not None]
    remaining = Counter(BONUS_POOL)
    remaining.subtract(visible)
    if any(v < 0 for v in remaining.values()):
        raise ValueError("Inconsistent observed bonus inventory")
    bonuses = sorted(remaining.elements())
    if len(bonuses) != observation["bonus_deck_count"]:
        raise ValueError("Observed bonus counts do not conserve the reserve")
    rng.shuffle(bonuses)
    return {"opponent_hand": sorted(unseen[:hand_count]),
            "agent_deck": unseen[hand_count:], "bonus_deck": bonuses}


@dataclass
class Particle:
    """One feasible assignment for the currently hidden pools.

    Lists retain a sampled order because draw order matters to a simulator.
    ``weight`` is only used while conditioning; particles are resampled after
    every update so a policy normally sees an unweighted finite population.
    """

    opponent_hand: list[int]
    agent_deck: list[int]
    bonus_deck: list[int]
    weight: float = 1.0

    def as_dict(self) -> dict:
        return {
            "opponent_hand": list(self.opponent_hand),
            "agent_deck": list(self.agent_deck),
            "bonus_deck": list(self.bonus_deck),
        }

    @classmethod
    def from_dict(cls, value: dict) -> "Particle":
        return cls(
            opponent_hand=list(value["opponent_hand"]),
            agent_deck=list(value["agent_deck"]),
            bonus_deck=list(value["bonus_deck"]),
            weight=float(value.get("weight", 1.0)),
        )


def _hidden_card_set(observation: dict) -> set[int]:
    me = observation["seat"]
    known = set(observation["players"][me]["hand"])
    known.update(observation["agent_discard"])
    for player in observation["players"]:
        for column in player["columns"]:
            known.update(column)
    return set(CARDS) - known


def _hidden_bonus_multiset(observation: dict) -> Counter:
    visible = list(observation["bonus_discard"])
    visible.extend(
        value
        for value in observation["planet_bonus"] + observation["technology_bonus"]
        if value is not None
    )
    result = Counter(BONUS_POOL)
    result.subtract(visible)
    if any(value < 0 for value in result.values()):
        raise ValueError("Inconsistent observed bonus inventory")
    return result


def _normalise_particle(particle: Particle, observation: dict, rng: random.Random) -> Particle | None:
    """Project an old particle onto a newer public observation.

    Public cards are removed from the hidden pools.  Any identities that became
    unknown because a player drew or mulliganed are filled from the remaining
    unseen set.  This preserves public card evidence across time while keeping
    genuinely hidden choices sampled.
    """

    unseen = _hidden_card_set(observation)
    hand_count = int(observation["players"][1 - observation["seat"]]["hand_count"])
    old_pool = list(particle.opponent_hand) + list(particle.agent_deck)
    if len(set(old_pool)) != len(old_pool):
        return None
    # The old sample may contain a card that has just become public.  Removing
    # it is exactly the conditioning event for a revealed play.
    kept = [card for card in old_pool if card in unseen]
    if len(set(kept)) != len(kept) or not set(kept) <= unseen:
        return None
    missing = list(unseen - set(kept))
    rng.shuffle(missing)
    kept.extend(missing)
    if len(kept) != len(unseen):
        return None
    # Preserve the relative order of cards that stayed hidden and insert newly
    # unknown cards at random positions.  The precise insertion distribution is
    # not a claim about the game; it simply avoids turning every draw into a
    # deterministic top card.
    if len(missing) > 1:
        rng.shuffle(kept)
    opponent_hand = kept[:hand_count]
    agent_deck = kept[hand_count:]

    expected_bonus = _hidden_bonus_multiset(observation)
    bonuses = [value for value in particle.bonus_deck if expected_bonus[value] > 0]
    counts = Counter(bonuses)
    if counts != expected_bonus:
        # A token can have moved between the reserve and a public discard since
        # the previous observation.  Reconstruct only that hidden reserve; no
        # public token identity is lost.
        bonuses = list(expected_bonus.elements())
        rng.shuffle(bonuses)
    return Particle(opponent_hand, agent_deck, bonuses)


def _public_action_compatibility(
    particle: Particle,
    event: dict | None,
    previous_observation: dict | None,
    current_observation: dict,
) -> float:
    """Return a likelihood for one particle and one public event.

    A public card play is hard evidence: immediately before the event that card
    had to be in the opponent's hand.  Mulligan counts and opaque choice tasks
    carry no card identity, so they receive the neutral likelihood of one.  A
    caller may supply a soft opponent-model likelihood through ``action_model``
    in :meth:`HistoryBelief.update`.
    """

    if not previous_observation:
        return 1.0
    # A newly visible card in the root player's hand was drawn from the deck,
    # so a particle that had already placed it in the opponent's hand is
    # impossible.  Conversely, every hidden card that newly entered the public
    # discard/columns must have come from that opponent's old hand.  Checking
    # this before projection prevents a particle from silently moving a card
    # from the wrong hidden pool just because the card vanished from the pool.
    previous_hidden = _hidden_card_set(previous_observation)
    current_hidden = _hidden_card_set(current_observation)
    newly_visible = previous_hidden - current_hidden
    seat = int(previous_observation["seat"])
    previous_hand = set(previous_observation["players"][seat].get("hand", []))
    current_hand = set(current_observation["players"][seat].get("hand", []))
    own_draws = (current_hand - previous_hand) & newly_visible
    opponent_reveals = newly_visible - own_draws
    opponent_hand = set(particle.opponent_hand)
    if any(card in opponent_hand for card in own_draws):
        return 0.0
    if any(card not in opponent_hand for card in opponent_reveals):
        return 0.0
    public = (event or {}).get("public_action")
    if not public or public.get("action") not in {"recruit", "technology", "leader"}:
        return 1.0
    actor = int((event or {}).get("actor", -1))
    if actor != 1 - int(previous_observation["seat"]):
        return 1.0
    card_id = public.get("card_id")
    if card_id is None:
        return 1.0
    return 1.0 if int(card_id) in particle.opponent_hand else 0.0


class HistoryBelief:
    """A finite, sequentially conditioned hidden-state belief.

    Parameters are intentionally explicit so experiment manifests can record
    the exact particle budget and seed.  ``update`` accepts the public event
    shape emitted by :class:`games.orbit.ai.history.Session`; callers can also
    pass an opponent action-likelihood function for an ablation.
    """

    VERSION = 1

    def __init__(self, observation: dict, *, particles: int = 128, seed: int = 0):
        if particles < 1:
            raise ValueError("particles must be positive")
        self.particle_count = int(particles)
        self.seed = int(seed)
        self.rng = random.Random(seed)
        self.seat = int(observation["seat"])
        self.schema = int(observation.get("schema", SCHEMA_VERSION))
        if self.schema != SCHEMA_VERSION:
            raise ValueError("Orbit belief observation schema mismatch")
        self.rules = rules_fingerprint()
        self.step_count = 0
        self.last_observation = copy.deepcopy(observation)
        self.particles = [
            Particle.from_dict(sample_hidden(observation, self.rng))
            for _ in range(self.particle_count)
        ]

    @property
    def version(self) -> int:
        return self.VERSION

    def _resample(self, weighted: list[Particle]) -> None:
        total = sum(max(0.0, p.weight) for p in weighted)
        if not math.isfinite(total) or total <= 0:
            # A soft model can be too sharp for a finite particle population.
            # Recover from the current public prior rather than returning an
            # impossible hidden world.
            self.particles = [
                Particle.from_dict(sample_hidden(self.last_observation, self.rng))
                for _ in range(self.particle_count)
            ]
            return
        # Systematic resampling has lower variance than independent roulette
        # draws and is deterministic for a recorded seed.
        stride = total / self.particle_count
        cursor = self.rng.random() * stride
        cumulative = 0.0
        index = 0
        result: list[Particle] = []
        for _ in range(self.particle_count):
            target = cursor
            while index < len(weighted) - 1 and cumulative + max(0.0, weighted[index].weight) < target:
                cumulative += max(0.0, weighted[index].weight)
                index += 1
            result.append(copy.deepcopy(weighted[index]))
            cursor += stride
        for particle in result:
            particle.weight = 1.0
        self.particles = result

    def update(
        self,
        observation: dict,
        event: dict | None = None,
        *,
        action_model: Callable[[dict, dict, dict], float] | None = None,
    ) -> None:
        """Condition particles on the next observation and public event.

        ``action_model`` receives ``(particle_dict, event, observation)`` and
        returns a non-negative likelihood.  It must only use information the
        observed opponent could have used; the belief class cannot verify that
        property, so experiment code should treat it as part of the model's
        audited contract.
        """

        if int(observation.get("schema", self.schema)) != self.schema:
            raise ValueError("Orbit belief observation schema mismatch")
        if int(observation["seat"]) != self.seat:
            raise ValueError("Orbit belief seat mismatch")
        previous = self.last_observation
        weighted: list[Particle] = []
        for old in self.particles:
            # Test the action against the *pre-event* hidden hand before the
            # projection removes the now-public card.
            weight = _public_action_compatibility(old, event, previous, observation)
            particle = _normalise_particle(old, observation, self.rng)
            if particle is None:
                continue
            if action_model is not None and weight:
                # Action likelihoods describe the choice made from the
                # pre-event hidden world; the normalized particle has already
                # removed any card that the event revealed.
                weight *= max(0.0, float(action_model(old.as_dict(), event or {}, observation)))
            particle.weight = weight
            weighted.append(particle)
        if not weighted or not any(p.weight > 0 for p in weighted):
            # Re-seed from the current observation, then apply only the hard
            # card identity constraint.  This path is expected after a long
            # hidden sequence exhausts a finite particle population.
            weighted = []
            for _ in range(self.particle_count * 2):
                particle = Particle.from_dict(sample_hidden(observation, self.rng))
                # The fallback starts at the post-event observation, so hard
                # card evidence is already represented by the public pools.
                weight = 1.0
                if action_model is not None and weight:
                    weight *= max(0.0, float(action_model(particle.as_dict(), event or {}, observation)))
                particle.weight = weight
                weighted.append(particle)
        self.last_observation = copy.deepcopy(observation)
        self.step_count += 1
        self._resample(weighted)

    def sample(self, rng: random.Random | None = None) -> dict:
        """Draw one feasible hidden world from the current particle set."""

        chooser = rng or self.rng
        if not self.particles:
            raise ValueError("Orbit belief has no particles")
        particle = self.particles[chooser.randrange(len(self.particles))]
        return particle.as_dict()

    def distribution(self) -> list[dict]:
        """Return a detached particle snapshot for diagnostics and archives."""

        return [particle.as_dict() for particle in self.particles]

    def archive(self) -> dict:
        return {
            "version": self.VERSION,
            "schema": self.schema,
            "rules": self.rules,
            "seat": self.seat,
            "particle_count": self.particle_count,
            "seed": self.seed,
            "step_count": self.step_count,
            "last_observation": copy.deepcopy(self.last_observation),
            "particles": self.distribution(),
            "rng_state": [self.rng.getstate()[0], list(self.rng.getstate()[1]), self.rng.getstate()[2]],
        }

    @classmethod
    def restore(cls, archive: dict) -> "HistoryBelief":
        if int(archive.get("version", -1)) != cls.VERSION:
            raise ValueError("Orbit belief version mismatch")
        if archive.get("rules", rules_fingerprint()) != rules_fingerprint():
            raise ValueError("Orbit belief rules fingerprint mismatch")
        if int(archive.get("schema", -1)) != SCHEMA_VERSION:
            raise ValueError("Orbit belief schema mismatch")
        result = cls(
            archive["last_observation"],
            particles=int(archive["particle_count"]),
            seed=int(archive["seed"]),
        )
        result.schema = int(archive["schema"])
        result.seat = int(archive["seat"])
        result.step_count = int(archive["step_count"])
        result.particles = [Particle.from_dict(value) for value in archive["particles"]]
        if len(result.particles) != result.particle_count:
            raise ValueError("Orbit belief particle count mismatch")
        if "rng_state" in archive:
            state = archive["rng_state"]
            result.rng.setstate((int(state[0]), tuple(state[1]), state[2]))
        return result
