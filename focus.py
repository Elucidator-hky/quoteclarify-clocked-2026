"""Source-preserving paragraph focus. Relevance never removes original evidence."""
import math
import re


def passages_for(documents, target=900):
    passages = []
    for document in documents.values():
        text = document["text"]
        # Blank lines are natural boundaries. Never cut a sentence/table merely
        # to meet a size target: even one long section fits the 6,000-char input.
        parts, start = [], 0
        for separator in re.finditer(r"(?:\r?\n)[ \t]*(?:\r?\n)+", text):
            if text[start:separator.start()].strip():
                parts.append((start, separator.start()))
            start = separator.end()
        if text[start:].strip():
            parts.append((start, len(text)))
        groups = []
        for start, end in parts:
            if groups and end - groups[-1][0] <= target:
                groups[-1] = (groups[-1][0], end)
            else:
                groups.append((start, end))
        for number, (start, end) in enumerate(groups, 1):
            passages.append({"id": document["id"] + "--part-" + str(number),
                "documentId": document["id"], "title": document["title"],
                "text": text[start:end], "start": start, "end": end,
                "part": number, "parts": len(groups)})
    return passages


def request_for(query, passages, documents):
    return {"query": query,
        "documents": [{"id": p["id"], "title": p["title"], "text": p["text"],
            "metadata": {"source": p["documentId"],
                "role": documents[p["documentId"]]["role"],
                "part": p["part"], "parts": p["parts"]}} for p in passages],
        "context": {"task": "Buyer reading the supplied RFQ and supplier quotations. Relevance is not a supplier selection or factual verification."},
        "instructions": "Rank each unchanged source section for the buyer's question. An RFQ states requirements, not a supplier promise. Other sections of the same document may qualify a clause; use expand when broader context is needed. Do not infer prices, dates, acceptance or supplier rankings."}


def probability(value):
    return float(value) if (isinstance(value, (int, float)) and not isinstance(value, bool)
        and math.isfinite(value) and 0 <= value <= 1) else None


def normalize(data, query, documents, passages):
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("Rerank returned no valid focus results.")
    by_id = {p["id"]: p for p in passages}
    results, seen = [], set()
    for item in data["results"]:
        if not isinstance(item, dict):
            raise ValueError("Rerank returned an invalid focus result.")
        identifier = item.get("id")
        if identifier not in by_id or identifier in seen or item.get("action") not in ("use", "expand", "skip"):
            raise ValueError("Rerank returned an invalid passage or action.")
        p = by_id[identifier]
        source = documents[p["documentId"]]["text"]
        if source[p["start"]:p["end"]] != p["text"]:
            raise ValueError("The focus passage no longer matches its original source.")
        seen.add(identifier)
        results.append({"passageId": identifier, "documentId": p["documentId"],
            "part": p["part"], "parts": p["parts"],
            "passage": {"documentId": p["documentId"], "quote": p["text"],
                "start": p["start"], "end": p["end"], "integrity": "exact"},
            "action": item["action"], "reason": item.get("reason"),
            "relevanceScore": probability(item.get("relevance_score")),
            "documentScore": probability(item.get("document_score")), "levels": item.get("levels", {})})
    if seen != set(by_id):
        raise ValueError("Rerank omitted a submitted passage.")
    return {"status": "completed", "query": query, "scope": "source_sections",
        "results": results, "sourceCount": len(documents), "passageCount": len(passages)}
