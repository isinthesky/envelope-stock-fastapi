// Backtest page helpers

const buildMultiPayload = (symbols, basePayload) => ({
  symbols,
  start_date: basePayload.start_date,
  end_date: basePayload.end_date,
  strategy_type: basePayload.strategy_type || 'mean_reversion',
  strategy_params: basePayload.strategy_params || null,
  strategy_config: basePayload.strategy_config || { type: 'mean_reversion' },
  backtest_config: buildBacktestConfig(basePayload),
});

const setOutput = (msg) => {
  const out = document.getElementById('backtest_output');
  if (out) out.textContent = msg;
};

const fmtNum = (n) => n != null ? Number(n).toLocaleString('ko-KR') : '-';
const fmtPct = (n) => n != null ? Number(n).toFixed(2) + '%' : '-';
const hasOwn = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);
const escapeHtml = (value) => String(value ?? '')
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#39;');

const formatApiDetail = (detail) => {
  if (Array.isArray(detail)) {
    return detail.map((item) => {
      if (item && typeof item === 'object') {
        const loc = Array.isArray(item.loc) ? item.loc.join('.') : '';
        return `${loc ? `${loc}: ` : ''}${item.msg || JSON.stringify(item)}`;
      }
      return String(item);
    }).join(' / ');
  }
  if (detail && typeof detail === 'object') {
    return detail.message || detail.msg || JSON.stringify(detail);
  }
  return String(detail);
};

const unwrapApiPayload = (payload, status) => {
  if (payload?.success === false) {
    throw new Error(formatApiDetail(payload.detail || payload.message || payload.error || `HTTP ${status}`));
  }
  return payload?.data ?? payload;
};

const requestJsonStrict = async (method, url, body = null) => {
  const options = { method, headers: { 'Content-Type': 'application/json' } };
  if (body !== null && ['POST', 'PATCH', 'DELETE'].includes(method)) {
    options.body = JSON.stringify(body);
  }
  const response = await fetch(url, options);
  const raw = await response.text();
  const payload = raw ? parseJson(raw) : null;
  if (!response.ok) {
    throw new Error(formatApiDetail(payload?.detail || payload?.message || payload?.error || `HTTP ${response.status}`));
  }
  return unwrapApiPayload(payload, response.status);
};

const safeParsePayload = (requireDates = false) => {
  try {
    const raw = document.getElementById('backtest_json')?.value.trim();
    const payload = raw ? parseJson(raw) : {};
    if (!payload || typeof payload !== 'object') {
      throw new Error('백테스트 JSON이 객체 형태가 아닙니다.');
    }
    if (requireDates && (!payload.start_date || !payload.end_date)) {
      throw new Error('start_date / end_date를 입력해줘야 합니다.');
    }
    return payload;
  } catch (e) {
    const msg = `입력 오류: ${e.message}`;
    alert(msg);
    setOutput(msg);
    return null;
  }
};

const parseNumberOrNull = (id) => {
  const raw = document.getElementById(id)?.value;
  if (raw === undefined || raw === null || raw === '') return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
};

const buildBacktestConfig = (payload = {}) => {
  const config = { ...(payload.backtest_config || {}) };
  const executionTiming = document.getElementById('bt_execution_timing')?.value;
  const autoCost = !!document.getElementById('bt_auto_cost')?.checked;
  const costScheduleDate = document.getElementById('bt_cost_schedule_date')?.value;

  if (executionTiming) config.execution_timing = executionTiming;
  if (autoCost) {
    delete config.commission_rate;
    delete config.tax_rate;
    delete config.slippage_rate;
    if (costScheduleDate) {
      config.cost_schedule_date = costScheduleDate;
    } else {
      delete config.cost_schedule_date;
    }
  } else {
    const commissionRate = parseNumberOrNull('bt_commission_rate');
    const taxRate = parseNumberOrNull('bt_tax_rate');
    const slippageRate = parseNumberOrNull('bt_slippage_rate');
    const hasManualCost = commissionRate !== null || taxRate !== null || slippageRate !== null;
    if (commissionRate !== null) config.commission_rate = commissionRate;
    if (taxRate !== null) config.tax_rate = taxRate;
    if (slippageRate !== null) config.slippage_rate = slippageRate;
    if (hasManualCost) delete config.cost_schedule_date;
  }
  return config;
};

const applyFormOverrides = (payload) => {
  const next = { ...payload };
  const symbol = document.getElementById('bt_symbol')?.value.trim();
  const start = document.getElementById('bt_start')?.value;
  const end = document.getElementById('bt_end')?.value;
  if (symbol) next.symbol = symbol;
  if (start) next.start_date = start;
  if (end) next.end_date = end;
  next.backtest_config = buildBacktestConfig(next);
  return next;
};

