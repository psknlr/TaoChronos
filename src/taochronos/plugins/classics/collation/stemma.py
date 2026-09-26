"""From variant units to a stemma: distances, a tree, the groups the readings define, and contamination.

* **Distance** between two witnesses: weighted disagreements in the units both carry, per 1 000 characters of
  base text both carry — lacunae are missing data, not disagreement; function-word variants weigh half.
* **Tree**: neighbour-joining on the distances (unrooted), rooted at the midpoint of its longest path or at a chosen
  witness; internal nodes are hypothetical exemplars (α, β …).
* **Groups**: in each unit the reading most witnesses carry stands for the transmitted text; a minority reading
  shared by two or more witnesses (and not all) is a candidate *shared innovation* and groups them (Lachmann's
  agreement in error).  Groups the tree holds as clades support it; groups it cannot hold point to contamination.
* **Contamination**: a witness whose shared readings keep grouping it with witnesses outside its own clade — the
  share of its group support that conflicts with the tree — copied, at least in part, from another branch.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from itertools import combinations
from typing import Any

from ....protocol.textual_criticism import ContaminationEdge, StemmaEdge, VariantUnit
from .variant_graph import counts

GREEK = "αβγδεζηθικλμνξοπρστυφχψω"


def distances(units: list[VariantUnit], sigla: list[str], present: dict[str, bytearray]) -> dict[tuple[str, str], float]:
    reading: dict[str, dict[str, str]] = {}
    for u in units:
        if not counts(u):
            continue
        reading[u.id] = {s: r.text for r in u.readings for s in r.witnesses}
    weight = {u.id: u.weight for u in units}
    out: dict[tuple[str, str], float] = {}
    for a, b in combinations(sigla, 2):
        shared = sum(x & y for x, y in zip(present[a], present[b])) if a in present and b in present else 0
        diff = sum(weight[uid] for uid, rd in reading.items() if a in rd and b in rd and rd[a] != rd[b])
        d = 1000.0 * diff / shared if shared else 1000.0
        out[(a, b)] = out[(b, a)] = round(d, 4)
    return out


def neighbour_joining(names: list[str], d: dict[tuple[str, str], float]) -> list[tuple[str, str, float]]:
    """Unrooted tree as undirected edges (u, v, length); internal nodes are named #1, #2 …"""
    nodes = list(names)
    if len(nodes) < 2:
        return []
    dist = {(a, b): d[(a, b)] for a in nodes for b in nodes if a != b}
    edges: list[tuple[str, str, float]] = []
    counter = 0
    while len(nodes) > 2:
        n = len(nodes)
        r = {a: sum(dist[(a, b)] for b in nodes if b != a) for a in nodes}
        best: tuple[float, str, str] | None = None
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                q = (n - 2) * dist[(a, b)] - r[a] - r[b]
                if best is None or q < best[0] - 1e-9:
                    best = (q, a, b)
        _, a, b = best  # type: ignore[misc]
        counter += 1
        u = f"#{counter}"
        la = 0.5 * dist[(a, b)] + (r[a] - r[b]) / (2 * (n - 2))
        lb = dist[(a, b)] - la
        edges += [(u, a, max(0.0, la)), (u, b, max(0.0, lb))]
        for c in nodes:
            if c not in (a, b):
                dist[(u, c)] = dist[(c, u)] = max(0.0, 0.5 * (dist[(a, c)] + dist[(b, c)] - dist[(a, b)]))
        nodes = [c for c in nodes if c not in (a, b)] + [u]
    a, b = nodes
    edges.append((a, b, max(0.0, dist[(a, b)])))
    return edges


def _adjacency(edges: list[tuple[str, str, float]]) -> dict[str, dict[str, float]]:
    adj: dict[str, dict[str, float]] = defaultdict(dict)
    for u, v, w in edges:
        adj[u][v] = w
        adj[v][u] = w
    return adj


