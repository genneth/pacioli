import pytest

@pytest.fixture
def temp_data_dir(tmp_path):
    """Provides a temporary data directory for tests."""
    d = tmp_path / "data"
    d.mkdir()
    return str(d)
