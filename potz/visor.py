"""Muestra la mesa local en vivo y reproduce las manos guardadas."""

import json
from pathlib import Path
from queue import Empty, SimpleQueue
import subprocess
import sys
from threading import Thread
import tkinter as tk
from tkinter import ttk

from .bot_arena import cards_from_wire
from .probador import ACCENT, BG, FIELD, INK, MUTED, PANEL, button, card_label, label

PROJECT = Path(__file__).resolve().parents[1]
ARENA = PROJECT / "arena"
KIT = ARENA / "pokerfight-arena-participantes"
RESULTS = KIT / "resultados" / "prueba-local"
HISTORY = RESULTS / "manos" / "final.jsonl"
STREETS = {"preflop": ("Antes del flop", 0), "flop": ("Flop", 3),
           "turn": ("Turn", 4), "river": ("River", 5)}
ACTIONS = {"check": "Pasa", "fold": "Se retira", "call": "Iguala",
           "bet": "Apuesta", "raise": "Sube a", "allin": "Va con todo"}
PLAYBACK_MS = 1100


def chips(value):
    return f"{value:,}".replace(",", " ")


def action_text(entry, names):
    action = entry["accion"]
    move = ACTIONS[action["tipo"]]
    if action["tipo"] in ("bet", "raise"):
        move += f" {chips(action['monto'])}"
    return f"{STREETS[entry['etapa']][0]}  ·  {names[entry['id_jugador']]}  ·  {move}"


def make_cards(parent, count):
    row = tk.Frame(parent, background=parent["background"])
    row.pack(fill="x")
    slots = []
    for _ in range(count):
        slot = tk.Label(row, width=3, pady=5, font=("Segoe UI Symbol", 15, "bold"))
        slot.pack(side="left", padx=(0, 5))
        slots.append(slot)
    return slots


def show_cards(slots, cards):
    for index, slot in enumerate(slots):
        if index < len(cards):
            card = cards[index]
            color = "#b52236" if card[1] in "hd" else BG
            slot.configure(text=card_label(card), background=INK, foreground=color)
        else:
            slot.configure(text="·", background=FIELD, foreground=MUTED)