const requireBacktestDates = (payload) => {
  if (!payload.start_date || !payload.end_date) {
    throw new Error('start_date / end_date를 입력해줘야 합니다.');
  }
};

const normalizedPayloadOrNull = () => {
  const payload = safeParsePayload(false);
  if (!payload) return null;
  try {
    const next = applyFormOverrides(payload);
    requireBacktestDates(next);
    return next;
  } catch (e) {
    const msg = `입력 오류: ${e.message}`;
    alert(msg);
    setOutput(msg);
    return null;
  }
};

const syncTextareaPayload = (payload) => {
  const textarea = document.getElementById('backtest_json');
  if (textarea) textarea.value = JSON.stringify(payload, null, 2);
};

const toggleAdvanced = () => {
  const el = document.getElementById('json_advanced');
  if (!el) return;
  el.style.display = el.style.display === 'none' ? 'block' : 'none';
};

const renderBacktestResult = (data) => {
  const section = document.getElementById('result_section');
  const grid = document.getElementById('result_cards');
  if (!section || !grid) return;
  if (!data || typeof data !== 'object' || Array.isArray(data) || !hasOwn(data, 'total_return')) {
    section.style.display = 'none';
    return;
  }

  const signClass = (n) => (n > 0 ? 'positive' : n < 0 ? 'negative' : '');
  const cards = [
    { label: '총 수익률', value: fmtPct(data.total_return), cls: signClass(data.total_return) },
    { label: '승률', value: fmtPct(data.win_rate), cls: '' },
    { label: 'MDD', value: fmtPct(data.mdd), cls: 'negative' },
    { label: 'Sharpe', value: data.sharpe_ratio != null ? Number(data.sharpe_ratio).toFixed(2) : '-', cls: '' },
    { label: '총 거래', value: fmtNum(data.total_trades), cls: '' },
    { label: '보유일(평균)', value: data.avg_holding_days != null ? Number(data.avg_holding_days).toFixed(1) + '일' : '-', cls: '' },
    { label: '체결 시점', value: data.execution_timing || '-', cls: '' },
  ];

  grid.innerHTML = cards.map(c => `
    <div class="result-card">
      <div class="label">${c.label}</div>
      <div class="value ${c.cls}">${c.value}</div>
    </div>
  `).join('');
  section.style.display = 'block';
};

const loadSavedScanItems = (key) => {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    const data = parsed.data || parsed; // backward compat
    return Array.isArray(data) ? data : [];
  } catch (e) {
    return [];
  }
};

const getFilterTopOnly = () => {
  const el = document.getElementById('filter_top_only');
  return !!(el && el.checked);
};

const pickSymbolsFromScan = (items, scanType, limit, topOnly) => {
  let filtered = items;

  // NOTE: fallback 구현하지 않음. 조건에 맞는 종목이 없으면 그냥 에러 처리.
  if (topOnly) {
    if (scanType === 'gc') {
      filtered = items.filter((x) => x && x.gc_state === 'OPTIMAL_BUY');
    }
  }

  const symbols = filtered.map((x) => x.symbol).filter(Boolean);
  return symbols.slice(0, limit);
};

const runBacktest = () => {
  const payload = normalizedPayloadOrNull();
  if (!payload) return;
  syncTextareaPayload(payload);
  requestJsonStrict('POST', '/api/v1/backtest/run', payload)
    .then((result) => {
      renderBacktestResult(result);
      setOutput(JSON.stringify(result, null, 2));
    })
    .catch((error) => {
      renderBacktestResult(null);
      setOutput(`백테스트 실패: ${error.message}`);
    });
};

const runMultiBacktest = () => {
  const payload = normalizedPayloadOrNull();
  if (!payload) return;
  syncTextareaPayload(payload);
  renderBacktestResult(null);
  requestJsonStrict('POST', '/api/v1/backtest/run-multi', payload)
    .then((result) => setOutput(JSON.stringify(result, null, 2)))
    .catch((error) => setOutput(`다중 백테스트 실패: ${error.message}`));
};

const runBacktestUI = () => {
  const next = normalizedPayloadOrNull();
  if (!next) return;
  syncTextareaPayload(next);
  requestJsonStrict('POST', '/api/v1/backtest/run', next)
    .then((result) => {
      renderBacktestResult(result);
      setOutput(JSON.stringify(result, null, 2));
    })
    .catch((error) => {
      renderBacktestResult(null);
      setOutput(`백테스트 실패: ${error.message}`);
    });
};

