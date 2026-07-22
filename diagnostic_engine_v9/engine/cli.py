"""
Command-line entry point for the diagnostic engine.

Usage:
    python -m engine.cli seed-config --milestone-mapping FILE --priors FILE \
        --anchors FILE --output FILE
    python -m engine.cli seed-lattice --input FILE
    python -m engine.cli simulate-session --grade N --config FILE
    python -m engine.cli validate-config --config FILE
    python -m engine.cli cleanup --config FILE [--lattice FILE] [--limit N]

Each subcommand returns an integer exit code. main() catches CliInputError
and validation errors and prints a clean message rather than a traceback.
"""

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Set, TextIO

import yaml
from prometheus_client import CollectorRegistry
from pydantic import ValidationError

from engine.cli_io import (
    CliInputError,
    cross_validate,
    load_anchors,
    load_lattice_edges,
    load_milestone_mapping,
    load_priors,
)
from engine.cleanup import run_cleanup
from engine.config import EngineConfig, load_engine_config
from engine.lattice import LatticeIndex
from engine.observability.logging import configure_logging, get_logger
from engine.observability.metrics import register_metrics
from engine.question_pool import StubQuestionPool
from engine.session import RoutingMode, end_session, record_response, start_session
from engine.storage import get_storage_backend
from engine.storage.memory import InMemoryStorage

# Operations included in the engine's scope. Numbers is excluded per
# project decision (4 operations: Add, Subtract, Multiply, Divide).
DEFAULT_OPERATIONS: Set[str] = {"Addition", "Subtraction", "Multiplication", "Division"}

# Default budgets and operation orders for the four supported grades.
# These match the values agreed in the design phase (handover section 4).
_DEFAULT_BUDGETS = {
    2: {"total": 25, "per_operation": 6,  "per_operation_cap_multiplier": 1.5, "reserve_size": 7},
    3: {"total": 42, "per_operation": 9,  "per_operation_cap_multiplier": 1.5, "reserve_size": 11},
    4: {"total": 59, "per_operation": 13, "per_operation_cap_multiplier": 1.5, "reserve_size": 15},
    5: {"total": 76, "per_operation": 16, "per_operation_cap_multiplier": 1.5, "reserve_size": 19},
}
_DEFAULT_OPERATION_ORDER = {
    2: ["Multiplication", "Addition", "Subtraction", "Division"],
    3: ["Multiplication", "Addition", "Subtraction", "Division"],
    4: ["Multiplication", "Addition", "Subtraction", "Division"],
    5: ["Division", "Addition", "Subtraction", "Multiplication"],
}
_DEFAULT_MISCONCEPTION = {
    "target": 2,
    "conditional_extra": 2,
    "clear_threshold": 0.75,
    "present_threshold": 0.50,
}

_DEFAULT_ALGORITHM = {
    "slip": 0.10,
    "guess": 0.15,
    "mastery_threshold": 0.95,
    "not_mastered_threshold": 0.10,
    "verification_trigger_high": 0.85,
    "verification_trigger_low": 0.15,
    "edge_propagation_value": 0.90,
    "info_gain_edge_bonus": 0.5,
}


# === seed-config ============================================================


def cmd_seed_config(args: argparse.Namespace, stderr: TextIO = sys.stderr) -> int:
    """Generate engine_config.yaml from the canonical source files."""
    allowed_ops = set(args.operations) if args.operations else DEFAULT_OPERATIONS

    print(f"loading milestone mapping from {args.milestone_mapping}...", file=stderr)
    skills = load_milestone_mapping(args.milestone_mapping, allowed_operations=allowed_ops)
    print(f"  loaded {len(skills)} skills", file=stderr)

    print(f"loading priors from {args.priors}...", file=stderr)
    priors = load_priors(args.priors, allowed_operations=allowed_ops)
    total_priors = sum(len(p) for p in priors.values())
    print(f"  loaded {total_priors} priors across grades {sorted(priors)}", file=stderr)

    print(f"loading anchors from {args.anchors}...", file=stderr)
    anchors = load_anchors(args.anchors, allowed_operations=allowed_ops)
    total_anchors = sum(len(a) for a in anchors.values())
    print(f"  loaded {total_anchors} anchors across grades {sorted(anchors)}", file=stderr)

    warnings = cross_validate(skills=skills, anchors=anchors, priors=priors)
    for w in warnings:
        print(f"  WARNING: {w}", file=stderr)

    config_dict = _build_engine_config_dict(
        skills=skills, anchors=anchors, priors=priors,
    )

    # Validate the constructed config by round-tripping through the Pydantic
    # model. This catches anything the source files lack (e.g. anchors for a
    # grade that has no entries in the priors file).
    try:
        EngineConfig.model_validate(config_dict)
    except ValidationError as e:
        print(f"ERROR: constructed config failed validation:\n{e}", file=stderr)
        return 2

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as f:
        # default_flow_style=False forces block style (one key per line).
        yaml.safe_dump(config_dict, f, default_flow_style=False, sort_keys=False)
    print(f"wrote {output_path} ({output_path.stat().st_size} bytes)", file=stderr)
    return 0


