from __future__ import annotations

import asyncio
import json
import random
import string
from collections import defaultdict
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Spender API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    """Simple health check used by platforms and load balancers."""
    return {"status": "ok", "service": "spender", "version": "1.0"}

# ─── Types ─────────────────────────────────────────────────────────────────

GEM_COLORS = ["white", "blue", "green", "red", "black"]


def empty_gems() -> dict[str, int]:
    return {c: 0 for c in GEM_COLORS + ["gold"]}


# ─── Card / Noble data ──────────────────────────────────────────────────────

LEVEL1: list[tuple] = [
    (0,"black",{"blue":1,"green":1,"red":1,"white":1}),(0,"black",{"blue":1,"green":2,"red":1}),
    (0,"black",{"green":3}),(0,"black",{"red":2,"white":1}),(0,"black",{"blue":2,"green":2}),
    (0,"black",{"green":1,"red":1,"white":2}),(0,"black",{"green":2,"blue":1}),(0,"black",{"green":1,"white":2,"blue":1}),
    (0,"blue",{"white":1,"green":1,"red":1,"black":1}),(0,"blue",{"white":1,"red":1,"black":2}),
    (0,"blue",{"red":2,"black":2}),(0,"blue",{"black":3}),(0,"blue",{"white":1,"green":2,"red":1}),
    (0,"blue",{"white":2,"red":2}),(0,"blue",{"white":1,"black":2}),(0,"blue",{"black":2,"red":1}),
    (0,"green",{"blue":1,"red":1,"black":1,"white":1}),(0,"green",{"blue":1,"black":1,"white":2}),
    (0,"green",{"blue":3}),(0,"green",{"white":2,"blue":1}),(0,"green",{"blue":2,"black":2}),
    (0,"green",{"blue":1,"red":2,"black":1}),(0,"green",{"blue":2,"white":1}),(0,"green",{"blue":1,"white":1,"black":2}),
    (0,"red",{"white":1,"blue":1,"green":1,"black":1}),(0,"red",{"white":2,"blue":1,"black":1}),
    (0,"red",{"white":3}),(0,"red",{"blue":2,"green":1}),(0,"red",{"white":2,"green":2}),
    (0,"red",{"white":1,"blue":1,"green":2}),(0,"red",{"white":2,"black":1}),(0,"red",{"white":1,"green":1,"black":2}),
    (0,"white",{"blue":1,"green":1,"red":1,"black":1}),(0,"white",{"green":1,"red":2,"black":1}),
    (0,"white",{"red":3}),(0,"white",{"green":2,"black":1}),(0,"white",{"red":2,"green":2}),
    (0,"white",{"red":1,"green":1,"blue":2}),(0,"white",{"red":2,"black":1}),(0,"white",{"red":1,"black":1,"green":2}),
]

LEVEL2: list[tuple] = [
    (1,"black",{"white":3,"blue":2,"green":2}),(1,"black",{"blue":3,"green":2,"red":3}),
    (2,"black",{"blue":3,"green":3,"red":5}),(2,"black",{"red":5,"white":3}),
    (2,"black",{"green":5}),(3,"black",{"black":6}),
    (1,"blue",{"white":2,"green":3,"red":3}),(1,"blue",{"white":3,"red":2,"black":3}),
    (2,"blue",{"white":3,"black":3,"red":5}),(2,"blue",{"white":5,"black":3}),
    (2,"blue",{"white":5}),(3,"blue",{"blue":6}),
    (1,"green",{"blue":2,"red":3,"black":3}),(1,"green",{"blue":3,"white":2,"black":2}),
    (2,"green",{"white":3,"blue":5,"black":3}),(2,"green",{"red":5,"blue":3}),
    (2,"green",{"blue":5}),(3,"green",{"green":6}),
    (1,"red",{"white":2,"blue":3,"black":3}),(1,"red",{"white":3,"blue":2,"green":3}),
    (2,"red",{"white":3,"green":5,"blue":3}),(2,"red",{"green":5,"white":3}),
    (2,"red",{"black":5}),(3,"red",{"red":6}),
    (1,"white",{"green":2,"red":3,"black":3}),(1,"white",{"red":3,"green":2,"black":3}),
    (2,"white",{"blue":3,"red":5,"black":3}),(2,"white",{"black":5,"green":3}),
    (2,"white",{"red":5}),(3,"white",{"white":6}),
]

