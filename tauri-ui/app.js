'use strict';

const $ = (id) => document.getElementById(id);
const state = { range: 'all', cache: {} };

function fmtInt(n) {
  return Number(n || 0).toLocaleString();
}

function fmtTokens(n) {
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'k';
  return String(n || 0);
}

function fmtDuration(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  if (h >= 100) return h + 'h';
  if (h > 0) return h + 'h ' + m + 'm';
  if (m > 0) return m + 'm';
  return sec + 's';
}

function svg(tag, attrs, children) {
  const el = document.createElementNS('http://www.w3.org/2000/svg', tag);
  if (attrs) for (const k in attrs) el.setAttribute(k, attrs[k]);
  if (children) for (const c of children) el.appendChild(c);
  return el;
}

async function invokeStats(refresh) {
  const api = window.__TAURI__ && window.__TAURI__.core;
  if (!api || !api.invoke) {
    throw new Error('Tauri 桥接未就绪');
  }
  return api.invoke('get_stats', { range: state.range, refresh });
}

const tip = $('tip');
function showTip(e, text) {
  tip.textContent = text;
  tip.classList.add('show');
  tip.style.left = (e.clientX + 12) + 'px';
  tip.style.top = (e.clientY + 12) + 'px';
}

function hideTip() {
  tip.classList.remove('show');
}

function renderCards(t) {
  const cards = [
    { k: '有效 token', v: fmtTokens(t.effective_tokens), title: fmtInt(t.effective_tokens) + ' = 非缓存输入 + 输出' },
    { k: '非缓存输入', v: fmtTokens(t.non_cached_input_tokens), title: fmtInt(t.non_cached_input_tokens) },
    { k: '输出 token', v: fmtTokens(t.output_tokens), title: fmtInt(t.output_tokens) },
    { k: '缓存输入', v: fmtTokens(t.cached_input_tokens), title: fmtInt(t.cached_input_tokens) },
    { k: '原始总 token', v: fmtTokens(t.raw_total_tokens || t.total_tokens), title: fmtInt(t.raw_total_tokens || t.total_tokens) },
    { k: '推理输出', v: fmtTokens(t.reasoning_output_tokens), title: fmtInt(t.reasoning_output_tokens) + '，已包含在输出 token 中' },
    { k: '会话数', v: fmtInt(t.session_count) },
    { k: '活跃天数', v: fmtInt(t.active_days) },
    { k: '总时长', v: fmtDuration(t.duration_s) },
    { k: '常用模型', v: t.top_model || '-' },
  ];
  const root = $('cards');
  root.innerHTML = '';
  for (const c of cards) {
    const el = document.createElement('div');
    el.className = 'card';
    if (c.title) el.title = c.title;
    el.innerHTML = `<div class="k">${c.k}</div><div class="v">${c.v}</div>`;
    root.appendChild(el);
  }
}

function renderTrend(trend) {
  const host = $('trend');
  host.innerHTML = '';
  window.__lastTrend = trend;
  if (!trend.length) {
    host.innerHTML = '<div class="sub">当前范围没有数据。</div>';
    return;
  }

  const W = Math.max(320, host.clientWidth || 880);
  const H = 160;
  const padL = 32, padR = 8, padT = 10, padB = 22;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const max = Math.max(1, ...trend.map(d => d.effective_tokens ?? d.tokens ?? 0));
  const bw = innerW / trend.length;
  const visBw = Math.min(bw, 28);
  const s = svg('svg', { viewBox: `0 0 ${W} ${H}`, width: '100%', height: H });

  for (let i = 0; i <= 2; i++) {
    const y = padT + innerH * (1 - i / 2);
    s.appendChild(svg('line', {
      x1: padL, x2: W - padR, y1: y, y2: y,
      stroke: 'currentColor', 'stroke-opacity': 0.08
    }));
    const t = svg('text', { x: padL - 4, y: y + 3, 'text-anchor': 'end', class: 'axis' });
    t.textContent = fmtTokens(Math.round(max * i / 2));
    s.appendChild(t);
  }

  trend.forEach((d, i) => {
    const tokens = d.effective_tokens ?? d.tokens ?? 0;
    const h = tokens > 0 ? Math.max(1, innerH * (tokens / max)) : 0;
    const slotX = padL + i * bw;
    const x = slotX + (bw - visBw) / 2;
    const y = padT + innerH - h;
    const r = svg('rect', {
      x: x + 0.5, y, width: Math.max(1, visBw - 1), height: h, class: 'trend-bar',
      rx: 1, ry: 1,
    });
    r.addEventListener('mousemove', (e) => showTip(e, `${d.date} · ${fmtInt(tokens)} 有效 token · ${d.sessions} 个会话`));
    r.addEventListener('mouseleave', hideTip);
    s.appendChild(r);
  });

  const pick = [0, Math.floor(trend.length / 2), trend.length - 1];
  const seen = new Set();
  pick.forEach(i => {
    if (seen.has(i) || i < 0 || i >= trend.length) return;
    seen.add(i);
    const t = svg('text', {
      x: padL + i * bw + bw / 2, y: H - 6, 'text-anchor': 'middle', class: 'axis'
    });
    t.textContent = trend[i].date.slice(5);
    s.appendChild(t);
  });

  host.appendChild(s);
}

