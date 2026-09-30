import json
import unittest
from unittest.mock import MagicMock, patch

from free_models_monitor import providers


class CatalogValidationTests(unittest.TestCase):
    def fetch(self, payload):
        response = MagicMock()
        response.__enter__.return_value = response
        response.read.return_value = json.dumps(payload).encode()
        with patch.object(providers.urllib.request, "urlopen", return_value=response):
            return providers.fetch_openrouter_free()

    def test_successful_empty_catalog(self):
        self.assertEqual(self.fetch({"data": []}), ({}, None))

    def test_bad_schema_is_failure_not_empty_success(self):
        for payload in ({}, [], {"data": None}, {"data": [None]},
                        {"data": [{"id": "a"}]}, {"data": [{"id": "", "pricing": {}}]},
                        {"data": [{"id": "a", "pricing": {"prompt": "NaN", "completion": "0"}}]},
                        {"data": [{"id": "a", "pricing": {"prompt": None, "completion": "0"}}]},
                        {"data": [{"id": "a", "pricing": {"prompt": "0", "completion": "0"},
                                   "context_length": "wrong"}]}):
            with self.subTest(payload=payload):
                current, error = self.fetch(payload)
                self.assertIsNone(current)
                self.assertTrue(error)

    def test_groq_metadata_and_deep_copy(self):
        first, _ = providers.fetch_groq_free()
        self.assertTrue(first)
        for info in first.values():
            self.assertFalse(info["free_tier_verified"])
            self.assertIsNone(info["catalog_as_of"])
        next(iter(first.values()))["name"] = "mutated"
        second, _ = providers.fetch_groq_free()
        self.assertNotEqual(first, second)