def _build_engine_config_dict(
    *,
    skills: List[Dict],
    anchors: Dict[int, Dict[str, str]],
    priors: Dict[int, Dict[str, float]],
) -> Dict:
    """Assemble the dict that will be written as engine_config.yaml.

    Uses the project's canonical defaults for algorithm parameters, budgets,
    and operation orders (these aren't derived from the source CSVs - they
    come from the design phase).

    For each grade configured in budgets, ensures that anchors[g] and
    priors[g] both exist (creating empty dicts if the source CSVs don't
    cover that grade). The engine defaults missing-prior skills to 0.5 at
    runtime, so an empty priors dict is acceptable.
    """
    # Defensive: copy so callers' dicts aren't mutated.
    anchors_out = {g: dict(a) for g, a in anchors.items()}
    priors_out = {g: dict(p) for g, p in priors.items()}

    # Fill empty entries for every grade in budgets.
    for g in _DEFAULT_BUDGETS:
        anchors_out.setdefault(g, {})
        priors_out.setdefault(g, {})

    return {
        "version": "0.7.0",
        "algorithm": dict(_DEFAULT_ALGORITHM),
        "misconception": dict(_DEFAULT_MISCONCEPTION),
        "budgets": {g: dict(b) for g, b in _DEFAULT_BUDGETS.items()},
        "operation_order": {g: list(o) for g, o in _DEFAULT_OPERATION_ORDER.items()},
        "skills": [
            {"name": s["name"], "operation": s["operation"],
             "sequence": s["sequence"], "content_grade": s["content_grade"]}
            for s in sorted(skills, key=lambda s: s["sequence"])
        ],
        "anchors": {g: anchors_out[g] for g in sorted(anchors_out)},
        "priors": {g: priors_out[g] for g in sorted(priors_out)},
    }


# === seed-lattice ===========================================================


def cmd_seed_lattice(args: argparse.Namespace, stderr: TextIO = sys.stderr) -> int:
    """Load lattice edges from XLSX into the configured storage backend."""
    print(f"loading lattice edges from {args.input}...", file=stderr)
    edges = load_lattice_edges(args.input)
    print(f"  loaded {len(edges)} edges", file=stderr)
    for e in edges:
        kind = "multi-view" if e.weight >= 1.0 else "single-view"
        same_op = "within-op" if e.operation_a == e.operation_b else "cross-op"
        print(
            f"    {e.skill_a} ({e.operation_a}) -> {e.skill_b} ({e.operation_b}) "
            f"| p(B|A)={e.p_b_given_a:.3f}, {kind}, {same_op}",
            file=stderr,
        )

    storage = (
        get_storage_backend(backend=args.storage) if args.storage
        else get_storage_backend()
    )
    print(f"writing to storage backend {type(storage).__name__}...", file=stderr)
    storage.save_lattice_edges(edges)
    print("done.", file=stderr)
    return 0


# === simulate-session ======================================================


@dataclass
class _SimulationSummary:
    grade: int
    policy: str
    questions_asked: int
    end_reason: str
    verdicts: List


