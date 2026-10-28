const cache=new Map();
export function linesFor(ctx,text,width){const lines=[];for(const para of String(text||'').split('\n')){let line='';for(const ch of para){if(line&&ctx.measureText(line+ch).width>width){lines.push(line);line=ch}else line+=ch}lines.push(line)}return lines;}
export async function composePage(page,url){
 if(!url)throw Error('这页的照片没有找到，请返回上传区域重新选择');
 const key=url+'|'+page.type+'|'+page.text+'|'+!!page.examplePhoto+'|'+!!page.watermark;if(cache.has(key))return cache.get(key);
 const img=new Image();img.crossOrigin='anonymous';await new Promise((resolve,reject)=>{img.onload=resolve;img.onerror=()=>reject(Error('画面暂时无法打开，请重新试试'));img.src=url});
 const canvas=document.createElement('canvas');canvas.width=1000;canvas.height=1333;const ctx=canvas.getContext('2d');if(!ctx)throw Error('当前浏览器暂不支持绘本排版');
 ctx.fillStyle='#faf7f1';ctx.fillRect(0,0,1000,1333);
 const photo=page.type==='photo',area=photo?{x:55,y:90,w:890,h:1040}:{x:0,y:0,w:1000,h:1333};
 const scale=photo?Math.min(area.w/img.naturalWidth,area.h/img.naturalHeight):Math.max(area.w/img.naturalWidth,area.h/img.naturalHeight);
 const w=img.naturalWidth*scale,h=img.naturalHeight*scale;ctx.save();ctx.beginPath();ctx.rect(area.x,area.y,area.w,area.h);ctx.clip();ctx.drawImage(img,area.x+(area.w-w)/2,area.y+(area.h-h)/2,w,h);ctx.restore();
 const text=page.examplePhoto?'照片尾页示意 · 创建后换成你选的照片':page.text;
 let size=photo?30:40,lines;const boxHeight=photo?110:290;
 do{ctx.font=(photo?'400 ':'500 ')+size+'px -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",sans-serif';lines=linesFor(ctx,text,800);if(lines.length*size*1.6<=boxHeight)break;size-=2}while(size>=16);
 const y=photo?1160:560;if(photo){ctx.fillStyle='#faf7f1';ctx.fillRect(0,1145,1000,188);}
 ctx.fillStyle='#352c28';ctx.textAlign='center';ctx.textBaseline='middle';const lh=size*1.6,start=y+(boxHeight-lines.length*lh)/2+lh/2;lines.forEach((line,i)=>{if(!photo){ctx.save();ctx.shadowColor='rgba(255,250,235,.95)';ctx.shadowBlur=9;ctx.lineJoin='round';ctx.lineWidth=8;ctx.strokeStyle='rgba(255,250,235,.9)';ctx.strokeText(line,500,start+i*lh);ctx.restore();}ctx.fillText(line,500,start+i*lh)});
 if(page.watermark){ctx.save();ctx.translate(500,666);ctx.rotate(-Math.PI/6);ctx.fillStyle='rgba(71,51,44,.23)';ctx.font='500 54px sans-serif';ctx.textAlign='center';for(let y=-1000;y<1300;y+=280)for(let x=-1000;x<1300;x+=430)ctx.fillText('叽咕·预览',x,y);ctx.restore();}
 if(cache.size>=4)cache.delete(cache.keys().next().value);cache.set(key,canvas);return canvas;
}
