import unittest
from decimal import Decimal
from scripts.finops_plan import cost, cost_per_success, examples, utilization, variance


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


if __name__ == "__main__":
    unittest.main()
