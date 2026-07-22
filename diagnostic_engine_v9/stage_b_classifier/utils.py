"""
Shared utilities for misconception classifiers across all four operations, v19.18.

These primitives are stateless and pure — safe to call repeatedly with no
caching concerns. Designed for low single-call latency.

Many of these support both "parsed-integer" and "raw-input-string" branches
of detection. Some misconceptions (e.g., A02 INPUT_ORDERING_ERROR with
leading-zero responses, A21 INCOMPLETE_ANSWER_WIDTH leading-drop) are only
detectable when the raw input string is preserved — int parsing drops
leading zeros and loses information.


ARCHITECTURE
------------
This file is the shared toolkit imported by all four operation classifiers:
addition.py, subtraction.py, multiplication.py, division.py.
Each classifier imports the subset of helpers it needs.

Common helpers (used by all):
  * parse_response(), parse_operand(), normalize_raw()
  * digits(), n_digits(), digit_sum()
  * ClassifyResult dataclass, scoring helpers

Operation-specific helpers (used by one classifier each):
  * Addition: column_sums_units_first, carry_dropped_all_variant,
    place_value_permutations, is_digit_permutation_strs, ...
  * Subtraction: long_subtract_simulate, borrow_chain, ...
  * Multiplication: long_multiply_simulate, column_wise_digit_mul,
    digit_concat_*_product, row_concat_digit_mul, ...
  * Division: parse_qr_response (quotient-remainder format), ...

CHANGELOG
---------
v19.18  parse_response: added comma-stripping (matches parse_operand). Without
        this, responses like "2,000" tagged as A01/S01/M01/D01 RANDOM_OR_INVALID
        even when "2,000" was the correct answer with thousands separator.
v19.17  long_multiply_simulate: added step_carry_delta and step_mul_delta
        parameters used by M14/M15 simulation. (Note: known issue --- modular
        arithmetic on negative deltas wraps to single-digit positives, causing
        false-positive matches on 1D x 1D problems. Mitigated in
        the multiplication classifier by adding 1D x 1D guards to the affected rules.)
"""

from typing import Optional


# ---------------------------------------------------------------------------
# Input parsing
# ---------------------------------------------------------------------------

def normalize_raw(raw: object) -> Optional[str]:
    """
    Return a normalized raw input string for raw-branch detection rules.
    Strips whitespace and quote characters but preserves digit content
    including leading zeros.

    Returns None if the raw is None/empty/cannot be a string.
    """
    if raw is None:
        return None
    s = str(raw).strip().strip("'\"")
    return s if s else None


def parse_response(raw: object) -> Optional[int]:
    """
    Parse a learner's raw response into a non-negative integer.

    Returns:
        int: the parsed value, if it is a valid non-negative integer.
        None: if the response is unparseable, contains decimals, contains
              non-digit characters, or is negative. The classifier surfaces
              all such cases as A01 / S01 / M01 / D01 (RANDOM_OR_INVALID).

    v19.18: comma-stripping added, matching parse_operand. Previously
    parse_operand stripped commas (so "2,000" parsed as 2000) but
    parse_response didn't, creating an asymmetry where "2,000-766=1,234"
    (the correct answer) tagged as S01 RANDOM_OR_INVALID.
    """
    s = normalize_raw(raw)
    if s is None:
        return None
    s = s.replace(",", "")
    if not s:
        return None
    if "." in s:
        return None
    if not s.isdigit():
        return None
    try:
        v = int(s)
    except ValueError:
        return None
    return v if v >= 0 else None


def parse_operand(raw: object) -> Optional[int]:
    """
    Parse an operand value (N1 or N2). Same as parse_response, plus
    comma-stripping (e.g., "1,006" → 1006) per the spec's note in A01/A26.
    """
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw if raw >= 0 else None
    s = str(raw).strip().strip("'\"").replace(",", "")
    if not s or "." in s or not s.isdigit():
        return None
    try:
        return int(s)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Digit operations
# ---------------------------------------------------------------------------

def digits(n: int) -> list[int]:
    """Return digits of n in left-to-right order (most-significant first)."""
    return [int(c) for c in str(n)]


def n_digits(n: int) -> int:
    """Number of digits in n. n_digits(0) == 1."""
    return len(str(n))