def cmd_simulate_session(args: argparse.Namespace, stderr: TextIO = sys.stderr) -> int:
    """Drive a session end-to-end through the engine functions with synthetic answers."""
    config = load_engine_config(args.config)

    if args.lattice:
        print(f"loading lattice from {args.lattice}...", file=stderr)
        edges = load_lattice_edges(args.lattice)
        lattice_index = LatticeIndex(edges)
        print(f"  loaded {len(edges)} edges", file=stderr)
    else:
        lattice_index = LatticeIndex([])
        print("no lattice provided; running with empty lattice", file=stderr)

    storage = InMemoryStorage()
    pool = StubQuestionPool()

    try:
        params = config.get_engine_params(args.grade, lattice_index)
    except ValueError as e:
        print(f"ERROR: cannot build engine params for grade {args.grade}: {e}", file=stderr)
        return 2

    print(
        f"\n=== simulate-session: grade={args.grade}, policy={args.policy}, "
        f"budget={params.routing_config.total_budget} ===",
        file=stderr,
    )

    sub_session_id = args.sub_session_id or f"sim-g{args.grade}-{args.policy}"
    start_result = start_session(
        sub_session_id=sub_session_id,
        learner_id="sim-learner",
        tenant_id="sim-tenant",
        class_id="sim-class",
        grade=args.grade,
        engine_version="cli-sim",
        params=params,
    )
    storage.save_session(start_result.session)

    if start_result.first_question is None:
        print("engine returned no first question; nothing to simulate.", file=stderr)
        return 0

    current_q = start_result.first_question
    answers = 0
    max_iter = params.routing_config.total_budget + 10  # safety cap
    end_reason = "natural"
    verdicts = []

    while current_q is not None and answers < max_iter:
        pick = pool.pick_question_for_skill(
            skill=current_q.skill,
            session=start_result.session,
            grade=args.grade,
            tenant_id="sim-tenant",
        )
        is_correct = _answer_for_policy(
            policy=args.policy,
            skill=current_q.skill,
            params=params,
        )
        try:
            rr = record_response(
                start_result.session,
                skill_id=current_q.skill,
                question_id=pick.question_id,
                is_correct=is_correct,
                params=params,
                routing_mode=RoutingMode.ONLINE,
                slip_override=pick.slip_override,
                guess_override=pick.guess_override,
            )
        except Exception as e:
            print(f"ERROR: record_response failed at question {answers + 1}: {e}", file=stderr)
            return 3

        answers += 1
        posterior_after = start_result.session.posteriors.get(current_q.skill, 0.5)
        print(
            f"  Q{answers:2d}: {current_q.skill[:40]:40s} ({current_q.purpose.value:14s}) "
            f"-> {'CORRECT' if is_correct else 'WRONG  '} | posterior={posterior_after:.3f}",
            file=stderr,
        )
        if rr.next_question is None:
            verdicts = rr.verdicts or []
            end_reason = "natural"
            current_q = None
        else:
            current_q = rr.next_question

    if current_q is not None:
        # Did not complete naturally within max_iter; force end.
        from engine.session import EndReason
        er = end_session(start_result.session, reason=EndReason.ABANDONED, params=params)
        verdicts = er.verdicts
        end_reason = "abandoned (max iterations reached)"

    print(f"\n=== summary ===", file=stderr)
    print(f"questions asked : {answers}", file=stderr)
    print(f"end reason      : {end_reason}", file=stderr)
    print(f"verdicts        : {len(verdicts)} skills", file=stderr)
    by_label: Dict[str, int] = {}
    for v in verdicts:
        by_label[v.confidence_label.value] = by_label.get(v.confidence_label.value, 0) + 1
    for label in sorted(by_label):
        print(f"  {label:12s}: {by_label[label]}", file=stderr)
    return 0


def _answer_for_policy(*, policy: str, skill: str, params) -> bool:
    """Return is_correct for a question on `skill` under the given answer policy."""
    if policy == "all-correct":
        return True
    if policy == "all-incorrect":
        return False
    if policy == "by-prior":
        # Correct iff the cohort prior says "more likely mastered than not".
        # Skills without an explicit prior fall back to 0.5 (treated as wrong here).
        return params.priors.get(skill, 0.5) > 0.5
    raise CliInputError(f"unknown policy: {policy}")


# === cleanup ================================================================


