"""Original QuoteClarify domain layer. No network, credentials, fixtures or gold."""
import copy
import datetime
import hashlib
import json
import math
import re
import uuid


class InputError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def require_string(value, name, maximum, minimum=1):
    if not isinstance(value, str) or not minimum <= len(value) <= maximum:
        raise InputError("%s must contain %d–%d Unicode characters." % (name, minimum, maximum))
    if minimum and not value.strip():
        raise InputError(name + " cannot be blank.")
    return value


def validate_input(value):
    if not isinstance(value, dict) or set(value) - {"rfq", "quotes", "focus", "draftSummary"}:
        raise InputError("Input must contain rfq, quotes, focus and optional draftSummary only.")
    if not isinstance(value.get("quotes"), list) or len(value["quotes"]) != 2:
        raise InputError("Supply exactly two quotations.")
    docs = [value.get("rfq")] + value["quotes"]
    seen = set()
    for index, document in enumerate(docs):
        allowed = {"id", "title", "text"} | ({"supplier"} if index else set())
        if not isinstance(document, dict) or set(document) != allowed:
            raise InputError("Each document needs id, title, text; each quotation also needs supplier.")
        identifier = require_string(document["id"], "document id", 64)
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier) or identifier in seen:
            raise InputError("Document IDs must be unique ASCII letters, digits, underscores or hyphens.")
        seen.add(identifier)
        require_string(document["text"], "document text", 6000)
        require_string(document["title"], "document title", 120)
        if index:
            require_string(document["supplier"], "supplier", 100)
    if sum(len(d["text"]) for d in docs) > 12000:
        raise InputError("The three documents together must not exceed 12,000 Unicode characters.")
    require_string(value.get("focus"), "focus", 1000)
    require_string(value.get("draftSummary", ""), "draftSummary", 2000, 0)
    return copy.deepcopy(value)


def input_digest(value):
    checked = validate_input(value)
    return digest({k: checked[k] for k in ("rfq", "quotes", "focus")})


def document_list(value):
    return [dict(value["rfq"], role="rfq", supplier=None)] + [
        dict(q, role="quote") for q in value["quotes"]]


def span_from_api(value, documents, expected_id=None):
    """Accept source positions only when exact, never search or repair a quote."""
    if not isinstance(value, dict):
        return {"documentId": expected_id, "quote": None, "start": None,
                "end": None, "integrity": "missing"}
    document_id = value.get("document")
    quote, start, end = value.get("quote"), value.get("start"), value.get("end")
    out = {"documentId": document_id, "quote": quote, "start": start, "end": end,
           "integrity": "mismatch"}
    if quote is None or start is None or end is None:
        out["integrity"] = "missing"
        return out
    source = documents.get(document_id)
    if (source is not None and (expected_id is None or document_id == expected_id)
            and isinstance(quote, str) and quote
            and type(start) is int and type(end) is int
            and 0 <= start < end <= len(source["text"])
            and source["text"][start:end] == quote):
        out["integrity"] = "exact"
    return out


def probability(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value) if 0 <= value <= 1 else None
    return None


def clarification_prompt(quote):
    """Choose questions from observed clause words, never infer commercial values."""
    lower = quote.lower()
    questions = []
    if re.search(r"required.{0,40}(receipt|arrival|deliver)|no later than|到货日期|最迟|截止", lower):
        questions.append("Can you meet the required receipt date quoted above? If not, please state the earliest firm receipt date and quote any alternative delivery option, including its additional charge if any.")
    if re.search(r"freight|shipping|insurance|\bfob\b|\bcif\b|\bexw\b|运费|运输|保险", lower):
        questions.append("Which freight, insurance and other charges remain outside this term, and which trade term and named place apply?")
    if not questions and re.search(r"deliver|dispatch|lead.time|arrival|receipt|发货|交货|到货|交期", lower):
        questions.append("What starts this lead time, and what dispatch and arrival dates can you commit to against our requirement?")
    if re.search(r"payment|deposit|advance|balance|付款|订金|定金|预付|尾款", lower):
        questions.append("Please confirm each payment milestone and its trigger, including any conditions attached to it.")
    if re.search(r"revis|supersed|valid|expir|版本|修订|有效", lower):
        questions.append("Which revision is currently valid, until when, and does it replace earlier terms?")
    if re.search(r"quantity|\bmoq\b|\bunit\b|\bpack|\bprice\b|数量|单价|单位|包装", lower):
        questions.append("Please confirm the pricing unit, quantity covered and exclusions so we can compare the same scope.")
    return " ".join(questions[:2]) if questions else "Please confirm how this term meets our requirement and identify any conditions or changes needed."


