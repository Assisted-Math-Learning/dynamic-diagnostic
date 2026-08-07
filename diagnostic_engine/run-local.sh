#!/usr/bin/env bash
# Start the v10 (0.10.0) dynamic diagnostic engine locally on :4001 (mongodb storage, Delhi tenant).
# One-time setup per clone: build the venv + seed the local config:
#   python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt -e . openpyxl httpx
#   ./.venv/bin/python -m engine.cli seed-config \
#     --milestone-mapping data/20260518_AML_Telangana_Milestone_and_Level_Mapping.csv \
#     --priors data/priors_table_delhi_only.csv --anchors data/anchor_recommendations_v3.xlsx \
#     --output config/engine_config.local.yaml
# Re-seed only if the data files change.
cd "$(dirname "$0")"
# Local seeded config (git-ignored). The committed config/engine_config.yaml is only a skeleton;
# re-run the seed-config command above if the data files change.
export ENGINE_CONFIG_PATH=$PWD/config/engine_config.local.yaml
# Persist sessions across engine restarts (a restart mid-diagnostic won't orphan the session).
# Switch STORAGE_BACKEND to `memory` for a throwaway run. DB defaults to `aml_engine` — a SEPARATE
# database from the BE's aml_service; the engine creates its collections on first start.
export STORAGE_BACKEND=mongodb
export MONGODB_URL=mongodb://localhost:27017
export QUESTION_PARAMETERS_PATH=$PWD/data/question_parameters.csv
export TENANT_QUESTION_LOOKUP_PATH=$PWD/inputs/tenant_question_lookup_v2.csv
export RETIRED_LIST_PATH=$PWD/inputs/retired_questions_v2.csv
# Karnataka is the tenant whose question lookup renders `_b` x_ids — the variant this local BE actually
# has (Delhi renders `_z`, which this BE lacks). Both registered so either name authenticates.
export TENANT_TOKENS_JSON='{"Delhi":"dev-secret","Karnataka":"dev-secret"}'
# ENGINE_VERSION intentionally NOT set — the engine defaults to its own package version
# (engine.__version__, currently 0.10.0), so the stamped verdict version tracks the code automatically.
echo "engine (v10, 0.10.0) → http://localhost:4001  (tenants Delhi+Karnataka, token 'dev-secret', storage mongodb→aml_engine)"
exec ./.venv/bin/uvicorn engine.api.main:app --host 0.0.0.0 --port 4001