def _farthest(adj: dict[str, dict[str, float]], start: str) -> tuple[str, float, dict[str, str]]:
    seen, stack, prev = {start: 0.0}, [start], {start: ""}
    while stack:
        x = stack.pop()
        for y, w in adj[x].items():
            if y not in seen:
                seen[y] = seen[x] + w
                prev[y] = x
                stack.append(y)
    far = max(seen, key=lambda k: (seen[k], k))
    return far, seen[far], prev


def root(edges: list[tuple[str, str, float]], leaves: list[str], at: str | None = None) -> tuple[list[StemmaEdge], str]:
    """Directed edges from a root: at the attachment of witness ``at``, else at the midpoint of the longest path.
    Internal nodes are renamed α, β … in breadth-first order."""
    if not edges:
        return [], leaves[0] if leaves else ""
    adj = _adjacency(edges)
    if at and at in adj:
        root_node = next(iter(adj[at])) if at in leaves and len(adj[at]) == 1 else at
    else:  # midpoint rooting: split the longest leaf-to-leaf path in the middle
        a, _, _ = _farthest(adj, leaves[0])
        b, total, prev = _farthest(adj, a)
        path = [b]
        while prev[path[-1]]:
            path.append(prev[path[-1]])
        half, acc, root_node = total / 2, 0.0, path[0]
        for x, y in zip(path, path[1:]):
            w = adj[x][y]
            if acc + w >= half:
                if half - acc < 1e-9:
                    root_node = x
                elif acc + w - half < 1e-9:
                    root_node = y
                else:  # insert a node on the edge
                    mid = "#root"
                    del adj[x][y], adj[y][x]
                    adj[x][mid] = adj[mid][x] = half - acc
                    adj[y][mid] = adj[mid][y] = acc + w - half
                    root_node = mid
                break
            acc += w
            root_node = y
    names: dict[str, str] = {}
    order = [root_node]
    seen = {root_node}
    out: list[StemmaEdge] = []
    i = 0
    while i < len(order):
        x = order[i]
        i += 1
        for y in sorted(adj[x], key=lambda k: (k.startswith("#"), k)):
            if y in seen:
                continue
            seen.add(y)
            order.append(y)
            out.append(StemmaEdge(parent=x, child=y, length=round(adj[x][y], 3)))
    greek = iter(GREEK)
    for x in order:
        if x.startswith("#") or x not in leaves:
            names[x] = next(greek, x) if x.startswith("#") else x
    for e in out:
        e.parent = names.get(e.parent, e.parent)
        e.child = names.get(e.child, e.child)
    return out, names.get(root_node, root_node)


def clades(edges: list[StemmaEdge], leaves: list[str]) -> dict[str, frozenset[str]]:
    """Every node of the rooted tree → the witnesses below it."""
    children: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        children[e.parent].append(e.child)
    memo: dict[str, frozenset[str]] = {}

    def below(x: str) -> frozenset[str]:
        if x not in memo:
            memo[x] = frozenset([x]) if x in leaves and not children[x] else frozenset().union(
                *(below(c) for c in children[x])) | (frozenset([x]) if x in leaves else frozenset())
        return memo[x]

    nodes = {e.parent for e in edges} | {e.child for e in edges}
    return {x: below(x) for x in nodes}


def splits(edges: list[tuple[str, str, float]], leaves: list[str]) -> set[frozenset[str]]:
    """Bipartitions of the leaves by the internal edges of an unrooted tree (the side without the first leaf)."""
    adj = _adjacency(edges)
    leafset = set(leaves)
    out: set[frozenset[str]] = set()
    for u, v, _ in edges:
        side = _side(adj, v, u) & leafset
        if 1 < len(side) < len(leafset) - 1:
            out.add(frozenset(side) if sorted(leaves)[0] not in side else frozenset(leafset - side))
    return out


def _side(adj: dict[str, dict[str, float]], start: str, block: str) -> set[str]:
    seen, stack = {start}, [start]
    while stack:
        x = stack.pop()
        for y in adj[x]:
            if y != block and y not in seen and not (x == start and y == block):
                seen.add(y)
                stack.append(y)
    return seen


