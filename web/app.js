/* 叽咕插画 V0 · 前端（无构建步骤，原生 JS） */
'use strict';

const app = document.getElementById('app');
const toastEl = document.getElementById('toast');
const loadingEl = document.getElementById('loading');
const loadingText = document.getElementById('loading-text');

const PAGE_LABELS = ['封面', '故事开始', '发生的事情', '最值得记住的细节', '结尾'];
const STATUS_ZH = {
  pending: '等待中', running: '正在画', done: '画好了', failed: '没画好',
  drafting: '草稿', review: '待确认', generating: '生成中', ready: '已完成', partial: '部分完成',
};

const S = {
  photos: [],
  draft: null,
  book: null,
  page: 0,
  presetId: '',
  pollTimer: null,
  editing: false,
};

/* ---------------- 小工具 ---------------- */
const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
  { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
));

function toast(msg, ms = 2200) {
  toastEl.textContent = msg;
  toastEl.hidden = false;
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { toastEl.hidden = true; }, ms);
}

function busy(on, text) {
  loadingEl.hidden = !on;
  if (text) loadingText.textContent = text;
}

async function req(path, { method = 'GET', body, form } = {}) {
  const opts = { method, headers: {} };
  if (form) {
    opts.body = form;
  } else if (body !== undefined) {
    opts.headers['Content-Type'] = 'application/json';
    opts.body = JSON.stringify(body);
  }
  const res = await fetch(path, opts);
  let data = {};
  try { data = await res.json(); } catch (e) { /* 非 JSON */ }
  if (!res.ok || data.ok === false) {
    throw new Error(data.error || `请求失败（${res.status}）`);
  }
  return data;
}

function fmtDate(s) {
  if (!s) return '';
  return s.slice(0, 10).replace(/-/g, '.');
}

function nav(hash) { location.hash = hash; }
function clearPoll() { if (S.pollTimer) { clearInterval(S.pollTimer); S.pollTimer = null; } }
function rerender() { route(); }

/* ---------------- 路由 ---------------- */
window.addEventListener('hashchange', () => { clearPoll(); route(); });

