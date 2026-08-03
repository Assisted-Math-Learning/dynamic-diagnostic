"""Per-operation offline sequencing-tree generator
(offline_tree_generator_spec_v2, Section 13).

Drives the real engine in deterministic mode RESTRICTED TO ONE OPERATION
(operation_order = [op], skills_in_scope = that op's skills), walks both answer
outcomes, dedups on the 2-decimal posterior sequencing key, depth-bounded at the
per-operation base cap (6/9/13/16). Nodes carry sequencing only -- {question_id,
skill_id, on_correct, on_incorrect}; leaves are bare terminals. Verdicts and
misconception counts are NOT in the tree (history-based scoring, Section 7).

The single-operation restriction is the only new mechanism vs the validated walk.
"""
from __future__ import annotations
import os
import sys, json, gzip, time, dataclasses
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import offline_tree_gen as G   # reuse load(), _clone(), state_key()
from engine.session import start_session, record_response
from engine.coverage import (select_next_coverage, select_leftover_skill,
                             _is_resolved, _resolve_choice, _routing_state)
from engine.api.routes import _pick_question_and_stash, _stash_resolved

LEAF = -1


def perop_params(cfg, lattice, grade, op):
    """EngineParams restricted to one operation: scope = op's skills, order = [op].
    Reserve kept as shipped (extra already 0); the walk is depth-bounded at the
    base per-op cap, so Phase-2/3 harvest beyond the cap is never reached."""
    full = cfg.get_engine_params(grade, lattice)
    op_skills = [s for s in full.skills_in_scope if full.skill_to_operation.get(s) == op]
    rc = dataclasses.replace(full.routing_config, operation_order=[op])
    params = dataclasses.replace(full, skills_in_scope=op_skills, routing_config=rc)
    return params, op_skills, full.routing_config.per_operation_budget


