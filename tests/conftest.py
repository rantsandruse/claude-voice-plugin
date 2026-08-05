import tempfile
import shutil
from pathlib import Path
import pytest


@pytest.fixture
def tmp_path(tmp_path_factory):
    """Override tmp_path to use a short base dir.

    macOS enforces a 104-character limit on AF_UNIX socket paths.  The default
    pytest tmp_path often lives under /private/var/folders/… which easily
    exceeds that limit.  By placing our temp dirs under /tmp/pt<n>/ the full
    path stays well under 104 characters.
    """
    base = Path(tempfile.mkdtemp(prefix="pt", dir="/tmp"))
    yield base
    shutil.rmtree(base, ignore_errors=True)
