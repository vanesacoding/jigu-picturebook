'use strict';
const {service}=require('./lib/cloud');
exports.main=async event=>{try{const {domain,pay}=service();const raw=event.isBase64Encoded?Buffer.from(event.body,'base64').toString():event.body;if(typeof raw!=='string')throw Error('invalid body');const transaction=pay.decodeNotification(event.headers||{},raw);await domain.settle(transaction);return{statusCode:200,headers:{'Content-Type':'application/json'},body:JSON.stringify({code:'SUCCESS',message:'成功'})}}catch{return{statusCode:401,headers:{'Content-Type':'application/json'},body:JSON.stringify({code:'FAIL',message:'支付核验未通过'})}}};
