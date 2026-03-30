// Strategy Dashboard - 전략 대시보드 통합 페이지 JS
(function () {
  'use strict';

  const API = '/api/v1/strategies';
  let _activePresetId = null;
  let _expandedStrategyId = null;
  let _strategies = [];

  // ==================== Presets ====================

  async function loadPresets() {
    const grid = document.getElementById('preset_grid');
    try {
      const res = await fetch(`${API}/presets`);
      const json = await res.json();
      const presets = json.data?.presets || [];

      if (!presets.length) {
        grid.innerHTML = '<div class="placeholder">등록된 프리셋이 없습니다.</div>';
        return;
      }

      grid.innerHTML = presets.map(p => {
        const riskClass = { low: 'risk-low', medium: 'risk-medium', high: 'risk-high' }[p.risk_level] || 'risk-medium';
        const riskLabel = { low: '보수형', medium: '표준', high: '공격형' }[p.risk_level] || p.risk_level;
        const tags = (p.tags || []).map(t => `<span class="preset-tag">${esc(t)}</span>`).join('');
        return `
          <div class="preset-card">
            <span class="risk-badge ${riskClass}">${riskLabel}</span>
            <h3>${esc(p.name)}</h3>
            <p>${esc(p.description)}</p>
            <div class="preset-tags">${tags}</div>
            <button class="btn-activate" onclick="openActivateModal('${esc(p.preset_id)}', '${esc(p.name)}')">활성화</button>
          </div>`;
      }).join('');
    } catch (e) {
      grid.innerHTML = `<div class="placeholder">프리셋 로드 실패: ${esc(e.message)}</div>`;
    }
  }

  function openActivateModal(presetId, presetName) {
    _activePresetId = presetId;
    document.getElementById('modal_title').textContent = `${presetName} 활성화`;
    document.getElementById('modal_name').value = '';
    document.getElementById('modal_symbols').value = '';
    document.getElementById('activate_modal').classList.add('open');
  }

  function closeModal() {
    document.getElementById('activate_modal').classList.remove('open');
    _activePresetId = null;
  }

  async function confirmActivate() {
    if (!_activePresetId) return;
    const btn = document.getElementById('modal_confirm_btn');
    btn.disabled = true;
    btn.textContent = '생성 중...';

    const nameOverride = document.getElementById('modal_name').value.trim() || null;
    const symbolsText = document.getElementById('modal_symbols').value.trim();
    const symbols = symbolsText ? symbolsText.split('\n').map(s => s.trim()).filter(Boolean) : null;

    try {
      const body = {};
      if (nameOverride) body.name_override = nameOverride;
      if (symbols && symbols.length) body.symbols = symbols;

      const res = await fetch(`${API}/presets/${_activePresetId}/activate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const json = await res.json();

      if (res.ok && json.success) {
        closeModal();
        loadMyStrategies();
        alert('전략이 생성되었습니다!');
      } else {
        alert(`실패: ${json.message || json.error || 'Unknown error'}`);
      }
    } catch (e) {
      alert(`오류: ${e.message}`);
    } finally {
      btn.disabled = false;
      btn.textContent = '활성화';
    }
  }

  // ==================== My Strategies ====================

  async function loadMyStrategies() {
    const body = document.getElementById('strategies_body');
    try {
      const res = await fetch(API);
      const json = await res.json();
      const list = json.data?.strategies || [];
      _strategies = list;

      if (!list.length) {
        body.innerHTML = '<tr><td colspan="7" class="placeholder">등록된 전략이 없습니다. 위 카탈로그에서 프리셋을 활성화하세요.</td></tr>';
        updateSignalSelect([]);
        return;
      }

      body.innerHTML = list.map(s => {
        const statusClass = { active: 'status-active', paused: 'status-paused', stopped: 'status-stopped' }[s.status] || 'status-stopped';
        const statusLabel = { active: '실행중', paused: '일시정지', stopped: '중지' }[s.status] || s.status;
        const symbolCount = s.symbols ? s.symbols.length : 0;
        const lastExec = s.last_executed_at ? new Date(s.last_executed_at).toLocaleString('ko-KR') : '-';
        const expandBtn = `<button class="btn-sm btn-delete" onclick="toggleExpand(${s.id})" title="종목 상태 보기">▼</button>`;

        let controls = '';
        if (s.status === 'active') {
          controls = `<button class="btn-sm btn-pause" onclick="controlStrategy(${s.id}, 'pause')">일시정지</button>
                      <button class="btn-sm btn-stop" onclick="controlStrategy(${s.id}, 'stop')">중지</button>`;
        } else if (s.status === 'paused') {
          controls = `<button class="btn-sm btn-start" onclick="controlStrategy(${s.id}, 'start')">시작</button>
                      <button class="btn-sm btn-stop" onclick="controlStrategy(${s.id}, 'stop')">중지</button>`;
        } else {
          controls = `<button class="btn-sm btn-start" onclick="controlStrategy(${s.id}, 'start')">시작</button>
                      <button class="btn-sm btn-delete" onclick="deleteStrategy(${s.id})">삭제</button>`;
        }

        return `
          <tr>
            <td>${expandBtn}</td>
            <td>${esc(s.name)}</td>
            <td>${esc(s.strategy_type)}</td>
            <td><span class="status-badge ${statusClass}">${statusLabel}</span></td>
            <td>${symbolCount}</td>
            <td>${lastExec}</td>
            <td><div class="btn-group">${controls}</div></td>
          </tr>
          <tr class="expand-row" id="expand_${s.id}" style="display:none;">
            <td colspan="7">
              <div class="expand-content" id="expand_content_${s.id}">
                <div class="placeholder">로딩 중...</div>
              </div>
            </td>
          </tr>`;
      }).join('');

      updateSignalSelect(list);
    } catch (e) {
      body.innerHTML = `<tr><td colspan="7" class="placeholder">전략 로드 실패: ${esc(e.message)}</td></tr>`;
    }
  }

  async function controlStrategy(id, action) {
    try {
      const res = await fetch(`${API}/${id}/${action}`, { method: 'POST' });
      const json = await res.json();
      if (res.ok && json.success) {
        loadMyStrategies();
      } else {
        alert(`실패: ${json.message || 'Unknown error'}`);
      }
    } catch (e) {
      alert(`오류: ${e.message}`);
    }
  }

  async function deleteStrategy(id) {
    if (!confirm('정말 삭제하시겠습니까?')) return;
    try {
      const res = await fetch(`${API}/${id}`, { method: 'DELETE' });
      if (res.ok) {
        loadMyStrategies();
      } else {
        const json = await res.json();
        alert(`삭제 실패: ${json.message || 'Unknown error'}`);
      }
    } catch (e) {
      alert(`오류: ${e.message}`);
    }
  }

  // ==================== Symbol States (Expand) ====================

  async function toggleExpand(strategyId) {
    const row = document.getElementById(`expand_${strategyId}`);
    if (!row) return;

    if (_expandedStrategyId === strategyId) {
      row.style.display = 'none';
      _expandedStrategyId = null;
      return;
    }

    // Close previous
    if (_expandedStrategyId !== null) {
      const prev = document.getElementById(`expand_${_expandedStrategyId}`);
      if (prev) prev.style.display = 'none';
    }

    _expandedStrategyId = strategyId;
    row.style.display = '';
    await loadSymbolStates(strategyId);
  }

  async function loadSymbolStates(strategyId) {
    const container = document.getElementById(`expand_content_${strategyId}`);
    if (!container) return;

    try {
      const res = await fetch(`${API}/${strategyId}/symbol-states`);
      const json = await res.json();
      const states = json.data?.states || [];

      if (!states.length) {
        container.innerHTML = '<div class="placeholder">종목 상태 없음</div>';
        return;
      }

      const stateColors = {
        'MONITORING': '#3b82f6',
        'GC_ACTIVE': '#22c55e',
        'WAITING_FOR_PULLBACK': '#f59e0b',
        'BUY_INTEREST': '#f97316',
        'READY_TO_BUY': '#ef4444',
        'OPTIMAL_BUY': '#eab308',
        'POSITION_HELD': '#8b5cf6',
      };

      container.innerHTML = `
        <div style="margin-bottom: 8px; font-size: 12px; color: #94a3b8;">
          총 ${states.length}개 종목 | ${Object.entries(json.data?.state_counts || {}).map(([k, v]) => `${k}: ${v}`).join(' | ')}
        </div>
        <div class="states-grid">
          ${states.map(s => {
            const borderColor = stateColors[s.state] || '#475569';
            const pnl = s.unrealized_pnl_ratio != null ? `${(s.unrealized_pnl_ratio * 100).toFixed(1)}%` : '';
            const pnlColor = s.unrealized_pnl_ratio > 0 ? '#22c55e' : s.unrealized_pnl_ratio < 0 ? '#ef4444' : '#94a3b8';
            return `
              <div class="state-chip" style="border-color: ${borderColor};">
                <div class="symbol">${esc(s.symbol)}</div>
                <div class="state-label">${esc(s.state)}</div>
                ${pnl ? `<div style="color: ${pnlColor}; font-size: 12px; font-weight: 600;">${pnl}</div>` : ''}
                ${s.entry_price ? `<div style="font-size: 11px; color: #64748b;">진입: ${Number(s.entry_price).toLocaleString()}</div>` : ''}
              </div>`;
          }).join('')}
        </div>`;
    } catch (e) {
      container.innerHTML = `<div class="placeholder">상태 로드 실패: ${esc(e.message)}</div>`;
    }
  }

  // ==================== Signals ====================

  function toggleSignals() {
    const body = document.getElementById('signal_body');
    body.classList.toggle('open');
    if (body.classList.contains('open') && !document.getElementById('signals_body').dataset.loaded) {
      loadSignals();
    }
  }

  function updateSignalSelect(strategies) {
    const select = document.getElementById('signal_strategy_id');
    select.innerHTML = strategies.map(s => `<option value="${s.id}">${esc(s.name)} (ID: ${s.id})</option>`).join('');
  }

  async function loadSignals() {
    const strategyId = document.getElementById('signal_strategy_id').value;
    if (!strategyId) return;

    const tbody = document.getElementById('signals_body');
    const statsDiv = document.getElementById('signal_stats');
    tbody.dataset.loaded = '1';

    try {
      // Load signals and stats in parallel
      const [sigRes, statRes] = await Promise.all([
        fetch(`${API}/${strategyId}/signals?limit=50`),
        fetch(`${API}/${strategyId}/signals/statistics?days=30`),
      ]);
      const sigJson = await sigRes.json();
      const statJson = await statRes.json();

      // Stats
      const stats = statJson.data || {};
      statsDiv.innerHTML = `
        <div style="display: flex; gap: 16px; font-size: 12px; color: #94a3b8;">
          <span>전체: <strong style="color: #e2e8f0;">${stats.total_signals || 0}</strong></span>
          <span>매수: <strong style="color: #22c55e;">${stats.buy_signals || 0}</strong></span>
          <span>매도: <strong style="color: #ef4444;">${stats.sell_signals || 0}</strong></span>
          <span>승률: <strong style="color: #f59e0b;">${(stats.win_rate || 0).toFixed(1)}%</strong></span>
          <span>총 손익: <strong style="color: ${(stats.total_pnl || 0) >= 0 ? '#22c55e' : '#ef4444'};">${(stats.total_pnl || 0).toLocaleString()}</strong></span>
        </div>`;

      // Signals table
      const signals = sigJson.data?.signals || [];
      if (!signals.length) {
        tbody.innerHTML = '<tr><td colspan="8" class="placeholder">시그널 이력 없음</td></tr>';
        return;
      }

      tbody.innerHTML = signals.map(s => {
        const typeColor = s.signal_type === 'buy' ? '#22c55e' : '#ef4444';
        const pnlRatio = s.realized_pnl_ratio != null ? `${(Number(s.realized_pnl_ratio) * 100).toFixed(2)}%` : '-';
        const pnlColor = s.realized_pnl_ratio > 0 ? '#22c55e' : s.realized_pnl_ratio < 0 ? '#ef4444' : '#94a3b8';
        return `
          <tr>
            <td>${new Date(s.signal_at).toLocaleString('ko-KR')}</td>
            <td>${esc(s.symbol)}</td>
            <td style="color: ${typeColor}; font-weight: 600;">${s.signal_type === 'buy' ? '매수' : '매도'}</td>
            <td>${esc(s.signal_status)}</td>
            <td>${Number(s.signal_price).toLocaleString()}</td>
            <td>${s.target_quantity || '-'}</td>
            <td style="color: ${pnlColor};">${pnlRatio}</td>
            <td style="font-size: 11px; color: #64748b;">${esc(s.exit_reason || s.note || '')}</td>
          </tr>`;
      }).join('');
    } catch (e) {
      tbody.innerHTML = `<tr><td colspan="8" class="placeholder">시그널 로드 실패: ${esc(e.message)}</td></tr>`;
    }
  }

  // ==================== Helpers ====================

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&#39;');
  }

  // ==================== Init ====================

  window.openActivateModal = openActivateModal;
  window.closeModal = closeModal;
  window.confirmActivate = confirmActivate;
  window.loadMyStrategies = loadMyStrategies;
  window.controlStrategy = controlStrategy;
  window.deleteStrategy = deleteStrategy;
  window.toggleExpand = toggleExpand;
  window.toggleSignals = toggleSignals;
  window.loadSignals = loadSignals;

  document.addEventListener('DOMContentLoaded', () => {
    loadPresets();
    loadMyStrategies();
  });

  // Close modal on overlay click
  document.addEventListener('click', (e) => {
    if (e.target.id === 'activate_modal') {
      closeModal();
    }
  });
})();
