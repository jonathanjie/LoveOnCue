#!/usr/bin/env python3
"""Requires pip install playwright and playwright install chromium.
Offline --bridge explicitly bypasses HTTP/cookie transport, not production policy.
The normal mode checks /api/config and refuses any non-demo target before acting.
"""
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
import argparse,json,os,sys,tempfile
import httpx

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'src'))
parser=argparse.ArgumentParser(description='Rehearsal-only Chromium smoke test; --bridge does not test browser networking')
parser.add_argument('--bridge',action='store_true',help='Use explicit offline fetch-to-ASGI bridge in restricted environments')
parser.add_argument('--url',default='http://127.0.0.1:8000')
args=parser.parse_args()
from fastapi.testclient import TestClient
from wedding_ops.api import create_app
from wedding_ops.config import Settings
from wedding_ops.db import Database
from wedding_ops.seed import seed_demo,DEMO_TIME
from wedding_ops.clock import DemoClock
tmp=tempfile.TemporaryDirectory()
db=Database('sqlite:///'+tmp.name+'/ui.db');db.create_schema();seed_demo(db)
backend=TestClient(create_app(Settings(mode='demo'),db,DemoClock(DEMO_TIME)),base_url='http://127.0.0.1:8000')
def bridge(source,url,options):
 headers=dict(options.get('headers',{}));headers['Origin']='http://127.0.0.1:8000'
 response=backend.request(options.get('method','GET'),url,content=options.get('body'),headers=headers)
 return {'status':response.status_code,'body':response.text,'headers':dict(response.headers)}

out=root/'artifacts';out.mkdir(exist_ok=True)
with sync_playwright() as p:
 binary=os.getenv('CHROMIUM_PATH')
 browser=p.chromium.launch(**({'executable_path':binary} if binary else {}),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
 page=browser.new_page(viewport={'width':1512,'height':1080},device_scale_factor=1)
 page.route('https://telegram.org/**',lambda route:route.abort())
 errors=[];page.on('pageerror',lambda exc:errors.append(str(exc)))
 if args.bridge:
  page.expose_binding('backendFetch',bridge)
  page.set_content('<html><head></head><body><div id="app"></div><div id="toast" role="status" aria-live="polite"></div></body></html>')
  page.add_style_tag(content=(root/'web/dist/app.css').read_text())
  page.evaluate("""() => {window.fetch=async (url,options={})=>{const r=await window.backendFetch(url,options);return new Response(r.body,{status:r.status,headers:r.headers});};}""")
  page.add_script_tag(content=(root/'web/dist/app.js').read_text(),type='module')
 else:
  config=httpx.get(args.url+'/api/config',timeout=10).json()
  if config.get('demo') is not True:raise RuntimeError('Refusing to run mutation tests against a non-demo site')
  page.goto(args.url,wait_until='networkidle')
 page.get_by_role('button',name='Alex Morgan · coordinator',exact=True).click()
 expect(page.get_by_role('heading',name='Command centre',exact=True)).to_be_visible()
 page.screenshot(path=str(out/'overview-desktop.png'),full_page=True)
 for name in ['Run of show','My tasks','Guest desk','People & teams','Issues','Approvals','Venue & vendors','Knowledge','Audit trail','Setup & imports','Overview']:
  page.get_by_role('navigation').get_by_role('button',name=name,exact=True).click()
  page.wait_for_timeout(120)
 assert not errors,errors
 page.get_by_label('Rehearsal role').select_option('banquet')
 expect(page.get_by_role('heading',name='Your operations brief')).to_be_visible()
 page.get_by_role('button',name='Dinner +12 min',exact=True).click()
 page.get_by_role('button',name='Confirm this interpretation',exact=True).click()
 page.get_by_role('navigation').get_by_role('button',name='Approvals',exact=True).click()
 expect(page.get_by_role('heading',name='Dinner service: +12 minutes')).to_be_visible()
 assert page.get_by_role('button',name='Approve reviewed change',exact=True).count()==0
 page.get_by_label('Rehearsal role').select_option('coordinator')
 expect(page.get_by_role('heading',name='Command centre',exact=True)).to_be_visible()
 page.get_by_role('navigation').get_by_role('button',name='Approvals',exact=True).click()
 expect(page.get_by_role('button',name='Approve reviewed change')).to_be_enabled()
 page.screenshot(path=str(out/'approval-desktop.png'),full_page=True)
 page.on('dialog',lambda dialog:dialog.accept())
 page.get_by_role('button',name='Approve reviewed change',exact=True).click()
 expect(page.get_by_text('Run sheet v2',exact=False)).to_be_visible()
 page.get_by_label('Rehearsal role').select_option('photographer')
 expect(page.get_by_role('heading',name='Your operations brief')).to_be_visible()
 page.get_by_role('button',name="Locate bride's father",exact=True).click()
 page.get_by_role('button',name='Confirm this interpretation',exact=True).click()
 page.get_by_label('Rehearsal role').select_option('registration-a')
 expect(page.get_by_role('heading',name='Your operations brief')).to_be_visible()
 page.get_by_role('button',name='Parents arrived',exact=True).click()
 page.get_by_role('button',name='Confirm this interpretation',exact=True).click()
 page.get_by_role('navigation').get_by_role('button',name='Guest desk',exact=True).click()
 page.get_by_label('Guest name',exact=True).fill('Sarah Tan')
 expect(page.get_by_role('heading',name='Sarah Tan')).to_be_visible()
 expect(page.get_by_text('Table 18 · Cedar Ballroom',exact=True)).to_be_visible()
 assert page.get_by_label('Show dietary service notes').count()==0
 page.get_by_label('Rehearsal role').select_option('usher')
 expect(page.get_by_role('heading',name='Your operations brief')).to_be_visible()
 page.get_by_role('button',name='Service lift',exact=True).click()
 expect(page.get_by_text('The service lift is in the east staff corridor, behind the banquet service door.',exact=True)).to_be_visible()
 page.set_viewport_size({'width':390,'height':844})
 page.get_by_role('navigation').get_by_role('button',name='My tasks',exact=True).click()
 expect(page.get_by_role('heading',name='Take position at Ballroom Entrance B')).to_be_visible()
 page.evaluate("document.querySelector('#toast').className=''")
 page.screenshot(path=str(out/'helper-mobile.png'),full_page=True)
 overflow=page.evaluate('document.documentElement.scrollWidth > window.innerWidth')
 assert not overflow,'Mobile overflow'
 assert not errors,errors
 report={'mode':'offline Chromium + real ASGI backend via test bridge (not network E2E)' if args.bridge else 'Chromium HTTP browser E2E','screens_visited':11,'tested_workflows':['delay-propose-confirm-approve','role-aware approval visibility','missing-family then parents arrival','guest seating lookup','approved knowledge lookup','mobile layout no horizontal overflow'],'javascript_errors':errors,'screenshots':[str(x.relative_to(root)) for x in out.glob('*.png')]}
 (out/'browser-report.json').write_text(json.dumps(report,indent=2)+'\n')
 print(json.dumps(report,indent=2))
 browser.close()
