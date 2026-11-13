"""Tests for install.py's per-harness rendering: for Codex an agent becomes one TOML file
whose prompt is developer_instructions, whatever characters the prompt holds; for Cursor a
read-only agent gets readonly: true; for Antigravity an agent carries no tools list, and an
agent with one is warned about, as for Codex; for Devin, Kiro and Cline an agent's tools carry
over under the harness's own names, and for OpenCode the tools it lacks become deny rules.

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
        for fallback in ("databricks-genie-code", "snowflake-cortex-code"):
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

    def test_cline_agents_are_yaml_files_with_clinecore_tool_names(self):
        tmpl, keys, fallback, fmt = install.agent_target("cline")
        self.assertEqual((tmpl, fmt, fallback), (".cline/agents/{name}.yaml", "markdown", None))
        out = install.render({"description": "d", "tools": "Read, Grep, Glob"}, "Body.\n", keys, "explore", "cline")
        self.assertEqual(out, "---\nname: explore\ndescription: d\ntools: [read_files, search_codebase]\n---\n\nBody.\n")
        self.assertEqual(install.native_tools({"tools": "Read, Edit, Write, Bash"}, "cline"),
                         "[read_files, editor, apply_patch, run_commands]")
        self.assertIsNone(install.unenforced({"tools": "Read, Grep, Glob"}, "cline"))

    def test_a_tool_cline_has_no_name_for_drops_the_list_and_warns(self):
        fm = {"description": "d", "tools": "Read, WebSearch"}
        self.assertIsNone(install.native_tools(fm, "cline"))
        self.assertNotIn("tools:", install.render(fm, "Body.\n", install.agent_target("cline")[1], "x", "cline"))
        self.assertIn("plan mode", install.unenforced(fm, "cline"))

    def test_opencode_agents_deny_the_actions_their_tools_lack(self):
        tmpl, keys, fallback, fmt = install.agent_target("opencode")
        self.assertEqual((tmpl, fmt, fallback), (".opencode/agents/{name}.md", "markdown", None))
        out = install.render({"description": "d", "tools": "Read, Grep, Glob"}, "Body.\n", keys, "explore", "opencode")
        self.assertTrue(out.startswith("---\ndescription: d\nmode: subagent\npermissions:\n"), out)
        for action in install.OPENCODE_GUARDED:
            self.assertIn(f'  - action: {action}\n    resource: "*"\n    effect: deny\n', out)
        self.assertNotIn("action: read", out)  # reads keep the session's defaults
        self.assertNotIn("name:", out)  # V2 takes the ID from the file name
        writer = install.native_tools({"tools": "Read, Edit, Bash"}, "opencode")
        self.assertNotIn("action: edit", writer)
        self.assertNotIn("action: shell", writer)
        self.assertIn("action: webfetch", writer)
        self.assertIsNone(install.unenforced({"tools": "Read, Grep, Glob"}, "opencode"))

    def test_an_opencode_agent_granted_every_guarded_action_gets_no_rules_or_warning(self):
        fm = {"description": "d", "tools": "Read, Edit, Bash, WebFetch, WebSearch, Task"}
        self.assertIsNone(install.native_tools(fm, "opencode"))
        self.assertIsNone(install.unenforced(fm, "opencode"))

    def test_a_tool_opencode_has_no_action_for_fails_closed_and_warns(self):
        # Without rules OpenCode allows every action, so an unmapped tool must not drop them.
        fm = {"description": "d", "tools": "Read, NotebookEdit"}
        out = install.render(fm, "Body.\n", install.agent_target("opencode")[1], "x", "opencode")
        for action in install.OPENCODE_GUARDED:
            self.assertIn(f"  - action: {action}\n", out)
        warning = install.unenforced(fm, "opencode")
        self.assertIn("no permission action for notebookedit", warning)
        self.assertIn("add an allow rule by hand", warning)

    def test_goose_agents_are_recipes_granting_only_the_tools_theirs_map_to(self):
        tmpl, keys, fallback, fmt = install.agent_target("goose")
        self.assertEqual((tmpl, fallback, fmt), (".goose/recipes/{name}.yaml", None, "recipe"))
        out = install.render_recipe({"description": "Finds — things", "tools": "Read, Grep, Glob"},
                                    "Line one.\n\nLine two.\n", keys, "explore")
        self.assertEqual(out, 'version: 1.0.0\ntitle: "explore"\ndescription: "Finds — things"\n'
                              "instructions: |\n  Line one.\n\n  Line two.\n"
                              "extensions:\n  - type: platform\n    name: developer\n"
                              "    available_tools: [tree, read_image]\n"
                              "  - type: platform\n    name: analyze\n")
        self.assertIn("not read them", install.unenforced({"tools": "Read, Grep, Glob"}, "goose"))
        writer = install.render_recipe({"description": "d", "tools": "Read, Edit, Write, Bash"},
                                       "Body.\n", keys, "fixer")
        self.assertIn("available_tools: [tree, read_image, edit, write, shell]", writer)
        self.assertIsNone(install.unenforced({"tools": "Read, Edit, Write, Bash"}, "goose"))

    def test_a_goose_agent_without_a_tools_list_inherits_and_an_unmapped_tool_fails_closed(self):
        keys = install.agent_target("goose")[1]
        self.assertNotIn("extensions", install.render_recipe({"description": "d"}, "B.\n", keys, "x"))
        out = install.render_recipe({"description": "d", "tools": "WebFetch"}, "B.\n", keys, "x")
        self.assertTrue(out.endswith("\nextensions: []\n"))
        self.assertIn("no tool for webfetch", install.unenforced({"tools": "WebFetch"}, "goose"))

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
