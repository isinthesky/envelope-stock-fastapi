// 보유 종목 매도 점검 — 입력(localStorage) → sell-signal API 대입 → 단계/손익 요약
'use strict';

const LS_KEY = 'holdings.sellCheck.v1';
const CONCURRENCY = 3;

const esc = (v) => String(v ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
const wonFmt = (n) => (n === null || n === undefined || Number.isNaN(Number(n)))
  ? '-' : Number(n).toLocaleString('ko-KR');
const pctFmt = (r) => (r === null || r === undefined || Number.isNaN(Number(r)))
  ? '-' : `${(Number(r) * 100).toFixed(2)}%`;

// ---------- 행 관리 ----------
function rowHtml(sym = '', avg = '', qty = '', high = '') {
  return `<tr>
    <td class="col-sym"><input type="text" class="h-sym" placeholder="예: 069500" value="${esc(sym)}" /></td>
    <td class="col-num"><input type="number" class="h-avg" placeholder="평단가" min="0" step="1" value="${esc(avg)}" /></td>
    <td class="col-num"><input type="number" class="h-qty" placeholder="선택" min="0" step="1" value="${esc(qty)}" /></td>
    <td class="col-num"><input type="number" class="h-high" placeholder="매수 후 최고가" min="0" step="1" value="${esc(high)}" /></td>
    <td class="col-del"><button class="btn-row-del" type="button" title="행 삭제" onclick="removeHoldingRow(this)">✕</button></td>
  </tr>`;
}

function addHoldingRow(sym = '', avg = '', qty = '', high = '') {
  const body = document.getElementById('holdings_input_body');
  body.insertAdjacentHTML('beforeend', rowHtml(sym, avg, qty, high));
  bindPersist();
}

function removeHoldingRow(btn) {
  const tr = btn.closest('tr');
  if (tr) tr.remove();
  const body = document.getElementById('holdings_input_body');
  if (!body.querySelector('tr')) addHoldingRow();
  persist();
}

function readRows() {
  const rows = [];
  document.querySelectorAll('#holdings_input_body tr').forEach((tr) => {
    const symbol = (tr.querySelector('.h-sym')?.value || '').trim();
    const avg = (tr.querySelector('.h-avg')?.value || '').trim();
    const qty = (tr.querySelector('.h-qty')?.value || '').trim();
    const high = (tr.querySelector('.h-high')?.value || '').trim();
    rows.push({ symbol, avg, qty, high });
  });
  return rows;
}

function persist() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      rows: readRows(),
      stoch: document.getElementById('stoch_threshold')?.value,
      rsi: document.getElementById('rsi_threshold')?.value,
    }));
  } catch (e) { /* ignore quota */ }
}

let _persistBound = false;
function bindPersist() {
  if (_persistBound) return;
  document.getElementById('holdings_input_body').addEventListener('input', persist);
  _persistBound = true;
}

function clearHoldings() {
  document.getElementById('holdings_input_body').innerHTML = '';
  try { localStorage.removeItem(LS_KEY); } catch (e) {}
  addHoldingRow();
  document.getElementById('pf_summary').innerHTML = '<div class="placeholder-message">매도 점검을 실행하면 요약이 표시됩니다.</div>';
  document.getElementById('hold_result_wrap').innerHTML = '<div class="placeholder-message">아직 실행하지 않았습니다.</div>';
}

// ---------- 실행 ----------
// 최고가 대비 손절(-15%)의 "고점"은 매수 이후 최고가여야 한다. 최고가를 보내지 않으면
// 서버는 max(현재가, 평단가)를 고점으로 쓰므로 손절이 평단가 기준 -15%로 바뀐다.
async function fetchSellSignal(symbol, avg, stoch, rsi, high) {
  let url = `/api/v1/strategies/sell-signal/${encodeURIComponent(symbol)}?stoch_overbought=${stoch}&rsi_overbought=${rsi}`;
  if (avg) url += `&entry_price=${encodeURIComponent(avg)}`;
  if (high) url += `&highest_price=${encodeURIComponent(high)}`;
  try {
    const res = await fetch(url);
    const json = await res.json();
    if (json && json.success && json.data) return { ok: true, data: json.data };
    return { ok: false, error: (json && (json.error || json.detail)) || `HTTP ${res.status}` };
  } catch (e) {
    return { ok: false, error: e.message };
  }
}

// 동시성 제한 풀
async function runPool(items, worker, limit) {
  const results = new Array(items.length);
  let idx = 0;
  async function next() {
    while (idx < items.length) {
      const cur = idx++;
      results[cur] = await worker(items[cur], cur);
    }
  }
  await Promise.all(Array.from({ length: Math.min(limit, items.length) }, next));
  return results;
}

