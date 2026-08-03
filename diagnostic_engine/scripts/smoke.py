#!/usr/bin/env python3
"""
End-to-end smoke test for the AML diagnostic engine.

What this script does:
  1. Loads the five canonical data files (milestone CSV, priors CSV, anchors
     XLSX, lattice XLSX, question_parameters CSV) from the bundled data/ dir
     (default) or a path supplied via --data-dir.
  2. Builds an EngineConfig + LatticeIndex from them.
  3. Constructs a real FastAPI app with in-memory storage.
  4. Drives a session through HTTP using FastAPI's TestClient (no uvicorn
     needed):
       - POST /session/start
       - POST /session/:id/response  (loop until session_complete=true)
       - GET  /session/:id/verdicts
  5. Verifies the response envelopes, prints a human-readable report.
  6. Exits 0 on success, non-zero on any failure.

Usage:
    python scripts/smoke.py                          # uses bundled data/
    python scripts/smoke.py --data-dir /path/to/data # custom data dir
    python scripts/smoke.py --grade 5                # different grade

This script is the demo end-to-end of the prototype. CI should run it on
every build to confirm the engine is wired up correctly with real data.
"""

import argparse
import sys
from pathlib import Path
from typing import Optional

# Add the repo root to sys.path so the script works when invoked directly.
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient    # noqa: E402

from engine.api.main import create_app       # noqa: E402
from engine.cli_io import (                  # noqa: E402
    load_anchors, load_lattice_edges, load_milestone_mapping, load_priors,
)
from engine.cli import (                     # noqa: E402
    DEFAULT_OPERATIONS, _build_engine_config_dict,
)
from engine.config import EngineConfig       # noqa: E402
from engine.lattice import LatticeIndex      # noqa: E402
from engine.question_pool import CsvQuestionPool  # noqa: E402
from engine.storage.memory import InMemoryStorage  # noqa: E402

# ---------------------------------------------------------------------------

TENANT_ID = "smoke-tenant"
TOKEN = "smoke-token"
LEARNER_ID = "smoke-learner"
CLASS_ID = "smoke-class"
SUB_SESSION_ID = "smoke-session-001"
ENGINE_VERSION = "0.9.0-smoke"


def _color(text: str, code: str) -> str:
    """ANSI colour wrap, no-op when stdout is not a TTY."""
    if not sys.stdout.isatty():
        return text
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str: return _color(text, "32")
def red(text: str) -> str:   return _color(text, "31")
def bold(text: str) -> str:  return _color(text, "1")


# === Steps =================================================================


def step_1_load_data(data_dir: Path) -> tuple:
    print(bold("\n[1/5] loading canonical data files..."))
    files = {
        "milestone": data_dir / "20260518_AML_Telangana_Milestone_and_Level_Mapping.csv",
        # Delhi-only priors derived from raw Delhi diagnostic responses
        # (n_DL >= 130 per skill). The earlier priors_table.csv was computed
        # from MainD response data, a selection-biased subset of learners
        # who had already progressed past each skill, and produced
        # uniformly-high priors that made the engine declare almost every
        # skill mastered without asking real questions. See CHANGES.md.
        "priors": data_dir / "priors_table_delhi_only.csv",
        "anchors": data_dir / "anchor_recommendations_v3.xlsx",
        "lattice": data_dir / "lattice_edges_final.xlsx",
        # Calibration output read by CsvQuestionPool: one row per (question,
        # grade) with calibrated slip / guess / discrimination.
        "question_params": data_dir / "question_parameters.csv",
    }
    for label, p in files.items():
        if not p.exists():
            print(red(f"  MISSING: {label} = {p}"))
            sys.exit(2)
        print(f"  found: {label:10s} = {p}")

    skills = load_milestone_mapping(str(files["milestone"]), allowed_operations=DEFAULT_OPERATIONS)
    priors = load_priors(str(files["priors"]), allowed_operations=DEFAULT_OPERATIONS)
    anchors = load_anchors(str(files["anchors"]), allowed_operations=DEFAULT_OPERATIONS)
    edges = load_lattice_edges(str(files["lattice"]))
    print(f"  loaded {len(skills)} skills, {len(edges)} edges, "
          f"{sum(len(p) for p in priors.values())} priors, "
          f"{sum(len(a) for a in anchors.values())} anchors")
    return skills, priors, anchors, edges, files["question_params"]


