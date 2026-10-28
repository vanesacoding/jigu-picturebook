import test from 'node:test';
import assert from 'node:assert/strict';
import {entitlement,availableBenefits,prepareDelivery,withWatermark} from '../../docs/experience.mjs';
const book=(id='one')=>({id,title:'宝宝的小故事',status:'needs_review',pages:Array.from({length:6},()=>({image:{id:'image'}}))});
test('preview confirmation spends the first experience once, and duplicate confirmation is idempotent',()=>{
 const b=book(),e=entitlement(),r=prepareDelivery(b,e,'first',123);
 assert.equal(b.status,'needs_review');assert.equal(e.firstUsed,false);
 assert.equal(r.book.status,'ready');assert.equal(r.book.deliveredAt,123);assert.equal(r.order.amount,0);assert.equal(r.entitlement.firstUsed,true);
 assert.throws(()=>prepareDelivery(book('two'),r.entitlement,'first'));
 assert.equal(prepareDelivery(r.book,r.entitlement,'first').order,null);
});
test('reading reward requires six simulated days and is issued only once',()=>{
 assert.equal(availableBenefits({readingDays:5})[1].available,false);
 assert.throws(()=>prepareDelivery(book(),{readingDays:5},'reading'));
 const r=prepareDelivery(book(),{readingDays:6},'reading');assert.equal(r.entitlement.readingUsed,true);
 assert.equal(r.entitlement.firstUsed,false);assert.throws(()=>prepareDelivery(book('two'),r.entitlement,'reading'));
});
test('incomplete or unreviewable work never spends a benefit, and preview watermark follows delivery state',()=>{
 assert.throws(()=>prepareDelivery({...book(),status:'generating'},entitlement(),'first'));
 assert.throws(()=>prepareDelivery({...book(),pages:[{}]},entitlement(),'first'));
 assert.equal(withWatermark(book(),{}).watermark,true);
 assert.equal(withWatermark({status:'ready'},{}).watermark,false);
});
