import base64, concurrent.futures, http.client, io, json, os, sys, tempfile, threading, unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from PIL import Image

class AppTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.old=app.DATA;app.DATA=Path(self.tmp.name);app.init()
  self.env=patch.dict(os.environ,{'ARK_API_KEY':'fake-test-key','JIGU_PAID_ENABLED':'1','JIGU_BUDGET_CNY':'10','ARK_TEXT_MODEL':''});self.env.start()
  for x in 'ab':app.create_user(x+'@example.test',x+'-test-password-123')
  self.server=app.ThreadingHTTPServer(('127.0.0.1',0),app.Handler);self.port=self.server.server_port
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.users={}
  for x in 'ab':
   _,v,h=self.req('/login','POST',{'email':x+'@example.test','password':x+'-test-password-123'});self.users[x]=(h['Set-Cookie'].split(';')[0],v['csrf'])
  im=Image.new('RGB',(90,90),'#becdb3');out=io.BytesIO();exif=im.getexif();exif[270]='sensitive metadata';im.save(out,'JPEG',exif=exif);self.photo=base64.b64encode(out.getvalue()).decode()
 def tearDown(self):
  self.server.shutdown();self.server.server_close();self.thread.join();self.env.stop();app.DATA=self.old;self.tmp.cleanup()
 def req(self,path,method='GET',body=None,user=None,headers=None):
  h={'Content-Type':'application/json'}
  if user:h.update({'Cookie':self.users[user][0],'X-CSRF-Token':self.users[user][1]})
  h.update(headers or {});c=http.client.HTTPConnection('127.0.0.1',self.port,timeout=10);c.request(method,'/api'+path,None if body is None else json.dumps(body).encode(),h);r=c.getresponse();s=r.status;h=dict(r.getheaders());raw=r.read();c.close();return s,json.loads(raw) if 'application/json' in h.get('Content-Type','') else raw,h
 def book(self,photos=None):
  return self.req('/books','POST',{'photos':photos or [self.photo],'event':'宝宝在家披着紫色围巾扮演国王和公主。','mood':'我觉得她好可爱。','detail':'开心说：「我是国王先生！」','nickname':'开心','event_date':'2026-10-21'},'a')
 def story(self,n=5):
  s,b,_=self.book();self.assertEqual(s,201);s,b,_=self.req('/books/'+b['id']+'/organize','POST',{'count':n},'a');self.assertEqual(s,200);return b
 def get(self,b):return self.req('/books/'+b['id'],user='a')[1]
 def start(self,b,key='test-request-key-123456'):return self.req('/books/'+b['id']+'/generate','POST',{'request_key':key},'a')
 def generated(self,b):
  out=io.BytesIO();Image.new('RGB',(1776,2368),'#eac5a5').save(out,'PNG');result={'data':[{'b64_json':base64.b64encode(out.getvalue()).decode()}],'usage':{'generated_images':1}}
  self.start(b)
  with patch.object(app,'ark',return_value=result) as mock:
   for p in b['pages']:self.assertTrue(app.worker_once())
   for call in mock.call_args_list:
    payload=call.args[1];self.assertEqual(payload['model'],app.MODEL);self.assertNotIn('sequential_image_generation',payload);self.assertFalse(payload['watermark']);self.assertEqual(payload['size'],'1776x2368');self.assertTrue(payload['image'][0].startswith('data:image/jpeg;base64,'))
  return self.get(b),result
 def test_auth_and_logout(self):
  self.assertEqual(self.req('/books')[0],401);self.assertEqual(self.req('/login','POST',{'email':'a@example.test','password':'wrong'})[0],401)
  self.assertEqual(self.req('/me',user='a')[1]['email'],'a@example.test');self.assertEqual(self.req('/logout','POST',{},'a')[0],200);self.assertEqual(self.req('/me',user='a')[0],401)
 def test_csrf_and_origin(self):
  self.assertEqual(self.req('/logout','POST',{},'a',{'X-CSRF-Token':'wrong'})[0],403);self.assertEqual(self.req('/logout','POST',{},'a',{'Origin':'https://evil.example'})[0],403)
 def test_all_cross_user_routes_denied(self):
  b=self.story()
  for path,m in [('', 'GET'),('', 'DELETE'),('/content','PATCH'),('/generate','POST'),('/redraw','POST'),('/pdf','GET'),('/save','POST'),('/choose','POST')]:self.assertEqual(self.req('/books/'+b['id']+path,m,{} if m!='GET' else None,'b')[0],404)
  self.assertEqual(self.req('/assets/'+b['photos'][0],user='b')[0],404);self.assertEqual(self.req('/assets/'+b['photos'][0])[0],401);self.assertEqual(self.req('/books',user='b')[1],[])
 def test_exif_and_cascade_delete(self):
  _,b,_=self.book();path=app.DATA/'assets'/(b['photos'][0]+'.jpg')
  with Image.open(path) as im:self.assertFalse(im.getexif())
  self.assertEqual(self.req('/books/'+b['id'],'DELETE',user='a')[0],200);self.assertFalse(path.exists())
 def test_invalid_upload_rolls_back_files(self):
  s,_,_=self.book([self.photo,base64.b64encode(b'bad').decode()]);self.assertEqual(s,400);self.assertEqual(list((app.DATA/'assets').iterdir()),[]);self.assertEqual(self.req('/books',user='a')[1],[])
 def test_extractive_story_counts_and_original_quote(self):
  for n in (5,7,10):
   b=self.story(n);self.assertEqual(b['source'],'structured');self.assertEqual(len(b['pages']),n);text=''.join(p['page_text'] for p in b['pages']);self.assertIn('我是国王先生',text);self.assertNotIn('病好了',text)
 def test_model_output_rejected_if_wrong_count(self):
  b=self.story()
  with patch.dict(os.environ,{'ARK_TEXT_MODEL':'test-model'}),patch.object(app,'ark',return_value={'choices':[{'message':{'content':'{"title":"x","pages":[]}'}}]}):self.assertEqual(self.req('/books/'+b['id']+'/organize','POST',{'count':5},'a')[0],400)
 def test_concurrent_submission_idempotent(self):
  b=self.story()
  with concurrent.futures.ThreadPoolExecutor(max_workers=5) as p:results=list(p.map(lambda _:self.start(b),range(5)))
  self.assertTrue(all(x[0]==202 for x in results));self.assertEqual(len(self.get(b)['jobs']),5);self.start(b,'another-request-key-12345');self.assertEqual(len(self.get(b)['jobs']),5)
 def test_budget_and_paid_gate(self):
  b=self.story()
  with patch.dict(os.environ,{'JIGU_BUDGET_CNY':'0.59'}):self.assertEqual(self.start(b)[0],409)
  with patch.dict(os.environ,{'JIGU_PAID_ENABLED':'0'}):self.assertEqual(self.start(b)[0],503)
  self.assertEqual(len(self.get(b)['jobs']),0)
 def test_persistent_queue_and_seedream_payload(self):
  b=self.story();self.start(b);app.init();self.assertEqual(len(self.get(b)['jobs']),5);b,_=self.generated(b);self.assertTrue(all(p['image'] for p in b['pages']));self.assertTrue(all(j['state']=='done' for j in b['jobs']))
 def test_ambiguous_failure_does_not_retry(self):
  b=self.story();self.start(b)
  with patch.object(app,'ark',side_effect=TimeoutError()):
   for i in range(5):app.worker_once()
   self.assertFalse(app.worker_once())
  self.assertTrue(all(j['state']=='uncertain' for j in self.get(b)['jobs']))
 def test_redraw_candidate_keeps_original(self):
  b,r=self.generated(self.story());old=b['pages'][0]['image'];s,_,_=self.req('/books/'+b['id']+'/redraw','POST',{'page':0,'reason':'宝宝不像','request_key':'redraw-request-123456789'},'a');self.assertEqual(s,202)
  with patch.object(app,'ark',return_value=r):app.worker_once()
  b=self.get(b);self.assertEqual(b['pages'][0]['image'],old);self.assertTrue(b['pages'][0]['candidate']);s,b,_=self.req('/books/'+b['id']+'/choose','POST',{'page':0,'accept':False},'a');self.assertEqual(s,200);self.assertEqual(b['pages'][0]['image'],old);self.assertIsNone(b['pages'][0]['candidate'])
 def test_pdf_complete_only(self):
  b=self.story();self.assertEqual(self.req('/books/'+b['id']+'/pdf',user='a')[0],409);b,_=self.generated(b);s,raw,_=self.req('/books/'+b['id']+'/pdf',user='a');self.assertEqual(s,200);self.assertTrue(raw.startswith(b'%PDF'))
  from pypdf import PdfReader
  self.assertEqual(len(PdfReader(io.BytesIO(raw)).pages),5)
 def test_optimistic_lock_and_save(self):
  b=self.story();data={'title':'我是国王先生！','pages':b['pages'],'revision':b['revision']};self.assertEqual(self.req('/books/'+b['id']+'/content','PATCH',data,'a')[0],200);self.assertEqual(self.req('/books/'+b['id']+'/content','PATCH',data,'a')[0],409);self.assertEqual(self.req('/books/'+b['id']+'/save','POST',{},'a')[0],409)

 def test_spend_survives_book_deletion(self):
  b,_=self.generated(self.story());self.assertEqual(self.req('/books/'+b['id'],'DELETE',user='a')[0],200)
  with app.tx() as c:self.assertAlmostEqual(c.execute('SELECT SUM(reserved) FROM charges').fetchone()[0],.6)
  other=self.story()
  with patch.dict(os.environ,{'JIGU_BUDGET_CNY':'1.19'}):self.assertEqual(self.start(other)[0],409)
 def test_text_model_requires_paid_authorization(self):
  b=self.story()
  with patch.dict(os.environ,{'ARK_TEXT_MODEL':'test-model','JIGU_PAID_ENABLED':'0'}),patch.object(app,'ark') as call:
   self.assertEqual(self.req('/books/'+b['id']+'/organize','POST',{'count':5},'a')[0],503);call.assert_not_called()
 def test_retry_failed_redraw_keeps_original(self):
  b,result=self.generated(self.story());old=b['pages'][0]['image']
  self.req('/books/'+b['id']+'/redraw','POST',{'page':0,'reason':'场景不对','request_key':'redraw-failure-12345678'},'a')
  with patch.object(app,'ark',side_effect=TimeoutError()):app.worker_once()
  self.assertEqual(self.req('/books/'+b['id']+'/retry','POST',{'request_key':'retry-failure-12345678'},'a')[0],202)
  with patch.object(app,'ark',return_value=result):app.worker_once()
  b=self.get(b);self.assertEqual(b['pages'][0]['image'],old);self.assertTrue(b['pages'][0]['candidate'])
 def test_worker_does_not_resend_running_job(self):
  b=self.story();self.start(b)
  with app.tx() as c:c.execute("UPDATE jobs SET state='running' WHERE id=(SELECT id FROM jobs LIMIT 1)")
  with patch.object(app,'ark') as call:self.assertFalse(app.worker_once());call.assert_not_called()

 def test_restart_marks_interrupted_without_touching_completed(self):
  b=self.story();self.start(b)
  with app.tx() as c:
   jid=c.execute('SELECT id FROM jobs LIMIT 1').fetchone()[0];c.execute("UPDATE jobs SET state='running' WHERE id=?",(jid,));c.execute("UPDATE charges SET state='running' WHERE id=?",(jid,))
  app.recover_interrupted();book=self.get(b);self.assertEqual(sum(j['state']=='uncertain' for j in book['jobs']),1);self.assertEqual(sum(j['state']=='queued' for j in book['jobs']),4)
 def test_visual_constraints_persist(self):
  b=self.story();s,b,_=self.req('/books/'+b['id']+'/content','PATCH',{'title':b['title'],'pages':b['pages'],'revision':b['revision'],'constraints':'紫色围巾，始终在家里'},'a');self.assertEqual(s,200);self.assertEqual(b['input']['constraints'],'紫色围巾，始终在家里')
 def test_worker_lock_prevents_second_process(self):
  with app.worker_lock():
   with self.assertRaises(SystemExit):
    with app.worker_lock():pass

if __name__=='__main__':unittest.main()
