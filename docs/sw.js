const CACHE='jigu-illustration-pwa-v9-miniapp-experience-2';
const ROOT=new URL('./',self.location).href;
const FILES=['./','./index.html','./style.css?v=20261029-2','./app.mjs?v=20261029-2','./demo.mjs','./experience.mjs?v=20261029-2','./pages.mjs?v=20261029-2','./core.mjs','./storage.mjs','./pdf.mjs?v=20261029-2','./manifest.webmanifest','./assets/bird.webp','./assets/paint-bird.webp','./assets/puddle-story.jpg','./assets/puddle-walk.jpg','./assets/puddle-look.jpg','./assets/puddle-hug.jpg','./assets/icon-192.png','./assets/icon-512.png','./assets/maskable-512.png'];
const ALLOWED=new Set(FILES.map(p=>new URL(p,ROOT).href));
self.addEventListener('install',event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(FILES)).then(()=>self.skipWaiting())));
self.addEventListener('activate',event=>event.waitUntil((async()=>{for(const key of await caches.keys())if(key.startsWith('jigu-illustration-pwa-')&&key!==CACHE)await caches.delete(key);await self.clients.claim()})()));
self.addEventListener('message',event=>{if(event.data?.type==='SKIP_WAITING')self.skipWaiting()});
// Only public assets enter the cache; baby photos stay in device-local IndexedDB.
self.addEventListener('fetch',event=>{const req=event.request;if(req.method!=='GET')return;const url=new URL(req.url);if(url.origin!==self.location.origin||(!ALLOWED.has(url.href)&&!url.pathname.startsWith(new URL('./assets/icons/',ROOT).pathname)))return;event.respondWith((async()=>{const cache=await caches.open(CACHE);try{const response=await fetch(req);if(response.ok)await cache.put(req,response.clone());return response}catch{return(await cache.match(req))||(req.mode==='navigate'?await cache.match('./index.html'):null)||Response.error()}})())});

