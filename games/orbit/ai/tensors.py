"""Versioned numeric adapter for audited semantic tokens.

Fit vocabulary on training inputs only. Freeze/export it with the checkpoint;
unknown paths/categories fail explicitly rather than hash-collide or disappear.
Sequence indices stay numeric, so longer columns/history need no new vocabulary.
This reference adapter preserves tokens; pooling into card/state embeddings is
the model's job, not a lossy preprocessing shortcut.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from functools import lru_cache
import json
import math
import struct

from .features import ENCODER_VERSION, FEATURE_GROUPS, FeatureToken
from .state import rules_fingerprint
from ..cards import CARDS

TENSOR_VERSION = "orbit-tensors-v3"
CARD_IDS = {card:i+1 for i,card in enumerate(sorted(CARDS))}
KINDS = ("object", "sequence", "missing", "boolean", "number", "category")
GROUPS = tuple(sorted(FEATURE_GROUPS))


@lru_cache(maxsize=16384)
def path_key(path):
    return json.dumps([None if type(part) is int else part for part in path],
                      ensure_ascii=False, separators=(",", ":"))


def entity_key(token):
    """Group fields by physical card/action, retaining every original token."""
    p = token.path
    size = 1
    if p and p[0] == "players" and len(p) >= 2:
        size = 2
        if len(p) >= 3 and p[2] == "columns":
            size = min(len(p), 5)
        elif len(p) >= 3 and p[2] == "hand":
            size = min(len(p), 4)
    elif p and p[0] in ("legal_moves", "agent_discard"):
        size = min(len(p), 2)
    elif len(p) >= 2 and p[:2] == ("history", "events"):
        size = min(len(p), 3)
    return (token.group, *p[:size])


@dataclass(frozen=True)
class Vocabulary:
    paths: tuple[str, ...]
    categories: tuple[str, ...]
    rules: str

    @classmethod
    def fit(cls, examples):
        paths, categories = set(), set()
        for tokens in examples:
            for token in tokens:
                paths.add(path_key(token.path))
                if token.kind == "category":
                    categories.add(token.value)
        return cls(tuple(sorted(paths)), tuple(sorted(categories)), rules_fingerprint())

    def as_dict(self):
        return {"version": TENSOR_VERSION, "encoder": ENCODER_VERSION,
                "rules": self.rules, "paths": list(self.paths),
                "categories": list(self.categories), "groups": list(GROUPS),
                "kinds": list(KINDS), "numeric_scale": 32}

    @classmethod
    def from_dict(cls, value):
        if (value.get("version") not in ("orbit-tensors-v2",TENSOR_VERSION) or value.get("encoder") != ENCODER_VERSION
                or value.get("rules") != rules_fingerprint()
                or value.get("groups") != list(GROUPS) or value.get("kinds") != list(KINDS)
                or value.get("numeric_scale") != 32):
            raise ValueError("Tensor vocabulary version/rules mismatch")
        for field in ("paths", "categories"):
            items = value[field]
            if any(not isinstance(x, str) for x in items) or items != sorted(set(items)):
                raise ValueError("Vocabulary must contain sorted unique strings")
        return cls(tuple(value["paths"]), tuple(value["categories"]), value["rules"])


class TensorEncoder:
    def __init__(self, vocabulary: Vocabulary):
        self.vocabulary = Vocabulary.from_dict(vocabulary.as_dict())
        # Zero is padding, never a real category/path/group/kind ID.
        self.paths = {key: i + 1 for i, key in enumerate(vocabulary.paths)}
        self.categories = {key: i + 1 for i, key in enumerate(vocabulary.categories)}

    def encode(self, tokens):
        tokens=tuple(tokens)
        observer=next((t.value for t in tokens if t.path==("seat",)),None)
        rows = []
        entities = {}
        for token in tokens:
            entity = entities.setdefault(entity_key(token), len(entities) + 1)
            try:
                path = self.paths[path_key(token.path)]
                group = GROUPS.index(token.group) + 1
                kind = KINDS.index(token.kind) + 1
                category = self.categories[token.value] if token.kind == "category" else 0
            except (KeyError, ValueError) as error:
                raise ValueError(f"Unseen or invalid semantic token: {token}") from error
            number = 0.0
            if token.kind in ("number", "sequence", "object", "boolean"):
                raw = float(token.value)
                try:
                    number = struct.unpack("<f", struct.pack("<f", raw / 32))[0]
                except OverflowError as error:
                    raise ValueError("Numeric feature outside float32 range") from error
                if not math.isfinite(number) or number * 32 != raw:
                    raise ValueError("Numeric feature cannot be represented exactly as float32")
            positions = [part for part in token.path if type(part) is int]
            if any(p < 0 or p >= 2**31 - 1 for p in positions):
                raise ValueError("Sequence position outside int32 range")
            p=token.path
            role=1
            if "players" in p and observer in (0,1):
                at=p.index("players")
                if len(p)>at+1 and type(p[at+1]) is int:role=2 if p[at+1]==observer else 3
            is_card = token.kind=="number" and (
                (len(p)>=2 and p[-2:]==("attributes","id")) or p[-1:]==("card_id",)
                or (len(p)>=2 and p[-2]=="card_ids" and type(p[-1]) is int)
                or (len(p)==2 and p[0]=="agent_discard" and type(p[1]) is int)
                or (len(p)==4 and p[0]=="players" and p[2]=="hand")
                or (len(p)==5 and p[0]=="players" and p[2]=="columns"))
            card=CARD_IDS[token.value] if is_card else 0
            rows.append({"group": group, "kind": kind, "path": path,
                         "positions": positions, "category": category, "number": number,
                         "entity": entity, "role":role, "card":card})
        return rows

    def batch(self, examples):
        """Return NumPy arrays with explicit token and path-position masks."""
        import numpy as np

        rows = [self.encode(tokens) for tokens in examples]
        width = max((len(example) for example in rows), default=0)
        depth = max((len(row["positions"]) for example in rows for row in example), default=0)
        result = {key: np.zeros((len(rows), width), dtype=np.int64)
                  for key in ("group", "kind", "path", "category", "entity", "role", "card")}
        result["number"] = np.zeros((len(rows), width), dtype=np.float32)
        result["mask"] = np.zeros((len(rows), width), dtype=bool)
        result["positions"] = np.zeros((len(rows), width, depth), dtype=np.int64)
        result["position_mask"] = np.zeros((len(rows), width, depth), dtype=bool)
        for b, example in enumerate(rows):
            for t, row in enumerate(example):
                for key in ("group", "kind", "path", "category", "number", "entity", "role", "card"):
                    result[key][b, t] = row[key]
                result["mask"][b, t] = True
                n = len(row["positions"])
                result["positions"][b, t, :n] = row["positions"]
                result["position_mask"][b, t, :n] = True
        return result


def native_request(vocabulary, tokens):
    return {"vocabulary": vocabulary.as_dict(), "tokens": [asdict(t) for t in tokens]}
