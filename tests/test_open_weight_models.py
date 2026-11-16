"""Offline unit tests for the monthly open-weight metadata collector."""
import io
import json
import unittest
from unittest.mock import patch
from scripts.update_open_weight_models import MODELS, build_snapshot, fetch_model


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self
    def __exit__(self, *args):
        self.close()


class ModelTrackerTests(unittest.TestCase):
    def test_license_tag_and_gating(self):
        model = MODELS[0]
        def opener(request, timeout):
            self.assertEqual(timeout, 25)
            self.assertIn(model, request.full_url)
            return FakeResponse(json.dumps({
                "id": model, "tags": ["license:llama3.1"],
                "gated": "manual", "lastModified": "2026-11-01T00:00:00Z"
            }).encode())
        row = fetch_model(model, opener)
        self.assertEqual(row["license_tag_unverified"], "llama3.1")
        self.assertEqual(row["gated"], "manual")

    def test_wrong_model_id_rejected(self):
        def opener(request, timeout):
            return FakeResponse(b'{"id":"unexpected"}')
        with self.assertRaises(ValueError):
            fetch_model(MODELS[0], opener)

    def test_snapshot_deterministic_and_complete(self):
        def fake_fetch(model):
            return {"model_id": model}
        a = build_snapshot("2026-11", fake_fetch)
        self.assertEqual(a, build_snapshot("2026-11", fake_fetch))
        self.assertEqual(len(a["models"]), len(MODELS))
        self.assertEqual(a["review_month_utc"], "2026-11")

    def test_invalid_month_rejected(self):
        with self.assertRaises(ValueError):
            build_snapshot("2026-13", lambda model: {})


if __name__ == "__main__":
    unittest.main()
