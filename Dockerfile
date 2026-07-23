FROM --platform=linux/amd64 python:3.11-slim

WORKDIR /opt/dynamic-diagnostic

COPY diagnostic_engine_v9/requirements.txt ./requirements.txt
# openpyxl is needed only by `python -m engine.cli seed-lattice` (reads the
# lattice XLSX); included so the one-time seed job can run from this image.
RUN pip install --no-cache-dir -r requirements.txt openpyxl==3.1.5

COPY diagnostic_engine_v9/engine ./engine
COPY diagnostic_engine_v9/stage_b_classifier ./stage_b_classifier
COPY diagnostic_engine_v9/config ./config
COPY diagnostic_engine_v9/data ./data
COPY diagnostic_engine_v9/inputs ./inputs
COPY diagnostic_engine_v9/artifact ./artifact

# Defaults point at the files baked into this image; the helm chart overrides
# ENGINE_CONFIG_PATH to the ConfigMap-mounted copy at /config.
ENV ENGINE_CONFIG_PATH=/opt/dynamic-diagnostic/config/engine_config_seeded.yaml \
    QUESTION_PARAMETERS_PATH=/opt/dynamic-diagnostic/data/question_parameters.csv \
    TENANT_QUESTION_LOOKUP_PATH=/opt/dynamic-diagnostic/inputs/tenant_question_lookup_v2.csv \
    RETIRED_LIST_PATH=/opt/dynamic-diagnostic/inputs/retired_questions_v2.csv \
    OFFLINE_ARTIFACT_DIR=/opt/dynamic-diagnostic/artifact

RUN groupadd -g 1000 engine && useradd -u 1000 -g engine -M engine
USER engine

EXPOSE 4001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:4001/health', timeout=4)"

CMD ["uvicorn", "engine.api.main:app", "--host", "0.0.0.0", "--port", "4001"]
