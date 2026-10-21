'use strict';
const {service,invokedByUser}=require('./lib/cloud');
// Deny client invocations in function security rules. This handler accepts only the deployed timer.
exports.main=async event=>{if(invokedByUser())return{ignored:true};if(event.Type!=='Timer'||event.TriggerName!=='jiguBookQueue')return{ignored:true};const domain=service().domain;const start=Date.now();let processed=0;while(Date.now()-start<40000&&processed<10){const result=await domain.worker();if(!result.processed)return{processed,...result};processed++}return{processed}};
