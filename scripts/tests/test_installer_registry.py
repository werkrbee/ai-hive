"""Frozen pre-#260 paths and real sandbox installs guard a behavior-preserving migration."""
import contextlib
import io
import copy
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import harnesses
ROOT = harnesses.ROOT
MCP = ROOT / 'hives/mcp-hive/scripts'
sys.path.insert(0, str(MCP))
spec = importlib.util.spec_from_file_location('mcp_installer_260', MCP / 'install.py')
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
BASELINE = json.loads((Path(__file__).parent / 'fixtures/installer-paths-260.json').read_text())
WINDOWS = [('github-copilot', '.copilot/skills'),
           ('claude-code', '.claude/skills'), ('cursor', '.cursor/skills'),
           ('codex', '.agents/skills'), ('gemini-cli', '.gemini/skills'), ('kiro', '.kiro/skills')]
RULES = {'agents': 'AGENTS.md', 'opencode': 'AGENTS.md', 'codex': 'AGENTS.md',
         'kiro': 'AGENTS.md', 'goose': 'AGENTS.md', 'databricks-genie-code': 'AGENTS.md',
         'snowflake-cortex-code': 'AGENTS.md', 'claude-code': 'CLAUDE.md',
         'cursor': '.cursor/rules/queen-charter.mdc', 'github-copilot': '.github/copilot-instructions.md',
         'gemini-cli': 'GEMINI.md', 'devin-desktop': '.devin/rules/queen-charter.md',
         'cline': '.cline/rules/queen-charter.md'}