def robinson_foulds(a: set[frozenset[str]], b: set[frozenset[str]]) -> float | None:
    """Normalised Robinson–Foulds distance: 0 = the same tree, 1 = no split in common."""
    total = len(a) + len(b)
    return round(len(a ^ b) / total, 4) if total else None


def groups(units: list[VariantUnit], sigla: list[str]) -> list[dict[str, Any]]:
    """Candidate shared innovations: minority readings carried by two or more witnesses (not all present)."""
    support: dict[frozenset[str], float] = defaultdict(float)
    examples: dict[frozenset[str], list[str]] = defaultdict(list)
    for u in units:
        if not counts(u):
            continue
        present = [s for r in u.readings for s in r.witnesses]
        if len(present) < 3:
            continue
        majority = max(u.readings, key=lambda r: (len(r.witnesses), r.text == u.lemma))
        for r in u.readings:
            if r is majority or not (2 <= len(r.witnesses) < len(present)):
                continue
            g = frozenset(r.witnesses)
            support[g] += u.weight
            if len(examples[g]) < 6:
                examples[g].append(u.id)
    return [{"witnesses": sorted(g), "support": round(w, 2), "examples": examples[g]}
            for g, w in sorted(support.items(), key=lambda kv: (-kv[1], sorted(kv[0])))]


def _parent_clade(edges: list[StemmaEdge], leaves: list[str], w: str) -> frozenset[str]:
    parent = next((e.parent for e in edges if e.child == w), None)
    if parent is None:
        return frozenset([w])
    return clades(edges, leaves).get(parent, frozenset([w]))