def step_2_build_config(skills, priors, anchors) -> EngineConfig:
    print(bold("\n[2/5] building EngineConfig..."))
    config_dict = _build_engine_config_dict(
        skills=skills, anchors=anchors, priors=priors,
    )
    config = EngineConfig.model_validate(config_dict)
    print(f"  config built: {len(config.skills)} skills, "
          f"grades {sorted(config.budgets)}")
    return config


def step_3_build_app(config: EngineConfig, edges, question_params_path: Path, seed=None,
                     lookup_path=None) -> TestClient:
    print(bold("\n[3/5] constructing FastAPI app..."))
    storage = InMemoryStorage()
    storage.save_lattice_edges(edges)
    lattice = LatticeIndex(edges)
    # Use the real CsvQuestionPool so the session trace shows real q_x_ids and
    # the Bayes update uses each question's calibrated slip / guess. Pass the
    # scope skills so a content-pool gap (a scope skill with no questions)
    # surfaces as a startup WARNING. seed is None by default (random, matches
    # production); pass --seed for a reproducible run. When a tenant lookup is
    # supplied the pool resolves tenant-scoped question_x_ids and applies the
    # tenant-availability filter; this smoke then runs as tenant TENANT_ID.
    pool = CsvQuestionPool(
        str(question_params_path),
        expected_skills={s.name for s in config.skills},
        seed=seed,
        lookup_path=str(lookup_path) if lookup_path else None,
    )
    mode = f"tenant-aware ({TENANT_ID})" if lookup_path else "legacy (no tenant lookup)"
    print(f"  question pool: CsvQuestionPool ({len(pool.available_skills)} skills with questions), {mode}")
    app = create_app(
        config=config,
        storage=storage,
        lattice_index=lattice,
        tenant_tokens={TENANT_ID: TOKEN},
        engine_version=ENGINE_VERSION,
        question_pool=pool,
    )
    client = TestClient(app)
    health = client.get("/health").json()
    if health.get("status") != "ok":
        print(red(f"  /health is not OK: {health}"))
        sys.exit(2)
    print(f"  /health: status={health['status']}, version={health['version']}, storage={health['storage']}")
    return client


def step_4_drive_session(client: TestClient, grade: int) -> dict:
    print(bold(f"\n[4/5] driving session for G{grade} learner (policy: all-correct)..."))
    headers = {"X-Internal-Service-Token": TOKEN}

    # POST /session/start
    r = client.post(
        "/api/v1/diagnostic/session/start",
        json={
            "learner_id": LEARNER_ID,
            "tenant_id": TENANT_ID,
            "sub_session_id": SUB_SESSION_ID,
            "class_id": CLASS_ID,
            "grade": grade,
        },
        headers=headers,
    )
    if r.status_code != 200:
        print(red(f"  session/start failed: {r.status_code} {r.text}"))
        sys.exit(2)
    start = r.json()
    if start["params"]["status"] != "SUCCESS":
        print(red(f"  envelope status not SUCCESS: {start}"))
        sys.exit(2)
    first_q = start["result"]["first_question"]
    budget = start["result"]["question_budget"]
    print(f"  session started. budget={budget}, first question on '{first_q['skill_id']}'")

    # POST /session/:id/response in a loop until session_complete
    current_q = first_q
    answers = 0
    max_iter = budget + 10
    final_result: Optional[dict] = None

    while current_q is not None and answers < max_iter:
        r = client.post(
            f"/api/v1/diagnostic/session/{SUB_SESSION_ID}/response",
            json={
                "learner_id": LEARNER_ID,
                "tenant_id": TENANT_ID,
                "skill_id": current_q["skill_id"],
                "question_x_id": current_q["question_x_id"],
                "is_correct": True,  # all-correct policy
            },
            headers=headers,
        )
        if r.status_code != 200:
            print(red(f"  response[{answers + 1}] failed: {r.status_code} {r.text}"))
            sys.exit(2)
        body = r.json()
        if body["params"]["status"] != "SUCCESS":
            print(red(f"  envelope status not SUCCESS at response[{answers + 1}]: {body}"))
            sys.exit(2)
        answers += 1
        result = body["result"]
        skill = current_q["skill_id"]
        print(f"  Q{answers:2d}: {skill[:50]:50s} -> CORRECT")
        if result["session_complete"]:
            final_result = result
            current_q = None
        else:
            current_q = result["next_question"]

    if final_result is None:
        print(red(f"  session did not complete within {max_iter} questions"))
        sys.exit(2)

    print(f"  session complete after {answers} questions. {len(final_result['verdicts'])} verdicts produced.")
    return final_result