def wi_column_digits(s: dict, width: int) -> list[str]:
    """
    [v20.0 raw-aware] Return per-column digit characters of the kid's answer,
    LEFT-aligned (MSB first), padded to the requested width.

    Prefers s["digits_raw"] (preserves any leading zeros the kid typed) over
    str(s["wi"]).zfill(...) (which fabricates leading zeros from the int).

    The distinction matters when the kid's raw input has leading zeros — e.g.
    raw="098" for a 3-column problem encodes the kid writing 0 at the
    hundreds position. The parsed wi=98 loses that signal.

    Returns a list of '0'..'9' chars, MSB first, length == width.
    If raw is longer than width, the rightmost `width` digits are returned.
    """
    raw_digits = s.get("digits_raw")
    if raw_digits is not None:
        if len(raw_digits) <= width:
            return ['0'] * (width - len(raw_digits)) + [str(d) for d in raw_digits]
        return [str(d) for d in raw_digits[-width:]]
    wi = s.get("wi")
    if wi is not None:
        return list(str(wi).zfill(width))
    return ['0'] * width


def digit_sum(n: int) -> int:
    """Sum of digits in n."""
    return sum(digits(n))


def concat_int(a: int, b: int) -> int:
    """Integer concatenation of a and b: concat_int(27, 38) == 2738."""
    return int(f"{a}{b}")


def is_digit_permutation_strs(a: str, b: str) -> bool:
    """
    String-level digit permutation check. Both strings must have the same
    length and the same multiset of digit characters.
    Used for A02's raw-branch detection where leading zeros matter.
    """
    return len(a) == len(b) and sorted(a) == sorted(b)


def is_digit_permutation(a: int, b: int) -> bool:
    """
    Integer-level digit permutation check.
    is_digit_permutation(123, 321) -> True
    is_digit_permutation(120, 12) -> False  (different digit multisets — extra zero)
    """
    return is_digit_permutation_strs(str(a), str(b))


# ---------------------------------------------------------------------------
# Column-level operations
# ---------------------------------------------------------------------------

def right_align_digits(n1: int, n2: int) -> tuple[list[int], list[int]]:
    """
    Right-align the digits of n1 and n2 to the same width by left-padding
    with zeros. Returns the padded digit lists in LEFT-TO-RIGHT order
    (most-significant-first).
    """
    width = max(n_digits(n1), n_digits(n2))
    d1 = [int(c) for c in str(n1).zfill(width)]
    d2 = [int(c) for c in str(n2).zfill(width)]
    return d1, d2


def column_sums_units_first(n1: int, n2: int) -> list[int]:
    """
    Per-column digit sums (without carries), units-first.
    column_sums_units_first(64, 18) -> [12, 7]   (4+8=12 in units, 6+1=7 in tens)
    column_sums_units_first(8, 61)  -> [9, 6]
    """
    d1, d2 = right_align_digits(n1, n2)
    # Iterate right-to-left to produce units-first
    return [d1[i] + d2[i] for i in range(len(d1) - 1, -1, -1)]


def carries_units_first(n1: int, n2: int) -> list[int]:
    """
    Carries OUT of each column when adding n1 + n2, units-first.
    carries_units_first(64, 18) -> [1, 0]
    carries_units_first(99, 99) -> [1, 1]

    Returns one entry per column at the operand width.
    """
    cols = column_sums_units_first(n1, n2)
    out = []
    carry_in = 0
    for s in cols:
        total = s + carry_in
        carry_out = 1 if total >= 10 else 0
        out.append(carry_out)
        carry_in = carry_out
    return out


def carries_in_units_first(n1: int, n2: int) -> list[int]:
    """
    Carries INTO each column when adding n1 + n2, units-first.
    Column 0 (units) always has carry-in 0.
    carries_in_units_first(64, 18) -> [0, 1]   (units has 0, tens receives 1)
    """
    outs = carries_units_first(n1, n2)
    return [0] + outs[:-1]


def has_any_carry(n1: int, n2: int) -> bool:
    """True iff adding n1 + n2 produces at least one carry."""
    return any(c > 0 for c in carries_units_first(n1, n2))


def is_no_carry_problem(n1: int, n2: int) -> bool:
    """True iff every column sum < 10 — used by A20 (MULTI_COLUMN_SLIP)."""
    return all(s < 10 for s in column_sums_units_first(n1, n2))


# ---------------------------------------------------------------------------
# Carry-drop variants for A12 (CARRY_IGNORED)
# ---------------------------------------------------------------------------

