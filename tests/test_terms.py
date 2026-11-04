import unittest

from terms import make_questions, normalize, read_spans


class TermTests(unittest.TestCase):
    def setUp(self):
        self.rfq = {"id": "rfq", "role": "rfq", "text": "Need destination receipt, including freight.", "title": "RFQ"}
        self.quote = {"id": "a", "role": "quote", "supplier": "A", "title": "A",
            "text": "🧪\r\nArrival is conditional on deposit clearance.\r\nNo deposit has cleared."}
        self.docs = {"rfq": self.rfq, "a": self.quote}

    def test_rejected_candidate_is_not_promoted_to_a_source(self):
        field = {"value": None, "reason": "verification_rejected",
            "rejected_value": "No deposit has cleared.", "start": 49, "end": 72}
        self.assertEqual(read_spans(field, "a", self.docs), [])

    def test_wrong_utf16_offset_is_not_repaired_by_finding_quote(self):
        text = "Arrival is conditional on deposit clearance."
        exact = {"value": text, "start": 3, "end": 3 + len(text)}
        self.assertEqual(read_spans(exact, "a", self.docs)[0]["integrity"], "exact")
        wrong = dict(exact, start=4, end=4 + len(text))
        self.assertEqual(read_spans(wrong, "a", self.docs)[0]["integrity"], "mismatch")

    def test_positive_classification_without_evidence_remains_unestablished(self):
        result = normalize({"fields": {"freight_status": {"value": "included_and_priced"},
            "receipt_status": {"value": "firm_receipt_date"}}}, self.quote, self.docs)
        self.assertEqual(result["signals"]["freight_status"], "not_established")
        self.assertEqual(result["signals"]["receipt_status"], "not_established")
        _, questions = make_questions(result, self.rfq, self.quote)
        self.assertEqual({q["term"] for q in questions}, {"freight", "receipt"})
        self.assertTrue(all("did not locate" in q["text"] for q in questions))
        self.assertTrue(all(q["sources"][0]["documentId"] == "rfq" for q in questions))

    def test_condition_and_negation_are_preserved_with_cap_warning(self):
        first, second = self.quote["text"].split("\r\n")[1:]
        items = []
        for sentence in (first, second):
            start = self.quote["text"].index(sentence)
            items.append({"value": sentence, "start": start, "end": start + len(sentence)})
        response = {"fields": {"receipt_clause": {"value": [first], "items": [items[0]]},
            "payment_clause": {"value": [first, second], "items": items, "finish": "cap"},
            "receipt_status": {"value": "conditional_receipt"}, "unmet_payment_condition": {"value": True}}}
        result = normalize(response, self.quote, self.docs)
        _, questions = make_questions(result, self.rfq, self.quote)
        payment = next(q for q in questions if q["term"] == "payment_condition")
        self.assertIn(first, payment["text"])
        self.assertIn(second, payment["text"])
        self.assertIn("whether it has been fulfilled", payment["text"])
        self.assertIn("bounded source read", payment["text"])
        self.assertTrue(all(s["documentId"] == "a" for s in payment["sources"]))


if __name__ == "__main__":
    unittest.main()
