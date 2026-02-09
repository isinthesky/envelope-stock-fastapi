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

const getControlStrategyId = () => {
  const raw = document.getElementById('control_strategy_id')?.value;
  const id = raw ? parseInt(raw, 10) : NaN;
  if (!id || Number.isNaN(id)) {
    alert('Strategy ID를 입력해줘');
    return null;
  }
  return id;
};

const callStrategyAction = async (action) => {
  const id = getControlStrategyId();
  if (!id) return;

  setControlOutput(`${action} 실행 중...`);
  try {
    const res = await fetch(`/api/v1/strategies/${id}/${action}`, { method: 'POST' });
    const parsed = await readJsonSafely(res);
    setControlOutput(parsed.data);
  } catch (e) {
    setControlOutput(`오류: ${e.message}`);
  }
};

const startStrategy = () => callStrategyAction('start');
const pauseStrategy = () => callStrategyAction('pause');
const stopStrategy = () => callStrategyAction('stop');

const executeStrategy = async () => {
  const id = getControlStrategyId();
  if (!id) return;

  const dryRun = confirm('dry_run=true로 실행할까? (확인=Dry Run / 취소=실주문 가능)');
  const payload = { dry_run: dryRun, force: false };

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
};

const getSchedulerStatus = async () => {
  setControlOutput('scheduler status 조회 중...');
  try {
    const res = await fetch('/api/v1/strategies/scheduler/status');
    const parsed = await readJsonSafely(res);
    setControlOutput(parsed.data);
  } catch (e) {
    setControlOutput(`오류: ${e.message}`);
  }
};

const loadSelectedStrategyDetail = async () => {
  const id = getControlStrategyId();
  if (!id) return;

  setStrategyDetailOutput(`전략 ${id} 상세 로딩 중...`);
  try {
    const res = await fetch(`/api/v1/strategies/${id}`);
    const parsed = await readJsonSafely(res);
    setStrategyDetailOutput(parsed.data);
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
};

window.startStrategy = startStrategy;
window.pauseStrategy = pauseStrategy;
window.stopStrategy = stopStrategy;
window.executeStrategy = executeStrategy;
window.getSchedulerStatus = getSchedulerStatus;
window.loadSelectedStrategyDetail = loadSelectedStrategyDetail;

document.addEventListener('DOMContentLoaded', () => {
  const input = document.getElementById('control_strategy_id');
  const persisted = loadPersistedSelectedStrategyId();
  if (input && persisted) {
    input.value = String(persisted);
  }

  const id = input ? parseInt(input.value || '', 10) : NaN;
  updateSelectedStrategyLabel(!Number.isNaN(id) && id > 0 ? id : null);

  if (input) {
    input.addEventListener('input', () => {
      const nextId = parseInt(input.value || '', 10);
      const normalized = !Number.isNaN(nextId) && nextId > 0 ? nextId : null;
      updateSelectedStrategyLabel(normalized);
      persistSelectedStrategyId(normalized);
    });
  }
});
