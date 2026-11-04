"""Render retained actual Fill responses through TEST-only API interception. No credits.
Run from app/: python3 web/tests/fill_ui_smoke.py
"""
import copy
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
record_path = Path(__file__).parent / 'fixtures/retained-fill-response.json'
record = json.loads(record_path.read_text())
result = record['result']
out=Path(__file__).parent/'artifacts';out.mkdir(exist_ok=True)
checks=[];errors=[];posts=[];polls=[0]
def handler(route):
    path=route.request.url.split('/api/',1)[1]
    if route.request.method=='POST':posts.append(path)
    if path=='status':body={'configured':True,'externalMode':'test','cashOverageEnabled':False,'budget':{'remainingCredits':1000}}
    elif path=='examples':body={'synthetic':True,'examples':[{'id':'retained-fill','title':'Retained actual Fill response (TEST playback)','input':result['input']}]}
    elif path=='analyze':body={'jobId':'test-fill','status':'queued','pollUrl':'/api/jobs/test-fill'}
    elif path=='jobs/test-fill':
        polls[0]+=1
        body={'status':'running','stage':'fill','progress':record['progress'][:2],'result':None,'error':None} if polls[0]==1 else record
    else:route.fulfill(status=404,json={'error':{'message':'No POST export in this read-only rendering check'}});return
    route.fulfill(status=200,json=body)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
    ctx=browser.new_context(viewport={'width':1440,'height':1000},locale='en-US');ctx.route('**/api/**',handler)
    page=ctx.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
    page.goto('http://127.0.0.1:8190');expect(page.locator('#analyze-button')).to_be_enabled();page.locator('#analyze-button').click()
    expect(page.locator('#progress-title')).to_contain_text('Reading each quotation');expect(page.locator('[data-stage="fill"]')).not_to_have_class('done');checks.append('Fill stage shown; one completed read does not mark both reads done')
    expect(page.locator('#results')).to_be_visible(timeout=10000);expect(page.locator('#result-intro')).to_contain_text('5 clarification questions');expect(page.locator('#clarifications .question-card')).to_have_count(5);checks.append('Five actual empty-memo questions shown without a false zero-result message')
    expect(page.locator('#clarifications')).to_contain_text('Freight to Durban is excluded and not yet priced.');expect(page.locator('#clarifications')).to_contain_text('only if the 40% deposit clears');checks.append('Negative freight wording and only-if receipt conditions remain visible')
    assert 'cites your requirement' not in page.locator('#clarifications').inner_text();checks.append('Supplier-origin questions correctly attribute quotation reading')
    page.screenshot(path=str(out/'fill-questions.png'),full_page=True)
    page.locator('#differences-tab').click();expect(page.locator('#term-reviews .term-review')).to_have_count(2);expect(page.locator('[data-term-document="quote-a"]')).to_contain_text('Receipt not committed');expect(page.locator('[data-term-document="quote-a"]')).to_contain_text('does not prove the quotation omitted');checks.append('Separate terms show uncommitted receipt and qualify unlocated passages')
    expect(page.locator('#term-reviews')).not_to_contain_text('98%');expect(page.locator('#comparisons')).to_contain_text('Related terms');checks.append('No confidence-as-guarantee; Compare overlapping remains related terms')
    page.locator('[data-term-document="quote-b"] summary').click();expect(page.locator('[data-term-document="quote-b"]')).to_contain_text('Conditional receipt');page.locator('[data-term-document="quote-b"] .evidence-link').first.click();expect(page.locator('#evidence-status')).to_contain_text('Exact quotation');checks.append('Conditional quote source opens with independently checked exact span')
    page.locator('#close-evidence').click();page.screenshot(path=str(out/'fill-terms.png'),full_page=True)
    assert not errors;checks.append('No JS errors; intercepted requests only');assert posts==['analyze']
    browser.close()
report={'passed':True,'scope':'Retained real API result rendered with intercepted TEST transport; no new Clocked calls','checks':checks,'browserErrors':errors,'record':str(record_path)}
(out/'fill-report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
