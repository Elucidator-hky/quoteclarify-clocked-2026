# QuoteClarify

Turn a buyer RFQ and two supplier quotations into source-linked clarification questions. Compare reports document relationships, Fill reads verbatim commercial conditions, Rerank locates original sections for the buyer's focus, and Verify checks an editable buyer memo. This is a review aid: no supplier ranking, landed-cost calculation, currency conversion or purchase approval.

**[Watch the recorded workflow — 2m42s](https://elucidator-hky.github.io/quoteclarify-clocked-2026/).** One continuous recording shows synthetic quotations, scripted user actions and earlier actual Clocked responses reused from the local cache; no fresh model calls or mocked responses occur during recording. English captions and no audio accompany questions from an empty memo, rejected and supported note claims, the actual downloaded brief, a source edit invalidating the old result, and a longer quotation whose highlighted original sections change with freight versus arrival focus. The player is a recording; local setup follows below.

All core code was started for the Clocked Build Challenge on 4 November 2026. It does not reuse earlier hackathon application cores. The examples are original synthetic materials prepared for this project; they do not describe real suppliers, transactions or employer data.

## Run locally

Requires Python 3.9+ and a Clocked API key. No third-party Python packages or frontend build step.

Create `~/.config/secrets/clocked.env` locally, outside the repository:

```sh
CLOCKED_API_KEY=your_key_here
```

Then:

```sh
python3 server.py
```

Open `http://127.0.0.1:8190`. The server binds only to the local host, keeps the API key on the backend and stores review data, request identities, raw receipts and cache in gitignored `.local/`. No paid plan is enabled by this application. A free account is required for live analysis; local source display and examples do not invoke the model. Model work consumes account credits even when the account is free.

The included development ledger stops new requests when fewer than 200 of its 1,000-credit budget remain. This is an application reserve, not an upstream hard per-call credit cap: a single accepted call is billed for its actual model time. Responses and the ledger show actual debits. Never treat the displayed Production reference dollars as an actual trial cash charge.

## Review and export

1. Load a synthetic example or paste one RFQ and two quotations. Source text remains unchanged.
2. Analyze; inspect each supplier question alongside exact source passages, or a clearly marked request for confirmation when the model did not locate a term. In Terms & evidence, focus results show unchanged source sections: locate a section in its full original document, and read the neighboring conditions when the result says expand. Changing the focus changes reading order, not supplier eligibility or the independently generated questions. Overlapping quotations are not automatically commercially equivalent: Fill separately reads freight, actual receipt versus production time, deposit conditions and revision clauses even without a buyer memo.
3. Enter or edit a buyer memo and run Verify separately. `not_stated`, contradictions, missing evidence and low support remain visible.
4. Export supplier questions plus individually supported, located memo claim excerpts. The untouched original memo paragraph is never certified or exported as a whole. A source, focus or memo edit invalidates the old export request.

### Resume the current review after refresh

The current browser tab keeps its confirmed job/result references and unsent source, focus and buyer-note edits in session storage. Refresh reopens that review through the same local server, or resumes GET polling for its acknowledged job. It does not start another analysis or model request. A restored review labels the original run’s usage separately from new work; the displayed build-budget ledger is not the platform account balance.

Edits remain distinct from the analyzed source: changed sources, focus or notes keep export blocked until analyzed or verified. Start blank and choosing another example discard the previous recovery reference and result. **Discard saved review, keep inputs** explicitly drops that result/reference while keeping the current input fields. An unknown or failed reference explains the failure without pretending an old result matches; an unconfirmed request stays blocked until explicitly discarded after checking server history.

This is refresh recovery for one tab and one local service, not a review archive or cloud synchronization. Closing the tab, clearing browser storage or losing the server’s saved records can make recovery unavailable. If the browser blocks storage, the page explains that the current review cannot be saved for refresh; keep it open or download the brief.

Returned offsets count Unicode code points, not UTF16 or UTF8 bytes. Fill uses strictly verbatim sentence reads (`infer:false`) and separate decision signals; generated/normalized dates and prices are not used as source quotes. A returned list may be capped, and rejected or missing values remain unlocated rather than recovered from diagnostics. An exact quote establishes what the supplied text says; it does not prove external truth. A model can overlook or misclassify a clause. A missing quote is not reconstructed, and absence from an API finding is not proof that a supplier omitted a term. Rerank reads natural source sections grouped up to a 900-character target; a longer unbroken section stays whole. Its use/expand/skip labels only guide reading. Every section and complete source remains accessible, including skip; Rerank failure falls back to complete sources without deleting earlier questions. Fill and Verify still read the original documents independently.

Network outcomes retain their original idempotency key. Retrying the same completed input uses a clearly marked local cache. Unknown outcomes pause different new work; no automatic paid retry or background model loop runs.

## Tests and API

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Client tests use a fake transport and temporary database, make no external calls and read no real credentials. Independent acceptance tests are maintained separately by the review agent. The precise request/result contract is in [HTTP-CONTRACT.md](HTTP-CONTRACT.md). Official API documentation: [Compare](https://clocked.rezolve.ai/docs/compare), [Fill](https://clocked.rezolve.ai/docs/fill), [Verify](https://clocked.rezolve.ai/docs/grounding), [Rerank](https://clocked.rezolve.ai/docs/rerank), [usage and source positions](https://clocked.rezolve.ai/docs/responses).
