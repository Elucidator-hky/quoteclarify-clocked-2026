# QuoteClarify web interface

The Python application serves this directory at `http://127.0.0.1:8190`. Start the server using the parent app README. The interface uses native HTML, CSS and JavaScript without external assets or a browser API credential.

`app.js` consumes the same-origin endpoints in `../HTTP-CONTRACT.md`. The RFQ, both quotations and focus remain editable. Example data is fetched from the server and explicitly marked synthetic. Source text, identifiers and document titles are preserved when loading examples. The browser performs accessible validation and switches to a missing quotation field before focusing it.

An analysis creates one server job. Progress and recovery query that same job; transient GET failures have a bounded retry. An unconfirmed final status retains the known job identifier and blocks a new analysis until the server history is reconciled. Source or focus changes require a full analysis. Note edits reuse the existing comparison and ranking through Verify.

A separate Fill source read per quotation preserves freight, receipt, payment, production and revision passages. The UI shows review signals beside exact source wording, qualifies missing passages and never promotes model scores or boolean choices into commercial guarantees. Questions remain requests for supplier confirmation even when source passages are exact.

Source highlights use Unicode code points and independently compare the returned span with the unchanged source. Ranked documents remain available even when marked skip. Single-sided requirements are questions to confirm, never assertions that a supplier omitted them. Verify covers only returned claims: the full original note stays visible, and the server exports only supported individual claims with exact evidence. Copy and download request a current-revision export from the server.

## Frontend verification

From the app directory run:

```sh
node --check web/app.js
python3 web/tests/ui_smoke.py
python3 web/tests/fill_ui_smoke.py
```

The smoke check uses an independent headless Chrome and intercepts every `/api/` request with labelled synthetic TEST responses. It consumes zero Clocked credits and validates rendering, input handling, source positioning, stale-result protection, current-revision export, temporary polling failure, failed jobs, free-only gating and mobile layout. The Fill-specific check replays a retained real synthetic API response through TEST-only interception and checks conditional/unknown source wording and the two-read progress. Its fixture is used only by the test and is never loaded by the product. These are not model accuracy tests. Generated screenshots and `report.json` stay in ignored `web/tests/artifacts/`. Independent QA records the separate real-response buyer workflow outside this directory.