def cmd_cleanup(args: argparse.Namespace, stderr: TextIO = sys.stderr) -> int:
    """Find complete sessions without verdicts and back-fill them.

    Intended for a Kubernetes CronJob; see README "Cleanup CronJob"
    section. The function emits structured JSON logs (one per session
    recovered, one summary at the end) so log aggregators can monitor
    recovery counts.

    Metrics: cleanup increments the spec section 9.1 cleanup counters
    (`diagnostic_cleanup_job_runs_total`,
    `diagnostic_cleanup_job_recovered_sessions_total`). Because a one-shot
    CLI process cannot be scraped by Prometheus directly, the counters are
    pushed to a Prometheus Pushgateway when the PROMETHEUS_PUSHGATEWAY_URL
    env var is set. When it is not set, the counts are still emitted in the
    summary log line, and a single note records that no Pushgateway was
    configured.

    Exit codes:
      0  - all examined sessions recovered successfully (or none found)
      1  - one or more per-session recoveries failed (see logs)
      2  - configuration or I/O error before any session was processed
    """
    # Configure structlog so cleanup logs go to stdout in the same JSON
    # format the engine itself uses. The CLI normally doesn't configure
    # logging; only cleanup explicitly does because its log output IS the
    # operator's primary feedback channel.
    configure_logging(level="info", fmt="json", version="cleanup-cli")

    try:
        config = load_engine_config(args.config)
    except (FileNotFoundError, ValidationError, yaml.YAMLError, ValueError) as e:
        print(f"ERROR: cannot load config: {e}", file=stderr)
        return 2

    # Lattice is optional for cleanup. compute_verdicts reads session
    # posteriors directly (which already had propagation applied during
    # the live session); it does not re-propagate. An empty LatticeIndex
    # is therefore safe.
    if args.lattice:
        try:
            edges = load_lattice_edges(args.lattice)
            lattice = LatticeIndex(edges)
        except (FileNotFoundError, CliInputError) as e:
            print(f"ERROR: cannot load lattice: {e}", file=stderr)
            return 2
    else:
        lattice = LatticeIndex([])

    try:
        storage = (
            get_storage_backend(backend=args.storage) if args.storage
            else get_storage_backend()
        )
    except Exception as e:
        print(f"ERROR: cannot connect to storage: {e}", file=stderr)
        return 2

    # Fresh registry for this one-shot run. The cleanup counters live here;
    # run_cleanup increments them. We push the registry to a Pushgateway if
    # one is configured, since a short-lived CLI process can't be scraped.
    registry = CollectorRegistry()
    metrics = register_metrics(registry)

    result = run_cleanup(
        storage=storage,
        config=config,
        lattice_index=lattice,
        limit=args.limit,
        metrics=metrics,
    )

    _push_cleanup_metrics(registry)

    return 0 if result.all_successful else 1


def _push_cleanup_metrics(registry: CollectorRegistry) -> None:
    """Push the cleanup metrics registry to a Pushgateway if one is configured.

    Reads PROMETHEUS_PUSHGATEWAY_URL (e.g. "pushgateway.monitoring:9091").
    When unset, logs a single note that metrics were not exported; the
    summary counts are still in the logs. Push failures are logged at WARN
    and do not change the cleanup exit code (the recovery work already
    succeeded or failed independently of metric export).
    """
    log = get_logger("engine.cleanup")
    gateway = os.environ.get("PROMETHEUS_PUSHGATEWAY_URL")
    if not gateway:
        log.info(
            "cleanup: PROMETHEUS_PUSHGATEWAY_URL not set; cleanup metrics were "
            "computed but not exported to Prometheus (counts are in the logs above)"
        )
        return
    try:
        from prometheus_client import push_to_gateway
        push_to_gateway(gateway, job="engine_cleanup", registry=registry)
        log.info(f"cleanup: pushed cleanup metrics to Pushgateway at {gateway}")
    except Exception as e:
        log.warning(
            f"cleanup: failed to push metrics to Pushgateway at {gateway}: "
            f"{type(e).__name__}: {e}"
        )


# === validate-config ========================================================