function route() {
  const hash = location.hash.replace(/^#/, '') || '/';
  const [, head, id] = hash.split('/');
  window.scrollTo(0, 0);
  if (head === 'create') return renderCreate();
  if (head === 'preview') return renderPreview();
  if (head === 'gen' && id) return renderGen(id);
  if (head === 'read' && id) return renderRead(id);
  if (head === 'library') return renderLibrary();
  return renderHome();
}

/* ---------------- 首页 ---------------- */
async function renderHome() {
  app.innerHTML = `
    <div class="home-hero">
      <div class="brand"><span class="dot"></span>叽咕插画</div>
      <h1>把今天的小故事，<br>画下来。</h1>
      <p class="sub">几分钟，做一本属于宝宝的成长小书。</p>
    </div>
    <div class="home-actions">
      <button class="btn" id="start">开始做小书</button>
      <button class="btn ghost" id="lib">我的小书</button>
    </div>
    <div class="section-head"><h2>最近制作</h2><span id="recent-count"></span></div>
    <div id="recent"></div>
    <p class="foot-note">私人使用 · 照片与作品只存在这台设备上<br>不会公开，也不会用于训练</p>
  `;
  document.getElementById('start').onclick = () => { S.photos = []; S.draft = null; nav('/create'); };
  document.getElementById('lib').onclick = () => nav('/library');

  try {
    const { books } = await req('/api/books');
    document.getElementById('recent-count').textContent = books.length ? `共 ${books.length} 本` : '';
    const box = document.getElementById('recent');
    if (!books.length) {
      box.innerHTML = `<div class="empty-state"><div class="big">还没有小书</div>今天的小事，也值得记下来</div>`;
    } else {
      box.innerHTML = `<div class="book-row">${books.slice(0, 8).map((b) => `
        <div class="book-mini" data-id="${esc(b.id)}">
          <div class="book-thumb">${b.cover_url
            ? `<img src="${esc(b.cover_url)}" alt="">`
            : `<span class="empty">未完</span>`}</div>
          <div class="name">${esc(b.title)}</div>
          <div class="date">${fmtDate(b.created_at)}</div>
        </div>`).join('')}</div>`;
      box.querySelectorAll('.book-mini').forEach((el) => {
        el.onclick = () => nav(`/read/${el.dataset.id}`);
      });
    }
  } catch (e) { toast(e.message); }
}

/* ---------------- 创建页 ---------------- */
function renderCreate() {
  const p = S.photos;
  app.innerHTML = `
    ${topbar('做一本小书', '')}
    <div class="field">
      <label>上传宝宝照片</label>
      <div class="photo-grid" id="grid">${photoCells(p)}</div>
      <p class="hint">1–6 张，推荐 2–4 张。人物照和当时的场景照都可以。<br>照片只存在本机，不会公开。</p>
    </div>
    <div class="field">
      <label>今天发生了什么？简单说一说。</label>
      <textarea id="event" rows="4" maxlength="500"
        placeholder="比如：宝宝今天发烧了，不能出门，在家用我的围巾扮演阿拉伯的国王和公主玩。"></textarea>
      <p class="hint required">必填</p>
    </div>
    <div class="field">
      <label>你当时是什么感受？宝宝看起来是什么心情？</label>
      <textarea id="feeling" rows="2" maxlength="200" placeholder="比如：我觉得她好可爱。"></textarea>
      <p class="hint">选填</p>
    </div>
    <div class="field">
      <label>有没有一句话、一个动作，特别想记下来？</label>
      <textarea id="detail" rows="3" maxlength="200"
        placeholder="比如：宝宝说“我是国王先生”，她居然知道国王是先生。"></textarea>
      <p class="hint">选填。衣物、配饰（比如紫色围巾）写在这里，会被固定画进每一页。</p>
    </div>
    <div class="field">
      <label>宝宝称呼</label>
      <input type="text" id="child_name" maxlength="10" placeholder="比如：开心、乐乐、团团">
      <p class="hint">选填，不填就叫「宝宝」</p>
    </div>
    <button class="btn" id="next">下一步：看看故事</button>
    <div style="text-align:center;margin-top:16px">
      <span class="preset-chip" id="preset">▸ 填入示例：《我是国王先生！》</span>
    </div>
    <div style="height:20px"></div>
  `;

  const grid = document.getElementById('grid');
  wirePhotoGrid(grid);

  document.getElementById('next').onclick = async () => {
    const event = document.getElementById('event').value.trim();
    if (!event) { toast('先说说今天发生了什么'); document.getElementById('event').focus(); return; }
    if (!S.photos.length) { toast('先传一张宝宝照片，才能画得像她'); return; }
    busy(true, '正在整理成五页小书……');
    try {
      const data = await req('/api/story/preview', {
        method: 'POST',
        body: {
          event,
          feeling: document.getElementById('feeling').value.trim(),
          detail: document.getElementById('detail').value.trim(),
          child_name: document.getElementById('child_name').value.trim(),
          preset: S.presetId,
        },
      });
      S.draft = data.draft;
      S.draft.event = event;
      S.draft.feeling = document.getElementById('feeling').value.trim();
      S.draft.detail = document.getElementById('detail').value.trim();
      S.draft.child_name = document.getElementById('child_name').value.trim() || '宝宝';
      busy(false);
      nav('/preview');
    } catch (e) { busy(false); toast(e.message); }
  };

  document.getElementById('preset').onclick = async () => {
    try {
      const { preset } = await req('/api/preset/king');
      document.getElementById('event').value = preset.event;
      document.getElementById('feeling').value = preset.feeling;
      document.getElementById('detail').value = preset.detail;
      document.getElementById('child_name').value = preset.child_name;
      S.presetId = preset.id;
      toast('已填入示例，记得上传开心的两张照片');
    } catch (e) { toast(e.message); }
  };
}

function photoCells(photos) {
  const cells = photos.map((ph, i) => `
    <div class="photo-item">
      <img src="${esc(ph.url)}" alt="">
      <button class="del" data-i="${i}" title="删除">×</button>
    </div>`).join('');
  const add = photos.length < 6 ? `
    <div class="photo-add">
      <div><div style="font-size:20px;line-height:1.2">＋</div>添加照片</div>
      <input type="file" accept="image/*" multiple id="file">
    </div>` : '';
  // 占位保持三列网格的视觉整齐
  const pad = photos.length < 2 ? '' : '';
  return cells + add + pad;
}

function wirePhotoGrid(grid) {
  const fileInput = grid.querySelector('#file');
  if (fileInput) {
    fileInput.onchange = async (e) => {
      const files = Array.from(e.target.files || []);
      if (!files.length) return;
      const form = new FormData();
      files.slice(0, 6 - S.photos.length).forEach((f) => form.append('photos', f));
      busy(true, '正在处理照片……');
      try {
        const { photos } = await req('/api/uploads', { method: 'POST', form });
        S.photos.push(...photos);
        busy(false);
        grid.innerHTML = photoCells(S.photos);
        wirePhotoGrid(grid);
      } catch (err) { busy(false); toast(err.message); }
    };
  }
  grid.querySelectorAll('.del').forEach((btn) => {
    btn.onclick = async () => {
      const i = Number(btn.dataset.i);
      const ph = S.photos[i];
      S.photos.splice(i, 1);
      grid.innerHTML = photoCells(S.photos);
      wirePhotoGrid(grid);
      if (ph && ph.id) { try { await req(`/api/uploads/${ph.id}`, { method: 'DELETE' }); } catch (e) { /* 忽略 */ } }
    };
  });
}

/* ---------------- 故事预览 ---------------- */
function renderPreview() {
  if (!S.draft) { nav('/create'); return; }
  const d = S.draft;
  app.innerHTML = `
    ${topbar('看看故事', '<span class="link" id="reroll">重新整理</span>')}
    <div class="draft-head">
      <input type="text" class="draft-title" id="title" value="${esc(d.title)}" maxlength="24">
      <input type="text" class="draft-sub" id="subtitle" value="${esc(d.subtitle)}" maxlength="30">
      <p class="draft-hint">文字和画面描述都能改。改完再画，画出来的才对得上。</p>
    </div>
    <div id="cards">
      ${d.pages.map((p, i) => `
        <div class="page-card card">
          <div class="head">
            <span class="tag">${PAGE_LABELS[i]}</span>
            <span class="no">P${i + 1}</span>
          </div>
          <textarea rows="2" data-text="${i}" maxlength="120">${esc(p.text)}</textarea>
          <details>
            <summary></summary>
            <textarea rows="3" data-scene="${i}" maxlength="160">${esc(p.scene)}</textarea>
          </details>
        </div>`).join('')}
    </div>
    <button class="btn" id="go">确认，开始画</button>
    <p class="hint" style="text-align:center;margin-top:12px">会用你上传的 ${S.photos.length} 张照片作参考，逐页画 5 张插画</p>
    <div style="height:20px"></div>
  `;

  document.getElementById('reroll').onclick = () => { S.presetId = ''; nav('/create'); };

  document.getElementById('go').onclick = async () => {
    const title = document.getElementById('title').value.trim();
    const subtitle = document.getElementById('subtitle').value.trim();
    const pages = d.pages.map((p, i) => ({
      text: app.querySelector(`[data-text="${i}"]`).value.trim(),
      scene: app.querySelector(`[data-scene="${i}"]`).value.trim(),
    }));
    if (pages.some((p) => !p.text)) { toast('每一页都要有文字'); return; }
    busy(true, '正在准备画布……');
    try {
      const created = await req('/api/books', {
        method: 'POST',
        body: {
          title, subtitle,
          child_name: d.child_name,
          event: d.event, feeling: d.feeling, detail: d.detail,
          character: d.character,
          pages,
          photo_ids: S.photos.map((p) => p.id),
        },
      });
      const bookId = created.book.id;
      await req(`/api/books/${bookId}/generate`, { method: 'POST' });
      busy(false);
      nav(`/gen/${bookId}`);
    } catch (e) { busy(false); toast(e.message); }
  };
}

/* ---------------- 生成进度 ---------------- */
async function renderGen(bookId) {
  app.innerHTML = `
    ${topbar('正在画', '')}
    <div style="margin:6px 0 20px">
      <h2 style="font-size:22px;line-height:1.5">一页一页画，<br>大约需要 1 分钟。</h2>
      <p class="sub" style="color:var(--muted);font-size:13.5px;margin-top:8px">可以先去倒杯水，画好了会自己翻到小书。</p>
    </div>
    <div class="gen-list" id="rows"></div>
    <div id="actions"></div>
  `;

  const tick = async () => {
    let book;
    try {
      const data = await req(`/api/books/${bookId}`);
      book = data.book;
    } catch (e) { clearPoll(); toast(e.message); return; }
    S.book = book;

    const rows = book.pages.map((p) => {
      const st = p.status;
      const state = st === 'running' ? `<span class="dots-anim"><span></span><span></span><span></span></span>`
        : (STATUS_ZH[st] || st);
      const thumb = p.image_url ? `<img class="thumb" src="${esc(p.image_url)}" alt="">` : '<div class="thumb"></div>';
      return `<div class="card gen-row ${esc(st)}">
        <div class="idx">${p.idx}</div>
        <div class="label">${PAGE_LABELS[p.idx - 1]}</div>
        <div class="state">${state}</div>
        ${thumb}
      </div>`;
    }).join('');
    document.getElementById('rows').innerHTML = rows;

    const doneCount = book.pages.filter((p) => p.image_url).length;
    const failed = book.pages.filter((p) => p.status === 'failed');
    const finished = !book.generating;

    const actions = [];
    if (doneCount > 0 && (finished || failed.length)) {
      actions.push(`<button class="btn" id="view">先看看画好的 ${doneCount} 页</button>`);
    }
    if (failed.length) {
      actions.push(`<p class="hint" style="text-align:center;margin-top:14px">有 ${failed.length} 页没画好，可以在阅读页逐页重画。</p>`);
    }
    document.getElementById('actions').innerHTML = actions.join('');
    const viewBtn = document.getElementById('view');
    if (viewBtn) viewBtn.onclick = () => nav(`/read/${bookId}`);

    if (finished) {
      clearPoll();
      if (book.status === 'ready') {
        toast('画好了');
        setTimeout(() => { if (location.hash.includes(bookId)) nav(`/read/${bookId}`); }, 700);
      } else if (!doneCount) {
        toast(book.error || '一页都没画成，请检查配置后重试', 4000);
      }
    }
  };

  await tick();
  clearPoll();
  S.pollTimer = setInterval(tick, 1600);
}

/* ---------------- 阅读页 ---------------- */
async function renderRead(bookId) {
  busy(true, '翻开小书……');
  let book;
  try {
    const data = await req(`/api/books/${bookId}`);
    book = data.book;
  } catch (e) { busy(false); toast(e.message); nav('/'); return; }
  busy(false);
  S.book = book;
  S.page = Math.min(S.page, book.pages.length - 1);
  S.editing = false;

  app.innerHTML = `
    ${topbar(esc(book.title), `<span class="link" id="export">存下来</span>`)}
    <div class="reader">
      <div class="book-stage" id="stage"></div>
      <div class="dots" id="dots"></div>
      <div class="reader-bar">
        <button class="nav-btn" id="prev">‹</button>
        <div class="pager"><span id="pager">1 / ${book.pages.length}</span></div>
        <button class="nav-btn" id="next">›</button>
      </div>
      <div class="reader-tools">
        <button class="btn plain" id="edit">改文字</button>
        <button class="btn plain" id="redraw">重画这页</button>
        <button class="btn plain" id="lib">我的小书</button>
      </div>
    </div>
    <div style="height:16px"></div>
  `;

  buildStage(book);
  setPage(S.page);

  document.getElementById('prev').onclick = () => setPage(S.page - 1);
  document.getElementById('next').onclick = () => setPage(S.page + 1);
  document.getElementById('lib').onclick = () => nav('/library');
  document.getElementById('edit').onclick = () => toggleEdit();
  document.getElementById('redraw').onclick = () => openRedrawSheet();
  document.getElementById('export').onclick = async () => {
    if (book.pages.some((p) => !p.image_url)) { toast('还有页面没画好，暂时不能导出'); return; }
    busy(true, '正在排版成书……');
    try {
      const res = await fetch(`/api/books/${bookId}/export`);
      if (!res.ok) {
        let msg = '导出失败';
        try { msg = (await res.json()).error || msg; } catch (e) { /* ignore */ }
        throw new Error(msg);
      }
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `${(book.title || '小书').replace(/[《》]/g, '')}.zip`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(url), 4000);
      busy(false);
      toast('已保存：五页图片 + PDF');
    } catch (e) { busy(false); toast(e.message); }
  };

  wireSwipe();
}

