"""Tests for install.py's per-harness rendering: for Codex an agent becomes one TOML file
whose prompt is developer_instructions, whatever characters the prompt holds; for Cursor a
read-only agent gets readonly: true; for Antigravity an agent carries no tools list, and an
agent with one is warned about, as for Codex; for Devin and Kiro an agent's tools carry over
under the harness's own names.

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
        warning = install.unenforced({"tools": "Read, Grep, Glob"}, "codex")
        self.assertIn("in a Codex agent file;", warning)
        self.assertIn("--sandbox read-only", warning)
        self.assertIsNone(install.unenforced({"tools": "Read, Grep, Glob"}, "claude-code"))
        self.assertIsNone(install.unenforced({}, "codex"))

    def test_antigravity_agents_carry_no_tools_and_are_warned_about(self):
        tmpl, keys, fallback, fmt = install.agent_target("gemini-cli")
        self.assertEqual((tmpl, fmt, fallback), (".agents/agents/{name}.md", "markdown", None))
        out = install.render({"description": "d", "tools": "Read, Grep, Glob", "model": "sonnet"},
                             "Body.\n", keys, "explore")
        self.assertEqual(out, "---\nname: explore\ndescription: d\n---\n\nBody.\n")
        warning = install.unenforced({"tools": "Read, Grep, Glob"}, "gemini-cli")
        self.assertIn("write_file(*) and command(*)", warning)

    def test_the_shared_agents_folder_carries_no_tools_since_antigravity_reads_it(self):
        self.assertEqual(install.agent_target("agents")[:2], install.agent_target("gemini-cli")[:2])
        for fallback in ("goose", "opencode"):
            tmpl, keys, via, fmt = install.agent_target(fallback)
            self.assertEqual((tmpl, via), (".agents/agents/{name}.md", "agents"))
            self.assertNotIn("tools", keys)
            self.assertNotIn("model", keys)
        self.assertIn("which Antigravity reads", install.unenforced({"tools": "Read"}, "agents"))

    def test_cursor_agents_are_readonly_when_their_tools_cannot_write(self):
        tmpl, keys, fallback, fmt = install.agent_target("cursor")
        self.assertIn("readonly", keys)
        out = install.render({"description": "d", "tools": "Read, Grep, Glob"}, "Body.\n", keys, "explore")
        self.assertIn("\nreadonly: true\n", out)
        self.assertNotIn("tools:", out)
        writer = install.render({"description": "d", "tools": "Read, Edit, Bash"}, "Body.\n", keys, "fixer")
        self.assertNotIn("readonly", writer)
        self.assertIsNone(install.readonly({"description": "no tools list"}))

    def test_devin_agents_carry_claude_code_tools_under_devin_names(self):
        tmpl, keys, fallback, fmt = install.agent_target("devin-desktop")
        self.assertEqual((tmpl, fmt, fallback), (".devin/agents/{name}.md", "markdown", None))
        out = install.render({"description": "d", "tools": "Read, Grep, Glob"}, "Body.\n", keys, "explore",
                             "devin-desktop")
        self.assertEqual(out, "---\nname: explore\ndescription: d\nallowed-tools: [read, grep, glob]\n---\n\nBody.\n")
        self.assertEqual(install.native_tools({"tools": "Read, Edit, Write, Bash"}, "devin-desktop"),
                         "[read, edit, exec]")
        self.assertIsNone(install.unenforced({"tools": "Read, Grep, Glob"}, "devin-desktop"))

    def test_a_tool_devin_has_no_name_for_drops_the_list_and_warns(self):
        fm = {"description": "d", "tools": "Read, WebFetch"}
        self.assertIsNone(install.native_tools(fm, "devin-desktop"))
        self.assertNotIn("allowed-tools", install.render(fm, "Body.\n", install.agent_target("devin-desktop")[1], "x",
                                                         "devin-desktop"))
        self.assertIn("deny edit and exec", install.unenforced(fm, "devin-desktop"))

    def test_kiro_agents_carry_claude_code_tools_under_kiro_categories(self):
        tmpl, keys, fallback, fmt = install.agent_target("kiro")
        self.assertEqual((tmpl, fmt, fallback), (".kiro/agents/{name}.md", "markdown", None))
        out = install.render({"description": "d", "tools": "Read, Grep, Glob"}, "Body.\n", keys, "explore", "kiro")
        self.assertEqual(out, "---\nname: explore\ndescription: d\ntools: [read]\n---\n\nBody.\n")
        self.assertEqual(install.native_tools({"tools": "Read, Edit, Write, Bash, WebFetch"}, "kiro"),
                         "[read, write, shell, web]")
        self.assertIsNone(install.unenforced({"tools": "Read, Grep, Glob"}, "kiro"))

    def test_a_tool_kiro_has_no_name_for_drops_the_list_and_warns(self):
        fm = {"description": "d", "tools": "Read, NotebookEdit"}
        self.assertIsNone(install.native_tools(fm, "kiro"))
        self.assertNotIn("tools:", install.render(fm, "Body.\n", install.agent_target("kiro")[1], "x", "kiro"))
        self.assertIn("deny fs_write and shell", install.unenforced(fm, "kiro"))

    def test_claude_code_keeps_its_own_tool_names(self):
        out = install.render({"description": "d", "tools": "Read, Grep"}, "Body.\n",
                             install.agent_target("claude-code")[1], "explore", "claude-code")
        self.assertIn("\ntools: Read, Grep\n", out)

    def test_every_canonical_agent_renders(self):
        for name, (fm, body) in install.load_agents([]).items():
            out = install.render_toml(fm, body, ["name", "description", "model"], name)
            self.assertTrue(out.startswith(f'name = "{name}"\n'), name)
            self.assertIn("developer_instructions = '''\n", out)


if __name__ == "__main__":
    unittest.main()
