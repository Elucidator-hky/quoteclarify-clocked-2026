# QuoteClarify

Turn a buyer RFQ and two supplier quotations into source-linked clarification questions. Compare finds terms needing review, Rerank focuses the original documents, and Verify checks an editable buyer memo. This is a review aid: no supplier ranking, landed-cost calculation, currency conversion or purchase approval.

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
2. Analyze; inspect each supplier question alongside both exact passages, or a clearly marked one-sided request for confirmation.
3. Enter or edit a buyer memo and run Verify separately. `not_stated`, contradictions, missing evidence and low support remain visible.
4. Export supplier questions plus individually supported, located memo claim excerpts. The untouched original memo paragraph is never certified or exported as a whole. A source, focus or memo edit invalidates the old export request.

Returned offsets count Unicode code points, not UTF16 or UTF8 bytes. An exact quote establishes what the supplied text says; it does not prove external truth. A model can overlook or misclassify a clause. A missing quote is not reconstructed, and absence from an API finding is not proof that a supplier omitted a term. Rerank does not exclude suppliers.

Network outcomes retain their original idempotency key. Retrying the same completed input uses a clearly marked local cache. Unknown outcomes pause different new work; no automatic paid retry or background model loop runs.

## Tests and API

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

Client tests use a fake transport and temporary database, make no external calls and read no real credentials. Independent acceptance tests are maintained separately by the review agent. The precise request/result contract is in [HTTP-CONTRACT.md](HTTP-CONTRACT.md). Official API documentation: [Compare](https://clocked.rezolve.ai/docs/compare), [Verify](https://clocked.rezolve.ai/docs/grounding), [Rerank](https://clocked.rezolve.ai/docs/rerank), [usage and source positions](https://clocked.rezolve.ai/docs/responses).
