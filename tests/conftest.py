"""Shared tests run against the made-up sample applicant in examples/profile, so they pass on any fresh copy
and never depend on anyone's real details. Personal tests live in profile/tests (run: pytest profile/tests)."""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("EMPLOYMINT_PROFILE_DIR", str(ROOT / "examples" / "profile"))
sys.path.insert(0, str(ROOT / "src"))
