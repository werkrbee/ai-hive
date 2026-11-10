"""Tests for install.py's Codex rendering: an agent becomes one TOML file whose prompt is
developer_instructions, whatever characters the prompt holds.

Standard library only (Python 3.9 has no TOML parser, so the strings are checked by hand).
Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/tests
"""
import importlib.util
import json
import unittest
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("agents_install", HIVE / "scripts" / "install.py")
install = importlib.util.module_from_spec(spec)
spec.loader.exec_module(install)


class CodexTomlTest(unittest.TestCase):
    def test_codex_reads_toml_agents_from_its_own_folder(self):
        tmpl, keys, fallback, fmt = install.agent_target("codex")
        self.assertEqual((tmpl, fmt, fallback), (".codex/agents/{name}.toml", "toml", None))
        self.assertNotIn("tools", keys)

    def test_an_agent_renders_its_prompt_as_developer_instructions(self):
        fm = {"description": 'Finds "where is X?"', "tools": "Read, Grep, Glob"}
        out = install.render_toml(fm, "Map the code.\nNever edit.\n", ["name", "description", "model"], "explore")
        self.assertEqual(out, 'name = "explore"\n'
                              'description = "Finds \\"where is X?\\""\n'
                              "developer_instructions = '''\nMap the code.\nNever edit.\n'''\n")

    def test_a_prompt_holding_triple_quotes_falls_back_to_a_basic_string(self):
        body = "Quote it like ''' this.\n"
        line = install.render_toml({}, body, ["name"], "x").splitlines()[1]
        self.assertEqual(line, "developer_instructions = " + json.dumps(body))

    def test_a_prompt_holding_control_characters_is_escaped(self):
        body = "bell\x07 delete\x7f return\r\n"
        value = install.toml_string(body)
        self.assertEqual(value, '"bell\\u0007 delete\\u007f return\\r\\n"')

    def test_an_agent_whose_tools_codex_cannot_enforce_is_warned_about(self):
        warning = install.unenforced({"tools": "Read, Grep, Glob"}, "toml")
        self.assertIn("--sandbox read-only", warning)
        self.assertIsNone(install.unenforced({"tools": "Read, Grep, Glob"}, "markdown"))
        self.assertIsNone(install.unenforced({}, "toml"))

    def test_every_canonical_agent_renders(self):
        for name, (fm, body) in install.load_agents([]).items():
            out = install.render_toml(fm, body, ["name", "description", "model"], name)
            self.assertTrue(out.startswith(f'name = "{name}"\n'), name)
            self.assertIn("developer_instructions = '''\n", out)


if __name__ == "__main__":
    unittest.main()