def normalize_comparison(data, documents):
    comparisons, findings, questions = [], [], []
    if not isinstance(data, dict) or not isinstance(data.get("pairs"), list):
        raise ValueError("Compare returned no valid pair list.")
    seen_pairs = set()
    for pair_index, pair in enumerate(data["pairs"]):
        if not isinstance(pair, dict):
            raise ValueError("Compare returned an invalid pair.")
        a_id, b_id = pair.get("a"), pair.get("b")
        if a_id not in documents or b_id not in documents or a_id == b_id:
            raise ValueError("Compare returned an unrecognized source pair.")
        identity = tuple(sorted([a_id, b_id]))
        if identity in seen_pairs:
            raise ValueError("Compare returned a duplicate source pair.")
        seen_pairs.add(identity)
        pair_id = "pair-%d" % pair_index
        comparison = {"id": pair_id, "a": a_id, "b": b_id,
            "relation": pair.get("relation"), "related": probability(pair.get("related")),
            "probabilities": pair.get("probabilities", {}), "findingIds": []}
        conflicts = pair.get("conflicts", [])
        if not isinstance(conflicts, list):
            raise ValueError("Compare returned malformed findings.")
        for finding_index, item in enumerate(conflicts):
            if not isinstance(item, dict):
                raise ValueError("Compare returned a malformed finding.")
            identifier = "finding-%d-%d" % (pair_index, finding_index)
            a = span_from_api(item.get("a"), documents, a_id)
            b = span_from_api(item.get("b"), documents, b_id)
            exact = a["integrity"] == b["integrity"] == "exact"
            finding = {"id": identifier, "pairId": pair_id, "kind": item.get("kind"),
                "label": "Terms to clarify", "a": a, "b": b,
                "sourceIntegrity": "exact" if exact else "needs_review", "questionIds": []}
            if exact:
                # A supplier never receives the competing supplier's confidential terms.
                for own, counterpart in ((a, b), (b, a)):
                    own_doc, other_doc = documents[own["documentId"]], documents[counterpart["documentId"]]
                    if own_doc["role"] != "quote":
                        continue
                    question_id = identifier.replace("finding", "question") + "-" + own_doc["id"]
                    if other_doc["role"] == "rfq":
                        text = ("Our request states: “%s” Your quotation states: “%s” "
                                "%s") % (counterpart["quote"], own["quote"], clarification_prompt(counterpart["quote"] + " " + own["quote"]))
                        sources = [counterpart, own]
                    else:
                        text = "Your quotation states: “%s” %s" % (own["quote"], clarification_prompt(own["quote"]))
                        sources = [own]
                    questions.append({"id": question_id, "supplierId": own_doc["id"],
                        "supplier": own_doc["supplier"], "findingId": identifier,
                        "text": text, "sources": sources, "status": "ready"})
                    finding["questionIds"].append(question_id)
            elif (a["integrity"] == "exact" and documents[a_id]["role"] == "rfq" and b["integrity"] == "missing"
                    or b["integrity"] == "exact" and documents[b_id]["role"] == "rfq" and a["integrity"] == "missing"):
                requirement, supplier_id = (a, b_id) if a["integrity"] == "exact" else (b, a_id)
                supplier = documents[supplier_id]
                if supplier["role"] == "quote":
                    question_id = identifier.replace("finding", "question") + "-" + supplier_id
                    text = ("Our request states: “%s” %s The analysis returned no corresponding quotation passage; "
                            "this is a request for confirmation, not a finding that your quotation omitted the term.") % (requirement["quote"], clarification_prompt(requirement["quote"]))
                    questions.append({"id": question_id, "supplierId": supplier_id,
                        "supplier": supplier["supplier"], "findingId": identifier, "text": text,
                        "sources": [requirement], "status": "needs_confirmation"})
                    finding["sourceIntegrity"] = "one_sided"
                    finding["questionIds"].append(question_id)
            comparison["findingIds"].append(identifier)
            findings.append(finding)
        comparisons.append(comparison)
    expected = len(documents) * (len(documents) - 1) // 2
    if len(seen_pairs) != expected:
        raise ValueError("Compare did not return every source pair; analysis is incomplete.")
    return comparisons, findings, questions