function buildStage(book) {
  const stage = document.getElementById('stage');
  stage.innerHTML = book.pages.map((p, i) => `
    <div class="book-page ${i === 0 ? 'cover' : ''}" data-i="${i}">
      <div class="art">${p.image_url
        ? `<img src="${esc(p.image_url)}" alt="" draggable="false">`
        : `<div class="placeholder">${p.status === 'failed' ? '这一页没画成<br>可以点「重画这页」' : '这一页还在画'}</div>`}</div>
      <div class="words"><p data-words="${i}">${esc(p.text)}</p></div>
      ${i === 0 ? '' : `<div class="pageno">${i}</div>`}
    </div>`).join('');
  stage.querySelectorAll('.book-page').forEach((el, i) => {
    el.style.transform = `translateX(${(i - S.page) * 100}%)`;
    if (Math.abs(i - S.page) > 1) el.style.opacity = '0';
  });
}

function setPage(n) {
  const book = S.book;
  if (!book) return;
  const max = book.pages.length - 1;
  n = Math.max(0, Math.min(max, n));
  if (S.editing) toggleEdit(false);
  S.page = n;
  document.querySelectorAll('.book-page').forEach((el, i) => {
    el.style.transform = `translateX(${(i - n) * 100}%)`;
    el.style.opacity = Math.abs(i - n) > 1 ? '0' : '1';
    el.style.pointerEvents = i === n ? 'auto' : 'none';
  });
  document.getElementById('pager').textContent = `${n + 1} / ${book.pages.length}`;
  const dots = document.getElementById('dots');
  dots.innerHTML = book.pages.map((_, i) => `<i class="${i === n ? 'on' : ''}"></i>`).join('');
  document.getElementById('prev').disabled = n === 0;
  document.getElementById('next').disabled = n === max;
}

