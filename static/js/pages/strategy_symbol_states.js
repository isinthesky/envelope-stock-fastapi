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

const setSymbolStatesOutput = (msg) => {
  const el = document.getElementById('symbol_states_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
};

const renderSymbolStatesTable = (items) => {
  const body = document.getElementById('symbol_states_table_body');
  if (!body) return;

  if (!items || items.length === 0) {
    body.innerHTML = `<tr><td colspan="4" class="placeholder-message" style="border:none;">결과가 없습니다.</td></tr>`;
    return;
  }

  body.innerHTML = items
    .map((item) => {
      return `
      <tr>
        <td>${item.symbol || '-'}</td>
        <td>${item.state || '-'}</td>
        <td>${item.last_close ?? '-'}</td>
        <td>${item.unrealized_pnl_ratio ?? '-'}</td>
      </tr>
    `;
    })
    .join('');
};

const loadSymbolStates = async () => {
  const id = getSelectedStrategyId('symbol_states_output');
  if (!id) return;

  setSymbolStatesOutput('Symbol States 조회 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/symbol-states`);
    const parsed = await readJsonSafely(res);
    setSymbolStatesOutput(parsed.data);
    if (parsed.ok) {
      const list =
        parsed.data?.data?.items ||
        parsed.data?.data?.symbol_states ||
        parsed.data?.data?.states ||
        parsed.data?.data?.symbols ||
        parsed.data?.items ||
        parsed.data?.symbol_states ||
        parsed.data?.states ||
        parsed.data?.symbols ||
        [];
      renderSymbolStatesTable(Array.isArray(list) ? list : []);
    }
  } catch (e) {
    setSymbolStatesOutput(`오류: ${e.message}`);
  }
};

window.loadSymbolStates = loadSymbolStates;

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
