"""Pure mechanics of the base-first, three-pass capped follow
(offline_tree_generator_spec_v3, Section 8.1), with no engine/data dependency so
it can be unit-tested in isolation. The answer model and scoring live in the
callers (offline_followsim, the device). A `tree` is any object exposing
`.root` (int), `.questions` (list[x_id]), and `.nodes` (list of
[q_index, on_correct, on_incorrect, phase]); leaf child = -1; phase 0/1/2.
"""
LEAF = -1
DEFAULT_OPS = ["Addition", "Subtraction", "Multiplication", "Division"]


def follow_capped(trees, budget, answer_fn, op_order=DEFAULT_OPS):
    """Three passes (base, backfill, harvest), each across operations in fixed
    order, with a global counter that hard-stops at `budget`. Resuming an
    operation on a later pass continues from the node where the previous pass
    paused (the phase boundary). `answer_fn(qid, op) -> (is_correct, payload)`;
    returns (list_of_payloads_in_show_order, question_count). question_count
    never exceeds budget (the hard cap)."""
    state = {op: {"node": trees[op].root} for op in op_order}
    out = []
    counter = 0
    for pass_phase in (0, 1, 2):
        for op in op_order:
            b = trees[op]
            node = state[op]["node"]
            while node != LEAF and node is not None:
                if b.nodes[node][3] != pass_phase:
                    break                                  # phase boundary -> pause for a later pass
                if counter >= budget:                      # hard cap (increment + compare, no compute)
                    state[op]["node"] = node
                    return out, counter
                qid = b.questions[b.nodes[node][0]]
                is_correct, payload = answer_fn(qid, op)
                out.append(payload)
                counter += 1
                node = b.nodes[node][1] if is_correct else b.nodes[node][2]
            state[op]["node"] = node
    return out, counter
