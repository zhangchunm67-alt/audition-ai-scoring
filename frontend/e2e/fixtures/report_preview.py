"""报告 UI 的离线示例预览：只读虚构数据，不连接业务数据库。运行 python3 serve.py。"""
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import json

ROOT = Path(__file__).resolve().parents[3] / 'frontend' / 'dist'
NAMES = {'P':'人设塑造','S':'销售循环','L':'表达逻辑','O':'其他能力'}
SCORES = {'P':84,'S':72,'L':91,'O':80}
GRADES = {'P':3,'S':4,'L':2,'O':4}
ITEMS = [
 ('P1','形象','P',10,10),('P2','口头禅','P',6,10),('P3','普通话标准','P',8,10),
 ('S1','需求引导','S',5,10),('S2','固定话术准确度','S',38,50),('S3','解答异议','S',0,20,'not_applicable'),
 ('L1','逻辑结构','L',18,20),('L2','举例说明','L',4.5,5),('L3','表达准确性','L',0,10,'missing_evidence'),
 ('O1','专业术语','O',6,10),('O2','卖点提炼','O',12,20),('O3','互动能力','O',10,10)]
items = [dict(item_id=i[0],name=i[1],dimension=i[2],type='T4',status=i[5] if len(i)>5 else 'scored',score=None if len(i)>5 else i[3],max=i[4],low_confidence=False,low_confidence_reasons=[],missing_reasons=[],contributions=[],notes=[],source='machine') for i in ITEMS]
ROUND = dict(round_no=1,total_grade=13,grade_pass=True,dimension_scores=SCORES,dimension_grades=GRADES)
DETAIL = dict(id='demo-report',revision=1,superseded_at=None,created_at='2026-11-16T09:30:00Z',recording_id='demo-recording',candidate_id='demo-candidate',candidate_name='陈思远（演示）',candidate_phone_masked='138****6280',candidate_video_asset_id=None,submitted_at='2026-11-16T09:00:00Z',sheet_code='DEMO-001',product_name='健康福百万重疾险',audience='new_trial',props_available=False,mode='live',label='recommend',conclusion='推荐',critical=False,redline_hit=False,informal=False,verdict=dict(reason='界面示例数据，仅用于预览布局，不代表真实候选人的评分。',rounds=[ROUND],display_round=1,majority_grade_pass=True),display_round=1,
 result=dict(items=items,dimensions=[dict(id=k,name=v,status='complete',raw=SCORES[k],applicable_max=100,scaled=SCORES[k],score=SCORES[k],grade=GRADES[k]) for k,v in NAMES.items()],total_grade=13,threshold=15,audience='new_trial',critical=False,low_confidence_items=[],missing_items=['L3'],redlines_enabled=False),
 evidence=[dict(evidence_id='demo-evidence',item_id='S1',item_name='需求引导',kind='level',start_ms=12000,end_ms=16000,quote='这里是评分证据的演示文本。',label='需求引导',judgment=5,reason='演示：先询问观众需求，再介绍产品责任。',confidence=.9,source='machine',ref=None,value=None,segment='main',delta=None,issue=True)],
 sentences=[dict(segment='main',sentences=[dict(segment='main',start_ms=12000,end_ms=16000,text='这里是评分证据的演示文本。',hits=[],issue=True,suggestion=None)],segment_hits=[])],
 trace=dict(rubric_version='rubric-v0.3',rubric_status='draft',config_hash='demo',detector_config_version='detectors-v3',detector_config_status='draft',redline_lexicon_version=None,model_manifest={'说明': {'用途':'界面示例，非真实评分'}}),
 media=dict(video_asset_id=None,video_deleted=False,segments=[dict(segment='main',start_ms=0,end_ms=600000)],objection_times=[]))
rows=[]
for idx,name in enumerate(['陈思远','黄诗涵','刘明远','孙佳怡']):
 rows.append(dict(id='demo-report' if idx==0 else f'demo-{idx}',rank=idx+1,recording_id='demo-recording',candidate_name=name+'（演示）',candidate_phone_masked=f'138****{6280+idx}',candidate_video_asset_id=None,submitted_at='2026-11-16T09:00:00Z',audience='new_trial',mode='audition',label='recommend' if idx<2 else 'pending',reason='界面演示，不代表真实评分',total_grade=13+idx,threshold=15,dimension_scores={**SCORES,'P':[84,72,66,58][idx]},dimension_grades={**GRADES,'P':3+idx},critical=False,informal=False,low_confidence_count=0,revision=1))

class Handler(SimpleHTTPRequestHandler):
 def __init__(self,*a,**kw):super().__init__(*a,directory=str(ROOT),**kw)
 def log_message(self,*args):pass
 def do_GET(self):
  path=urlparse(self.path).path
  if path.startswith('/api/'):
   if path=='/api/auth/me':data=dict(id='preview',username='preview',display_name='界面预览 · 示例数据',role='admin',permissions=['report.read_all','report.read_own','recording.upload','sheet.read','config.read','candidate.read','dashboard.read'])
   elif path=='/api/reports':
    query=parse_qs(urlparse(self.path).query)
    value=lambda key:query.get(key,[''])[0]
    data=[r for r in rows if (not value('mode') or r['mode']==value('mode')) and (not value('label') or r['label']==value('label')) and (not value('date_from') or r['submitted_at'][:10]>=value('date_from')) and (not value('date_to') or r['submitted_at'][:10]<=value('date_to'))]
    if value('sort') in NAMES:data=sorted(data,key=lambda r:-r['dimension_scores'][value('sort')])
   elif path.endswith('/revisions'):data=[dict(id='demo-report',revision=1,label='recommend',rubric_version='rubric-v0.3',superseded_at=None)]
   elif path.startswith('/api/reports/'):
    if path.endswith('/pdf'):
     self.send_error(501,'Preview only');return
    data={**DETAIL,'id':path.rsplit('/',1)[-1]}
    row=next((r for r in rows if r['id']==data['id']),None)
    if row:
     data.update(candidate_name=row['candidate_name'],candidate_phone_masked=row['candidate_phone_masked'],label=row['label'],mode=row['mode'])
     data['result']={**DETAIL['result'],'total_grade':row['total_grade'],'dimensions':[{**dim,'score':row['dimension_scores'][dim['id']],'grade':row['dimension_grades'][dim['id']]} for dim in DETAIL['result']['dimensions']]}
   else:data=[]
   body=json.dumps(data,ensure_ascii=False).encode();self.send_response(200);self.send_header('Content-Type','application/json; charset=utf-8');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body);return
  if not path.startswith('/assets/'):self.path='/index.html'
  super().do_GET()

if __name__=='__main__':
 print('示例预览 http://127.0.0.1:8766/reports',flush=True)
 ThreadingHTTPServer(('127.0.0.1',8766),Handler).serve_forever()
