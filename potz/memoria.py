"""Historial de las acciones que Potz observa a través del protocolo."""

from contextlib import contextmanager
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4

from .motor import DEFAULT_STRONG_WEIGHT, DECK, strong_combinations

DATABASE = Path(__file__).resolve().parents[1] / "datos" / "potz.sqlite"
BOARD_SIZE = {"flop": 3, "turn": 4, "river": 5}
AGGRESSIVE = {"bet", "raise", "allin"}
REMOTE_SAMPLE_LIMIT = 24
REMOTE_HALF_LIFE = 8


class ObservedHand:
    def __init__(self, state, player_id, hole):
        self.id = state["id_mano"]
        self.player_id = player_id
        self.hole = hole
        self.actions = []
        self.large_bets = {}
        self.previous = None
        self.observe(state)

    def observe(self, state):
        actions = state.get("historial_acciones") or []
        if len(actions) <= len(self.actions):
            self.previous = state
            return
        last = actions[-1]
        self.record_large_bet(state, last, actions[len(self.actions):-1], len(actions) - 1)
        self.actions = actions
        self.previous = state

    def record_large_bet(self, state, action, skipped, index):
        stage = action["etapa"]
        rival = action["id_jugador"]
        if (
                self.previous is None
                or stage not in BOARD_SIZE
                or self.previous["etapa"] != stage
                or state["etapa"] != stage
                or rival == self.player_id
                or action["accion"]["tipo"] not in AGGRESSIVE
                or any(entry["id_jugador"] == rival for entry in skipped)
        ):
            return

        players = state["jugadores"]
        current = next(player["apuesta_ronda"] for player in players if player["id"] == rival)
        previous = next(player["apuesta_ronda"] for player in self.previous["jugadores"] if player["id"] == rival)
        highest_other = max((p["apuesta_ronda"] for p in players if p["id"] != rival), default=0)
        added = current - previous
        # Un all-in que solo iguala no cuenta como apuesta. La comparación
        # incluye las fichas de Potz aunque la mesa omitiera avisarle su propia jugada.
        if current > max(highest_other, self.previous["apuesta_actual"]) and 2 * added >= state["pozo"]:
            self.large_bets[index] = current

    def bettor(self, state):
        for index, entry in reversed(list(enumerate(self.actions))):
            if entry["etapa"] != state["etapa"]:
                break
            if self.large_bets.get(index) == state["apuesta_actual"]:
                rival = entry["id_jugador"]
                if any(player["id"] == rival and player["activo"] for player in state["jugadores"]):
                    return rival
        return None

    def rows(self, board, shown):
        last_large = {
            (entry["id_jugador"], entry["etapa"]): index
            for index, entry in enumerate(self.actions) if index in self.large_bets
        }
        for index, entry in enumerate(self.actions):
            rival = entry["id_jugador"]
            if rival == self.player_id:
                continue
            stage = entry["etapa"]
            action = entry["accion"]
            cards = shown.get(rival, ())
            is_large = index in self.large_bets
            strong = None
            if cards and last_large.get((rival, stage)) == index:
                visible = board[:BOARD_SIZE[stage]]
                if len(visible) == BOARD_SIZE[stage]:
                    remaining = [card for card in DECK if card not in visible and card not in self.hole]
                    candidates = strong_combinations(visible, remaining)
                    if len(candidates) < len(remaining) * (len(remaining) - 1) // 2:
                        shown_pair = frozenset(cards)
                        strong = any(frozenset(pair) == shown_pair for pair in candidates)
            yield (index, rival, stage, action["tipo"], action.get("monto"),
                   is_large, " ".join(cards) or None, strong)


