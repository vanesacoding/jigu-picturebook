'use strict';
const crypto=require('node:crypto');
const {service,publicError}=require('./lib/cloud');
exports.main=async event=>{try{const domain=service().domain;if(event.action==='grant')return{ok:true,data:await domain.grant(event.data||{})};const secret=process.env.OPS_TOKEN||'',given=String(event.token||'');if(secret.length<32||secret.length!==given.length||!crypto.timingSafeEqual(Buffer.from(secret),Buffer.from(given)))return{ok:false,error:{code:'FORBIDDEN',message:'拒绝访问'}};if(event.action==='refundStatus')return{ok:true,data:await domain.refreshRefund(event.data||{})};if(event.action==='refund')return{ok:true,data:await domain.requestRefund(event.data||{})};return{ok:false,error:{code:'INPUT',message:'不支持的操作'}}}catch(e){return publicError(e)}};
