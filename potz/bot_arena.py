"""Conecta el motor del probador al protocolo de PokerFight."""

import argparse
from ipaddress import ip_address
import json
import socket
import sys
from uuid import uuid4

from .memoria import ObservedHand, open_memory
from .motor import DEFAULT_STRONG_WEIGHT, RANKS, SUITS, Situation, decide

VERSION = "1.0.0"


def cards_from_wire(cards):
    return tuple(RANKS[card["rango"] - 2] + SUITS[card["palo"]] for card in cards)


def facing_postflop_pressure(state, player_id):
    stage = state.get("etapa")
    all_in_totals = {player["id"]: player["apuesta_ronda"] for player in state["jugadores"]}
    earlier_raisers = set()
    highest = 0
    bettor = None
    raised = False
    for entry in state.get("historial_acciones") or []:
        street = entry["etapa"]
        action = entry["accion"]
        actor = entry["id_jugador"]
        if street != stage:
            if street in ("flop", "turn") and action["tipo"] == "raise":
                earlier_raisers.add(actor)
            continue
        if action["tipo"] == "allin":
            total = all_in_totals.get(actor, 0)
        elif action["tipo"] in ("bet", "raise"):
            total = action["monto"]
        else:
            continue
        if total > highest:
            bettor = actor
            raised = highest > 0 or action["tipo"] == "raise"
            highest = total
    return (
        bettor is not None and bettor != player_id and highest == state["apuesta_actual"]
        and (raised or bettor in earlier_raisers)
    )


def choose_action(state, valid_actions, player_id, hole, *, strong_weight=DEFAULT_STRONG_WEIGHT):
    safe = {"tipo": "check" if "check" in valid_actions else "fold"}
    players = state["jugadores"]
    player = next((item for item in players if item["id"] == player_id), None)
    rivals = [item for item in players if item["activo"] and item["id"] != player_id]
    if player is None or len(hole) != 2 or not 1 <= len(rivals) <= 5:
        return safe

    stack = player["saldo"]
    committed = player["apuesta_ronda"]
    pending = max(0, state["apuesta_actual"] - committed)
    to_call = min(stack, pending)
    pot = state["pozo"]
    if len(rivals) == 1 and pending > stack:
        # El rival recupera la parte de esta apuesta que Potz no puede igualar.
        pot -= max(0, rivals[0]["apuesta_ronda"] - committed - to_call)
    aggressive = "raise" if pending else "bet"
    min_raise = pending + state["subida_minima"]
    if "allin" in valid_actions and to_call < stack:
        min_raise = min(min_raise, stack)
    elif aggressive not in valid_actions or min_raise > stack:
        min_raise = None

    situation = Situation(
        hole=hole,
        board=cards_from_wire(state["comunitarias"] or []),
        pot=pot,
        to_call=to_call,
        stack=stack,
        opponents=len(rivals),
        min_raise=min_raise,
    )
    facing_raise = bool(situation.board and to_call and facing_postflop_pressure(state, player_id))
    decision = decide(situation, strong_weight=strong_weight, facing_raise=facing_raise)

    if decision.amount > to_call:
        if decision.amount == stack and "allin" in valid_actions:
            return {"tipo": "allin"}
        if aggressive in valid_actions:
            return {"tipo": aggressive, "monto": committed + decision.amount}
    if decision.action == "Pagar" and "call" in valid_actions:
        return {"tipo": "call"}
    return safe


def send(connection, message):
    connection.sendall((json.dumps(message) + "\n").encode("utf-8"))


def memory_scope(host, address, player_id, name):
    try:
        local = ip_address(host).is_loopback
    except ValueError:
        local = host.lower() == "localhost"
    if local:
        return f"local:{name}" if name else "local"
    if name:
        return f"remoto:{name}:{player_id}"
    # Sin etiqueta no sabemos si otra conexión pertenece al mismo evento.
    return f"remoto:sesion:{address}:{player_id}:{uuid4().hex}"


def play(address, token, scope_name=None):
    host, port = address.rsplit(":", 1)
    host = host.removeprefix("[").removesuffix("]")
    with socket.create_connection((host, int(port)), timeout=5) as connection:
        with connection.makefile("r", encoding="utf-8", newline="\n") as incoming:
            send(connection, {"tipo": "saludo", "version": VERSION, "token": token})
            line = incoming.readline()
            if not line:
                raise RuntimeError("La mesa cerró la conexión antes de aceptar al bot.")
            welcome = json.loads(line)
            if welcome["tipo"] != "bienvenida":
                raise RuntimeError(welcome.get("mensaje", "La mesa no aceptó al bot."))
            player_id = welcome["id_jugador"]
            print(f"Potz conectado a la mesa ({player_id}).", file=sys.stderr)
            connection.settimeout(None)
            scope = memory_scope(host, address, player_id, scope_name)
            with open_memory(scope) as memory:
                play_hands(connection, incoming, player_id, memory)


def play_hands(connection, incoming, player_id, memory):
    hole = ()
    hand = None
    for line in incoming:
        message = json.loads(line)
        kind = message["tipo"]
        state = message.get("estado")
        if kind == "mano_inicio":
            hole = cards_from_wire(message["cartas"])
            hand = ObservedHand(state, player_id, hole) if memory and state else None
            continue
        if hand and state and state["id_mano"] == hand.id:
            hand.observe(state)
        if kind == "solicitar_accion":
            weight = DEFAULT_STRONG_WEIGHT
            if hand and hand.id == state["id_mano"] and state.get("comunitarias"):
                weight = memory.strong_weight(hand.bettor(state), state["etapa"])
            action = choose_action(state, message["acciones_validas"], player_id, hole, strong_weight=weight)
            send(connection, {
                "tipo": "accion", "version": VERSION,
                "id_mano": state["id_mano"], "accion": action,
            })
        elif kind == "mano_fin":
            result = message.get("resultado") or {}
            if hand and result.get("id_mano") == hand.id:
                board = cards_from_wire(result.get("comunitarias") or [])
                shown = {
                    rival: cards_from_wire(cards)
                    for rival, cards in (result.get("mostradas") or {}).items()
                }
                memory.remember(hand, board, shown)
            hand = None
            hole = ()
        elif kind == "error":
            raise RuntimeError(message.get("mensaje", "La mesa informó un error."))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-addr", required=True, help="Dirección de la mesa (host:puerto)")
    parser.add_argument("-token", required=True, help="Token de la mesa")
    parser.add_argument("-ambito-memoria", metavar="NOMBRE",
                        help="Etiqueta para recuperar perfiles de un evento, por ejemplo practica o campeonato-2026")
    args = parser.parse_args()
    try:
        play(args.addr, args.token, args.ambito_memoria)
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f"Potz: {error}\n")


if __name__ == "__main__":
    main()
