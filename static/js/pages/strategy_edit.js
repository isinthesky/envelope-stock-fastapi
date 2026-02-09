const {
  readJsonSafely,
  resolveStrategyId,
  validateStrategyId,
  extractStrategy,
  parsePositiveInt,
  persistSelection,
  clearSelection,
} = window.StrategyShared;

let currentStrategy = null;
let inFlight = false;

const warningEl = () => document.getElementById('strategy_context_warning');

const setWarning = (msg, linkHref = null, linkText = null) => {
  const el = warningEl();
  if (!el) return;

  if (!msg) {
    el.style.display = 'none';
    el.textContent = '';
    return;
  }

  el.style.display = 'block';
  el.textContent = '';
  el.appendChild(document.createTextNode(String(msg)));

  if (linkHref) {
    el.appendChild(document.createTextNode(' → '));
    const a = document.createElement('a');
    a.href = linkHref;
    a.textContent = linkText || linkHref;
    el.appendChild(a);
  }
};

const setButtonsDisabled = (disabled) => {
  ['btn_detail_refresh', 'btn_patch_strategy', 'btn_reset_patch', 'btn_get_config', 'btn_patch_config'].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (el) el.disabled = !!disabled;
    }
  );
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

const getSelectedStrategyId = () => {
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

const fillStrategyPatchForm = (strategy) => {
  if (!strategy) return;

  const name = document.getElementById('patch_strategy_name');
  const status = document.getElementById('patch_strategy_status');
  const desc = document.getElementById('patch_strategy_description');
  const descClear = document.getElementById('patch_strategy_description_clear');
  const symbols = document.getElementById('patch_strategy_symbols');

  if (name) name.value = strategy.name || '';
  if (status) status.value = strategy.status || '';
  if (desc) desc.value = strategy.description || '';
  if (descClear) descClear.checked = false;

  if (symbols) {
    const list = Array.isArray(strategy.symbols) ? strategy.symbols.join(',') : strategy.symbols || '';
    symbols.value = list;
  }
};

const resetStrategyPatchForm = () => {
  ['patch_strategy_name', 'patch_strategy_status', 'patch_strategy_description', 'patch_strategy_symbols'].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    }
  );

  const descClear = document.getElementById('patch_strategy_description_clear');
  if (descClear) descClear.checked = false;

  setStrategyPatchOutput('(PATCH 결과가 여기에 표시됩니다)');
};

const explainNoContext = (detail, isQueryFailClose = false) => {
  currentStrategy = null;
  updateSelectedStrategyLabel(null);
  setButtonsDisabled(true);

  const extra = isQueryFailClose
    ? ' (query param이 무효라서 localStorage로 fallback 하지 않았습니다)'
    : '';
  setWarning(`전략 컨텍스트가 없습니다. ${detail || ''}${extra}`, '/mypage/strategy/manage');
};

const loadAndValidateFromResolved = async () => {
  const resolved = resolveStrategyId();
  const input = document.getElementById('control_strategy_id');

  if (resolved.source === 'query' && !resolved.id) {
    if (input) input.value = '';
    explainNoContext(`strategy_id=${resolved.queryRaw || '(empty)'} 가 유효하지 않습니다.`, true);
    return;
  }

  if (resolved.id && input) {
    input.value = String(resolved.id);
  }

  const id = resolved.id || getSelectedStrategyId();
  if (!id) {
    explainNoContext('strategy_id가 없습니다.');
    return;
  }

  setWarning(null);
  setButtonsDisabled(false);
  setStrategyDetailOutput(`전략 ${id} 상세 로딩 중...`);

  const validated = await validateStrategyId(id);
  if (!validated.ok) {
    if (resolved.source === 'storage') {
      clearSelection();
    }
    setStrategyDetailOutput(validated.error);
    explainNoContext('전략 검증 실패(404/권한/오류 등).');
    return;
  }

  currentStrategy = validated.strategy;
  updateSelectedStrategyLabel(currentStrategy);
  setStrategyDetailOutput(validated.dto);
  persistSelection({ id: currentStrategy.id, account_no: currentStrategy.account_no });
  fillStrategyPatchForm(currentStrategy);
};

const withInFlight = async (fn) => {
  if (inFlight) return;
  inFlight = true;
  setButtonsDisabled(true);
  try {
    await fn();
  } finally {
    inFlight = false;
    setButtonsDisabled(false);
  }
};