class Memory:
    def __init__(self, connection, scope):
        self.connection = connection
        self.scope = scope
        self.session = uuid4().hex
        self.hand_number = 0
        self.reported_error = False
        connection.executescript("""
                                 CREATE TABLE IF NOT EXISTS acciones (
                                                                         ambito TEXT NOT NULL,
                                                                         sesion TEXT NOT NULL,
                                                                         numero_mano INTEGER NOT NULL,
                                                                         mano TEXT NOT NULL,
                                                                         orden INTEGER NOT NULL,
                                                                         rival TEXT NOT NULL,
                                                                         etapa TEXT NOT NULL,
                                                                         accion TEXT NOT NULL,
                                                                         monto INTEGER,
                                                                         apuesta_grande INTEGER NOT NULL,
                                                                         cartas_mostradas TEXT,
                                                                         fuerte INTEGER,
                                                                         fecha TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                                                                         PRIMARY KEY (sesion, numero_mano, orden)
                                     );
                                 CREATE INDEX IF NOT EXISTS evidencia_por_rival
                                     ON acciones (ambito, rival, etapa) WHERE fuerte IS NOT NULL;
                                 CREATE INDEX IF NOT EXISTS evidencia_reciente_por_rival
                                     ON acciones (ambito, rival, etapa, fecha) WHERE fuerte IS NOT NULL;
                                 """)

    def report_error(self, error):
        if not self.reported_error:
            print(f"Potz: memoria no disponible ({error}). El bot sigue jugando.", file=sys.stderr)
            self.reported_error = True

    def remember(self, hand, board, shown):
        self.hand_number += 1
        prefix = (self.scope, self.session, self.hand_number, hand.id)
        rows = [prefix + row for row in hand.rows(board, shown)]
        try:
            with self.connection:
                self.connection.executemany("""
                                            INSERT INTO acciones
                                            (ambito, sesion, numero_mano, mano, orden, rival, etapa, accion, monto,
                                             apuesta_grande, cartas_mostradas, fuerte)
                                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                                            """, rows)
        except sqlite3.Error as error:
            self.report_error(error)

    def strong_weight(self, rival, stage):
        if rival is None:
            return DEFAULT_STRONG_WEIGHT
        try:
            count, weak = self.evidence(rival, stage)
        except sqlite3.Error as error:
            self.report_error(error)
            return DEFAULT_STRONG_WEIGHT
        if not count:
            return DEFAULT_STRONG_WEIGHT

        # Unas pocas cartas mostradas pesan menos que la estimación inicial.
        prior = 12
        weak_in_random = 0.75
        weak_rate = (weak + prior * weak_in_random * (1 - DEFAULT_STRONG_WEIGHT)) / (count + prior)
        return max(0.10, min(0.95, 1 - weak_rate / weak_in_random))

    def evidence(self, rival, stage):
        key = (self.scope, rival, stage)
        if not self.scope.startswith("remoto:"):
            return self.connection.execute("""
                                           SELECT COUNT(*), COUNT(*) - COALESCE(SUM(fuerte), 0)
                                           FROM acciones
                                           WHERE ambito = ? AND rival = ? AND etapa = ? AND fuerte IS NOT NULL
                                           """, key).fetchone()

        rows = self.connection.execute("""
                                       SELECT fuerte
                                       FROM acciones
                                       WHERE ambito = ? AND rival = ? AND etapa = ? AND fuerte IS NOT NULL
                                         AND fecha >= datetime('now', '-7 days')
                                       ORDER BY fecha DESC, rowid DESC
                                           LIMIT ?
                                       """, (*key, REMOTE_SAMPLE_LIMIT))

        total = weak = 0.0
        for age, (strong,) in enumerate(rows):
            weight = 2 ** (-age / REMOTE_HALF_LIFE)
            total += weight
            weak += weight * (1 - strong)
        return total, weak


@contextmanager
def open_memory(scope, path=DATABASE):
    connection = None
    try:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path, timeout=1.5)
            connection.execute("PRAGMA journal_mode=WAL;")
            memory = Memory(connection, scope)
        except (OSError, sqlite3.Error) as error:
            print(f"Potz: memoria no disponible ({error}). El bot sigue jugando.", file=sys.stderr)
            memory = None
        yield memory
    finally:
        if connection is not None:
            connection.close()