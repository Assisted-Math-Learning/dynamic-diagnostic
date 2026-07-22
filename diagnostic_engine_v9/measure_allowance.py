"""Open point 4 re-measurement WITH the always-on Section 6a misconception
backfill in the trees. Per grade/allowance: combined gzipped size, residual
skill gap vs online, below-target misconceptions (acceptance test), misc-unsure,
offline questions, determinism. Delhi, round3, shipped config. Past the base cap
the order mirrors online: Phase-2 backfill to target, then Phase-3 harvest to allowance.
Usage: python measure_allowance.py <grade> <lvl,lvl,...>"""
import os
import sys, json, gzip, random, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_tree_gen as G, offline_tree_perop as P
from offline_scorer import score_history, full_params
from offline_efficiency_gap import resolve, respond
from engine.session import start_session, record_response, compute_verdicts
from engine.coverage import select_next_coverage
from engine.api.routes import _pick_question_and_stash, _stash_resolved
from engine.misconception import derive_misconception_signals, SIGNAL_UNSURE

TENANT = "Delhi"; N = 300; OPS = ["Addition", "Subtraction", "Multiplication", "Division"]


def metrics(skills, sigs, asked, applicable, target):
    unc = sum(1 for v in skills.values() if v == "uncertain")
    below = sum(1 for m in applicable if asked.get(m, 0) < target)
    unsure = sum(1 for v in sigs.values() if v == SIGNAL_UNSURE)
    return unc, below, unsure


def run_offline(rng, mastery, trees, pool, cfg, lattice, grade, applicable, target):
    steps = []
    for op, b in trees.items():
        node = b.root
        while node != P.LEAF and node is not None:
            qid = b.questions[b.nodes[node][0]]
            sk, slip, guess, tags = resolve(pool, qid, grade)
            ok = respond(rng, mastery, sk, slip, guess)
            steps.append((qid, sk, ok, slip, guess, tags))
            node = b.nodes[node][1] if ok else b.nodes[node][2]
    skills, sigs, s = score_history(steps, cfg, lattice, pool, grade, TENANT, return_session=True)
    return metrics(skills, sigs, s.misconception_asked, applicable, target), len(steps)


def run_online(rng, mastery, pool, cfg, lattice, grade, params, applicable, target):
    res = start_session(sub_session_id="o", learner_id="l", tenant_id=TENANT, class_id="c",
                        grade=grade, engine_version="o", params=params)
    s = res.session
    s.misconception_applicable = applicable
    if res.first_question is not None:
        _pick_question_and_stash(res.first_question, s, pool, grade=grade, tenant_id=TENANT)
    nq = 0
    while s.pending_question_id is not None:
        sk, slip, guess = (s.pending_question_skill_id, s.pending_question_slip_override,
                           s.pending_question_guess_override)
        ok = respond(rng, mastery, sk, slip, guess); nq += 1
        record_response(s, skill_id=sk, question_id=s.pending_question_id, is_correct=ok,
                        params=params, slip_override=slip, guess_override=guess, defer_next=True)
        nxt = select_next_coverage(s, params, pool)
        if nxt is None:
            break
        skp, pick = nxt; _stash_resolved(s, skp, pick)
    skills = {v.skill_id: v.confidence_label.value for v in compute_verdicts(s, params=params)}
    sigs = {x.misconception: x.state for x in derive_misconception_signals(
        s, misconception_target=target, clear_threshold=cfg.misconception.clear_threshold,
        present_threshold=cfg.misconception.present_threshold)}
    return metrics(skills, sigs, s.misconception_asked, applicable, target), nq


