# 叽咕插画 V7 · 小程序界面交付

公开预览使用 docs/，延续首页、书架、我的三个入口。原有 server/、mvp/、web/ 与 wechat-miniapp/ 不在本次改动范围。

本版包含：叽咕一会品牌配色与系统字体、画笔小鸟 Logo、三个引导问题、5/10 页选择和价格说明、文字合入插画、真实照片尾页、共读画笔规则（规划中）。详细口径见 PRODUCT_RULES.md。

接入点：
- docs/demo.mjs：引导答案整理与固定示例图适配；PLANS 为展示价格；appendPhoto 添加真实照片页。
- docs/app.mjs：全部模拟流程；pageURLs 读取当前设备选中的照片。
- docs/pages.mjs：1000×1333 书页合成，文字在画面内部；最多缓存 4 页避免移动端占用过大。
- docs/pdf.mjs：复用书页画布，导出 6 页或 11 页 PDF。
- docs/storage.mjs：延续原 IndexedDB，保留旧数据。
- docs/assets/paint-bird.webp：新画笔小鸟；icon-192/icon-512/maskable-512 为安装图标。
- docs/style.css：奶白 #faf7f1、深棕 #352c28、深色按钮 #38312c、陶土色 #c97853、浅绿 #e7efe1；系统字体，标题 22–23px，正文 13–14px。

AI、真实订单与共读发奖均未接通。页面清楚标注演示不扣费；不把妈妈照片上传到公共仓库。真实版本需接入微信账号、腾讯云私有存储、豆包任务、支付与奖励账本。此次不修改叽咕一会。

已直接执行全部 21 个测试用例，均通过，另外检查重画计次和本地照片 Blob 引用。标准命令为 node --experimental-vm-modules --test pwa/tests/*.test.mjs；当前环境的标准 CLI 调度器不可用，实际采用相同用例直接执行。浏览器渲染与手机验收仍待完成。
