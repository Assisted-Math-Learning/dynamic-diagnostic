"""Validate the SERIALIZED artifact (not the in-memory builder). Deserialize each
grade's diagnostic_offline_trees document, follow it with the base-first capped
follow, score from history, and confirm it reproduces the harness results:
cap correctness (over-budget = 0), session length within budget, misconception
below-target ~0, residual gap, and determinism (deserialized tree vs engine).
Usage: python offline_validate_artifact.py <grade[,grade...]>
"""
import os
import sys, json, gzip, random, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_tree_gen as G, offline_tree_perop as P
from offline_scorer import score_history, full_params
from offline_followsim import (base_first_follow, by_op_uncertain, run_online,
                               BUDGET, OPS, N, TENANT)
from measure_allowance import determinism

ART = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifact", "Delhi")


class TreeView:
    """Minimal builder-like view over a deserialized tree for follow/determinism."""
    def __init__(self, t):
        self.root = t["root"]; self.questions = t["questions"]; self.nodes = t["nodes"]


def load_artifact(grade):
    with gzip.open(f"{ART}/g{grade}.json.gz", "rb") as f:
        return json.loads(f.read())


def main(grades):
    cfg, lattice, pool, fps = G.load()
    for grade in grades:
        doc = load_artifact(grade)
        assert doc["allowance"] == {2: 3, 3: 4, 4: 4, 5: 3}[grade], "allowance mismatch vs locked!"
        params = full_params(cfg, lattice, grade)
        target = cfg.misconception.target; budget = BUDGET[grade]
        s2op = params.skill_to_operation
        applic = pool.applicable_misconceptions(TENANT, grade, params.skills_in_scope)
        trees = {op: TreeView(doc["trees"][op]) for op in OPS}

        seeds = list(range(N))
        masteries = [{s: (random.Random(sd).random() < float(params.priors.get(s, 0.5)))
                      for s in params.skills_in_scope} for sd in seeds]
        # online reference
        on = [run_online(random.Random(2 * sd + 2), masteries[i], pool, cfg, lattice, grade,
                         params, applic, target) for i, sd in enumerate(seeds)]
        on_unc = st.mean(sum(1 for v in sk.values() if v == "uncertain") for sk in on)
        # offline from the DESERIALIZED artifact
        off_unc, qs, bt_all, over = [], [], [], 0
        for i, sd in enumerate(seeds):
            hist, qc = base_first_follow(trees, budget, random.Random(2 * sd + 1),
                                         masteries[i], pool, grade)
            skills, sigs, sess = score_history(hist, cfg, lattice, pool, grade, TENANT, return_session=True)
            off_unc.append(sum(1 for v in skills.values() if v == "uncertain"))
            bt_all.append(sum(1 for m in applic if sess.misconception_asked.get(m, 0) < target))
            qs.append(qc); over += (qc > budget)
        # determinism: deserialized tree vs engine deterministic picks
        det = 0
        for op in OPS:
            b = P.PerOpBuilder(cfg, lattice, pool, grade, op, tenant=TENANT, allowance=doc["allowance"])
            b.nodes = doc["trees"][op]["nodes"]; b.questions = doc["trees"][op]["questions"]
            b.root = doc["trees"][op]["root"]
            det += determinism(b, op, pool, n=150)

        print(f"G{grade} (allow +{doc['allowance']}, budget {budget}): "
              f"gap={st.mean(off_unc)-on_unc:.2f}  below_tgt={st.mean(bt_all):.2f}  "
              f"q_mean={st.mean(qs):.1f} q_max={max(qs)}  over_budget_frac={over/N:.3f}  "
              f"determinism={det}  [provenance calib={doc['provenance']['calibration_fingerprint']}]",
              flush=True)


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1].split(",")])
