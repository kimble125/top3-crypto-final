"""시험 공통: 패키지 경로와 임시 DB."""
import os
import sys
import tempfile

PKG_PARENT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)


def temp_db() -> tuple[str, tempfile.TemporaryDirectory]:
    d = tempfile.TemporaryDirectory()
    return os.path.join(d.name, "test.db"), d
