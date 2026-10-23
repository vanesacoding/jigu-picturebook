// shortcut: local demo uses fixed illustration assets. Replace these adapters with server jobs at launch.
export const ART=['./assets/puddle-walk.jpg','./assets/puddle-look.jpg','./assets/puddle-story.jpg','./assets/puddle-story.jpg','./assets/puddle-hug.jpg'];
export const PLANS={5:{price:390,label:'小小故事'},10:{price:790,label:'完整故事'}};
export const EVENT='今天下过雨，我带开心去公园。她先蹲下来看水坑里的倒影，然后鼓起勇气，第一次自己跳过了小水坑。她回头喊：“妈妈，我跳过去啦！”我抱了抱她。';
export const EXAMPLE_ANSWERS={where:'雨后的公园',what:'开心第一次自己跳过了小水坑。',reaction:'她回头喊：“妈妈，我跳过去啦！”我抱了抱她。'};
export function storyInput(answers){const a=answers||{};if(!String(a.where||'').trim()||!String(a.what||'').trim())throw Error('填一下去了哪里、发生了什么小事吧');return[String(a.where).trim()+'。',String(a.what).trim(),String(a.reaction||'').trim()].filter(Boolean).join('');}
export function createStory(input){
 const event=String(input.event||'').trim();if(!event)throw Error('先记下今天的小事吧');if(event.length>1600)throw Error('这段经历有点长，精简到 1600 字以内吧');
 const count=Number(input.count||5);if(!PLANS[count])throw Error('请选择 5 页或 10 页');
 const name=String(input.nickname||'宝宝').trim().slice(0,20)||'宝宝';
 const parts=event.match(/[^。！？!?\n]+[。！？!?]?[”」]?/g)||[event],groups=Array.from({length:count-1},()=>[]);
 const chunks=parts.flatMap(s=>{const out=[];for(let i=0;i<s.length;i+=100)out.push(s.slice(i,i+100));return out});
 chunks.forEach((s,i)=>groups[Math.min(groups.length-1,Math.floor(i*groups.length/Math.max(groups.length,chunks.length)))].push(s));
 const title=input.example?'第一次跳过小水坑':name+'的成长小故事';
 const endings=['今天的小事，想和你一起记住。','慢慢长大，也慢慢发现这个世界。','这一天，因为有你，变得特别。'];
 const texts=[title,...groups.map((g,i)=>g.join('')||endings[i%endings.length])];
 return{title,count,amount:PLANS[count].price,demo:true,status:'draft',saved:false,redrawUsed:0,pages:texts.map((text,i)=>({text,art:ART[i%ART.length],type:'illustration',image:null}))};
}
export function appendPhoto(book,photoId){return{...book,storyPhotoId:photoId||null,pages:[...book.pages.filter(p=>p.type!=='photo'),{type:'photo',text:'故事之外，真实的这一天',photoId:photoId||null,art:photoId?null:ART[2],examplePhoto:!photoId,image:null}]};}
export function complete(book){return{...book,status:'ready',saved:true,pages:book.pages.map((p,i)=>({...p,image:{id:book.id+'-'+i}}))};}
export function imageMap(book){return Object.fromEntries(book.pages.filter(p=>p.image).map(p=>[p.image.id,p.art]));}
export const SAMPLE=complete(appendPhoto({...createStory({event:EVENT,nickname:'开心',example:true}),id:'sample',sample:true,saved:true,date:'2026-10-22',input:{event:EVENT,nickname:'开心',answers:EXAMPLE_ANSWERS},photos:[]},null));

export const GENERATION_MS=3250;
export function generationProgress(book,now=Date.now()){const started=Number(book.generationStartedAt||book.updatedAt||now);return Math.max(0,Math.min(100,Math.floor((now-started)/GENERATION_MS*100)));}
export function bookGroup(book){return book.status==='ready'?'ready':book.status==='generating'?'generating':'draft';}