def carry_dropped_all_variant(n1: int, n2: int) -> Optional[int]:
    """
    A12 Variant A: each column sum mod 10 is written; the LEFTMOST column
    writes its full sum (no place to carry to).
    """
    cs = column_sums_units_first(n1, n2)
    if not cs:
        return None
    digits_units_first: list[int] = []
    for i, s in enumerate(cs):
        if i == len(cs) - 1:
            # leftmost column writes full (possibly 2-digit) sum
            digits_units_first.append(s)
        else:
            digits_units_first.append(s % 10)
    parts = [str(d) for d in reversed(digits_units_first)]
    if not parts:
        return None
    return int("".join(parts))


def carry_dropped_one_variant_candidates(n1: int, n2: int) -> set[int]:
    """
    A12 Variant B: exactly ONE column's carry-OUT is dropped, while all other
    carries (including incoming carries at that column) propagate normally.
    Returns the set of candidate answers, one per column where this could happen.
    """
    cs = column_sums_units_first(n1, n2)
    if not cs:
        return set()

    candidates: set[int] = set()
    for k in range(len(cs)):
        digits_units_first: list[int] = []
        carry_in = 0
        for i, s in enumerate(cs):
            total = s + carry_in
            if i == k:
                # Drop the carry-out from THIS column
                digits_units_first.append(total % 10)
                carry_in = 0
            else:
                digits_units_first.append(total % 10)
                carry_in = total // 10
        if carry_in > 0:
            digits_units_first.append(carry_in)
        parts = [str(d) for d in reversed(digits_units_first)]
        candidates.add(int("".join(parts)) if parts else 0)
    return candidates


# ---------------------------------------------------------------------------
# A09 PVP candidate set — multi-sub-type per the spec
# ---------------------------------------------------------------------------

def place_value_permutations(n1: int, n2: int) -> set[int]:
    """
    Generate the A09 candidate set: place-value-error wrong answers.

    Per the spec, the set includes:
      (i)   Grid permutations of all digits across both operands (small
            problems only — combinatorial blowup limit).
      (ii)  Shift-based family: N1 × 10^k1 + N2 × 10^k2 for k1, k2 in
            [0, max_len + 1].
      (iii) Sparse placements: digits of the shorter operand placed into
            the wider operand's column grid (preserving order, zeros in gaps).

    Excludes: 1D+1D (per spec guard); the correct answer; zero.
    """
    if n_digits(n1) == 1 and n_digits(n2) == 1:
        return set()

    correct = n1 + n2
    candidates: set[int] = set()

    # --- (ii) Shift-based: N1 × 10^k1 + N2 × 10^k2 ---
    max_len = max(n_digits(n1), n_digits(n2))
    for k1 in range(max_len + 2):
        for k2 in range(max_len + 2):
            if k1 == 0 and k2 == 0:
                continue
            v = n1 * (10 ** k1) + n2 * (10 ** k2)
            if v > 0 and v != correct:
                candidates.add(v)

    # --- (iii) Sparse placements: shorter into wider's grid ---
    if n_digits(n1) != n_digits(n2):
        from itertools import combinations
        if n_digits(n1) < n_digits(n2):
            shorter, longer = n1, n2
        else:
            shorter, longer = n2, n1
        s_digits = digits(shorter)
        slots = n_digits(longer)
        for positions in combinations(range(slots), len(s_digits)):
            placed = [0] * slots
            for d, pos in zip(s_digits, positions):
                placed[pos] = d
            # Avoid building integers with leading zero implication;
            # treating placed list as int strips leading zeros naturally.
            sparse_val = int("".join(str(d) for d in placed))
            v = longer + sparse_val
            if v != correct and v > 0:
                candidates.add(v)

    # --- (i) Grid permutations — small problems only ---
    # v14.1: split-width is NOT constrained to the original operand widths.
    # The place-value misconception generalises to "kid re-distributes the
    # available digits across two numbers of arbitrary width". E.g. for
    # 6 + 187 (widths 1, 3) the kid can form 61 + 87 = 148 — a (2, 2) split
    # that the old restriction would never generate.
    total_digits = n_digits(n1) + n_digits(n2)
    if total_digits <= 5:
        from itertools import permutations
        all_digits = digits(n1) + digits(n2)
        for perm in set(permutations(all_digits)):
            for split_len in range(1, len(perm)):  # every interior split
                a_str = "".join(str(d) for d in perm[:split_len])
                b_str = "".join(str(d) for d in perm[split_len:])
                if a_str[0] != "0" and b_str[0] != "0":
                    v = int(a_str) + int(b_str)
                    if v != correct and v > 0:
                        candidates.add(v)

    candidates.discard(correct)
    candidates.discard(0)
    return candidates