LEVEL3: list[tuple] = [
    (3,"black",{"white":3,"blue":3,"green":3,"red":5}),(4,"black",{"white":7}),
    (4,"black",{"white":3,"black":7}),(5,"black",{"black":7,"white":3}),
    (3,"blue",{"white":3,"green":3,"red":3,"black":5}),(4,"blue",{"blue":7}),
    (4,"blue",{"blue":3,"white":7}),(5,"blue",{"blue":7,"black":3}),
    (3,"green",{"white":3,"blue":3,"red":3,"black":5}),(4,"green",{"green":7}),
    (4,"green",{"green":3,"blue":7}),(5,"green",{"green":7,"red":3}),
    (3,"red",{"white":3,"blue":3,"green":5,"black":3}),(4,"red",{"red":7}),
    (4,"red",{"red":3,"green":7}),(5,"red",{"red":7,"green":3}),
    (3,"white",{"blue":3,"green":3,"red":3,"black":5}),(4,"white",{"white":7}),
    (4,"white",{"white":3,"red":7}),(5,"white",{"white":7,"blue":3}),
]

ALL_NOBLES = [
    {"id":"n1","points":3,"req":{"white":4,"green":4}},
    {"id":"n2","points":3,"req":{"white":3,"blue":3,"black":3}},
    {"id":"n3","points":3,"req":{"white":3,"red":3,"green":3}},
    {"id":"n4","points":3,"req":{"blue":4,"green":4}},
    {"id":"n5","points":3,"req":{"blue":4,"black":4}},
    {"id":"n6","points":3,"req":{"green":4,"red":4}},
    {"id":"n7","points":3,"req":{"red":4,"black":4}},
    {"id":"n8","points":3,"req":{"white":4,"blue":4}},
    {"id":"n9","points":3,"req":{"white":4,"red":4}},
    {"id":"n10","points":3,"req":{"black":3,"red":3,"blue":3}},
]


# ─── Game logic ─────────────────────────────────────────────────────────────

def make_card(level: int, data: tuple, idx: int) -> dict:
    pts, bonus, cost = data
    return {"id": f"L{level}-{idx}", "level": level, "points": pts, "bonus": bonus, "cost": cost}


def build_deck() -> dict:
    l1 = [make_card(1, d, i) for i, d in enumerate(LEVEL1)]
    l2 = [make_card(2, d, i) for i, d in enumerate(LEVEL2)]
    l3 = [make_card(3, d, i) for i, d in enumerate(LEVEL3)]
    random.shuffle(l1)
    random.shuffle(l2)
    random.shuffle(l3)
    return {"L1": l1, "L2": l2, "L3": l3}


def bonuses_from(purchased: list[dict]) -> dict[str, int]:
    b = empty_gems()
    for card in purchased:
        b[card["bonus"]] = b.get(card["bonus"], 0) + 1
    return b


def can_afford(cost: dict, tokens: dict, bonuses: dict) -> bool:
    gold_needed = 0
    for c in GEM_COLORS:
        need = max(0, cost.get(c, 0) - bonuses.get(c, 0))
        have = tokens.get(c, 0)
        if have < need:
            gold_needed += need - have
    return gold_needed <= tokens.get("gold", 0)


def calc_spend(cost: dict, tokens: dict, bonuses: dict) -> dict[str, int]:
    spend = empty_gems()
    for c in GEM_COLORS:
        need = max(0, cost.get(c, 0) - bonuses.get(c, 0))
        have = min(tokens.get(c, 0), need)
        spend[c] = have
        gap = need - have
        spend["gold"] = spend.get("gold", 0) + gap
    return spend

# ... (omitted rest for brevity in patch) ...

