"""Mutation matrix of the invariants: each of six boundaries removed in turn, and all 19 probes run on every variant.

    python3 paper/figures/mutation_matrix.py     # about half a minute; writes source_data/extfig_mutation_matrix.json

``docs/evals.md`` records the diagonal (a boundary removed, its invariant broken); this measures the rest: which of the
other 18 still hold.  A boundary is removed by deleting its check and nothing else: the refusing ``if`` is cut from the
installed source and the function's code replaced, so every holder of the function runs it without the check (event
authority also widens one table entry).  Each variant is a fresh EvalContext on a fresh data directory (demonstration
corpus, offline full-discovery profile), patched before its harness and reference run are built and restored after its
probes; a second intact run checks the restores.
"""

from __future__ import annotations

import __future__
import ast
import inspect
import json
import os
import shutil
import sys
import tempfile
import textwrap
import time
from contextlib import ExitStack, contextmanager
from itertools import count
from pathlib import Path
from typing import Any, Callable, Iterator

sys.dont_write_bytecode = True  # the harness is imported, never recompiled into the repository

HOME = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "source_data" / "extfig_mutation_matrix.json"
sys.path.insert(0, str(HOME / "src"))


# ------------------------------------------------------------------ the two ways a boundary is removed
def _without(fn: Any, tests: tuple[str, ...]) -> tuple[Any, list[str]]:
    """``fn``'s code compiled from its installed source with the ``if`` statements whose conditions read as ``tests``
    deleted (a deleted ``elif`` hands on the branches after it), and the statements deleted."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    ast.increment_lineno(tree, fn.__code__.co_firstlineno - 1)
    gone: list[ast.If] = []

    class Cut(ast.NodeTransformer):
        def visit_If(self, node: ast.If) -> Any:
            self.generic_visit(node)
            if ast.unparse(node.test) not in tests:
                return node
            gone.append(node)
            return node.orelse

    tree = ast.fix_missing_locations(Cut().visit(tree))
    found = sorted(ast.unparse(n.test) for n in gone)
    if found != sorted(tests):
        raise SystemExit(f"{fn.__qualname__}: expected to cut {sorted(tests)}, found {found}; the source changed")
    ns: dict[str, Any] = {}
    exec(compile(tree, inspect.getsourcefile(fn), "exec", flags=__future__.annotations.compiler_flag, dont_inherit=True),
         fn.__globals__, ns)
    cut = [" ".join(ast.unparse(ast.If(test=n.test, body=n.body, orelse=[])).split()) for n in gone]
    return ns[fn.__name__].__code__.replace(co_qualname=fn.__code__.co_qualname), cut


@contextmanager
def cut(fn: Any, *tests: str) -> Iterator[str]:
    """``fn`` without the checks ``tests`` names, until the block ends."""
    code, gone = _without(fn, tests)
    saved, fn.__code__ = fn.__code__, code
    try:
        yield (f"{fn.__module__}.{fn.__qualname__}: " + " · ".join(f"`{g}`" for g in gone)
               + f" deleted (__code__ recompiled from its source without {'it' if len(gone) == 1 else 'them'})")
    finally:
        fn.__code__ = saved


@contextmanager
def widen(event_type: str) -> Iterator[str]:
    """Every principal may emit ``event_type``, until the block ends."""
    from taochronos.kernel import authority

    saved = authority.EVENT_AUTHORITY[event_type]
    authority.EVENT_AUTHORITY[event_type] = frozenset(authority.PRINCIPALS)
    try:
        yield f"taochronos.kernel.authority.EVENT_AUTHORITY[{event_type!r}]: {'/'.join(sorted(saved))} widened to every principal"
    finally:
        authority.EVENT_AUTHORITY[event_type] = saved


def knockouts() -> list[tuple[str, str, str, str, Callable[[], list]]]:
    """name · boundary removed · the invariant docs/evals.md reports broken · where the boundary lives · its patches."""
    from taochronos.kernel.reducer import Reducer
    from taochronos.verification import hooks, provenance, scope

    return [
        ("no_scope_guard", "BeforeToolCall scope guard", "I01",
         "hook 'scope_guard' at BeforeToolCall (registered by verification.hooks.install_default_hooks)",
         lambda: [cut(scope.scope_argument_guard, "hits")]),
        ("no_scope_firewall", "AfterToolCall scope firewall", "I02",
         "hook 'scope_firewall' at AfterToolCall (registered by verification.hooks.install_default_hooks)",
         lambda: [cut(scope.scope_result_firewall, "hits")]),
        ("no_semantic_support", "semantic-support commit hook (BeforeClaimCommit)", "I04",
         "factory of hook 'semantic_support' at BeforeClaimCommit; a claim still receives its support reading and frame",
         lambda: [cut(hooks.semantic_support_validator, "a.verdict == 'contradicts'")]),
        ("no_gate_authority", "reducer authority for GateEvaluated (G7 only by an expert)", "I12",
         "the authority table and Reducer.validate; Reducer._gate_evaluated still drops a G7 result when applying",
         lambda: [widen("GateEvaluated"), cut(Reducer.validate, "event.type == T.GATE_EVALUATED.value")]),
        ("no_evidence_bounds", "evidence bound checks (provenance verification)", "I13",
         "the two checks added for audit probe P09; the quote is still compared with the text at its span",
         lambda: [cut(provenance.verify_evidence, "not record.quote",
                      "not 0 <= record.start < record.end <= len(passage.text)")]),
        ("no_publish_guard", "publish guard (BeforeArtifactPublish)", "I18",
         "factory of hook 'publish_guard' at BeforeArtifactPublish: all three of its refusals",
         lambda: [cut(hooks.publish_guard, "not artifact.evidence_refs", "missing or retracted", "stale")]),
    ]


# ------------------------------------------------------------------ one variant
def variant(name: str, root: Path, boundary: str = "", target: str = "", where: str = "",
            patches: Callable[[], list] = list) -> tuple[dict[str, Any], Any]:
    from taochronos.evals import boundaries
    from taochronos.evals.base import EvalContext

    with ExitStack() as stack:
        how = [stack.enter_context(p) for p in patches()]
        boundaries._SEQ = count(1)  # the probes' session counter: every variant runs the same sessions
        ctx = EvalContext(home=HOME, data_dir=root / name)
        result = boundaries.invariants(ctx)  # builds the harness under evaluation, and its reference run, patched
        h, ref = ctx.pipeline()
    if h.capabilities.names("corpus") != ["demo"] or getattr(h.corpus, "large", False):
        raise SystemExit(f"{name}: the harness is not on the demonstration corpus ({h.capabilities.names('corpus')})")
    m = result.metrics
    row = {"name": name, "boundary_removed": boundary or None, "target": target or None,
           "patch": "; ".join(how) + f" | {where}" if how else None, "held": m["held"], "broken": m["broken"],
           "off_target": [i for i in m["broken"] if i != target], "not_exercised": m["not_exercised"],
           "results": [{"id": d["id"], "held": d["held"], "observed": d["observed"]} for d in result.details],
           # the research run I18 and I19 read: an off-target effect through it would change it
           "reference_run": {"events": ref.seq, "state_hash": ref.state.state_hash(),
                             "hook_blocks": dict(sorted(ref.state.metrics.get("hook_blocks_by_hook", {}).items()))}}
    return row, h


def main() -> None:
    started = time.perf_counter()
    root = Path(tempfile.mkdtemp(prefix="taochronos-mutation-"))
    os.environ["TAOCHRONOS_DATA"] = str(root)  # nothing read from or written to a real data directory
    try:
        from taochronos.evals.boundaries import INVARIANTS

        intact, h = variant("intact", root)
        rows = [intact] + [variant(name, root, *spec)[0] for name, *spec in knockouts()]
        if variant("intact-rerun", root)[0]["results"] != intact["results"]:
            raise SystemExit("the intact harness no longer reproduces its first run: a patch was not restored")
    finally:
        shutil.rmtree(root, ignore_errors=True)
    corpus = next(b["config"]["corpus"] for b in h.profile.bundles if b["plugin"] == "taochronos.plugins.classics")
    doc = {"generated_by": "paper/figures/mutation_matrix.py",
           "corpus": f"demonstration corpus ({corpus}, {len(h.corpus)} passages)",
           "profile": f"{h.profile.name} ({h.profile.routing.get('default_provider')})",
           "invariants": [{"id": iid, "probe": probe, "invariant": statement, "boundary": boundary}
                          for iid, probe, statement, boundary, _ in INVARIANTS],
           "variants": rows,
           "intact_rerun_identical": True}
    OUT.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    heads = [r["name"].removeprefix("no_") for r in rows]
    print(f"{len(INVARIANTS)} invariants × {len(rows)} variants (✓ held, ✗ broken, – not exercised)")
    print("     " + "  ".join(heads))
    for i, (iid, *_) in enumerate(INVARIANTS):
        marks = [{True: "✓", False: "✗", None: "–"}[r["results"][i]["held"]] for r in rows]
        print(f"{iid}  " + "  ".join(mark.center(len(head)) for mark, head in zip(marks, heads)))
    for r in rows:
        errors = [x["id"] for x in r["results"] if x["observed"].startswith("probe error:")]
        target = f"target {r['target']} {'broken' if r['target'] in r['broken'] else 'HELD'}; " if r["target"] else ""
        print(f"{r['name']:20} {r['held']}/{len(INVARIANTS) - len(r['not_exercised'])} held; {target}off-target broken: "
              f"{r['off_target'] or 'none'}; not exercised: {r['not_exercised'] or 'none'}"
              + (f"; PROBE ERRORS: {errors}" if errors else ""))
    same = len({json.dumps(r["reference_run"], sort_keys=True) for r in rows}) == 1
    print(f"reference run {'identical under every knock-out' if same else 'CHANGED by a knock-out'} · intact re-run identical "
          f"to the first · {len(rows) + 1} runs in {time.perf_counter() - started:.1f} s · wrote {OUT.relative_to(HOME)}")


if __name__ == "__main__":
    main()
