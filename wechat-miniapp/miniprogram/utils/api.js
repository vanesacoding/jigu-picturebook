const config=require('../config');
async function call(action,data={}){if(!config.envId)throw new Error('开发环境尚未连接，请配置云开发环境后再试');const response=await wx.cloud.callFunction({name:'api',data:{action,data}});const result=response.result;if(!result||!result.ok){const e=new Error(result?.error?.message||'暂时没有完成，请稍后再试');e.code=result?.error?.code;throw e}return result.data}
function error(page,e){page.setData({error:e.message||'网络有些慢，请稍后再试'});}
async function bootstrap(){const b=await call('bootstrap');getApp().globalData.bootstrap=b;return b}
function openBook(book){const route=book.status==='draft'||book.status==='checkout'?'confirm':book.status==='generating'||book.status==='failed'?'generating':'reader';wx.navigateTo({url:'/pages/'+route+'/index?id='+book.id})}
async function images(book,includePhotos=false){const ids=[];book.pages.forEach(p=>{if(p.image)ids.push(p.image.id);if(p.candidate)ids.push(p.candidate.id)});if(includePhotos)ids.push(...book.photos);return ids.length?call('imageUrls',{bookId:book.id,ids:[...new Set(ids)]}):{}}
function modal(title,content,extra={}){return new Promise(resolve=>wx.showModal({title,content,...extra,success:resolve,fail:()=>resolve({confirm:false})}))}
function platform(){const device=wx.getDeviceInfo?wx.getDeviceInfo():wx.getSystemInfoSync();return device.platform}
async function payOrder(orderId){const p=await call('payment',{orderId});if(!p.paid){try{await wx.requestPayment(p.params)}catch(e){if(String(e.errMsg).includes('cancel'))throw new Error('订单已保留，可以稍后继续付款');throw new Error('付款没有完成，请到订单中查看')} }const status=await call('checkPayment',{orderId});if(!status.paid)throw new Error('正在核对付款结果，请稍后在我的订单中查看');return status.bookId}
module.exports={call,error,bootstrap,openBook,images,modal,platform,payOrder};
