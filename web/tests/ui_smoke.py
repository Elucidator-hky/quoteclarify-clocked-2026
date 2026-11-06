"""Frontend-only checks: intercept every /api call; never consume Clocked credits.
Run from app/: python3 web/tests/ui_smoke.py [--url http://127.0.0.1:8190]
Generated screenshots and report are written beside this script in artifacts/.
"""
import argparse
import copy
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

parser = argparse.ArgumentParser()
parser.add_argument('--url', default='http://127.0.0.1:8190')
args = parser.parse_args()
out = Path(__file__).parent / 'artifacts'
out.mkdir(exist_ok=True)
source = '🧪 SYNTHETIC supplier quote. Freight USD 90. Arrival date unknown.'
input_data = {'rfq': {'id':'rfq','title':'Buyer RFQ','text':'SYNTHETIC RFQ: delivered price and arrival date required.'}, 'quotes':[{'id':'quote-a','title':'Quotation A','supplier':'Supplier A','text':source}, {'id':'quote-b','title':'Quotation B','supplier':'Supplier B','text':'SYNTHETIC offer B: Freight not quoted.'}], 'focus':'What delivery terms must be clarified?', 'draftSummary':''}
quote = 'Freight USD 90.'
span = {'documentId':'quote-a','quote':quote,'start':source.index(quote),'end':source.index(quote)+len(quote),'integrity':'exact'}
rfq_span = {'documentId':'rfq','quote':input_data['rfq']['text'],'start':0,'end':len(input_data['rfq']['text']),'integrity':'exact'}
result = {'analysisId':'33333333-3333-4333-8333-333333333333','revision':'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa','inputDigest':'cccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccccc','createdAt':'2026-11-04T03:00:00Z','input':input_data,'documents':[dict(input_data['rfq'],role='rfq',supplier=None), *[dict(q,role='quote') for q in input_data['quotes']]],'comparisons':[{'id':'p1','a':'rfq','b':'quote-a','relation':'conflicting','findingIds':['f1']}], 'findings':[{'id':'f1','pairId':'p1','kind':'value','label':'Delivery terms','a':rfq_span,'b':span,'sourceIntegrity':'exact'}], 'rerank':{'status':'completed','query':input_data['focus'],'results':[{'documentId':'quote-a','action':'use','reason':None},{'documentId':'quote-b','action':'skip','reason':'different_case'}]},'grounding':{'status':'not_requested','text':'','claims':[]},'clarifications':[{'id':'q1','supplierId':'quote-a','supplier':'Supplier A','findingId':'f1','text':'Please confirm the arrival date. <img src=x onerror="window.injected=true">','sources':[span],'status':'ready'},{'id':'q2','supplierId':'quote-b','supplier':'Supplier B','findingId':'f2','text':'Can you confirm delivered pricing against the RFQ?','sources':[rfq_span],'status':'needs_confirmation'}], 'usage':{'newCredits':0,'calls':[{'endpoint':'compare','transport':'cache','credits':0,'elapsedMs':3},{'endpoint':'rerank','transport':'cache','credits':0,'elapsedMs':2}]},'limitations':['SYNTHETIC FRONTEND TEST RESPONSE. Not a live API result.']}
posts=[]; jobs={}; checks=[]; errors=[]; mode={'fail':False,'overage':False}
def check(name, condition=True):
    assert condition, name
    checks.append(name)
