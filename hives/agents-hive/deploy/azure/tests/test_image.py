"""Tests for the image: every file a deployed passport names is in it.

The server refuses a passport whose files are missing, so a passport that names a file the
Dockerfile doesn't copy, or that .dockerignore keeps out of the build, deploys an app that
can't start, though every check that reads the repo passes.

Standard library only. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/deploy/azure/tests -p 'test_*.py'
"""
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
DEPLOYED = ("patricia", "barry")  # PERSONA's values: the passports the image runs


def named(passport):
    """The repo paths a passport names: its prompt files, its policy, its eval's suite and
    the results its baseline is in."""
    paths = [p["path"] for p in passport.get("pins", {}).get("prompt", [])]
    if "policy" in passport:
        paths.append(passport["policy"]["ruleset"])
    ev = passport.get("eval")
    if ev:
        paths.append(ev["suite"])
        paths.append(ev["baseline"]["result"].split("#")[0])
    return paths


def copied(dockerfile):
    """The sources of the Dockerfile's COPY lines."""
    sources = []
    for line in dockerfile.splitlines():
        words = line.split()
        if words[:1] == ["COPY"] and not any(w.startswith("--from") for w in words):
            sources += [w for w in words[1:-1] if not w.startswith("--")]
    return sources


def allowed(dockerignore):
    """The paths .dockerignore lets through: it ignores everything, then allows each."""
    lines = [line.strip() for line in dockerignore.splitlines()]
    lines = [line for line in lines if line and not line.startswith("#")]
    assert lines[0] == "*", ".dockerignore no longer starts by ignoring everything"
    return [line[1:] for line in lines[1:] if line.startswith("!")]


def covers(entries, path):
    return any(path == e or path.startswith(e.rstrip("/") + "/") for e in entries)


def image_tree(root):
    """The repo's files the image holds, under root: what a COPY line copies to the same path
    and .dockerignore lets through."""
    through = allowed((REPO / ".dockerignore").read_text(encoding="utf-8"))
    for line in (HERE.parent / "Dockerfile").read_text(encoding="utf-8").splitlines():
        words = [w for w in line.split() if not w.startswith("--")]
        if words[:1] != ["COPY"] or len(words) != 3 or words[1] != words[2]:
            continue  # only what keeps its repo path is read through REPO_ROOT
        src = REPO / words[1]
        files = [src] if src.is_file() else [f for f in src.rglob("*") if f.is_file()]
        for f in files:
            rel = f.relative_to(REPO).as_posix()
            if covers(through, rel) and "__pycache__" not in rel:
                (root / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, root / rel)


class Image(unittest.TestCase):
    def test_every_file_a_deployed_passport_names_is_copied_into_the_image(self):
        sources = copied((HERE.parent / "Dockerfile").read_text(encoding="utf-8"))
        through = allowed((REPO / ".dockerignore").read_text(encoding="utf-8"))
        for name in DEPLOYED:
            passport = json.loads((REPO / f"hives/agents-hive/passports/{name}/passport.json").read_text())
            for path in named(passport):
                with self.subTest(passport=name, path=path):
                    self.assertTrue((REPO / path).is_file(), "the passport names a file the repo doesn't have")
                    self.assertTrue(covers(sources, path), "no COPY line in the Dockerfile copies it")
                    self.assertTrue(covers(through, path), ".dockerignore keeps it out of the build")

    def test_each_deployed_passport_passes_the_servers_check_inside_the_image(self):
        root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        image_tree(root)
        script = root / "hives/agents-hive/scripts/validate_passports.py"
        spec = importlib.util.spec_from_file_location("validate_passports_in_image", script)
        vp = importlib.util.module_from_spec(spec)
        saved = list(sys.path)
        try:
            spec.loader.exec_module(vp)  # its REPO_ROOT is the image's tree
            self.assertEqual(Path(vp.REPO_ROOT).resolve(), root.resolve())
            for name in DEPLOYED:
                with self.subTest(passport=name):
                    self.assertEqual(vp.check(root / f"hives/agents-hive/passports/{name}/passport.json"), [])
        finally:
            sys.path[:] = saved
            for mod in [m for m, v in sys.modules.items() if str(root) in str(getattr(v, "__file__", "") or "")]:
                del sys.modules[mod]

    def test_the_check_sees_a_missing_file(self):
        self.assertTrue(covers(["a/b"], "a/b/c.json"))
        self.assertTrue(covers(["a/b/c.json"], "a/b/c.json"))
        self.assertFalse(covers(["a/b/cases.json"], "a/b/goals.json"))
        self.assertFalse(covers(["a/bc"], "a/b/c.json"))
        self.assertEqual(copied("COPY --chown=x a b /dst\nCOPY --from=build c /d\nRUN e"), ["a", "b"])


if __name__ == "__main__":
    unittest.main()
