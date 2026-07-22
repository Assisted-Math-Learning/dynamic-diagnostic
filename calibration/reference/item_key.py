"""
item_key.py - the single source of truth for the composite content key ("item").

The item key identifies a unique question by content so that the calibration
script (calibrate_questions.py) and the per-tenant lookup builder
(build_question_lookup.py) join on byte-identical keys. Both import
build_item_key from here; neither reimplements it. This is the property that
makes the lookup reproducible and auditable: the key cannot drift between the
two pipelines because there is only one implementation.

Key definition (pool-build spec Section 3):
    non-division: L1 | L2.5 | Type | Text | N1 | N2
    division:     L1 | L2.5 | Type | Text | N1 | N2 | response_includes_remainder

Rules:
- Fields joined by "|"; each value normalized as "" when null, else str(value).
- N1/N2 are stored as integers, so str() yields "3" not "3.0" (no float drift).
  Read the workbook with pandas so integer columns stay int64; do not coerce.
- The seventh field is appended for DIVISION rows only, derived from the stored
  correct answer: a JSON object carrying a "remainder" key -> "True", else
  "False" (and "False" on parse failure). NEVER inferred from operands (n1 % n2):
  a remainder-format question whose operands divide evenly is still "True".
  Non-division keys are byte-identical to the six-field key.

Why the caller passes column names: the L1/operation column is named differently
in the two inputs. The shared workbook has "Final Q L1 Skill" (use
WORKBOOK_FIELDS); calibrate_questions aliases that to "Q L1 Skill" (use
CALIBRATION_FIELDS). The VALUES are identical, so the keys are identical.
"""
from __future__ import annotations
import json
import pandas as pd

SEP = "|"
DIVISION_LABEL = "Division"
CORRECT_ANSWER_COL = "Q Correct Answer"

# Base six fields. Position 0 is the L1/operation field; only its column name
# varies between the two inputs (see module docstring).
CALIBRATION_FIELDS = ("Q L1 Skill", "Q L2.5 Skill", "Q Type", "Q Text", "Q N1", "Q N2")
WORKBOOK_FIELDS    = ("Final Q L1 Skill", "Q L2.5 Skill", "Q Type", "Q Text", "Q N1", "Q N2")


def _norm(v) -> str:
    return "" if pd.isna(v) else str(v)


def derive_response_includes_remainder(row, l1_field=CALIBRATION_FIELDS[0],
                                       correct_answer_col=CORRECT_ANSWER_COL,
                                       division_label=DIVISION_LABEL) -> str:
    """Seventh key field. "" for non-division. For division, "True" if the stored
    correct answer is a JSON object carrying a "remainder" key, else "False"
    (also "False" on parse failure). Never inferred from operands."""
    if str(row.get(l1_field)) != division_label:
        return ""
    ca = row.get(correct_answer_col)
    try:
        obj = json.loads(ca) if isinstance(ca, str) else ca
        return str(bool(isinstance(obj, dict) and "remainder" in {str(k).lower() for k in obj}))
    except Exception:
        return "False"


def build_item_key(df, fields=CALIBRATION_FIELDS, sep=SEP, append_remainder=True,
                   correct_answer_col=CORRECT_ANSWER_COL, division_label=DIVISION_LABEL):
    """Return a pd.Series of item keys, one per row of df.

    fields: the six base column names; position 0 is the L1/operation column.
    append_remainder: when True, append the division-only seventh field.
    """
    fields = list(fields)
    missing = [c for c in fields if c not in df.columns]
    if missing:
        raise KeyError(f"item_key: missing key columns {missing}")
    base = df[fields].apply(lambda r: sep.join(_norm(v) for v in r), axis=1)
    if not append_remainder:
        return base
    if correct_answer_col not in df.columns:
        raise KeyError(f"item_key: append_remainder=True needs column {correct_answer_col!r}")
    l1_field = fields[0]
    rir = df.apply(lambda r: derive_response_includes_remainder(
        r, l1_field, correct_answer_col, division_label), axis=1)
    return pd.Series([b + (sep + s if s != "" else "") for b, s in zip(base, rir)],
                     index=base.index)
