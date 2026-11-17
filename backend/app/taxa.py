"""The taxon tree: kingdom → phylum → class → order → family → genus → species.

Serves two things in Explore's sidebar — a tree to browse, and a search box
over every rank at once — and the `taxon` filter both of them select into.

**A taxon is (kingdom, rank, name), never a bare name.** Genus names are only
unique within a nomenclatural code, and this store has ~30 that collide across
kingdoms: *Arenaria* is a sandwort and a sandpiper, *Chloris* a grass and a
finch. Filtering on `genus = 'Arenaria'` would mix them, so the kingdom always
travels with the name, and the filter value is `Kingdom/rank/Name`
(`Plantae/genus/Arenaria`; a kingdom alone is just `Plantae`).

The species step is the **binomial**, not the stored `scientific_name`:
selecting *Rosa canina* includes *Rosa canina* var. *x*, the way picking a
species does in GBIF. Subgenus and hybrid sign are kept as part of it
(`Onthophagus (Parascatonomus) tricornis`, `Alpinia × formosana`).

Like `api/species.py`, everything here reads one grouped scan (~0.7s, ~35k
paths) held in memory with a TTL, so tree expansion and search-as-you-type cost
no scan at all. Counts are therefore store-wide, not narrowed by Explore's other
filters — the tree is for choosing a taxon, the result total is what reports
the intersection. Names are as the store holds them; nothing is reconciled
against a checklist (see `species.py`).
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from . import duck

# (rank, SQL expression over `occurrence`, its Chinese-name column)
BINOMIAL = r"""nullif(regexp_extract(scientific_name, '^(\S+ (?:\([^)]+\) )?(?:× )?[a-z]\S*)', 1), '')"""
RANKS: list[tuple[str, str, str]] = [
    ("kingdom", "kingdom", "kingdom_c"),
    ("phylum", "phylum", "phylum_c"),
    ("class", '"class"', "class_c"),
    ("order", '"order"', "order_c"),
    ("family", "family", "family_c"),
    ("genus", "genus", "genus_c"),
    ("species", BINOMIAL, "common_name_c"),
]
RANK_NAMES = [r for r, _, _ in RANKS]
_COL = {r: col for r, col, _ in RANKS}

# A pasted URL with dozens of taxa is not a lookup anyone makes by hand.
MAX_TAXA = 30


def parse_taxon(value: str) -> tuple[str, str, str] | None:
    """"Plantae/genus/Arenaria" -> ("Plantae", "genus", "Arenaria");
    "Plantae" -> ("Plantae", "kingdom", "Plantae"). None if malformed."""
    parts = [p.strip() for p in value.split("/", 2)]
    if len(parts) == 1 and parts[0]:
        return parts[0], "kingdom", parts[0]
    if len(parts) == 3 and all(parts) and parts[1] in _COL:
        return parts[0], parts[1], parts[2]
    return None


def taxon_key(kingdom: str, rank: str, name: str) -> str:
    return kingdom if rank == "kingdom" else f"{kingdom}/{rank}/{name}"


def taxon_condition(value: str) -> tuple[str, list[Any]] | None:
    """SQL for one taxon filter value, or None if it does not parse."""
    t = parse_taxon(value)
    if not t:
        return None
    kingdom, rank, name = t
    if rank == "kingdom":
        return "kingdom = ?", [kingdom]
    if rank == "species":
        # The binomial and everything below it: "Rosa canina", "Rosa canina var. x".
        return (
            "(kingdom = ? AND (scientific_name = ? OR starts_with(scientific_name, ?)))",
            [kingdom, name, name + " "],
        )
    return f"(kingdom = ? AND {_COL[rank]} = ?)", [kingdom, name]


# ---------------------------------------------------------------- the rollup

_ROLLUP_SQL = f"""
    SELECT {", ".join(f"{col} AS {rank}" for rank, col, _ in RANKS)},
           {", ".join(f"max({c}) AS {rank}_c" for rank, _, c in RANKS[:-1])},
           max(common_name_c) FILTER (WHERE scientific_name = {BINOMIAL}) AS species_c,
           count(*) AS n
    FROM occurrence
    WHERE kingdom IS NOT NULL AND kingdom <> ''
    GROUP BY ALL
