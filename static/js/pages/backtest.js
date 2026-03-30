// Backtest page helpers

const buildMultiPayload = (symbols, basePayload) => ({
  symbols,
  start_date: basePayload.start_date,
  end_date: basePayload.end_date,
  strategy_type: basePayload.strategy_type || 'mean_reversion',
  strategy_params: basePayload.strategy_params || null,
  strategy_config: basePayload.strategy_config || { type: 'mean_reversion' },
  backtest_config: basePayload.backtest_config || { initial_capital: 10000000 },
});

const setOutput = (msg) => {
  const out = document.getElementById('backtest_output');
  if (out) out.textContent = msg;
};

const safeParsePayload = () => {
  try {
    const raw = document.getElementById('backtest_json')?.value;
    const payload = parseJson(raw);
    if (!payload || typeof payload !== 'object') {
      throw new Error('백테스트 JSON이 객체 형태가 아닙니다.');
    }
    if (!payload.start_date || !payload.end_date) {
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
    } else if (scanType === 'ma5') {
      filtered = items.filter((x) => x && x.ma5_state === 'BREAKOUT');
    }
  }

  const symbols = filtered.map((x) => x.symbol).filter(Boolean);
  return symbols.slice(0, limit);
};

const runBacktest = () => {
  const payload = safeParsePayload();
  if (!payload) return;
  postJson('/api/v1/backtest/run', payload, 'backtest_output');
};

const runMultiBacktest = () => {
  const payload = safeParsePayload();
  if (!payload) return;
  postJson('/api/v1/backtest/run-multi', payload, 'backtest_output');
};

const runMultiFromSavedScan = (scanType) => {
  const limit = parseInt(document.getElementById('scan_symbol_limit')?.value || '30', 10);
  const topOnly = getFilterTopOnly();
  const base = safeParsePayload();
  if (!base) return;

  const key = scanType === 'gc' ? 'buyStrategy.gcScan' : 'buyStrategy.ma5Scan';
  const items = loadSavedScanItems(key);

  const symbols = pickSymbolsFromScan(items, scanType, limit, topOnly);
  if (!symbols.length) {
    const reason = topOnly
      ? (scanType === 'gc'
          ? '조건(gc_state=OPTIMAL_BUY)을 만족하는 종목이 0개입니다.'
          : '조건(ma5_state=BREAKOUT)을 만족하는 종목이 0개입니다.')
      : '저장된 스캔 결과가 없습니다.';

    const hint = topOnly
      ? '전략 페이지에서 스캔을 다시 돌리거나(조건이 너무 빡셀 수 있음), 또는 필터 체크를 해제하고 다시 시도해줘.'
      : '전략 페이지에서 먼저 스캔을 실행한 뒤 다시 시도해줘.';

    const msg = `실행 불가: ${reason}\n${hint}`;
    alert(msg);
    setOutput(msg);
    return;
  }

  const payload = buildMultiPayload(symbols, base);
  postJson('/api/v1/backtest/run-multi', payload, 'backtest_output');
};

window.runBacktest = runBacktest;
window.runMultiBacktest = runMultiBacktest;
window.runMultiFromSavedScan = runMultiFromSavedScan;
