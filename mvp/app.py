"""叽咕插画: private, single-host MVP. Python 3.11+, Pillow, reportlab."""
from __future__ import annotations
import argparse, base64, contextlib, hashlib, hmac, io, json, os, re, secrets, sqlite3, time, urllib.request, urllib.error
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from PIL import Image, ImageOps, UnidentifiedImageError

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get('JIGU_DATA_DIR', ROOT / 'private-data')).resolve()
MODEL = 'doubao-seedream-5-0-flash-260915'
ARK_URL = 'https://ark.cn-beijing.volces.com/api/v3/'
MAX_BODY = 54 * 1024 * 1024
# Track new asset files per transaction; remove them if database changes roll back.
import threading
_pending = threading.local()
Image.MAX_IMAGE_PIXELS = 36_000_000

def uid(): return secrets.token_hex(16)
def dumps(x): return json.dumps(x, ensure_ascii=False)
def now(): return int(time.time())
class Problem(Exception):
    def __init__(self, status, message): self.status, self.message = status, message

def db():
    c = sqlite3.connect(DATA / 'jigu.sqlite3', timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA busy_timeout=30000')
    return c

@contextlib.contextmanager
def tx():
    with contextlib.closing(db()) as c:
        c.execute('BEGIN IMMEDIATE')
        _pending.files = []
        try: yield c; c.commit()
        except BaseException:
            c.rollback()
            for path in _pending.files: path.unlink(missing_ok=True)
            raise
        finally: _pending.files = []

def init():
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    (DATA / 'assets').mkdir(exist_ok=True, mode=0o700)
    with contextlib.closing(db()) as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,email TEXT UNIQUE,password TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),csrf TEXT,expires INTEGER);
        CREATE TABLE IF NOT EXISTS auth_attempts(ip TEXT,at INTEGER);
        CREATE TABLE IF NOT EXISTS books(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),title TEXT,event_date TEXT,input TEXT,pages TEXT,source TEXT,saved INTEGER DEFAULT 0,created INTEGER,revision INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS assets(id TEXT PRIMARY KEY,user_id TEXT REFERENCES users(id),book_id TEXT REFERENCES books(id) ON DELETE CASCADE,kind TEXT);
        CREATE TABLE IF NOT EXISTS charges(id TEXT PRIMARY KEY,model TEXT,kind TEXT,state TEXT,reserved REAL,usage TEXT,elapsed REAL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,user_id TEXT,book_id TEXT REFERENCES books(id) ON DELETE CASCADE,page INTEGER,reason TEXT,state TEXT,request_key TEXT,created INTEGER,started INTEGER,finished INTEGER,error TEXT,usage TEXT,reserved REAL,elapsed REAL);
        CREATE UNIQUE INDEX IF NOT EXISTS unique_job ON jobs(user_id,request_key);
        CREATE UNIQUE INDEX IF NOT EXISTS active_page ON jobs(book_id,page) WHERE state IN ('queued','running');
        CREATE INDEX IF NOT EXISTS owner_books ON books(user_id,created);
        ''')
        c.commit()

def clean(x, maximum=2000):
    if not isinstance(x, str) or len(x) > maximum: raise Problem(400, '内容太长或格式不正确')
    return x.strip()

def owns(c, book_id, user):
    b = c.execute('SELECT * FROM books WHERE id=? AND user_id=?',(book_id,user)).fetchone()
    if not b: raise Problem(404,'找不到这本小书')
    return b

def pack(c,b):
    d = dict(b); d['input'] = json.loads(d['input']); d['pages'] = json.loads(d['pages'])
    d['photos'] = [r['id'] for r in c.execute("SELECT id FROM assets WHERE book_id=? AND kind='photo' ORDER BY rowid",(d['id'],))]
    d['jobs'] = [dict(r) for r in c.execute('SELECT id,page,reason,state,error,elapsed,usage,reserved FROM jobs WHERE book_id=? ORDER BY created,rowid',(d['id'],))]
    return d

def store_image(c, raw, user, book, kind):
    try:
        with Image.open(io.BytesIO(raw)) as im:
            if im.format not in ('JPEG','PNG','WEBP','HEIF','HEIC'): raise ValueError()
            im = ImageOps.exif_transpose(im).convert('RGB')
            im.thumbnail((2048,2048) if kind == 'photo' else (1776,2368))
            out = io.BytesIO(); im.save(out,'JPEG',quality=92)
    except (Exception,) as e: raise Problem(400,'照片无法读取，请选择 JPG、PNG 或 WebP 图片') from e
    aid = uid(); p = DATA / 'assets' / (aid+'.jpg')
    if hasattr(_pending, 'files'): _pending.files.append(p)
    p.write_bytes(out.getvalue()); p.chmod(0o600)
    c.execute('INSERT INTO assets VALUES(?,?,?,?)',(aid,user,book,kind))
    return aid

def validate_pages(pages, n):
    if n not in (5,7,10) or not isinstance(pages,list) or len(pages)!=n: raise Problem(400,'请使用 5、7 或 10 页，封面也计入页数')
    out=[]
    for p in pages:
        if not isinstance(p,dict): raise Problem(400,'故事格式不正确')
        text=clean(p.get('page_text'),240); scene=clean(p.get('scene_description'),500)
        if not text or not scene: raise Problem(400,'请为每一页填写文字和画面')
        out.append({'page_text':text,'scene_description':scene,'image':None,'candidate':None,'history':[]})
    return out

def fallback(inp,n):
    # Deterministic extractive draft: never pretend to be model output or invent an event.
    facts = [part.strip()+'。' for part in re.split(r'[。！？]+',inp['event']) if part.strip()] or [inp['event']]
    if inp.get('detail'): facts.append(inp['detail'])
    if inp.get('mood'): facts.append('妈妈的心情：'+inp['mood'])
    title=(inp.get('nickname') or '宝宝')+'的小小一天'
    pages=[]
    for i in range(n):
        text=title if i==0 else facts[min((i-1)*len(facts)//(n-1),len(facts)-1)]
        view=['留白封面，中景','侧面中景','双手与道具近景','环境远景','侧面特写'][i%5]
        pages.append({'page_text':text[:240], 'scene_description':view+'；只画已描述的事实：'+inp['event'][:220]+'。宝宝的脸型、发型与衣着以照片为准。'})
    return title,validate_pages(pages,n),'structured'

def ark(path,payload,timeout=180):
    key=os.environ.get('ARK_API_KEY')
    if not key: raise Problem(503,'尚未配置创作服务，请联系管理员')
    req=urllib.request.Request(ARK_URL+path,data=dumps(payload).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r: return json.load(r)
    except urllib.error.HTTPError as e:
        # Do not log response bodies, prompts, credentials or photos.
        raise Problem(502,'创作服务返回错误（HTTP '+str(e.code)+'），请检查服务配置') from None
    except (TimeoutError,urllib.error.URLError):
        raise Problem(502,'未能确认创作结果。为避免重复计费，不会自动重试，请先核对服务账单') from None

def organize(inp,n):
    model=os.environ.get('ARK_TEXT_MODEL','')
    if not model: return fallback(inp,n)
    system='你是成长记录编辑。只使用输入中明确出现的真实事实，保留原话，不推测疾病变化、地点、人物、道具、穿着或动作，不编结局。不足时重复观察同一瞬间，不虚构。封面计入总页数。每页1-2句。画面描述用可见动作、空间关系和不同景别，未描述的动作不能新增。输出JSON：title、pages（page_text、scene_description）。只输出JSON。'
    if not os.environ.get('ARK_API_KEY') or os.environ.get('JIGU_PAID_ENABLED')!='1': raise Problem(503,'故事服务尚未开启，可先使用结构化初稿')
    record=uid();reserve=float(os.environ.get('JIGU_TEXT_RESERVE_CNY','0.05'));start=time.monotonic()
    with tx() as c:
        used=c.execute('SELECT COALESCE(SUM(reserved),0) FROM charges').fetchone()[0]
        if used+reserve>cost_limit():raise Problem(409,'故事整理额度不足，可先使用结构化初稿')
        c.execute('INSERT INTO charges VALUES(?,?,?,?,?,?,?)',(record,model,'text','running',reserve,None,None))
    try:
        result=ark('chat/completions',{'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':dumps({'facts':inp,'page_count':n})}],'temperature':0.2,'response_format':{'type':'json_object'},'max_tokens':4096},90)
    except Exception:
        with tx() as c:c.execute("UPDATE charges SET state='uncertain',elapsed=? WHERE id=?",(time.monotonic()-start,record))
        raise
    with tx() as c:c.execute("UPDATE charges SET state='done',usage=?,elapsed=? WHERE id=?",(dumps(result.get('usage',{})),time.monotonic()-start,record))
    try:
        value=json.loads(result['choices'][0]['message']['content'])
        return clean(value['title'],80),validate_pages(value['pages'],n),'doubao'
    except (KeyError,ValueError,TypeError): raise Problem(502,'故事格式没有整理好，请重新整理，或使用结构化初稿')

def prompt(b,page,reason):
    inp=json.loads(b['input']); pages=json.loads(b['pages']); p=pages[page]
    constraint=inp.get('constraints','')
    # No hard-coded age, gender, outfit or scarf for unrelated families.
    return '\n'.join([
        '【画风】简约彩色儿童小绘本，柔和低饱和水彩与彩铅质感，暖白背景，大量留白，简单自然比例。',
        '【人物】严格参考原始照片中宝宝的脸型、五官、发型与衣着，不美化、不放大眼睛；同一本书保持一致。'+constraint,
        '【本页】'+p['scene_description']+'。故事事实：'+inp['event']+'。特别细节：'+inp.get('detail','')+'。重画要求：'+(reason or '初次绘制'),
        '【禁止】不出现文字、字母、水印、拼图；不添加未描述的人物、动物、道具或事件；不把扮演想象画成现实场景；不画王冠、权杖、宫殿，除非真实事实明确提及；不加复杂背景与强光影。一页只聚焦一件事。'])

def cost_limit():
    try: return float(os.environ.get('JIGU_BUDGET_CNY','0'))
    except ValueError: return 0

def enqueue(c,b,user,key,indices,reason=''):
    if not os.environ.get('ARK_API_KEY') or os.environ.get('JIGU_PAID_ENABLED')!='1': raise Problem(503,'绘画服务尚未开启，请管理员完成安全配置和预算授权')
    if not isinstance(key,str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,100}',key): raise Problem(400,'请刷新后重新提交')
    previous=c.execute('SELECT id FROM jobs WHERE user_id=? AND request_key LIKE ?',(user,key+':%')).fetchall()
    if previous: return
    pages=json.loads(b['pages']); unit=float(os.environ.get('JIGU_IMAGE_UNIT_CNY','0.12'))
    todo=[]
    for i in indices:
        if c.execute("SELECT 1 FROM jobs WHERE book_id=? AND page=? AND state IN ('queued','running')",(b['id'],i)).fetchone(): continue
        if not reason and pages[i]['image']: continue
        if pages[i].get('candidate'): raise Problem(409,'请先选择是否保留这次重画')
        count=c.execute('SELECT COUNT(*) FROM jobs WHERE book_id=? AND page=?',(b['id'],i)).fetchone()[0]
        if count>=4: raise Problem(409,'这一页已达到本次创作上限，请联系管理员核对')
        todo.append(i)
    used=c.execute('SELECT COALESCE(SUM(reserved),0) FROM charges').fetchone()[0]
    if used+len(todo)*unit>cost_limit()+1e-8: raise Problem(409,'本次创作额度不足，请联系管理员')
    for i in todo:
        job_id=uid()
        c.execute('INSERT INTO jobs(id,user_id,book_id,page,reason,state,request_key,created,reserved) VALUES(?,?,?,?,?,?,?,?,?)',(job_id,user,b['id'],i,reason,'queued',key+':'+str(i),now(),unit))
        c.execute('INSERT INTO charges VALUES(?,?,?,?,?,?,?)',(job_id,MODEL,'image','queued',unit,None,None))

def worker_once():
    with tx() as c:
        if c.execute("SELECT 1 FROM jobs WHERE state='running'").fetchone(): return False
        j=c.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created,rowid LIMIT 1").fetchone()
        if not j: return False
        c.execute("UPDATE jobs SET state='running',started=? WHERE id=?",(now(),j['id']))
        c.execute("UPDATE charges SET state='running' WHERE id=?",(j['id'],))
        b=owns(c,j['book_id'],j['user_id'])
        refs=[r['id'] for r in c.execute("SELECT id FROM assets WHERE book_id=? AND kind='photo' ORDER BY rowid",(b['id'],))]
    start=time.monotonic(); usage=None
    try:
        payload={'model':MODEL,'prompt':prompt(b,j['page'],j['reason']),'image':['data:image/jpeg;base64,'+base64.b64encode((DATA/'assets'/(r+'.jpg')).read_bytes()).decode() for r in refs],'size':'1776x2368','watermark':False,'response_format':'b64_json'}
        result=ark('images/generations',payload)
        usage=result.get('usage',{})
        outputs=result.get('data',[])
        if len(outputs)!=1 or not outputs[0].get('b64_json'): raise Problem(502,'未收到一张完整图片，请核对账单后再试')
        raw=base64.b64decode(outputs[0]['b64_json'],validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            if im.size!=(1776,2368): raise Problem(502,'图片尺寸不符合小书要求，请核对账单')
        with tx() as c:
            fresh=owns(c,b['id'],j['user_id']); pages=json.loads(fresh['pages'])
            aid=store_image(c,raw,j['user_id'],b['id'],'illustration')
            p=pages[j['page']]
            if p['image']: p['candidate']=aid
            else: p['image']=aid
            c.execute('UPDATE books SET pages=?,revision=revision+1 WHERE id=?',(dumps(pages),b['id']))
            count=usage.get('generated_images',1)
            reserve=max(1,int(count))*float(os.environ.get('JIGU_IMAGE_UNIT_CNY','0.12'))
            c.execute("UPDATE charges SET state='done',usage=?,elapsed=?,reserved=? WHERE id=?",(dumps(usage),time.monotonic()-start,reserve,j['id']))
            c.execute("UPDATE jobs SET state='done',usage=?,finished=?,elapsed=?,reserved=? WHERE id=?",(dumps(usage),now(),time.monotonic()-start,reserve,j['id']))
    except Exception:
        # A failed response can still have been billed: reserve budget and require a deliberate retry.
        with tx() as c:
            c.execute("UPDATE charges SET state='uncertain',usage=?,elapsed=? WHERE id=?",(dumps(usage),time.monotonic()-start,j['id']))
            c.execute("UPDATE jobs SET state='uncertain',error=?,usage=?,finished=?,elapsed=? WHERE id=?",('这一页未能确认完成，已保留其他书页。请先核对账单，再手动重试。',dumps(usage),now(),time.monotonic()-start,j['id']))
    return True

def password_hash(password,salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()

def create_user(email,password):
    email=email.strip().lower()
    if '@' not in email or len(email)>200 or len(password)<12: raise Problem(400,'邮箱格式不正确，或密码不足 12 位')
    with tx() as c: c.execute('INSERT INTO users VALUES(?,?,?)',(uid(),email,password_hash(password)))

def pdf_bytes(book):
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.cidfonts import UnicodeCIDFont
    from reportlab.lib.utils import ImageReader
    pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
    out=io.BytesIO(); cv=canvas.Canvas(out,pagesize=(450,600)); cv.setTitle(book['title'])
    for i,p in enumerate(json.loads(book['pages'])):
        cv.setFillColorRGB(.98,.97,.94);cv.rect(0,0,450,600,fill=1,stroke=0)
        if p['image']: cv.drawImage(ImageReader(str(DATA/'assets'/(p['image']+'.jpg'))),22,160,width=406,height=418,preserveAspectRatio=True,anchor='c',mask='auto')
        cv.setFillColorRGB(.29,.25,.22)
        size = 17 if len(p['page_text'])<=90 else 11
        cv.setFont('STSong-Light',size)
        text=p['page_text']; lines=[]; line=''
        for ch in text:
            if ch=='\n' or pdfmetrics.stringWidth(line+ch,'STSong-Light',size)>366:
                lines.append(line);line='' if ch=='\n' else ch
            else: line+=ch
        if line: lines.append(line)
        for n,line in enumerate(lines): cv.drawString(42,130-n*(size+5),line)
        cv.setFont('STSong-Light',10);cv.drawCentredString(225,22,f'{i+1} / {len(json.loads(book["pages"]))}  ·  叽咕插画');cv.showPage()
    cv.save();return out.getvalue()

class Handler(BaseHTTPRequestHandler):
    server_version='Jigu'
    def log_message(self,*args): pass
    def send(self,status,data,mime='application/json; charset=utf-8',cookie=None,download=None):
        raw=dumps(data).encode() if mime.startswith('application/json') else data
        self.send_response(status)
        self.send_header('Content-Type',mime);self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store' if self.path.startswith('/api') else 'no-cache')
        self.send_header('X-Content-Type-Options','nosniff');self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Content-Security-Policy',"default-src 'self'; img-src 'self' blob: data:; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if cookie:self.send_header('Set-Cookie',cookie)
        if download:self.send_header('Content-Disposition','attachment; filename="jigu-storybook.pdf"')
        self.end_headers();self.wfile.write(raw)
    def body(self):
        n=int(self.headers.get('Content-Length','0'))
        if n>MAX_BODY:raise Problem(413,'照片太大，请减少照片或压缩后上传')
        if 'application/json' not in self.headers.get('Content-Type',''):raise Problem(415,'请求格式不正确')
        try:return json.loads(self.rfile.read(n))
        except ValueError:raise Problem(400,'请求格式不正确')
    def auth(self,c,write=False):
        cookie=SimpleCookie();cookie.load(self.headers.get('Cookie',''))
        token=cookie.get('jigu_session');token=token.value if token else ''
        row=c.execute('SELECT * FROM sessions WHERE token=? AND expires>?',(hashlib.sha256(token.encode()).hexdigest(),now())).fetchone()
        if not row:raise Problem(401,'请先登录，收好你的小书')
        if write and not hmac.compare_digest(row['csrf'],self.headers.get('X-CSRF-Token','')):raise Problem(403,'页面已过期，请刷新重试')
        return row
    def setup(self):
        super().setup()
        self.connection.settimeout(30)
    def do_GET(self):self.run('GET')
    def do_POST(self):self.run('POST')
    def do_PATCH(self):self.run('PATCH')
    def do_DELETE(self):self.run('DELETE')
    def run(self,method):
        try:self.route(method)
        except Problem as e:self.send(e.status,{'error':e.message})
        except (sqlite3.IntegrityError,ValueError,KeyError,TypeError,IndexError):self.send(400,{'error':'内容格式不正确或操作冲突，请刷新后重试'})
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception:self.send(500,{'error':'暂时没能完成，请稍后重试'})
    def route(self,method):
        path=self.path.split('?')[0];parts=path.strip('/').split('/')
        if method!='GET':
            origin=self.headers.get('Origin')
            allowed=os.environ.get('JIGU_ORIGIN','http://'+self.headers.get('Host',''))
            if origin and origin!=allowed:raise Problem(403,'不允许跨站请求')
        if not path.startswith('/api/'):
            if method!='GET':raise Problem(405,'不支持的操作')
            allowed={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/hero.svg':'hero.svg'}
            if path not in allowed:raise Problem(404,'找不到页面')
            file=ROOT/'static'/allowed[path]
            mime={'html':'text/html; charset=utf-8','js':'text/javascript; charset=utf-8','css':'text/css; charset=utf-8','svg':'image/svg+xml'}[file.suffix[1:]]
            return self.send(200,file.read_bytes(),mime)
        if path=='/api/health':return self.send(200,{'ok':True})
        if path=='/api/login' and method=='POST':
            inp=self.body();email=clean(inp.get('email',''),200).lower();pw=clean(inp.get('password',''),200)
            with tx() as c:
                ip=self.client_address[0]
                c.execute('DELETE FROM auth_attempts WHERE at<?',(now()-900,))
                if c.execute('SELECT COUNT(*) FROM auth_attempts WHERE ip=?',(ip,)).fetchone()[0]>=12:raise Problem(429,'尝试次数较多，请 15 分钟后再试')
                c.execute('INSERT INTO auth_attempts VALUES(?,?)',(ip,now()))
                user=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone()
                expected=user['password'] if user else password_hash('unused-dummy-password')
                valid=hmac.compare_digest(password_hash(pw,expected.split(':')[0]),expected)
            if not user or not valid:raise Problem(401,'邮箱或密码不正确')
            token=secrets.token_urlsafe(32);csrf=uid()
            with tx() as c:
                c.execute('DELETE FROM sessions WHERE expires<?',(now(),))
                c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),user['id'],csrf,now()+86400*7))
            cookie='jigu_session='+token+'; HttpOnly; SameSite=Strict; Path=/; Max-Age=604800'
            if os.environ.get('JIGU_SECURE_COOKIE')=='1':cookie+='; Secure'
            return self.send(200,{'email':email,'csrf':csrf},cookie=cookie)
        with tx() as c:
            session=self.auth(c,method!='GET');user=session['user_id']
            if path=='/api/me':
                u=c.execute('SELECT email FROM users WHERE id=?',(user,)).fetchone()
                return self.send(200,{'email':u['email'],'csrf':session['csrf'],'text_ready':bool(os.environ.get('ARK_TEXT_MODEL')),'painting_ready':bool(os.environ.get('ARK_API_KEY')) and os.environ.get('JIGU_PAID_ENABLED')=='1'})
            if path=='/api/logout' and method=='POST':
                c.execute('DELETE FROM sessions WHERE token=?',(session['token'],));return self.send(200,{},cookie='jigu_session=; HttpOnly; SameSite=Strict; Path=/; Max-Age=0')
            if len(parts)==3 and parts[1]=='assets' and method=='GET':
                aid=parts[2]
                if not c.execute('SELECT 1 FROM assets WHERE id=? AND user_id=?',(aid,user)).fetchone():raise Problem(404,'找不到图片')
                return self.send(200,(DATA/'assets'/(aid+'.jpg')).read_bytes(),'image/jpeg')
            if path=='/api/books' and method=='GET':
                return self.send(200,[pack(c,b) for b in c.execute('SELECT * FROM books WHERE user_id=? ORDER BY created DESC,rowid DESC',(user,))])
            if path=='/api/books' and method=='POST':
                inp=self.body();event=clean(inp.get('event',''),1600)
                if not event:raise Problem(400,'先说说今天发生了什么吧')
                photos=inp.pop('photos',[])
                if not isinstance(photos,list) or not 1<=len(photos)<=6:raise Problem(400,'请选择 1–6 张照片')
                facts={k:clean(inp.get(k,''),1600 if k=='event' else 500) for k in ('event','mood','detail','nickname','constraints')};facts['event']=event
                date=clean(inp.get('event_date',''),10)
                try:datetime.strptime(date,'%Y-%m-%d')
                except ValueError:raise Problem(400,'故事日期不正确')
                book=uid()
                c.execute('INSERT INTO books(id,user_id,title,event_date,input,pages,source,created) VALUES(?,?,?,?,?,?,?,?)',(book,user,'还没起名的小书',date,dumps(facts),'[]','draft',now()))
                for photo in photos:
                    raw=base64.b64decode(photo,validate=True)
                    if len(raw)>6*1024*1024:raise Problem(413,'单张照片请小于 6MB')
                    store_image(c,raw,user,book,'photo')
                return self.send(201,pack(c,owns(c,book,user)))
            if len(parts)>=3 and parts[1]=='books':
                b=owns(c,parts[2],user);tail=parts[3] if len(parts)>3 else ''
                if not tail and method=='GET':return self.send(200,pack(c,b))
                if not tail and method=='DELETE':
                    if c.execute("SELECT 1 FROM jobs WHERE book_id=? AND state='running'",(b['id'],)).fetchone():raise Problem(409,'这一页还在绘制，请完成后再删除')
                    ids=[r[0] for r in c.execute('SELECT id FROM assets WHERE book_id=?',(b['id'],))]
                    c.execute("DELETE FROM charges WHERE id IN (SELECT id FROM jobs WHERE book_id=? AND state='queued')",(b['id'],))
                    c.execute('DELETE FROM books WHERE id=?',(b['id'],))
                    for aid in ids:(DATA/'assets'/(aid+'.jpg')).unlink(missing_ok=True)
                    return self.send(200,{})
                if tail=='organize' and method=='POST':
                    inp=self.body();n=inp.get('count',5)
                    if n not in (5,7,10):raise Problem(400,'请选择 5、7 或 10 页')
                    if json.loads(b['pages']) and c.execute('SELECT 1 FROM jobs WHERE book_id=?',(b['id'],)).fetchone():raise Problem(409,'绘制开始后不能重新拆分故事')
                    # Release write transaction during a network request; update conditionally afterwards.
                    facts=json.loads(b['input']);rev=b['revision'];bid=b['id']
                    c.commit()
                    title,pages,source=fallback(facts,n) if inp.get('structured') else organize(facts,n)
                    c.execute('BEGIN IMMEDIATE')
                    if c.execute('UPDATE books SET title=?,pages=?,source=?,revision=revision+1 WHERE id=? AND revision=?',(title,dumps(pages),source,bid,rev)).rowcount!=1:raise Problem(409,'故事已在其他页面更新，请刷新')
                    return self.send(200,pack(c,owns(c,bid,user)))
                if tail=='content' and method=='PATCH':
                    inp=self.body()
                    if inp.get('revision')!=b['revision']:raise Problem(409,'这本书已更新，请刷新后再修改')
                    if c.execute("SELECT 1 FROM jobs WHERE book_id=? AND state IN ('queued','running')",(b['id'],)).fetchone():raise Problem(409,'绘制时请先保留当前文字')
                    old=json.loads(b['pages']);new=validate_pages(inp.get('pages'),len(old))
                    for i,p in enumerate(new):
                        for k in ('image','candidate','history'):p[k]=old[i].get(k)
                    title=clean(inp.get('title',''),80)
                    facts=json.loads(b['input'])
                    if 'constraints' in inp:facts['constraints']=clean(inp['constraints'],500)
                    if not title:raise Problem(400,'给小书起个名字吧')
                    c.execute('UPDATE books SET title=?,pages=?,input=?,revision=revision+1 WHERE id=?',(title,dumps(new),dumps(facts),b['id']))
                    return self.send(200,pack(c,owns(c,b['id'],user)))
                if tail in ('generate','redraw','retry') and method=='POST':
                    inp=self.body();pages=json.loads(b['pages'])
                    if not pages:raise Problem(400,'请先确认故事内容')
                    reason='';indices=list(range(len(pages)))
                    if tail=='retry':
                        latest={r['page']:r for r in c.execute('SELECT * FROM jobs WHERE book_id=? ORDER BY created,rowid',(b['id'],))}
                        indices=[i for i,j in latest.items() if j['state'] in ('uncertain','failed')]
                        reason='重试未完成页面'
                    if tail=='redraw':
                        i=inp.get('page');reason=inp.get('reason')
                        if type(i)!=int or not 0<=i<len(pages) or reason not in ('宝宝不像','场景不对','换个画面'):raise Problem(400,'请选择这一页的重画原因')
                        indices=[i]
                    enqueue(c,b,user,inp.get('request_key'),indices,reason)
                    return self.send(202,pack(c,owns(c,b['id'],user)))
                if tail=='choose' and method=='POST':
                    inp=self.body();pages=json.loads(b['pages']);i=inp.get('page')
                    if type(i)!=int or not 0<=i<len(pages) or type(inp.get('accept'))!=bool:raise Problem(400,'请选择要保留的画面')
                    p=pages[i]
                    if not p.get('candidate'):raise Problem(409,'没有待确认的新画面')
                    if inp['accept']:
                        p['history'].append(p['image']);p['image']=p['candidate']
                    else:p['history'].append(p['candidate'])
                    p['candidate']=None
                    c.execute('UPDATE books SET pages=?,revision=revision+1 WHERE id=?',(dumps(pages),b['id']))
                    return self.send(200,pack(c,owns(c,b['id'],user)))
                if tail=='save' and method=='POST':
                    if not all(p['image'] for p in json.loads(b['pages'])) or not json.loads(b['pages']):raise Problem(409,'小书画完后就可以收好啦')
                    c.execute('UPDATE books SET saved=1 WHERE id=?',(b['id'],));return self.send(200,{'saved':True})
                if tail=='pdf' and method=='GET':
                    pages=json.loads(b['pages'])
                    if not pages or not all(p['image'] for p in pages):raise Problem(409,'请等所有书页绘制完成后下载')
                    return self.send(200,pdf_bytes(b),'application/pdf',download=True)
        raise Problem(404,'找不到页面')

@contextlib.contextmanager
def worker_lock():
    lock=open(DATA/'worker.lock','a+b')
    try:
        if os.name=='nt':
            import msvcrt
            lock.seek(0);lock.write(b'0');lock.flush();lock.seek(0)
            msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    except OSError:
        lock.close();raise SystemExit('已有绘画进程运行，请勿重复启动或同时恢复任务')
    try:yield
    finally:lock.close()

def recover_interrupted():
    with tx() as c:
        c.execute("UPDATE charges SET state='uncertain' WHERE id IN (SELECT id FROM jobs WHERE state='running')")
        c.execute("UPDATE jobs SET state='uncertain',error='上次服务中断，结果尚未确认。请核对账单后手动重试。',finished=? WHERE state='running'",(now(),))

def main():
    p=argparse.ArgumentParser();p.add_argument('command',choices=['serve','worker','create-user','recover','costs','reset-password']);p.add_argument('--port',type=int,default=4173);p.add_argument('--host',default='127.0.0.1');p.add_argument('--email');p.add_argument('--strictPort',action='store_true',help=argparse.SUPPRESS);a=p.parse_args();init()
    if a.command=='create-user':
        import getpass
        create_user(a.email or input('Email: '),getpass.getpass('Password (12+ characters): '));print('账号已创建')
    elif a.command=='reset-password':
        import getpass
        pw=getpass.getpass('New password (12+ characters): ')
        if len(pw)<12:raise SystemExit('Password too short')
        with tx() as c:
            row=c.execute('SELECT id FROM users WHERE email=?',((a.email or '').strip().lower(),)).fetchone()
            if not row:raise SystemExit('Account not found')
            c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(pw),row['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(row['id'],))
        print('密码已重置，旧会话已失效')
    elif a.command=='costs':
        with contextlib.closing(db()) as c:
            for row in c.execute('SELECT model,kind,state,COUNT(*) AS calls,SUM(reserved) AS reserved_cny FROM charges GROUP BY model,kind,state'): print(dumps(dict(row)))
        print('金额为保守预留/估算；实际费用以火山账单为准。')
    elif a.command=='recover':
        with worker_lock():recover_interrupted()
        print('未完成的调用已标记待核对；未自动重新扣费')
    elif a.command=='worker':
        with worker_lock():
            recover_interrupted()
            print('Private generation worker ready',flush=True)
            while True:
                if not worker_once():time.sleep(1)
    else:
        print(f'Jigu listening on http://{a.host}:{a.port}',flush=True)
        ThreadingHTTPServer((a.host,a.port),Handler).serve_forever()
if __name__=='__main__':main()