class PerOpBuilder:
    def __init__(self, cfg, lattice, pool, grade, op, tenant="Delhi", posterior_mode="round3",
                 allowance=0, backfill=True, switched_off=None):
        self.cfg, self.lattice, self.pool, self.grade, self.op = cfg, lattice, pool, grade, op
        self.tenant = tenant
        self.posterior_mode = posterior_mode
        self.allowance = allowance
        self.backfill = backfill
        # Deactivation Failsafe mechanism 3a (spec section 6a): variants switched
        # off at build time are excluded from the tree. Fed to the same candidate
        # filter as the retired list via the synthetic session below; the walk's
        # every pick then skips them and an item with no usable variant is not
        # placed. Constant for the build, so sharing it across clones is safe and
        # it does not enter the memo state key. Empty by default (the bundle has
        # no live pool to query; the set is supplied by the caller/service).
        self.switched_off = set(switched_off or ())
        self.params, self.op_skills, self.base_cap = perop_params(cfg, lattice, grade, op)
        self.target = cfg.misconception.target
        self.applicable = pool.applicable_misconceptions(tenant, grade, self.op_skills)
        self.memo = {}            # state-key -> node id
        self.nodes = []           # id -> [q_index, on_correct, on_incorrect]
        self.q_index = {}         # x_id -> index
        self.questions = []       # index -> x_id
        self.leaf_id = None       # single shared terminal

    def _qidx(self, xid):
        if xid not in self.q_index:
            self.q_index[xid] = len(self.questions)
            self.questions.append(xid)
        return self.q_index[xid]

    def _terminal(self):
        if self.leaf_id is None:
            self.leaf_id = LEAF
        return LEAF

    def _phase3_pick(self, session):
        """Engine's own Phase-3 skill-harvest pick (no Phase-2 / no misconception
        backfill): most-uncertain in-scope skill, info-gain among unsure, caps
        lifted. Returns None when no skill is still uncertain -> branch ends early."""
        state = _routing_state(session, self.params)
        unsure = [s for s in self.params.skills_in_scope
                  if not _is_resolved(session.posteriors[s], self.params)]
        while unsure:
            choice = select_leftover_skill(state, self.params.routing_config,
                                           self.params.lattice_index, unsure)
            if choice is None:
                return None
            resolved = _resolve_choice(choice, session, self.params, self.pool)
            if resolved is not None:
                return resolved
            unsure = [s for s in unsure if s != choice.skill]
        return None

    def _advance(self, session, is_correct):
        child = G._clone(session)
        record_response(child, skill_id=child.pending_question_skill_id,
                        question_id=child.pending_question_id, is_correct=is_correct,
                        params=self.params, defer_next=True)
        child._hv = getattr(session, "_hv", 0)        # harvest questions used on this path
        qpo = child.questions_per_operation.get(self.op, 0)
        if qpo < self.base_cap:
            nxt = select_next_coverage(child, self.params, self.pool)   # Phase-1 adaptive
            child._phase = 0                                            # base
        else:
            # Past the base cap: Phase-2 misconception backfill to target (always on,
            # Section 6a), THEN Phase-3 skill harvest up to the allowance.
            needed = {m for m in self.applicable
                      if child.misconception_asked.get(m, 0) < self.target} if self.backfill else set()
            if needed:
                nxt = self.pool.backfill_pick(
                    tenant_id=child.tenant_id, grade=self.grade,
                    skills_in_scope=self.params.skills_in_scope, session=child, needed=needed)
                child._phase = 1                                        # backfill
            elif child._hv < self.allowance:
                nxt = self._phase3_pick(child)
                child._phase = 2                                        # harvest
                if nxt is not None:
                    child._hv += 1                    # this child's pending is a harvest question
            else:
                return None
        if nxt is None:
            return None
        sk, pick = nxt
        _stash_resolved(child, sk, pick)
        return child

    def walk(self, session):
        if session.pending_question_id is None:
            return self._terminal()
        key = (G.state_key(session, self.applicable, self.target,
                           posterior_mode=self.posterior_mode, params=self.params),
               getattr(session, "_hv", 0))   # harvest progress distinguishes harvest states
        if key in self.memo:
            return self.memo[key]
        nid = len(self.nodes)
        self.memo[key] = nid
        self.nodes.append(None)   # placeholder (reserve id before recursing)
        qi = self._qidx(session.pending_question_id)
        c = self._advance(session, True)
        i = self._advance(session, False)
        oc = self.walk(c) if c is not None else self._terminal()
        oi = self.walk(i) if i is not None else self._terminal()
        self.nodes[nid] = [qi, oc, oi, getattr(session, "_phase", 0)]
        return nid

    def build(self):
        res = start_session(sub_session_id=f"po-{self.grade}-{self.op}", learner_id="g",
                            tenant_id=self.tenant, class_id="c", grade=self.grade,
                            engine_version="gen", params=self.params)
        s = res.session
        s.misconception_applicable = self.applicable
        s.switched_off_question_x_ids = self.switched_off      # mechanism 3a (build input)
        s._hv = 0
        s._phase = 0   # the anchor question is a base (Phase-1) pick
        if res.first_question is not None:
            _pick_question_and_stash(res.first_question, s, self.pool,
                                     grade=self.grade, tenant_id=self.tenant)
        self.root = self.walk(s)
        return self

    def serialize(self):
        return {"root": self.root, "questions": self.questions, "nodes": self.nodes}


if __name__ == "__main__":
    grade = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    op = sys.argv[2] if len(sys.argv) > 2 else "Addition"
    cfg, lattice, pool, fps = G.load()
    t0 = time.time()
    b = PerOpBuilder(cfg, lattice, pool, grade, op).build()
    dt = time.time() - t0
    blob = json.dumps(b.serialize()).encode()
    gz = gzip.compress(blob, 9)
    print(f"G{grade} {op}: skills={len(b.op_skills)} base_cap={b.base_cap} "
          f"applicable_misc={len(b.applicable)}")
    print(f"  nodes={len(b.nodes):,}  distinct_questions={len(b.questions)}  "
          f"json={len(blob)/1024:.1f}KB  gzipped={len(gz)/1024:.1f}KB  build={dt:.1f}s")