# ---------------------------------------------------------------------------
# Boundary-slip detection (A19 mode c)
# ---------------------------------------------------------------------------

def digit_position_mismatches(a: int, b: int) -> int:
    """
    Number of digit positions where a and b differ, when right-aligned.
    """
    width = max(n_digits(a), n_digits(b))
    sa = str(a).zfill(width)
    sb = str(b).zfill(width)
    return sum(1 for x, y in zip(sa, sb) if x != y)


# ---------------------------------------------------------------------------
# Width / prefix tests for A21 and A25
# ---------------------------------------------------------------------------

def is_strict_prefix(wi: int, correct: int) -> bool:
    """
    A25 INCOMPLETE_ENTRY: str(wi) is a strict prefix of str(correct).
    """
    sw, sc = str(wi), str(correct)
    return len(sw) < len(sc) and sc.startswith(sw)


# ===========================================================================
# Subtraction-specific primitives
# ===========================================================================

def reverse_int(n: int) -> int:
    """
    Reverse the digit string of n. Leading zeros after reversal are stripped
    (the result is parsed as an integer).
        reverse_int(21)  -> 12
        reverse_int(680) -> 86  (rev "086" → 86)
        reverse_int(7)   -> 7
    """
    return int(str(n)[::-1])


def units(n: int) -> int:
    """Rightmost (ones) digit of n."""
    return n % 10