def handler(route):
    request=route.request; path=request.url.split('/api/',1)[1]
    status=200
    if request.method=='POST': posts.append({'path':path,'payload':request.post_data_json})
    if path=='status': body={'configured':True,'budget':{'limitCredits':1000,'usedCredits':0,'remainingCredits':1000},'externalMode':'test','cashOverageEnabled':mode['overage']}
    elif path=='examples': body={'synthetic':True,'examples':[{'id':'synthetic-test','title':'Synthetic frontend check','input':input_data}]}
    elif path=='analyze':
        current=copy.deepcopy(result); current['input']=request.post_data_json
        jobs['11111111-1111-4111-8111-111111111111']={'result':current,'polls':0,'failed':mode['fail']}
        status=202; body={'jobId':'11111111-1111-4111-8111-111111111111','status':'queued','pollUrl':'/api/jobs/11111111-1111-4111-8111-111111111111'}
    elif path=='verify':
        payload=request.post_data_json; current=copy.deepcopy(result)
        current['analysisId']='44444444-4444-4444-8444-444444444444';current['revision']='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb';current['input']['draftSummary']=payload['draftSummary']
        current['grounding']={'status':'needs_review','text':payload['draftSummary'],'reviewScope':'returned_claims_only','originalDraftIncluded':False,'claims':[{'id':'c1','text':'Freight is USD 90.','verdict':'supported','supported':0.99,'counted':True,'ready':True,'evidence':span},{'id':'c2','text':'Arrival is confirmed.','verdict':'not_stated','supported':0,'counted':True,'ready':False,'evidence':None}]}
        jobs['22222222-2222-4222-8222-222222222222']={'result':current,'polls':0,'failed':False}
        status=202;body={'jobId':'22222222-2222-4222-8222-222222222222','status':'queued','pollUrl':'/api/jobs/22222222-2222-4222-8222-222222222222'}
    elif path.startswith('jobs/'):
        job=jobs[path.split('/')[-1]];job['polls']+=1
        if path=='jobs/11111111-1111-4111-8111-111111111111' and job['polls']==1 and not job['failed']:
            route.fulfill(status=503,content_type='application/json',body=json.dumps({'error':{'code':'temporarily_unavailable','message':'SYNTHETIC transient poll failure'}})); return
        if job['polls']<=2: body={'jobId':path.split('/')[-1],'status':'running','stage':'compare','progress':[],'error':None,'result':None}
        elif job['failed']: body={'jobId':path.split('/')[-1],'status':'failed','stage':'failed','progress':[{'endpoint':'compare','transport':'cache','credits':0}],'error':{'code':'upstream_unavailable','message':'Synthetic upstream failure','retryable':False},'result':None}
        else: body={'jobId':path.split('/')[-1],'status':'succeeded','stage':'complete','progress':job['result']['usage']['calls'],'error':None,'result':job['result']}
    elif path=='export': body={'analysisId':'test','revision':'test','text':'SYNTHETIC TEST BRIEF\nSupplier A: Please confirm arrival.\nSupported claim: Freight is USD 90.\n','filename':'synthetic-test-brief.txt','contentType':'text/plain;charset=utf-8','includedMemo':True,'includedClaimIds':['c1'],'originalDraftIncluded':False}
    else: status=404;body={'error':{'message':'Unexpected mocked endpoint'}}
    route.fulfill(status=status,content_type='application/json',body=json.dumps(body))

