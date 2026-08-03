"""Serialize the offline trees to the diagnostic_offline_trees contract
(offline_tree_generator_spec_v3, Sections 9, 10). Per grade: four per-operation
trees (node table + question table, phase tag per node) + a shared per-grade
params block (calibration, priors, lattice, thresholds) + provenance. Delhi,
locked allowances, round3, backfill always on.
Usage: python offline_serialize.py <grade[,grade...]>
"""
import os
import sys, json, gzip, os, hashlib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_tree_gen as G, offline_tree_perop as P
from offline_scorer import full_params
from engine import __version__ as ENGINE_VERSION   # real engine version (no drift)

TENANT = "Delhi"
# Offline-serving compatibility version (mixed-mode spec v11, decision 8). A
# small integer independent of engine_version; the serving guard checks THIS,
# not an exact engine_version match, so a plain engine bump no longer strands
# the trees. Bump only on a tree-format change or a calibration/Bayes/lattice/
# verdict/selection change. Initial value 1 (0.9.0 artifacts carried no field);
# the `items` array added this release is a format change, hence 1.
TREE_COMPAT_VERSION = 1
# Deactivation Failsafe mechanism 3a (spec section 6a): variants switched off at
# build time, excluded from generated trees. Empty here - the bundle has no live
# pool to query; a production build supplies the set. A switched-off change does
# NOT bump TREE_COMPAT_VERSION (decision 8): old trees stay valid, the device skip
# rule handles any switched-off question still in them.
SWITCHED_OFF = frozenset()
ALLOWANCE = {2: 3, 3: 4, 4: 4, 5: 3}          # locked (spec Section 5.2)
OPS = ["Addition", "Subtraction", "Multiplication", "Division"]
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "artifact")
_ALL = "all"


def _fp(path):
    return f"sha256:{hashlib.sha256(open(path, 'rb').read()).hexdigest()[:16]}"


def calib_for(pool, xid, grade):
    item = pool._qxid_to_item[xid]
    rows = pool._item_rows.get(item, {}); row = rows.get(str(grade)) or rows.get(_ALL)
    return {"skill": item.split("|")[1], "slip": row.slip, "guess": row.guess,
            "discrimination": row.discrimination,   # populated; carried for GDINA, DINA uses slip/guess
            "tags": dict(pool.misconceptions_for_item(item) or {})}


def serialize_grade(cfg, lattice, pool, fps, grade):
    params = full_params(cfg, lattice, grade)
    rc = params.routing_config
    trees, all_xids = {}, set()
    for op in OPS:
        b = P.PerOpBuilder(cfg, lattice, pool, grade, op, tenant=TENANT,
                           allowance=ALLOWANCE[grade], switched_off=SWITCHED_OFF).build()
        # items[i] is the item (operand-level key) of questions[i]. The device
        # cannot derive item from calibration (skill only), so the artifact
        # carries it for in-item-space entry-point matching (v11 sections 6, 11).
        items = [pool._qxid_to_item[x] for x in b.questions]
        trees[op] = {"root": b.root, "questions": b.questions, "items": items,
                     "nodes": b.nodes, "allowance": b.allowance, "base_cap": b.base_cap}
        all_xids.update(b.questions)
    calibration = {x: calib_for(pool, x, grade) for x in sorted(all_xids)}
    raw_edges = G.smoke.step_1_load_data(G.PROJECT)[3]
    edges = [{"skill_a": e.skill_a, "skill_b": e.skill_b, "p_b_given_a": e.p_b_given_a,
              "p_b_given_not_a": e.p_b_given_not_a, "weight": e.weight} for e in raw_edges]
    params_block = {
        "calibration": calibration,
        "priors": {s: float(params.priors.get(s, 0.5)) for s in params.skills_in_scope},
        "lattice": edges,
        "thresholds": {"target": cfg.misconception.target,
                       "clear": cfg.misconception.clear_threshold,
                       "present": cfg.misconception.present_threshold,
                       "mastery": rc.mastery_threshold,
                       "not_mastered": rc.not_mastered_threshold},
    }
    doc = {
        "tenant": TENANT, "grade": grade, "engine_version": ENGINE_VERSION,
        "tree_compat_version": TREE_COMPAT_VERSION,
        "allowance": ALLOWANCE[grade], "budget": rc.total_budget,
        "provenance": {
            "lattice_version": fps["lattice"],
            "priors_version": _fp(G.PROJECT / "priors_table_delhi_only.csv"),
            "anchors_version": _fp(G.PROJECT / "anchor_recommendations_v3.xlsx"),
            "calibration_fingerprint": fps["question_parameters"],
            "lookup_fingerprint": fps["lookup"], "retired_fingerprint": fps["retired"],
            "tenant": TENANT},
        "params": params_block,
        "trees": {op: {k: trees[op][k] for k in ("root", "questions", "items", "nodes")}
                  for op in OPS},
    }
    return doc, trees


def packed_size(doc):
    """Alternative size: phase as a separate byte array instead of inline 4th field."""
    d = json.loads(json.dumps(doc))
    blob = bytearray()
    for op in OPS:
        nodes = d["trees"][op]["nodes"]
        d["trees"][op]["nodes"] = [n[:3] for n in nodes]
        blob += bytes(n[3] for n in nodes)
    return len(gzip.compress(json.dumps(d).encode() + b"|PHASES|" + bytes(blob), 9))


def main(grades):
    cfg, lattice, pool, fps = G.load()
    os.makedirs(f"{OUT}/{TENANT}", exist_ok=True)
    for grade in grades:
        doc, _ = serialize_grade(cfg, lattice, pool, fps, grade)
        blob = json.dumps(doc).encode()
        gz = gzip.compress(blob, 9)
        path = f"{OUT}/{TENANT}/g{grade}.json.gz"
        with open(path, "wb") as f:
            f.write(gz)
        nodes = sum(len(doc["trees"][op]["nodes"]) for op in OPS)
        print(f"G{grade} allow=+{ALLOWANCE[grade]}: nodes={nodes:,} calib_q={len(doc['params']['calibration'])} "
              f"inline={len(gz)/1024/1024:.2f}MB packed={packed_size(doc)/1024/1024:.2f}MB -> {path}", flush=True)


if __name__ == "__main__":
    main([int(x) for x in sys.argv[1].split(",")])
