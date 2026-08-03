"""
AML misconception engine: dispatch + eligibility-by-probing.

Eligibility for a code on a question = "could this code appear in the ranked
list for SOME response, given the operands". Computed by feeding the classifier
a constructed probe set and taking the union of every code that appears. The
classifier is deterministic, so this asks the rules themselves rather than
re-deriving them. Completeness is guaranteed empirically by validate_eligibility.py
(every code that fires on real responses must be in the eligible set).
"""
import addition, subtraction, multiplication, division

_MODS = {
    "addition": addition, "subtraction": subtraction,
    "multiplication": multiplication, "division": division,
}
_ALIASES = {
    "addition": "addition", "add": "addition", "+": "addition",
    "subtraction": "subtraction", "sub": "subtraction", "-": "subtraction",
    "multiplication": "multiplication", "mul": "multiplication",
    "mult": "multiplication", "x": "multiplication", "*": "multiplication",
    "division": "division", "div": "division", "/": "division",
}

def norm_op(op):
    return _ALIASES.get(str(op).strip().lower())

def classify_one(op, n1, n2, response, learner_grade=None,
                 system_expects_remainder=None, return_debug=False):
    """Route to the right module. Returns ClassifyResult."""
    o = norm_op(op)
    if o is None:
        raise ValueError(f"unknown operation: {op!r}")
    mod = _MODS[o]
    if o == "division":
        return mod.classify(n1, n2, response, learner_grade,
                            system_expects_remainder=system_expects_remainder,
                            return_debug=return_debug)
    return mod.classify(n1, n2, response, learner_grade, return_debug=return_debug)

# ---------------------------------------------------------------------------
# Probe generation
# ---------------------------------------------------------------------------
INVALID_PROBES = ["-1", "-5", "-99", "abc", "", " ", "?", "x", "1.5", "1/2", -5]

def _digits(n):
    return [int(c) for c in str(abs(int(n)))]

def _harvest_debug(o, n1, n2, sysrem):
    """Run one valid-wrong probe with debug on and pull every int / int-collection."""
    vals = set()
    try:
        if o == "division":
            res = _MODS[o].classify(n1, n2, 1, system_expects_remainder=sysrem,
                                    return_debug=True)
        else:
            res = _MODS[o].classify(n1, n2, 1, return_debug=True)
    except Exception:
        return vals
    for v in res.debug.values():
        if isinstance(v, bool):
            continue
        if isinstance(v, int):
            vals.add(v)
        elif isinstance(v, (set, list, tuple)):
            for x in v:
                if isinstance(x, int) and not isinstance(x, bool):
                    vals.add(x)
    return vals

