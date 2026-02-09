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

const setStrategyPatchOutput = (msg) => {
  const el = document.getElementById('strategy_patch_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
};

const setStrategyConfigOutput = (msg) => {
  const el = document.getElementById('strategy_config_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
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

const fillStrategyPatchForm = (strategy) => {
  if (!strategy) return;
  const name = document.getElementById('patch_strategy_name');
  const status = document.getElementById('patch_strategy_status');
  const desc = document.getElementById('patch_strategy_description');
  const symbols = document.getElementById('patch_strategy_symbols');

  if (name) name.value = strategy.name || '';
  if (status) status.value = strategy.status || '';
  if (desc) desc.value = strategy.description || '';
  if (symbols) {
    const list = Array.isArray(strategy.symbols) ? strategy.symbols.join(',') : strategy.symbols || '';
    symbols.value = list;
  }
};

const resetStrategyPatchForm = () => {
  const ids = [
    'patch_strategy_name',
    'patch_strategy_status',
    'patch_strategy_description',
    'patch_strategy_symbols',
  ];

  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    el.value = '';
  });

  setStrategyPatchOutput('(PATCH 결과가 여기에 표시됩니다)');
};

const loadSelectedStrategyDetail = async () => {
  const id = getSelectedStrategyId('strategy_detail_output');
  if (!id) return;

  setStrategyDetailOutput(`전략 ${id} 상세 로딩 중...`);
  try {
    const res = await fetch(`/api/v1/strategies/${id}`);
    const parsed = await readJsonSafely(res);
    setStrategyDetailOutput(parsed.data);
    if (parsed.ok) {
      const strategy = getStrategyFromResponse(parsed.data);
      if (strategy) fillStrategyPatchForm(strategy);
    }
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
};

const patchStrategy = async () => {
  const id = getSelectedStrategyId('strategy_patch_output');
  if (!id) return;

  const name = document.getElementById('patch_strategy_name')?.value?.trim();
  const status = document.getElementById('patch_strategy_status')?.value;
  const description = document.getElementById('patch_strategy_description')?.value?.trim();
  const symbolsRaw = document.getElementById('patch_strategy_symbols')?.value;
  const symbols = parseSymbols(symbolsRaw);

  const payload = {};
  if (name) payload.name = name;
  if (status) payload.status = status;
  if (description) payload.description = description;
  if (symbols.length) payload.symbols = symbols;

  if (Object.keys(payload).length === 0) {
    setStrategyPatchOutput('PATCH할 항목을 입력해줘.');
    return;
  }

  setStrategyPatchOutput('전략 PATCH 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const parsed = await readJsonSafely(res);
    setStrategyPatchOutput(parsed.data);
    if (parsed.ok) {
      await loadSelectedStrategyDetail();
    }
  } catch (e) {
    setStrategyPatchOutput(`오류: ${e.message}`);
  }
};

const getStrategyConfig = async () => {
  const id = getSelectedStrategyId('strategy_config_output');
  if (!id) return;

  setStrategyConfigOutput('Config 조회 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/config`);
    const parsed = await readJsonSafely(res);
    setStrategyConfigOutput(parsed.data);
    if (parsed.ok) {
      const textarea = document.getElementById('strategy_config_textarea');
      if (textarea) {
        const cfg = parsed.data?.data?.config ?? parsed.data?.data ?? {};
        textarea.value = JSON.stringify(cfg, null, 2);
      }
    }
  } catch (e) {
    setStrategyConfigOutput(`오류: ${e.message}`);
  }
};

const patchStrategyConfig = async () => {
  const id = getSelectedStrategyId('strategy_config_output');
  if (!id) return;

  const textarea = document.getElementById('strategy_config_textarea');
  const raw = textarea?.value?.trim();
  if (!raw) {
    setStrategyConfigOutput('PATCH할 JSON을 입력해줘.');
    return;
  }

  let payload;
  try {
    payload = JSON.parse(raw);
    payload = payload?.config ?? payload?.data ?? payload;
  } catch (e) {
    setStrategyConfigOutput(`JSON 파싱 오류: ${e.message}`);
    return;
  }

  setStrategyConfigOutput('Config PATCH 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/config`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    const parsed = await readJsonSafely(res);
    setStrategyConfigOutput(parsed.data);
    if (parsed.ok && textarea) {
      textarea.value = JSON.stringify(parsed.data?.data ?? {}, null, 2);
    }
  } catch (e) {
    setStrategyConfigOutput(`오류: ${e.message}`);
  }
};

window.loadSelectedStrategyDetail = loadSelectedStrategyDetail;
window.patchStrategy = patchStrategy;
window.resetStrategyPatchForm = resetStrategyPatchForm;
window.getStrategyConfig = getStrategyConfig;
window.patchStrategyConfig = patchStrategyConfig;

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
