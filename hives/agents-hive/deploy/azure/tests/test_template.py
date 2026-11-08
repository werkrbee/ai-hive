"""Tests for the compiled template: each agent may write only its own audit blob.

The audit container holds Patricia's copy and hosted Barry's. Its retention policy refuses
changes and deletes but not appends, so an identity with Storage Blob Data Contributor on
the whole container could add to the other agent's copy. Each assignment of that role on
the container must carry a condition that keeps its identity to its own blob.

The check is by meaning, not compiled text. Each condition's ARM expression is evaluated
to its final string, using the template's own variables, and that string is parsed as a
role-assignment condition. The test then asks the condition which blob data actions it
allows, and on which paths. The evaluator knows only the ARM functions the template uses,
and the parser knows only the condition forms it uses; anything else fails loudly, so a
Bicep upgrade that compiles differently is reported, never guessed at. No Azure access.

Needs the Azure CLI with Bicep (az bicep build); skipped without it. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/deploy/azure/tests -p 'test_*.py'
"""
import copy
import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
CONTRIBUTOR = "storageBlobDataContributor"
BLOBS = "Microsoft.Storage/storageAccounts/blobServices/containers/blobs"
# Storage Blob Data Contributor's blob data actions, each of which the condition must keep
# to the agent's own blob. Named here, not read from the template, so a template that drops
# one is caught.
BLOB_ACTIONS = [f"{BLOBS}/{a}" for a in ("read", "write", "delete", "add/action", "move/action")]
BLOB = {"patricia": "patricia.jsonl", "barry": "barry.jsonl"}


class Unknown(ValueError):
    """An ARM function or condition form this test doesn't evaluate."""


# ARM template expressions: string literals, integers and function calls.
ARM_TOKEN = re.compile(r"\s*(?:(?P<str>'(?:[^']|'')*')|(?P<num>-?\d+)|(?P<name>[A-Za-z_]\w*)|(?P<punct>[(),]))")


def arm_parse(text):
    """The syntax tree of an ARM expression (the text inside its [ ])."""
    tokens, pos = [], 0
    while pos < len(text):
        m = ARM_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip():
                raise Unknown(f"an ARM expression this test can't read, at: {text[pos:pos + 40]!r}")
            break
        kind = m.lastgroup
        tokens.append((kind, m.group(kind)))
        pos = m.end()

    def node(i):
        kind, val = tokens[i]
        if kind == "str":
            return ("str", val[1:-1].replace("''", "'")), i + 1
        if kind == "num":
            return ("num", int(val)), i + 1
        if kind == "name" and i + 1 < len(tokens) and tokens[i + 1] == ("punct", "("):
            args, i = [], i + 2
            while tokens[i] != ("punct", ")"):
                arg, i = node(i)
                args.append(arg)
                if tokens[i] == ("punct", ","):
                    i += 1
                elif tokens[i] != ("punct", ")"):
                    raise Unknown(f"an ARM expression this test can't read: {text!r}")
            return ("call", val, args), i + 1
        raise Unknown(f"an ARM expression this test can't read: {text!r}")

    tree, end = node(0)
    if end != len(tokens):
        raise Unknown(f"an ARM expression this test can't read: {text!r}")
    return tree


def net_format(fmt, args):
    """ARM's format(): .NET composite formatting, {0} and the {{ }} escapes only."""
    def one(m):
        if m.group(0) in ("{{", "}}"):
            return m.group(0)[0]
        if m.group(1) is None:
            raise Unknown(f"a format string this test can't read: {fmt!r}")
        return str(args[int(m.group(1))])
    return re.sub(r"\{\{|\}\}|\{(\d+)\}|[{}]", one, fmt)


def arm(value, variables):
    """A template value with its ARM expression, if it has one, evaluated."""
    if not isinstance(value, str) or not value.startswith("["):
        return value
    if value.startswith("[["):
        return value[1:]
    if not value.endswith("]"):
        raise Unknown(f"an ARM expression this test can't read: {value!r}")
    return evaluate(arm_parse(value[1:-1]), variables, {})


def evaluate(tree, variables, env):
    kind = tree[0]
    if kind in ("str", "num"):
        return tree[1]
    name, args = tree[1], tree[2]
    if name == "lambda":
        params = [evaluate(a, variables, env) for a in args[:-1]]
        return ("lambda", params, args[-1], env)
    values = [evaluate(a, variables, env) for a in args]
    if name == "variables":
        if values[0] not in variables:
            raise Unknown(f"variables('{values[0]}') isn't in the template")
        return arm(variables[values[0]], variables)
    if name == "format":
        return net_format(values[0], values[1:])
    if name == "join":
        return values[1].join(values[0])
    if name == "map":
        _, params, body, scope = values[1]
        return [evaluate(body, variables, {**scope, params[0]: item}) for item in values[0]]
    if name == "lambdaVariables":
        return env[values[0]]
    raise Unknown(f"the ARM function {name}(), which this test doesn't evaluate")