def tens(n: int) -> int:
    """Tens digit of n (= n // 10 % 10)."""
    return (n // 10) % 10


def subtract_columnwise_abs(n1: int, n2: int) -> int:
    """
    Column-wise |N1_col - N2_col| treating each column independently
    (no borrowing). Both operands right-aligned, units-first comparison.
    Returns the integer formed from the column results, MSB-first.
        subtract_columnwise_abs(91, 76) -> "|9-7|"+"|1-6|" = "2"+"5" = 25
        subtract_columnwise_abs(50, 28) -> "|5-2|"+"|0-8|" = "3"+"8" = 38
    """
    d1, d2 = right_align_digits(n1, n2)
    cols_msb = [abs(d1[i] - d2[i]) for i in range(len(d1))]
    return int("".join(str(d) for d in cols_msb)) if cols_msb else 0


def n1_minus_n2_left_aligned(n1: int, n2: int) -> int:
    """
    For S10 PLACE_VALUE_POSITIONING Tier 1.
    N2 left-aligned at width L = max(len(N1), len(N2)) means N2 is shifted
    so its leftmost digit aligns with N1's leftmost digit, then subtracted.
        n1_minus_n2_left_aligned(52, 5) -> 52 - 50 = 2     (5 left-aligned to width 2 = 50)
        n1_minus_n2_left_aligned(90, 6) -> 90 - 60 = 30
        n1_minus_n2_left_aligned(864, 45) -> 864 - 450 = 414
    Returns the raw subtraction result (may be negative). The caller is
    responsible for checking whether a negative result is meaningful for
    its diagnostic context — S10 Tier 1 uses this value via equality
    against wi, where a negative result simply won't match a non-negative
    wi.
    """
    L = max(n_digits(n1), n_digits(n2))
    shift = L - n_digits(n2)
    n2_shifted = n2 * (10 ** shift)
    result = n1 - n2_shifted
    return result


def borrow_columns(n1: int, n2: int) -> list[bool]:
    """
    For each column (units-first), does borrowing occur during standard
    right-to-left subtraction N1 - N2? Returns a list of booleans, one
    entry per column at the wider operand's width.
        borrow_columns(91, 76) -> [True, False]   (units 1<6 borrow; tens 9-7-1=1 OK)
        borrow_columns(50, 28) -> [True, False]   (units 0<8 borrow; tens 5-2-1=2 OK)
        borrow_columns(43, 17) -> [True, False]
        borrow_columns(99, 11) -> [False, False]
    """
    if n1 < n2:
        # Subtraction undefined for N1 < N2 in this domain
        # (the spec assumes N1 >= N2). Return all-False to be safe.
        return [False] * max(n_digits(n1), n_digits(n2))
    d1, d2 = right_align_digits(n1, n2)
    width = len(d1)
    # Walk units-first, tracking effective top digit
    borrows: list[bool] = []
    eff_top = list(d1)  # mutable copy of N1 digits
    for i in range(width - 1, -1, -1):  # rightmost first
        if eff_top[i] < d2[i]:
            borrows.append(True)
            # Borrow from next non-zero column to the left
            j = i - 1
            while j >= 0 and eff_top[j] == 0:
                eff_top[j] = 9       # zero column becomes 9 (chain borrow)
                j -= 1
            if j >= 0:
                eff_top[j] -= 1
            eff_top[i] += 10
        else:
            borrows.append(False)
    return borrows  # already units-first


def units_borrow_required(n1: int, n2: int) -> bool:
    """True iff the units-column subtraction needs a borrow."""
    return units(n1) < units(n2)


def any_borrow_required(n1: int, n2: int) -> bool:
    """True iff any column requires borrowing."""
    return any(borrow_columns(n1, n2))


def lender_column_for_borrow(n1: int, n2: int, borrow_col: int) -> Optional[int]:
    """
    Return the column index that LENT a 1 to satisfy the borrow at borrow_col.
    Walking left from borrow_col, find the first non-zero column.
    Returns None if no lender exists (i.e., subtraction infeasible at that column).
    """
    d1, _ = right_align_digits(n1, n2)
    width = len(d1)
    # d1 is MSB-first; convert to units-first
    d1_uf = list(reversed(d1))
    j = borrow_col + 1
    while j < width and d1_uf[j] == 0:
        j += 1
    if j >= width:
        return None
    return j


def n1_effective_digits_after_borrow(n1: int, n2: int) -> list[int]:
    """
    Return N1's effective top digits after all borrowing has occurred,
    units-first. Used by S25 X_MINUS_X_EQUALS_X.

    Examples:
        # 618-17: no borrow required (8 >= 7, 1 >= 1, 6 >= 0).
        n1_effective_digits_after_borrow(618, 17) -> [8, 1, 6]
        # 23-17: units borrow (3 < 7), tens lends.
        n1_effective_digits_after_borrow(23, 17) -> [13, 1]
        # 100-1: chain borrow through zero pass-through.
        n1_effective_digits_after_borrow(100, 1) -> [10, 9, 0]
    """
    d1, d2 = right_align_digits(n1, n2)
    width = len(d1)
    eff_top = list(d1)  # MSB-first
    eff_uf = list(reversed(eff_top))  # units-first
    for i in range(width):
        if eff_uf[i] < d2[width - 1 - i]:  # d2 indexed MSB-first
            j = i + 1
            while j < width and eff_uf[j] == 0:
                eff_uf[j] = 9
                j += 1
            if j < width:
                eff_uf[j] -= 1
            eff_uf[i] += 10
    return eff_uf


def pairwise_digit_diffs(n: int) -> set[int]:
    """
    Set of |di - dj| for all unordered digit pairs (di, dj) of n.
    Used by S26 CORRECT_ANSWER_DIGITS_SUBTRACTED.
        pairwise_digit_diffs(883) -> {|8-8|, |8-3|, |8-3|} = {0, 5}
        pairwise_digit_diffs(58)  -> {|5-8|} = {3}
    """
    ds = digits(n)
    out: set[int] = set()
    for i in range(len(ds)):
        for j in range(i + 1, len(ds)):
            out.add(abs(ds[i] - ds[j]))
    return out


# ===========================================================================
# Multiplication-specific primitives
# ===========================================================================

def digit_sum(n: int) -> int:
    """Sum of decimal digits of n (e.g. digit_sum(123) = 6)."""
    return sum(digits(n))


def digits_rtl(n: int) -> list[int]:
    """Digits of n, units-first (RTL order). digits_rtl(327) -> [7, 2, 3]."""
    return list(reversed(digits(n)))


def digits_ltr(n: int) -> list[int]:
    """Digits of n, MSB-first (LTR order). digits_ltr(327) -> [3, 2, 7]."""
    return digits(n)


def long_multiply_correct(n1: int, n2: int) -> int:
    """Simple correct product, included for symmetry with simulators."""
    return n1 * n2


def long_multiply_simulate(
    n1: int,
    n2: int,
    *,
    drop_carries: Optional[set[tuple[int, int]]] = None,
    step_op_add: Optional[tuple[int, int]] = None,
    step_mul_delta: Optional[tuple[int, int, int]] = None,
    step_carry_delta: Optional[tuple[int, int, int]] = None,
    step_trec_delta: Optional[tuple[int, int, int]] = None,
    second_step_trec_delta: Optional[tuple[int, int, int]] = None,
    write_carry_swap: bool = False,
    carry_swap_only_when_zero_carry_in: bool = False,
    carry_swap_first_step_only: bool = False,
    carry_add_before_mul: bool = False,
    carry_add_n2_skip: bool = False,
    carry_propagation_confusion: bool = False,
    same_digit_identity_substep: bool = False,
    zero_property_substep: bool = False,
    row1_carry_dropped: bool = False,
    row_result_concat: bool = False,
    row_result_concat_reversed: bool = False,
    shift_offsets: Optional[tuple[int, ...]] = None,
    ltr_direction: bool = False,
    final_carry_dropped: bool = False,
    final_carry_prepended_only: bool = False,
) -> Optional[int]:
    """
    Simulate the standard RTL long-multiplication algorithm with optional
    perturbations. Returns the simulated answer, or None if the perturbation
    config is incompatible with the operands (e.g. requested step doesn't exist).

    Perturbations (each maps to a specific misconception):
      drop_carries:                 set of (row, pos) tuples; at each, force carry_in→carry_out=0
                                    after writing the product digit. Models M10 CARRYING_ERROR.
      step_op_add:                  (row, pos) tuple; at that step, use d1+d2_row instead of
                                    d1*d2_row as the raw product. Models M13 STEP_OP_ADDITION.
      step_mul_delta:               (row, pos, delta) — at that step, use (d1+delta)*d2_row
                                    instead of d1*d2_row. delta ∈ {-2,-1,1,2}. Models M14.
      step_carry_delta:             (row, pos, delta) — at that step, add carry_in+delta
                                    after computing d1*d2_row. delta in {-3..-1, 1..3}.
                                    Models M15 STEP_CARRY_ADD_ERROR.
      step_trec_delta:              (row, pos, delta) — replaces the WHOLE product
                                    (d1*d2_row + carry_in) with (d1*d2_row + carry_in + delta).
                                    Models a single table-recall slip. Used by M45.
      second_step_trec_delta:       second TREC delta at a different (row, pos). Used by M45.
      write_carry_swap:             swap write/carry digits (write tens, carry units). M18.
      carry_swap_only_when_zero_carry_in: variant of swap — only swap when carry_in == 0.
      carry_swap_first_step_only:   variant — swap only at row 0 step 0.
      carry_add_before_mul:         single-digit-N2 only. step = (d+carry_in)*N2 (M11).
      carry_add_n2_skip:            single-digit-N2 only. for i>=1, step = carry_in + N2 (M12).
      carry_propagation_confusion:  carry_in = previous write digit (not previous carry_out). M20.
      same_digit_identity_substep:  at steps where d1==d2_row, write d1 and carry 0. M21.
      zero_property_substep:        at d1×d2_row where one is 0, write the non-zero digit. M03.
      row1_carry_dropped:           multi-digit N2 only. The result IS row 0's digit-products
                                    (no carries); ignores rows 1+. Models M35.
      row_result_concat:            multi-digit N2 only. Skip summation; concatenate rows
                                    (units row first). Models M45.
      row_result_concat_reversed:   reversed concat order (tens row first).
      shift_offsets:                tuple of column offsets per row, one int per row of N2.
                                    Default is (0, 1, 2, ...). Modeling M16/M22/M23.
      ltr_direction:                process N1 digits LTR; carry flows toward units. M21.
      final_carry_dropped:          drop the leftmost carry at end of each row.
      final_carry_prepended_only:   at end, prepend remaining carry (no overflow handling).

    Defaults reproduce the correct algorithm.
    """
    drop_carries = drop_carries or set()
    d2_digits_rtl = digits_rtl(n2)

    rows: list[int] = []
    for j, d2 in enumerate(d2_digits_rtl):
        # Apply row1_carry_dropped: only row 0 contributes, and with carries dropped
        if row1_carry_dropped:
            if j != 0:
                continue
            d1_digits = digits_rtl(n1)
            row_digits_rtl: list[int] = []
            for i, d1 in enumerate(d1_digits):
                row_digits_rtl.append((d1 * d2) % 10)
            row_value = int("".join(str(x) for x in reversed(row_digits_rtl)))
            return row_value

        # Determine direction of N1 digit iteration
        if ltr_direction:
            d1_iter = list(enumerate(digits_ltr(n1)))
        else:
            d1_iter = list(enumerate(digits_rtl(n1)))

        carry = 0
        prev_write = 0
        last_real_carry = 0
        row_digits: list[int] = []  # in iteration order (for RTL: units-first)
        for step_idx, (i, d1) in enumerate(d1_iter):
            # carry-add-before-mul (M11): only single-digit N2, only when iterating N1's digits
            if carry_add_before_mul and len(d2_digits_rtl) == 1 and j == 0:
                step = (d1 + carry) * d2
            elif carry_add_n2_skip and len(d2_digits_rtl) == 1 and j == 0 and i >= 1:
                step = carry + n2  # learner skipped multiplying digit, added carry to N2
            elif step_op_add == (j, i):
                step = (d1 + d2) + carry  # raw product replaced by sum, carry still added
            elif step_mul_delta and step_mul_delta[0] == j and step_mul_delta[1] == i:
                delta = step_mul_delta[2]
                step = (d1 + delta) * d2 + carry
            elif step_carry_delta and step_carry_delta[0] == j and step_carry_delta[1] == i:
                delta = step_carry_delta[2]
                step = d1 * d2 + carry + delta
            elif (step_trec_delta and step_trec_delta[0] == j and step_trec_delta[1] == i):
                delta = step_trec_delta[2]
                step = d1 * d2 + carry + delta
            elif (second_step_trec_delta and second_step_trec_delta[0] == j
                  and second_step_trec_delta[1] == i):
                delta = second_step_trec_delta[2]
                step = d1 * d2 + carry + delta
            elif zero_property_substep and (d1 == 0 or d2 == 0) and not (d1 == 0 and d2 == 0):
                # Write the non-zero digit instead of 0
                step = (d1 if d1 != 0 else d2) + carry
            elif same_digit_identity_substep and d1 == d2 and d1 != 0:
                # Write d1 and carry 0
                row_digits.append(d1)
                carry = 0
                prev_write = d1
                continue
            else:
                step = d1 * d2 + carry

            # Write/carry split
            if write_carry_swap:
                # Variants
                do_swap = True
                if carry_swap_only_when_zero_carry_in and carry != 0:
                    do_swap = False
                if carry_swap_first_step_only and not (j == 0 and step_idx == 0):
                    do_swap = False
                if do_swap and step >= 10:
                    write = step // 10
                    new_carry = step % 10
                else:
                    write = step % 10
                    new_carry = step // 10
            else:
                write = step % 10
                new_carry = step // 10

            # Carrying-error: drop the carry at this position
            if (j, i) in drop_carries:
                new_carry = 0

            row_digits.append(write)
            # M19: next step's carry_in = THIS step's write digit (not new_carry).
            # But the REAL carry (used at end-of-row prepend) is still new_carry.
            if carry_propagation_confusion:
                carry = write          # what next step sees as carry_in
                last_real_carry = new_carry   # what we'd prepend at end
            else:
                carry = new_carry
                last_real_carry = new_carry
            prev_write = write

        # End-of-row: prepend remaining carry
        # For M19: prepend the real carry of the last step (not the propagated "write-as-carry").
        end_carry = last_real_carry if carry_propagation_confusion else carry
        if end_carry > 0 and not final_carry_dropped:
            row_digits.append(end_carry)

        # If LTR, the row_digits are in LTR order, so reverse to get LSB-first
        if ltr_direction:
            # In LTR processing, the carry flows toward units (rightward); the natural
            # interpretation: digits assembled in iteration order represent MSB-first.
            row_digits = list(reversed(row_digits))

        # Assemble row value (digits are LSB-first)
        row_value = sum(d * (10 ** k) for k, d in enumerate(row_digits))
        rows.append(row_value)

    # row1_carry_dropped already returned early
    if row_result_concat:
        # Concatenate row strings instead of summing
        if row_result_concat_reversed:
            row_strs = [str(r) for r in reversed(rows)]
        else:
            row_strs = [str(r) for r in rows]
        return int("".join(row_strs))

    # Apply shift_offsets if provided
    offsets = shift_offsets if shift_offsets is not None else tuple(range(len(rows)))
    if len(offsets) != len(rows):
        return None
    total = sum(r * (10 ** offsets[k]) for k, r in enumerate(rows))
    return total


def column_wise_digit_mul(n1: int, n2: int) -> Optional[int]:
    """
    M26 COLUMN_WISE_MUL: at each matching position (right-aligned), multiply the
    two digits, concatenate the results MSB-first.
        column_wise_digit_mul(34, 26) -> str(3*2) + str(4*6) = "6" + "24" = 624
        column_wise_digit_mul(34, 6) -> only one column matches → str(4*6) = 24
    Returns the integer result, or None if not applicable.
    """
    d1 = digits_rtl(n1)
    d2 = digits_rtl(n2)
    width = min(len(d1), len(d2))
    if width == 0:
        return None
    parts = []
    for k in range(width - 1, -1, -1):  # MSB-first within the matched range
        parts.append(str(d1[k] * d2[k]))
    return int("".join(parts))


def digit_concat_rtl_product(n1: int, n2: int) -> int:
    """
    M08 DIGIT_CONCAT_RTL: each digit of N1 multiplied by N2, joined RTL as text.
    Example: 897×8 → "7×8=56 | 9×8=72 | 8×8=64" → "567264".
    """
    d1 = digits_rtl(n1)
    parts = [str(d * n2) for d in d1]
    return int("".join(parts))


def digit_concat_ltr_product(n1: int, n2: int) -> int:
    """
    M09 DIGIT_CONCAT_LTR: same as M08 but joined LTR.
    Example: 897×8 → "8×8=64 | 9×8=72 | 7×8=56" → "647256".
    """
    d1 = digits_ltr(n1)
    parts = [str(d * n2) for d in d1]
    return int("".join(parts))


def row_concat_digit_mul(n1: int, n2: int) -> int:
    """
    M32 ROW_CONCAT_DIGIT_MUL: multi-digit N2 only. For each digit of N2 (RTL),
    for each digit of N1 (RTL), compute d1*d2 as string, concatenate within row,
    concatenate rows.
    Example: 30×24 → row 4: "0", "12" → "012"; row 2: "0", "6" → "06" → "01206" → 1206.
    """
    d1 = digits_rtl(n1)
    d2 = digits_rtl(n2)
    out_parts = []
    for d2_digit in d2:
        row_parts = []
        for d1_digit in d1:
            row_parts.append(str(d1_digit * d2_digit))
        out_parts.append("".join(row_parts))
    return int("".join(out_parts))


# ===========================================================================
# Division-specific parsing
# ===========================================================================

import re as _re


def parse_qr_response(raw: object) -> dict:
    """
    Parse a division learner response that may be in either:
      - integer-only form: "12", "12 ", " 12 "
      - Q-R form: "12 R 3", "12 r 3", "12 remainder 3", "12 R3", "12R3"

    Returns a dict with:
      - "raw":     the normalized raw string (or None)
      - "is_qr":   True if response was in Q-R form, False otherwise
      - "wi":      int | None — full integer parse (only meaningful when is_qr=False)
      - "q_w":     int | None — quotient component
      - "r_w":     int | None — remainder component (None when not Q-R)

    Notes:
      - Whitespace, quotes, commas tolerated as in parse_operand.
      - For Q-R form, both q_w and r_w must parse cleanly as non-negative integers
        for is_qr=True; otherwise returns is_qr=False with all components None.
      - For integer-only form, q_w == wi (so D-rules that compare against q_w work
        uniformly whether or not the response was QR).
      - Decimals and negative numbers cause everything to return None, except that
        "raw" is preserved for D01 detection.
    """
    out: dict = {
        "raw": None, "is_qr": False, "wi": None, "q_w": None, "r_w": None,
    }
    if raw is None:
        return out
    s = str(raw).strip().strip("'\"")
    if not s:
        return out
    out["raw"] = s

    # Normalise: collapse multiple whitespace, strip commas (operand-style)
    s_clean = s.replace(",", "")
    # Look for Q-R separator. Accept: "R", "r", "remainder", with or without
    # surrounding whitespace.
    m = _re.match(
        r"^\s*([0-9]+)\s*(?:[Rr]|remainder|REMAINDER)\s*([0-9]+)\s*$", s_clean
    )
    if m:
        try:
            q = int(m.group(1))
            r = int(m.group(2))
        except ValueError:
            return out
        if q < 0 or r < 0:
            return out
        out["is_qr"] = True
        out["q_w"] = q
        out["r_w"] = r
        return out

    # Integer-only form
    if "." in s_clean:
        return out
    if not s_clean.isdigit():
        return out
    try:
        v = int(s_clean)
    except ValueError:
        return out
    if v < 0:
        return out
    out["wi"] = v
    out["q_w"] = v  # for unified comparisons
    return out
