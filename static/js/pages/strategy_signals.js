const {
  readJsonSafely,
  resolveStrategyId,
  validateStrategyId,
  parsePositiveInt,
  escapeHtml,
  persistSelection,
  clearSelection,
} = window.StrategyShared;

let validatedStrategy = null;

const warningEl = () => document.getElementById('strategy_context_warning');

const setWarning = (html) => {
  const el = warningEl();
  if (!el) return;
  if (!html) {
    el.style.display = 'none';
    el.textContent = '';
    return;
  }
  el.style.display = 'block';
  el.innerHTML = html;
};

const updateSelectedStrategyLabel = (strategyOrId) => {
  const el = document.getElementById('selected_strategy_label');
  if (!el) return;

  if (!strategyOrId) {
    el.textContent = '-';
    return;
  }

  if (typeof strategyOrId === 'number') {
    el.textContent = `ID ${strategyOrId}`;
    return;
  }

  const s = strategyOrId;
  const bits = [`ID ${s.id}`];
  if (s.name) bits.push(s.name);
  if (s.status) bits.push(`(${s.status})`);
  el.textContent = bits.join(' ');
};

const setSignalsOutput = (msg) => {
  const el = document.getElementById('signals_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
};

const setSignalsStatisticsOutput = (msg) => {
  const el = document.getElementById('signals_statistics_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
};

const setButtonsDisabled = (disabled) => {
  const b1 = document.getElementById('btn_load_signals');
  const b2 = document.getElementById('btn_load_statistics');
  if (b1) b1.disabled = !!disabled;
  if (b2) b2.disabled = !!disabled;
};

const getStrategyId = () => {
  const raw = document.getElementById('control_strategy_id')?.value;
  return parsePositiveInt(raw);
};

const renderSignalsTable = (items) => {
  const body = document.getElementById('signals_table_body');
  if (!body) return;

  if (!items || items.length === 0) {
    body.innerHTML =
      '<tr><td colspan="6" class="placeholder-message" style="border:none;">결과가 없습니다.</td></tr>';
    return;
  }

  body.innerHTML = items
    .map((item) => {
      const ts = item.signal_at || item.created_at || item.time || item.timestamp || '-';
      return `
      <tr>
        <td>${escapeHtml(ts)}</td>
        <td>${escapeHtml(item.symbol || '-')}</td>
        <td>${escapeHtml(item.signal_type || '-')}</td>
        <td>${escapeHtml(item.signal_status || '-')}</td>
        <td>${escapeHtml(item.signal_price ?? '-')}</td>
        <td>${escapeHtml(item.target_quantity ?? item.executed_quantity ?? '-')}</td>
      </tr>
    `;
    })
    .join('');
};

const loadSignals = async () => {
  const id = getStrategyId();
  if (!id) {
    setSignalsOutput('먼저 Strategy ID를 선택하거나 입력해줘.');
    return;
  }

  const limit = parseInt(document.getElementById('signals_limit')?.value || '50', 10);
  const offset = parseInt(document.getElementById('signals_offset')?.value || '0', 10);

  setSignalsOutput('Signals 조회 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/signals?limit=${limit}&offset=${offset}`);
    const parsed = await readJsonSafely(res);
    setSignalsOutput(parsed.data);
    if (parsed.ok && (parsed.data?.success ?? true)) {
      const list =
        parsed.data?.data?.signals ||
        parsed.data?.data?.items ||
        parsed.data?.signals ||
        parsed.data?.items ||
        [];
      renderSignalsTable(Array.isArray(list) ? list : []);
    }
  } catch (e) {
    setSignalsOutput(`오류: ${e.message}`);
  }
};

const loadSignalStatistics = async () => {
  const id = getStrategyId();
  if (!id) {
    setSignalsStatisticsOutput('먼저 Strategy ID를 선택하거나 입력해줘.');
    return;
  }

  setSignalsStatisticsOutput('Signals statistics 조회 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/signals/statistics`);
    const parsed = await readJsonSafely(res);
    setSignalsStatisticsOutput(parsed.data);
  } catch (e) {
    setSignalsStatisticsOutput(`오류: ${e.message}`);
  }
};

window.loadSignals = loadSignals;
window.loadSignalStatistics = loadSignalStatistics;

document.addEventListener('DOMContentLoaded', async () => {
  const input = document.getElementById('control_strategy_id');
  if (input) {
    input.addEventListener('input', () => {
      updateSelectedStrategyLabel(getStrategyId());
    });
  }

  setButtonsDisabled(true);

  const resolved = resolveStrategyId();
  if (resolved.source === 'query' && !resolved.id) {
    if (input) input.value = '';
    setWarning(
      `strategy_id=${resolved.queryRaw || '(empty)'} 가 유효하지 않습니다. (fail-close) → <a href="/mypage/strategy/manage">/mypage/strategy/manage</a>`
    );
    updateSelectedStrategyLabel(null);
    return;
  }

  if (resolved.id && input) {
    input.value = String(resolved.id);
  }

  const id = resolved.id || getStrategyId();
  if (!id) {
    setWarning(`전략을 선택하세요 → <a href="/mypage/strategy/manage">/mypage/strategy/manage</a>`);
    updateSelectedStrategyLabel(null);
    return;
  }

  setWarning(null);
  const validated = await validateStrategyId(id);
  if (!validated.ok) {
    if (resolved.source === 'storage') {
      clearSelection();
    }
    setWarning(`전략 검증 실패 → <a href="/mypage/strategy/manage">/mypage/strategy/manage</a>`);
    updateSelectedStrategyLabel(null);
    setSignalsOutput(validated.error);
    return;
  }

  validatedStrategy = validated.strategy;
  updateSelectedStrategyLabel(validatedStrategy);
  persistSelection({ id: validatedStrategy.id, account_no: validatedStrategy.account_no });
  setButtonsDisabled(false);
});
