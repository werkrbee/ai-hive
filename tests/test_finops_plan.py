import json
import unittest
from decimal import Decimal
from pathlib import Path
from scripts.finops_plan import cost, cost_per_success, examples, utilization, variance

from scripts.finops_planning_schema import validate_records


class FinopsPlanTests(unittest.TestCase):
    def test_examples(self):
        e = examples()
        self.assertEqual(e["api"]["usd"], Decimal("8.0"))
        self.assertEqual(e["api"]["cost_per_success"], Decimal("0.005"))
        self.assertEqual(e["agent"]["usd"], Decimal("7.20"))
        self.assertEqual(e["agent"]["cost_per_success"], Decimal("0.09"))
        self.assertEqual(e["host"]["usd"], Decimal("320.0"))
        self.assertEqual(e["host"]["cost_per_success"], Decimal("0.04"))
        self.assertEqual(e["host"]["utilization"], Decimal("0.5"))

    def test_reject_invalid_values(self):
        for value in [-1, "NaN", "Infinity", "not-a-number"]:
            with self.assertRaises(ValueError):
                cost(value, 1)
        with self.assertRaises(ValueError):
            cost_per_success(10, 0)
        with self.assertRaises(ValueError):
            utilization(11, 10)

    def test_variance_zero_forecast(self):
        self.assertEqual(variance(5, 0)["percent"], None)
        self.assertEqual(variance(120, 100)["percent"], Decimal("20"))


class PlanningSchemaTests(unittest.TestCase):
    def setUp(self):
        fixture = Path(__file__).parent / "fixtures" / "finops_planning_records.json"
        self.records = json.loads(fixture.read_text(encoding="utf-8"))

    def test_fixture_accepts_rate_and_direct_cost(self):
        validate_records(self.records)

    def test_rejects_inconsistent_and_invalid_fields(self):
        rate_record = self.records[0]
        for changes in (
            {"amount_usd": "7"},
            {"quantity": None},
            {"unit_rate_usd": "NaN"},
            {"period": "2026-13"},
            {"source_date": "2026-02-30"},
            {"source": ""},
            {"basis": "unknown"},
            {"direct_amount_reason": "Cannot mix direct and rated amounts"},
            {"live_billing_account": "unexpected field"},
        ):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate_records([rate_record | changes])
        missing_rate = dict(rate_record)
        del missing_rate["unit_rate_usd"]
        with self.assertRaisesRegex(ValueError, "unit_rate_usd"):
            validate_records([missing_rate])

    def test_rejects_duplicates_and_allows_alternate_scenarios(self):
        rate_record = self.records[0]
        with self.assertRaisesRegex(ValueError, "duplicate record_id"):
            validate_records([rate_record, rate_record])
        duplicate_charge = rate_record | {"record_id": "alternate"}
        with self.assertRaisesRegex(ValueError, "duplicate source charge"):
            validate_records([rate_record, duplicate_charge])
        validate_records([rate_record, duplicate_charge | {"scenario": "api-high"}])


if __name__ == "__main__":
    unittest.main()
