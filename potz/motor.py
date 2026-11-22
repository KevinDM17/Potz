"""Estrategia de Potz para Texas Hold'em."""

from collections import Counter
from dataclasses import dataclass
from itertools import combinations
from random import Random
from dataclasses import dataclass, replace

import os
import sys
import time




DEBUG = os.environ.get("POTZ_LOG") == "1"
STAGES = {0: "preflop", 3: "flop", 4: "turn", 5: "river"}
RANKS = "23456789TJQKA"
SUITS = "cdhs"
DECK = tuple(rank + suit for suit in SUITS for rank in RANKS)
CARD_VALUES = {card: (RANKS.index(card[0]) + 2, card[1]) for card in DECK}
DEFAULT_STRONG_WEIGHT = 0.5
CHEN_HIGH_CARD_POINTS = {14: 10, 13: 8, 12: 7, 11: 6}
CHEN_GAP_PENALTIES = (0, 1, 2, 4, 5)
LOW_TRIPS_KICKER_MAX = 9


@dataclass(frozen=True)
class Situation:
    hole: tuple[str, str]
    board: tuple[str, ...]
    pot: int
    to_call: int
    stack: int
    opponents: int
    min_raise: int | None = None

    def __post_init__(self):
        if len(self.hole) != 2:
            raise ValueError("Elige las dos cartas del bot.")
        if len(self.board) not in (0, 3, 4, 5):
            raise ValueError("La mesa debe tener 0, 3, 4 o 5 cartas.")

        cards = self.hole + self.board
        if any(card not in CARD_VALUES for card in cards):
            raise ValueError("Hay una carta que no pertenece al mazo.")
        if len(set(cards)) != len(cards):
            raise ValueError("Cada carta puede aparecer una sola vez.")
        if self.stack < 1:
            raise ValueError("El bot necesita al menos una ficha disponible.")
        if not 0 <= self.to_call <= self.pot:
            raise ValueError("El bote debe incluir la apuesta rival que se está igualando.")
        if self.to_call > self.stack:
            raise ValueError("Si el bot tiene menos fichas, ingresa solo las que pondría al pagar.")
        if not 1 <= self.opponents <= 5:
            raise ValueError("Debe haber de 1 a 5 rivales en la mano.")
        if self.min_raise is not None and not self.to_call < self.min_raise <= self.stack:
            raise ValueError("El mínimo para subir debe superar el coste de pagar y caber en tus fichas.")


@dataclass(frozen=True)
class Decision:
    action: str
    amount: int
    equity: float
    required_equity: float | None
    explanation: str


def straight_high(ranks):
    values = set(ranks)
    if 14 in values:
        values.add(1)
    for high in sorted(values, reverse=True):
        if all(high - offset in values for offset in range(1, 5)):
            return high
    return 0


def hand_rank(cards):
    """Devuelve una tupla comparable para la mejor mano de cinco cartas."""
    by_suit = {suit: [] for suit in SUITS}
    counts = Counter()
    for card in cards:
        value, suit = CARD_VALUES[card]
        counts[value] += 1
        by_suit[suit].append(value)

    ranks = sorted(counts, reverse=True)
    flush = next((sorted(values, reverse=True) for values in by_suit.values() if len(values) >= 5), [])
    groups = sorted(((count, rank) for rank, count in counts.items()), reverse=True)
    count, highest_group = groups[0]
    others = [rank for rank in ranks if rank != highest_group]

    if flush and (high := straight_high(flush)):
        return 8, high
    if count == 4:
        return 7, highest_group, others[0]
    if count == 3 and groups[1][0] >= 2:
        return 6, highest_group, groups[1][1]
    if flush:
        return (5, *flush[:5])
    if high := straight_high(ranks):
        return 4, high
    if count == 3:
        return (3, highest_group, *others[:2])
    if count == 2 and groups[1][0] == 2:
        second_pair = groups[1][1]
        return 2, highest_group, second_pair, next(rank for rank in others if rank != second_pair)
    if count == 2:
        return (1, highest_group, *others[:3])
    return (0, *ranks[:5])


