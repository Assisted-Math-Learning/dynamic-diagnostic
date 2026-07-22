"""Test package.

DATA_DIR resolves the real-data files (question_parameters.csv, priors,
anchors, lattice, milestone mapping) used by the real-data tests. It defaults
to the repo's ``data/`` directory so the suite runs from a clean checkout with
no hardcoded absolute paths; set the ``AML_TEST_DATA_DIR`` environment variable
to point the real-data tests at an out-of-tree copy.
"""
import os
from pathlib import Path

DATA_DIR = Path(
    os.environ.get("AML_TEST_DATA_DIR", str(Path(__file__).resolve().parent.parent / "data"))
)