function parseISODateUTC(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function addDaysUTC(dt, days) {
  const d = new Date(dt);
  d.setUTCDate(d.getUTCDate() + days);
  return d;
}

function isoDateUTC(dt) {
  const pad2 = (n) => n < 10 ? '0' + n : String(n);
  return dt.getUTCFullYear() + '-' + pad2(dt.getUTCMonth() + 1) + '-' + pad2(dt.getUTCDate());
}

function renderHeatmap(hm) {
  const host = $('heatmap');
  host.innerHTML = '';
  const cell = 12, gap = 3;
  const weeks = hm.weeks;
  const W = weeks * (cell + gap) + 28;
  const H = 7 * (cell + gap) + 18;
  const dayMap = hm.effective_tokens_by_day || hm.tokens_by_day || {};
  const values = Object.values(dayMap);
  const max = values.length ? Math.max(...values) : 0;

  function bucket(v) {
    if (!v || max <= 0) return 0;
    const r = v / max;
    if (r <= 0.05) return 1;
    if (r <= 0.20) return 2;
    if (r <= 0.50) return 3;
    return 4;
  }

  const s = svg('svg', { viewBox: `0 0 ${W} ${H}`, width: W, height: H });
  const g = svg('g', { transform: 'translate(0, 14)', class: 'heatmap-grid' });
  s.appendChild(g);

  const start = parseISODateUTC(hm.start);
  const end = parseISODateUTC(hm.end);
  const monthLabels = [];
  let lastMonth = -1;

  for (let w = 0; w < weeks; w++) {
    for (let row = 0; row < 7; row++) {
      const d = addDaysUTC(start, w * 7 + row);
      if (d > end) break;
      const iso = isoDateUTC(d);
      const v = dayMap[iso] || 0;
      const rect = svg('rect', {
        x: w * (cell + gap), y: row * (cell + gap),
        width: cell, height: cell, rx: 2, ry: 2, fill: `var(--grid-${bucket(v)})`
      });
      rect.addEventListener('mousemove', (e) => showTip(e, `${iso} · ${fmtInt(v)} 有效 token`));
      rect.addEventListener('mouseleave', hideTip);
      g.appendChild(rect);

      if (d.getUTCMonth() !== lastMonth) {
        monthLabels.push({ w, m: d.getUTCMonth() });
        lastMonth = d.getUTCMonth();
      }
    }
  }

  const months = ['1月','2月','3月','4月','5月','6月','7月','8月','9月','10月','11月','12月'];
  for (const ml of monthLabels) {
    const t = svg('text', { x: ml.w * (cell + gap), y: 10, class: 'axis' });
    t.textContent = months[ml.m];
    s.appendChild(t);
  }

  host.appendChild(s);
}

function renderFooter(d) {
  const lines = [`codex_home: ${d.codex_home || '(unknown)'}`];
  if (!d.sessions_dir_exists) {
    lines.push(`<span class="err">找不到 sessions 目录：${d.sessions_dir}</span>`);
  } else {
    lines.push(`sessions_dir: ${d.sessions_dir}`);
  }
  if (d.timezone) lines.push(`tz: ${d.timezone}`);
  $('footer').innerHTML = lines.join(' · ');
}

function renderDashboard(d) {
  renderCards(d.totals);
  renderTrend(d.trend);
  renderHeatmap(d.heatmap);
  renderFooter(d);
  const modelStr = d.totals.top_model ? ` · ${d.totals.top_model}` : '';
  $('sub').textContent = `${d.totals.session_count} 个会话${modelStr}`;
}

async function load() {
  $('sub').textContent = '加载中...';
  try {
    const cached = state.cache[state.range];
    if (cached) {
      renderDashboard(cached);
      return;
    }
    const d = await invokeStats(false);
    state.cache[state.range] = d;
    renderDashboard(d);
  } catch (e) {
    $('sub').innerHTML = `<span class="err">加载失败：${e.message || e}</span>`;
  }
}

async function refresh() {
  state.cache = {};
  $('sub').textContent = '刷新中...';
  try {
    const d = await invokeStats(true);
    state.cache[state.range] = d;
    renderDashboard(d);
  } catch (e) {
    $('sub').innerHTML = `<span class="err">刷新失败：${e.message || e}</span>`;
  }
}

function bind() {
  document.querySelectorAll('#tabs button').forEach(b => {
    b.addEventListener('click', () => {
      if (b.classList.contains('active')) return;
      document.querySelectorAll('#tabs button').forEach(x => x.classList.remove('active'));
      b.classList.add('active');
      state.range = b.dataset.range;
      load();
    });
  });
  $('refresh').addEventListener('click', refresh);
  window.addEventListener('resize', () => {
    if (window.__lastTrend) renderTrend(window.__lastTrend);
  });
}

bind();
load();