def cmd_validate_config(args: argparse.Namespace, stderr: TextIO = sys.stderr) -> int:
    """Load engine_config.yaml and report any validation errors."""
    try:
        config = load_engine_config(args.config)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=stderr)
        return 2
    except ValidationError as e:
        print(f"ERROR: validation failed:\n{e}", file=stderr)
        return 2
    except (yaml.YAMLError, ValueError) as e:
        print(f"ERROR: cannot parse config: {e}", file=stderr)
        return 2

    print(f"{args.config}: valid", file=stderr)
    print(f"  version          : {config.version}", file=stderr)
    print(f"  grades           : {sorted(config.budgets)}", file=stderr)
    print(f"  skills           : {len(config.skills)}", file=stderr)
    print(f"  anchors (entries): {sum(len(a) for a in config.anchors.values())}", file=stderr)
    print(f"  priors  (entries): {sum(len(p) for p in config.priors.values())}", file=stderr)

    # Try to build EngineParams for each configured grade.
    lattice = LatticeIndex([])
    for grade in sorted(config.budgets):
        try:
            params = config.get_engine_params(grade, lattice)
            in_scope = len(params.skills_in_scope)
            print(f"  G{grade}: builds OK, {in_scope} skills in scope", file=stderr)
        except ValueError as e:
            print(f"  G{grade}: BUILD FAILED: {e}", file=stderr)
            return 2
    return 0


# === argument parsing =======================================================


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="engine",
        description="AML dynamic diagnostic engine CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # seed-config
    p = sub.add_parser(
        "seed-config",
        help="Generate engine_config.yaml from milestone CSV, priors CSV, anchors XLSX.",
    )
    p.add_argument("--milestone-mapping", required=True, help="path to milestone mapping CSV")
    p.add_argument("--priors", required=True, help="path to priors CSV (e.g. priors_table_delhi_only.csv)")
    p.add_argument("--anchors", required=True, help="path to anchor_recommendations_v3.xlsx")
    p.add_argument("--output", required=True, help="path to write engine_config.yaml")
    p.add_argument(
        "--operations", nargs="+", default=None,
        help="Operations to include (default: Addition Subtraction Multiplication Division)",
    )
    p.set_defaults(func=cmd_seed_config)

    # seed-lattice
    p = sub.add_parser(
        "seed-lattice",
        help="Load lattice edges from XLSX into the configured storage backend.",
    )
    p.add_argument("--input", required=True, help="path to lattice_edges_final.xlsx")
    p.add_argument(
        "--storage", default=None,
        help="Storage backend: 'memory' or 'mongodb' (default: $STORAGE_BACKEND or 'memory').",
    )
    p.set_defaults(func=cmd_seed_lattice)

    # simulate-session
    p = sub.add_parser(
        "simulate-session",
        help="Drive a full session end-to-end through the engine with synthetic answers.",
    )
    p.add_argument("--grade", type=int, required=True, choices=[2, 3, 4, 5, 6, 7, 8])
    p.add_argument(
        "--policy", default="all-correct",
        choices=["all-correct", "all-incorrect", "by-prior"],
        help="Synthetic answer policy.",
    )
    p.add_argument("--config", required=True, help="path to engine_config.yaml")
    p.add_argument("--lattice", default=None, help="path to lattice_edges_final.xlsx (optional)")
    p.add_argument("--sub-session-id", default=None, help="explicit sub-session id (default: auto)")
    p.set_defaults(func=cmd_simulate_session)

    # validate-config
    p = sub.add_parser(
        "validate-config",
        help="Load engine_config.yaml and report validation errors. Returns non-zero on failure.",
    )
    p.add_argument("--config", required=True, help="path to engine_config.yaml")
    p.set_defaults(func=cmd_validate_config)

    # cleanup
    p = sub.add_parser(
        "cleanup",
        help=(
            "Back-fill verdicts for complete sessions whose verdict write "
            "crashed. Intended as a Kubernetes CronJob; see README."
        ),
    )
    p.add_argument("--config", required=True, help="path to engine_config.yaml")
    p.add_argument(
        "--lattice", default=None,
        help=(
            "path to lattice_edges_final.xlsx (optional; compute_verdicts "
            "does not re-propagate, so an empty lattice is safe)"
        ),
    )
    p.add_argument(
        "--storage", default=None,
        help="Storage backend: 'memory' or 'mongodb' (default: $STORAGE_BACKEND or 'memory').",
    )
    p.add_argument(
        "--limit", type=int, default=100,
        help="Maximum sessions to process in this run (default: 100).",
    )
    p.set_defaults(func=cmd_cleanup)

    return parser


def main(argv: Optional[List[str]] = None, *, stderr: TextIO = sys.stderr) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args, stderr=stderr)
    except CliInputError as e:
        print(f"ERROR: {e}", file=stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
