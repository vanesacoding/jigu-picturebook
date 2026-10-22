import {localDate} from './core.mjs';
// shortcut: fixed example art stands in for AI; replace this module with server jobs for launch.
export const ART=['./assets/puddle-walk.jpg','./assets/puddle-look.jpg','./assets/puddle-story.jpg','./assets/puddle-story.jpg','./assets/puddle-hug.jpg'];
export const EVENT='今天下过雨，我带开心去公园。她先蹲下来看水坑里的倒影，然后鼓起勇气，第一次自己跳过了小水坑。她回头喊：“妈妈，我跳过去啦！”我抱了抱她。';
const TEXT=['第一次跳过小水坑','雨停了，开心穿上黄色雨靴，和妈妈一起去公园。','小水坑亮晶晶的。开心蹲下来，发现里面还有一个小小的自己。','“妈妈，看我！”开心轻轻一跳，水花也跟着跳了起来。','妈妈抱住开心。今天的小小勇敢，要好好记下来。'];
export function createStory(input){
 const event=String(input.event||'').trim();if(!event)throw Error('先写下今天发生的一件小事吧');if(event.length>1600)throw Error('故事最多写 1600 字哦');
 const name=String(input.nickname||'宝宝').trim().slice(0,20)||'宝宝';
 const parts=event.match(/[^。！？!?\n]+[。！？!?]?[”」]?/g)||[event],groups=Array.from({length:4},()=>[]);
 const chunks=parts.flatMap(s=>{const out=[];for(let i=0;i<s.length;i+=100)out.push(s.slice(i,i+100));return out;});
 chunks.forEach((s,i)=>groups[Math.min(3,Math.floor(i*4/Math.max(4,chunks.length)))].push(s));
 const title=event===EVENT?TEXT[0]:name+'的成长小故事';
 const texts=event===EVENT?TEXT:[title,...groups.map((g,i)=>g.join('')||['这件小事，值得好好留下。','这是属于'+name+'的一天。','慢慢长大，也慢慢收藏这些瞬间。','今天的故事，就收到这里。'][i])];
 return{title,count:5,demo:true,status:'draft',saved:false,redrawUsed:0,pages:texts.map((text,i)=>({text,art:ART[i],image:null}))};
}
export function complete(book){return{...book,status:'ready',pages:book.pages.map((p,i)=>({...p,art:p.art||ART[i],image:{id:book.id+'-'+i}}))};}
export function imageMap(book){return Object.fromEntries(book.pages.filter(p=>p.image).map((p,i)=>[p.image.id,p.art||ART[i]]));}
export const SAMPLE=complete({...createStory({event:EVENT,nickname:'开心'}),id:'sample',sample:true,saved:true,date:'2026-10-22',input:{event:EVENT,nickname:'开心'},photos:[]});


