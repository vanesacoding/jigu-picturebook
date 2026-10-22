import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
import path from 'node:path';

async function harness(){
 const root=path.resolve('docs'),db={books:new Map(),photos:new Map(),meta:new Map()},nodes=new Map(),events={};
 function element(){return{innerHTML:'',textContent:'',value:'',hidden:false,disabled:false,dataset:{},open:false,addEventListener(){},setAttribute(){},showModal(){this.open=true},close(){this.open=false}}}
 const node=s=>{if(!nodes.has(s))nodes.set(s,element());return nodes.get(s)};
 const document={hidden:false,querySelector:node,querySelectorAll:s=>s==='[data-page]'?node('pages').items||[]:[],addEventListener(n,fn){(events[n]??=[]).push(fn)}};
 const store={async get(n,k){const v=db[n].get(k);return v?structuredClone(v):undefined},async put(n,v){db[n].set(v.id,structuredClone(v))},async all(n){return[...db[n].values()].map(v=>structuredClone(v))},async remove(n,k){db[n].delete(k)}};
 let interval;
 const context=vm.createContext({console,document,navigator:{},location:{hash:'#/home'},crypto:{randomUUID:()=> 'book-'+crypto.randomUUID()},Date,URL,structuredClone,sessionStorage:{data:new Map(),getItem(k){return this.data.get(k)},setItem(k,v){this.data.set(k,v)}},setTimeout(fn){return 1},clearTimeout(){},setInterval(fn){interval=fn;return 1},clearInterval(){},window:{addEventListener(){},scrollTo(){}},Error,Promise});
 const modules=new Map();
 const storage=new vm.SyntheticModule(['store','compressPhoto'],function(){this.setExport('store',store);this.setExport('compressPhoto',async()=>new Blob())},{context});
 const pdf=new vm.SyntheticModule(['downloadPDF'],function(){this.setExport('downloadPDF',async()=>{throw Error('PDF browser rasterization is not covered by VM checks')})},{context});
 modules.set(path.join(root,'storage.mjs'),storage);modules.set(path.join(root,'pdf.mjs'),pdf);
 async function load(file){if(modules.has(file))return modules.get(file);let source=await fs.readFile(file,'utf8');if(file.endsWith('app.mjs'))source+='\nexport {S,actions,render};';const m=new vm.SourceTextModule(source,{context,identifier:file});modules.set(file,m);await m.link((s,from)=>load(path.resolve(path.dirname(from.identifier),s)));return m;}
 const mod=await load(path.join(root,'app.mjs'));await mod.evaluate();
 return{api:mod.namespace,context,node,db,store,async submit(){for(const fn of events.submit||[])await fn({target:{id:'story-form'},preventDefault(){}})},async render(view,id=''){context.location.hash='#/'+view+(id?'/'+id:'');await mod.namespace.render()},async input(el){for(const fn of events.input||[])await fn({target:el})},async tick(){await interval()}};
}
test('real page handlers complete example creation, edit, five-page reading and shelf persistence',async()=>{
 const h=await harness(),a=h.api;
 assert.match(h.node('#app').innerHTML,/今天，有什么小事想留下/);
 await a.actions['use-example']();await h.submit();
 assert.match(h.context.location.hash,/#\/confirm\//);
 const id=[...h.db.books.keys()][0];await h.render('confirm',id);
 h.node('#book-title').value='我第一次跳水坑';h.node('pages').items=a.S.book.pages.map(p=>({value:p.text}));
 await a.actions.generate();await h.render('generating',id);
 for(let i=0;i<5;i++)await h.tick();
 assert.equal(h.db.books.get(id).status,'ready');await h.render('reader',id);
 a.actions.prev();assert.equal(a.S.current,0);for(let i=0;i<8;i++)a.actions.next();assert.equal(a.S.current,4);
 h.node('#page-edit').value='妈妈把今天的小勇敢，记在了心里。';await a.actions['save-page']();
 assert.match(h.db.books.get(id).pages[4].text,/小勇敢/);
 await a.actions['save-book']();assert.equal(h.db.books.get(id).saved,true);
 await h.render('library');assert.match(h.node('#app').innerHTML,/我第一次跳水坑/);assert.match(h.node('#app').innerHTML,/已收好/);
 await h.render('account');assert.match(h.node('#app').innerHTML,/叽咕一会/);
 await h.render('home');assert.doesNotMatch(h.node('#app').innerHTML,/叽咕一会/);
});
test('confirmation edits persist and user markup is escaped when reading',async()=>{
 const h=await harness(),a=h.api;await a.actions['use-example']();await h.submit();const id=[...h.db.books.keys()][0];await h.render('confirm',id);
 await h.input({id:'book-title',value:'<img onerror=evil()>',dataset:{}});await a.S.write;
 assert.equal(h.db.books.get(id).title,'<img onerror=evil()>');
 await h.render('confirm',id);assert.match(h.node('#app').innerHTML,/&lt;img onerror=evil\(\)&gt;/);assert.doesNotMatch(h.node('#app').innerHTML,/<img onerror/);
});

