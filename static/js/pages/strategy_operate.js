const {
  readJsonSafely,
  resolveStrategyId,
  validateStrategyId,
  parsePositiveInt,
  persistSelection,
  clearSelection,
  setText,
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

const setStrategyDetailOutput = (msg) => {
  const el = document.getElementById('strategy_detail_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
};

const setControlOutput = (msg) => {
  const el = document.getElementById('strategy_control_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
};

const setButtonsDisabled = (disabled) => {
  ['btn_start', 'btn_pause', 'btn_stop', 'btn_execute', 'btn_scheduler'].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.disabled = !!disabled;
  });
};

const applyStatusGuard = (strategy) => {
  const startBtn = document.getElementById('btn_start');
  const pauseBtn = document.getElementById('btn_pause');
  const stopBtn = document.getElementById('btn_stop');

  if (!startBtn || !pauseBtn || !stopBtn) return;

  if (!strategy?.status) {
    startBtn.disabled = true;
    pauseBtn.disabled = true;
    stopBtn.disabled = true;
    return;
  }

  const status = String(strategy.status).toLowerCase();
  // status: active/paused/stopped/completed
  if (status === 'active') {
    startBtn.disabled = true;
    pauseBtn.disabled = false;
    stopBtn.disabled = false;
    return;
  }
  if (status === 'paused') {
    startBtn.disabled = false;
    pauseBtn.disabled = true;
    stopBtn.disabled = false;
    return;
  }
  if (status === 'stopped' || status === 'completed') {
    startBtn.disabled = false;
    pauseBtn.disabled = true;
    stopBtn.disabled = true;
    return;
  }

  // fallback: unknown
  startBtn.disabled = false;
  pauseBtn.disabled = false;
  stopBtn.disabled = false;
};

const getControlStrategyId = () => {
  const raw = document.getElementById('control_strategy_id')?.value;
  const id = parsePositiveInt(raw);
  return id;
};

const disableAndExplain = (reason, isQuerySsoFailClose = false) => {
  currentStrategy = null;
  updateSelectedStrategyLabel(null);
  setButtonsDisabled(true);

  const detail = reason || '전략을 선택하세요.';
  const extra = isQuerySsoFailClose
    ? ' (query param이 무효라서 localStorage로 fallback 하지 않았습니다)'
    : '';

  setWarning(`전략 컨텍스트가 없습니다. ${detail}${extra}`, '/mypage/strategy/manage');
};

const loadAndValidateFromResolved = async () => {
  const resolved = resolveStrategyId();
  const input = document.getElementById('control_strategy_id');

  if (resolved.source === 'query' && !resolved.id) {
    if (input) input.value = '';
    disableAndExplain(`strategy_id=${resolved.queryRaw || '(empty)'} 가 유효하지 않습니다.`, true);
    return;
  }

  if (resolved.id && input) {
    input.value = String(resolved.id);
  }

  const id = resolved.id || getControlStrategyId();
  if (!id) {
    disableAndExplain('strategy_id가 없습니다.');
    return;
  }

  setWarning(null);
  setButtonsDisabled(true);
  setStrategyDetailOutput(`전략 ${id} 상세 로딩 중...`);

  const validated = await validateStrategyId(id);
  if (!validated.ok) {
    if (resolved.source === 'storage') {
      clearSelection();
    }

    disableAndExplain('전략 검증 실패(404/권한/오류 등).');
    setStrategyDetailOutput(validated.error);
    return;
  }

  currentStrategy = validated.strategy;
  updateSelectedStrategyLabel(currentStrategy);
  setStrategyDetailOutput(validated.dto);
  persistSelection({ id: currentStrategy.id, account_no: currentStrategy.account_no });

  setButtonsDisabled(false);
  applyStatusGuard(currentStrategy);
};

const withInFlight = async (fn) => {
  if (inFlight) return;
  inFlight = true;
  setButtonsDisabled(true);
  try {
    await fn();
  } finally {
    inFlight = false;

    if (!currentStrategy) {
      setButtonsDisabled(true);
      return;
    }

    // restore based on latest strategy status
    setButtonsDisabled(false);
    applyStatusGuard(currentStrategy);
  }
};

const callStrategyAction = async (action) => {
  const id = getControlStrategyId();
  if (!id) {
    alert('Strategy ID를 입력해줘');
    return;
  }

  if (!currentStrategy || currentStrategy.id !== id) {
    disableAndExplain('입력한 ID가 현재 검증된 전략과 다릅니다. 상세 새로고침으로 다시 검증해줘.');
    setControlOutput('먼저 상세 새로고침으로 전략을 검증한 뒤 실행해줘.');
    return;
  }

  await withInFlight(async () => {
    setControlOutput(`${action} 실행 중...`);
    try {
      const res = await fetch(`/api/v1/strategies/${id}/${action}`, { method: 'POST' });
      const parsed = await readJsonSafely(res);
      setControlOutput(parsed.data);
    } catch (e) {
      setControlOutput(`오류: ${e.message}`);
    }

    await loadAndValidateFromResolved();
  });
};

const startStrategy = () => callStrategyAction('start');
const pauseStrategy = () => callStrategyAction('pause');
const stopStrategy = async () => {
  const id = getControlStrategyId();
  if (!id) {
    alert('Strategy ID를 입력해줘');
    return;
  }

  if (!currentStrategy || currentStrategy.id !== id) {
    disableAndExplain('입력한 ID가 현재 검증된 전략과 다릅니다. 상세 새로고침으로 다시 검증해줘.');
    setControlOutput('먼저 상세 새로고침으로 전략을 검증한 뒤 실행해줘.');
    return;
  }
  if (!confirm(`전략을 중지할까? (ID=${id})`)) return;
  return callStrategyAction('stop');
};

const executeStrategy = async () => {
  const id = getControlStrategyId();
  if (!id) {
    alert('Strategy ID를 입력해줘');
    return;
  }

  if (!currentStrategy || currentStrategy.id !== id) {
    disableAndExplain('입력한 ID가 현재 검증된 전략과 다릅니다. 상세 새로고침으로 다시 검증해줘.');
    setControlOutput('먼저 상세 새로고침으로 전략을 검증한 뒤 실행해줘.');
    return;
  }

  const dryRun = document.getElementById('execute_dry_run')?.checked ?? true;
  const force = document.getElementById('execute_force')?.checked ?? false;

  const name = currentStrategy?.name ? ` / ${currentStrategy.name}` : '';
  const ok = confirm(`전략 실행할까? (ID=${id}${name})\n- dry_run=${dryRun}\n- force=${force}`);
  if (!ok) return;

  if (!dryRun) {
    const ok2 = confirm('dry_run=false 입니다. 실주문 가능성이 있습니다. 정말 실행할까?');
    if (!ok2) return;

    const phrase = prompt('계속하려면 RUN 을 입력해줘');
    if (phrase !== 'RUN') {
      alert('취소됨');
      return;
    }
  }

  const payload = { dry_run: dryRun, force };

  await withInFlight(async () => {
    setControlOutput('execute 실행 중...');
    try {
      const res = await fetch(`/api/v1/strategies/${id}/execute`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      const parsed = await readJsonSafely(res);
      setControlOutput(parsed.data);
    } catch (e) {
      setControlOutput(`오류: ${e.message}`);
    }

    await loadAndValidateFromResolved();
  });
};

const getSchedulerStatus = async () => {
  await withInFlight(async () => {
    setControlOutput('scheduler status 조회 중...');
    try {
      const res = await fetch('/api/v1/strategies/scheduler/status');
      const parsed = await readJsonSafely(res);
      setControlOutput(parsed.data);
    } catch (e) {
      setControlOutput(`오류: ${e.message}`);
    }
  });
};

const loadSelectedStrategyDetail = async () => {
  const id = getControlStrategyId();
  if (!id) {
    alert('Strategy ID를 입력해줘');
    return;
  }

  setWarning(null);
  setButtonsDisabled(true);
  setStrategyDetailOutput(`전략 ${id} 상세 로딩 중...`);
  const validated = await validateStrategyId(id);
  if (!validated.ok) {
    setStrategyDetailOutput(validated.error);
    disableAndExplain('전략 검증 실패(404/권한/오류 등).');
    return;
  }
  currentStrategy = validated.strategy;
  updateSelectedStrategyLabel(currentStrategy);
  setStrategyDetailOutput(validated.dto);
  persistSelection({ id: currentStrategy.id, account_no: currentStrategy.account_no });
  setButtonsDisabled(false);
  applyStatusGuard(currentStrategy);
};

window.startStrategy = startStrategy;
window.pauseStrategy = pauseStrategy;
window.stopStrategy = stopStrategy;
window.executeStrategy = executeStrategy;
window.getSchedulerStatus = getSchedulerStatus;
window.loadSelectedStrategyDetail = loadSelectedStrategyDetail;

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('control_strategy_id');
  if (input) {
    input.addEventListener('input', () => {
      const id = getControlStrategyId();
      // typing invalidates the previously validated context
      if (!currentStrategy || currentStrategy.id !== id) {
        currentStrategy = null;
        setButtonsDisabled(true);
        if (id) {
          setWarning('ID가 변경되었습니다. 상세 새로고침으로 다시 검증한 뒤 실행할 수 있어요.', '/mypage/strategy/manage');
        } else {
          setWarning('전략을 선택하세요', '/mypage/strategy/manage');
        }
      }
      updateSelectedStrategyLabel(id);
      // do not persist on raw typing (validated selection only)
    });
  }

  // default: disabled until validated
  setButtonsDisabled(true);
  loadAndValidateFromResolved();
});
