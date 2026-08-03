"""Offline efficiency gap (spec 13.6): how many MORE skills end uncertain under
offline-only per-operation sequencing (each op to its base cap, no cross-op
harvest) versus the full online engine (reserve + Phase-3 harvest), over a
simulated learner sample. Sizes open point 4 (whether a per-op reserve is worth
adding). Scoring is identical for both (history-based); only the question
sequence differs."""
import os
import sys, random, statistics as st
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import offline_tree_gen as G, offline_tree_perop as P
from offline_scorer import score_history, full_params
from engine.session import start_session, record_response, compute_verdicts
from engine.coverage import select_next_coverage
from engine.api.routes import _pick_question_and_stash, _stash_resolved

_ALL = "all"
TENANT = "Delhi"

def resolve(pool, qid, grade):
    item = pool._qxid_to_item[qid]; skill = item.split("|")[1]
    rows = pool._item_rows.get(item, {}); row = rows.get(str(grade)) or rows.get(_ALL)
    return skill, row.slip, row.guess, (pool.misconceptions_for_item(item) or {})

def uncertain(m):  # skills MainD must re-diagnose
    return sum(1 for v in m.values() if v == "uncertain")

def respond(rng, mastery, skill, slip, guess):
    return rng.random() < ((1 - slip) if mastery.get(skill, False) else guess)

def run_offline(rng, mastery, trees, pool, cfg, lattice, grade):
    steps = []
    for op, b in trees.items():
        node = b.root
        while node != P.LEAF and node is not None:
            qid = b.questions[b.nodes[node][0]]
            sk, slip, guess, tags = resolve(pool, qid, grade)
            ok = respond(rng, mastery, sk, slip, guess)
            steps.append((qid, sk, ok, slip, guess, tags))
            node = b.nodes[node][1] if ok else b.nodes[node][2]
    sk_map, _ = score_history(steps, cfg, lattice, pool, grade, TENANT)
    return uncertain(sk_map), len(steps)

def run_online(rng, mastery, pool, cfg, lattice, grade, params):
    res = start_session(sub_session_id="o", learner_id="l", tenant_id=TENANT, class_id="c",
                        grade=grade, engine_version="o", params=params)
    s = res.session
    s.misconception_applicable = pool.applicable_misconceptions(TENANT, grade, params.skills_in_scope)
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
    sk_map = {v.skill_id: v.confidence_label.value for v in compute_verdicts(s, params=params)}
    return uncertain(sk_map), nq

if __name__ == "__main__":
    cfg, lattice, pool, fps = G.load()
    grade = 5; N = 300
    params = full_params(cfg, lattice, grade)
    trees = {op: P.PerOpBuilder(cfg, lattice, pool, grade, op, tenant=TENANT).build()
             for op in ["Addition", "Subtraction", "Multiplication", "Division"]}
    off_u, on_u, off_q, on_q, gaps = [], [], [], [], []
    for seed in range(N):
        mastery = {s: (random.Random(seed).random() < float(params.priors.get(s, 0.5)))
                   for s in params.skills_in_scope}
        ou, oq = run_offline(random.Random(2 * seed + 1), mastery, trees, pool, cfg, lattice, grade)
        nu, nq = run_online(random.Random(2 * seed + 2), mastery, pool, cfg, lattice, grade, params)
        off_u.append(ou); on_u.append(nu); off_q.append(oq); on_q.append(nq); gaps.append(ou - nu)
    print(f"G{grade}, N={N}, {len(params.skills_in_scope)} skills in scope")
    print(f"  online : uncertain mean={st.mean(on_u):.2f} (sd {st.pstdev(on_u):.2f})  "
          f"questions mean={st.mean(on_q):.1f}")
    print(f"  offline: uncertain mean={st.mean(off_u):.2f} (sd {st.pstdev(off_u):.2f})  "
          f"questions mean={st.mean(off_q):.1f}")
    print(f"  extra uncertain skills offline (gap): mean={st.mean(gaps):.2f}  "
          f"median={st.median(gaps):.0f}  max={max(gaps)}")
    print(f"  sessions where offline left MORE uncertain: {sum(1 for g in gaps if g > 0)}/{N}")