def normalize_rerank(data, value, documents):
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("Rerank returned no valid results.")
    results, seen = [], set()
    for item in data["results"]:
        identifier = item.get("id")
        if identifier not in documents or identifier in seen or item.get("action") not in ("use", "expand", "skip"):
            raise ValueError("Rerank returned an invalid source or action.")
        seen.add(identifier)
        results.append({"documentId": identifier, "action": item["action"],
            "reason": item.get("reason"), "relevanceScore": probability(item.get("relevance_score")),
            "documentScore": probability(item.get("document_score")), "levels": item.get("levels", {})})
    if seen != set(documents):
        raise ValueError("Rerank omitted a submitted document.")
    return {"status": "completed", "query": value["focus"], "results": results}


def normalize_grounding(data, text, documents):
    if not isinstance(data, dict) or not isinstance(data.get("claims"), list):
        raise ValueError("Verify returned no valid claims.")
    claims = []
    for index, item in enumerate(data["claims"]):
        if not isinstance(item, dict) or not isinstance(item.get("claim"), str):
            raise ValueError("Verify returned an invalid claim.")
        evidence = span_from_api(item.get("evidence"), documents) if item.get("evidence") else None
        support = probability(item.get("supported"))
        counted = item.get("counted") is True
        ready = (counted and item.get("verdict") == "supported" and support is not None
            and support >= 0.8 and evidence is not None and evidence["integrity"] == "exact"
            and (item.get("source") is None or item.get("source") == evidence["documentId"]))
        claims.append({"id": "memo-claim-%d" % index, "text": item["claim"],
            "verdict": item.get("verdict"), "supported": support,
            "contradicted": probability(item.get("contradicted")),
            "notStated": probability(item.get("not_stated")), "counted": counted,
            "sourceId": item.get("source"), "evidence": evidence, "ready": bool(ready)})
    factual = [c for c in claims if c["counted"]]
    return {"status": "supported" if factual and all(c["ready"] for c in factual) else "needs_review",
        "text": text, "verdict": data.get("verdict"), "grounded": probability(data.get("grounded")),
        "claims": claims, "reviewScope": "returned_claims_only",
        "originalDraftIncluded": False}


def finish(result):
    result["revision"] = digest({k: v for k, v in result.items() if k != "revision"})
    return result


def analyze_case(request, client, on_progress=None, base=None):
    value = validate_input(request)
    docs = document_list(value)
    document_map = {d["id"]: d for d in docs}
    result = {"analysisId": str(uuid.uuid4()), "inputDigest": input_digest(value),
        "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "input": value,
        "documents": docs, "comparisons": [], "findings": [], "clarifications": [],
        "rerank": {"status": "not_requested", "query": value["focus"], "results": []},
        "grounding": {"status": "not_requested", "text": "", "verdict": None, "grounded": None, "claims": []},
        "usage": {"newCredits": 0, "referenceCostUsd": 0, "calls": []},
        "limitations": ["Review aid using supplied sources; not a purchase approval or external truth verification.",
            "Different quotations, revisions and requirements may have different scope. A flagged difference needs clarification, not an automatic contradiction verdict.",
            "No currency/unit conversion, landed-cost calculation or supplier ranking is performed.",
            "Missing evidence is not fabricated; a clean result does not establish that every commercial risk was found."]}
    api_documents = [{"id": d["id"], "text": d["text"]} for d in docs]

    def call(endpoint, payload):
        if on_progress:
            on_progress(endpoint, None)
        response = client.call(endpoint, payload)
        if not isinstance(response, dict) or "data" not in response or "meta" not in response:
            raise ValueError("API client returned an invalid envelope.")
        meta = dict(response["meta"], endpoint=endpoint)
        result["usage"]["calls"].append(meta)
        # Transport is authoritative even if a replay receipt repeats its old debit.
        if meta.get("transport") in ("cache", "replay"):
            meta["credits"] = 0
        result["usage"]["newCredits"] += meta.get("credits", 0)
        if meta.get("transport") == "live":
            result["usage"]["referenceCostUsd"] += meta.get("referenceCostUsd", 0)
        if on_progress:
            on_progress(endpoint, meta)
        return response["data"]

    if base is not None:
        if base["inputDigest"] != result["inputDigest"]:
            raise InputError("A changed source or focus requires a new analysis.")
        for key in ("comparisons", "findings", "clarifications", "rerank"):
            result[key] = copy.deepcopy(base[key])
    else:
        compared = call("compare", {"documents": api_documents, "evidence": "all",
            "instructions": "These are a buyer RFQ and two supplier quotations for a purchase. Surface differences in price basis, currency, unit, model, delivery triggers, dates, payment, exclusions and scope that need human clarification. A requirement versus a different offer or an older version is not two simultaneously true conflicting facts. Preserve document attribution; do not assume acceptance, normalize units/currency, invent missing charges, or recommend a supplier."})
        result["comparisons"], result["findings"], result["clarifications"] = normalize_comparison(compared, document_map)
        ranked = call("rerank", {"query": value["focus"], "documents": [
            {"id": d["id"], "title": d["title"], "text": d["text"]} for d in docs],
            "context": {"task": "Buyer review of the supplied RFQ and quotations; focus only, not a supplier selection."}})
        result["rerank"] = normalize_rerank(ranked, value, document_map)
    memo = value.get("draftSummary", "")
    if memo.strip():
        grounded = call("grounding", {"documents": api_documents, "answer": memo,
            "question": "Is this buyer memo supported by the supplied RFQ and supplier quotations, with correct supplier, scope, units, currency and conditions?",
            "instructions": "Check each factual assertion independently. Do not treat a buyer requirement as a supplier commitment. Attribute suppliers and versions precisely. Missing terms are not zero costs or promises. A conditional delivery period does not establish a calendar arrival date. Do not infer lowest landed cost or a purchase recommendation.",
            "evidence": "all"})
        result["grounding"] = normalize_grounding(grounded, memo, document_map)
    return finish(result)


