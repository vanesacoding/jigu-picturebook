"""ISOLATED VISUAL QA ONLY. No real users, no secrets, no model calls.
Never deploy this file. Production entrypoint is app.py serve.
"""
import io, json, sys, tempfile
from pathlib import Path
from urllib.parse import urlparse, parse_qs
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import app
from PIL import Image,ImageDraw
scratch=tempfile.TemporaryDirectory(prefix='jigu-visual-only-');app.DATA=Path(scratch.name);app.init()
with app.tx() as c:
 c.execute('INSERT INTO users VALUES(?,?,?)',('visual-qa','qa@example.test','UNUSABLE'))
 inp={'event':'宝宝今天发烧了，不能出门，在家用妈妈的围巾扮演阿拉伯的国王和公主玩。','mood':'我觉得她好可爱。','detail':'开心说：「我是国王先生！」她居然知道国王是先生。','nickname':'开心','constraints':'紫色围巾。只在家里，不增加王冠、权杖、宫殿。'}
 pages=app.fallback(inp,5)[1]
 texts=['我是国王先生！','今天，开心发烧了，不能出门。','在家里，开心披着妈妈的紫色围巾，玩起了国王和公主的扮演游戏。','开心说：「我是国王先生！」','原来，她已经知道国王是先生。妈妈觉得她好可爱。']
 c.execute('INSERT INTO books(id,user_id,title,event_date,input,pages,source,created) VALUES(?,?,?,?,?,?,?,?)',('f'*32,'visual-qa','我是国王先生！','2026-10-21',app.dumps(inp),'[]','structured',app.now()))
 for i,p in enumerate(pages):
  im=Image.new('RGB',(1776,2368),'#faf7f0');d=ImageDraw.Draw(im)
  d.ellipse((480,1620,1350,1760),fill='#e4e8d5');d.ellipse((570+i*15,760,1260+i*15,1610),fill='#e7ce8e')
  d.ellipse((775+i*15,1030,800+i*15,1060),fill='#5b4b3c');d.ellipse((1010+i*15,1030,1035+i*15,1060),fill='#5b4b3c');d.ellipse((880+i*15,1130,955+i*15,1175),fill='#d5a17d')
  d.rounded_rectangle((720,1310,1110,1590),30,fill='#fffcf4',outline='#cfbea5',width=5);d.line((915,1315,915,1585),fill='#d9ccbb',width=4)
  out=io.BytesIO();im.save(out,'JPEG');p['image']=app.store_image(c,out.getvalue(),'visual-qa','f'*32,'illustration');p['page_text']=texts[i]
 c.execute('UPDATE books SET pages=? WHERE id=?',(app.dumps(pages),'f'*32))
 c.execute("INSERT INTO jobs(id,user_id,book_id,page,reason,state,request_key,created,reserved) VALUES(?,?,?,?,?,?,?,?,?)",('visual-job','visual-qa','f'*32,0,'','done','visual-job',app.now(),0))
 clean_pages=[{**p,'image':None} for p in pages]
 c.execute('INSERT INTO books(id,user_id,title,event_date,input,pages,source,created) VALUES(?,?,?,?,?,?,?,?)',('e'*32,'visual-qa','我是国王先生！','2026-10-21',app.dumps(inp),app.dumps(clean_pages),'structured',app.now()-1))
class VisualHandler(app.Handler):
 def auth(self,c,write=False):return {'user_id':'visual-qa','csrf':'VISUAL-QA-NOT-A-SESSION'}
 def send_header(self,k,v):
  if k=='Content-Security-Policy':v=v.replace("frame-ancestors 'none'","frame-ancestors 'self'")
  super().send_header(k,v)
 def route(self,method):
  if self.path=='/qa.css':
   return self.send(200,b'body{margin:0;background:#e8e4dc;font-family:system-ui;text-align:center;color:#70665a}p{font-size:12px;margin:16px}a{color:inherit;margin:0 10px}iframe{display:block;margin:14px auto;border:1px solid #d2c8b8;border-radius:22px;background:#faf7f0}', 'text/css; charset=utf-8')
  if self.path.startswith('/qa'):
   q=parse_qs(urlparse(self.path).query);w=int(q.get('width',['390'])[0]);w=w if w in (375,390,430) else 390
   screen=q.get('screen',['home'])[0];frag='book/'+('e'*32 if screen=='confirm' else 'f'*32) if screen in ('reader','confirm') else screen
   html='''<!doctype html><meta charset="utf-8"><title>叽咕插画 · 隔离排版验收</title><link rel="stylesheet" href="/qa.css"><p>界面验收专用 · 插图为程序绘制的测试素材，非豆包生成结果 · 无真实照片</p><p><a href="/qa?width=375">375</a><a href="/qa?width=390">390</a><a href="/qa?width=430">430</a> ｜ <a href="/qa?screen=home">首页</a><a href="/qa?screen=form">记录故事</a><a href="/qa?screen=confirm">故事确认</a><a href="/qa?screen=reader">阅读页</a><a href="/qa?screen=library">我的小书</a></p>'''+f'<iframe title="手机界面验收" width="{w}" height="844" src="/#{frag}"></iframe>'
   return self.send(200,html.encode(),'text/html; charset=utf-8')
  return super().route(method)
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('--host',default='0.0.0.0');p.add_argument('--port',type=int,default=4173);p.add_argument('--strictPort',action='store_true');a=p.parse_args()
 app.ThreadingHTTPServer((a.host,a.port),VisualHandler).serve_forever()
