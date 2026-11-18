"""Tests for the OpenAPI documents rendered for A2A's HTTP+JSON binding: every contract
renders a valid one, the document follows its contract, and the check refuses what OpenAPI
3.0 doesn't allow, so CI fails when a document would drift from either.

Standard library only. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/tests
"""
import contextlib
import copy
import importlib.util
import io
import json
import unittest
from pathlib import Path

HIVE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("openapi", HIVE / "scripts/openapi.py")
openapi = importlib.util.module_from_spec(spec)
spec.loader.exec_module(openapi)
CONTRACT = json.loads((HIVE / "contracts/governance-review/contract.json").read_text())
OAUTH = {"tokenUrl": "https://login.example.test/t/oauth2/v2.0/token", "scope": "api://app/.default"}


def render(contract=CONTRACT, oauth=OAUTH):
    return openapi.render(contract, "https://agents.example.test/patricia/", oauth, "patricia")


class OpenApiTest(unittest.TestCase):
    def test_every_contract_renders_a_valid_document(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(openapi.check_all(), 0, out.getvalue())
        self.assertIn("OpenAPI documents valid", out.getvalue())

    def test_the_document_follows_the_contract(self):
        doc = render()
        self.assertEqual(openapi.validate(doc), [])
        schemas = doc["components"]["schemas"]
        self.assertEqual(schemas["Input"]["required"], CONTRACT["inputs"]["required"])
        self.assertEqual(set(schemas["Input"]["properties"]), set(CONTRACT["inputs"]["properties"]))
        verdict = schemas["Output"]["properties"]["verdict"]
        self.assertEqual(verdict, {**CONTRACT["output"]["properties"]["verdict"], "type": "string"},
                         "a string enum gets its type, and nothing else changes")
        self.assertEqual(doc["info"]["version"], str(CONTRACT["version"]))
        self.assertEqual(doc["servers"], [{"url": "https://agents.example.test/patricia"}])
        op = doc["paths"]["/message:send"]["post"]
        self.assertEqual(op["operationId"], "SendMessage")
        self.assertEqual(op["parameters"][0]["schema"]["enum"], ["1.0"], "the A2A-Version header is required")
        for code in ("400", "401", "403", "429"):
            self.assertEqual(op["responses"][code]["content"]["application/json"]["schema"],
                             {"$ref": "#/components/schemas/Error"}, f"{code} is A2A's REST error")
        self.assertIn("WWW-Authenticate", op["responses"]["401"]["headers"])
        self.assertEqual(doc["security"], [{"entra": ["api://app/.default"]}])

    def test_a_delegated_scope_adds_the_authorization_code_flow(self):
        doc = render(oauth={**OAUTH, "delegated": ["Review.RequestAsUser"]})
        self.assertEqual(openapi.validate(doc), [])
        flow = doc["components"]["securitySchemes"]["entra"]["flows"]["authorizationCode"]
        self.assertEqual(flow["authorizationUrl"], "https://login.example.test/t/oauth2/v2.0/authorize")
        self.assertEqual(list(flow["scopes"]), ["api://app/Review.RequestAsUser"])
        self.assertIn({"entra": ["api://app/Review.RequestAsUser"]}, doc["security"])

    def test_a_contract_it_cannot_describe_is_refused(self):
        for change, why in ((lambda c: c["inputs"]["properties"]["proposal"].update(const="x"), "const"),
                            (lambda c: c["inputs"].update(type="string"), "object inputs")):
            contract = copy.deepcopy(CONTRACT)
            change(contract)
            with self.subTest(why), self.assertRaises(openapi.SpecError) as e:
                render(contract)
            self.assertIn(why, str(e.exception))

    def test_the_check_refuses_what_openapi_3_0_does_not_allow(self):
        def problems(change):
            doc = render()
            change(doc)
            return openapi.validate(doc)

        schemas = lambda d: d["components"]["schemas"]  # noqa: E731
        cases = {
            "3.0.x": lambda d: d.update(openapi="3.1.0"),
            "a single string": lambda d: schemas(d)["Input"]["properties"]["proposal"].update(type=["string", "null"]),
            "isn't a Schema Object field": lambda d: schemas(d)["Input"].update(const="x"),
            "no sibling fields": lambda d: schemas(d)["Message"]["properties"]["parts"]["items"].update(description="x"),
            "doesn't resolve": lambda d: schemas(d).pop("Output"),
            "needs items": lambda d: schemas(d)["Artifact"]["properties"]["parts"].pop("items"),
            "https URL": lambda d: d["servers"][0].update(url="http://agents.example.test"),
            "no flow granting": lambda d: d["security"].append({"entra": ["api://app/Other"]}),
            "every call needs a token": lambda d: d.pop("security"),
            "isn't a status code": lambda d: d["paths"]["/message:send"]["post"]["responses"].update(ok={
                "description": "x"}),
        }
        for expected, change in cases.items():
            with self.subTest(expected):
                found = problems(change)
                self.assertTrue(any(expected in p for p in found), found)


if __name__ == "__main__":
    unittest.main()
