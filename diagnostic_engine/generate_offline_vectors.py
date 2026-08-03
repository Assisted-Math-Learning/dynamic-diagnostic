"""Generate shared offline-walk test vectors (mixed-mode v11 decision 10).

The device's offline walk is an independent TypeScript port; these vectors bind
it to this Python reference (`offline_follow.follow_capped`) so the two cannot
drift. Vectors are generated from the SHIPPED artifacts (the exact trees the
device downloads), so the port - loading the same artifacts - sees identical
question_x_ids. The walk is deterministic; each pattern fixes the answer to every
question (an explicit map, or a `default_answer` for the uniform all-correct /
all-wrong patterns), so there is no randomness to replicate.

Coverage: to pin the port across MANY tree paths (not one branch per grade),
each grade carries several answer PATTERNS - all-correct (every on_correct
branch), all-wrong (every on_incorrect branch), and seeded mixes - and each
pattern has a fresh case (empty history) and a resumed case (first K items
pre-answered, so the walk routes past them and spends the remaining budget).

Run: `python generate_offline_vectors.py` (writes vectors/offline_walk_vectors.json).
`tests/test_offline_vectors.py` re-runs the reference against the file.
"""
import gzip
import json
import os
import random

from offline_follow import DEFAULT_OPS, follow_capped

HERE = os.path.dirname(os.path.abspath(__file__))
ARTIFACT = os.path.join(HERE, "artifact", "Delhi")
SEED = 20260722


class _ArtifactTree:
    """Adapter exposing .root/.questions/.nodes (+ .items) from a shipped tree."""
    def __init__(self, d):
        self.root = d["root"]
        self.questions = d["questions"]
        self.items = d["items"]
        self.nodes = d["nodes"]


def _load_grade(grade):
    doc = json.loads(gzip.open(os.path.join(ARTIFACT, f"g{grade}.json.gz"), "rb").read())
    trees = {op: _ArtifactTree(doc["trees"][op]) for op in DEFAULT_OPS}
    items = {op: trees[op].items for op in DEFAULT_OPS}
    return doc["budget"], doc["tree_compat_version"], trees, items


def _all_qids(trees):
    out = []
    for op in DEFAULT_OPS:
        out.extend(trees[op].questions)
    return out


def _walk(trees, budget, answer_of, items=None, answered=None, unavailable=None):
    seq = []

    def answer_fn(qid, op):
        seq.append(qid)
        return answer_of(qid), qid
    follow_capped(trees, budget, answer_fn, answered=answered, items=items,
                  unavailable=unavailable)
    return seq, len(seq)


def _patterns(trees, grade):
    """The answer patterns for one grade: uniform all-correct / all-wrong plus
    two seeded mixes. Uniform patterns use default_answer and an empty map;
    mixes carry an explicit per-question map."""
    pats = [
        {"name": "all_correct", "default_answer": True, "answers": {}},
        {"name": "all_wrong", "default_answer": False, "answers": {}},
    ]
    for tag, salt in (("mix_a", 1), ("mix_b", 2)):
        rng = random.Random(SEED + grade * 10 + salt)
        answers = {qid: (rng.random() < 0.5) for qid in _all_qids(trees)}
        pats.append({"name": f"mix_{tag}", "default_answer": False, "answers": answers})
    return pats


def build():
    doc = {
        "generated_by": "generate_offline_vectors.py against offline_follow.follow_capped",
        "spec": "mixed-mode v11 sections 6-7 (offline walk) + decision 10 (shared vectors)",
        "source": "shipped artifacts artifact/Delhi/g{2,3,4,5}.json.gz",
        "tree_compat_version": 1,
        "op_order": DEFAULT_OPS,
        "answer_lookup": "answer(qid) = answers[qid] if present else default_answer",
        "grades": {},
    }
    for grade in (2, 3, 4, 5):
        budget, tcv, trees, items = _load_grade(grade)
        assert tcv == 1
        item_of = {}
        for op in DEFAULT_OPS:
            for qid, it in zip(trees[op].questions, trees[op].items):
                item_of[qid] = it
        patterns_out = []
        for pat in _patterns(trees, grade):
            answers, default = pat["answers"], pat["default_answer"]

            def answer_of(qid, _a=answers, _d=default):
                return _a.get(qid, _d)

            fresh_seq, fresh_n = _walk(trees, budget, answer_of)
            k = min(8, max(1, len(fresh_seq) // 2))
            seed_items = {item_of[qid]: answer_of(qid) for qid in fresh_seq[:k]}
            resumed_seq, resumed_n = _walk(trees, budget - len(seed_items), answer_of,
                                           items=items, answered=dict(seed_items))
            cases = [
                {"name": "fresh", "initial_answered_items": {}, "unavailable": [],
                 "expected_sequence": fresh_seq, "expected_count": fresh_n},
                {"name": f"resumed_prefix{k}", "initial_answered_items": seed_items,
                 "unavailable": [],
                 "expected_sequence": resumed_seq, "expected_count": resumed_n},
            ]
            if pat["name"] == "all_correct" and fresh_seq:
                # Section 6b (device skip-and-do-not-record): the fresh walk's
                # first question is unavailable on the device -> skipped (nothing
                # recorded), on-incorrect followed. Its id must not appear.
                unavail = [fresh_seq[0]]
                u_seq, u_n = _walk(trees, budget, answer_of, unavailable=set(unavail))
                cases.append({"name": "unavailable_skip", "initial_answered_items": {},
                              "unavailable": unavail,
                              "expected_sequence": u_seq, "expected_count": u_n})
            patterns_out.append({
                "name": pat["name"],
                "default_answer": default,
                "answers": answers,
                "cases": cases,
            })
        doc["grades"][str(grade)] = {"budget": budget, "patterns": patterns_out}
    return doc


def main():
    out_dir = os.path.join(HERE, "vectors")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "offline_walk_vectors.json")
    doc = build()
    with open(path, "w") as fh:
        json.dump(doc, fh, indent=1, sort_keys=True)
    n = sum(len(p["cases"]) for g in doc["grades"].values() for p in g["patterns"])
    print(f"wrote {n} vectors ({len(doc['grades'])} grades x "
          f"{len(next(iter(doc['grades'].values()))['patterns'])} patterns x 2 cases) -> {path}")


if __name__ == "__main__":
    main()