# Role-assignment conditions: OR, AND, !( ), ActionMatches{'...'} and a blob path compared
# with StringEquals.
COND_TOKEN = re.compile(r"\s*(?:(?P<str>'[^']*')|(?P<attr>@Resource\[[^\]]*\])|(?P<word>[A-Za-z]+)|(?P<punct>[(){}!]))")
PATH = f"@Resource[{BLOBS}:path]"


def condition_parse(text):
    """The syntax tree of a condition: ("or", [...]), ("and", [...]), ("not", x),
    ("action", name) or ("path", blob)."""
    tokens, pos = [], 0
    while pos < len(text):
        m = COND_TOKEN.match(text, pos)
        if not m or m.end() == pos:
            if text[pos:].strip():
                raise Unknown(f"a condition this test can't read, at: {text[pos:pos + 40]!r}")
            break
        kind = m.lastgroup
        tokens.append((kind, m.group(kind)))
        pos = m.end()
    tokens.append(("end", ""))
    i = 0

    def take(kind, val=None):
        nonlocal i
        k, v = tokens[i]
        if k != kind or (val is not None and v != val):
            raise Unknown(f"a condition this test can't read: expected {val or kind}, found {v!r} in {text!r}")
        i += 1
        return v

    def joined(word, part):
        items = [part()]
        while tokens[i] == ("word", word):
            take("word", word)
            items.append(part())
        return items[0] if len(items) == 1 else (word.lower(), items)

    def unary():
        k, v = tokens[i]
        if (k, v) == ("punct", "!"):
            take("punct", "!")
            return ("not", unary())
        if (k, v) == ("punct", "("):
            take("punct", "(")
            inner = joined("OR", lambda: joined("AND", unary))
            take("punct", ")")
            return inner
        if (k, v) == ("word", "ActionMatches"):
            take("word", "ActionMatches")
            take("punct", "{")
            action = take("str")[1:-1]
            take("punct", "}")
            if "*" in action:
                raise Unknown(f"a wildcard action, {action}, which this test doesn't evaluate")
            return ("action", action)
        if k == "attr":
            if v != PATH:
                raise Unknown(f"the attribute {v}, which this test doesn't evaluate")
            take("attr")
            take("word", "StringEquals")
            return ("path", take("str")[1:-1])
        raise Unknown(f"a condition this test can't read: unexpected {v!r} in {text!r}")

    tree = joined("OR", lambda: joined("AND", unary))
    take("end")
    return tree


def allows(tree, action, path):
    """Whether the condition lets an identity do action on the blob at path."""
    kind = tree[0]
    if kind == "or":
        return any(allows(t, action, path) for t in tree[1])
    if kind == "and":
        return all(allows(t, action, path) for t in tree[1])
    if kind == "not":
        return not allows(tree[1], action, path)
    if kind == "action":
        return action == tree[1]
    return path == tree[1]


def nodes(tree):
    yield tree
    if tree[0] in ("or", "and"):
        for t in tree[1]:
            yield from nodes(t)
    elif tree[0] == "not":
        yield from nodes(tree[1])


def audit_writers(template):
    """The Contributor assignments on the audit container, by whose identity they're for."""
    found = {}
    for r in template["resources"]:
        p = r.get("properties", {})
        if r.get("type") == "Microsoft.Authorization/roleAssignments" and CONTRIBUTOR in p.get("roleDefinitionId", "") \
                and "variables('auditContainer')" in r.get("scope", ""):
            who = "barry" if "variables('barryName')" in p["principalId"] else "patricia"
            if who in found:
                raise AssertionError(f"two Contributor assignments on the audit container for {who}")
            found[who] = p
    return found


