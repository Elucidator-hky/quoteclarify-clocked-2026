const $ = (id) => document.getElementById(id);
const state = { examples: [], service: null, result: null, busy: false, job: null, memo: '', inputMeta: null, unresolvedRequest: false, evidence: new Map(), toastTimer: null };
const BASE_FOCUS = 'Which terms need clarification before I can compare delivered cost and receipt dates?';
const escapeHtml = (value) => String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const arr = (value) => Array.isArray(value) ? value : [];
const cpLength = (value) => Array.from(value || '').length;
const human = (value) => String(value || 'unavailable').replace(/[_-]/g, ' ');
const setText = (id, text) => { $(id).textContent = text; };
const show = (id, visible = true) => { $(id).hidden = !visible; };
const canonical = (obj) => JSON.stringify(obj, (_key, value) => value && typeof value === 'object' && !Array.isArray(value) ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))) : value);

function inputValue() {
  return {
    rfq: { id: state.inputMeta?.rfq?.id || 'rfq', title: state.inputMeta?.rfq?.title || 'Buyer requirement', text: $('rfq-text').value },
    quotes: ['a', 'b'].map((letter) => ({ id: state.inputMeta?.quotes?.[letter === 'a' ? 0 : 1]?.id || `quote-${letter}`, title: state.inputMeta?.quotes?.[letter === 'a' ? 0 : 1]?.title || `Offer ${letter.toUpperCase()}`, supplier: $('quote-' + letter + '-name').value || 'Supplier ' + letter.toUpperCase(), text: $('quote-' + letter + '-text').value })),
    focus: $('focus-input').value,
    draftSummary: state.memo,
  };
}
function baseSignature(input) {
  return canonical({ rfq: input.rfq, quotes: input.quotes, focus: input.focus });
}
function inputIsStale() { return !!state.result && baseSignature(inputValue()) !== baseSignature(state.result.input); }
function memoIsStale() { return !!state.result && state.memo !== (state.result.input?.draftSummary || ''); }
function canRun() { return !!state.service?.configured && state.service.cashOverageEnabled === false && Number(state.service.budget?.remainingCredits) > 0; }
function updateButtons() {
  $('analyze-button').disabled = state.busy || !canRun() || state.unresolvedRequest;
  $('example-select').disabled = state.busy;
  $('clear-inputs').disabled = state.busy;
  const stale = inputIsStale();
  const memoStale = memoIsStale();
  $('copy-brief').disabled = $('download-brief').disabled = !state.result || state.busy || stale || memoStale;
  $('verify-note').disabled = !state.result || state.busy || stale || !state.memo.trim() || !canRun() || state.unresolvedRequest;
  $('reanalyze-button').disabled = state.busy || !canRun() || state.unresolvedRequest;
  show('stale-notice', !!state.result && (stale || memoStale));
  if (state.result && (stale || memoStale)) {
    $('stale-notice').querySelector('span').textContent = stale ? 'Inputs have changed. This brief belongs to the previous input.' : 'Your buyer note changed. Verify this version before exporting.';
    setText('reanalyze-button', stale ? 'Analyze again ↗' : 'Verify note ↗');
  }
  if (state.result) setText('verify-hint', stale ? 'Source inputs changed. Analyze again before checking a note.' : memoStale ? 'This edited note has not been verified yet.' : 'Checks use the sources from this analysis.');
  ['a', 'b'].forEach((letter) => $('quote-' + letter + '-fill').classList.toggle('filled', !!$('quote-' + letter + '-text').value.trim()));
}

function selectTab(group, value, focus = false) {
  const attribute = group === 'quote' ? 'data-quote-tab' : 'data-output-tab';
  document.querySelectorAll(`[${attribute}]`).forEach((button) => {
    const selected = button.getAttribute(attribute) === value;
    button.setAttribute('aria-selected', String(selected)); button.tabIndex = selected ? 0 : -1;
    $(button.getAttribute('aria-controls')).hidden = !selected;
    if (selected && focus) button.focus();
  });
}
function tabKeyboard(event, group) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
  const attr = group === 'quote' ? 'data-quote-tab' : 'data-output-tab';
  const buttons = [...document.querySelectorAll(`[${attr}]`)];
  const current = buttons.indexOf(event.target);
  if (current < 0) return;
  event.preventDefault();
  const index = event.key === 'Home' ? 0 : event.key === 'End' ? buttons.length - 1 : (current + (event.key === 'ArrowRight' ? 1 : -1) + buttons.length) % buttons.length;
  selectTab(group, buttons[index].getAttribute(attr), true);
}

