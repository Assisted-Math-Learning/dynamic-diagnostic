"""
Build the per-tenant question lookup and misconception tags (spec Pieces A + D).
Standalone offline script. Reads the shared multi-tenant workbook and writes:
  tenant_question_lookup.csv   one record per (tenant, item):
                               tenant, item, question_x_id, + 11 misconception flags
  build_report.txt             uncalibrated items, multi-id tiebreaks applied,
                               and (Piece C, added later) retired-dropped rows
The misconception flags are DERIVED from the raw fields (operation, type, N1, N2,
correct answer), not read from the workbook's reference columns. The derivation
is validated to reproduce the workbook's reference tags (columns AQ to BA) over
all rows; see test_build_lookup.py.
The `item` key is built with the shared item_key module (WORKBOOK_FIELDS), so it
is byte-identical to the calibration script's key.
Run:
    python build_question_lookup.py --workbook WB.xlsx --params question_parameters.csv --out-dir .
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import pandas as pd
import item_key
# Tag order is fixed; this is the column order in the output and the parity map.
MISCONCEPTIONS = [
    "x_plus_0", "x_plus_x",                       # Addition
    "x_minus_0", "zero_minus_x", "x_minus_x",     # Subtraction
    "x_into_x", "x_into_0",                        # Multiplication
    "zero_end_n1", "zero_mid_n1",                  # Division (N1)
    "zero_end_quotient_no_zero_n1", "zero_mid_quotient_no_zero_n1",  # Division (quotient)
]
# Workbook reference-tag column for each derived flag (used only by the parity test).
REFERENCE_COLUMN = {
    "x_plus_0": "x + 0", "x_plus_x": "x + x",
    "x_minus_0": "x - 0", "zero_minus_x": "0 - x", "x_minus_x": "x - x",
    "x_into_x": "x into x", "x_into_0": "x into 0",
    "zero_end_n1": "0 end n1", "zero_mid_n1": "0 mid n1",
    "zero_end_quotient_no_zero_n1": "No 0 in n1 but 0 end Quotient",
    "zero_mid_quotient_no_zero_n1": "No 0 in n1 but 0 mid Quotient",
}
FIB = "Fib"
# =========================================================================== #
# Digit / answer helpers (spec 5.2)                                            #
# =========================================================================== #
def _digits_lr(n) -> dict:
    """Place-value digits right to left: {0:O, 1:T, 2:H, 3:Th, 4:TTh}. Only the
    places present in the number are keys; absent places are simply missing."""
    return {i: int(c) for i, c in enumerate(reversed(str(int(n))))}
def _both_places(n1, n2):
    """(top, bottom) digit pairs for every place present in BOTH operands."""
    d1, d2 = _digits_lr(n1), _digits_lr(n2)
    return [(d1[p], d2[p]) for p in sorted(set(d1) & set(d2))]
def _sub_b_top(n1, n2):
    """Effective top digit at each column after borrow propagation (the
    Sub_B_Top logic). Processes ones upward, carrying a borrow flag; the stored
    value is the raw digit minus 1 if it lent to the right, plus 10 if it
    borrowed from the left. Returns (eff, bottom_digits)."""
    d1, d2 = _digits_lr(n1), _digits_lr(n2)
    borrow = 0
    eff = {}
    for p in range(max(d1) + 1):
        raw = d1.get(p, 0)
        bottom = d2.get(p, 0)
        t = raw - borrow
        if t < bottom:
            t += 10
            borrow = 1
        else:
            borrow = 0
        eff[p] = t
    return eff, d2
def _quotient_of(answer):
    """The quotient from Q Correct Answer: parse JSON when it carries a
    `quotient` field, otherwise treat the bare answer as the quotient. The
    remainder is never used by any misconception."""
    a = str(answer).strip()
    if "quotient" in a:
        try:
            return int(json.loads(a)["quotient"])
        except Exception:
            pass
    try:
        return int(float(a))
    except (ValueError, TypeError):
        return None
# =========================================================================== #
# The 11 geometric rules (spec 5.3), dispatched by Q Type then operation       #
# =========================================================================== #
def derive_geometric_flags(operation, q_type, n1, n2, answer) -> dict:
    """Pre-gate flags. MCQ -> all zero (the MCQ seam, spec 5.6). Otherwise the
    flags for the row's operation are computed; other operations' flags stay 0."""
    f = {k: 0 for k in MISCONCEPTIONS}
    if q_type != FIB:
        return f
    if operation == "Addition":
        bp = _both_places(n1, n2)
        f["x_plus_0"] = int(any((a == 0) != (b == 0) for a, b in bp))
        f["x_plus_x"] = int(any(a == b and a != 0 for a, b in bp))
    elif operation == "Subtraction":
        bp = _both_places(n1, n2)
        f["x_minus_0"] = int(any(a != 0 and b == 0 for a, b in bp))
        eff, bottom = _sub_b_top(n1, n2)
        # effective top presents as 0 (a multiple of 10) with bottom nonzero
        f["zero_minus_x"] = int(any(eff[p] % 10 == 0 and bottom.get(p, 0) != 0 for p in eff))
        # effective top digit equals the bottom digit and is nonzero
        f["x_minus_x"] = int(any((eff[p] % 10) == bottom.get(p, 0) and (eff[p] % 10) != 0 for p in eff))
    elif operation == "Multiplication":
        s1 = {int(c) for c in str(int(n1))}
        s2 = {int(c) for c in str(int(n2))}
        f["x_into_x"] = int(any(d not in (0, 1) for d in (s1 & s2)))
        f["x_into_0"] = int("0" in str(int(n1)) or "0" in str(int(n2)))
    elif operation == "Division":
        n1s = str(int(n1))
        f["zero_end_n1"] = int(int(n1) % 10 == 0)
        # "mid" 0 = a 0 anywhere except the single ones place (so 400 -> 1, 40 -> 0)
        f["zero_mid_n1"] = int("0" in n1s[:-1])
        q = _quotient_of(answer)
        if q is not None:
            no_zero_n1 = "0" not in n1s
            f["zero_end_quotient_no_zero_n1"] = int(q % 10 == 0 and no_zero_n1)
            f["zero_mid_quotient_no_zero_n1"] = int(("0" in str(abs(q))[:-1]) and no_zero_n1)
    return f
def apply_class_one_gate(flags: dict, content_class) -> dict:
    """Spec 5.4 policy overlay: force zero_minus_x to 0 for class-one content.
    Applied AFTER the geometric derivation; the reference columns are pre-gate."""
    if str(content_class).strip() == "class-one":
        flags = dict(flags)
        flags["zero_minus_x"] = 0
    return flags
def derive_flags(operation, q_type, n1, n2, answer, content_class, gate=True) -> dict:
    f = derive_geometric_flags(operation, q_type, n1, n2, answer)
    if gate:
        f = apply_class_one_gate(f, content_class)
    return f
# =========================================================================== #
# (tenant, item) -> question_x_id resolution (spec 4.3)                        #
# =========================================================================== #
def resolve_question_x_id(xids) -> str:
    """Deterministic tiebreak by variant precedence: prefer ids containing
    `entry`, then ids containing `dlg`, then ids ending in `_b`, and finally the
    lexicographically smallest. The substring/suffix tests are case-insensitive;
    the final tiebreak uses the original id, so the ordering is total and the
    result is fully deterministic."""
    def _rank(qxid: str):
        q = qxid.lower()
        return (
            0 if "entry" in q else 1,      # 1. prefer entry variants
            0 if "dlg" in q else 1,        # 2. then dlg (Delhi grade-specific) variants
            0 if q.endswith("_b") else 1,  # 3. then _b-suffixed variants
            qxid,                          # 4. lexicographic final tiebreak
        )
    return min({str(x) for x in xids}, key=_rank)
# =========================================================================== #
# Retired-list filter (spec Piece C, section 6)                                #
# =========================================================================== #
def load_retired(path):
    """Read the retired-questions CSV (canonical: retired_questions_v2.csv) -> (retired_items set, retired_xids set).
    scope `item` retires a content key (all its instances, every tenant);
    scope `question_x_id` retires one instance (that tenant only)."""
    df = pd.read_csv(path)
    items = set(df.loc[df["scope"] == "item", "key"].astype(str))
    xids = set(df.loc[df["scope"] == "question_x_id", "key"].astype(str))
    return items, xids
# =========================================================================== #
# Build                                                                        #
# =========================================================================== #
DEFAULT_FIELD_MAP = dict(
    tenant="Tenant", operation="Final Q L1 Skill", content_class="Final Q Content Class",
    q_type="Q Type", n1="Q N1", n2="Q N2", answer="Q Correct Answer", xid="Q X ID",
)
def build_lookup(wb: pd.DataFrame, calibrated_items=None, gate=True, fields=DEFAULT_FIELD_MAP,
                 retired_items=None, retired_xids=None):
    """Return (lookup_df, report_dict).
    lookup_df: one row per (tenant, item) with the resolved question_x_id and the
    11 flags. report_dict: lists for the build report.
    """
    df = wb.copy()
    df["item"] = item_key.build_item_key(df, fields=item_key.WORKBOOK_FIELDS)
    # Retired-list filter (applied before grouping so retired instances never
    # become the resolved id, and items left with no instances drop out).
    retired_items = set(retired_items or set())
    retired_xids = set(retired_xids or set())
    xcol_pre = fields["xid"]
    n_before = len(df)
    dropped_by_item = int(df["item"].isin(retired_items).sum())
    dropped_by_xid = int(df[xcol_pre].astype(str).isin(retired_xids).sum())
    if retired_items:
        df = df[~df["item"].isin(retired_items)]
    if retired_xids:
        df = df[~df[xcol_pre].astype(str).isin(retired_xids)]
    # Derive flags per row (geometric + optional class-one gate).
    flag_rows = df.apply(
        lambda r: derive_flags(r[fields["operation"]], r[fields["q_type"]],
                               r[fields["n1"]], r[fields["n2"]], r[fields["answer"]],
                               r[fields["content_class"]], gate=gate),
        axis=1, result_type="expand")
    df = pd.concat([df, flag_rows], axis=1)
    tcol, xcol = fields["tenant"], fields["xid"]
    records = []
    multi_id_log = []
    flag_conflict_log = []
    for (tenant, item), g in df.groupby([tcol, "item"], sort=True):
        xids = list(g[xcol])
        chosen = resolve_question_x_id(xids)
        if g[xcol].nunique() > 1:
            multi_id_log.append((tenant, item, sorted(set(map(str, xids))), chosen))
        # Flags from the tiebreak-winning row (deterministic). Flag a conflict if
        # rows of the same (tenant, item) disagree (should not happen: flags are
        # content-derived and item encodes the content + the gate uses class).
        win = g[g[xcol] == chosen].iloc[0]
        flags = {k: int(win[k]) for k in MISCONCEPTIONS}
        for k in MISCONCEPTIONS:
            if g[k].nunique() > 1:
                flag_conflict_log.append((tenant, item, k))
        rec = dict(tenant=tenant, item=item, question_x_id=chosen)
        rec.update(flags)
        records.append(rec)
    lookup = pd.DataFrame(records, columns=["tenant", "item", "question_x_id"] + MISCONCEPTIONS)
    # Uncalibrated items (not present in question_parameters.csv) have no
    # calibration row, so they can never be selection candidates. Log them for
    # visibility, then DROP them from the written lookup: an uncalibrated row is
    # an unservable row. Only possible when --params is supplied; without it the
    # full set is written unchanged (legacy behaviour).
    uncalibrated = []
    dropped_uncalibrated_rows = 0
    if calibrated_items is not None:
        cal = set(calibrated_items)
        uncalibrated = sorted(set(lookup["item"]) - cal)
        before_drop = len(lookup)
        lookup = lookup[lookup["item"].isin(cal)].reset_index(drop=True)
        dropped_uncalibrated_rows = before_drop - len(lookup)
    report = dict(
        n_rows=n_before, n_records=len(lookup),
        tenants=sorted(df[tcol].unique()),
        multi_id=multi_id_log, flag_conflicts=sorted(set(flag_conflict_log)),
        uncalibrated=uncalibrated,
        retired_items=sorted(retired_items), retired_xids=sorted(retired_xids),
        dropped_by_item=dropped_by_item, dropped_by_xid=dropped_by_xid,
        dropped_uncalibrated_rows=dropped_uncalibrated_rows,
    )
    return lookup, report
def write_report(report: dict, path: Path):
    lines = []
    lines.append("BUILD REPORT: tenant question lookup")
    lines.append("=" * 50)
    lines.append(f"workbook rows read      : {report['n_rows']}")
    lines.append(f"(tenant, item) records  : {report['n_records']}")
    lines.append(f"tenants                 : {', '.join(report['tenants'])}")
    lines.append("")
    lines.append("retired-list filter:")
    lines.append(f"    item-scope keys     : {len(report.get('retired_items', []))} "
                 f"(rows dropped: {report.get('dropped_by_item', 0)})")
    lines.append(f"    question_x_id-scope : {len(report.get('retired_xids', []))} "
                 f"(rows dropped: {report.get('dropped_by_xid', 0)})")
    for it in report.get("retired_items", []):
        lines.append(f"        [item] {it}")
    for x in report.get("retired_xids", []):
        lines.append(f"        [question_x_id] {x}")
    lines.append("")
    lines.append(f"uncalibrated items (no calibration row): {len(report['uncalibrated'])} "
                 f"(rows dropped from lookup: {report.get('dropped_uncalibrated_rows', 0)})")
    for it in report["uncalibrated"]:
        lines.append(f"    {it}")
    lines.append("")
    lines.append(f"(tenant, item) pairs resolved by tiebreak (multi-id): {len(report['multi_id'])}")
    for tenant, item, xids, chosen in report["multi_id"]:
        lines.append(f"    [{tenant}] {item}")
        lines.append(f"        candidates: {xids}")
        lines.append(f"        chosen    : {chosen}")
    lines.append("")
    if report["flag_conflicts"]:
        lines.append(f"WARNING: flag conflicts within (tenant, item): {len(report['flag_conflicts'])}")
        for tenant, item, tag in report["flag_conflicts"]:
            lines.append(f"    [{tenant}] {item} :: {tag}")
    else:
        lines.append("flag conflicts within (tenant, item): none")
    path.write_text("\n".join(lines) + "\n")
def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workbook", required=True, help="Shared multi-tenant workbook (.xlsx)")
    p.add_argument("--params", default="", help="question_parameters.csv (for the uncalibrated-items report)")
    p.add_argument("--retired", default="", help="retired_questions_v2.csv (canonical 27-item list; item / question_x_id scope)")
    p.add_argument("--out-dir", default=".", help="Output directory")
    p.add_argument("--no-gate", action="store_true", help="Skip the class-one zero_minus_x gate (emit geometric flags)")
    a = p.parse_args(argv)
    out_dir = Path(a.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wb = pd.read_excel(a.workbook)
    calibrated = None
    if a.params:
        calibrated = pd.read_csv(a.params)["item"].unique()
    retired_items, retired_xids = (set(), set())
    if a.retired:
        retired_items, retired_xids = load_retired(a.retired)
    lookup, report = build_lookup(wb, calibrated_items=calibrated, gate=not a.no_gate,
                                  retired_items=retired_items, retired_xids=retired_xids)
    lookup_path = out_dir / "tenant_question_lookup.csv"
    lookup.to_csv(lookup_path, index=False)
    write_report(report, out_dir / "build_report.txt")
    print(f"wrote {lookup_path} ({len(lookup)} records across {len(report['tenants'])} tenants)")
    print(f"wrote {out_dir / 'build_report.txt'}")
    return lookup, report
if __name__ == "__main__":
    main()
