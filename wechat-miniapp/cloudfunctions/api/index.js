'use strict';
const {service,identity,publicError}=require('./lib/cloud');
exports.main=async event=>{try{const user=await identity();return{ok:true,data:await service().domain.api(event.action,user,event.data||{})}}catch(e){return publicError(e)}};
