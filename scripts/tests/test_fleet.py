import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import fleet


class FleetTest(unittest.TestCase):
    def test_registry_has_exactly_one_ranked_pro_code_ten(self):
        harnesses = fleet.load_top_ten()
        self.assertEqual(list(range(1, 11)), [h["rank"] for h in harnesses])

    def test_free_open_source_harnesses_are_dashed(self):
        for harness in fleet.load_top_ten():
            is_free = harness["id"] in fleet.FREE_OPEN_SOURCE
            svg = fleet.hexagon(100, 100, dashed=is_free)
            if is_free:
                self.assertIn("stroke-dasharray", svg)
            else:
                self.assertNotIn("stroke-dasharray", svg)

    def test_fleet_orders_inner_ring_before_corners(self):
        harnesses = fleet.load_top_ten()
        svg = fleet.draw_fleet(harnesses)
        inner = harnesses[:6]
        corners = harnesses[6:]
        for harness in inner:
            self.assertIn(harness["name"], svg)
        for harness in corners:
            self.assertIn(harness["name"], svg)


if __name__ == "__main__":
    unittest.main()
