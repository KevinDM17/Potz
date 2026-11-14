"""Interfaz local para preparar y evaluar jugadas."""

import tkinter as tk
from tkinter import ttk

from .motor import RANKS, Situation, decide

BG = "#101820"
PANEL = "#192630"
FIELD = "#243743"
INK = "#f2f6f8"
MUTED = "#b3c5ce"
ACCENT = "#9aead0"
ERROR = "#ffb4a7"
SUITS = {"s": "♠", "h": "♥", "d": "♦", "c": "♣"}
STREETS = {0: "Antes del flop", 3: "Flop", 4: "Turn", 5: "River"}
PRESETS = {
    "Trío contra una apuesta": (
        ("Ah", "Ad"), ("As", "8c", "3d"), ("800", "200", "1800", "2", "400"),
    ),
    "Mano débil, apuesta grande": (
        ("7c", "2d"), ("Ks", "Qh", "Jh", "9s", "5d"), ("900", "600", "2200", "2", ""),
    ),
    "Proyecto sin apuesta": (
        ("Ah", "9h"), ("Kh", "6h", "3s"), ("300", "0", "1700", "1", ""),
    ),
}


def card_label(card):
    rank, suit = card
    return f"{'10' if rank == 'T' else rank}{SUITS[suit]}"


def label(parent, value, *, size=11, color=INK, bold=False, wrap=0):
    return tk.Label(
        parent, text=value, font=("Segoe UI", size, "bold" if bold else "normal"),
        foreground=color, background=parent["background"], anchor="w", justify="left",
        wraplength=wrap,
    )


def button(parent, value, action, *, primary=False):
    return tk.Button(
        parent, text=value, command=action, cursor="hand2", relief="flat", borderwidth=0,
        foreground=BG if primary else INK, background=ACCENT if primary else FIELD,
        activeforeground=BG, activebackground=ACCENT, padx=14, pady=8,
        font=("Segoe UI", 10, "bold"),
    )


