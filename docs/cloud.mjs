// Public PWA uses same-origin authenticated API; model credentials stay on the server.
// No credential is received from, stored in, or sent to the browser.
import {store} from './storage.mjs';
export const configured=true;
const serviceOrigin=window.JIGU_CONFIG?.serviceOrigin||location.origin;
export const remoteHost=serviceOrigin!==location.origin;
export const authMode='chatgpt';
export function signInHref(){return '/signin-with-chatgpt?return_to='+encodeURIComponent(location.pathname+location.search+location.hash)}
export function signOutHref(){return '/signout-with-chatgpt?return_to='+encodeURIComponent('/studio/#/account')}

let worker;
async function request(path,method='GET',data){if(remoteHost)throw Error('请进入在线版后使用云端书架');const r=await fetch('/api'+path,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':'same-origin'},body:data===undefined?undefined:JSON.stringify(data)});const v=await r.json();if(!r.ok)throw Object.assign(Error(v.error||'暂时无法完成'),{code:r.status===401?'LOGIN':'SERVICE'});return v}
function book(b){const latest={};for(const j of b.jobs||[])latest[j.page]=j;const jobs=Object.values(latest),active=jobs.some(j=>['queued','running'].includes(j.state)),failed=jobs.some(j=>['failed','uncertain'].includes(j.state)),ready=b.pages.length&&b.pages.every(p=>p.image);return {...b,remote:true,date:b.event_date,count:b.pages.length||5,createdAt:b.created,status:active?'generating':failed?'failed':ready?'ready':b.pages.length?'confirmed':'draft',redrawUsed:(b.jobs||[]).filter(j=>['宝宝不像','场景不对','换个画面'].includes(j.reason)).length,pages:b.pages.map(p=>({...p,text:p.page_text,scene:p.scene_description,image:p.image?{id:p.image}:null,candidate:p.candidate?{id:p.candidate}:null}))}}
async function resume(id){if(worker)return;worker=id;try{for(;;){const b=await request('/books/'+id);const latest={};for(const j of b.jobs)latest[j.page]=j;const jobs=Object.values(latest);if(jobs.some(j=>j.state==='uncertain'||j.state==='failed')||!jobs.some(j=>j.state==='queued'))break;const r=await fetch('/api/books/'+id+'/work',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':'same-origin'},body:'{}'});if(!r.ok)break;await r.text()}}finally{worker=null}}
export async function session(){if(remoteHost)return null;try{const me=await request('/me');return{user:{id:me.id,email:me.email},service:me}}catch(e){if(e.code==='LOGIN')return null;throw e}}
export async function sendCode(){throw Error('此私有试用版使用网站登录，无需邮箱验证码。请刷新页面重新登录。')}
export async function logout(){location.assign(signOutHref())}
export async function call(action,data={}){const p='/books/'+encodeURIComponent(data.bookId||'');switch(action){
case 'bootstrap':return request('/benefits');
case 'list':return(await request('/books')).map(book);
case 'getBook':{const b=book(await request(p));if(b.status==='generating')resume(b.id).catch(()=>{});return b}
case 'create':return book(await request('/books','POST',{...data,event_date:data.date,photos:[]}));
case 'upload':return request(p+'/photos','POST',data);
case 'organize':return book(await request(p+'/organize','POST',{count:data.count,structured:data.structured}));
case 'saveContent':return book(await request(p+'/content','PATCH',{revision:data.revision,title:data.title,pages:data.pages.map(v=>({page_text:v.text,scene_description:v.scene}))}));
case 'imageUrls':return Object.fromEntries(data.ids.map(id=>[id,'/api/assets/'+encodeURIComponent(id)]));
case 'begin':await request(p+'/generate','POST',{request_key:'book-'+data.bookId+'-revision-'+data.revision});resume(data.bookId).catch(()=>{});return{mode:'generation'};
case 'retry':await request(p+'/retry','POST',{request_key:crypto.randomUUID(),confirmUnknown:data.confirmUnknown===true});resume(data.bookId).catch(()=>{});return{};
case 'redraw':await request(p+'/redraw','POST',{...data,request_key:crypto.randomUUID()});resume(data.bookId).catch(()=>{});return{};
case 'choose':return book(await request(p+'/choose','POST',data));
case 'save':return request(p+'/save','POST',{});
case 'remove':return request(p,'DELETE');
case 'orders':return[];
case 'connection':return request('/connection','POST',{});
default:throw Error('这个操作暂时不可用')}
}

// A deliberate, origin-checked draft handoff avoids moving photos into URLs or public GitHub.
export async function openOnline(book){
 if(!remoteHost){location.assign('/studio/#/home');return}
 const nonce=crypto.randomUUID(),popup=window.open(serviceOrigin+'/studio/#/connect/'+nonce,'_blank');
 if(!popup)throw Error('请允许打开新窗口，再进入在线版');
 const draft=book&&!book.remote&&!book.sample?structuredClone(book):null;
 const photos=draft?await Promise.all(draft.photos.map(p=>store.get('photos',p.id))):[];
 return new Promise((resolve,reject)=>{const timer=setTimeout(()=>{cleanup();reject(Error('在线版没有连接成功，原草稿仍在这台设备。'))},60000);
 function cleanup(){clearTimeout(timer);window.removeEventListener('message',onMessage)}
 function onMessage(e){if(e.source!==popup||e.origin!==serviceOrigin||e.data?.nonce!==nonce)return;
  if(e.data.type==='jigu-ready')popup.postMessage({type:'jigu-draft',nonce,book:draft,photos},serviceOrigin);
  if(e.data.type==='jigu-saved'){cleanup();resolve()}
  if(e.data.type==='jigu-error'){cleanup();reject(Error('草稿没有转入，原草稿仍在本机。'))}
 }
 window.addEventListener('message',onMessage);
 });
}
export async function receiveDraft(nonce){
 const origin='https://vanesacoding.github.io';
 if(remoteHost||!window.opener||!/^[a-f0-9-]{36}$/.test(nonce))throw Error('请从原来的叽咕页面重新进入在线版');
 return new Promise((resolve,reject)=>{let saving=false;
 const announce=()=>window.opener.postMessage({type:'jigu-ready',nonce},origin);
 const pulse=setInterval(announce,500),timer=setTimeout(()=>{cleanup();reject(Error('没有收到草稿，请回原页面重新进入'))},60000);
 function cleanup(){clearInterval(pulse);clearTimeout(timer);window.removeEventListener('message',onMessage)}
 async function onMessage(e){if(saving||e.source!==window.opener||e.origin!==origin||e.data?.nonce!==nonce||e.data.type!=='jigu-draft')return;saving=true;
 try{const {book,photos}=e.data;
 if(!book){cleanup();window.opener.postMessage({type:'jigu-saved',nonce},origin);resolve(null);return}
 if(book.remote||book.sample||typeof book.input?.event!=='string'||JSON.stringify(book).length>50000||!Array.isArray(photos)||photos.length>6||photos.length!==book.photos?.length||photos.some(p=>!p||!(p.blob instanceof Blob)||p.blob.type!=='image/jpeg'||p.blob.size>600000))throw Error('invalid draft');
 const copied=structuredClone(book);copied.id=crypto.randomUUID();delete copied.remoteId;copied.photos=photos.map(p=>({id:crypto.randomUUID()}));
 await store.transaction(['books','photos'],'readwrite',tx=>{tx.objectStore('books').put(copied);photos.forEach((p,i)=>tx.objectStore('photos').put({...p,id:copied.photos[i].id}))});
 cleanup();window.opener.postMessage({type:'jigu-saved',nonce},origin);resolve(copied);
 }catch{cleanup();window.opener.postMessage({type:'jigu-error',nonce},origin);reject(Error('草稿没有转入，原件仍在原页面。'))}}
 window.addEventListener('message',onMessage);announce();
 });
}
