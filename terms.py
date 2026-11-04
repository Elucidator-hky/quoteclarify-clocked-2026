"""Source-preserving commercial term reads. Independent of Compare relations and memos."""
from core import span_from_api


FIELDS = {
    "freight_clause": {"type": "extract", "infer": False, "unit": "sentence", "list": True, "max_items": 2,
        "description": "Complete source sentence about freight/shipping price, inclusion, exclusion or not-yet-priced freight; retain all negations and qualifiers."},
    "receipt_clause": {"type": "extract", "infer": False, "unit": "sentence", "list": True, "max_items": 2,
        "description": "Complete sentence giving destination receipt/arrival date, a conditional arrival offer, or saying destination receipt/transit is not committed. Include the entire only-if condition, not just its date. Production time is not receipt."},
    "payment_clause": {"type": "extract", "infer": False, "unit": "sentence", "list": True, "max_items": 2,
        "description": "Complete sentence about a deposit/payment trigger for offered delivery or production, including any statement that the deposit has not cleared; preserve not and only if."},
    "production_clause": {"type": "extract", "infer": False, "unit": "sentence",
        "description": "Complete source sentence specifying production or dispatch lead time and its trigger. Do not substitute a destination receipt date."},
    "version_clause": {"type": "extract", "infer": False, "unit": "sentence", "list": True, "max_items": 2,
        "description": "Complete source sentence explicitly stating a revision supersedes an older version, an older offer is obsolete, or multiple versions are present. Leave null when no such statement exists."},
    "freight_status": {"type": "choice", "description": "How does this quotation establish freight to destination? Do not turn a subtotal or unpriced freight into an included delivered total.",
        "options": ["included_and_priced", "excluded_or_unpriced", "not_established"]},
    "receipt_status": {"type": "choice", "description": "What does this quotation establish about actual destination receipt? A production or dispatch lead time is not an arrival commitment; retain payment and other conditions.",
        "options": ["firm_receipt_date", "conditional_receipt", "not_committed", "not_established"]},
    "unmet_payment_condition": {"type": "yes_no", "description": "Does the offered receipt, dispatch or production timing depend on a payment/deposit condition not explicitly stated to have been fulfilled in this quotation? Do not infer that any deposit has cleared."},
    "version_attention": {"type": "yes_no", "description": "Does this text explicitly distinguish superseded/obsolete and current quotation revisions, or contain competing revisions needing identification?"},
}


def request_for(document):
    return {"text": document["text"], "fields": FIELDS,
        "instructions": "Read only this supplier quotation. Extraction fields must be verbatim full source sentences with their original offsets, not normalized dates/numbers or generated summaries. Preserve negation, exclusions, production versus transit/receipt, and every payment/only-if qualifier. If a fact is not found, return null; do not borrow from another supplier or invent a price/date. Decision fields are review signals, not proof that an omitted term is absent."}


def read_spans(field, identifier, documents):
    if not isinstance(field, dict) or field.get("value") is None:
        return []
    items = field.get("items") if isinstance(field.get("value"), list) else [field]
    if not isinstance(items, list):
        return []
    spans = []
    for item in items:
        if not isinstance(item, dict):
            continue
        span = span_from_api({"document": identifier, "quote": item.get("value"),
            "start": item.get("start"), "end": item.get("end")}, documents, identifier)
        spans.append(span)
    return spans


