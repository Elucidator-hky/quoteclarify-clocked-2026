import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

from client import ApiError, ClockedClient


class Response:
    status = 200
    def __init__(self, transport="door:east", credits="7", cost="0.0014"):
        self.headers = {"X-Clocked-Transport": transport, "X-Clocked-Credits": credits,
            "X-Clocked-Cost-Usd": cost, "X-Clocked-Cost-Basis": "reference"}
    def __enter__(self):
        return self
    def __exit__(self, *args):
        pass
    def read(self):
        return b'{"model":"fake-test","pairs":[]}'


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        secret = self.root / "fake.env"
        secret.write_text("CLOCKED_API_KEY=fake-test-only\n")
        self.client = ClockedClient(self.root / "state", secret_path=secret)
        self.payload = {"documents": [{"id": "a", "text": "Synthetic A"}, {"id": "b", "text": "Synthetic B"}]}

    @patch("client.urllib.request.urlopen")
    def test_cache_never_rebills_or_reuses_auth_as_source(self, call):
        call.return_value = Response()
        first = self.client.call("compare", self.payload)
        second = self.client.call("compare", self.payload)
        self.assertEqual(first["meta"]["credits"], 7)
        self.assertEqual(second["meta"]["transport"], "cache")
        self.assertEqual(second["meta"]["credits"], 0)
        self.assertEqual(self.client.budget()["usedCredits"], 7)
        self.assertEqual(call.call_count, 1)
        for p in (self.root / "state").glob("receipt-*.json"):
            self.assertNotIn("fake-test-only", p.read_text())

    @patch("client.urllib.request.urlopen")
    def test_unknown_network_result_blocks_different_work_and_reuses_id(self, call):
        call.side_effect = TimeoutError("fake timeout")
        with self.assertRaises(ApiError) as first:
            self.client.call("compare", self.payload)
        self.assertEqual(first.exception.code, "unknown_network_outcome")
        with self.client._db() as db:
            before = db.execute("SELECT request_id FROM calls").fetchone()[0]
        with self.assertRaises(ApiError) as other:
            self.client.call("compare", {"documents": ["different", "work"]})
        self.assertEqual(other.exception.code, "unknown_previous_request")
        self.assertEqual(call.call_count, 1)
        call.side_effect = None
        call.return_value = Response("replay")
        replay = self.client.call("compare", self.payload)
        self.assertEqual(replay["meta"]["requestId"], before)
        self.assertEqual(replay["meta"]["credits"], 0)
        self.assertEqual(self.client.budget()["usedCredits"], 7)

    @patch("client.urllib.request.urlopen")
    def test_http_conflict_does_not_become_new_logical_request(self, call):
        call.side_effect = urllib.error.HTTPError("https://example.invalid", 409, "in progress", {},
            io.BytesIO(b'{"error":"request still running"}'))
        with self.assertRaises(ApiError):
            self.client.call("compare", self.payload)
        with self.client._db() as db:
            request_id, status = db.execute("SELECT request_id,status FROM calls").fetchone()
        self.assertEqual(status, "unknown")
        call.side_effect = None
        call.return_value = Response("replay")
        result = self.client.call("compare", self.payload)
        self.assertEqual(result["meta"]["requestId"], request_id)

    @patch("client.urllib.request.urlopen")
    def test_invalid_billing_receipt_pauses_new_work(self, call):
        call.return_value = Response(credits="-7")
        with self.assertRaises(ApiError) as error:
            self.client.call("compare", self.payload)
        self.assertEqual(error.exception.code, "invalid_billing_receipt")
        with self.assertRaises(ApiError) as other:
            self.client.call("rerank", {"query": "new", "documents": ["x"]})
        self.assertEqual(other.exception.code, "unknown_previous_request")

    @patch("client.urllib.request.urlopen")
    def test_budget_reserve_stops_request_before_network(self, call):
        self.client.limit = 199
        with self.assertRaises(ApiError) as error:
            self.client.call("compare", self.payload)
        self.assertEqual(error.exception.code, "development_budget_exhausted")
        call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
