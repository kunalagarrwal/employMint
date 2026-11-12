"""The public export keeps an existing public repo's history and never lets personal strings through."""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import export_public as X  # noqa: E402


def test_prepare_keeps_git_history_and_clears_the_rest(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "old.txt").write_text("stale")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.py").write_text("x")
    assert X.prepare_dest(tmp_path) is True  # an existing repo: update in place
    assert (tmp_path / ".git").is_dir()
    assert sorted(p.name for p in tmp_path.iterdir()) == [".git"]


def test_prepare_fresh_folder(tmp_path):
    d = tmp_path / "new"
    assert X.prepare_dest(d) is False and d.is_dir()


def test_leaks_match_whole_words_only(tmp_path):
    (tmp_path / "a.md").write_text("A widgetry note for Widget Co.")
    (tmp_path / "b.py").write_text("programming is fine")
    found = X.leaks(tmp_path, ["Widget", "gram"])
    assert found == ["a.md: contains 'Widget'"]


def test_site_and_pages_workflow_are_shipped():
    assert "site" in X.ALLOW and ".github" in X.ALLOW


def test_site_images_allowed_other_binaries_blocked(tmp_path):
    (tmp_path / "site").mkdir()
    (tmp_path / "site" / "og.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\xff")
    (tmp_path / "data.sqlite").write_bytes(b"\x00\xff\xfe")
    found = X.leaks(tmp_path, [])
    assert found == ["data.sqlite: binary file (not allowed in the public copy)"]


def test_project_urls_are_allowed_but_the_handle_elsewhere_is_not(tmp_path):
    (tmp_path / "ok.html").write_text('<a href="https://github.com/someone/employMint">x</a> '
                                      'https://someone.github.io/employMint/')
    (tmp_path / "bad.md").write_text("Made by someone at https://github.com/someone")
    found = X.leaks(tmp_path, ["someone"], allowed=X.public_urls("someone"))
    assert found == ["bad.md: contains 'someone'"]
