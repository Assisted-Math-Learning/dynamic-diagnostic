"""Shared pytest fixtures."""
import pytest

from tests import DATA_DIR


@pytest.fixture
def data_dir():
    """Directory holding the real-data files (repo ``data/`` by default;
    override with the ``AML_TEST_DATA_DIR`` environment variable)."""
    return DATA_DIR
