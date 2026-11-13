"""The pre-push guard (tools/check_private.py): what it flags and how it reads git's push input."""
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_private as C  # noqa: E402

PERSONAL = ["Alex Rivera", "alex.rivera@example.edu", "Zorbify"]


def test_flags_personal_details_in_files():
    hits = C.find({"README.md": "Built by Alex Rivera for Zorbify."}, PERSONAL)
    assert len(hits) == 2 and all(h.startswith("README.md") for h in hits)


def test_whole_words_only():
    assert not C.find({"a.py": "zorbifying the data"}, PERSONAL)


def test_file_names_are_checked_too():
    assert C.find({"docs/alex rivera notes.md": ""}, PERSONAL)


def test_project_url_with_the_handle_is_allowed():
    assert not C.find({"site/index.html": "github.com/Zorbify/employMint"}, PERSONAL, ["github.com/Zorbify/employMint"])


def test_reads_pushed_ranges_and_skips_branch_deletes():
    zero = C.ZERO
    stdin = io.StringIO(f"refs/heads/main {'a' * 40} refs/heads/main {'b' * 40}\n"
                        f"(delete) {zero} refs/heads/old {'c' * 40}\n")
    assert C.pushed_ranges(stdin) == [("a" * 40, "b" * 40)]
