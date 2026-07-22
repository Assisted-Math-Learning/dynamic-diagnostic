"""
test_item_key.py - proves item_key.build_item_key reproduces the original inline
composite_key logic byte-for-byte, and pins the division seventh-field rules.
Run: python -m pytest test_item_key.py -q
"""
import json
import pandas as pd
import item_key


# Frozen copy of the ORIGINAL inline logic from calibrate_questions.py, as it was
# before extraction. The parity tests assert item_key reproduces this exactly.
_KEY_FIELDS = ("Q L1 Skill", "Q L2.5 Skill", "Q Type", "Q Text", "Q N1", "Q N2")
def _legacy_rir(row):
    if str(row.get(_KEY_FIELDS[0])) != "Division":
        return ""
    ca = row.get("Q Correct Answer")
    try:
        obj = json.loads(ca) if isinstance(ca, str) else ca
        return str(bool(isinstance(obj, dict) and "remainder" in {str(k).lower() for k in obj}))
    except Exception:
        return "False"
def _legacy_composite_key(df):
    def norm(v): return "" if pd.isna(v) else str(v)
    base = df[list(_KEY_FIELDS)].apply(lambda r: "|".join(norm(v) for v in r), axis=1)
    rir = df.apply(_legacy_rir, axis=1)
    return pd.Series([b + ("|" + s if s != "" else "") for b, s in zip(base, rir)], index=base.index)


def _frame():
    # A comprehensive frame: every operation, nulls in Q Text, integer operands,
    # division with remainder-format True and False, division that divides evenly
    # but is remainder-format (must be True), MCQ, bad-JSON answer.
    rows = [
        # non-division, null Text (Fib), integer operands
        {"Q L1 Skill": "Addition", "Q L2.5 Skill": "1D+1D sum upto 9", "Q Type": "Fib",
         "Q Text": None, "Q N1": 3, "Q N2": 4, "Q Correct Answer": "7"},
        {"Q L1 Skill": "Subtraction", "Q L2.5 Skill": "2D-1D", "Q Type": "Fib",
         "Q Text": None, "Q N1": 12, "Q N2": 5, "Q Correct Answer": "7"},
        {"Q L1 Skill": "Multiplication", "Q L2.5 Skill": "Tables", "Q Type": "MCQ",
         "Q Text": "What is 3x4?", "Q N1": 3, "Q N2": 4, "Q Correct Answer": "12"},
        # division, quotient-only -> False
        {"Q L1 Skill": "Division", "Q L2.5 Skill": "2D by 1D", "Q Type": "Fib",
         "Q Text": None, "Q N1": 36, "Q N2": 3, "Q Correct Answer": "12"},
        # division, quotient+remainder JSON -> True
        {"Q L1 Skill": "Division", "Q L2.5 Skill": "2D by 1D", "Q Type": "Fib",
         "Q Text": None, "Q N1": 37, "Q N2": 3, "Q Correct Answer": json.dumps({"quotient": 12, "remainder": 1})},
        # division, remainder-format but divides evenly -> STILL True (not operand-inferred)
        {"Q L1 Skill": "Division", "Q L2.5 Skill": "2D by 1D", "Q Type": "Fib",
         "Q Text": None, "Q N1": 36, "Q N2": 3, "Q Correct Answer": json.dumps({"quotient": 12, "remainder": 0})},
        # division, bad JSON answer -> False (exception path)
        {"Q L1 Skill": "Division", "Q L2.5 Skill": "2D by 1D", "Q Type": "Fib",
         "Q Text": None, "Q N1": 40, "Q N2": 4, "Q Correct Answer": "{bad json"},
    ]
    return pd.DataFrame(rows)


def test_parity_with_legacy():
    df = _frame()
    got = item_key.build_item_key(df, fields=_KEY_FIELDS)
    exp = _legacy_composite_key(df)
    assert list(got) == list(exp), f"\n got={list(got)}\n exp={list(exp)}"


def test_non_division_is_six_fields():
    df = _frame()
    keys = item_key.build_item_key(df, fields=_KEY_FIELDS)
    for op, k in zip(df["Q L1 Skill"], keys):
        if op != "Division":
            assert k.count("|") == 5, f"non-division key must have 6 fields: {k}"


def test_division_seventh_field():
    df = _frame()
    keys = list(item_key.build_item_key(df, fields=_KEY_FIELDS))
    # rows 3..6 are division; check the appended flag
    assert keys[3].endswith("|False")   # quotient-only
    assert keys[4].endswith("|True")    # remainder JSON
    assert keys[5].endswith("|True")    # remainder-format, divides evenly -> True
    assert keys[6].endswith("|False")   # bad JSON -> False
    for k in keys[3:7]:
        assert k.count("|") == 6, f"division key must have 7 fields: {k}"


def test_integer_operands_no_float_drift():
    df = _frame()
    k = item_key.build_item_key(df, fields=_KEY_FIELDS).iloc[0]
    assert "|3|4" in k and "3.0" not in k, k


def test_workbook_fields_equivalent_to_calibration_fields():
    # Same values under the workbook's "Final Q L1 Skill" name must yield the
    # same key as calibration's "Q L1 Skill" name. This is what guarantees the
    # builder and the calibration script join on identical keys.
    df = _frame()
    wb = df.rename(columns={"Q L1 Skill": "Final Q L1 Skill"})
    from_cal = item_key.build_item_key(df, fields=item_key.CALIBRATION_FIELDS)
    from_wb  = item_key.build_item_key(wb, fields=item_key.WORKBOOK_FIELDS)
    assert list(from_cal) == list(from_wb)


def test_append_remainder_false_gives_base_only():
    df = _frame()
    keys = item_key.build_item_key(df, fields=_KEY_FIELDS, append_remainder=False)
    for k in keys:
        assert k.count("|") == 5   # always six base fields, no seventh


def test_missing_column_raises():
    df = _frame().drop(columns=["Q N2"])
    try:
        item_key.build_item_key(df, fields=_KEY_FIELDS)
        assert False, "expected KeyError"
    except KeyError:
        pass


def test_missing_answer_col_raises_when_remainder_requested():
    df = _frame().drop(columns=["Q Correct Answer"])
    try:
        item_key.build_item_key(df, fields=_KEY_FIELDS, append_remainder=True)
        assert False, "expected KeyError"
    except KeyError:
        pass
