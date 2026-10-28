// Browser-only experience. Never represents WeChat identity, payment, or cloud grants.
export const EXPERIENCE_ID='jigu-web-experience-v1';
export function entitlement(value){return {id:EXPERIENCE_ID,firstUsed:false,readingDays:0,readingUsed:false,...value};}
export function availableBenefits(value){const e=entitlement(value);return [{id:'first',label:'首次免费体验',available:!e.firstUsed},{id:'reading',label:'六天共读体验奖励',available:e.readingDays>=6&&!e.readingUsed}];}
export function prepareDelivery(book,value,source,now=Date.now()){
 const e=entitlement(value);
 if(book.status==='ready')return {book,entitlement:e,order:null};
 if(book.status!=='needs_review'||book.pages.some(p=>!p.image))throw Error('请先等预览画好，再确认收书');
 const benefit=availableBenefits(e).find(x=>x.id===source);
 if(!benefit?.available)throw Error('这份体验权益暂时不可用，请回到权益页查看');
 if(source==='first')e.firstUsed=true;else e.readingUsed=true;
 return {entitlement:e,book:{...book,status:'ready',saved:true,deliverySource:source,deliveredAt:now,updatedAt:now},order:{id:'experience-'+book.id,bookId:book.id,title:book.title,source,label:benefit.label,amount:0,status:'delivered',createdAt:now,demo:true}};
}
export function withWatermark(book,page){return {...page,watermark:book.status==='needs_review'};}