def normalize(data, document, documents):
    fields = data.get("fields") if isinstance(data, dict) else None
    if not isinstance(fields, dict):
        raise ValueError("Fill returned no commercial term fields.")
    clauses = {name: read_spans(fields.get(name), document["id"], documents)
               for name in ("freight_clause", "receipt_clause", "payment_clause", "production_clause", "version_clause")}
    statuses = {}
    for name, allowed in (("freight_status", FIELDS["freight_status"]["options"]),
                          ("receipt_status", FIELDS["receipt_status"]["options"])):
        raw = fields.get(name, {})
        value = raw.get("value") if isinstance(raw, dict) else None
        statuses[name] = value if value in allowed else "not_established"
    for name in ("unmet_payment_condition", "version_attention"):
        raw = fields.get(name, {})
        value = raw.get("value") if isinstance(raw, dict) else None
        statuses[name] = value if type(value) is bool else None
    # A positive decision without located supporting source is not a confirmed term.
    if not any(s["integrity"] == "exact" for s in clauses["freight_clause"]):
        statuses["freight_status"] = "not_established"
    if not any(s["integrity"] == "exact" for s in clauses["receipt_clause"]):
        statuses["receipt_status"] = "not_established"
    warnings = []
    for name in clauses:
        field = fields.get(name)
        if not isinstance(field, dict) or field.get("value") is None:
            warnings.append({"field": name, "code": "not_located",
                "reason": field.get("reason") if isinstance(field, dict) else None})
        elif field.get("finish") == "cap":
            warnings.append({"field": name, "code": "list_limit_reached", "reason": "The bounded read may omit additional source clauses."})
        if any(s["integrity"] != "exact" for s in clauses[name]):
            warnings.append({"field": name, "code": "unlocated_source", "reason": "Returned source coordinates could not be verified; no repair was attempted."})
    return {"documentId": document["id"], "supplier": document["supplier"],
        "origin": "fill", "clauses": clauses, "signals": statuses,
        "signalReadouts": {name: fields.get(name) for name in statuses}, "warnings": warnings}


def make_questions(review, rfq, supplier):
    questions, findings = [], []
    rfq_span = {"documentId": rfq["id"], "quote": rfq["text"], "start": 0,
        "end": len(rfq["text"]), "integrity": "exact"}
    signals, clauses = review["signals"], review["clauses"]

    def add(kind, names, prompt):
        spans = []
        for name in names:
            spans += [s for s in clauses.get(name, []) if s["integrity"] == "exact"]
        # Keep source coordinates, never repair a missing/incorrect offset by search.
        spans = list({(s["documentId"], s["start"], s["end"]): s for s in spans}.values())
        identifier = "term-%s-%s" % (supplier["id"], kind)
        prefix = "Your quotation states: " + " ".join("“%s”" % s["quote"] for s in spans) + " " if spans else (
            "The analysis did not locate a usable source passage for this term; this does not establish that your quotation omitted it. ")
        sources = spans if spans else [rfq_span]
        if any(w["code"] == "list_limit_reached" and w["field"] in names for w in review.get("warnings", [])):
            prompt += " The bounded source read may not include every condition; please confirm any additional conditions in the original quotation."
        questions.append({"id": identifier + "-question", "supplierId": supplier["id"],
            "supplier": supplier["supplier"], "findingId": identifier, "text": prefix + prompt,
            "sources": sources, "status": "needs_confirmation", "origin": "fill", "term": kind})
        findings.append({"id": identifier, "pairId": None, "kind": kind, "label": "Terms to confirm",
            "a": rfq_span, "b": spans[0] if spans else {"documentId": supplier["id"], "quote": None,
                "start": None, "end": None, "integrity": "missing"},
            "sourceIntegrity": "exact" if spans else "one_sided", "questionIds": [identifier + "-question"],
            "origin": "fill"})

    if signals["freight_status"] != "included_and_priced":
        add("freight", ["freight_clause"],
            "Please quote or confirm freight to the RFQ destination and a complete delivered total for the requested quantity, identifying included charges and exclusions. An unpriced charge cannot be treated as zero.")
    if signals["receipt_status"] != "firm_receipt_date":
        add("receipt", ["receipt_clause", "production_clause", "payment_clause"],
            "Please confirm an actual destination receipt date against our RFQ deadline, separately from production/dispatch time. State the payment or other conditions and whether that date remains achievable given when those conditions can actually be fulfilled.")
    if signals["unmet_payment_condition"] is True:
        add("payment_condition", ["payment_clause", "receipt_clause"],
            "Please confirm the deposit/payment deadline and clearance trigger behind this offer, whether it has been fulfilled, and how any offered production, dispatch or receipt timing changes if it has not. We are not treating a conditional date as an unconditional commitment.")
    if signals["version_attention"] is True:
        add("revision", ["version_clause"],
            "Please identify the currently valid revision and confirm which earlier quoted terms it replaces; keep obsolete terms separate from the current offer.")
    return findings, questions