class Replay:
    def __init__(self, root, parent):
        self.root = root
        self.hands = []
        self.hand_index = 0
        self.step = 0
        self.timer = None
        page = tk.Frame(parent, background=BG, padx=20, pady=14)
        page.pack(fill="both", expand=True)
        label(page, "Repetición de la partida local", size=21, bold=True).pack(fill="x")
        self.summary = label(page, "", color=MUTED)
        self.summary.pack(fill="x", pady=(2, 8))

        hands = tk.Frame(page, background=BG)
        hands.pack(fill="x", pady=(0, 10))
        self.previous_hand = button(hands, "‹ Mano", lambda: self.change_hand(-1))
        self.previous_hand.pack(side="left")
        self.next_hand = button(hands, "Mano ›", lambda: self.change_hand(1))
        self.next_hand.pack(side="left", padx=6)
        button(hands, "Recargar partida", self.load).pack(side="right")

        body = tk.Frame(page, background=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=1, minsize=470)
        body.columnconfigure(1, weight=1, minsize=360)
        body.rowconfigure(0, weight=1)
        table = tk.Frame(body, background=PANEL, padx=14, pady=10)
        table.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        log = tk.Frame(body, background=PANEL, padx=14, pady=10)
        log.grid(row=0, column=1, sticky="nsew")

        self.street = label(table, "", size=13, bold=True)
        self.street.pack(fill="x", pady=(0, 4))
        self.board = make_cards(table, 5)
        self.players = tk.Frame(table, background=PANEL)
        self.players.pack(fill="both", expand=True, pady=(9, 0))

        label(log, "Jugadas", size=13, bold=True).pack(fill="x")
        self.status = label(log, "", color=ACCENT, bold=True, wrap=340)
        self.status.pack(fill="x", pady=(3, 6))
        actions = tk.Frame(log, background=PANEL)
        actions.pack(fill="both", expand=True)
        scroll = tk.Scrollbar(actions)
        scroll.pack(side="right", fill="y")
        self.log = tk.Listbox(
            actions, background=FIELD, foreground=INK, borderwidth=0, highlightthickness=0,
            activestyle="none", font=("Segoe UI", 10), yscrollcommand=scroll.set,
        )
        self.log.pack(side="left", fill="both", expand=True)
        scroll.configure(command=self.log.yview)

        controls = tk.Frame(log, background=PANEL)
        controls.pack(fill="x", pady=(8, 0))
        self.previous_step = button(controls, "‹ Jugada", lambda: self.change_step(-1))
        self.previous_step.pack(side="left")
        self.play_button = button(controls, "Reproducir", self.toggle_play, primary=True)
        self.play_button.pack(side="left", padx=5)
        self.next_step = button(controls, "Jugada ›", lambda: self.change_step(1))
        self.next_step.pack(side="left")
        self.load()

    def load(self):
        self.stop()
        self.hands = []
        self.hand_index = self.step = 0
        try:
            with HISTORY.open(encoding="utf-8") as history:
                self.hands = [json.loads(line) for line in history if line.strip()]
            message = "Todavía no hay manos guardadas. Juega una partida y pulsa «Recargar partida»."
        except FileNotFoundError:
            message = "Abre «Jugar partida local.cmd». Cuando termine, pulsa «Recargar partida»."
        except (OSError, ValueError):
            message = "Espera a que la arena termine de guardar la partida y pulsa «Recargar partida»."
        self.render(message)

    def stop(self):
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None

    def change_hand(self, offset):
        self.stop()
        self.hand_index += offset
        self.step = 0
        self.render()

    def change_step(self, offset):
        self.stop()
        self.step += offset
        self.render()

    def toggle_play(self):
        if self.timer is not None:
            self.stop()
            self.render()
            return
        if self.step == self.end_step():
            self.step = 0
        self.timer = self.root.after(PLAYBACK_MS, self.advance)
        self.render()

    def advance(self):
        self.step += 1
        self.timer = (
            self.root.after(PLAYBACK_MS, self.advance) if self.step < self.end_step() else None
        )
        self.render()

    def end_step(self):
        return len(self.hands[self.hand_index]["acciones"] or []) + 1

    def render(self, empty_message=""):
        self.log.delete(0, "end")
        for child in self.players.winfo_children():
            child.destroy()
        ready = bool(self.hands)
        for control, enabled in (
            (self.previous_hand, ready and self.hand_index > 0),
            (self.next_hand, self.hand_index + 1 < len(self.hands)),
            (self.previous_step, ready and self.step > 0),
            (self.next_step, ready and self.step < self.end_step()),
            (self.play_button, ready),
        ):
            control.configure(state="normal" if enabled else "disabled")
        self.play_button.configure(text="Pausar" if self.timer is not None else "Reproducir")
        if not ready:
            self.summary.configure(text=empty_message)
            self.status.configure(text="")
            self.street.configure(text="Cartas en la mesa")
            show_cards(self.board, ())
            return

        hand = self.hands[self.hand_index]
        players = [player for player in hand["jugadores"] if player["en_mano"]]
        names = {player["id"]: player["nombre"] for player in hand["jugadores"]}
        actions = (hand["acciones"] or [])[:self.step]
        last_action = actions[-1] if actions else None
        finished = self.step == self.end_step()
        street, visible = STREETS[last_action["etapa"] if last_action else "preflop"]
        board = cards_from_wire(hand["comunitarias"] or [])
        show_cards(self.board, board if finished else board[:visible])
        self.summary.configure(text=f"Mano {self.hand_index + 1} de {len(self.hands)}")
        self.street.configure(text="Mano terminada" if finished else street)

        if finished:
            self.status.configure(text=f"Bote final  {chips(hand['pozo'])} fichas")
        elif actions:
            self.status.configure(text=f"Jugada {self.step} de {self.end_step() - 1}")
        else:
            self.status.configure(text="Cartas repartidas")

        folded = {entry["id_jugador"] for entry in actions if entry["accion"]["tipo"] == "fold"}
        for player in players:
            player_id = player["id"]
            row = tk.Frame(self.players, background=PANEL)
            row.pack(fill="x", pady=2)
            private = hand.get("privadas", {}).get(player_id, ())
            card_group = tk.Frame(row, background=PANEL)
            card_group.pack(side="left", padx=(0, 7))
            show_cards(make_cards(card_group, 2), cards_from_wire(private))
            details = "Se retiró" if player_id in folded else "En la mano"
            if finished:
                details = f"{chips(player['saldo'])} fichas al cierre"
            color = ACCENT if player_id == "potz" else INK
            label(row, f"{player['nombre']}   ·   {details}", size=10, color=color).pack(
                side="left", fill="x", expand=True,
            )

        for entry in actions:
            self.log.insert("end", action_text(entry, names))
        if finished:
            for payout in hand["repartos"] or []:
                name = names[payout["id_jugador"]]
                self.log.insert("end", f"Reparto  ·  {name} recibe {chips(payout['monto'])} fichas")
        self.log.see("end")


