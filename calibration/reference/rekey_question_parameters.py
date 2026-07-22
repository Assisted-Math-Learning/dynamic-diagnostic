#!/usr/bin/env python3
"""Re-key question_parameters.csv division rows to the v9 seven-field key (AC11).

The seventh field (response_includes_remainder) is appended to DIVISION items only;
non-division items are untouched, so their calibration join is unchanged. The
value is derived from each question's correct answer in the question source (a
JSON object with a 'remainder' key -> True). Because the 7th field is a function
of content that is constant within a six-field item group (verified: every
division duplicate group carries one remainder flag), this is a pure string
re-key: no slip/guess re-estimation is required. The guard below asserts that
property and refuses to proceed if any item maps to conflicting flags (which
would mean a genuine split that needs re-estimation, to be escalated).

Inputs:
  --params   question_parameters.csv (has the 6-field 'item' column)
  --source   question source with columns: q_l1_skill,q_l2_5_skill,q_type,q_text,
             q_n1,q_n2,q_correct_answer  (the same fields calibrate_questions.py keys on)
Output:
  a copy of question_parameters.csv with division 'item' values re-keyed.
"""
import argparse, json
import pandas as pd

SEP = "|"
DIV = "Division"
K6 = ["q_l1_skill", "q_l2_5_skill", "q_type", "q_text", "q_n1", "q_n2"]


def _norm(v):
    return "" if pd.isna(v) else str(v)


def six_field_key(row):
    return SEP.join(_norm(row[c]) for c in K6)


def derive_rir(row):
    if row["q_l1_skill"] != DIV:
        return ""
    ca = row["q_correct_answer"]
    try:
        obj = json.loads(ca) if isinstance(ca, str) else ca
        return str(bool(isinstance(obj, dict) and "remainder" in {str(k).lower() for k in obj}))
    except Exception:
        return "False"


def build_item_to_rir(source_df):
    """Map 6-field item -> remainder flag, asserting one flag per item."""
    src = source_df.copy()
    src["k6"] = src.apply(six_field_key, axis=1)
    src["rir"] = src.apply(derive_rir, axis=1)
    div = src[src["q_l1_skill"] == DIV]
    conflicts = div.groupby("k6")["rir"].nunique()
    conflicts = conflicts[conflicts > 1]
    if len(conflicts):
        raise SystemExit(f"GUARD FAILED: {len(conflicts)} division item(s) map to conflicting "
                         f"remainder flags; these need re-estimation, not a pure re-key:\n"
                         + "\n".join(f"  {k}" for k in conflicts.index[:10]))
    return dict(zip(div["k6"], div["rir"]))


def rekey(params_df, item_to_rir):
    out = params_df.copy()
    is_div = out["item"].astype(str).str.startswith(DIV + SEP)
    def newkey(it):
        r = item_to_rir.get(it)
        return it if r is None else it + SEP + r          # append only when we know the flag
    out.loc[is_div, "item"] = out.loc[is_div, "item"].map(newkey)
    n_div = int(is_div.sum())
    n_mapped = int((out.loc[is_div, "item"].str.count(r"\|") == 6).sum())  # 7 fields -> 6 separators
    return out, n_div, n_mapped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--params", required=True)
    ap.add_argument("--source", required=True)
    ap.add_argument("-o", "--output", required=True)
    args = ap.parse_args()
    params = pd.read_csv(args.params)
    source = pd.read_parquet(args.source) if args.source.endswith(".parquet") else pd.read_csv(args.source)
    item_to_rir = build_item_to_rir(source)
    out, n_div, n_mapped = rekey(params, item_to_rir)
    assert len(out) == len(params), "row count changed"
    out.to_csv(args.output, index=False)
    print(f"rows: {len(out)} (unchanged) | division rows: {n_div} | re-keyed to 7 fields: {n_mapped} "
          f"| unmapped division (source not covering them): {n_div - n_mapped}")


if __name__ == "__main__":
    main()
