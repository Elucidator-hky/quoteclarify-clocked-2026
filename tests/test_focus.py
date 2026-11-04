import copy
import unittest

from client import ApiError
from core import analyze_case, export_text
from focus import normalize, passages_for, request_for


class FocusTests(unittest.TestCase):
    def test_source_coordinates_preserve_emoji_crlf_and_repeated_clauses(self):
        text = "🧭 Quote 7\r\n\r\nFreight is excluded.\r\n\r\nFreight is excluded.\r\nOnly if a deposit clears."
        docs = {"q": {"id": "q", "title": "Original", "role": "quote", "text": text}}
        parts = passages_for(docs, target=24)
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[1]["text"], "Freight is excluded.")
        self.assertEqual(parts[2]["text"], "Freight is excluded.\r\nOnly if a deposit clears.")
        for part in parts:
            self.assertEqual(text[part["start"]:part["end"]], part["text"])
        self.assertNotEqual(parts[1]["start"], parts[2]["start"])

    def test_long_unbroken_condition_is_not_cut_to_fit_target(self):
        text = "Arrival " + "may depend on production; " * 100 + "only if the deposit clears."
        doc = {"q": {"id": "q", "title": "Q", "role": "quote", "text": text}}
        self.assertEqual([p["text"] for p in passages_for(doc)], [text])

    def test_many_tiny_sections_stay_within_api_limits_without_losing_words(self):
        text = "\n\n".join("Item %d" % n for n in range(400))
        doc = {"q": {"id": "q", "title": "Q", "role": "quote", "text": text}}
        parts = passages_for(doc)
        self.assertLess(len(parts), 20)
        self.assertTrue(all(any("Item %d" % n in p["text"] for p in parts) for n in range(400)))
        self.assertEqual(parts[0]["start"], 0)
        self.assertEqual(parts[-1]["end"], len(text))

    def test_results_join_local_sections_and_keep_skip_expand(self):
        docs = {"q": {"id": "q", "title": "Q", "role": "quote", "text": "Price\n\nOnly if paid\n\nFreight"}}
        parts = passages_for(docs, target=12)
        rows = [{"id": p["id"], "action": a} for p, a in zip(parts, ["skip", "expand", "use"])]
        result = normalize({"results": list(reversed(rows))}, "freight", docs, parts)
        self.assertEqual([r["action"] for r in result["results"]], ["use", "expand", "skip"])
        self.assertTrue(all(r["passage"]["integrity"] == "exact" for r in result["results"]))
        self.assertEqual(result["results"][0]["passage"]["quote"], "Freight")
        request = request_for("freight", parts, docs)
        self.assertNotIn("top_n", request)
        self.assertEqual(len(request["documents"]), 3)

    def test_unknown_duplicate_or_omitted_passage_cannot_be_repaired(self):
        docs = {"q": {"id": "q", "title": "Q", "role": "quote", "text": "A\n\nB"}}
        parts = passages_for(docs, target=1)
        for rows in [[], [{"id": "not-in-request", "action": "use"}],
                     [{"id": parts[0]["id"], "action": "use"}] * 2]:
            with self.assertRaises(ValueError):
                normalize({"results": rows}, "question", docs, parts)

    def test_rerank_failure_keeps_questions_and_independent_verify(self):
        value = {"rfq": {"id": "rfq", "title": "RFQ", "text": "Need destination receipt and freight."},
            "quotes": [{"id": "a", "title": "A", "supplier": "A", "text": "Freight not stated."},
                       {"id": "b", "title": "B", "supplier": "B", "text": "Production only; destination receipt not committed."}],
            "focus": "What is the destination receipt?", "draftSummary": "The freight is unknown."}
        class Client:
            calls = []
            def call(self, endpoint, payload):
                self.calls.append((endpoint, payload))
                if endpoint == "rerank":
                    raise ApiError("upstream_429", "Rate limited")
                pairs = [{"a": a, "b": b, "relation": "overlapping", "conflicts": []}
                    for a, b in [("rfq", "a"), ("rfq", "b"), ("a", "b")]]
                return {"data": {"pairs": pairs} if endpoint == "compare" else
                    {"fields": {}} if endpoint == "fill" else {"claims": []},
                    "meta": {"transport": "cache", "credits": 0}}
        client = Client()
        result = analyze_case(value, client)
        self.assertEqual(result["rerank"]["status"], "unavailable")
        self.assertEqual(len(result["documents"]), 3)
        self.assertTrue(result["clarifications"])
        self.assertEqual(result["grounding"]["status"], "not_requested")
        self.assertEqual(client.calls[-1][0], "rerank")
        exported = export_text(result, value, result["revision"])
        self.assertIn("SUPPLIER: A", exported["text"])
        self.assertIn("SUPPLIER: B", exported["text"])
        amended = copy.deepcopy(value)
        amended["draftSummary"] = "This note is checked independently."
        verify = analyze_case(amended, client, base=result)
        self.assertEqual(client.calls[-1][0], "grounding")
        self.assertEqual(verify["grounding"]["status"], "needs_review")


if __name__ == "__main__":
    unittest.main()
