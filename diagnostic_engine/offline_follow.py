"""Pure mechanics of the base-first, three-pass capped follow
(offline_tree_generator_spec_v3, Section 8.1), with no engine/data dependency so
it can be unit-tested in isolation. The answer model and scoring live in the
callers (offline_followsim, the device). A `tree` is any object exposing
`.root` (int), `.questions` (list[x_id]), and `.nodes` (list of
[q_index, on_correct, on_incorrect, phase]); leaf child = -1; phase 0/1/2.
"""
LEAF = -1
DEFAULT_OPS = ["Addition", "Subtraction", "Multiplication", "Division"]


def follow_capped(trees, budget, answer_fn, op_order=DEFAULT_OPS,
                  answered=None, items=None, unavailable=None):
    """Three passes (base, backfill, harvest), each across operations in fixed
    order, with a global counter that hard-stops at `budget`. Resuming an
    operation on a later pass continues from the node where the previous pass
    paused (the phase boundary). `answer_fn(qid, op) -> (is_correct, payload)`;
    returns (list_of_payloads_in_show_order, question_count). question_count
    never exceeds budget (the hard cap).

    Mixed-mode extension (v11 sections 6-7): pass `answered` (a dict
    item -> is_correct of the UNIFIED history so far, in item space) and `items`
    (a dict op -> list parallel to trees[op].questions giving each question's
    item) to RESUME a walk from an existing history. At each node whose item is
    already answered - in ANY prior segment, online or offline, possibly under a
    different display variant - the walk does NOT re-ask: it routes on the
    recorded answer (this is the replay-to-first-unanswered entry point), and it
    never emits a question whose item is already present (no-repeat in item
    space). `budget` is then the REMAINING unified budget
    (grade_budget - len(history)) and the counter counts only NEW asks. With
    `answered`/`items` omitted this is exactly the fresh base-first walk, so
    existing callers are unaffected."""
    answered = dict(answered) if answered else {}
    state = {op: {"node": trees[op].root} for op in op_order}
    out = []
    counter = 0
    for pass_phase in (0, 1, 2):
        for op in op_order:
            b = trees[op]
            item_list = items[op] if items else None
            node = state[op]["node"]
            while node != LEAF and node is not None:
                if b.nodes[node][3] != pass_phase:
                    break                                  # phase boundary -> pause for a later pass
                q_index = b.nodes[node][0]
                item = item_list[q_index] if item_list is not None else None
                qid = b.questions[q_index]
                if item is not None and item in answered:
                    # Already answered (any segment); route past on the recorded
                    # answer without re-asking. Not a new ask -> not counted.
                    node = b.nodes[node][1] if answered[item] else b.nodes[node][2]
                    continue
                if unavailable is not None and qid in unavailable:
                    # Deactivation Failsafe mechanism 3b (spec section 6b): the
                    # device cannot present this question (switched off in device
                    # content, or a missing asset). Skip it - display nothing,
                    # record nothing, spend no budget - and follow the on-incorrect
                    # branch (under-placement, never over-placement).
                    node = b.nodes[node][2]
                    continue
                if counter >= budget:                      # hard cap (increment + compare, no compute)
                    state[op]["node"] = node
                    return out, counter
                is_correct, payload = answer_fn(qid, op)
                out.append(payload)
                counter += 1
                if item is not None:
                    answered[item] = is_correct            # so later nodes see it (no-repeat)
                node = b.nodes[node][1] if is_correct else b.nodes[node][2]
            state[op]["node"] = node
    return out, counter
