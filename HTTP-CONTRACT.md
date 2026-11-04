# QuoteClarify HTTP contract v1

Local only: `http://127.0.0.1:8190`, Python 3.9 standard library. UI files are served from `web/` at `/`. No browser-side API key. JSON responses use UTF-8. All examples are synthetic. Service never reads `fixtures/acceptance`.

## Input

```json
{"rfq":{"id":"rfq","title":"Buyer requirement","text":"Original unchanged text"},"quotes":[{"id":"quote-a","title":"Offer A","supplier":"Supplier A","text":"Original unchanged text"},{"id":"quote-b","title":"Offer B","supplier":"Supplier B","text":"Original unchanged text"}],"focus":"Which price, delivery, payment and scope terms require clarification?","draftSummary":"Optional buyer-written memo to verify"}
```

Exactly one RFQ and two quotes. IDs unique, `[a-zA-Z0-9_-]{1,64}`. Each text 1–6,000 Unicode code points, aggregate ≤12,000. `focus` 1–1,000, `draftSummary` optional 0–2,000. Titles ≤120 and supplier labels ≤100. Preserve original strings/line endings. Unknown keys rejected. `inputDigest` binds RFQ, quotes and focus; `revision` also binds the exact memo and analysis outputs. These are opaque SHA256 strings; do not derive them in UI.

## Endpoints

- `GET /api/health` → `{ok:true,name:"QuoteClarify",version:"0.1"}`.
- `GET /api/status` → `{configured:true,budget:{limitCredits:1000,usedCredits:13,remainingCredits:987},pendingJobs:0,externalMode:"live",cashOverageEnabled:false}`. Budget numbers cover this development stage, not all account credits. Key contents never returned.
- `GET /api/examples` → `{synthetic:true,examples:[{id,title,input:<Input>}]}`. Three allowlisted cases; no gold/expected fields.
- `POST /api/analyze` with Input → HTTP202 `{jobId,status:"queued",pollUrl:"/api/jobs/<id>"}`. Compare and Rerank run; Grounding runs only when a nonempty user memo is supplied.
- `GET /api/jobs/<id>` → `{jobId,status,stage,progress,error,result}`. `status`: `queued|running|succeeded|failed`; `stage`: `queued|compare|rerank|grounding|complete|failed`; `progress` is an array of completed `{endpoint,transport,credits,referenceCostUsd,elapsedMs}`. `error:null|{code,message,retryable}`. `result:null|<Result>`; result is present only on success. Keep supplied inputs visible on failure, show completed progress, never show a success badge for partial work.
- `GET /api/analyses/<analysisId>` → Result. Immutable completed analysis; 404 if absent.
- `POST /api/verify` body `{analysisId,expectedRevision,draftSummary}` → HTTP202 job acknowledgement. Checks existing revision, reuses Compare/Rerank, calls Grounding on new memo only; produces a NEW analysisId/revision. Original analysis stays immutable. Source edits require a new `/analyze`.
- `POST /api/export` body `{analysisId,expectedRevision,input:<current Input>}` → `{analysisId,revision,text,filename,contentType:"text/plain;charset=utf-8",includedMemo:boolean}`. Server recomputes digest of current RFQ/quotes/focus and requires exact equality. Memo must also equal the analyzed memo; changed source/focus/memo returns409. Returns supplier questions from exact source passages. Buyer memo is included only when Grounding status is `supported`; other draft claims remain visibly withheld. No ranking or purchase recommendation.

## Result (exact top-level field names)

```json
{
 "analysisId":"uuid","revision":"sha256","inputDigest":"sha256","createdAt":"ISO UTC",
 "input":{},
 "documents":[{"id":"rfq","title":"Buyer requirement","role":"rfq","supplier":null,"text":"raw"}],
 "comparisons":[{"id":"pair-0","a":"rfq","b":"quote-a","relation":"conflicting","related":0.9,"probabilities":{},"findingIds":["finding-0-0"]}],
 "findings":[{"id":"finding-0-0","pairId":"pair-0","kind":"value","label":"Terms to clarify","a":{},"b":{},"sourceIntegrity":"exact","questionIds":["question-0-0-quote-a"]}],
 "rerank":{"status":"completed","query":"...","results":[{"documentId":"quote-a","action":"use","reason":null,"relevanceScore":0.9,"documentScore":0.95,"levels":{}}]},
 "grounding":{"status":"not_requested","text":"","verdict":null,"grounded":null,"claims":[]},
 "clarifications":[{"id":"question-0-0-quote-a","supplierId":"quote-a","supplier":"Supplier A","findingId":"finding-0-0","text":"A concrete question containing own quote and, if applicable, RFQ excerpt","sources":[],"status":"ready"}],
 "usage":{"newCredits":13,"referenceCostUsd":0.0026,"calls":[]},
 "limitations":["Review aid using supplied sources; not a purchase approval or external truth verification."]
}
```

`documents` contains all three raw sources. `input` is the original input object including memo if any. `usage.calls` and job `progress` share the meta shape above; transport `live|replay|cache` clearly distinguishes new model work from reuse. A cached/replayed result contributes **0 newCredits**, even if the original debit headers are retained in client evidence. Cost is Production reference only; cash charge is zero on this trial.

`Span = {documentId,quote,start,end,integrity}`; start/end nullable, zero-based Unicode **code points**, end-exclusive. `integrity` is `exact|missing|mismatch`; JS highlight with `Array.from(text).slice(start,end)`, never UTF16 offsets. Never synthesize a quote when absent or mismatched. `sourceIntegrity` for findings is `exact` only when both sides validate. Invalid/missing-source findings remain visible, create no ready export question.

`grounding.status = not_requested|supported|needs_review`; `needs_review` includes contradicted, not_stated, missing/mismatched evidence, low support or no counted claims. `claims[] = {id,text,verdict,supported,contradicted,notStated,counted,sourceId,evidence:Span|null,ready:boolean}`. Model verdict is an untrusted string for display, not a UI success enum. `ready` requires API supported + support≥0.8 + exact source evidence. `supported` for a memo requires every counted claim ready and ≥1 counted claim. It means supported by supplied text, not objectively true. Verify HTTP failures fail the job rather than turning into `needs_review` success.

Rerank `use|expand|skip` only controls focus presentation; it does not discard quotes or select a supplier. API `conflicting` is displayed as different terms requiring clarification; requirements versus offers and different versions are not automatically contradictory facts. Quote-versus-quote questions never expose one supplier’s competing quote to the other; RFQ excerpts may be included.

## Errors and persistence

Synchronous validation errors: HTTP400 `{error:{code:"invalid_input",message,retryable:false}}`; missing ID404; revision/input mismatch409 `stale_analysis`; credits gate402 `development_budget_exhausted`; other failures500. Background upstream errors are recorded in `job.error`; poll stays200. Client has no automatic retry that could incur duplicate charges. Unknown network result preserves one request ID in the local ledger; operator recovery reuses the identical key/payload. No product retry control is exposed in v1.

Local job/analysis/cache/usage state persists in `.local/` (gitignored). Actual model outputs are used; cached results state `transport:cache`. QA can import `core.analyze_case(request, client, on_progress=None)` without credentials/network. Inject `client.call(endpoint,payload)` returning `{data:<endpoint raw body>,meta:{requestId,endpoint,transport,credits,referenceCostUsd,elapsedMs}}`; exceptions should be `client.ApiError(code,message,retryable=False)` or ordinary exceptions. All source text is validated before invocation. Core never loads examples or acceptance gold itself.
