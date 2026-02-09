const {
  readJsonSafely,
  extractStrategy,
  parsePositiveInt,
  escapeHtml,
  persistSelection,
  loadSelection,
  buildUrl,
} = window.StrategyShared;

let selectedStrategy = null;

const setStrategyDetailOutput = (msg) => {
  const el = document.getElementById('strategy_detail_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
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

const setSelectedStrategyIdInput = (id) => {
  const input = document.getElementById('control_strategy_id');
  if (!input) return;
  input.value = id ? String(id) : '';
};

const getSelectedStrategyIdFromInput = () => {
  const raw = document.getElementById('control_strategy_id')?.value;
  return parsePositiveInt(raw);
};

const parseSymbols = (raw) => {
  if (!raw) return [];
  return raw
    .split(',')
    .map((s) => s.trim())
    .filter(Boolean);
};

function renderStrategyList(strategies) {
  const body = document.getElementById('strategy_list_table_body');
  if (!body) return;

  if (!strategies || !strategies.length) {
    body.innerHTML =
      '<tr><td colspan="6" class="placeholder-message" style="border:none;">전략이 없습니다.</td></tr>';
    return;
  }

  body.innerHTML = strategies
    .map((s) => {
      const id = Number(s.id);
      const symbols = Array.isArray(s.symbols) ? s.symbols.join(', ') : s.symbols || '';
      return `
      <tr onclick="selectStrategy(${id})">
        <td>${id}</td>
        <td>${escapeHtml(s.name || '-')}</td>
        <td>${escapeHtml(s.strategy_type || '-')}</td>
        <td>${escapeHtml(s.status || '-')}</td>
        <td style="max-width: 360px; overflow:hidden; text-overflow: ellipsis; white-space: nowrap;">${escapeHtml(
          symbols
        )}</td>
        <td>
          <button class="secondary" onclick="event.stopPropagation(); selectStrategy(${id})">Select</button>
          <button class="secondary" onclick="event.stopPropagation(); goOperate(${id})">Operate</button>
          <button class="secondary" onclick="event.stopPropagation(); goEdit(${id})">Edit</button>
          <button class="secondary" onclick="event.stopPropagation(); goSymbolStates(${id})">States</button>
          <button class="secondary" onclick="event.stopPropagation(); goSignals(${id})">Signals</button>
          <button onclick="event.stopPropagation(); deleteStrategy(${id})" style="background:#fecaca;color:#991b1b;">Delete</button>
        </td>
      </tr>
    `;
    })
    .join('');
}

async function loadStrategies() {
  setStrategyDetailOutput('전략 목록 로딩 중...');

  const qs = new URLSearchParams();
  const accountNo = document.getElementById('filter_account_no')?.value?.trim();
  const statusFilter = document.getElementById('filter_status_filter')?.value;
  if (accountNo) qs.set('account_no', accountNo);
  if (statusFilter) qs.set('status_filter', statusFilter);

  const url = `/api/v1/strategies${qs.toString() ? `?${qs.toString()}` : ''}`;

  try {
    const res = await fetch(url);
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
  const strategyId = parsePositiveInt(id);
  if (!strategyId) return;

  setSelectedStrategyIdInput(strategyId);
  updateSelectedStrategyLabel(strategyId);
  persistSelection({ id: strategyId });

  setStrategyDetailOutput(`전략 ${strategyId} 상세 로딩 중...`);
  try {
    const res = await fetch(`/api/v1/strategies/${strategyId}`);
    const parsed = await readJsonSafely(res);
    setStrategyDetailOutput(parsed.data);

    if (parsed.ok && (parsed.data?.success ?? true)) {
      const s = extractStrategy(parsed.data);
      if (s?.id) {
        selectedStrategy = s;
        updateSelectedStrategyLabel(s);
        persistSelection({ id: s.id, account_no: s.account_no });
      }
    }
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
}

async function loadSelectedStrategyDetail() {
  const id = getSelectedStrategyIdFromInput();
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
  const strategyId = parsePositiveInt(id);
  if (!strategyId) return;

  if (!confirm(`전략 ${strategyId}를 삭제할까?`)) return;
  setStrategyDetailOutput('전략 삭제 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${strategyId}`, { method: 'DELETE' });
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
  const strategyId = parsePositiveInt(id);
  if (!strategyId) return;
  persistSelection({ id: strategyId });
  location.href = buildUrl('/mypage/strategy/operate', strategyId);
};

const goEdit = (id) => {
  const strategyId = parsePositiveInt(id);
  if (!strategyId) return;
  persistSelection({ id: strategyId });
  location.href = buildUrl('/mypage/strategy/edit', strategyId);
};

const goSymbolStates = (id) => {
  const strategyId = parsePositiveInt(id);
  if (!strategyId) return;
  persistSelection({ id: strategyId });
  location.href = buildUrl('/mypage/strategy/symbol-states', strategyId);
};

const goSignals = (id) => {
  const strategyId = parsePositiveInt(id);
  if (!strategyId) return;
  persistSelection({ id: strategyId });
  location.href = buildUrl('/mypage/strategy/signals', strategyId);
};

const requireSelected = () => {
  const id = getSelectedStrategyIdFromInput();
  if (!id) {
    alert('먼저 Strategy ID를 선택하거나 입력해줘.');
    return null;
  }
  persistSelection({ id });
  return id;
};

const goOperateSelected = () => {
  const id = requireSelected();
  if (!id) return;
  goOperate(id);
};
const goEditSelected = () => {
  const id = requireSelected();
  if (!id) return;
  goEdit(id);
};
const goSymbolStatesSelected = () => {
  const id = requireSelected();
  if (!id) return;
  goSymbolStates(id);
};
const goSignalsSelected = () => {
  const id = requireSelected();
  if (!id) return;
  goSignals(id);
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
window.goOperateSelected = goOperateSelected;
window.goEditSelected = goEditSelected;
window.goSymbolStatesSelected = goSymbolStatesSelected;
window.goSignalsSelected = goSignalsSelected;

document.addEventListener('DOMContentLoaded', () => {
  const stored = loadSelection();
  if (stored?.id) {
    setSelectedStrategyIdInput(stored.id);
    updateSelectedStrategyLabel(stored.id);
  } else {
    updateSelectedStrategyLabel(null);
  }

  const input = document.getElementById('control_strategy_id');
  if (input) {
    input.addEventListener('input', () => {
      const id = getSelectedStrategyIdFromInput();
      updateSelectedStrategyLabel(id);
    });
  }

  loadStrategies();
});