with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
    context=browser.new_context(viewport={'width':1440,'height':1000},locale='en-US',accept_downloads=True)
    context.route('**/api/**',handler)
    page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
    page.goto(args.url);expect(page.locator('#rfq-text')).to_have_value(input_data['rfq']['text']);expect(page.locator('#analyze-button')).to_be_enabled()
    check('Synthetic sample auto-loads without analysis POST',not posts)
    page.locator('#clear-inputs').click();page.locator('#rfq-text').fill('My RFQ');page.locator('#quote-a-text').fill('My quote A');page.locator('#analyze-button').click()
    expect(page.locator('#form-error')).to_contain_text('Supplier B');expect(page.locator('#quote-b-tab')).to_have_attribute('aria-selected','true');expect(page.locator('#quote-b-text')).to_be_focused()
    check('Hidden empty quote switches to visible field without native focus error',not posts)
    page.locator('#example-select').select_option('synthetic-test');page.locator('#analyze-button').click();expect(page.locator('#run-progress')).to_be_visible();expect(page.locator('#results')).to_be_visible(timeout=10000)
    check('Single analysis POST preserves all original sample metadata',posts[0]['payload']==input_data)
    check('Transient poll 503 resumes same job using GET only',jobs['11111111-1111-4111-8111-111111111111']['polls']==3 and len(posts)==1)
    expect(page.locator('#run-label')).to_have_text('TEST RESPONSE');check('Test transport never presented as live')
    check('Untrusted result text escaped',page.locator('#clarifications img').count()==0 and page.evaluate('window.injected !== true'))
    expect(page.locator('[data-question-id="q2"]')).to_contain_text('does not assert');check('Single-sided requirement is a question, not alleged omission')
    page.locator('[data-question-id="q1"] [data-evidence]').click();expect(page.locator('#evidence-source mark')).to_have_text(quote);expect(page.locator('#evidence-status')).to_contain_text('Exact quotation');check('Unicode codepoint highlight remains exact after emoji');page.locator('#close-evidence').click()
    page.locator('#differences-tab').click();expect(page.locator('#comparisons')).to_contain_text('Different proposed terms');expect(page.locator('#retrieval .passage-card')).to_have_count(2);check('All ranked sources remain available including skip')
    page.locator('#verification-tab').click();expect(page.locator('#verification-results')).to_contain_text('No buyer note');page.locator('#review-summary').fill('Freight is USD 90. Arrival is confirmed. Untouched original statement.');expect(page.locator('#download-brief')).to_be_disabled();page.locator('#verify-note').click();expect(page.locator('#verification-results .claim-card')).to_have_count(2,timeout=10000)
    check('Verify uses revision and only a new memo',posts[-1]['path']=='verify' and set(posts[-1]['payload'])=={'analysisId','expectedRevision','draftSummary'})
    expect(page.locator('#verification-results')).to_contain_text('individual supported claims');expect(page.locator('#review-summary')).to_have_value('Freight is USD 90. Arrival is confirmed. Untouched original statement.');check('Full original memo retained; only returned claims assessed')
    page.locator('#questions-tab').click()
    with page.expect_download() as download: page.locator('#download-brief').click()
    download.value.save_as(out/'synthetic-test-brief.txt')
    check('Download uses server export with current revision',posts[-1]['path']=='export' and posts[-1]['payload']['expectedRevision']=='bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb')
    page.screenshot(path=str(out/'desktop-result.png'),full_page=True)
    page.locator('#rfq-text').fill(input_data['rfq']['text']+' EDITED');expect(page.locator('#stale-notice')).to_be_visible();expect(page.locator('#download-brief')).to_be_disabled();expect(page.locator('#verify-note')).to_be_disabled();check('Source edit blocks stale export and memo-only verification')
    page.set_viewport_size({'width':375,'height':900});check('Mobile width has no horizontal page overflow',page.evaluate('document.documentElement.scrollWidth <= innerWidth'))
    page.screenshot(path=str(out/'mobile-result.png'),full_page=True)
    mode['fail']=True;page.locator('#analyze-button').click();expect(page.locator('#run-error')).to_contain_text('Synthetic upstream failure',timeout=10000);expect(page.locator('#results')).to_be_hidden();expect(page.locator('#rfq-text')).to_have_value(input_data['rfq']['text']+' EDITED');expect(page.locator('#run-error')).to_contain_text('1 completed API call');check('Failed job retains edited input and completed-call history without partial success')
    mode['overage']=True;page.reload();expect(page.locator('#analyze-button')).to_be_disabled();expect(page.locator('#service-state')).to_contain_text('Free-only');check('Paid-overage status blocks new analysis')
    check('No browser JS errors',not errors)
    browser.close()
report={'passed':True,'scope':'Frontend-only intercepted TEST responses; no real Clocked requests or credits','checks':checks,'browserErrors':errors,'posts':[{'path':x['path']} for x in posts]}
(out/'report.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
