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

const setStrategyDetailOutput = (msg) => {
  const el = document.getElementById('strategy_detail_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
};

const updateSelectedStrategyLabel = (id) => {
  const el = document.getElementById('selected_strategy_label');
  if (!el) return;
  el.textContent = id ? `ID ${id}` : '-';
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

const setSelectedStrategyId = (id) => {
  const input = document.getElementById('control_strategy_id');
  if (input) input.value = id ? String(id) : '';
  updateSelectedStrategyLabel(id);
  persistSelectedStrategyId(id);
};

const getSelectedStrategyId = () => {
  const raw = document.getElementById('control_strategy_id')?.value;
  const id = raw ? parseInt(raw, 10) : NaN;
  if (!id || Number.isNaN(id)) return null;
  return id;
};

const parseSymbols = (raw) => {
  if (!raw) return [];
  return raw.split(',').map((s) => s.trim()).filter(Boolean);
};

const getStrategyFromResponse = (payload) => {
  if (!payload) return null;
  if (payload.data?.strategy) return payload.data.strategy;
  if (payload.data?.id) return payload.data;
  if (payload.strategy) return payload.strategy;
  if (payload.id) return payload;
  return null;
};

function renderStrategyList(strategies) {
  const body = document.getElementById('strategy_list_table_body');
  if (!body) return;

  if (!strategies || !strategies.length) {
    body.innerHTML = `<tr><td colspan="6" class="placeholder-message" style="border:none;">전략이 없습니다.</td></tr>`;
    return;
  }

  body.innerHTML = strategies
    .map((s) => {
      const symbols = Array.isArray(s.symbols) ? s.symbols.join(', ') : s.symbols || '';
      return `
      <tr onclick="selectStrategy(${s.id})">
        <td>${s.id}</td>
        <td>${s.name || '-'}</td>
        <td>${s.strategy_type || '-'}</td>
        <td>${s.status || '-'}</td>
        <td style="max-width: 360px; overflow:hidden; text-overflow: ellipsis; white-space: nowrap;">${symbols}</td>
        <td>
          <button class="secondary" onclick="event.stopPropagation(); selectStrategy(${s.id})">Select</button>
          <button class="secondary" onclick="event.stopPropagation(); goOperate(${s.id})">Operate</button>
          <button class="secondary" onclick="event.stopPropagation(); goEdit(${s.id})">Edit</button>
          <button class="secondary" onclick="event.stopPropagation(); goSymbolStates(${s.id})">States</button>
          <button class="secondary" onclick="event.stopPropagation(); goSignals(${s.id})">Signals</button>
          <button onclick="event.stopPropagation(); deleteStrategy(${s.id})" style="background:#fecaca;color:#991b1b;">Delete</button>
        </td>
      </tr>
    `;
    })
    .join('');
}

async function loadStrategies() {
  setStrategyDetailOutput('전략 목록 로딩 중...');
  try {
    const res = await fetch('/api/v1/strategies');
    const parsed = await readJsonSafely(res);
    if (parsed.ok && parsed.data?.success && parsed.data?.data) {
      renderStrategyList(parsed.data.data.strategies || []);
      setStrategyDetailOutput('(목록 로드 완료)');
      return;
    }
    setStrategyDetailOutput(parsed.data);
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
}

async function selectStrategy(id) {
  setSelectedStrategyId(id);

  setStrategyDetailOutput(`전략 ${id} 상세 로딩 중...`);
  try {
    const res = await fetch(`/api/v1/strategies/${id}`);
    const parsed = await readJsonSafely(res);
    setStrategyDetailOutput(parsed.data);

    if (parsed.ok) {
      getStrategyFromResponse(parsed.data);
    }
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
}

async function loadSelectedStrategyDetail() {
  const id = getSelectedStrategyId();
  if (!id) {
    setStrategyDetailOutput('먼저 Strategy ID를 선택하거나 입력해줘.');
    return;
  }
  await selectStrategy(id);
}

async function createStrategy() {
  const name = document.getElementById('create_strategy_name')?.value?.trim();
  const strategyType = document.getElementById('create_strategy_type')?.value || 'golden_cross';
  const accountNo = document.getElementById('create_strategy_account')?.value?.trim();
  const symbolsRaw = document.getElementById('create_strategy_symbols')?.value;
  const symbols = parseSymbols(symbolsRaw);

  if (!name) {
    alert('전략 이름을 입력해줘');
    return;
  }
  if (!symbols.length) {
    alert('심볼을 1개 이상 입력해줘 (예: 005930,000660)');
    return;
  }

  const payload = {
    name,
    strategy_type: strategyType,
    account_no: accountNo || null,
    symbols,
  };

  setStrategyDetailOutput('전략 생성 중...');
  try {
    const res = await fetch('/api/v1/strategies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const parsed = await readJsonSafely(res);
    setStrategyDetailOutput(parsed.data);
    if (parsed.ok && parsed.data?.success) {
      await loadStrategies();
      const id = parsed.data?.data?.id;
      if (id) await selectStrategy(id);
    }
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
}

async function deleteStrategy(id) {
  if (!confirm(`전략 ${id}를 삭제할까?`)) return;
  setStrategyDetailOutput('전략 삭제 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}`, { method: 'DELETE' });
    if (res.status === 204) {
      setStrategyDetailOutput({ success: true, detail: 'deleted (204)' });
    } else {
      const parsed = await readJsonSafely(res);
      setStrategyDetailOutput(parsed.data);
    }
    await loadStrategies();
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
}

const goOperate = (id) => {
  setSelectedStrategyId(id);
  location.href = '/mypage/strategy/operate';
};

const goEdit = (id) => {
  setSelectedStrategyId(id);
  location.href = '/mypage/strategy/edit';
};

const goSymbolStates = (id) => {
  setSelectedStrategyId(id);
  location.href = '/mypage/strategy/symbol-states';
};

const goSignals = (id) => {
  setSelectedStrategyId(id);
  location.href = '/mypage/strategy/signals';
};

window.loadStrategies = loadStrategies;
window.selectStrategy = selectStrategy;
window.loadSelectedStrategyDetail = loadSelectedStrategyDetail;
window.createStrategy = createStrategy;
window.deleteStrategy = deleteStrategy;
window.goOperate = goOperate;
window.goEdit = goEdit;
window.goSymbolStates = goSymbolStates;
window.goSignals = goSignals;

document.addEventListener('DOMContentLoaded', () => {
  const persisted = loadPersistedSelectedStrategyId();
  if (persisted) {
    setSelectedStrategyId(persisted);
  } else {
    updateSelectedStrategyLabel(null);
  }

  const input = document.getElementById('control_strategy_id');
  if (input) {
    input.addEventListener('input', () => {
      const id = getSelectedStrategyId();
      updateSelectedStrategyLabel(id);
      persistSelectedStrategyId(id);
    });
  }

  loadStrategies();
});
