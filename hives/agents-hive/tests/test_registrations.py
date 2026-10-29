"""Tests for caller registrations: lineup's example is valid, each way a registration can let
the model vouch for a fact or reach an action it shouldn't is refused, and resolve() turns
a tool call into the request the policy decides.

Standard library only. Run from the repo root:
  python3 -B -m unittest discover -s hives/agents-hive/tests
"""
import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

HIVE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("registrations", HIVE / "scripts/registrations.py")
registrations = importlib.util.module_from_spec(spec)
spec.loader.exec_module(registrations)
EXAMPLE = json.loads((HIVE / "registrations/lineup/registration.json").read_text())


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name) / "lineup"
        self.dir.mkdir()

    def problems(self, change=None):
        """The checker's problems with lineup's example after change(reg) edits a copy."""
        reg = copy.deepcopy(EXAMPLE)
        if change:
            change(reg)
        (self.dir / "registration.json").write_text(json.dumps(reg))
        return registrations.check(self.dir / "registration.json")[0]

    def refused(self, change, expected):
        problems = self.problems(change)
        self.assertTrue(any(expected in p for p in problems), problems)

    def test_the_example_is_valid(self):
        self.assertEqual(self.problems(), [])

    def test_a_fact_from_the_calls_arguments_is_refused(self):
        def change(reg):
            reg["tools"]["lineup/send_message"]["facts"]["recipient.notifyOptIn"] = {
                "from": "argument", "path": "notifyOptIn"}
        self.refused(change, "comes from the call's arguments, which the model chooses")

    def test_an_unknown_action_is_refused(self):
        self.refused(lambda reg: reg["tools"]["lineup/send_message"].update(action="lineup.fee.charge"),
                     "unknown action 'lineup.fee.charge'")

    def test_a_tool_with_no_map_is_refused(self):
        self.refused(lambda reg: reg["tools"].update({"lineup/charge_fee": {}}), "has no map")

    def test_a_tool_on_a_server_that_isnt_registered_is_refused(self):
        self.refused(lambda reg: reg["tools"].update({"airtable/list_records": {"fact_source": True}}),
                     "no registered server named 'airtable'")

    def test_a_lookup_must_name_a_fact_source(self):
        def change(reg):
            reg["tools"]["lineup/send_message"]["facts"]["recipient.notifyOptIn"]["tool"] = "lineup/cancel_event"
        self.refused(change, "isn't one of the registration's fact sources")

    def test_a_lookups_input_cant_come_from_another_lookup(self):
        def change(reg):
            fact = reg["tools"]["lineup/send_message"]["facts"]["recipient.notifyOptIn"]
            fact["input"]["member"] = copy.deepcopy(fact)
        self.refused(change, "can't come from lookup")

    def test_only_actor_facts_come_from_the_request_and_they_come_only_from_it(self):
        def recipient_from_request(reg):
            reg["tools"]["lineup/send_message"]["facts"]["recipient.notifyOptIn"] = {
                "from": "request", "field": "recipient.notifyOptIn"}
        self.refused(recipient_from_request, "vouches only for actor.* facts")

        def actor_from_lookup(reg):
            reg["tools"]["lineup/cancel_event"]["facts"]["actor.role"] = {
                "from": "lookup", "tool": "lineup/get_member", "input": {}, "path": "role"}
        self.refused(actor_from_lookup, "is about the actor")

        def another_request_field(reg):
            reg["tools"]["lineup/cancel_event"]["facts"]["actor.role"]["field"] = "actor.title"
        self.refused(another_request_field, "must come from the request's own actor.role")

    def test_a_subject_needs_the_tools_subjects(self):
        self.refused(lambda reg: reg["tools"]["lineup/send_message"].pop("subjects"),
                     "needs the tool's subjects")

    def test_a_present_item_the_policy_doesnt_present_is_refused(self):
        self.refused(lambda reg: reg["tools"]["lineup/send_message"]["present"].update(
            {"sender": {"from": "value", "value": "lineup"}}), "no mandate for 'message.send' presents it")

    def test_the_policy_must_extend_the_charter(self):
        with mock.patch.object(registrations, "CHARTER", "hives/rules-hive/rules/elsewhere/policy.json"):
            self.refused(None, "doesn't extend the Queen Bee's Charter")

    def test_a_local_server_is_refused(self):
        def change(reg):
            reg["servers"][0]["mcp"] |= {"transport": "stdio", "config": {"command": "lineup-mcp"}}
        self.refused(change, "must be a remote server")

    def test_resolve_takes_facts_from_lookups_and_the_request_never_the_arguments(self):
        def lookup(tool, given):
            return {"m1": {"notifyOptIn": True}, "m2": {"notifyOptIn": False}}.get(given.get("member"))

        req, present = registrations.resolve(
            EXAMPLE, "lineup/send_message",
            {"channel": "sms", "audience": "group", "recipients": ["m1", "m2"], "text": "Hi",
             "notifyOptIn": True},
            {"trigger": "bullpen.slot-opened", "facts": {"actor.role": "organizer"}}, lookup)
        # The two recipients disagree, so the fact is missing, not the model's true.
        self.assertEqual(req, {"action": "message.send", "scope": {"channel": "sms", "audience": "group"},
                               "trigger": "bullpen.slot-opened", "facts": {}})
        self.assertEqual(present, {"message": "Hi", "recipient count": 2, "estimated cost": None})
        with self.assertRaises(registrations.Unmapped):
            registrations.resolve(EXAMPLE, "lineup/estimate_cost", {}, {}, lookup)


if __name__ == "__main__":
    unittest.main()
