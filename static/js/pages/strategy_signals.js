const SELECTED_STRATEGY_ID_KEY = 'buyStrategy.selectedStrategyId';

const readJsonSafely = async (res) => {
  try {
    const data = await res.json();
    if (!res.ok) {
      return { ok: false, data: { ...data, status: res.status, success: data?.success ?? false } };
    }
    return { ok: true, data };
  } catch (e) {
    return {
      ok: false,
      data: { success: false, status: res.status, detail: 'JSON 파싱 실패' },
    };
  }
};

const persistSelectedStrategyId = (id) => {
  try {
    if (!id) {
      localStorage.removeItem(SELECTED_STRATEGY_ID_KEY);
      return;
    }
    localStorage.setItem(SELECTED_STRATEGY_ID_KEY, String(id));
  } catch (e) {
    // ignore
  }
};

const loadPersistedSelectedStrategyId = () => {
  try {
    const raw = localStorage.getItem(SELECTED_STRATEGY_ID_KEY);
    if (!raw) return null;
    const id = parseInt(raw, 10);
    return Number.isNaN(id) || id <= 0 ? null : id;
  } catch (e) {
    return null;
  }
};

const updateSelectedStrategyLabel = (id) => {
  const el = document.getElementById('selected_strategy_label');
  if (!el) return;
  el.textContent = id ? `ID ${id}` : '-';
};

const getSelectedStrategyId = (outputElId) => {
  const raw = document.getElementById('control_strategy_id')?.value;
  const id = raw ? parseInt(raw, 10) : NaN;
  if (!id || Number.isNaN(id)) {
    const msg = '먼저 Strategy ID를 선택하거나 입력해줘.';
    if (outputElId) {
      const el = document.getElementById(outputElId);
      if (el) el.textContent = msg;
    } else {
      alert(msg);
    }
    return null;
  }
  return id;
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

const renderSignalsTable = (items) => {
  const body = document.getElementById('signals_table_body');
  if (!body) return;

  if (!items || items.length === 0) {
    body.innerHTML = `<tr><td colspan="6" class="placeholder-message" style="border:none;">결과가 없습니다.</td></tr>`;
    return;
  }

  body.innerHTML = items
    .map((item) => {
      const ts = item.signal_at || item.created_at || item.time || item.timestamp || '-';
      return `
      <tr>
        <td>${ts}</td>
        <td>${item.symbol || '-'}</td>
        <td>${item.signal_type || '-'}</td>
        <td>${item.signal_status || '-'}</td>
        <td>${item.signal_price ?? '-'}</td>
        <td>${item.target_quantity ?? item.executed_quantity ?? '-'}</td>
      </tr>
    `;
    })
    .join('');
};

const loadSignals = async () => {
  const id = getSelectedStrategyId('signals_output');
  if (!id) return;

  const limit = parseInt(document.getElementById('signals_limit')?.value || '50', 10);
  const offset = parseInt(document.getElementById('signals_offset')?.value || '0', 10);

  setSignalsOutput('Signals 조회 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/signals?limit=${limit}&offset=${offset}`);
    const parsed = await readJsonSafely(res);
    setSignalsOutput(parsed.data);
    if (parsed.ok) {
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
  const id = getSelectedStrategyId('signals_statistics_output');
  if (!id) return;

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

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('control_strategy_id');
  const persisted = loadPersistedSelectedStrategyId();
  if (input && persisted) {
    input.value = String(persisted);
  }

  const id = input ? parseInt(input.value || '', 10) : NaN;
  const normalized = !Number.isNaN(id) && id > 0 ? id : null;
  updateSelectedStrategyLabel(normalized);

  if (input) {
    input.addEventListener('input', () => {
      const nextId = parseInt(input.value || '', 10);
      const n = !Number.isNaN(nextId) && nextId > 0 ? nextId : null;
      updateSelectedStrategyLabel(n);
      persistSelectedStrategyId(n);
    });
  }
});