const appendBacktestConfigParams = (params, config) => {
  if (!config || typeof config !== 'object') return;
  [
    'execution_timing',
    'cost_schedule_date',
    'commission_rate',
    'tax_rate',
    'slippage_rate',
  ].forEach((key) => {
    if (hasOwn(config, key) && config[key] !== null && config[key] !== '') {
      params.set(key, String(config[key]));
    }
  });
};

const runMultiFromSavedScan = (scanType) => {
  const limit = parseInt(document.getElementById('scan_symbol_limit')?.value || '30', 10);
  const topOnly = getFilterTopOnly();
  const base = normalizedPayloadOrNull();
  if (!base) return;
  const normalizedBase = applyFormOverrides(base);
  syncTextareaPayload(normalizedBase);

  const key = 'buyStrategy.gcScan';
  const items = loadSavedScanItems(key);

  const symbols = pickSymbolsFromScan(items, scanType, limit, topOnly);
  if (!symbols.length) {
    const reason = topOnly
      ? '조건(gc_state=OPTIMAL_BUY)을 만족하는 종목이 0개입니다.'
      : '저장된 스캔 결과가 없습니다.';

    const hint = topOnly
      ? '전략 페이지에서 스캔을 다시 돌리거나(조건이 너무 빡셀 수 있음), 또는 필터 체크를 해제하고 다시 시도해줘.'
      : '전략 페이지에서 먼저 스캔을 실행한 뒤 다시 시도해줘.';

    const msg = `실행 불가: ${reason}\n${hint}`;
    alert(msg);
    setOutput(msg);
    return;
  }

  const payload = buildMultiPayload(symbols, normalizedBase);
  renderBacktestResult(null);
  requestJsonStrict('POST', '/api/v1/backtest/run-multi', payload)
    .then((result) => setOutput(JSON.stringify(result, null, 2)))
    .catch((error) => setOutput(`스캔 다중 백테스트 실패: ${error.message}`));
};

const buildUniversePayload = () => {
  const startDate = document.getElementById('universe_start_date')?.value;
  const endDate = document.getElementById('universe_end_date')?.value;
  if (!startDate || !endDate) {
    throw new Error('유니버스 백테스트 기간을 입력해주세요.');
  }
  return {
    market: document.getElementById('universe_market_filter')?.value || null,
    eligible_only: !!document.getElementById('universe_eligible_only')?.checked,
    limit: parseInt(document.getElementById('universe_limit')?.value || '20', 10),
    start_date: `${startDate}T00:00:00`,
    end_date: `${endDate}T00:00:00`,
    portfolio: !!document.getElementById('universe_portfolio')?.checked,
    max_positions: parseInt(document.getElementById('universe_max_positions')?.value || '5', 10),
    backtest_config: buildBacktestConfig({}),
  };
};

const renderUniverseMetricCards = (summary, title) => {
  if (!summary) return '';
  const label = summary.label || summary.summary_type || '';
  return `
    <div class="panel">
      <h3>${escapeHtml(title)}</h3>
      <div class="config-note">${escapeHtml(label)}</div>
      <div class="universe-summary-grid">
        <div class="universe-summary-card"><div class="label">수익률</div><div class="value ${summary.average_return >= 0 ? 'positive' : 'negative'}">${fmtPct(summary.average_return)}</div></div>
        <div class="universe-summary-card"><div class="label">승률</div><div class="value">${fmtPct(summary.average_win_rate)}</div></div>
        <div class="universe-summary-card"><div class="label">MDD</div><div class="value negative">${fmtPct(summary.average_mdd)}</div></div>
        <div class="universe-summary-card"><div class="label">보유일</div><div class="value">${summary.average_holding_days != null ? Number(summary.average_holding_days).toFixed(1) + '일' : '-'}</div></div>
        <div class="universe-summary-card"><div class="label">거래 수</div><div class="value">${fmtNum(summary.total_trades)}</div></div>
      </div>
    </div>
  `;
};