async function api(path, options = {}) {
  if (!path.startsWith('/api/') || new URL(path, location.href).origin !== location.origin) throw new Error('Unexpected API location.');
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 18000);
  try {
    const response = await fetch(path, { ...options, signal: controller.signal, headers: { 'Accept': 'application/json', ...(options.body ? { 'Content-Type': 'application/json' } : {}) } });
    let body;
    try { body = await response.json(); } catch { throw new Error('The server did not return a readable result. Your inputs are kept.'); }
    if (!response.ok) {
      const error = new Error(body.error?.message || `The server returned HTTP ${response.status}.`);
      error.code = body.error?.code; error.status = response.status; error.confirmedResponse = true;
      throw error;
    }
    return body;
  } finally { clearTimeout(timeout); }
}
async function refreshStatus() {
  try {
    const status = await api('/api/status'); state.service = status;
    const ready = canRun();
    $('service-state').className = 'service-state ' + (ready ? 'ready' : 'error');
    const budget = Number(status.budget?.remainingCredits);
    $('service-state').querySelector('span:last-child').textContent = ready ? `${status.externalMode === 'live' ? 'Live connection' : 'Test connection'} · ${budget.toLocaleString()} credits in allowance` : status.cashOverageEnabled !== false ? 'Free-only usage guard required' : status.configured ? 'Credit allowance exhausted' : 'Server connection not configured';
    $('service-state').title = 'The allowance is this server’s configured build budget, not the full account balance.';
  } catch {
    state.service = null; $('service-state').className = 'service-state error';
    $('service-state').querySelector('span:last-child').textContent = 'Service unavailable';
  }
  updateButtons();
}
function setMemo(text, source) {
  state.memo = text;
  if (source !== 'initial') $('initial-summary').value = text;
  if (source !== 'review') $('review-summary').value = text;
  if (memoIsStale()) $('verification-results').innerHTML = '<p class="unavailable-message">Your note has changed. Verify this version to see its source support.</p>';
  else if (state.result) renderGrounding();
  updateButtons();
}
function fillInput(input, synthetic = false) {
  state.inputMeta = {rfq: {id: input.rfq?.id, title: input.rfq?.title}, quotes: arr(input.quotes).map(({id, title}) => ({id, title}))};
  $('rfq-text').value = input.rfq?.text || '';
  arr(input.quotes).slice(0, 2).forEach((quote, i) => { const letter = i ? 'b' : 'a'; $('quote-' + letter + '-text').value = quote.text || ''; $('quote-' + letter + '-name').value = quote.supplier || (i ? 'Supplier B' : 'Supplier A'); });
  $('focus-input').value = input.focus || BASE_FOCUS;
  setMemo(input.draftSummary || '', 'load');
  show('sample-note', synthetic);
  show('form-error', false);
  updateButtons();
}
async function loadExamples() {
  try {
    const data = await api('/api/examples'); state.examples = arr(data.examples);
    $('example-select').innerHTML = '<option value="">Choose an example…</option>' + state.examples.map((example) => `<option value="${escapeHtml(example.id)}">${escapeHtml(example.title)}</option>`).join('');
    if (state.examples.length && !['rfq-text', 'quote-a-text', 'quote-b-text'].some((id) => $(id).value)) {
      $('example-select').value = state.examples[0].id; fillInput(state.examples[0].input, true);
    }
  } catch { $('example-select').innerHTML = '<option value="">Examples unavailable — paste your own terms</option>'; }
}
function validate(input) {
  const fields = [{ text: input.rfq.text, id: 'rfq-text', label: 'Buyer’s RFQ' }, ...input.quotes.map((q, i) => ({ text: q.text, id: `quote-${i ? 'b' : 'a'}-text`, label: `Supplier ${i ? 'B' : 'A'} quotation` }))];
  for (const field of fields) {
    if (!field.text.trim() || cpLength(field.text) > 6000) {
      if (field.id === 'quote-b-text') selectTab('quote', 'b'); else if (field.id === 'quote-a-text') selectTab('quote', 'a');
      $(field.id).focus(); throw new Error(`${field.label} must contain between 1 and 6,000 characters.`);
    }
  }
  if (fields.reduce((sum, f) => sum + cpLength(f.text), 0) > 12000) throw new Error('The RFQ and both quotations must total at most 12,000 characters. Shorten the supplied text before analyzing.');
  if (!input.focus.trim() || cpLength(input.focus) > 1000) { $('focus-input').focus(); throw new Error('Add a question of up to 1,000 characters.'); }
  if (cpLength(input.draftSummary) > 2000) throw new Error('The buyer note must contain at most 2,000 characters.');
}
function toast(message) { clearTimeout(state.toastTimer); setText('toast', message); show('toast'); state.toastTimer = setTimeout(() => show('toast', false), 4000); }
function setBusy(busy) {
  state.busy = busy; $('output-panel').setAttribute('aria-busy', String(busy));
  show('run-progress', busy); $('analyze-button').querySelector('span').textContent = busy ? 'Analysis in progress…' : 'Build clarification brief'; updateButtons();
}
function renderProgress(job, kind) {
  const titles = { queued: 'Waiting for the analysis worker', compare: 'Comparing the quoted terms', fill: 'Reading each quotation’s terms', rerank: 'Finding sources for your question', grounding: 'Checking the buyer note', complete: 'Analysis complete', failed: 'Analysis stopped' };
  setText('progress-title', titles[job.stage] || 'Analysis is running');
  const completed = arr(job.progress); if (state.job) state.job.progress = completed; const endpoints = new Set(completed.map((call) => call.endpoint));
  setText('progress-detail', completed.length ? `${completed.length} API request${completed.length === 1 ? '' : 's'} completed. ${kind === 'verify' ? 'The earlier comparison is reused.' : 'Keep this page open; no additional analysis is started while polling.'}` : 'Your original inputs are kept while the server works.');
  const expected = kind === 'verify' ? 1 : (state.job?.input?.draftSummary?.trim() ? 5 : 4);
  const done = kind === 'verify' ? (endpoints.has('grounding') ? 1 : 0) : completed.filter((call) => ['compare', 'fill', 'rerank', 'grounding'].includes(call.endpoint)).length;
  $('progress-fill').style.width = `${Math.max(4, Math.min(96, done / expected * 100))}%`;
  document.querySelectorAll('[data-stage]').forEach((element) => { const name = element.dataset.stage; element.classList.toggle('active', name === job.stage); element.classList.toggle('done', name === 'fill' ? completed.filter((call) => call.endpoint === 'fill').length >= 2 : endpoints.has(name)); });
}
function showRunError(error, unconfirmed = false) {
  const title = unconfirmed ? 'Run status not confirmed' : 'Analysis did not complete';
  const message = unconfirmed ? `The connection was interrupted before the server confirmed the final run status. Your inputs are kept.${state.job?.id ? ' Existing job: ' + state.job.id + '.' : ''} Check the server request history before starting a new analysis; no analysis request has been retried automatically.` : error.message || 'No completed analysis was returned.';
  $('run-error').innerHTML = `<strong>${escapeHtml(title)}</strong>${escapeHtml(message)}${error.code ? `<small class="error-code"> (${escapeHtml(error.code)})</small>` : ''}${arr(state.job?.progress).length ? `<p>${state.job.progress.length} completed API call${state.job.progress.length === 1 ? '' : 's'}: ${state.job.progress.map((call) => escapeHtml(human(call.endpoint))).join(', ')}. Partial work is not a completed analysis.</p>` : ''}`;
  show('run-error'); setText('run-label', 'NOT COMPLETED'); $('run-label').classList.remove('live');
}
async function pollJob(jobId, pollUrl, kind) {
  let failures = 0;
  const deadline = Date.now() + 7 * 60 * 1000;
  while (Date.now() < deadline) {
    let job;
    try { job = await api(pollUrl); failures = 0; } catch (error) {
      if ((error.confirmedResponse && error.status < 500 && error.status !== 429) || ++failures > 3) throw error;
      setText('progress-title', 'Reconnecting to the existing run'); setText('progress-detail', 'Only its status is checked; no new analysis or model request is sent.');
      await new Promise((resolve) => setTimeout(resolve, 1000 * failures)); continue;
    }
    renderProgress(job, kind);
    if (job.status === 'succeeded') { if (!job.result?.analysisId || !job.result?.input) throw new Error('The completed run is missing its analysis or original input.'); return job.result; }
    if (job.status === 'failed') { const error = new Error(job.error?.message || 'The API run failed. No success result was produced.'); error.code = job.error?.code; error.confirmedJobFailure = true; throw error; }
    if (!['queued', 'running'].includes(job.status)) throw new Error('The server returned an unknown job status.');
    await new Promise((resolve) => setTimeout(resolve, 800));
  }
  throw new Error(`The existing run ${jobId} has not completed within seven minutes. Its API work may still be running. No new analysis was started.`);
}
async function startRun(kind = 'analyze') {
  if (state.busy || !canRun() || state.unresolvedRequest) return;
  let input;
  try {
    input = inputValue(); validate(input);
    if (kind === 'verify' && (inputIsStale() || !state.result)) throw new Error('Analyze the current source inputs before verifying a note.');
    if (kind === 'verify' && !state.memo.trim()) throw new Error('Write a buyer note before verifying it.');
  } catch (error) { setText('form-error', error.message); show('form-error'); return; }
  show('form-error', false); show('run-error', false); setBusy(true); setText('run-label', kind === 'verify' ? 'CHECKING NOTE' : 'ANALYZING');
  state.job = { input, kind }; renderProgress({ stage: 'queued', progress: [] }, kind);
  if (kind === 'analyze') { show('results', false); show('empty-state', false); }
  let ack;
  try {
    const payload = kind === 'verify' ? { analysisId: state.result.analysisId, expectedRevision: state.result.revision, draftSummary: state.memo } : input;
    ack = await api(kind === 'verify' ? '/api/verify' : '/api/analyze', { method: 'POST', body: JSON.stringify(payload) });
    if (!ack.jobId || typeof ack.pollUrl !== 'string' || !ack.pollUrl.startsWith('/api/jobs/')) throw new Error('The server did not return a trackable analysis job.');
    state.job = { ...state.job, id: ack.jobId, pollUrl: ack.pollUrl };
    const result = await pollJob(ack.jobId, ack.pollUrl, kind);
    state.result = result;
    // Do not overwrite a note the user edited while the run was in flight.
    renderResult();
    await refreshStatus();
    if (kind === 'analyze' && matchMedia('(max-width: 800px)').matches) $('output-panel').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (error) {
    const unconfirmed = !ack && !error.confirmedResponse;
    const trackingUncertain = !!ack && !error.confirmedJobFailure;
    if (unconfirmed || trackingUncertain) state.unresolvedRequest = true;
    showRunError(error, unconfirmed || trackingUncertain);
    if (kind === 'analyze') { state.result = null; show('results', false); }
    await refreshStatus();
  } finally { setBusy(false); }
}

function documentFor(id) { return arr(state.result?.documents).find((doc) => doc.id === id); }
function sourceName(id) { const doc = documentFor(id); return doc?.role === 'rfq' ? 'Buyer RFQ' : doc?.supplier || doc?.title || id || 'Source unavailable'; }
function evidenceButton(span, label) {
  if (!span?.documentId) return '';
  const key = `ref-${state.evidence.size}`; state.evidence.set(key, span);
  return `<button type="button" class="evidence-link" data-evidence="${key}">${escapeHtml(label || sourceName(span.documentId))}</button>`;
}
function sourceLink(id, label) { return evidenceButton({ documentId: id, quote: null, start: null, end: null, integrity: 'missing' }, label || 'Read original source'); }
function questionRationale(question) {
  const supplierSpan = arr(question.sources).some((span) => documentFor(span.documentId)?.role === 'quote' && exactSourceSpan(span));
  if (question.origin === 'fill') return supplierSpan ? 'From a separate reading of this quotation. The supplier has not confirmed an answer; exact source passages are linked below.' : 'The separate source read did not locate an exact supplier passage. Check the full quotation and ask for confirmation; this does not prove an omission.';
  if (question.status === 'needs_confirmation') return supplierSpan ? 'Please confirm these quoted terms with the supplier. A source quotation is not an unconditional commercial commitment.' : 'This question cites your requirement. It does not assert that the supplier omitted or rejected it.';
  return question.status === 'ready' ? '' : 'The source evidence is incomplete. Review this question before use.';
}
function renderQuestions() {
  const questions = arr(state.result.clarifications);
  setText('question-count', String(questions.length));
  $('clarifications').innerHTML = questions.length ? questions.map((q, i) => `<article class="question-card" data-question-id="${escapeHtml(q.id)}"><div class="question-header"><span class="supplier-label">${String(i + 1).padStart(2, '0')} / ${escapeHtml(q.supplier || sourceName(q.supplierId))}</span><span class="status-pill ${q.status === 'ready' ? 'supported' : 'unknown'}">${q.status === 'ready' ? 'Source-backed question' : q.status === 'needs_confirmation' ? 'Supplier confirmation needed' : 'Review source'}</span></div><p class="question-text">${escapeHtml(q.text)}</p>${questionRationale(q) ? `<p class="question-rationale">${escapeHtml(questionRationale(q))}</p>` : ''}${arr(q.sources).length ? `<div class="evidence-links">${q.sources.map((span) => evidenceButton(span)).join('')}</div>` : '<p class="no-evidence">No source quotation returned. Review the original documents.</p>'}</article>`).join('') : '<p class="unavailable-message">No source-backed clarification questions were produced. This does not confirm that every requirement is met. Review the terms and your buyer note.</p>';
  setText('result-intro', questions.length ? `${questions.length} clarification question${questions.length === 1 ? '' : 's'} for supplier confirmation. Review their source passages before use; these are questions, not confirmed commitments.` : 'The analysis did not produce a clarification question. Missing findings are not proof that the quotes are complete.');
}
function exactSourceSpan(span) {
  const doc = documentFor(span?.documentId);
  if (!doc || span.integrity !== 'exact' || !Number.isInteger(span.start) || !Number.isInteger(span.end)) return false;
  const chars = Array.from(doc.text || '');
  return span.start >= 0 && span.end > span.start && span.end <= chars.length && chars.slice(span.start, span.end).join('') === span.quote;
}
function renderTermReviews() {
  const reviews = arr(state.result.termReviews);
  const labels = {freight_clause: 'Freight / delivered-price basis', receipt_clause: 'Destination receipt', payment_clause: 'Payment conditions', production_clause: 'Production / dispatch', version_clause: 'Revision scope'};
  const signals = {included_and_priced: 'Read suggests a priced freight basis — confirm scope', excluded_or_unpriced: 'Read flags excluded or unpriced freight', not_established: 'Not established by the source read', firm_receipt_date: 'Read identifies a receipt date — confirm scope', conditional_receipt: 'Conditional receipt — conditions still apply', not_committed: 'Receipt not committed in the located wording'};
  $('term-reviews').innerHTML = reviews.length ? '<div class="section-caption"><span>QUOTE TERMS READ SEPARATELY</span></div><p class="view-intro">Machine reading signals guide review. They do not certify completeness or supplier commitments. Negations and conditions remain in the original passages.</p>' + reviews.map((review, index) => `<details class="term-review" ${index === 0 ? 'open' : ''} data-term-document="${escapeHtml(review.documentId)}"><summary>${escapeHtml(review.supplier || sourceName(review.documentId))}<span>View source terms</span></summary>${Object.entries(labels).map(([field, label]) => {
    const exact = arr(review.clauses?.[field]).filter(exactSourceSpan);
    const signal = field === 'freight_clause' ? review.signals?.freight_status : field === 'receipt_clause' ? review.signals?.receipt_status : null;
    const flag = field === 'payment_clause' && review.signals?.unmet_payment_condition === true ? 'Payment / clearance condition flagged — confirm whether fulfilled' : field === 'version_clause' && review.signals?.version_attention === true ? 'Revision scope flagged for review' : null;
    return `<section class="term-clause"><h3>${escapeHtml(label)}</h3>${signal || flag ? `<p class="term-signal">${escapeHtml(exact.length ? signals[signal] || flag || human(signal) : 'Not established from exact source evidence')}</p>` : ''}${exact.length ? exact.map((span) => `<blockquote>${escapeHtml(span.quote)}</blockquote>${evidenceButton(span, 'Locate original passage')}`).join('') : `<p class="field-help">No exact passage located by this read. This does not prove the quotation omitted the term.</p>${sourceLink(review.documentId, 'Check complete quotation')}`}</section>`;
  }).join('')}</details>`).join('') : '';
}

function quoteSide(span, fallbackId) {
  const docId = span?.documentId || fallbackId;
  const quote = typeof span?.quote === 'string' && span.quote ? span.quote : null;
  return `<div class="quote-side"><span class="supplier-label">${escapeHtml(sourceName(docId))}</span>${quote ? `<blockquote>${escapeHtml(quote)}</blockquote>` : '<p class="field-help">No quotation returned.</p>'}${span?.documentId ? evidenceButton(span, 'View in source') : sourceLink(docId)}</div>`;
}
function renderComparisons() {
  const findings = arr(state.result.findings);
  const relationLabels = { conflicting: 'Different proposed terms', same: 'Same compared terms', overlapping: 'Related terms', unrelated: 'Different scope' };
  const pairs = arr(state.result.comparisons);
  const pairSummary = `<div class="pair-summary">${pairs.map((p) => `<p><span>${escapeHtml(sourceName(p.a))} ↔ ${escapeHtml(sourceName(p.b))}</span><b>${escapeHtml(relationLabels[p.relation] || human(p.relation))}</b></p>`).join('')}</div>`;
  $('comparisons').innerHTML = pairSummary + (findings.length ? findings.map((f) => `<article class="comparison-card"><div class="comparison-top"><h3>${escapeHtml(f.label || 'Terms to clarify')}</h3><span class="status-pill ${f.sourceIntegrity === 'exact' ? '' : 'unknown'}">${f.sourceIntegrity === 'exact' ? human(f.kind) : 'Source needs review'}</span></div><div class="quote-pair">${quoteSide(f.a)}${quoteSide(f.b)}</div>${f.sourceIntegrity === 'one_sided' ? '<p class="comparison-note">Only the RFQ passage is located. Ask the supplier to confirm the requirement; no omission is asserted.</p>' : f.sourceIntegrity !== 'exact' ? '<p class="comparison-note">One or both source spans could not be verified. No source-backed conclusion is inferred from this finding.</p>' : ''}</article>`).join('') : '<p class="unavailable-message">No specific clause differences were returned. This is not an assurance that all commercial terms match.</p>');
}
function renderRetrieval() {
  const data = state.result.rerank;
  const labels = { use: 'Passage relevant to your question', expand: 'Read the broader source', skip: 'Not selected for focus' };
  const cards = arr(data?.results).map((row, i) => {
    const exact = exactSourceSpan(row.passage);
    return `<article class="passage-card ${row.action === 'skip' ? 'skipped' : ''}" data-focus-passage="${escapeHtml(row.passageId || row.documentId)}"><span class="passage-rank">${String(i + 1).padStart(2, '0')}</span><div class="passage-content"><div class="passage-meta"><strong>${escapeHtml(sourceName(row.documentId))}${row.parts ? ` · section ${Number(row.part)} of ${Number(row.parts)}` : ''}</strong><span>${escapeHtml(labels[row.action] || human(row.action))}</span></div>${exact ? `<blockquote class="focus-excerpt">${escapeHtml(row.passage.quote)}</blockquote>` : ''}${row.action === 'expand' ? '<p class="field-help">This section may not contain the answer. Read the complete source and neighboring conditions.</p>' : ''}${row.reason ? `<p class="field-help">Reason: ${escapeHtml(human(row.reason))}</p>` : ''}${exact ? evidenceButton(row.passage, 'Locate this passage in original') : ''} ${sourceLink(row.documentId, 'Read complete source')}</div></article>`;
  }).join('');
  const fallback = data?.status === 'unavailable' ? `<p class="unavailable-message">${escapeHtml(data.message || 'Focus is unavailable. Read the complete sources.')}</p>` : '<p class="unavailable-message">No source-focus results returned.</p>';
  $('retrieval').innerHTML = `<p class="field-help">Focus: ${escapeHtml(data?.query || state.result.input.focus)}. Relevant wording may be qualified elsewhere; every original source stays available.</p>` + (cards || fallback) + `<div class="focus-all-sources">${arr(state.result.documents).map(doc => sourceLink(doc.id, `Read ${sourceName(doc.id)}`)).join(' ')}</div>`;
}
function renderGrounding() {
  if (!state.result || memoIsStale()) return;
  const grounding = state.result.grounding || {};
  const claims = arr(grounding.claims);
  let html = grounding.status === 'not_requested' ? `<p class="unavailable-message">${escapeHtml(grounding.message || 'No buyer note has been checked. Write a note above to verify its claims against these sources.')}</p>` : `<div class="grounding-overview ${grounding.status === 'supported' ? 'supported' : ''}"><strong>${grounding.status === 'supported' ? 'The returned claims have source support.' : 'Some returned claims still need review.'}</strong><p>${grounding.status === 'supported' ? 'Only the returned, supported claims and their evidence can enter the brief. The API may omit claims; your full original note is not certified or exported.' : 'Only individual supported claims with exact evidence may enter the brief. Unreturned or unsupported statements are withheld; the original note remains here for your review.'}</p></div>`;
  html += claims.map((claim) => `<article class="claim-card" data-claim-id="${escapeHtml(claim.id)}"><div class="claim-top"><p>${escapeHtml(claim.text)}</p><span class="status-pill ${claim.ready ? 'supported' : 'unknown'}">${claim.ready ? 'Supported with source' : 'Needs review'}</span></div><p class="claim-detail">Model verdict: ${escapeHtml(human(claim.verdict))}.${!claim.counted ? ' Not counted as an assessable claim.' : ''}${claim.evidence?.integrity === 'exact' ? '' : ' No exact source span is available for this claim.'}</p>${claim.evidence?.documentId ? `<div class="evidence-links">${evidenceButton(claim.evidence, claim.ready ? 'Read supporting text' : 'Read returned evidence')}</div>` : ''}</article>`).join('');
  $('verification-results').innerHTML = html;
}
function renderResult() {
  state.evidence.clear(); show('empty-state', false); show('results'); show('run-error', false);
  const calls = arr(state.result.usage?.calls);
  const isLive = calls.some((c) => c.transport === 'live');
  setText('run-label', state.service?.externalMode === 'test' ? 'TEST RESPONSE' : state.service?.externalMode === 'live' ? (isLive ? 'LIVE ANALYSIS' : 'SAVED RESULT') : 'ANALYSIS RESULT');
  $('run-label').classList.toggle('live', state.service?.externalMode === 'live');
  renderQuestions(); renderTermReviews(); renderComparisons(); renderRetrieval(); renderGrounding();
  const credits = Number(state.result.usage?.newCredits) || 0;
  $('usage-strip').innerHTML = `<span>${credits} new credits used</span><span>${calls.length} endpoint request${calls.length === 1 ? '' : 's'}</span><span>${calls.some((c) => ['cache', 'replay'].includes(c.transport)) ? 'Includes saved/replayed work' : 'No automatic retry'}</span>`;
  const details = [['Analysis', state.result.analysisId], ['Created', state.result.createdAt ? new Date(state.result.createdAt).toLocaleString() : 'Unavailable'], ['Source revision', state.result.revision], ['Memo status', human(state.result.grounding?.status)], ['New credits', String(credits)], ...calls.map((c) => [human(c.endpoint), `${human(c.transport)} · ${Number(c.elapsedMs) || 0} ms`])];
  $('analysis-details').innerHTML = '<dl>' + details.map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(value)}</dd>`).join('') + '</dl>' + arr(state.result.limitations).map((line) => `<p class="field-help">${escapeHtml(line)}</p>`).join('');
  updateButtons();
}
function showEvidence(span) {
  const doc = documentFor(span.documentId);
  if (!doc) { toast('The returned source identifier is not part of this analysis.'); return; }
  setText('evidence-title', sourceName(doc.id));
  const chars = Array.from(doc.text || '');
  const validRange = Number.isInteger(span.start) && Number.isInteger(span.end) && span.start >= 0 && span.end >= span.start && span.end <= chars.length;
  const exact = validRange && typeof span.quote === 'string' && chars.slice(span.start, span.end).join('') === span.quote;
  setText('evidence-status', exact ? 'Exact quotation in the analyzed source. Highlight uses Unicode code-point positions.' : span.quote ? 'Returned quotation is shown for review. Its exact position is unavailable or does not match.' : 'Complete original source from this analysis; no passage-level position was returned.');
  setText('evidence-quote', span.quote || '');
  $('evidence-source').innerHTML = exact ? escapeHtml(chars.slice(0, span.start).join('')) + '<mark>' + escapeHtml(chars.slice(span.start, span.end).join('')) + '</mark>' + escapeHtml(chars.slice(span.end).join('')) : escapeHtml(doc.text);
  $('evidence-dialog').showModal();
  requestAnimationFrame(() => $('evidence-source').querySelector('mark')?.scrollIntoView({ block: 'center' }));
}
async function exportBrief(mode) {
  if (!state.result || state.busy || inputIsStale() || memoIsStale()) return;
  const button = $(mode === 'copy' ? 'copy-brief' : 'download-brief'); button.disabled = true;
  try {
    const data = await api('/api/export', { method: 'POST', body: JSON.stringify({ analysisId: state.result.analysisId, expectedRevision: state.result.revision, input: inputValue() }) });
    if (typeof data.text !== 'string') throw new Error('The server did not return a clarification brief.');
    if (mode === 'download') {
      const url = URL.createObjectURL(new Blob([data.text], { type: 'text/plain;charset=utf-8' })); const link = document.createElement('a');
      link.href = url; link.download = String(data.filename || 'supplier-clarification-brief.txt').replace(/[\\/]/g, '-'); link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      toast(data.includedMemo ? 'Brief downloaded with individually supported claims.' : 'Brief downloaded. No buyer-note claims included.');
    } else {
      try { await navigator.clipboard.writeText(data.text); } catch {
        const box = document.createElement('textarea'); box.value = data.text; box.style.position = 'fixed'; box.style.opacity = '0'; document.body.append(box); box.select(); const copied = document.execCommand('copy'); box.remove(); if (!copied) throw new Error('Clipboard access is unavailable. Use Download brief instead.');
      }
      toast(data.includedMemo ? 'Brief copied with individually supported claims.' : 'Brief copied. No buyer-note claims included.');
    }
  } catch (error) { if (error.status === 409) { setText('form-error', 'The server rejected this stale brief. Analyze the current inputs or verify the changed note first.'); show('form-error'); } else toast(error.message); }
  finally { updateButtons(); }
}

$('analysis-form').addEventListener('submit', (event) => { event.preventDefault(); startRun(); });
$('verify-note').addEventListener('click', () => startRun('verify'));
$('reanalyze-button').addEventListener('click', () => startRun(inputIsStale() ? 'analyze' : 'verify'));
$('copy-brief').addEventListener('click', () => exportBrief('copy'));
$('download-brief').addEventListener('click', () => exportBrief('download'));
$('initial-summary').addEventListener('input', (event) => setMemo(event.target.value, 'initial'));
$('review-summary').addEventListener('input', (event) => setMemo(event.target.value, 'review'));
['rfq-text', 'quote-a-text', 'quote-b-text', 'quote-a-name', 'quote-b-name', 'focus-input'].forEach((id) => $(id).addEventListener('input', updateButtons));
$('example-select').addEventListener('change', () => { const selected = state.examples.find((e) => e.id === $('example-select').value); if (selected) fillInput(selected.input, true); });
$('clear-inputs').addEventListener('click', () => { fillInput({ rfq: { text: '' }, quotes: [{ text: '', supplier: 'Supplier A' }, { text: '', supplier: 'Supplier B' }], focus: BASE_FOCUS }); $('example-select').value = ''; selectTab('quote', 'a'); $('rfq-text').focus(); });
document.querySelectorAll('[data-quote-tab]').forEach((button) => { button.addEventListener('click', () => selectTab('quote', button.dataset.quoteTab)); button.addEventListener('keydown', (event) => tabKeyboard(event, 'quote')); });
document.querySelectorAll('[data-output-tab]').forEach((button) => { button.addEventListener('click', () => selectTab('output', button.dataset.outputTab)); button.addEventListener('keydown', (event) => tabKeyboard(event, 'output')); });
document.addEventListener('click', (event) => { const button = event.target.closest('[data-evidence]'); if (button) { const span = state.evidence.get(button.dataset.evidence); if (span) showEvidence(span); } });
$('close-evidence').addEventListener('click', () => $('evidence-dialog').close());
$('how-button').addEventListener('click', () => $('help-dialog').showModal());
$('close-help').addEventListener('click', () => $('help-dialog').close());
[$('evidence-dialog'), $('help-dialog')].forEach((dialog) => dialog.addEventListener('click', (event) => { if (event.target === dialog) { const r = dialog.getBoundingClientRect(); if (event.clientX < r.left || event.clientX > r.right || event.clientY < r.top || event.clientY > r.bottom) dialog.close(); } }));
updateButtons();
Promise.allSettled([refreshStatus(), loadExamples()]);