function wireSwipe() {
  const stage = document.getElementById('stage');
  let x0 = 0, y0 = 0, tracking = false;
  stage.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1) return;
    x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; tracking = true;
  }, { passive: true });
  stage.addEventListener('touchend', (e) => {
    if (!tracking) return;
    tracking = false;
    const t = e.changedTouches[0];
    const dx = t.clientX - x0;
    const dy = t.clientY - y0;
    if (Math.abs(dx) > 44 && Math.abs(dx) > Math.abs(dy) * 1.4) {
      setPage(S.page + (dx < 0 ? 1 : -1));
    }
  }, { passive: true });
  // 桌面端也支持键盘左右
  document.onkeydown = (e) => {
    if (e.key === 'ArrowRight') setPage(S.page + 1);
    if (e.key === 'ArrowLeft') setPage(S.page - 1);
  };
}

function toggleEdit(force) {
  const book = S.book;
  if (!book) return;
  const want = force === undefined ? !S.editing : force;
  const words = document.querySelector(`[data-words="${S.page}"]`);
  if (!words) return;
  if (want) {
    S.editing = true;
    const cur = book.pages[S.page].text;
    words.outerHTML = `<textarea data-edit="${S.page}" rows="3"
      style="width:100%;font-family:var(--serif);font-size:16px;text-align:center;line-height:1.8;
      border:1px dashed var(--line);border-radius:10px;padding:8px">${esc(cur)}</textarea>`;
    const ta = document.querySelector(`[data-edit="${S.page}"]`);
    ta.focus();
    ta.onblur = async () => {
      const val = ta.value.trim();
      if (!val) { toast('文字不能为空'); toggleEdit(true); return; }
      try {
        await req(`/api/books/${book.id}/pages/${S.page + 1}`, { method: 'PATCH', body: { text: val } });
        book.pages[S.page].text = val;
        S.editing = false;
        buildStage(book);
        setPage(S.page);
        toast('已改好');
      } catch (e) { toast(e.message); }
    };
  } else {
    S.editing = false;
  }
}