async function runHoldingsCheck() {
  persist();
  const stoch = document.getElementById('stoch_threshold').value || 70;
  const rsi = document.getElementById('rsi_threshold').value || 70;
  const holdings = readRows().filter((r) => r.symbol);

  const status = document.getElementById('hold_status');
  const runBtn = document.getElementById('run_btn');

  if (!holdings.length) {
    status.textContent = '종목코드를 1개 이상 입력하세요.';
    return;
  }

  runBtn.disabled = true;
  status.textContent = `분석 중... (0/${holdings.length})`;
  let done = 0;

  const results = await runPool(holdings, async (h) => {
    const r = await fetchSellSignal(h.symbol, h.avg, stoch, rsi, h.high);
    done += 1;
    status.textContent = `분석 중... (${done}/${holdings.length})`;
    return { input: h, ...r };
  }, CONCURRENCY);

  runBtn.disabled = false;
  status.textContent = `완료 (${results.filter((r) => r.ok).length}/${holdings.length} 성공)`;
  renderResults(results);
  renderSummary(results);
}

// ---------- 렌더 ----------
const STAGE_ORDER = { HOLD: 0, REDUCE_1: 1, REDUCE_2: 2, EXIT_ALL: 3 };
const STAGE_NAMES = { HOLD: '보유 유지', REDUCE_1: '1차 비중 축소', REDUCE_2: '2차 비중 축소', EXIT_ALL: '전량 청산' };

// 다른 화면(매도 전략/공개 분석)과 동일하게 API의 최종 단계(final_stage)를 표시한다.
// sell_stage는 규칙 단계(점수/익절/트레일링/손절 반영 전)라 최종 판단과 다를 수 있다.
function displayStage(d) {
  return d.final_stage || d.sell_stage || 'HOLD';
}

function displayStageName(d) {
  if (d.final_stage) return STAGE_NAMES[d.final_stage] || d.final_stage;
  return d.sell_stage_name || STAGE_NAMES[d.sell_stage] || '보유 유지';
}

function reduceRatioText(d) {
  const useFinal = d.final_stage && d.final_ratio_min !== null && d.final_ratio_min !== undefined;
  const a = useFinal ? d.final_ratio_min : d.sell_ratio_min;
  const b = useFinal ? d.final_ratio_max : d.sell_ratio_max;
  if (a === null || a === undefined) return '-';
  const lo = Math.round(Number(a) * 100), hi = Math.round(Number(b ?? a) * 100);
  if (lo === 0 && hi === 0) return '-';
  return lo === hi ? `${lo}%` : `${lo}~${hi}%`;
}

function renderResults(results) {
  const wrap = document.getElementById('hold_result_wrap');
  // 매도 시급도(단계) 높은 순 → 손익 낮은 순
  const sorted = [...results].sort((x, y) => {
    const sx = x.ok ? (STAGE_ORDER[displayStage(x.data)] ?? -1) : -2;
    const sy = y.ok ? (STAGE_ORDER[displayStage(y.data)] ?? -1) : -2;
    return sy - sx;
  });

  const rows = sorted.map((r) => {
    if (!r.ok) {
      return `<tr>
        <td>${esc(r.input.symbol)}</td>
        <td colspan="8" style="text-align:left; color:#dc2626;">분석 실패: ${esc(r.error)}</td>
      </tr>`;
    }
    const d = r.data;
    const qty = r.input.qty ? Number(r.input.qty) : null;
    const entry = r.input.avg ? Number(r.input.avg) : (d.entry_price != null ? Number(d.entry_price) : null);
    const cur = Number(d.current_price);
    const pnl = (qty && entry) ? (cur - entry) * qty : null;
    const stg = displayStage(d);
    const profitCls = d.profit_ratio > 0 ? 'pl-pos' : (d.profit_ratio < 0 ? 'pl-neg' : '');
    const pnlCls = (pnl > 0) ? 'pl-pos' : (pnl < 0 ? 'pl-neg' : '');
    const reasons = Array.isArray(d.sell_reasons) && d.sell_reasons.length
      ? d.sell_reasons.slice(0, 3).map(esc).join(' · ')
      : esc(d.sell_phase_action || '-');
    const flags = [];
    if (d.is_stop_loss_triggered) flags.push('🛑손절');
    if (d.is_take_profit_triggered) flags.push('🎯익절');
    const inputHigh = r.input.high ? Number(r.input.high) : null;
    const usedHigh = d.highest_price != null ? Number(d.highest_price) : null;
    // 입력한 최고가가 서버 응답 고점보다 크면 서버가 최고가를 반영하지 않은 것(평단가 기준 손절).
    const highIgnored = inputHigh && (usedHigh === null || usedHigh < inputHigh);
    if (highIgnored) flags.push('⚠️최고가 미반영');
    return `<tr>
      <td><strong>${esc(d.symbol)}</strong>${d.name ? `<br><span style="font-size:11px;color:#94a3b8;">${esc(d.name)}</span>` : ''}</td>
      <td><span class="stg stg-${esc(stg)}">${esc(displayStageName(d))}</span>${flags.length ? `<br><span style="font-size:11px;">${flags.join(' ')}</span>` : ''}</td>
      <td>${wonFmt(cur)}</td>
      <td>${entry != null ? wonFmt(entry) : '-'}</td>
      <td>${d.drawdown_from_high != null ? `-${pctFmt(d.drawdown_from_high)}` : '-'}</td>
      <td class="${profitCls}">${pctFmt(d.profit_ratio)}</td>
      <td class="${pnlCls}">${pnl != null ? wonFmt(Math.round(pnl)) : '-'}</td>
      <td>${reduceRatioText(d)}</td>
      <td class="reasons">${reasons}</td>
    </tr>`;
  }).join('');

  wrap.innerHTML = `<table class="hold-result-table">
    <thead><tr>
      <th>종목</th><th>매도 단계</th><th>현재가</th><th>평단가</th>
      <th>최고가 대비</th><th>수익률</th><th>평가손익</th><th>축소 비중</th><th>근거</th>
    </tr></thead>
    <tbody>${rows}</tbody>
  </table>`;
}