def determinism(b, op, pool, n=200):
    rng = random.Random(0); mism = 0
    for _ in range(n):
        res = start_session(sub_session_id="d", learner_id="d", tenant_id=TENANT, class_id="c",
                            grade=b.grade, engine_version="d", params=b.params)
        s = res.session; s.misconception_applicable = b.applicable; s._hv = 0
        if res.first_question is not None:
            _pick_question_and_stash(res.first_question, s, pool, grade=b.grade, tenant_id=TENANT)
        node = b.root
        while node != P.LEAF and s.pending_question_id is not None:
            if b.questions[b.nodes[node][0]] != s.pending_question_id:
                mism += 1; break
            c = rng.random() < 0.5
            record_response(s, skill_id=s.pending_question_skill_id, question_id=s.pending_question_id,
                            is_correct=c, params=b.params, defer_next=True)
            node = b.nodes[node][1] if c else b.nodes[node][2]
            qpo = s.questions_per_operation.get(op, 0)
            hv = getattr(s, "_hv", 0)
            if qpo < b.base_cap:
                nxt = select_next_coverage(s, b.params, pool); done = nxt is None
            else:
                needed = {m for m in b.applicable if s.misconception_asked.get(m, 0) < b.target}
                if needed:
                    nxt = pool.backfill_pick(tenant_id=s.tenant_id, grade=b.grade,
                                             skills_in_scope=b.params.skills_in_scope,
                                             session=s, needed=needed); done = nxt is None
                elif hv < b.allowance:
                    nxt = b._phase3_pick(s); done = nxt is None
                    if not done:
                        s._hv = hv + 1
                else:
                    done = True; nxt = None
            if not done and nxt is not None:
                sk, pk = nxt; _stash_resolved(s, sk, pk)
            if (node == P.LEAF) != done:
                mism += 1; break
    return mism


def main(grade, levels):
    cfg, lattice, pool, fps = G.load()
    params = full_params(cfg, lattice, grade)
    target = cfg.misconception.target
    applicable = pool.applicable_misconceptions(TENANT, grade, params.skills_in_scope)
    seeds = list(range(N))
    masteries = [{s: (random.Random(sd).random() < float(params.priors.get(s, 0.5)))
                  for s in params.skills_in_scope} for sd in seeds]
    on = [run_online(random.Random(2 * sd + 2), masteries[i], pool, cfg, lattice, grade,
                     params, applicable, target) for i, sd in enumerate(seeds)]
    on_unc = st.mean(m[0][0] for m in on); on_bt = st.mean(m[0][1] for m in on)
    on_us = st.mean(m[0][2] for m in on); on_q = st.mean(m[1] for m in on)
    print(f"\n=== G{grade}  (online ref: uncertain={on_unc:.2f} below_target={on_bt:.2f} "
          f"misc_unsure={on_us:.2f} questions={on_q:.1f}; {len(params.skills_in_scope)} skills, "
          f"{len(applicable)} applicable misc, budget {params.routing_config.total_budget}) ===")
    print("lvl | gz_MB  | skill_gap | below_tgt | misc_unsure | off_q  | determ")
    for lvl in levels:
        trees = {op: P.PerOpBuilder(cfg, lattice, pool, grade, op, tenant=TENANT, allowance=lvl).build()
                 for op in OPS}
        gz = sum(len(gzip.compress(json.dumps(b.serialize()).encode(), 9)) for b in trees.values()) / 1024
        mism = sum(determinism(b, op, pool) for op, b in trees.items())
        off = [run_offline(random.Random(2 * sd + 1), masteries[i], trees, pool, cfg, lattice,
                           grade, applicable, target) for i, sd in enumerate(seeds)]
        ou = st.mean(m[0][0] for m in off); bt = st.mean(m[0][1] for m in off)
        us = st.mean(m[0][2] for m in off); oq = st.mean(m[1] for m in off)
        print(f" +{lvl} | {gz/1024:5.2f}  |   {ou-on_unc:5.2f}   |   {bt:5.2f}   |    {us:5.2f}    "
              f"| {oq:5.1f}  |  {mism}")


if __name__ == "__main__":
    grade = int(sys.argv[1]); levels = [int(x) for x in sys.argv[2].split(",")]
    main(grade, levels)