class LiveTable:
    def __init__(self, root, parent, on_finish):
        self.root = root
        self.on_finish = on_finish
        self.process = None
        self.events = SimpleQueue()
        self.snapshots = []
        self.position = -1
        self.cards = {}
        self.paused = False
        self.waiting = False
        self.timer = None
        self.hand_id = None
        self.hand_count = 0
        self.error = ""

        page = tk.Frame(parent, background=BG, padx=20, pady=14)
        page.pack(fill="both", expand=True)
        header = tk.Frame(page, background=BG)
        header.pack(fill="x")
        label(header, "Mesa en vivo", size=21, bold=True).pack(side="left")
        self.start_button = button(header, "Jugar partida", self.start, primary=True)
        self.start_button.pack(side="right")
        self.status = label(page, "Pulsa «Jugar partida» para sentar a los cinco bots.", color=MUTED, wrap=850)
        self.status.pack(fill="x", pady=(4, 8))
        controls = tk.Frame(page, background=BG)
        controls.pack(fill="x", pady=(0, 12))
        self.pause_button = button(controls, "Detener", self.toggle_pause)
        self.pause_button.pack(side="left")
        self.back_button = button(controls, "‹ Jugada anterior", self.back)
        self.back_button.pack(side="left", padx=6)
        self.next_button = button(controls, "Siguiente jugada ›", self.forward)
        self.next_button.pack(side="left")

        table = tk.Frame(page, background=PANEL, padx=14, pady=12)
        table.pack(fill="x")
        self.street = label(table, "Cartas en la mesa", size=13, bold=True)
        self.street.pack(fill="x", pady=(0, 5))
        self.board = make_cards(table, 5)
        show_cards(self.board, ())

        metrics = tk.Frame(table, background=PANEL)
        metrics.pack(fill="x", pady=(12, 0))
        self.pot = label(metrics, "Pozo  ·  —", size=13, color=ACCENT, bold=True)
        self.pot.pack(side="left", padx=(0, 35))
        self.bet = label(metrics, "Apuesta actual  ·  —", size=13, bold=True)
        self.bet.pack(side="left")
        self.payout = label(table, "", size=10, color=ACCENT, wrap=830)
        self.payout.pack(fill="x", pady=(4, 0))

        self.players = ttk.Treeview(
            page, columns=("bot", "cards", "stack", "committed", "status"), show="headings",
            height=5, selectmode="none",
        )
        self.players.tag_configure("potz", background="#dbf4e9", foreground=BG)
        for key, title, width, align in (
            ("bot", "Jugador", 220, "w"),
            ("cards", "Cartas", 105, "center"),
            ("stack", "Fichas disponibles", 170, "e"),
            ("committed", "Puso en esta ronda", 170, "e"),
            ("status", "Estado", 155, "center"),
        ):
            self.players.heading(key, text=title, anchor=align)
            self.players.column(key, width=width, anchor=align)
        self.players.pack(fill="x", pady=(10, 8))

        label(page, "Jugadas de esta mano", bold=True).pack(fill="x")
        self.log = tk.Listbox(
            page, background=FIELD, foreground=INK, height=5,
            borderwidth=0, highlightthickness=0, font=("Segoe UI", 10),
        )
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.update_controls()

    def start(self):
        if self.process is not None:
            return
        self.snapshots.clear()
        self.position = -1
        self.cards = {}
        self.paused = False
        self.waiting = False
        self.hand_id = None
        self.hand_count = 0
        self.error = ""
        self.log.delete(0, "end")
        self.players.delete(*self.players.get_children())
        self.street.configure(text="Cartas en la mesa")
        show_cards(self.board, ())
        self.pot.configure(text="Pozo  ·  —")
        self.bet.configure(text="Apuesta actual  ·  —")
        self.payout.configure(text="")
        try:
            self.process = subprocess.Popen(
                [str(KIT / "bin" / "arena.exe"), "correr", "-config", str(ARENA / "prueba-local.json"),
                 "-visor-en-vivo"],
                cwd=PROJECT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, encoding="utf-8", errors="replace",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as error:
            self.status.configure(text=f"No se pudo abrir la arena. {error}")
            self.update_controls()
            return
        self.start_button.configure(state="disabled")
        self.status.configure(text="Conectando a los bots…")
        self.update_controls()
        Thread(target=self.read_events, args=(self.process,), daemon=True).start()
        self.root.after(60, self.poll_events)

    def read_events(self, process):
        with process.stdout as output:
            for line in output:
                if line.startswith('{"tipo":"mesa_en_vivo",'):
                    self.events.put(("mesa", json.loads(line)))
                elif " — ERROR:" in line or line.startswith("arena: "):
                    self.events.put(("error", line.strip()))
        self.events.put(("fin", process.wait()))

    def poll_events(self):
        try:
            while True:
                kind, value = self.events.get_nowait()
                if kind == "mesa":
                    self.receive_snapshot(value)
                elif kind == "error":
                    self.error = value
                elif kind == "fin":
                    self.finish(value)
                    return
        except Empty:
            self.root.after(60, self.poll_events)

    def receive_snapshot(self, event):
        state = event["estado"]
        if state["id_mano"] != self.hand_id:
            self.hand_id = state["id_mano"]
            self.hand_count += 1
            self.cards = event.get("privadas", {})
        at_latest = self.position == len(self.snapshots) - 1
        self.snapshots.append((state, event.get("resultado"), self.cards, self.hand_count))
        if at_latest:
            self.position += 1
        self.waiting = False
        self.show_position()
        self.schedule_next()

    def update_controls(self):
        running = self.process is not None
        self.pause_button.configure(
            text="Continuar" if self.paused else "Detener",
            state="normal" if running else "disabled",
        )
        self.back_button.configure(state="normal" if self.position > 0 else "disabled")
        can_advance = self.position < len(self.snapshots) - 1 or (
            running and self.paused and self.position >= 0 and not self.waiting
        )
        self.next_button.configure(state="normal" if can_advance else "disabled")

    def cancel_timer(self):
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None

    def schedule_next(self):
        if self.process is not None and not self.paused and not self.waiting and self.snapshots:
            delay = 1100 if self.snapshots[-1][1] else 450
            self.timer = self.root.after(delay, self.request_next)

    def request_next(self):
        self.timer = None
        if self.process is None or self.waiting:
            return
        self.waiting = True
        try:
            self.process.stdin.write("avanzar\n")
            self.process.stdin.flush()
        except (BrokenPipeError, OSError):
            # La lectura del proceso entregará su resultado o error.
            pass
        self.update_controls()

    def toggle_pause(self):
        self.paused = not self.paused
        self.cancel_timer()
        if not self.paused:
            self.position = len(self.snapshots) - 1
            self.schedule_next()
        self.show_position()

    def back(self):
        self.paused = self.process is not None
        self.cancel_timer()
        self.position -= 1
        self.show_position()

    def forward(self):
        if self.position < len(self.snapshots) - 1:
            self.position += 1
            self.show_position()
        else:
            self.request_next()

    def show_position(self):
        self.update_controls()
        if self.position < 0:
            return
        state, result, cards, hand_number = self.snapshots[self.position]
        if self.process is None:
            mode = "Revisión"
        else:
            mode = "En pausa" if self.paused else "En vivo"
        actions = state["historial_acciones"] or []
        self.status.configure(text=f"{mode}   ·   Mano {hand_number}   ·   {len(actions)} jugadas")
        self.render(state, result, cards, actions)

    def render(self, state, result, cards, actions):
        stage = state["etapa"]
        self.log.delete(0, "end")
        self.log.insert("end", "Se reparten las cartas y se ponen las ciegas.")
        players = state["jugadores"]
        names = {player["id"]: player["nombre"] for player in players}
        show_cards(self.board, cards_from_wire(state["comunitarias"] or []))
        self.street.configure(text="Mano terminada" if result else STREETS.get(stage, (stage, 0))[0])
        pot = 0 if result else state["pozo"]
        bet = 0 if result else state["apuesta_actual"]
        self.pot.configure(text=f"Pozo  ·  {chips(pot)} fichas")
        self.bet.configure(text=f"Apuesta actual  ·  {chips(bet)} fichas")
        payouts = result["repartos"] if result else []
        self.payout.configure(text="   ·   ".join(
            f"{names[item['id_jugador']]} recibe {chips(item['monto'])} fichas" for item in payouts
        ))

        recipients = {item["id_jugador"] for item in payouts}
        for player in players:
            player_id = player["id"]
            if not player["en_torneo"]:
                status = "Sin fichas"
            elif result:
                status = "Recibió fichas" if player_id in recipients else "Mano terminada"
            elif not player["activo"]:
                status = "Se retiró"
            else:
                status = "Con todo" if player["allin"] else "En la mano"
            private = "  ".join(card_label(card) for card in cards_from_wire(cards.get(player_id, ())))
            values = (player["nombre"], private or "—", chips(player["saldo"]),
                      chips(0 if result else player["apuesta_ronda"]), status)
            if self.players.exists(player_id):
                self.players.item(player_id, values=values)
            else:
                self.players.insert(
                    "", "end", iid=player_id, values=values, tags=("potz",) if player_id == "potz" else (),
                )

        for entry in actions:
            self.log.insert("end", action_text(entry, names))
        if result:
            self.log.insert("end", f"Se reparten {chips(state['pozo'])} fichas del pozo.")
        self.log.see("end")

    def finish(self, code):
        self.cancel_timer()
        self.close_input()
        self.process = None
        self.update_controls()
        self.start_button.configure(state="normal")
        if code or self.error or not self.hand_count:
            self.status.configure(text=f"La partida no pudo completarse. {self.error}".strip())
        else:
            self.status.configure(text=f"Partida terminada   ·   {self.hand_count} manos")
            self.on_finish()

    def close_input(self):
        if self.process is not None:
            # La arena cancela la partida cuando se cierra esta entrada.
            try:
                self.process.stdin.close()
            except OSError:
                pass

    def close(self):
        self.cancel_timer()
        self.close_input()
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    root.title("PokerFight · Partida local")
    root.configure(background=BG)
    root.minsize(960, 680)
    tabs = ttk.Notebook(root)
    tabs.pack(fill="both", expand=True)
    live_tab = tk.Frame(tabs, background=BG)
    replay_tab = tk.Frame(tabs, background=BG)
    tabs.add(live_tab, text="En vivo")
    tabs.add(replay_tab, text="Repetición")
    replay = Replay(root, replay_tab)
    live = LiveTable(root, live_tab, replay.load)
    root.protocol("WM_DELETE_WINDOW", live.close)
    if "--en-vivo" in sys.argv:
        root.after(0, live.start)
    else:
        tabs.select(replay_tab)
    root.mainloop()