function renderSummary(results) {
  const ok = results.filter((r) => r.ok);
  let totalVal = 0, totalCost = 0, hasQty = false;
  let exitCnt = 0, reduceCnt = 0, holdCnt = 0;

  ok.forEach((r) => {
    const d = r.data;
    const qty = r.input.qty ? Number(r.input.qty) : null;
    const entry = r.input.avg ? Number(r.input.avg) : (d.entry_price != null ? Number(d.entry_price) : null);
    const cur = Number(d.current_price);
    if (qty && entry) { hasQty = true; totalVal += cur * qty; totalCost += entry * qty; }
    const stg = displayStage(d);
    if (stg === 'EXIT_ALL') exitCnt++;
    else if (stg === 'REDUCE_1' || stg === 'REDUCE_2') reduceCnt++;
    else holdCnt++;
  });

  const pnl = totalVal - totalCost;
  const pnlRatio = totalCost > 0 ? pnl / totalCost : null;
  const pnlCls = pnl > 0 ? 'pos' : (pnl < 0 ? 'neg' : '');

  const cards = [
    `<div class="pf-card"><div class="label">점검 종목</div><div class="value">${ok.length}${results.length > ok.length ? ` <span style="font-size:12px;color:#dc2626;">(+${results.length - ok.length} 실패)</span>` : ''}</div></div>`,
    `<div class="pf-card"><div class="label">청산 / 축소 / 유지</div><div class="value" style="font-size:15px;"><span style="color:#991b1b;">${exitCnt}</span> / <span style="color:#9a3412;">${reduceCnt}</span> / <span style="color:#166534;">${holdCnt}</span></div></div>`,
  ];
  if (hasQty) {
    cards.push(`<div class="pf-card"><div class="label">총 평가금액</div><div class="value">${wonFmt(Math.round(totalVal))}원</div></div>`);
    cards.push(`<div class="pf-card"><div class="label">총 평가손익</div><div class="value ${pnlCls}">${pnl >= 0 ? '+' : ''}${wonFmt(Math.round(pnl))}원 <span style="font-size:12px;">(${pctFmt(pnlRatio)})</span></div></div>`);
  } else {
    cards.push(`<div class="pf-card"><div class="label">평가금액/손익</div><div class="value" style="font-size:13px; color:#94a3b8;">수량 입력 시 계산</div></div>`);
  }
  document.getElementById('pf_summary').innerHTML = cards.join('');
}

// ---------- init ----------
(function init() {
  const body = document.getElementById('holdings_input_body');
  bindPersist();
  let saved = null;
  try { saved = JSON.parse(localStorage.getItem(LS_KEY)); } catch (e) {}
  if (saved && Array.isArray(saved.rows) && saved.rows.length) {
    saved.rows.forEach((r) => addHoldingRow(r.symbol, r.avg, r.qty, r.high || ''));
    if (saved.stoch) document.getElementById('stoch_threshold').value = saved.stoch;
    if (saved.rsi) document.getElementById('rsi_threshold').value = saved.rsi;
  } else {
    addHoldingRow();
  }
  document.getElementById('stoch_threshold').addEventListener('input', persist);
  document.getElementById('rsi_threshold').addEventListener('input', persist);
})();