def problems(template, who):
    """What's wrong with who's audit role, judged by what its condition allows."""
    p = audit_writers(template).get(who)
    if p is None:
        return [f"no Contributor assignment on the audit container for {who}"]
    if "condition" not in p:
        return ["has no condition, so it may write every blob in the container"]
    found = []
    if p.get("conditionVersion") != "2.0":
        found.append(f"conditionVersion is {p.get('conditionVersion')!r}, not '2.0'")
    tree = condition_parse(arm(p["condition"], template["variables"]))
    excluded = {t[1][1] for t in nodes(tree) if t[0] == "not" and t[1][0] == "action"}
    for action in BLOB_ACTIONS:
        if action not in excluded:
            found.append(f"doesn't exclude ActionMatches {action}")
    paths = {t[1] for t in nodes(tree) if t[0] == "path"}
    if paths != {BLOB[who]}:
        found.append(f"allows the paths {sorted(paths)}, not only {BLOB[who]}")
    other = BLOB["barry" if who == "patricia" else "patricia"]
    for action in BLOB_ACTIONS:
        if not allows(tree, action, BLOB[who]):
            found.append(f"doesn't allow {action} on its own blob, {BLOB[who]}")
        for path in (other, "elsewhere.jsonl"):
            if allows(tree, action, path):
                found.append(f"allows {action} on {path}")
    return found


@unittest.skipUnless(shutil.which("az"), "needs the Azure CLI with Bicep")
class Template(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        out = subprocess.run(["az", "bicep", "build", "--file", str(HERE.parent / "main.bicep"), "--stdout"],
                             capture_output=True, text=True, check=True).stdout
        cls.template = json.loads(out)

    def changed(self, who, change):
        """A copy of the template with change(properties, variables) applied to who's audit role."""
        t = copy.deepcopy(self.template)
        change(audit_writers(t)[who], t["variables"])
        return t

    def refused(self, who, change, expected):
        found = problems(self.changed(who, change), who)
        self.assertTrue(any(expected in p for p in found), found)

    def test_each_agents_audit_role_is_conditioned_to_its_own_blob(self):
        self.assertEqual(set(audit_writers(self.template)), {"patricia", "barry"})
        for who in BLOB:
            with self.subTest(agent=who):
                self.assertEqual(problems(self.template, who), [])

    def test_a_condition_written_differently_but_meaning_the_same_passes(self):
        # The exclusions in another order, inlined rather than a variable, and the two halves
        # of the OR swapped; ARM doubles a quote inside a string.
        exclusions = " AND ".join(f"!(ActionMatches{{''{a}''}})" for a in reversed(BLOB_ACTIONS))
        for who in BLOB:
            with self.subTest(agent=who):
                def rewrite(p, v):
                    p["condition"] = f"[format('({{1}} StringEquals ''{{2}}'') OR ({{0}})', '{exclusions}', " \
                                     f"'{PATH}', '{BLOB[who]}')]"
                self.assertEqual(problems(self.changed(who, rewrite), who), [])

    def test_a_role_with_no_condition_is_refused(self):
        self.refused("barry", lambda p, v: p.pop("condition"), "has no condition")

    def test_a_condition_naming_the_other_agents_blob_is_refused(self):
        def swap(p, v):
            p["condition"] = p["condition"].replace("variables('patriciaAuditBlob')", "variables('barryAuditBlob')")
        self.refused("patricia", swap, "allows the paths ['barry.jsonl'], not only patricia.jsonl")
        self.refused("patricia", swap, "allows " + BLOB_ACTIONS[1] + " on barry.jsonl")

    def test_a_blob_action_dropped_from_the_exclusions_is_refused(self):
        self.refused("barry", lambda p, v: v["blobActions"].remove("delete"), f"doesn't exclude ActionMatches {BLOBS}/delete")
        self.refused("barry", lambda p, v: v["blobActions"].remove("delete"), f"allows {BLOBS}/delete on patricia.jsonl")

    def test_a_second_allowed_path_is_refused(self):
        def widen(p, v):
            p["condition"] = p["condition"].replace(
                "StringEquals ''{1}''))'", f"StringEquals ''{{1}}'') OR ({PATH} StringEquals ''other.jsonl''))'")
        self.refused("barry", widen, "allows the paths ['barry.jsonl', 'other.jsonl'], not only barry.jsonl")

    def test_an_unknown_function_or_condition_form_fails_loudly(self):
        with self.assertRaisesRegex(Unknown, r"concat\(\)"):
            problems(self.changed("barry", lambda p, v: p.update(condition="[concat('a', 'b')]")), "barry")
        with self.assertRaisesRegex(Unknown, "StringLike|can't read"):
            problems(self.changed("barry", lambda p, v: p.update(
                condition=f"[format('{PATH} StringLike ''*.jsonl''')]")), "barry")

    def test_patricias_job_pushes_to_the_blob_her_role_allows(self):
        url = self.template["outputs"]["auditBlobUrl"]["value"]
        self.assertTrue(re.search(r"variables\('patriciaAuditBlob'\)\)\]$", url), url)


if __name__ == "__main__":
    unittest.main()
