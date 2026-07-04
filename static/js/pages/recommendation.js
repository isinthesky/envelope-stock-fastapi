(function () {
  const shared = window.StrategyShared || {};
  const escapeHtml = shared.escapeHtml || ((value) => String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;'));

  const state = {
    ruleSets: [],
    candidates: [],
    candidateMeta: null,
    sortKey: 'final_score',
    sortDir: 'desc',
  };

  const qs = (selector) => document.querySelector(selector);
  const qsa = (selector) => Array.from(document.querySelectorAll(selector));
  const valueOf = (selector) => qs(selector)?.value || '';
  const checked = (selector) => !!qs(selector)?.checked;
  const num = (value, fallback = 0) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  };
  const fmtNum = (value) => value == null ? '-' : Number(value).toLocaleString('ko-KR');
  const fmtScore = (value) => value == null ? '미평가' : Number(value).toFixed(1);
  const cssToken = (value) => String(value ?? '').replace(/[^a-zA-Z0-9_-]/g, '');
  const dateValue = (selector) => valueOf(selector);

  const setBanner = (message, warning = false) => {
    const banner = qs('#recommendation_auth_banner');
    if (!banner) return;
    banner.hidden = !message;
    banner.classList.toggle('warning', warning);
    banner.textContent = message || '';
  };

  const formatDetail = (detail) => {
    if (Array.isArray(detail)) {
      return detail.map((item) => {
        if (item && typeof item === 'object') {
          const loc = Array.isArray(item.loc) ? item.loc.join('.') : '';
          return `${loc ? `${loc}: ` : ''}${item.msg || JSON.stringify(item)}`;
        }
        return String(item);
      }).join(' / ');
    }
    if (detail && typeof detail === 'object') {
      return detail.message || detail.msg || JSON.stringify(detail);
    }
    return String(detail);
  };

  const readResponse = async (response) => {
    const payload = await response.json().catch(() => null);
    if (!response.ok || payload?.success === false) {
      const detail = payload?.detail || payload?.message || payload?.error || `HTTP ${response.status}`;
      const message = formatDetail(detail);
      throw new Error(response.status === 403 ? `관리자 접근이 필요합니다: ${message}` : message);
    }
    return payload?.data ?? payload;
  };

  const fetchData = async (url, options = {}) => {
    const response = await fetch(url, options);
    return readResponse(response);
  };

  const setLoadingRow = (tbodyId, colspan, message) => {
    const tbody = qs(tbodyId);
    if (tbody) {
      tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty-cell">${escapeHtml(message)}</td></tr>`;
    }
  };

  const activeRuleSets = () => state.ruleSets.filter((item) => item.status === 'active');
  const draftRuleSets = () => state.ruleSets.filter((item) => item.status === 'draft');

  const renderRuleSetOptions = () => {
    const scanSelect = qs('#rec_rule_set_id');
    const validateSelect = qs('#validate_rule_id');
    if (scanSelect) {
      scanSelect.innerHTML = '<option value="">기본 파라미터</option>' + activeRuleSets().map((item) =>
        `<option value="${escapeHtml(item.rule_id)}">${escapeHtml(item.name)} v${fmtNum(item.version)}</option>`
      ).join('');
    }
    if (validateSelect) {
      const drafts = draftRuleSets();
      validateSelect.innerHTML = drafts.length
        ? drafts.map((item) => `<option value="${escapeHtml(item.rule_id)}">${escapeHtml(item.name)} (${item.candidates?.length || 0})</option>`).join('')
        : '<option value="">검증할 draft 룰셋 없음</option>';
    }
  };

  const renderRuleSets = () => {
    const tbody = qs('#rule_set_rows');
    if (!tbody) return;
    if (!state.ruleSets.length) {
      tbody.innerHTML = '<tr><td colspan="5" class="empty-cell">등록된 룰셋이 없습니다.</td></tr>';
      renderRuleSetOptions();
      return;
    }
    tbody.innerHTML = state.ruleSets.map((item) => {
      const status = cssToken(item.status);
      const hash = item.frozen_hash ? `${escapeHtml(item.frozen_hash.slice(0, 16))}` : '-';
      return `
        <tr>
          <td class="metric-num">${escapeHtml(item.rule_id)}</td>
          <td>${escapeHtml(item.name)} <span class="metric-num">v${fmtNum(item.version)}</span></td>
          <td><span class="rule-status-badge rule-status-${status}">${escapeHtml(item.status)}</span></td>
          <td>${fmtNum(item.candidates?.length || 0)}</td>
          <td><span class="hash-chip">${hash}</span></td>
        </tr>
      `;
    }).join('');
    renderRuleSetOptions();
  };

  const loadRuleSets = async () => {
    setLoadingRow('#rule_set_rows', 5, '룰셋 목록을 불러오는 중입니다.');
    try {
      const data = await fetchData('/api/v1/recommendations/rule-sets?limit=100&offset=0');
      state.ruleSets = data.rule_sets || [];
      renderRuleSets();
      setBanner('');
    } catch (error) {
      state.ruleSets = [];
      renderRuleSets();
      setBanner(error.message, true);
    }
  };

  const candidateScore = (candidate, key) => {
    if (key in candidate) return candidate[key];
    return candidate.scorecard?.[key];
  };

  const sortedCandidates = () => {
    const dir = state.sortDir === 'asc' ? 1 : -1;
    return [...state.candidates].sort((a, b) => {
      const av = candidateScore(a, state.sortKey);
      const bv = candidateScore(b, state.sortKey);
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      if (typeof av === 'number' || typeof bv === 'number') return (Number(av) - Number(bv)) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  };

  const renderCandidateSummary = () => {
    const summary = qs('#candidate_summary');
    const errors = qs('#candidate_errors');
    const meta = state.candidateMeta;
    if (!summary || !meta) return;
    summary.hidden = false;
    summary.innerHTML = [
      ['Scanned', fmtNum(meta.total_scanned)],
      ['Candidates', fmtNum(meta.candidate_count)],
      ['Generated', meta.generated_at ? new Date(meta.generated_at).toLocaleString('ko-KR') : '-'],
      ['Sort', `${state.sortKey} ${state.sortDir}`],
    ].map(([label, value]) => `
      <div class="summary-item"><div class="label">${label}</div><div class="value">${escapeHtml(value)}</div></div>
    `).join('');
    const messages = meta.errors || [];
    if (errors) {
      errors.hidden = messages.length === 0;
      errors.textContent = messages.length ? `스캔 경고: ${messages.join(' / ')}` : '';
    }
  };

  const renderCandidates = () => {
    const tbody = qs('#candidate_rows');
    if (!tbody) return;
    if (!state.candidates.length) {
      tbody.innerHTML = '<tr><td colspan="10" class="empty-cell">표시할 후보가 없습니다.</td></tr>';
      renderCandidateSummary();
      return;
    }
    tbody.innerHTML = sortedCandidates().map((item) => {
      const score = item.scorecard || {};
      const readiness = cssToken(item.readiness_label);
      const missing = item.missing_evidence || [];
      const blocked = item.blocked_actions || [];
      return `
        <tr>
          <td><strong>${escapeHtml(item.symbol)}</strong><br><span>${escapeHtml(item.name)}</span></td>
          <td>${escapeHtml(item.market)}</td>
          <td class="metric-num hide-mobile">${fmtNum(item.current_price)}</td>
          <td class="hide-mobile">${escapeHtml(item.technical_state)}</td>
          <td class="metric-num hide-mobile">${fmtScore(score.technical_score)}</td>
          <td class="metric-num hide-mobile">${fmtScore(score.fundamental_score)}</td>
          <td class="metric-num hide-mobile">${fmtScore(score.quant_score)}</td>
          <td class="metric-num"><strong>${fmtScore(score.final_score)}</strong></td>
          <td><span class="readiness-badge readiness-${readiness}">${escapeHtml(item.readiness_label)}</span></td>
          <td class="hide-mobile">
            <div class="evidence-list">
              <span>Missing: ${missing.length ? missing.map(escapeHtml).join(', ') : '-'}</span>
              <span>Blocked: ${blocked.length ? blocked.map(escapeHtml).join(', ') : '-'}</span>
            </div>
          </td>
        </tr>
      `;
    }).join('');
    renderCandidateSummary();
  };

  const scanCandidates = async () => {
    const limit = Math.max(1, Math.min(5000, num(valueOf('#rec_limit'), 300)));
    if (!confirm(`추천 후보 스캔을 실행합니다. limit=${limit} 기준으로 시간이 오래 걸릴 수 있습니다.`)) return;
    const button = qs('#scan_candidates_btn');
    if (button) {
      button.disabled = true;
      button.textContent = '스캔 중...';
    }
    setLoadingRow('#candidate_rows', 10, '추천 후보 스캔 중입니다.');
    try {
      const params = new URLSearchParams({
        stoch_threshold: String(num(valueOf('#rec_stoch_threshold'), 30)),
        gc_only: String(checked('#rec_gc_only')),
        include_etf: String(checked('#rec_include_etf')),
        limit: String(limit),
      });
      const market = valueOf('#rec_market');
      const ruleSetId = valueOf('#rec_rule_set_id');
      if (market) params.set('market', market);
      if (ruleSetId) params.set('rule_set_id', ruleSetId);
      const data = await fetchData(`/api/v1/recommendations/candidates?${params.toString()}`);
      state.candidates = data.candidates || [];
      state.candidateMeta = data;
      renderCandidates();
      setBanner('');
    } catch (error) {
      state.candidates = [];
      setLoadingRow('#candidate_rows', 10, error.message);
      setBanner(error.message, true);
    } finally {
      if (button) {
        button.disabled = false;
        button.textContent = '스캔 실행';
      }
    }
  };

  const parseCandidates = () => {
    const raw = valueOf('#rule_candidates_json').trim();
    const parsed = JSON.parse(raw);
    const candidates = Array.isArray(parsed) ? parsed : parsed?.candidates;
    if (!Array.isArray(candidates) || candidates.length === 0) {
      throw new Error('후보 목록은 비어 있지 않은 배열이어야 합니다.');
    }
    candidates.forEach((item) => {
      if (!item?.candidate_id || !item?.name || !item?.rules) {
        throw new Error('각 후보에는 candidate_id, name, rules가 필요합니다.');
      }
    });
    return candidates;
  };

  const createRuleSet = async () => {
    const name = valueOf('#rule_set_name').trim();
    if (!name) {
      alert('룰셋 이름을 입력해주세요.');
      return;
    }
    try {
      const candidates = parseCandidates();
      await fetchData('/api/v1/recommendations/rule-sets', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, candidates }),
      });
      await loadRuleSets();
      alert('룰셋이 등록되었습니다.');
    } catch (error) {
      alert(`룰셋 등록 실패: ${error.message}`);
    }
  };

  const ruleSetById = (ruleId) => state.ruleSets.find((item) => item.rule_id === ruleId);

  const validateRuleSet = async () => {
    const ruleId = valueOf('#validate_rule_id');
    if (!ruleId) {
      alert('검증할 draft 룰셋이 없습니다.');
      return;
    }
    const target = ruleSetById(ruleId);
    const candidateCount = target?.candidates?.length || 0;
    if (!confirm(`룰셋 검증을 실행합니다. 후보 ${candidateCount}개 x 2회 백테스트가 실행될 수 있습니다.`)) return;
    const resultBox = qs('#validation_result');
    if (resultBox) {
      resultBox.hidden = false;
      resultBox.innerHTML = '<div class="empty-cell">walk-forward 검증 실행 중...</div>';
    }
    try {
      const body = {
        train_start: dateValue('#validate_train_start'),
        train_end: dateValue('#validate_train_end'),
        test_start: dateValue('#validate_test_start'),
        test_end: dateValue('#validate_test_end'),
        benchmark: valueOf('#validate_benchmark'),
        market: valueOf('#validate_market') || null,
        eligible_only: checked('#validate_eligible_only'),
        limit: num(valueOf('#validate_limit'), 20),
        selection_metric: valueOf('#validate_metric') || 'cagr',
      };
      const data = await fetchData(`/api/v1/recommendations/rule-sets/${encodeURIComponent(ruleId)}/validate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      renderValidationResult(data);
      await loadRuleSets();
    } catch (error) {
      if (resultBox) {
        resultBox.innerHTML = `<div class="status-banner">${escapeHtml(error.message)}</div>`;
      }
    }
  };

  const metricRow = (label, train, test) => `
    <tr>
      <td>${escapeHtml(label)}</td>
      <td class="metric-num">${fmtScore(train)}</td>
      <td class="metric-num">${fmtScore(test)}</td>
    </tr>
  `;

  const renderValidationResult = (data) => {
    const box = qs('#validation_result');
    if (!box) return;
    const train = data.train_metrics || {};
    const test = data.test_metrics || {};
    box.hidden = false;
    box.innerHTML = `
      <h3>검증 결과</h3>
      <div class="summary-strip">
        <div class="summary-item"><div class="label">Rule ID</div><div class="value">${escapeHtml(data.rule_id)}</div></div>
        <div class="summary-item"><div class="label">Selected</div><div class="value">${escapeHtml(data.selected_candidate_id)}</div></div>
        <div class="summary-item"><div class="label">Hash</div><div class="value hash-chip">${escapeHtml(data.selected_candidate_hash)}</div></div>
        <div class="summary-item"><div class="label">Warning</div><div class="value">${data.data_snooping_warning ? 'Data snooping' : 'None'}</div></div>
      </div>
      <table class="recommendation-table compact">
        <thead><tr><th>Metric</th><th>Train</th><th>Test</th></tr></thead>
        <tbody>
          ${metricRow('CAGR', train.cagr, test.cagr)}
          ${metricRow('Benchmark CAGR', train.benchmark_cagr, test.benchmark_cagr)}
          ${metricRow('MDD', train.mdd, test.mdd)}
          ${metricRow('Sharpe', train.sharpe, test.sharpe)}
          ${metricRow('Turnover', train.turnover, test.turnover)}
        </tbody>
      </table>
      <pre>${escapeHtml(data.report_markdown || '')}</pre>
    `;
  };

  const bindTabs = () => {
    qsa('.tab-button').forEach((button) => {
      button.addEventListener('click', () => {
        const tab = button.dataset.tab;
        qsa('.tab-button').forEach((item) => item.classList.toggle('active', item === button));
        qsa('[data-panel]').forEach((panel) => {
          panel.hidden = panel.dataset.panel !== tab;
        });
      });
    });
  };

  const bindSort = () => {
    qsa('.recommendation-table th[data-sort]').forEach((th) => {
      th.addEventListener('click', () => {
        const key = th.dataset.sort;
        if (state.sortKey === key) {
          state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
        } else {
          state.sortKey = key;
          state.sortDir = key === 'final_score' ? 'desc' : 'asc';
        }
        renderCandidates();
      });
    });
  };

  document.addEventListener('DOMContentLoaded', () => {
    bindTabs();
    bindSort();
    qs('#scan_candidates_btn')?.addEventListener('click', scanCandidates);
    qs('#refresh_rule_sets_btn')?.addEventListener('click', loadRuleSets);
    qs('#create_rule_set_btn')?.addEventListener('click', createRuleSet);
    qs('#validate_rule_set_btn')?.addEventListener('click', validateRuleSet);
    loadRuleSets();
  });
})();