def make_probes(o, n1, n2, sysrem=None, mult_window=25):
    """Return a set of probe responses (strings) for one question.

    mult_window: the dense-window half-width for multiplication when BOTH
    operands are multi-digit (the ~50ms-per-probe path). "fast" tagging uses
    25, "regular" uses 200.
    """
    probes = set()
    for p in INVALID_PROBES:
        probes.add(str(p))

    # numeric correct + structural candidates
    if o == "division":
        correct = n1 // n2 if n2 else 0
        rem = n1 % n2 if n2 else 0
    elif o == "addition":
        correct = n1 + n2
    elif o == "subtraction":
        correct = n1 - n2
    else:
        correct = n1 * n2

    cands = set()
    cands.update([n1, n2, n1 + n2, abs(n1 - n2), n1 * n2, correct])
    if n2:
        cands.update([n1 // n2, n1 % n2])
    # concat / reversal
    try:
        cands.add(int(str(n1) + str(n2)))
        cands.add(int(str(n2) + str(n1)))
    except ValueError:
        pass
    for base in (correct, n1, n2):
        s = str(abs(base))[::-1]
        if s:
            cands.add(int(s))
    # +/- powers of ten and small multiples
    L = len(str(abs(correct))) + 2
    for k in range(L):
        p = 10 ** k
        cands.update([correct + p, correct - p, correct + 2 * p])
    # digit substitution / drop / duplicate on correct
    cs = str(abs(correct))
    for i in range(len(cs)):
        for d in "0123456789":
            cands.add(int(cs[:i] + d + cs[i + 1:]))
        cands.add(int((cs[:i] + cs[i + 1:]) or "0"))
        cands.add(int(cs[:i] + cs[i] + cs[i:]))
    # column-wise constructions in BOTH orders (units-first and most-sig-first)
    da, db = _digits(n1), _digits(n2)
    w = max(len(da), len(db))
    da = [0] * (w - len(da)) + da
    db = [0] * (w - len(db)) + db
    pairs_msf = list(zip(da, db))
    for seq in (pairs_msf, list(reversed(pairs_msf))):
        for builder in (
            "".join(str((x + y) % 10) for x, y in seq),
            "".join(str(x + y) for x, y in seq),
            "".join(str(abs(x - y)) for x, y in seq),
            "".join(str(x * y) for x, y in seq),
        ):
            if builder:
                cands.add(int(builder))
    # single digit / single column of correct alone
    for ch in str(abs(correct)):
        cands.add(int(ch))
    for x, y in pairs_msf:
        cands.update([x + y, abs(x - y), x * y, (x + y) % 10])
    # multiplication-specific structural probes (partial products)
    if o == "multiplication":
        for d in _digits(n2):
            cands.add(n1 * d)
        for d in _digits(n1):
            cands.add(n2 * d)
        for x in _digits(n1):
            for y in _digits(n2):
                cands.add(x * y)
        cands.add(sum(n1 * d for d in _digits(n2)))
        pp = "".join(str(n1 * d) for d in _digits(n2))
        if pp:
            cands.add(int(pp))
    # bounded dense window near correct. Multiplication: wide only when one
    # operand is single-digit (fast path); tight when both multi-digit (50ms/probe).
    if o == "multiplication":
        W = 300 if min(n1, n2) <= 9 else mult_window
    else:
        W = 200
    cands.update(range(max(0, correct - W), correct + W + 1))
    # harvested module candidates
    cands.update(_harvest_debug(o, n1, n2, sysrem))

    for v in cands:
        if isinstance(v, int) and v >= 0:
            probes.add(str(v))

    # division: Q R r string variants
    if o == "division":
        q, r = correct, rem
        qset = {q, q + 1, q - 1, q + 2, q - 2, r, 0, 1, n1, n2,
                q * 10, q * 100, q * 1000}
        # quotient digit-prefixes (partial/truncated division)
        sq = str(q)
        for i in range(1, len(sq) + 1):
            qset.add(int(sq[:i]))
        rset = set(range(0, min(n2 + 1, 30))) | {r, r + 1, r - 1, n1, n2, q, 0, 1}
        for qq in qset:
            for rr in rset:
                if qq >= 0 and rr >= 0:
                    probes.add(f"{qq} R {rr}")
        # swap / structural
        probes.add(str(q))
        probes.add(f"{n2} R {n1}")
        probes.add(f"{n1} R {n2}")
        probes.add(f"{r} R {q}")
        probes.add(f"{q} R {n2}")
        probes.add(f"{q}{r}")
    return probes

# ---------------------------------------------------------------------------
# Eligibility (cached per question)
# ---------------------------------------------------------------------------
_elig_cache = {}

def eligible_codes(op, n1, n2, system_expects_remainder=None, mult_window=25):
    o = norm_op(op)
    if o is None:
        raise ValueError(f"unknown operation: {op!r}")
    sr = bool(system_expects_remainder) if o == "division" else None
    key = (o, int(n1), int(n2), sr, mult_window if o == "multiplication" else None)
    if key in _elig_cache:
        return _elig_cache[key]
    elig = set()
    for resp in make_probes(o, int(n1), int(n2), system_expects_remainder, mult_window=mult_window):
        try:
            res = classify_one(o, n1, n2, resp,
                               system_expects_remainder=system_expects_remainder)
        except Exception:
            continue
        if res.cascade_code and res.cascade_code != "CORRECT":
            elig.add(res.cascade_code)
        for code, _name, _score in res.ranked:
            if code != "CORRECT":
                elig.add(code)
    _elig_cache[key] = elig
    return elig

# ---------------------------------------------------------------------------
# Code names + RANDOM_OR_INVALID set
# ---------------------------------------------------------------------------
_NAMES = {
    "addition": addition.ADDITION_ERROR_NAMES,
    "subtraction": subtraction.SUBTRACTION_ERROR_NAMES,
    "multiplication": multiplication.MULTIPLICATION_ERROR_NAMES,
    "division": division.DIVISION_ERROR_NAMES,
}
INVALID_CODES = {"A01", "S01", "M01", "D01"}  # RANDOM_OR_INVALID per operation

# Machine-readable module versions (v9 provenance: read from one structured place,
# never parsed from a filename or docstring).
MODULE_VERSIONS = {
    "addition": addition.__version__,
    "subtraction": subtraction.__version__,
    "multiplication": multiplication.__version__,
    "division": division.__version__,
}

def code_name(op, code):
    o = norm_op(op)
    return _NAMES.get(o, {}).get(code, "")
