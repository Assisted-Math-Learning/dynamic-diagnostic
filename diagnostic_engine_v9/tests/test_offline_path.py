"""Unit tests for the load-bearing offline-path logic that the integration
harness (offline_validate_artifact.py) exercises end to end but did not protect
with focused regressions: the hard cap, the phase-boundary pause/resume, the
three-pass order, and that the cap trims later operations first. Pure mechanics
(no engine/data) via offline_follow.follow_capped, plus a version-drift guard."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import offline_follow as F


class _Tree:
    def __init__(self, root, nodes, questions):
        self.root, self.nodes, self.questions = root, nodes, questions


def _chain(prefix):
    # base(0) -> base(0) -> backfill(1) -> harvest(2) -> leaf
    nodes = [
        [0, 1, 1, 0],
        [1, 2, 2, 0],
        [2, 3, 3, 1],
        [3, F.LEAF, F.LEAF, 2],
    ]
    return _Tree(0, nodes, [f"{prefix}{i}" for i in range(4)])


def _trees():
    return {op: _chain(op[0]) for op in F.DEFAULT_OPS}


def _ans_correct(qid, op):
    return True, (op, qid)


def test_hard_cap_never_exceeds_budget():
    trees = _trees()
    for budget in [0, 1, 3, 8, 9, 12, 16, 100]:
        out, qc = F.follow_capped(trees, budget, _ans_correct)
        assert qc <= budget, f"budget {budget}: showed {qc}"
        assert len(out) == qc
    # full session (4 ops x 4 nodes) tops out at 16 regardless of a larger budget
    _, qc = F.follow_capped(trees, 100, _ans_correct)
    assert qc == 16


def test_three_pass_order():
    trees = _trees()
    qid_phase = {t.questions[n[0]]: n[3] for t in trees.values() for n in t.nodes}
    shown = []
    F.follow_capped(trees, 100, lambda qid, op: (True, shown.append(qid_phase[qid])))
    # phases are non-decreasing across the whole session: all base, then backfill, then harvest
    assert shown == sorted(shown)
    assert shown[:8] == [0] * 8        # every operation's base before any backfill
    assert shown[8:12] == [1] * 4      # all backfill before any harvest
    assert shown[12:] == [2] * 4


def test_phase_boundary_pause_resume():
    trees = _trees()
    order = []
    F.follow_capped(trees, 100, lambda qid, op: (True, order.append((op, qid))))
    # Addition resumes across passes in the right place: base a0,a1 -> backfill a2 -> harvest a3
    add = [q for o, q in order if o == "Addition"]
    assert add == ["A0", "A1", "A2", "A3"]
    # the backfill node A2 is shown only after every operation's base questions
    assert "A2" not in [q for _, q in order[:8]]


def test_cap_trims_later_operations_first():
    trees = _trees()
    order = []
    # 8 base + 1 -> only Addition's backfill fits; Division never reaches harvest
    out, qc = F.follow_capped(trees, 9, lambda qid, op: (True, order.append((op, qid))))
    assert qc == 9
    assert ("Division", "D3") not in order and ("Multiplication", "M3") not in order
    assert ("Addition", "A2") in order   # earliest backfill is the first thing past base


def test_serializer_version_not_drifted():
    # the serializer must read the real engine version, not a literal.
    # import offline_serialize first: its import chain puts the engine on sys.path.
    import offline_serialize
    import engine
    assert offline_serialize.ENGINE_VERSION == engine.__version__
