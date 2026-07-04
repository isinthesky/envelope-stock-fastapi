(function () {
  const shared = window.StrategyShared || {};
  const escapeHtml = shared.escapeHtml || ((value) => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;'));

  const qs = (selector) => document.querySelector(selector);
  const formatRatio = (value) => value == null ? '-' : `${(Number(value) * 100).toFixed(2)}%`;
  const formatNumber = (value) => value == null ? '-' : Number(value).toLocaleString('ko-KR');
  const dateToCompact = (value) => String(value || '').replaceAll('-', '');

  const renderMessage = (message, tone = '') => {
    const container = qs('#preregistered_research_container');
    if (!container) return;
    container.innerHTML = `<div class="placeholder-message ${tone}">${escapeHtml(message)}</div>`;
  };

  const renderResult = (data) => {
    const container = qs('#preregistered_research_container');
    if (!container) return;
    const rows = data?.out_of_sample || [];
    const symbolRows = data?.symbols || [];
    const definitionRows = data?.frozen_candidate_definitions || [];
    const definitions = new Map(definitionRows.map((item) => [item.candidate_id, item.definition_hash]));
    const resultRows = rows.length ? rows.map((item) => `
      <tr>
        <td><strong>${escapeHtml(item.candidate_id)}</strong><br><span class="hash-chip">${escapeHtml(item.definition_hash || definitions.get(item.candidate_id) || '-')}</span></td>
        <td>${escapeHtml(item.description || '-')}</td>
        <td>${formatNumber(item.rows_evaluated)}</td>
        <td>${formatNumber(item.trigger_count)}</td>
        <td>${formatNumber(item.peak_hit_count)}</td>
        <td>${formatRatio(item.precision)}</td>
        <td>${formatRatio(item.avg_future_drawdown_10d)}</td>
        <td>${formatRatio(item.avg_future_return_10d)}</td>
        <td>${formatRatio(item.avg_trade_impact_10d)}</td>
      </tr>
    `).join('') : '<tr><td colspan="9" style="text-align:center; color:#94a3b8;">OOS 결과가 없습니다.</td></tr>';

    const symbolHtml = symbolRows.length ? symbolRows.map((item) => `
      <li><span>${escapeHtml(item.symbol)}</span><strong>${formatNumber(item.rows)} rows / ${formatNumber(item.peak_labels)} peaks</strong></li>
    `).join('') : '<li><span>데이터 없음</span><span>-</span></li>';

    container.innerHTML = `
      <div class="result-header">
        <h3>사전등록 규칙 OOS 결과</h3>
        <div style="font-size: 12px; color: #64748b;">
          ${escapeHtml(data?.start_date || '')} ~ ${escapeHtml(data?.end_date || '')}
          ${data?.data_snooping_warning ? ' · data-snooping warning' : ''}
        </div>
      </div>
      <div class="universe-ranking" style="grid-template-columns: 1fr;">
        <div class="panel">
          <h4>심볼 데이터</h4>
          <ul>${symbolHtml}</ul>
        </div>
      </div>
      <div class="table-wrap" style="margin-top: 16px; overflow-x: auto;">
        <table class="history-table">
          <thead>
            <tr>
              <th>Candidate / Hash</th>
              <th>Description</th>
              <th>Rows</th>
              <th>Trigger</th>
              <th>Peak Hit</th>
              <th>Precision</th>
              <th>Drawdown 10D</th>
              <th>Return 10D</th>
              <th>Impact 10D</th>
            </tr>
          </thead>
          <tbody>${resultRows}</tbody>
        </table>
      </div>
    `;
  };

  const runPreregisteredResearch = async () => {
    const symbols = qs('#preregistered_symbols')?.value.trim();
    const startDate = dateToCompact(qs('#preregistered_start_date')?.value);
    const endDate = dateToCompact(qs('#preregistered_end_date')?.value);
    if (!startDate || !endDate) {
      alert('시작일과 종료일을 입력해주세요.');
      return;
    }
    const params = new URLSearchParams({ start_date: startDate, end_date: endDate });
    if (symbols) params.set('symbols', symbols);
    renderMessage('사전등록 규칙 리서치 실행 중...');
    try {
      const response = await fetch(`/api/v1/strategies/sell-rules/preregistered/research?${params.toString()}`);
      const payload = await response.json().catch(() => null);
      if (!response.ok || payload?.success === false) {
        const detail = payload?.detail || payload?.message || `HTTP ${response.status}`;
        throw new Error(response.status === 404
          ? '사전등록 리서치 API를 찾을 수 없습니다. 서버 라우터 등록과 배포 버전을 확인하세요.'
          : detail);
      }
      renderResult(payload.data || payload);
    } catch (error) {
      renderMessage(`리서치 실패: ${error.message}`, 'negative');
    }
  };

  document.addEventListener('DOMContentLoaded', () => {
    qs('#preregistered_research_btn')?.addEventListener('click', runPreregisteredResearch);
  });
})();