function openRedrawSheet() {
  const book = S.book;
  const idx = S.page + 1;
  const mask = document.createElement('div');
  mask.className = 'sheet-mask';
  mask.innerHTML = `
    <div class="sheet">
      <h3>重画第 ${idx} 页</h3>
      <p class="sub">选一个原因，会按这个方向重画，其他页不动。</p>
      <button class="opt" data-f="unlike">宝宝不像<small>加强五官与脸型，眼睛不要画大</small></button>
      <button class="opt" data-f="scene">场景不对<small>只画这一页描述的场景，不加多余东西</small></button>
      <button class="opt" data-f="variation">换个画面<small>换机位和景别，人物不变</small></button>
      <button class="opt" data-f="">直接重画<small>同样的描述再来一次</small></button>
      <div class="cancel">取消</div>
    </div>`;
  document.body.appendChild(mask);
  mask.onclick = (e) => { if (e.target === mask) mask.remove(); };
  mask.querySelector('.cancel').onclick = () => mask.remove();
  mask.querySelectorAll('.opt').forEach((btn) => {
    btn.onclick = async () => {
      mask.remove();
      busy(true, '正在重画这一页，约 15 秒……');
      try {
        const data = await req(`/api/books/${book.id}/pages/${idx}/regenerate`, {
          method: 'POST', body: { feedback: btn.dataset.f || null },
        });
        S.book = data.book;
        buildStage(S.book);
        setPage(S.page);
        busy(false);
        toast('这页重画好了');
      } catch (e) { busy(false); toast(e.message, 3600); }
    };
  });
}

