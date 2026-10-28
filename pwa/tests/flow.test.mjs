import {Blob} from 'node:buffer';
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import path from 'node:path';

async function harness(){
 let now=Date.now();class ClockDate extends Date{constructor(...args){super(...(args.length?args:[now]))}static now(){return now}}
 const root=path.resolve(import.meta.dirname,'../../docs'),db={books:new Map(),photos:new Map(),meta:new Map()},nodes=new Map(),events={};
 function element(){return{innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,dataset:{},open:false,querySelector(){return null},append(){},addEventListener(){},setAttribute(){},showModal(){this.open=true},close(){this.open=false}}}
 const node=s=>{if(!nodes.has(s))nodes.set(s,element());return nodes.get(s)};
 const document={hidden:false,createElement:element,querySelector:node,querySelectorAll:s=>s==='[data-page]'?node('pages').items||[]:[],addEventListener(n,fn){(events[n]??=[]).push(fn)}};
 const store={async get(n,k){const v=db[n].get(k);return v?structuredClone(v):undefined},async put(n,v){db[n].set(v.id,structuredClone(v))},async all(n){return[...db[n].values()].map(v=>structuredClone(v))},async remove(n,k){db[n].delete(k)}};
 let interval;
 const context=vm.createContext({console,document,navigator:{},location:{hash:'#/home'},crypto:{randomUUID:()=> 'book-'+crypto.randomUUID()},Date:ClockDate,URL,structuredClone,sessionStorage:{data:new Map(),getItem(k){return this.data.get(k)},setItem(k,v){this.data.set(k,v)}},setTimeout(fn){return 1},clearTimeout(){},setInterval(fn){interval=fn;return 1},clearInterval(){},window:{addEventListener(){},scrollTo(){}},Error,Promise});
 const modules=new Map();
 const storage=new vm.SyntheticModule(['store','compressPhoto','transaction'],function(){this.setExport('store',store);this.setExport('transaction',async(names,mode,fn)=>{const pending=[];let aborted=false;const tx={abort(){aborted=true},objectStore(name){return{get(id){const req={result:structuredClone(db[name].get(id))};pending.push(req);return req},put(v){db[name].set(v.id,structuredClone(v))},delete(id){db[name].delete(id)}}}};fn(tx);for(const req of pending)req.onsuccess?.();if(aborted)throw Error('Transaction aborted');});this.setExport('compressPhoto',async()=>new Blob())},{context});
 const pdf=new vm.SyntheticModule(['downloadPDF'],function(){this.setExport('downloadPDF',async()=>{throw Error('PDF browser rasterization is not covered by VM checks')})},{context});
 modules.set(path.join(root,'storage.mjs'),storage);modules.set(path.join(root,'pdf.mjs'),pdf);
 async function load(file){if(modules.has(file))return modules.get(file);let source=await fs.readFile(file,'utf8');if(file.endsWith('app.mjs'))source+='\nexport {S,actions,render};';const m=new vm.SourceTextModule(source,{context,identifier:file});modules.set(file,m);await m.link((s,from)=>load(path.resolve(path.dirname(from.identifier),s.split('?')[0])));return m;}
 const mod=await load(path.join(root,'app.mjs'));await mod.evaluate();
 return{api:mod.namespace,context,node,db,store,async submit(){for(const fn of events.submit||[])await fn({target:{id:'story-form'},preventDefault(){}})},async render(view,id=''){context.location.hash='#/'+view+(id?'/'+id:'');await mod.namespace.render()},async input(el){for(const fn of events.input||[])await fn({target:el})},async change(el){for(const fn of events.change||[])await fn({target:el})},async tick(){now+=650;await interval()},advance(ms){now+=ms}};
}
test('real page handlers complete example creation, edit, five-page reading and shelf persistence',async()=>{
 const h=await harness(),a=h.api;
 assert.match(h.node('#app').innerHTML,/把今天的小事，画成故事/);
 await a.actions['use-example']();await h.submit();
 assert.match(h.context.location.hash,/#\/confirm\//);
 const id=[...h.db.books.keys()][0];await h.render('confirm',id);
 h.node('#book-title').value='我第一次跳水坑';h.node('pages').items=a.S.book.pages.map(p=>({value:p.text}));
 await a.actions.generate();await h.render('generating',id);
 for(let i=0;i<5;i++)await h.tick();
 assert.equal(h.db.books.get(id).status,'needs_review');await h.render('reader',id);
 a.actions.prev();assert.equal(a.S.current,0);for(let i=0;i<8;i++)a.actions.next();assert.equal(a.S.current,5);a.actions.prev();
 h.node('#page-edit').value='妈妈把今天的小勇敢，记在了心里。';await a.actions['save-page']();
 assert.match(h.db.books.get(id).pages[4].text,/小勇敢/);
 await a.actions['save-book']();assert.match(h.node('#dialog').innerHTML,/首次免费体验/);await a.actions['claim-delivery']({dataset:{source:'first'}});assert.equal(h.db.books.get(id).status,'ready');assert.equal(h.db.meta.get('jigu-web-experience-v1').firstUsed,true);assert.equal(h.db.meta.get('jigu-experience-orders').items.length,1);
 await h.render('library');assert.match(h.node('#app').innerHTML,/我第一次跳水坑/);assert.match(h.node('#app').innerHTML,/已完成/);
 await h.render('account');assert.match(h.node('#app').innerHTML,/叽咕一会/);
 await h.render('home');assert.doesNotMatch(h.node('#app').innerHTML,/叽咕一会/);
});
test('confirmation edits persist and user markup is escaped when reading',async()=>{
 const h=await harness(),a=h.api;await a.actions['use-example']();await h.submit();const id=[...h.db.books.keys()][0];await h.render('confirm',id);
 await h.input({id:'book-title',value:'<img onerror=evil()>',dataset:{}});await a.S.write;
 assert.equal(h.db.books.get(id).title,'<img onerror=evil()>');
 await h.render('confirm',id);assert.match(h.node('#app').innerHTML,/&lt;img onerror=evil\(\)&gt;/);assert.doesNotMatch(h.node('#app').innerHTML,/<img onerror/);
});


test('new miniapp flow uses six pages even when resuming a legacy ten-page draft',async()=>{const h=await harness(),a=h.api;await a.actions['use-example']();await a.actions.plan({dataset:{count:'10'}});a.S.draft.photos=[{id:'real-photo'}];a.S.draft.storyPhotoId='real-photo';await h.store.put('photos',{id:'real-photo',blob:new Blob(['local fixture'],{type:'image/jpeg'})});await h.submit();const id=[...h.db.books.keys()][0],b=h.db.books.get(id);assert.equal(b.count,5);assert.equal(b.amount,390);assert.equal(b.pages.length,6);assert.equal(b.pages.at(-1).photoId,'real-photo');assert.equal(b.pages.at(-1).art,null);});
test('guided questions remain visible and current benefits replace old purchase and brush rules',async()=>{const h=await harness();assert.match(h.node('#app').innerHTML,/今天在哪里，和谁一起/);assert.match(h.node('#app').innerHTML,/发生了哪件小事/);assert.match(h.node('#app').innerHTML,/宝宝有什么反应/);assert.doesNotMatch(h.node('#app').innerHTML,/¥3.9|¥7.9/);await h.render('benefits');assert.match(h.node('#app').innerHTML,/共读满 6 天/);assert.match(h.node('#app').innerHTML,/不同步微信/);});

test('generation resumes into a watermarked preview without spending an entitlement',async()=>{const h=await harness(),a=h.api;await a.actions['use-example']();await h.submit();const id=[...h.db.books.keys()][0];await h.render('confirm',id);h.node('#book-title').value='留下普通的一天';h.node('pages').items=a.S.book.pages.map(p=>({value:p.text}));await a.actions.generate();await h.render('library');assert.equal(h.db.books.get(id).status,'generating');h.advance(4000);await h.render('library');const b=h.db.books.get(id);assert.equal(b.status,'needs_review');assert.equal(b.saved,false);assert.match(h.node('#app').innerHTML,/待确认预览/);await a.actions.filter({dataset:{filter:'saved'}});assert.doesNotMatch(h.node('#app').innerHTML,/留下普通的一天/);});
test('example entry protects existing answers and viewing a sample does not overwrite them',async()=>{const h=await harness(),a=h.api;a.S.draft.input.answers={where:'奶奶家',what:'一起吃饭',reaction:''};await a.actions['use-example']();assert.match(h.node('#dialog').innerHTML,/不会改动/);assert.equal(a.S.draft.input.answers.what,'一起吃饭');a.actions.sample();assert.equal(a.S.draft.input.answers.where,'奶奶家');a.actions['try-example']();assert.equal(a.S.draft.input.answers.what,'一起吃饭');await a.actions['fill-example']();assert.match(a.S.draft.input.answers.what,/小水坑/);});
test('confirmation is a short recap with optional page editing and a selected photo preview',async()=>{const h=await harness(),a=h.api;await a.actions['use-example']();a.S.draft.photos=[{id:'photo'}];a.S.draft.storyPhotoId='photo';await h.store.put('photos',{id:'photo',blob:new Blob(['fixture'],{type:'image/jpeg'})});await h.submit();const id=[...h.db.books.keys()][0];await h.render('confirm',id);const html=h.node('#app').innerHTML;assert.match(html,/<details class="story-review">/);assert.doesNotMatch(html,/<details class="story-review" open/);assert.match(html,/已选作故事尾页的照片/);assert.match(html,/换一张照片/);assert.equal(a.S.book.storyPhotoId,'photo');});
test('inline name and date persist and future dates do not create a book',async()=>{const h=await harness(),a=h.api;await h.input({dataset:{draftField:'nickname'},value:'圆圆'});await h.input({dataset:{draftField:'date'},value:'2025-06-01'});await a.S.write;assert.equal(h.db.meta.get('prototype-composer-v1').input.nickname,'圆圆');assert.equal(h.db.meta.get('prototype-composer-v1').date,'2025-06-01');await a.actions['fill-example']();a.S.draft.date='2999-01-01';await h.submit();assert.equal(h.db.books.size,0);assert.match(h.node('#form-error').textContent,/今天或以前/);});
test('archiving a new story preserves plan and representative photo for resume',async()=>{const h=await harness(),a=h.api;await a.actions['use-example']();a.S.draft.count=10;a.S.draft.storyPhotoId='tail';a.S.draft.photos=[{id:'tail'}];await a.actions.fresh();const archived=[...h.db.books.values()][0];assert.equal(archived.count,10);assert.equal(archived.storyPhotoId,'tail');assert.equal(archived.example,true);});

test('photo tail replacement stays local and preserves redraw allowance',async()=>{const h=await harness(),a=h.api;await a.actions['use-example']();await h.submit();const id=[...h.db.books.keys()][0];const b=h.db.books.get(id);b.status='ready';b.saved=true;b.redrawUsed=1;b.pages=b.pages.map((p,i)=>({...p,image:{id:id+'-'+i}}));await h.store.put('books',b);await h.render('reader',id);a.S.current=b.pages.length-1;await h.change({id:'replace-photo',files:[new Blob(['replacement'],{type:'image/jpeg'})],dataset:{}});const changed=h.db.books.get(id);assert.ok(changed.pages.at(-1).photoId);assert.equal(changed.pages.at(-1).examplePhoto,false);assert.equal(changed.redrawUsed,1);assert.equal(changed.storyPhotoId,changed.pages.at(-1).photoId);assert.ok(h.db.photos.has(changed.storyPhotoId));});
test('one existing confirmation draft appears once and is not duplicated when starting fresh',async()=>{const h=await harness(),a=h.api;await a.actions['use-example']();await h.submit();const id=[...h.db.books.keys()][0];await h.render('library');assert.doesNotMatch(h.node('#app').innerHTML,/class="draft-strip"/);await a.actions.fresh();assert.equal(h.db.books.size,1);assert.equal(h.db.books.get(id).status,'draft');});