def starting_hand_score(pair):
    """Puntuación de Chen para manos iniciales, como en el bot Base del kit."""
    (high, high_suit), (low, low_suit) = sorted(
        (CARD_VALUES[card] for card in pair), reverse=True,
    )
    points = CHEN_HIGH_CARD_POINTS.get(high, high / 2)
    if high == low:
        return max(5, points * 2)
    gap = high - low - 1
    suited_bonus = 2 if high_suit == low_suit else 0
    connected_bonus = 1 if gap <= 1 and high < 12 else 0
    return points + suited_bonus + connected_bonus - CHEN_GAP_PENALTIES[min(gap, 4)]


def strong_combinations(board, remaining, fraction=4):
    """La fracción superior de manos (1/fraction), incluidos los empates en el corte."""
    score = (lambda pair: hand_rank(board + pair)) if board else starting_hand_score
    ranked = sorted((score(pair), pair) for pair in combinations(remaining, 2))
    cutoff = ranked[-(len(ranked) // fraction)][0]
    return tuple(pair for rank, pair in ranked if rank >= cutoff)

def estimate_equity(
        situation, samples=2400, *, strong_rival=False, strong_weight=DEFAULT_STRONG_WEIGHT,
        fraction=4,
):
    seen = set(situation.hole + situation.board)
    remaining = [card for card in DECK if card not in seen]
    missing = 5 - len(situation.board)
    strong_pairs = strong_combinations(situation.board, remaining, fraction) if strong_rival else ()

    if missing == 0 and situation.opponents == 1:
        hero = hand_rank(situation.board + situation.hole)
        strong_set = set(strong_pairs)
        strong_share = 0.0
        share = 0.0
        count = 0
        for pair in combinations(remaining, 2):
            rival = hand_rank(situation.board + pair)
            won = 1.0 if hero > rival else 0.5 if hero == rival else 0.0
            share += won
            if pair in strong_set:
                strong_share += won
            count += 1
        if strong_set:
            return (1 - strong_weight) * share / count + strong_weight * strong_share / len(strong_set)
        return share / count

    random = Random()
    share = 0.0
    for _ in range(samples):
        if strong_pairs and random.random() < strong_weight:
            pair = random.choice(strong_pairs)
            available = [card for card in remaining if card not in pair]
            draw = random.sample(available, missing + 2 * (situation.opponents - 1))
            draw.extend(pair)
        else:
            draw = random.sample(remaining, missing + 2 * situation.opponents)
        board = situation.board + tuple(draw[:missing])
        hero = hand_rank(board + situation.hole)
        tied = 1
        for index in range(missing, len(draw), 2):
            rival = hand_rank(board + (draw[index], draw[index + 1]))
            if rival > hero:
                break
            if rival == hero:
                tied += 1
        else:
            share += 1 / tied
    return share / samples




def decide(situation, *, strong_weight=DEFAULT_STRONG_WEIGHT, facing_raise=False):
    started = time.perf_counter()
    decision, weight = _decide(situation, strong_weight, facing_raise)
    if DEBUG:
        ms = (time.perf_counter() - started) * 1000
        req = f"{decision.required_equity:.0%}" if decision.required_equity is not None else "-"
        print(
            f"[{STAGES[len(situation.board)]:<7}] {' '.join(situation.hole)} | "
            f"mesa {' '.join(situation.board) or '-':<14} | "
            f"eq {decision.equity:.0%} req {req} w{weight:.2f} vs {situation.opponents} "
            f"pot {situation.pot} call {situation.to_call} stack {situation.stack} | "
            f"{decision.action} {decision.amount} | t={ms:.0f}ms",
            file=sys.stderr, flush=True,
        )
    return decision
def _preflop(s, facing_raise):
    call = s.to_call
    score = starting_hand_score(s.hole)
    eq = estimate_equity(replace(s, opponents=min(s.opponents, 2)), samples=600)
    req = call / (s.pot + call) if call else None
    can_raise = s.min_raise is not None
    amount = min(s.stack, max(s.min_raise or 0, 3 * call, s.pot if not call else 0))
    shove = amount >= s.stack * 0.5

    def dec(action, amt, why):
        return Decision(action, amt, eq, req, why)

    if facing_raise:
        if score >= 14 and can_raise:
            return dec("Subir", amount, "Mano premium: resube por valor.")
        if score >= 10 and call <= s.stack * 0.15:
            return dec("Pagar", call, "Mano fuerte: paga la subida.")
        return dec("Retirarse", 0, "Mano insuficiente contra una subida.")
    if score >= 9 and can_raise and not (shove and score < 14):
        return dec("Subir" if call else "Apostar / subir", amount,
                   "Mano jugable: sube para tomar la iniciativa.")
    if not call:
        return dec("Pasar", 0, "Puedes seguir sin poner fichas.")
    limit = 0.25 if score >= 9 else 0.06
    if score >= 6 and call <= s.stack * limit:
        return dec("Pagar", call, "Mano especulativa barata.")
    return dec("Retirarse", 0, "Mano débil.")
def _decide(situation, strong_weight, facing_raise):
    if not situation.board:
        return _preflop(situation, facing_raise), 0.0

    call = situation.to_call
    large_bet = call > 0 and 2 * call >= situation.pot
    postflop_raise = bool(call and facing_raise)
    strong_rival = large_bet or postflop_raise

    weight = strong_weight if strong_rival else 0.0
    fraction = 4
    if call and not strong_rival:
        frac = call / max(1, situation.pot - call)
        weight = min(0.85, 0.25 + 0.55 * frac)
        strong_rival = True
    if postflop_raise or (large_bet and len(situation.board) >= 4):
        weight = max(weight, 0.75)
    if postflop_raise and len(situation.board) >= 4:
        weight, fraction = max(weight, 0.85), 10

    if not call and len(situation.board) >= 4:
        weight, strong_rival = 0.35, True

    equity = estimate_equity(
        situation, strong_rival=strong_rival, strong_weight=weight, fraction=fraction,
    )
    required = call / (situation.pot + call) if call else None

    reraise_caution = ""
    if postflop_raise and hand_rank(situation.board + situation.hole)[0] < 4:
        reraise_caution = "sin escalera o mejor no resube contra una subida"

    raise_min = situation.min_raise
    target = call + max(1, (situation.pot + call) // 2)

    value_threshold = 0.66 if situation.opponents == 1 else 0.55
    if len(situation.board) == 5 and hand_rank(situation.board + situation.hole)[0] < 2:
        value_threshold = max(value_threshold, 0.80)
    if call:
        value_threshold += 0.06

    avoid_all_in = False
    if (
            not reraise_caution
            and raise_min is not None
            and (raise_min <= target or situation.pot == 0)
            and equity >= value_threshold
    ):
        amount = min(situation.stack, max(raise_min, target))
        committed = amount >= situation.stack * 0.5 and situation.pot >= situation.stack * 0.5
        min_allin_equity = 0.70 if committed else 0.88
        avoid_all_in = bool(amount == situation.stack and equity < min_allin_equity)
        if not avoid_all_in:
            return Decision(
                "Subir" if call else "Apostar / subir", amount, equity, required,
                "La mano tiene suficiente fuerza en la simulación para intentar ganar un bote mayor.",
            ), weight

    if (
            not call
            and raise_min is not None
            and situation.pot > 0
            and equity >= (0.55 if situation.opponents == 1 else 0.45)
    ):
        probe_amount = min(situation.stack, max(raise_min, situation.pot // 3))
        if probe_amount < situation.stack * 0.4:
            return Decision(
                "Apostar / subir", probe_amount, equity, required,
                "Ningún rival mostró fuerza; apuesta de presión para ganar el bote.",
            ), weight

    if not call:
        return Decision(
            "Pasar", 0, equity, required,
            "La apuesta usaría todas tus fichas y la mano no tiene fuerza suficiente para hacerlo."
            if avoid_all_in else "Puedes seguir en la mano sin poner más fichas.",
        ), weight

    big = 0.10 if call >= situation.stack * 0.25 else 0.0
    if equity >= required + big:
        explanation = "Tu parte estimada del bote cubre el coste de igualar la apuesta."
        if reraise_caution:
            explanation = f"La estimación alcanza para igualar, pero {reraise_caution}."
        elif avoid_all_in:
            explanation = "Subir comprometería todas tus fichas sin suficiente margen; conviene solo igualar."
        return Decision("Pagar", call, equity, required, explanation), weight

    return Decision(
        "Retirarse", 0, equity, required,
        "El bot da más peso a manos rivales fuertes. Con esa estimación, igualar cuesta demasiado.",
    ), weight