class Tester:
    def __init__(self, root):
        self.root = root
        self.cards = [None] * 7
        self.slots = []
        self.fields = {}
        root.title("PokerFight · Probador de jugadas")
        root.configure(background=BG)
        page = tk.Frame(root, background=BG, padx=24, pady=12)
        page.pack(fill="both", expand=True)
        label(page, "POKERFIGHT  /  PRUEBAS LOCALES", size=10, color=ACCENT, bold=True).pack(fill="x")
        label(page, "Probador de jugadas", size=26, bold=True).pack(fill="x")
        label(
            page, "Arma una mano y revisa qué haría el bot.", color=MUTED,
        ).pack(fill="x", pady=(2, 10))

        body = tk.Frame(page, background=BG)
        body.pack(fill="both", expand=True)
        body.columnconfigure(0, weight=3, minsize=545)
        body.columnconfigure(1, weight=2, minsize=345)
        body.rowconfigure(0, weight=1)
        setup = tk.Frame(body, background=PANEL, padx=19, pady=12)
        setup.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        result = tk.Frame(body, background=PANEL, padx=20, pady=12)
        result.grid(row=0, column=1, sticky="nsew")

        self.build_setup(setup)
        self.build_result(result)
        for field in self.fields.values():
            field.trace_add("write", self.invalidate)
        self.load_example(next(iter(PRESETS)))
        root.update_idletasks()
        min_width = root.winfo_reqwidth()
        min_height = root.winfo_reqheight() + self.error.winfo_reqheight()
        root.minsize(min_width, min_height)
        root.geometry(f"{max(1040, min_width)}x{min_height}")

    def build_setup(self, setup):
        examples = tk.Frame(setup, background=PANEL)
        examples.pack(fill="x")
        label(examples, "Escenario", size=16, bold=True).pack(side="left")
        self.example = ttk.Combobox(examples, values=tuple(PRESETS), state="readonly", width=27)
        self.example.pack(side="right")
        self.example.set("Cargar un ejemplo")
        self.example.bind("<<ComboboxSelected>>", lambda _: self.load_example(self.example.get()))
        label(setup, "Haz clic en un espacio para elegir una carta.", color=MUTED).pack(
            fill="x", pady=(3, 12),
        )

        cards = tk.Frame(setup, background=PANEL)
        cards.pack(fill="x")
        self.add_slots(cards, "Tus cartas", 2).pack(side="left", padx=(0, 18))
        self.add_slots(cards, "Cartas en la mesa", 5).pack(side="left")
        self.street = label(setup, "", size=10, color=MUTED)
        self.street.pack(fill="x", pady=(6, 10))

        settings = tk.Frame(setup, background=PANEL)
        settings.pack(fill="x")
        settings.columnconfigure(0, weight=1, uniform="settings")
        settings.columnconfigure(1, weight=1, uniform="settings")
        for row, (key, title) in enumerate((
            ("pot", "Bote actual"),
            ("call", "Cuánto cuesta pagar"),
            ("stack", "Fichas disponibles del bot"),
            ("opponents", "Rivales en la mano (1 a 5)"),
            ("raise", "Mínimo para subir (opcional)"),
        )):
            field = tk.Frame(settings, background=PANEL)
            field.grid(row=row // 2, column=row % 2, sticky="ew", padx=(0, 12), pady=(0, 6))
            label(field, title, size=10, bold=True).pack(fill="x")
            variable = tk.StringVar()
            self.fields[key] = variable
            if key == "opponents":
                entry = ttk.Combobox(field, values=("1", "2", "3", "4", "5"), textvariable=variable,
                                     state="readonly", font=("Segoe UI", 11))
            else:
                entry = ttk.Entry(field, textvariable=variable, font=("Segoe UI", 11))
            entry.pack(fill="x", pady=(2, 0), ipady=2)

        label(
            setup, "El bote incluye la apuesta rival que puedes ganar. Para subir, ingresa el total "
            "que añadirías ahora, incluido el pago. Déjalo vacío si no se puede subir.",
            size=10, color=MUTED, wrap=500,
        ).pack(fill="x", pady=(0, 6))
        controls = tk.Frame(setup, background=PANEL)
        controls.pack(fill="x", pady=(4, 0))
        self.evaluate_button = button(controls, "Probar jugada", self.evaluate, primary=True)
        self.evaluate_button.pack(side="left")
        button(controls, "Limpiar", self.clear).pack(side="left", padx=(8, 0))
        self.error = label(setup, "", size=10, color=ERROR, wrap=500)
        self.error.pack(fill="x", pady=(5, 0))

    def add_slots(self, parent, title, count):
        group = tk.Frame(parent, background=PANEL)
        label(group, title, size=10, bold=True).pack(fill="x", pady=(0, 4))
        row = tk.Frame(group, background=PANEL)
        row.pack(fill="x")
        for _ in range(count):
            index = len(self.slots)
            slot = tk.Button(
                row, text="＋", command=lambda index=index: self.pick_card(index),
                width=3, height=1, background=FIELD, foreground=MUTED, relief="flat",
                borderwidth=0, activebackground=ACCENT, cursor="hand2",
                font=("Segoe UI Symbol", 16, "bold"),
            )
            slot.pack(side="left", padx=(0, 4), ipady=4)
            self.slots.append(slot)
        return group

    def build_result(self, result):
        label(result, "Decisión del bot", size=16, bold=True).pack(fill="x")
        self.action = label(result, "", size=24, color=ACCENT, bold=True)
        self.action.pack(fill="x", pady=(16, 0))
        self.amount = label(result, "", size=11, color=MUTED)
        self.amount.pack(fill="x", pady=(0, 13))
        self.reason = label(result, "", size=12, wrap=304)
        self.reason.pack(fill="x", pady=(0, 17))

        metrics = tk.Frame(result, background=FIELD, padx=12, pady=10)
        metrics.pack(fill="x")
        label(metrics, "Parte estimada del bote", size=10, color=MUTED).pack(fill="x")
        self.equity = label(metrics, "", size=20, bold=True)
        self.equity.pack(fill="x", pady=(0, 7))
        label(metrics, "Parte que necesitas para pagar", size=10, color=MUTED).pack(fill="x")
        self.required = label(metrics, "", size=20, bold=True)
        self.required.pack(fill="x")
        label(
            result, "El bot simula manos rivales y cuenta los empates. Da más peso a manos "
            "fuertes si igualar cuesta al menos la mitad del bote actual.",
            size=10, color=MUTED, wrap=304,
        ).pack(fill="x", pady=(14, 0))
        self.invalidate()

    def invalidate(self, *_):
        self.error.configure(text="")
        self.action.configure(text="Por evaluar")
        self.amount.configure(text="")
        self.reason.configure(text="Pulsa «Probar jugada» para ver la decisión.")
        self.equity.configure(text="—")
        self.required.configure(text="—")

    def load_example(self, name):
        hole, board, values = PRESETS[name]
        self.cards = [*hole, *board, *([None] * (5 - len(board)))]
        self.example.set(name)
        for field, value in zip(self.fields.values(), values, strict=True):
            field.set(value)
        self.refresh_cards()

    def clear(self):
        self.cards = [None] * 7
        self.example.set("Cargar un ejemplo")
        for key, field in self.fields.items():
            field.set("1" if key == "opponents" else "")
        self.refresh_cards()

    def refresh_cards(self):
        for card, slot in zip(self.cards, self.slots, strict=True):
            slot.configure(
                text=card_label(card) if card else "＋",
                foreground=("#b52236" if card[1] in "hd" else BG) if card else MUTED,
                background=INK if card else FIELD,
            )
        board_count = sum(card is not None for card in self.cards[2:])
        street = STREETS.get(board_count, "Completa el flop con tres cartas")
        self.street.configure(text=f"{street}  ·  {board_count}/5 cartas en mesa")
        self.invalidate()

    def pick_card(self, index):
        picker = tk.Toplevel(self.root)
        picker.title("Elige una carta")
        picker.configure(background=PANEL, padx=15, pady=12)
        picker.transient(self.root)
        picker.resizable(False, False)
        picker.grab_set()
        picker.bind("<Escape>", lambda _: picker.destroy())

        def select(card):
            self.cards[index] = card
            self.refresh_cards()
            picker.destroy()

        used = set(self.cards[:index] + self.cards[index + 1:])
        for row, suit in enumerate(SUITS):
            for column, rank in enumerate(reversed(RANKS)):
                card = rank + suit
                choice = tk.Button(
                    picker, text=card_label(card), command=lambda card=card: select(card),
                    state="disabled" if card in used else "normal", font=("Segoe UI Symbol", 12),
                    foreground="#b52236" if suit in "hd" else BG, background=INK, width=3,
                    activebackground=ACCENT, relief="flat", borderwidth=0, cursor="hand2",
                    disabledforeground="#7b8d96",
                )
                choice.grid(row=row, column=column, padx=2, pady=2, ipady=3)
        button(picker, "Quitar carta", lambda: select(None)).grid(
            row=4, column=0, columnspan=13, sticky="w", pady=(8, 0),
        )
        picker.focus_set()

    def read_amount(self, field, title, *, optional=False):
        value = self.fields[field].get().strip()
        if not value and optional:
            return None
        if not value.isascii() or not value.isdecimal() or len(value) > 9:
            raise ValueError(f"Ingresa un número entero válido en «{title}».")
        return int(value)

    def evaluate(self):
        self.invalidate()
        try:
            if None in self.cards[:2]:
                raise ValueError("Elige las dos cartas del bot.")
            board = tuple(card for card in self.cards[2:] if card is not None)
            if self.cards[2:2 + len(board)] != list(board):
                raise ValueError("Llena las cartas de la mesa de izquierda a derecha.")
            situation = Situation(
                hole=(self.cards[0], self.cards[1]),
                board=board,
                pot=self.read_amount("pot", "Bote actual"),
                to_call=self.read_amount("call", "Cuánto cuesta pagar"),
                stack=self.read_amount("stack", "Fichas disponibles del bot"),
                opponents=self.read_amount("opponents", "Rivales en la mano"),
                min_raise=self.read_amount("raise", "Mínimo para subir", optional=True),
            )
        except ValueError as error:
            self.error.configure(text=str(error))
            return

        decision = decide(situation)
        self.action.configure(text=decision.action)
        self.amount.configure(text=f"{decision.amount:,}".replace(",", " ") + " fichas a poner")
        self.reason.configure(text=decision.explanation)
        self.equity.configure(text=f"{decision.equity:.1%}".replace(".", ","))
        if decision.required_equity is not None:
            self.required.configure(text=f"{decision.required_equity:.1%}".replace(".", ","))


if __name__ == "__main__":
    root = tk.Tk()
    Tester(root)
    root.mainloop()
