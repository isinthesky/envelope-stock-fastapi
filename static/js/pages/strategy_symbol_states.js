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

const setOutput = (msg) => {
  const el = document.getElementById('symbol_states_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
};

const setLoadDisabled = (disabled) => {
  const btn = document.getElementById('btn_load_symbol_states');
  if (btn) btn.disabled = !!disabled;
};

const getStrategyId = () => {
  const raw = document.getElementById('control_strategy_id')?.value;
  return parsePositiveInt(raw);
};

const renderTable = (items) => {
  const body = document.getElementById('symbol_states_table_body');
  if (!body) return;

  if (!items || items.length === 0) {
    body.innerHTML =
      '<tr><td colspan="4" class="placeholder-message" style="border:none;">결과가 없습니다.</td></tr>';
    return;
  }

  body.innerHTML = items
    .map((item) => {
      return `
      <tr>
        <td>${escapeHtml(item.symbol || '-')}</td>
        <td>${escapeHtml(item.state || '-')}</td>
        <td>${escapeHtml(item.last_close ?? '-')}</td>
        <td>${escapeHtml(item.unrealized_pnl_ratio ?? item.unrealized_pnl_pct ?? '-')}</td>
      </tr>
    `;
    })
    .join('');
};

const loadSymbolStates = async () => {
  const id = getStrategyId();
  if (!id) {
    setOutput('먼저 Strategy ID를 선택하거나 입력해줘.');
    return;
  }

  setOutput('Symbol States 조회 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/symbol-states`);
    const parsed = await readJsonSafely(res);
    setOutput(parsed.data);
    if (parsed.ok && (parsed.data?.success ?? true)) {
      const list =
        parsed.data?.data?.symbol_states ||
        parsed.data?.data?.items ||
        parsed.data?.symbol_states ||
        parsed.data?.items ||
        [];
      renderTable(Array.isArray(list) ? list : []);
    }
  } catch (e) {
    setOutput(`오류: ${e.message}`);
  }
};

window.loadSymbolStates = loadSymbolStates;

document.addEventListener('DOMContentLoaded', async () => {
  const input = document.getElementById('control_strategy_id');
  if (input) {
    input.addEventListener('input', () => {
      updateSelectedStrategyLabel(getStrategyId());
    });
  }

  setLoadDisabled(true);

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
    setOutput(validated.error);
    return;
  }

  validatedStrategy = validated.strategy;
  updateSelectedStrategyLabel(validatedStrategy);
  persistSelection({ id: validatedStrategy.id, account_no: validatedStrategy.account_no });
  setLoadDisabled(false);
});