/* ---------------- 我的小书 ---------------- */
async function renderLibrary() {
  app.innerHTML = `${topbar('我的小书', '')}<div class="lib-list" id="list"><div class="empty-state">正在打开……</div></div>`;
  const list = document.getElementById('list');
  try {
    const { books } = await req('/api/books');
    if (!books.length) {
      list.innerHTML = `<div class="empty-state"><div class="big">还没有小书</div>
        <button class="btn small" id="go" style="margin-top:16px">做第一本</button></div>`;
      document.getElementById('go').onclick = () => nav('/create');
      return;
    }
    list.innerHTML = books.map((b) => `
      <div class="card lib-item" data-id="${esc(b.id)}">
        <div class="cover">${b.cover_url ? `<img src="${esc(b.cover_url)}" alt="">` : '未完'}</div>
        <div class="meta">
          <div class="t">${esc(b.title)}</div>
          <div class="d">${fmtDate(b.created_at)} · ${b.n_pages}/5 页 · ${STATUS_ZH[b.status] || b.status}</div>
        </div>
        <button class="del" data-del="${esc(b.id)}" title="删除">✕</button>
      </div>`).join('');
    list.querySelectorAll('.lib-item').forEach((el) => {
      el.onclick = (e) => {
        if (e.target.closest('[data-del]')) return;
        S.page = 0;
        nav(`/read/${el.dataset.id}`);
      };
    });
    list.querySelectorAll('[data-del]').forEach((btn) => {
      btn.onclick = async (e) => {
        e.stopPropagation();
        if (!confirm('删除这本小书？照片和插画会一起删掉，不能恢复。')) return;
        try {
          await req(`/api/books/${btn.dataset.del}`, { method: 'DELETE' });
          toast('已删除');
          renderLibrary();
        } catch (err) { toast(err.message); }
      };
    });
  } catch (e) {
    list.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
  }
}

/* ---------------- 组件 ---------------- */
function topbar(title, right) {
  return `
    <div class="topbar">
      <button class="back" id="back">‹</button>
      <div class="title">${title}</div>
      <div class="spacer"></div>
      ${right || ''}
    </div>`;
}

document.addEventListener('click', (e) => {
  const back = e.target.closest('#back');
  if (!back) return;
  if (history.length > 1) history.back();
  else nav('/');
});

/* 启动 */
route();
