const CACHE='jigu-illustration-pwa-v2-editorial';
const ROOT=new URL('./',self.location).href;
const FILES=['./','./index.html','./style.css','./style.css?v=2','./app.mjs','./app.mjs?v=2','./core.mjs','./storage.mjs','./cloud.mjs','./pdf.mjs','./config.js','./manifest.webmanifest','./assets/bird.webp','./assets/home-feature.webp','./assets/sample-page.webp','./assets/icon-192.png','./assets/icon-512.png','./assets/maskable-512.png'];
const ALLOWED=new Set(FILES.map(p=>new URL(p,ROOT).href));
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(FILES))));
self.addEventListener('activate',event=>event.waitUntil((async()=>{for(const key of await caches.keys())if(key.startsWith('jigu-illustration-pwa-')&&key!==CACHE)await caches.delete(key);await self.clients.claim()})()));
self.addEventListener('message',event=>{if(event.data?.type==='SKIP_WAITING')self.skipWaiting()});
// Only the explicit app shell is cached. Never cache cloud responses or private images.
self.addEventListener('fetch',event=>{const req=event.request;if(req.method!=='GET')return;const url=new URL(req.url);if(url.origin!==self.location.origin||!ALLOWED.has(url.href))return;event.respondWith((async()=>{const cache=await caches.open(CACHE);if(req.mode==='navigate'){try{const response=await fetch(req);if(response.ok)await cache.put(req,response.clone());return response}catch{return(await cache.match('./index.html'))||Response.error()}}return(await cache.match(req))||fetch(req)})())});