const renderPortfolioSummary = (summary) => {
  if (!summary) return '';
  return `
    <div class="panel">
      <h3>포트폴리오 수익률</h3>
      <div class="config-note">${escapeHtml(summary.simulation_type || 'shared_capital_portfolio')} · max ${fmtNum(summary.max_positions)} positions</div>
      <div class="universe-summary-grid">
        <div class="universe-summary-card"><div class="label">총 수익률</div><div class="value ${summary.total_return >= 0 ? 'positive' : 'negative'}">${fmtPct(summary.total_return)}</div></div>
        <div class="universe-summary-card"><div class="label">벤치마크 초과</div><div class="value ${summary.excess_return >= 0 ? 'positive' : 'negative'}">${fmtPct(summary.excess_return)}</div></div>
        <div class="universe-summary-card"><div class="label">MDD</div><div class="value negative">${fmtPct(summary.mdd)}</div></div>
        <div class="universe-summary-card"><div class="label">진입 / 제외</div><div class="value">${fmtNum(summary.entered_positions)} / ${fmtNum(summary.rejected_candidates)}</div></div>
        <div class="universe-summary-card"><div class="label">거래 수</div><div class="value">${fmtNum(summary.total_trades)}</div></div>
      </div>
    </div>
  `;
};

const renderUniverseBacktest = (data) => {
  const container = document.getElementById('universe_result_section');
  if (!container) return;
  if (!data || !data.diagnostic_summary) {
    container.innerHTML = '<div class="panel">유니버스 백테스트 결과가 없습니다.</div>';
    return;
  }
  const comparison = data.config_summary?.comparison_results || [];
  const comparisonRows = comparison.map((item) => `
    <tr>
      <td>${escapeHtml(item.label || item.key || '-')}</td>
      <td>${escapeHtml(item.summary_type || 'non_portfolio_diagnostic')}</td>
      <td>${item.diagnostic_average_return != null ? Number(item.diagnostic_average_return).toFixed(2) + '%' : '-'}</td>
      <td>${item.diagnostic_average_win_rate != null ? Number(item.diagnostic_average_win_rate).toFixed(2) + '%' : '-'}</td>
      <td>${item.average_holding_days != null ? Number(item.average_holding_days).toFixed(1) + '일' : '-'}</td>
    </tr>
  `).join('');
  container.innerHTML = `
    ${renderPortfolioSummary(data.portfolio_summary)}
    ${renderUniverseMetricCards(data.diagnostic_summary, '진단용 개별 종목 평균')}
    ${comparisonRows ? `
      <div class="panel">
        <h3>비교군 진단 요약</h3>
        <table class="multi-table">
          <thead><tr><th>Label</th><th>Type</th><th>평균 수익률</th><th>평균 승률</th><th>보유일</th></tr></thead>
          <tbody>${comparisonRows}</tbody>
        </table>
      </div>
    ` : ''}
  `;
};

const runUniverseBacktest = async (method = 'POST') => {
  const container = document.getElementById('universe_result_section');
  renderBacktestResult(null);
  try {
    const payload = buildUniversePayload();
    if (container) {
      container.innerHTML = '<div class="panel">유니버스 백테스트 실행 중...</div>';
    }
    const result = method === 'GET'
      ? await (() => {
          const params = new URLSearchParams({
            eligible_only: String(payload.eligible_only),
            limit: String(payload.limit),
            start_date: payload.start_date.slice(0, 10),
            end_date: payload.end_date.slice(0, 10),
            portfolio: String(payload.portfolio),
            max_positions: String(payload.max_positions),
          });
          if (payload.market) params.set('market', payload.market);
          appendBacktestConfigParams(params, payload.backtest_config);
          return requestJsonStrict('GET', `/api/v1/backtest/universe/golden-cross?${params.toString()}`);
        })()
      : await requestJsonStrict('POST', '/api/v1/backtest/run-universe-golden-cross', payload);
    renderUniverseBacktest(result);
    setOutput(JSON.stringify(result, null, 2));
  } catch (e) {
    const message = `유니버스 백테스트 실패: ${e.message}`;
    if (container) container.innerHTML = `<div class="panel negative">${escapeHtml(message)}</div>`;
    setOutput(message);
  }
};

const bindBacktestControls = () => {
  const autoCost = document.getElementById('bt_auto_cost');
  const manualFields = document.getElementById('bt_manual_cost_fields');
  const syncCostMode = () => {
    if (manualFields) manualFields.style.display = autoCost?.checked ? 'none' : 'flex';
  };
  autoCost?.addEventListener('change', syncCostMode);
  syncCostMode();
};

window.runBacktest = runBacktest;
window.runBacktestUI = runBacktestUI;
window.runMultiBacktest = runMultiBacktest;
window.runMultiFromSavedScan = runMultiFromSavedScan;
window.runUniverseBacktest = runUniverseBacktest;
window.toggleAdvanced = toggleAdvanced;

document.addEventListener('DOMContentLoaded', bindBacktestControls);