def _direction(units: list[VariantUnit], w: str, s: str, blocks: int = 8) -> tuple[float, float, int]:
    """Where ``w`` and ``s`` share private readings, which one carries the other's private readings?

    In a stretch copied from ``s``, every private reading of ``s`` reappears in ``w`` while ``w``'s own new readings
    appear in no other witness: the share of ``s``'s private readings found in ``w`` (``a``) exceeds the share of
    ``w``'s found in ``s`` (``b``).  Counted block by block, only in blocks where the two share private readings."""
    ordered = sorted((u for u in units if counts(u)), key=lambda u: u.start)
    if not ordered:
        return 0.0, 0.0, 0
    size = max(1, len(ordered) // blocks)
    pair = only_s = only_w = 0.0
    for k in range(0, len(ordered), size):
        chunk = ordered[k: k + size]
        ps = pw = pws = 0.0
        for u in chunk:
            for r in u.readings:
                members = set(r.witnesses)
                if members == {w, s}:
                    pws += u.weight
                elif members == {s}:
                    ps += u.weight
                elif members == {w}:
                    pw += u.weight
        if pws:
            pair, only_s, only_w = pair + pws, only_s + ps, only_w + pw
    if not pair:
        return 0.0, 0.0, 0
    return pair / (pair + only_s), pair / (pair + only_w), int(pair)


def patterns(units: list[VariantUnit], sigla: list[str], top: int = 12) -> list[dict[str, Any]]:
    """How the witnesses split in the units all of them carry (AB|C …): the agreement patterns and their weight.
    With three witnesses, where no minority reading can be told from a majority one, these are the evidence."""
    weight: Counter = Counter()
    n = Counter()
    for u in units:
        if not counts(u):
            continue
        present = {s for r in u.readings for s in r.witnesses}
        if set(sigla) - present:
            continue
        key = "|".join(sorted("".join(sorted(r.witnesses)) for r in u.readings))
        weight[key] += u.weight
        n[key] += 1
    return [{"pattern": k, "units": n[k], "weight": round(w, 2)} for k, w in weight.most_common(top)]


def contamination(units: list[VariantUnit], grouped: list[dict[str, Any]], edges: list[StemmaEdge], sigla: list[str], *,
                  min_support: float = 3.0, per_unit: float = 0.015, min_share: float = 0.2, margin: float = 0.1
                  ) -> tuple[list[ContaminationEdge], list[dict[str, Any]]]:
    """Contaminated witnesses (with the witness they also copied) and the conflicts whose direction is undetermined.

    A conflicting group is one the tree does not hold as a clade; its members outside a witness's own branch are
    that witness's *cross partners*.  For each witness and cross partner with enough conflicting support — at least
    ``min_support`` and ``per_unit`` of the counting units, since in a long text a few coincident changes are expected
    — the direction test decides which one copied the other (see ``_direction``).  The share is the part of a
    witness's group support that crosses the tree: a witness copied half from each branch shows about a fifth, since
    the readings of the branch it sits in are majority readings and form no group."""
    min_support = max(min_support, per_unit * sum(1 for u in units if counts(u)))
    tree_clades = set(clades(edges, sigla).values())
    leafset = set(sigla)
    cross: dict[tuple[str, str], float] = defaultdict(float)
    examples: dict[tuple[str, str], list[str]] = defaultdict(list)
    total: dict[str, float] = defaultdict(float)
    for g in grouped:
        members = frozenset(g["witnesses"]) & leafset
        for w in members:
            total[w] += g["support"]
        if len(members) < 2 or members in tree_clades:
            continue
        for w in members:
            own = _parent_clade(edges, sigla, w)
            for s in members - own:
                cross[(w, s)] += g["support"]
                if len(examples[(w, s)]) < 6:
                    examples[(w, s)] += g["examples"][:2]
    edges_out: list[ContaminationEdge] = []
    undetermined: list[dict[str, Any]] = []
    done: set[frozenset[str]] = set()
    for (w, s), support in sorted(cross.items(), key=lambda kv: (-kv[1], kv[0])):
        pair = frozenset((w, s))
        if pair in done or support < min_support:
            continue
        done.add(pair)
        a, b, n = _direction(units, w, s)
        share_w = support / total[w] if total[w] else 0.0
        share_s = cross.get((s, w), support) / total[s] if total[s] else 0.0
        if a > b + margin and share_w >= min_share:
            edges_out.append(ContaminationEdge(witness=w, source=s, share=round(share_w, 3), support=round(support, 2),
                                               examples=examples[(w, s)][:6]))
        elif b > a + margin and share_s >= min_share:
            edges_out.append(ContaminationEdge(witness=s, source=w, share=round(share_s, 3), support=round(support, 2),
                                               examples=examples[(w, s)][:6]))
        elif max(share_w, share_s) >= min_share:
            undetermined.append({"witnesses": sorted(pair), "support": round(support, 2), "shared_private": n,
                                 "examples": examples[(w, s)][:6]})
    return edges_out, undetermined


def newick(edges: list[StemmaEdge], root_name: str) -> str:
    children: dict[str, list[StemmaEdge]] = defaultdict(list)
    for e in edges:
        children[e.parent].append(e)

    def render(x: str) -> str:
        if not children[x]:
            return x
        inner = ",".join(f"{render(e.child)}:{e.length}" for e in children[x])
        return f"({inner}){'' if x.startswith(tuple(GREEK)) or x == '#root' else x}"

    return render(root_name) + ";"


def ascii_tree(edges: list[StemmaEdge], root_name: str, labels: dict[str, str] | None = None) -> str:
    children: dict[str, list[StemmaEdge]] = defaultdict(list)
    for e in edges:
        children[e.parent].append(e)
    labels = labels or {}
    lines = [labels.get(root_name, root_name)]

    def walk(x: str, prefix: str) -> None:
        kids = children[x]
        for i, e in enumerate(kids):
            last = i == len(kids) - 1
            lines.append(f"{prefix}{'└─' if last else '├─'} {labels.get(e.child, e.child)}  ({e.length})")
            walk(e.child, prefix + ("   " if last else "│  "))

    walk(root_name, "")
    return "\n".join(lines)


__all__ = ["ascii_tree", "clades", "contamination", "distances", "groups", "neighbour_joining", "newick", "patterns",
           "robinson_foulds", "root", "splits"]