def export_text(result, current_input, expected_revision):
    value = validate_input(current_input)
    if (result["revision"] != expected_revision or result["inputDigest"] != input_digest(value)
            or value.get("draftSummary", "") != result["input"].get("draftSummary", "")):
        raise InputError("Source, focus or memo changed. Analyze or verify the current text before exporting.")
    lines = ["QUOTECLARIFY — SUPPLIER CLARIFICATION DRAFT", "",
        "Analysis: " + result["analysisId"], "Revision: " + result["revision"],
        "Prepared from supplied documents only. Review before sending. No purchase approval.", ""]
    if not result["clarifications"]:
        lines.append("No source-complete questions were produced. This is not confirmation that the offers match the RFQ.")
    for document in result["documents"]:
        if document["role"] != "quote":
            continue
        own = [q for q in result["clarifications"] if q["supplierId"] == document["id"] and q["status"] in ("ready", "needs_confirmation")]
        own = list({q["text"]: q for q in own}.values())
        lines.extend(["SUPPLIER: " + document["supplier"], ""])
        if not own:
            lines.append("No source-complete question produced; manually review omitted or unflagged terms.")
        for index, question in enumerate(own, 1):
            lines.append("%d. %s" % (index, question["text"]))
            for span in question["sources"]:
                lines.append("   Source %s, code points [%d:%d]: %s" % (
                    span["documentId"], span["start"], span["end"], span["quote"]))
        lines.append("")
    ready_claims = [claim for claim in result["grounding"]["claims"] if claim["ready"]]
    included = bool(ready_claims)
    if included:
        lines.extend(["MODEL-CHECKED CLAIMS — supplied-source support only, not external truth",
            "Only the individual claims below are included. The original draft is not exported or certified as a whole."])
        for claim in ready_claims:
            lines.append("- " + claim["text"])
            span = claim["evidence"]
            lines.append("  Source %s, code points [%d:%d]: %s" % (span["documentId"], span["start"], span["end"], span["quote"]))
        lines.append("")
    if result["grounding"]["status"] != "not_requested":
        lines.extend(["ORIGINAL BUYER DRAFT WITHHELD", "Unreturned, unsupported, uncertain and unlocated claims are not included as verified conclusions. Check the original draft and review results in the app.", ""])
    lines.extend(["LIMITATIONS"] + result["limitations"])
    return {"analysisId": result["analysisId"], "revision": result["revision"],
        "text": "\n".join(lines) + "\n", "filename": "quoteclarify-%s.txt" % result["analysisId"][:8],
        "contentType": "text/plain;charset=utf-8", "includedMemo": included,
        "includedClaimIds": [claim["id"] for claim in ready_claims], "originalDraftIncluded": False}