"""


@dataclass
class Node:
    kingdom: str
    rank: str
    name: str
    name_c: str | None = None
    n: int = 0
    parent: "Node | None" = None
    children: dict[str, "Node"] = field(default_factory=dict)
    # Records under this node with nothing at the next rank — a family whose
    # order is blank. Counted, not drawn as a node: there is nothing to name it.
    n_unplaced: int = 0

    @property
    def key(self) -> str:
        return taxon_key(self.kingdom, self.rank, self.name)

    def row(self) -> dict:
        return {
            "key": self.key, "kingdom": self.kingdom, "rank": self.rank,
            "name": self.name, "name_c": self.name_c, "n": self.n,
            "has_children": bool(self.children),
        }


@dataclass
class Tree:
    roots: dict[str, Node]
    by_key: dict[str, Node]


_TREE: Tree | None = None
_TREE_AT = 0.0
_TREE_TTL = 600.0
_lock = asyncio.Lock()


def build_tree(rows: list[dict]) -> Tree:
    roots: dict[str, Node] = {}
    by_key: dict[str, Node] = {}
    for r in rows:
        n = r["n"]
        kingdom = r["kingdom"]
        siblings, parent = roots, None
        for rank in RANK_NAMES:
            name = r[rank]
            if name is None or name == "":
                if parent is not None:
                    parent.n_unplaced += n
                break
            node = siblings.get(name)
            if node is None:
                node = Node(kingdom, rank, name, parent=parent)
                siblings[name] = node
                # A name can sit under two parents (a genus filed in two
                # families); both tree nodes select the same records, so the
                # search lists it once.
                by_key.setdefault(node.key, node)
            node.n += n
            node.name_c = node.name_c or r.get(f"{rank}_c") or None
            siblings, parent = node.children, node
    return Tree(roots, by_key)


async def tree() -> Tree:
    global _TREE, _TREE_AT
    async with _lock:
        if _TREE is not None and time.monotonic() - _TREE_AT < _TREE_TTL:
            return _TREE
        _TREE, _TREE_AT = build_tree(await duck.query(_ROLLUP_SQL)), time.monotonic()
        return _TREE


def _sorted(nodes) -> list[dict]:
    return [c.row() for c in sorted(nodes, key=lambda c: (-c.n, c.name))]


async def children(key: str | None) -> dict:
    """The kingdoms (no key), or one node's children, largest first."""
    t = await tree()
    if not key:
        return {"items": _sorted(t.roots.values()), "n_unplaced": 0}
    node = t.by_key.get(key)
    if node is None:
        return {"items": [], "n_unplaced": 0}
    return {"items": _sorted(node.children.values()), "n_unplaced": node.n_unplaced}


def _lineage(node: Node) -> list[str]:
    """Ancestors, nearest first, for telling homonyms and similar names apart."""
    out, p = [], node.parent
    while p is not None:
        out.append(p.name)
        p = p.parent
    return out


async def search(q: str, limit: int = 20) -> list[dict]:
    """Taxa at any rank whose Latin or Chinese name contains `q`.

    Exact matches first, then prefixes, then the rest; larger taxa first within
    each, so "Rosa" puts the genus above *Rosa canina* above Rosales."""
    q = q.strip()
    if not q:
        return []
    ql = q.lower()
    hits = []
    for node in (await tree()).by_key.values():
        name, name_c = node.name.lower(), node.name_c or ""
        if ql in name or (name_c and q in name_c):
            tier = 0 if ql == name or q == name_c else 1 if name.startswith(ql) or name_c.startswith(q) else 2
            hits.append((tier, -node.n, node.name, node))
    hits.sort(key=lambda h: h[:3])
    return [{**node.row(), "lineage": _lineage(node)} for *_, node in hits[:limit]]


def reset_cache() -> None:
    global _TREE
    _TREE = None