def step_5_fetch_verdicts(client: TestClient, final_result: dict) -> None:
    print(bold("\n[5/5] re-fetching verdicts via GET /verdicts..."))
    r = client.get(
        f"/api/v1/diagnostic/session/{SUB_SESSION_ID}/verdicts",
        headers={"X-Internal-Service-Token": TOKEN},
    )
    if r.status_code != 200:
        print(red(f"  verdicts fetch failed: {r.status_code} {r.text}"))
        sys.exit(2)
    body = r.json()
    fetched = body["result"]["verdicts"]
    if len(fetched) != len(final_result["verdicts"]):
        print(red(f"  verdict count mismatch: "
                  f"fetched={len(fetched)}, expected={len(final_result['verdicts'])}"))
        sys.exit(2)

    print(f"  fetched {len(fetched)} verdicts.")

    print(bold("\nverdict summary:"))
    by_label: dict = {}
    for v in fetched:
        by_label.setdefault(v["confidence_label"], 0)
        by_label[v["confidence_label"]] += 1
    for label, count in sorted(by_label.items()):
        print(f"  {label:24s}: {count}")

    print(bold("\nverdicts by recommendation:"))
    by_rec: dict = {}
    for v in fetched:
        by_rec.setdefault(v["recommendation"], 0)
        by_rec[v["recommendation"]] += 1
    for rec, count in sorted(by_rec.items()):
        print(f"  {rec:24s}: {count}")


# === Entry point ===========================================================


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data-dir", default=str(Path(__file__).resolve().parent.parent / "data"),
        help="Directory containing the five canonical data files (default: the bundled data/ dir)",
    )
    parser.add_argument(
        "--grade", type=int, default=3, choices=[2, 3, 4, 5],
        help="Grade to simulate (default: 3)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Optional random seed for the question pool. Unset (default) "
             "matches production: selection is random and the verdict counts "
             "on borderline skills can vary by one between runs. Set a seed "
             "for a reproducible run (used to pin the documented distribution).",
    )
    parser.add_argument(
        "--lookup", default=None,
        help="Optional path to tenant_question_lookup.csv. When set, the pool "
             "resolves tenant-scoped question_x_ids and filters to items the "
             "tenant can serve; the run uses --tenant.",
    )
    parser.add_argument(
        "--tenant", default="Delhi",
        help="Tenant to run the session as (used when --lookup is set; default Delhi).",
    )
    args = parser.parse_args(argv)

    global TENANT_ID
    TENANT_ID = args.tenant

    data_dir = Path(args.data_dir)
    if not data_dir.is_dir():
        print(red(f"data dir not found: {data_dir}"))
        return 2

    print(bold("=== AML Diagnostic Engine smoke test ==="))
    print(f"data dir: {data_dir}")
    print(f"grade   : {args.grade}")
    print(f"seed    : {args.seed if args.seed is not None else 'unset (random)'}")
    print(f"tenant  : {TENANT_ID}{'' if args.lookup else ' (legacy, ignored)'}")

    skills, priors, anchors, edges, question_params_path = step_1_load_data(data_dir)
    config = step_2_build_config(skills, priors, anchors)
    client = step_3_build_app(config, edges, question_params_path, seed=args.seed,
                              lookup_path=args.lookup)
    final = step_4_drive_session(client, args.grade)
    step_5_fetch_verdicts(client, final)

    print(green(bold("\n=== smoke test PASSED ===")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