const loadSelectedStrategyDetail = async () => {
  const id = getSelectedStrategyId();
  if (!id) {
    alert('먼저 Strategy ID를 선택하거나 입력해줘.');
    return;
  }

  setWarning(null);
  await withInFlight(async () => {
    setStrategyDetailOutput(`전략 ${id} 상세 로딩 중...`);
    const validated = await validateStrategyId(id);
    if (!validated.ok) {
      setStrategyDetailOutput(validated.error);
      explainNoContext('전략 검증 실패(404/권한/오류 등).');
      return;
    }

    currentStrategy = validated.strategy;
    updateSelectedStrategyLabel(currentStrategy);
    setStrategyDetailOutput(validated.dto);
    persistSelection({ id: currentStrategy.id, account_no: currentStrategy.account_no });
    fillStrategyPatchForm(currentStrategy);
  });
};

const patchStrategy = async () => {
  const id = getSelectedStrategyId();
  if (!id) {
    setStrategyPatchOutput('먼저 Strategy ID를 선택하거나 입력해줘.');
    return;
  }

  const name = document.getElementById('patch_strategy_name')?.value?.trim();
  const status = document.getElementById('patch_strategy_status')?.value;

  const descClear = document.getElementById('patch_strategy_description_clear')?.checked ?? false;
  const descriptionRaw = document.getElementById('patch_strategy_description')?.value;
  const description = descriptionRaw?.trim();

  const symbolsRaw = document.getElementById('patch_strategy_symbols')?.value;
  const symbols = parseSymbols(symbolsRaw);

  const payload = {};
  if (name) payload.name = name;
  if (status) payload.status = status;

  // clear/null 정책: 빈 문자열은 변경 안 함. 비우기는 체크박스가 SSOT.
  if (descClear) {
    payload.description = null;
  } else if (description) {
    payload.description = description;
  }

  if (symbols.length) payload.symbols = symbols;

  if (Object.keys(payload).length === 0) {
    setStrategyPatchOutput('PATCH할 항목을 입력해줘.');
    return;
  }

  await withInFlight(async () => {
    setStrategyPatchOutput('전략 PATCH 중...');
    try {
      const res = await fetch(`/api/v1/strategies/${id}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const parsed = await readJsonSafely(res);
      setStrategyPatchOutput(parsed.data);
      if (parsed.ok && (parsed.data?.success ?? true)) {
        await loadSelectedStrategyDetail();
      }
    } catch (e) {
      setStrategyPatchOutput(`오류: ${e.message}`);
    }
  });
};

const getStrategyConfig = async () => {
  const id = getSelectedStrategyId();
  if (!id) {
    setStrategyConfigOutput('먼저 Strategy ID를 선택하거나 입력해줘.');
    return;
  }

  await withInFlight(async () => {
    setStrategyConfigOutput('Config 조회 중...');
    try {
      const res = await fetch(`/api/v1/strategies/${id}/config`);
      const parsed = await readJsonSafely(res);
      setStrategyConfigOutput(parsed.data);
      if (parsed.ok && (parsed.data?.success ?? true)) {
        const textarea = document.getElementById('strategy_config_textarea');
        if (textarea) {
          const cfg = parsed.data?.data?.config ?? parsed.data?.data ?? {};
          textarea.value = JSON.stringify(cfg, null, 2);
        }
      }
    } catch (e) {
      setStrategyConfigOutput(`오류: ${e.message}`);
    }
  });
};

const patchStrategyConfig = async () => {
  const id = getSelectedStrategyId();
  if (!id) {
    setStrategyConfigOutput('먼저 Strategy ID를 선택하거나 입력해줘.');
    return;
  }

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

  await withInFlight(async () => {
    setStrategyConfigOutput('Config PATCH 중...');
    try {
      const res = await fetch(`/api/v1/strategies/${id}/config`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const parsed = await readJsonSafely(res);
      setStrategyConfigOutput(parsed.data);
      if (parsed.ok && (parsed.data?.success ?? true) && textarea) {
        textarea.value = JSON.stringify(parsed.data?.data ?? {}, null, 2);
      }
    } catch (e) {
      setStrategyConfigOutput(`오류: ${e.message}`);
    }
  });
};

window.loadSelectedStrategyDetail = loadSelectedStrategyDetail;
window.patchStrategy = patchStrategy;
window.resetStrategyPatchForm = resetStrategyPatchForm;
window.getStrategyConfig = getStrategyConfig;
window.patchStrategyConfig = patchStrategyConfig;

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('control_strategy_id');
  if (input) {
    input.addEventListener('input', () => {
      const id = getSelectedStrategyId();
      updateSelectedStrategyLabel(id);

      // Recovery UX: allow manual entry even when opened directly (no query/storage)
      const refreshBtn = document.getElementById('btn_detail_refresh');
      if (refreshBtn) refreshBtn.disabled = !id;
      if (id) setWarning(null);
    });
  }

  setButtonsDisabled(true);
  const refreshBtn = document.getElementById('btn_detail_refresh');
  if (refreshBtn) refreshBtn.disabled = !getSelectedStrategyId();

  loadAndValidateFromResolved();
});