class RegistryParity(unittest.TestCase):
    def test_all_mcp_paths_keys_formats_and_env_references_match_before(self):
        expected = {h: {s: tuple(v) for s, v in scopes.items()}
                    for h, scopes in BASELINE['JSON_TARGETS'].items()}
        self.assertEqual(installer.JSON_TARGETS, expected)
        self.assertEqual(installer.SNIPPET_TARGETS, BASELINE['SNIPPET_TARGETS'])
        self.assertEqual(installer.ENV_REF, {(x['harness'], x['scope']): x['value']
                                          for x in BASELINE['ENV_REF']})

    def test_mcp_cli_merges_every_target_scope_without_clobbering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); home = root / 'home'; project = root / 'project'
            home.mkdir(); project.mkdir(); servers = root / 'servers'; (servers / 'fixture').mkdir(parents=True)
            (servers / 'fixture/mcp.json').write_text(json.dumps({'name': 'fixture', 'config': {
                'command': 'demo', 'args': ['${WORKSPACE}'], 'env': {'KEEP': 'literal'}}}))
            env = {**os.environ, 'HOME': str(home), 'USERPROFILE': str(home)}
            for h in [*installer.JSON_TARGETS, *installer.SNIPPET_TARGETS]:
                for scope in ('project', 'global'):
                    args = [sys.executable, str(MCP / 'install.py'), '--servers-dir', str(servers),
                            '--dir', str(project), '--harness', h]
                    if scope == 'global': args.append('--global')
                    target_spec = BASELINE['JSON_TARGETS'].get(h, {}).get(scope)
                    if target_spec:
                        rel, key = target_spec
                        target = home / rel[2:] if rel.startswith('~/') else project / rel
                        target.parent.mkdir(parents=True, exist_ok=True)
                        existing = {'untouched': True}; table = existing
                        for part in key.split('.'): table = table.setdefault(part, {})
                        table['existing'] = {'command': 'keep'}
                        target.write_text(json.dumps(existing))
                    out = subprocess.run(args, env=env, capture_output=True, text=True, check=True)
                    if not target_spec:
                        if h == 'cline': self.assertIn('has no project MCP config', out.stderr)
                        else: self.assertIn('add to your '+BASELINE['SNIPPET_TARGETS'][h].upper(), out.stdout)
                        continue
                    data = json.loads(target.read_text()); self.assertTrue(data['untouched'])
                    table = data
                    for part in key.split('.'): table = table[part]
                    self.assertEqual(table['existing'], {'command': 'keep'})
                    want = {'command': 'demo', 'args': [str(project)], 'env': {'KEEP': 'literal'}}
                    if h == 'opencode': want = {'type': 'local', 'command': ['demo', str(project)],
                                                'environment': {'KEEP': 'literal'}}
                    self.assertEqual(table['fixture'], want)

    def test_remote_configs_headers_inputs_and_snippets_match_before(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/mcp-remote-260.json').read_text())
        server = fixture['server']
        for header in server['remote']['headers']:
            header['parts'] = [tuple(p) for p in header['parts']]
        for key, expected in fixture['json'].items():
            hid, scope = key.split('/')
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                config, inputs = installer.json_config(hid, scope, 'remote', server, '/workspace')
            self.assertEqual({'config': config, 'inputs': inputs, 'output': out.getvalue()}, expected)
        for hid, expected in fixture['snippets'].items():
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                installer.print_snippet(installer.SNIPPET_TARGETS[hid], {'remote': server}, '/workspace')
            self.assertEqual(out.getvalue(), expected)

    def test_malformed_mcp_registry_fields_are_refused(self):
        for mutate, message in [
            (lambda s: s.update(format='xml'), 'format'),
            (lambda s: s['keys'].update(project=''), 'servers key'),
            (lambda s: s['env'].update(project='%s%s'), 'env reference'),
            (lambda s: s['env'].pop('project'), 'env reference'),
            (lambda s: s.update(project=3), 'path must'),
            (lambda s: s.update(default_order=0), 'positive integer')]:
            reg = copy.deepcopy(harnesses.load()); s = harnesses.surface('claude-code', 'mcp', reg)
            mutate(s)
            self.assertTrue(any(message in p for p in harnesses.check(reg)), message)

    def test_windows_defaults_require_the_matching_destination(self):
        for hid, name, path, message in [('claude-code', 'skills', 'global', 'global skills path'),
                                          ('claude-code', 'rules', 'project', 'project rules path')]:
            reg = copy.deepcopy(harnesses.load())
            harnesses.surface(hid, name, reg).pop(path)
            self.assertTrue(any(message in p for p in harnesses.check(reg)))

    def test_invalid_metadata_containers_report_problems_without_crashing(self):
        for field, value, message in [('keys', None, 'servers key'), ('env', None, 'env reference'),
                                      ('default_order', {}, 'positive integer')]:
            reg = copy.deepcopy(harnesses.load())
            harnesses.surface('claude-code', 'mcp', reg)[field] = value
            self.assertTrue(any(message in p for p in harnesses.check(reg)))
        for value in (None, 'claude', {'alias': 'claude'}):
            reg = copy.deepcopy(harnesses.load())
            harnesses.surface('claude-code', 'skills', reg)['windows_aliases'] = value
            self.assertTrue(any('windows_aliases' in p for p in harnesses.check(reg)))


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell not installed')
class PowerShellParity(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'home'; self.home.mkdir()
        self.env = {**os.environ, 'HOME': str(self.home), 'USERPROFILE': str(self.home), 'NO_COLOR': '1'}

    def run_ps(self, hive, *args, success=True):
        out = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File',
                              str(ROOT / 'hives' / hive / 'scripts/install.ps1'), *args],
                             env=self.env, capture_output=True, text=True)
        if success: self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        else: self.assertNotEqual(out.returncode, 0)
        return out

    def test_skills_defaults_preserve_targets_and_order(self):
        for _, rel in WINDOWS: (self.home / rel).parent.mkdir(parents=True, exist_ok=True)
        out = self.run_ps('skills-hive', '-DryRun').stdout
        lines = [line for line in out.splitlines() if line.startswith('-> ')]
        self.assertEqual(lines, [f'-> {h} ({self.home / p})' for h, p in WINDOWS])
        self.assertFalse(any(self.home.rglob('SKILL.md')))

    def test_skills_canonical_ids_and_deprecated_aliases_keep_paths(self):
        for h, rel in WINDOWS:
            out = self.run_ps('skills-hive', '-Only', h, '-DryRun').stdout
            self.assertIn(f'-> {h} ({self.home / rel})', out)
        for alias, canonical in [('claude','claude-code'), ('copilot','github-copilot'), ('gemini','gemini-cli')]:
            out = self.run_ps('skills-hive', '-Only', alias, '-DryRun').stdout
            self.assertIn('deprecated', out); self.assertIn('-> '+canonical, out)
        self.run_ps('skills-hive', '-Only', 'unknown', '-DryRun', success=False)
        # Autopilot, formerly Scout, takes skills as uploads, so there's no folder to link.
        self.run_ps('skills-hive', '-Only', 'scout', '-DryRun', success=False)

    def test_skills_skip_installed_conflict_and_force(self):
        out = self.run_ps('skills-hive', '-DryRun').stdout
        self.assertNotIn('-> ', out)
        dest = self.home / '.copilot/skills/barry'; dest.mkdir(parents=True)
        out = self.run_ps('skills-hive', '-Only', 'github-copilot', '-DryRun').stdout
        self.assertIn('barry exists (skip;', out)
        out = self.run_ps('skills-hive', '-Only', 'github-copilot', '-DryRun', '-Force').stdout
        self.assertIn('barry (would link)', out); self.assertTrue(dest.exists())

    def test_missing_registry_destination_fails_before_installing(self):
        for hive, surface, field in [('skills-hive', 'skills', 'global'), ('rules-hive', 'rules', 'project')]:
            house = Path(self.tmp.name) / hive
            script = house / 'hives' / hive / 'scripts/install.ps1'
            script.parent.mkdir(parents=True)
            shutil.copyfile(ROOT / 'hives' / hive / 'scripts/install.ps1', script)
            reg = harnesses.load(); harnesses.surface('claude-code', surface, reg).pop(field)
            (house / 'harnesses.json').write_text(json.dumps(reg))
            source = (script.parent.parent / 'skills/barry/SKILL.md' if surface == 'skills' else
                      script.parent.parent / 'rules/queen-charter/AGENTS.md')
            source.parent.mkdir(parents=True); source.write_text('fixture')
            args = ['-DryRun'] if surface == 'skills' else ['-Dir', str(self.home)]
            out = subprocess.run(['pwsh', '-NoProfile', '-NonInteractive', '-File', str(script), *args],
                                 env=self.env, capture_output=True, text=True)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn('needs a', out.stderr)
            self.assertFalse(any(self.home.rglob('SKILL.md')))
            self.assertFalse((self.home / 'AGENTS.md').exists())

    @unittest.skipUnless(os.name == 'nt', 'Actual junction creation requires Windows')
    def test_windows_real_junction_and_repeat_install(self):
        self.run_ps('skills-hive', '-Only', 'claude-code')
        target = self.home / '.claude/skills/barry/SKILL.md'
        self.assertEqual(target.read_bytes(), (ROOT / 'hives/skills-hive/skills/barry/SKILL.md').read_bytes())
        out = self.run_ps('skills-hive', '-Only', 'claude-code').stdout
        self.assertIn('barry (already linked)', out)

    def test_rules_every_harness_path_content_and_frontmatter(self):
        content = (ROOT / 'hives/rules-hive/rules/queen-charter/AGENTS.md').read_text()
        for h, rel in RULES.items():
            project = Path(self.tmp.name) / h
            self.run_ps('rules-hive', '-Harness', h, '-Dir', str(project))
            prefix = ('---\ndescription: queen-charter\nalwaysApply: true\n---\n\n' if h == 'cursor' else
                      '---\ntrigger: always_on\n---\n\n' if h == 'devin-desktop' else '')
            self.assertEqual((project / rel).read_text(), prefix+content+'\n')
            self.assertEqual([p.relative_to(project).as_posix() for p in project.rglob('*') if p.is_file()], [rel])
        project = Path(self.tmp.name) / 'default'
        out = self.run_ps('rules-hive', '-Dir', str(project)).stdout
        paths = ['AGENTS.md','CLAUDE.md','.cursor/rules/queen-charter.mdc',
                 '.github/copilot-instructions.md','GEMINI.md']
        self.assertEqual([x for x in out.splitlines() if x.startswith('wrote:')],
                         ['wrote: '+str(project / p) for p in paths])
        self.run_ps('rules-hive', '-Harness', 'unknown', '-Dir', str(project), success=False)

if __name__ == '__main__': unittest.main()
