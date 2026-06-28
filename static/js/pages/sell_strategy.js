let analysisHistory = [];
let selectedHistoryId = null;
let analysisInProgress = false;
let cashPlanInProgress = false;

const escapeHtml = (v) => String(v ?? '')
  .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;').replace(/'/g, '&#39;');

// CSS class name에 사용할 문자만 허용 (attribute injection 방지)
const sanitizeCssClass = (v) => String(v ?? '').replace(/[^a-zA-Z0-9_-]/g, '');

// 숫자 필드 안전 렌더링 (API에서 오는 숫자형 값)
const safeNum = (v, fallback = '-') =>
  Number.isFinite(Number(v)) ? String(Number(v)) : escapeHtml(String(fallback));

/**
 * Canvas 기반 수평 게이지 차트 (격자 포함)
 * @param {string} id - canvas element ID
 * @param {number} value - 현재 값
 * @param {number} min - 최솟값
 * @param {number} max - 최댓값
 * @param {object} opts - { ticks, zones, highThreshold, lowThreshold, barColor }
 */
const drawGauge = (id, value, min, max, opts = {}) => {
  const canvas = document.getElementById(id);
  if (!canvas || !canvas.getContext) return;
  if (!Number.isFinite(Number(value))) return;
  if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const dpr = window.devicePixelRatio || 1;
  const W = canvas.offsetWidth;
  if (W <= 0) {
    // 레이아웃 미완료 — ResizeObserver로 재시도 (이전 observer 해제 후 교체)
    if (canvas._gaugeZeroRo) canvas._gaugeZeroRo.disconnect();
    if (window.ResizeObserver) {
      const ro = new ResizeObserver((entries, observer) => {
        const w = entries[0]?.contentRect.width;
        if (w > 0) {
          observer.disconnect();
          canvas._gaugeZeroRo = null;
          drawGauge(id, value, min, max, opts);
        }
      });
      ro.observe(canvas);
      canvas._gaugeZeroRo = ro;
    }
    return;
  }

  const H = 40;
  canvas.width = W * dpr;
  canvas.height = H * dpr;
  canvas.style.width = W + 'px';
  canvas.style.height = H + 'px';

  ctx.scale(dpr, dpr);

  const PAD = { left: 2, right: 2, top: 4, bottom: 14 };
  const chartW = W - PAD.left - PAD.right;
  const chartH = H - PAD.top - PAD.bottom;
  const clamp = (v) => Math.min(Math.max(v, min), max);
  const toX = (v) => PAD.left + ((clamp(v) - min) / (max - min)) * chartW;

  // 배경
  ctx.fillStyle = '#f8fafc';
  ctx.fillRect(0, 0, W, H);

  // 구간 색상 (zones)
  (opts.zones || []).forEach(z => {
    ctx.fillStyle = z.color;
    ctx.fillRect(toX(z.from), PAD.top, toX(z.to) - toX(z.from), chartH);
  });

  // 값 막대
  const vx = toX(value);
  const high = opts.highThreshold ?? max;
  const low = opts.lowThreshold ?? min;
  const barColor = opts.barColor
    || (value >= high ? '#dc2626' : value <= low ? '#16a34a' : '#3b82f6');
  ctx.fillStyle = barColor;
  ctx.globalAlpha = 0.65;
  ctx.fillRect(PAD.left, PAD.top, vx - PAD.left, chartH);
  ctx.globalAlpha = 1;

  // 격자선 (gridlines)
  const ticks = opts.ticks || [min, (min + max) / 2, max];
  ticks.forEach(tick => {
    const x = toX(tick);
    ctx.strokeStyle = '#cbd5e1';
    ctx.lineWidth = 1;
    ctx.setLineDash([2, 2]);
    ctx.beginPath();
    ctx.moveTo(x, PAD.top);
    ctx.lineTo(x, PAD.top + chartH);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.fillStyle = '#94a3b8';
    ctx.font = '8px ui-sans-serif,system-ui,sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(tick, x, H - 2);
  });

  // 현재값 마커
  ctx.strokeStyle = '#1e293b';
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(vx, PAD.top);
  ctx.lineTo(vx, PAD.top + chartH);
  ctx.stroke();
};

const SELL_LAST_ANALYSIS_KEY = 'sellStrategy.lastAnalysis';
const SELL_LAST_REFRESH_KEY = 'sellStrategy.lastRefresh';
const CACHE_SCHEMA_VERSION = 1;
const CACHE_TTL_MS = 3600000;  // 1시간
const ANALYSIS_COOLDOWN_MS = 60000;  // 1분
const REFRESH_COOLDOWN_MS = 60000;  // 1분

const formatNumber = (n) => {
  if (n === null || n === undefined) return '-';
  return Number(n).toLocaleString();
};

const formatDateTime = (dateStr) => {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return '-';
  return date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
};

const formatTime = (dateStr) => {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return '-';
  return date.toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul' });
};

const getRelativeTime = (dateStr) => {
  if (!dateStr) return null;
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return null;

  const diff = Date.now() - date.getTime();
  if (diff < 0) return '잠시 후';

  const mins = Math.floor(diff / 60000);
  const hours = Math.floor(diff / 3600000);
  const days = Math.floor(diff / 86400000);

  if (mins < 1) return '방금 전';
  if (mins < 60) return `${mins}분 전`;
  if (hours < 24) return `${hours}시간 전`;
  return `${days}일 전`;
};

const isCacheStale = (savedAt) => {
  if (!savedAt) return true;
  return (Date.now() - savedAt) > CACHE_TTL_MS;
};

const formatPercent = (ratio) => {
  if (ratio === null || ratio === undefined) return '-';
  return (ratio * 100).toFixed(2) + '%';
};

const updateLastAnalysisLabel = (data, isStale = false) => {
  const label = document.getElementById("sell_last_analysis");
  if (!label) return;

  const timeText = formatDateTime(data?.analyzed_at);
  const relTime = getRelativeTime(data?.analyzed_at);
  const nameText = data?.symbol
    ? `${escapeHtml(data.symbol)}${data.name ? ` ${escapeHtml(data.name)}` : ''}`
    : '';

  label.classList.toggle('stale', isStale);

  const mainText = nameText
    ? `마지막 분석: ${nameText} - ${timeText}`
    : `마지막 분석: ${timeText}`;

  label.innerHTML = `
    <span class="time-badge">${relTime || '알 수 없음'}</span>
    <span>${mainText}</span>
    <span class="cache-indicator ${isStale ? 'cached' : 'fresh'}">${isStale ? '캐시됨' : '최신'}</span>
  `;
};

const saveLastAnalysis = (data) => {
  try {
    localStorage.setItem(SELL_LAST_ANALYSIS_KEY, JSON.stringify({
      schemaVersion: CACHE_SCHEMA_VERSION,
      savedAt: Date.now(),
      data
    }));
  } catch (e) {
    console.warn('Failed to save last analysis:', e);
  }
};

const loadLastAnalysis = () => {
  try {
    const raw = localStorage.getItem(SELL_LAST_ANALYSIS_KEY);
    if (!raw) return null;

    const cached = JSON.parse(raw);

    if (!cached.schemaVersion) {
      return { data: cached, isStale: true };
    }

    if (cached.schemaVersion !== CACHE_SCHEMA_VERSION) {
      localStorage.removeItem(SELL_LAST_ANALYSIS_KEY);
      return null;
    }

    const isStale = isCacheStale(cached.savedAt);
    return { data: cached.data, isStale, savedAt: cached.savedAt };
  } catch (e) {
    console.warn('Failed to load last analysis:', e);
    return null;
  }
};

const saveLastRefresh = (data) => {
  try {
    localStorage.setItem(SELL_LAST_REFRESH_KEY, JSON.stringify({
      schemaVersion: CACHE_SCHEMA_VERSION,
      savedAt: Date.now(),
      refreshedAt: data.refreshedAt,
      updated_count: data.updated_count
    }));
  } catch (e) {
    console.warn('Failed to save last refresh:', e);
  }
};

const loadLastRefresh = () => {
  try {
    const raw = localStorage.getItem(SELL_LAST_REFRESH_KEY);
    if (!raw) return null;

    const cached = JSON.parse(raw);

    if (!cached.schemaVersion || cached.schemaVersion !== CACHE_SCHEMA_VERSION) {
      localStorage.removeItem(SELL_LAST_REFRESH_KEY);
      return null;
    }

    const isStale = isCacheStale(cached.savedAt);
    return {
      data: { refreshedAt: cached.refreshedAt, updated_count: cached.updated_count },
      savedAt: cached.savedAt,
      isStale
    };
  } catch (e) {
    console.warn('Failed to load last refresh:', e);
    return null;
  }
};

const updateLastRefreshLabel = (data, isStale = false) => {
  const label = document.getElementById("sell_last_refresh");
  if (!label) return;

  const refreshedAt = data?.refreshedAt;
  const timeText = formatDateTime(refreshedAt);
  const relTime = getRelativeTime(refreshedAt);
  const countText = data?.updated_count != null ? `${safeNum(data.updated_count)}개 종목` : '';

  label.classList.toggle('stale', isStale);

  const mainText = countText
    ? `마지막 갱신: ${timeText} - ${countText} 갱신됨`
    : `마지막 갱신: ${timeText}`;

  label.innerHTML = `
    <span class="time-badge">${relTime || '알 수 없음'}</span>
    <span>${mainText}</span>
    <span class="cache-indicator ${isStale ? 'cached' : 'fresh'}">${isStale ? '캐시됨' : '최신'}</span>
  `;
};

const normalizeSellReasons = (item) => {
  let reasons = item.sell_reasons;
  if (typeof reasons === 'string') {
    try {
      reasons = JSON.parse(reasons);
    } catch (e) {
      reasons = [reasons];
    }
  }
  if (!Array.isArray(reasons)) reasons = [];
  return reasons;
};

const getStageDisplayName = (stage) => {
  const stageNames = {
    HOLD: '보유 유지',
    REDUCE_1: '1차 비중 축소',
    REDUCE_2: '2차 비중 축소',
    EXIT_ALL: '전량 청산'
  };
  return stageNames[stage] || '보유 유지';
};

const resolveDisplayStage = (item) => {
  if (item?.final_stage) return item.final_stage;
  if (item?.sell_stage) return item.sell_stage;

  const phaseToStage = {
    PHASE_2: 'REDUCE_1',
    PHASE_3: 'REDUCE_1',
    PHASE_4: 'REDUCE_2',
    PHASE_5: 'EXIT_ALL'
  };
  return phaseToStage[item?.sell_phase] || 'HOLD';
};

const getPhaseDisplayName = (phase, phaseName) => {
  const phaseNumbers = {
    'PHASE_1': 1, 'PHASE_2': 2, 'PHASE_3': 3, 'PHASE_4': 4, 'PHASE_5': 5
  };
  const num = phaseNumbers[phase];
  const safeName = escapeHtml(phaseName);
  if (num) {
    return `${safeName}(${num})`;
  }
  return safeName || '보유 유지';
};

const loadHistory = async () => {
  try {
    const response = await fetch('/api/v1/strategies/analysis-history?analysis_type=sell&limit=100');
    const data = await response.json();

    if (data.success && data.data) {
      analysisHistory = data.data.items;
      renderHistoryTable();
      loadPortfolioCashPlan();

      const latest = analysisHistory[0];
      if (latest) {
        const cached = loadLastAnalysis();
        const cachedTime = cached?.data?.analyzed_at ? new Date(cached.data.analyzed_at).getTime() : 0;
        const historyTime = latest.analyzed_at ? new Date(latest.analyzed_at).getTime() : 0;

        if (historyTime > cachedTime) {
          const historyLatest = {
            ...latest,
            sell_reasons: normalizeSellReasons(latest)
          };
          displayResult(historyLatest);
          updateLastAnalysisLabel(historyLatest, false);
        }
      }
    }
  } catch (e) {
    console.error('Failed to load history:', e);
    document.getElementById("history_body").innerHTML =
      '<tr><td colspan="10" style="text-align: center; color: #ef4444;">히스토리 로딩 실패</td></tr>';
  }
};

const renderPortfolioCashPlan = (data) => {
  const container = document.getElementById("cash_plan_container");
  if (!container) return;

  if (!data) {
    container.innerHTML = `<div class="placeholder-message">현금화 계획 데이터가 없습니다.</div>`;
    return;
  }

  const topActions = (data.actions || []).slice(0, 5);
  const displayGap = data.cash_gap_ratio !== null && data.cash_gap_ratio !== undefined
    ? data.cash_gap_ratio
    : (data.current_cash_ratio !== null && data.current_cash_ratio !== undefined
      ? (data.target_cash_ratio - data.current_cash_ratio)
      : null);
  const winnerCount = (data.actions || []).filter(action => (action.profit_ratio || 0) > 0).length;
  const immediateCount = (data.actions || []).filter(action => action.sell_stage === 'EXIT_ALL').length;

  const actionHtml = topActions.length > 0
    ? topActions.map(action => {
        const stage = action.sell_stage || 'HOLD';
        const stageClass = `stage-${sanitizeCssClass(stage)}`;
        const profitClass = (action.profit_ratio || 0) >= 0 ? 'positive' : 'negative';
        const profitText = action.profit_ratio !== null && action.profit_ratio !== undefined
          ? `<span class="cash-plan-profit ${profitClass}">${formatPercent(action.profit_ratio)}</span>`
          : '';
        const ratioText = `${Math.round((action.suggested_sell_ratio || 0) * 100)}%`;
        const reasons = (action.reasons || []).slice(0, 3).map(reason => `<li>${escapeHtml(reason)}</li>`).join('');

        return `
          <div class="cash-plan-action">
            <div class="cash-plan-action-header">
              <div>
                <strong>${parseInt(action.priority, 10) || 0}. ${escapeHtml(action.symbol)}${action.name ? ` ${escapeHtml(action.name)}` : ''}</strong>
                <div style="font-size: 12px; color: #64748b; margin-top: 4px;">${escapeHtml(action.action)}</div>
              </div>
              <div class="cash-plan-action-meta">
                ${profitText}
                <span class="stage-badge ${stageClass}" style="font-size: 11px; padding: 4px 8px;">${getStageDisplayName(stage)}</span>
                <span class="recommendation-badge recommendation-CONSIDER_SELL" style="font-size: 11px; padding: 4px 8px;">권장 ${ratioText}</span>
              </div>
            </div>
            ${action.note ? `<div class="cash-plan-note">${escapeHtml(action.note)}</div>` : ''}
            ${reasons ? `<div class="cash-plan-reasons"><ul>${reasons}</ul></div>` : ''}
          </div>
        `;
      }).join('')
    : `<div class="placeholder-message">우선 정리할 종목이 없습니다.</div>`;

  container.innerHTML = `
    <div class="result-header">
      <h3>포트폴리오 현금화 요약</h3>
      <div style="font-size: 12px; color: #64748b;">${formatDateTime(data.analyzed_at)}</div>
    </div>
    <div class="cash-plan-grid">
      <div class="cash-plan-card">
        <div class="label">목표 / 현재 현금</div>
        <div class="value" style="font-size: 18px;">${formatPercent(data.target_cash_ratio)} / ${data.current_cash_ratio !== null && data.current_cash_ratio !== undefined ? formatPercent(data.current_cash_ratio) : '-'}</div>
      </div>
      <div class="cash-plan-card">
        <div class="label">현금 격차</div>
        <div class="value" style="font-size: 18px; ${displayGap !== null && displayGap > 0 ? 'color: #dc2626;' : 'color: #166534;'}">${displayGap !== null ? formatPercent(displayGap) : '-'}</div>
      </div>
      <div class="cash-plan-card">
        <div class="label">위험 점수 / 과열도</div>
        <div class="value" style="font-size: 18px;">${Number(data.market_risk_score || 0).toFixed(1)} / ${escapeHtml(data.market_heat_level)}</div>
      </div>
      <div class="cash-plan-card">
        <div class="label">활성 종목 / 수익 종목</div>
        <div class="value" style="font-size: 18px;">${safeNum(data.active_sell_count)} / ${safeNum(winnerCount)}</div>
      </div>
      <div class="cash-plan-card">
        <div class="label">즉시 정리 후보</div>
        <div class="value" style="font-size: 18px;">${safeNum(immediateCount)}</div>
      </div>
    </div>
    <div class="cash-plan-summary">
      <strong>${escapeHtml(data.portfolio_action)}</strong>
      <ul>
        ${(data.summary || []).map(line => `<li>${escapeHtml(line)}</li>`).join('')}
      </ul>
    </div>
    <div class="cash-plan-actions">
      ${actionHtml}
    </div>
  `;
};

const loadPortfolioCashPlan = async () => {
  if (cashPlanInProgress) return;

  const targetRaw = document.getElementById("cash_plan_target_ratio")?.value || '30';
  const currentRaw = document.getElementById("cash_plan_current_ratio")?.value || '';
  const targetRatio = Number(targetRaw) / 100;
  const currentRatio = currentRaw === '' ? null : Number(currentRaw) / 100;

  if (Number.isNaN(targetRatio) || targetRatio < 0 || targetRatio > 1) {
    alert('목표 현금 비중은 0~100 사이여야 합니다.');
    return;
  }
  if (currentRatio !== null && (Number.isNaN(currentRatio) || currentRatio < 0 || currentRatio > 1)) {
    alert('현재 현금 비중은 0~100 사이여야 합니다.');
    return;
  }

  cashPlanInProgress = true;
  const container = document.getElementById("cash_plan_container");
  if (container) {
    container.innerHTML = `<div class="placeholder-message">현금화 계획 계산 중...</div>`;
  }

  let url = `/api/v1/strategies/portfolio-cash-plan?target_cash_ratio=${targetRatio.toFixed(4)}`;
  if (currentRatio !== null) {
    url += `&current_cash_ratio=${currentRatio.toFixed(4)}`;
  }

  try {
    const response = await fetch(url);
    const result = await response.json();
    if (result.success && result.data) {
      renderPortfolioCashPlan(result.data);
    } else {
      if (container) {
        container.innerHTML = `<div class="placeholder-message" style="color:#dc2626;">현금화 계획 조회 실패</div>`;
      }
    }
  } catch (e) {
    console.error('Failed to load portfolio cash plan:', e);
    if (container) {
      container.innerHTML = `<div class="placeholder-message" style="color:#dc2626;">현금화 계획 조회 실패</div>`;
    }
  } finally {
    cashPlanInProgress = false;
  }
};

const canAnalyze = () => {
  if (analysisInProgress) {
    return { allowed: false, reason: '분석 진행 중...' };
  }

  const cached = loadLastAnalysis();
  if (!cached?.savedAt) return { allowed: true };

  const elapsed = Date.now() - cached.savedAt;
  if (elapsed < ANALYSIS_COOLDOWN_MS) {
    const remaining = Math.ceil((ANALYSIS_COOLDOWN_MS - elapsed) / 1000);
    return {
      allowed: false,
      reason: `${remaining}초 후 재분석 가능`,
      forceAllowed: true
    };
  }
  return { allowed: true };
};

const analyzeSellSignal = async (forceRefresh = false) => {
  const symbol = document.getElementById("symbol_input").value.trim();
  if (!symbol) {
    alert("종목코드를 입력해주세요.");
    return;
  }

  if (!forceRefresh) {
    const check = canAnalyze();
    if (!check.allowed) {
      if (check.forceAllowed) {
        if (!confirm(`${check.reason}\n강제로 다시 분석하시겠습니까?`)) {
          return;
        }
      } else {
        alert(check.reason);
        return;
      }
    }
  }

  const stochThreshold = document.getElementById("stoch_threshold").value || 70;
  const rsiThreshold = document.getElementById("rsi_threshold").value || 70;
  const entryPrice = document.getElementById("entry_price_input").value;
  const strategyId = document.getElementById("strategy_id_input")?.value;

  analysisInProgress = true;
  document.getElementById("scan_output").style.display = "block";
  document.getElementById("scan_output").textContent = `${symbol} 분석 중... (OHLCV 데이터 조회 및 지표 계산)`;

  let url = `/api/v1/strategies/sell-signal/${symbol}?stoch_overbought=${stochThreshold}&rsi_overbought=${rsiThreshold}`;
  if (entryPrice) {
    url += `&entry_price=${entryPrice}`;
  } else if (strategyId) {
    url += `&strategy_id=${strategyId}`;
  }

  try {
    const response = await fetch(url);
    const data = await response.json();

    if (data.success && data.data) {
      if (!data.data.analyzed_at) {
        data.data.analyzed_at = new Date().toISOString();
      }
      displayResult(data.data);
      updateLastAnalysisLabel(data.data);
      saveLastAnalysis(data.data);
      await saveToHistory(data.data);
      document.getElementById("scan_output").textContent = `분석 완료: ${symbol}`;
    } else {
      document.getElementById("scan_output").textContent = `오류: ${data.error || data.detail || '알 수 없는 오류'}`;
    }
  } catch (e) {
    document.getElementById("scan_output").textContent = `오류: ${e.message}`;
  } finally {
    analysisInProgress = false;
  }
};

const saveToHistory = async (data) => {
  try {
    const payload = {
      analysis_type: 'sell',
      symbol: data.symbol,
      name: data.name || null,
      current_price: data.current_price,
      ma_short: data.ma_short,
      ma_long: data.ma_long,
      ma_gap_ratio: data.ma_gap_ratio,
      stoch_k: data.stoch_k,
      stoch_d: data.stoch_d,
      rsi: data.rsi,
      is_death_cross: data.is_death_cross,
      is_stoch_overbought: data.is_stoch_overbought,
      is_rsi_overbought: data.is_rsi_overbought,
      sell_phase: data.sell_phase,
      sell_reasons: data.sell_reasons,
      sell_stage: data.final_stage || data.sell_stage,
      sell_ratio_min: data.final_ratio_min ?? data.sell_ratio_min,
      sell_ratio_max: data.final_ratio_max ?? data.sell_ratio_max,
      volume_ratio: data.volume_ratio,
      is_volume_spike: data.is_volume_spike,
      is_volume_sell_signal: data.is_volume_sell_signal,
      adx: data.adx,
      plus_di: data.plus_di,
      minus_di: data.minus_di,
      is_strong_uptrend: data.is_strong_uptrend,
      overbought_sell_blocked: data.overbought_sell_blocked,
      is_active: true
    };

    const response = await fetch('/api/v1/strategies/analysis-history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    if (result.success && result.data) {
      analysisHistory.unshift({
        ...result.data,
        sell_stage: payload.sell_stage,
        sell_stage_name: getStageDisplayName(payload.sell_stage),
        sell_ratio_min: payload.sell_ratio_min,
        sell_ratio_max: payload.sell_ratio_max
      });
      renderHistoryTable();
      loadPortfolioCashPlan();
    }
  } catch (e) {
    console.error('Failed to save history:', e);
  }
};

const deleteHistory = async (id, event) => {
  event.stopPropagation();
  if (!confirm('이 분석 기록을 삭제하시겠습니까?')) return;

  try {
    const response = await fetch(`/api/v1/strategies/analysis-history/${id}`, {
      method: 'DELETE'
    });

    if (response.ok) {
      analysisHistory = analysisHistory.filter(h => h.id !== id);
      renderHistoryTable();
      loadPortfolioCashPlan();
      if (selectedHistoryId === id) {
        document.getElementById("result_section").style.display = "none";
        selectedHistoryId = null;
      }
    }
  } catch (e) {
    console.error('Failed to delete history:', e);
    alert('삭제 실패');
  }
};

const toggleActive = async (id, event) => {
  event.stopPropagation();
  const item = analysisHistory.find(h => h.id === id);
  if (!item) return;

  const newActive = !item.is_active;

  try {
    const response = await fetch(`/api/v1/strategies/analysis-history/${id}/active?is_active=${newActive}`, {
      method: 'PATCH'
    });

    const result = await response.json();
    if (result.success && result.data) {
      const idx = analysisHistory.findIndex(h => h.id === id);
      if (idx >= 0) {
        analysisHistory[idx] = result.data;
        renderHistoryTable();
        loadPortfolioCashPlan();
      }
    }
  } catch (e) {
    console.error('Failed to toggle active:', e);
  }
};

let refreshInProgress = false;

const canRefresh = () => {
  if (refreshInProgress) {
    return { allowed: false, reason: '갱신 진행 중...' };
  }

  const cached = loadLastRefresh();
  if (!cached?.savedAt) return { allowed: true };

  const elapsed = Date.now() - cached.savedAt;
  if (elapsed < REFRESH_COOLDOWN_MS) {
    const remaining = Math.ceil((REFRESH_COOLDOWN_MS - elapsed) / 1000);
    return {
      allowed: false,
      reason: `${remaining}초 후 재갱신 가능`,
      forceAllowed: true
    };
  }
  return { allowed: true };
};

const refreshHistory = async (forceRefresh = false) => {
  if (!forceRefresh) {
    const check = canRefresh();
    if (!check.allowed) {
      if (check.forceAllowed) {
        if (!confirm(`${check.reason}\n강제로 다시 갱신하시겠습니까?`)) {
          return;
        }
      } else {
        alert(check.reason);
        return;
      }
    }
  }

  const tbody = document.getElementById("history_body");
  const refreshBtn = document.querySelector('.history-section .btn-refresh');
  tbody.classList.add('loading');
  refreshInProgress = true;

  if (refreshBtn) {
    refreshBtn.disabled = true;
    refreshBtn.textContent = '갱신 중...';
  }

  try {
    const response = await fetch('/api/v1/strategies/analysis-history/refresh?analysis_type=sell', {
      method: 'POST'
    });

    const result = await response.json();
    if (result.success && result.data) {
      const items = result.data.items || [];
      items.forEach(updated => {
        const idx = analysisHistory.findIndex(h => h.symbol === updated.symbol && h.is_active);
        if (idx >= 0) {
          analysisHistory[idx] = updated;
        }
      });
      renderHistoryTable();

      const updatedCount = result.data.updated_count ?? items.length ?? 0;
      const refreshData = {
        updated_count: updatedCount,
        refreshedAt: new Date().toISOString()
      };
      saveLastRefresh(refreshData);
      updateLastRefreshLabel(refreshData, false);
      loadPortfolioCashPlan();

      alert(`${updatedCount}개 종목 갱신 완료`);
    } else {
      const errorMsg = result.message || result.error || '알 수 없는 오류';
      alert(`갱신 실패: ${errorMsg}`);
    }
  } catch (e) {
    console.error('Failed to refresh:', e);
    alert(`갱신 실패: ${e.message}`);
  } finally {
    tbody.classList.remove('loading');
    refreshInProgress = false;

    if (refreshBtn) {
      refreshBtn.disabled = false;
      refreshBtn.textContent = '활성 종목 갱신';
    }
  }
};

const showHistoryDetail = (id) => {
  const item = analysisHistory.find(h => h.id === id);
  if (!item) return;

  selectedHistoryId = id;

  displayResult({
    ...item,
    sell_reasons: normalizeSellReasons(item)
  });
  updateLastAnalysisLabel(item);
  renderHistoryTable();
};

const displayResult = (data) => {
  document.getElementById("result_section").style.display = "block";

  const displayStage = resolveDisplayStage(data);
  const phaseClass = `phase-${sanitizeCssClass(data.sell_phase || 'NONE')}`;
  const stageClass = `stage-${sanitizeCssClass(displayStage)}`;

  const stochStatus = data.is_stoch_overbought ? 'status-danger' : 'status-safe';
  const rsiStatus = data.is_rsi_overbought ? 'status-danger' : 'status-safe';
  const maStatus = data.is_death_cross ? 'status-danger' : 'status-safe';

  const sellReasons = data.sell_reasons || [];
  const stageReasons = data.sell_stage_reasons || [];

  const stages = ['HOLD', 'REDUCE_1', 'REDUCE_2', 'EXIT_ALL'];
  const stageNames = ['보유 유지', '1차 축소 (20~30%)', '2차 축소 (30~40%)', '전량 청산 (100%)'];
  const currentStage = displayStage;
  const stageIdx = stages.indexOf(currentStage);

  const stageIndicatorHtml = stages.map((s, i) => {
    let activeClass = '';
    if (i === stageIdx) {
      activeClass = i >= 3 ? 'active critical' : (i >= 2 ? 'active danger' : (i >= 1 ? 'active' : ''));
    }
    return `<div class="phase-step ${activeClass}">${stageNames[i]}</div>`;
  }).join('');

  let profitSectionHtml = '';
  if (data.profit_ratio !== null && data.profit_ratio !== undefined) {
    const profitClass = data.profit_ratio >= 0 ? '' : 'loss';
    const valueClass = data.profit_ratio >= 0 ? 'positive' : 'negative';
    profitSectionHtml = `
      <div class="profit-section ${profitClass}">
        <h4>${data.profit_ratio >= 0 ? '수익 정보' : '손실 정보'}</h4>
        <div class="profit-grid">
          <div class="profit-item">
            <div class="label">진입가</div>
            <div class="value">${formatNumber(data.entry_price)}</div>
          </div>
          <div class="profit-item">
            <div class="label">현재가</div>
            <div class="value">${formatNumber(data.current_price)}</div>
          </div>
          <div class="profit-item">
            <div class="label">수익률</div>
            <div class="value ${valueClass}">${formatPercent(data.profit_ratio)}</div>
          </div>
          <div class="profit-item">
            <div class="label">적용 임계값</div>
            <div class="value" style="font-size: 14px;">Stoch ${safeNum(data.dynamic_stoch_threshold, 70)} / RSI ${safeNum(data.dynamic_rsi_threshold, 70)}</div>
          </div>
          ${data.is_stop_loss_triggered ? '<div class="profit-item"><div class="label">상태</div><div class="value negative">손절 라인</div></div>' : ''}
          ${data.is_take_profit_triggered ? '<div class="profit-item"><div class="label">상태</div><div class="value positive">익절 목표</div></div>' : ''}
        </div>
      </div>
    `;
  }

  let trailingStopHtml = '';
  if (data.highest_price) {
    const drawdownPct = data.drawdown_from_high ? (data.drawdown_from_high * 100).toFixed(2) : '-';
    trailingStopHtml = `
      <div class="indicator-card">
        <div class="label">트레일링 스탑</div>
        <div class="value" style="font-size: 16px;">${data.trailing_stop_activated ? '활성' : '비활성'}</div>
        <div style="font-size: 12px; color: #64748b; margin-top: 4px;">
          최고가: ${formatNumber(data.highest_price)}<br/>
          고점 대비: -${drawdownPct}%
        </div>
      </div>
    `;
  }

  let volumeSectionHtml = '';
  if (data.volume_ratio !== null && data.volume_ratio !== undefined) {
    const volumeSpikeBadge = data.is_volume_spike ? '<span class="volume-spike-badge">급증</span>' : '';
    const volumeSellSignal = data.is_volume_sell_signal ? '<span class="volume-spike-badge">매도 신호</span>' : '';
    volumeSectionHtml = `
      <div class="volume-section">
        <h4>거래량 분석 ${volumeSpikeBadge} ${volumeSellSignal}</h4>
        <div class="indicator-grid" style="grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));">
          <div class="indicator-card">
            <div class="label">현재 거래량</div>
            <div class="value" style="font-size: 18px;">${formatNumber(data.current_volume)}</div>
          </div>
          <div class="indicator-card">
            <div class="label">20일 평균</div>
            <div class="value" style="font-size: 18px;">${formatNumber(data.volume_ma_20)}</div>
          </div>
          <div class="indicator-card">
            <div class="label">거래량 비율</div>
            <div class="value" style="font-size: 18px; ${data.is_volume_spike ? 'color: #dc2626;' : ''}">${(data.volume_ratio * 100).toFixed(0)}%</div>
            ${data.is_volume_spike ? '<span class="status status-danger">1.3x 초과</span>' : ''}
          </div>
          ${data.price_drop_ratio !== null ? `
          <div class="indicator-card">
            <div class="label">가격 변동</div>
            <div class="value" style="font-size: 18px; color: ${data.price_drop_ratio > 0 ? '#dc2626' : '#16a34a'};">${data.price_drop_ratio > 0 ? '-' : '+'}${(Math.abs(data.price_drop_ratio) * 100).toFixed(2)}%</div>
          </div>
          ` : ''}
        </div>
        ${data.volume_sell_reasons && data.volume_sell_reasons.length > 0 ? `
          <div style="margin-top: 8px; font-size: 12px; color: #9a3412; background: #fff7ed; padding: 8px; border-radius: 4px;">
            ${data.volume_sell_reasons.map(r => escapeHtml(r)).join(', ')}
          </div>
        ` : ''}
      </div>
    `;
  }

  let adxSectionHtml = '';
  if (data.adx !== null && data.adx !== undefined) {
    const uptrendBadge = data.is_strong_uptrend ? '<span class="adx-uptrend-badge">강한 상승 추세</span>' : '';
    const downtrendBadge = data.is_strong_downtrend ? '<span class="adx-downtrend-badge">강한 하락 추세</span>' : '';
    const blockedBadge = data.overbought_sell_blocked ? '<span class="overbought-blocked">과매수 매도 차단</span>' : '';
    adxSectionHtml = `
      <div class="adx-section">
        <h4>추세 분석 (ADX) ${uptrendBadge} ${downtrendBadge} ${blockedBadge}</h4>
        <div class="indicator-grid" style="grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));">
          <div class="indicator-card">
            <div class="label">ADX</div>
            <div class="value" style="font-size: 18px; ${data.adx > 25 ? 'color: #2563eb; font-weight: 700;' : ''}">${Number(data.adx).toFixed(1)}</div>
            <span class="status ${data.adx > 25 ? 'status-info' : 'status-safe'}">${data.adx > 25 ? '강한 추세' : '횡보/약한 추세'}</span>
            <canvas class="indicator-gauge" id="gauge_adx"></canvas>
          </div>
          <div class="indicator-card">
            <div class="label">+DI (상승 강도)</div>
            <div class="value" style="font-size: 18px; ${data.plus_di > data.minus_di ? 'color: #16a34a;' : ''}">${Number(data.plus_di).toFixed(1)}</div>
          </div>
          <div class="indicator-card">
            <div class="label">-DI (하락 강도)</div>
            <div class="value" style="font-size: 18px; ${data.minus_di > data.plus_di ? 'color: #dc2626;' : ''}">${Number(data.minus_di).toFixed(1)}</div>
          </div>
          <div class="indicator-card">
            <div class="label">추세 방향</div>
            <div class="value" style="font-size: 16px;">${data.plus_di > data.minus_di ? '↑ 상승' : '↓ 하락'}</div>
          </div>
        </div>
        ${data.overbought_sell_blocked ? `
          <div style="margin-top: 8px; font-size: 12px; color: #1e40af; background: #eff6ff; padding: 8px; border-radius: 4px;">
            강한 상승 추세(ADX>25)로 과매수 매도 신호가 차단되었습니다.
          </div>
        ` : ''}
      </div>
    `;
  }

  let sellRatioHtml = '';
  const ratioMinValue = data.final_ratio_min ?? data.sell_ratio_min;
  const ratioMaxValue = data.final_ratio_max ?? data.sell_ratio_max;
  if (currentStage && currentStage !== 'HOLD') {
    const ratioMin = ratioMinValue !== undefined ? (ratioMinValue * 100).toFixed(0) : '0';
    const ratioMax = ratioMaxValue !== undefined ? (ratioMaxValue * 100).toFixed(0) : '0';
    sellRatioHtml = `
      <div style="background: #fef2f2; border: 1px solid #fecaca; padding: 12px 16px; border-radius: 8px; margin-bottom: 16px;">
        <strong style="color: #991b1b;">권장 매도 비율: ${ratioMin}% ~ ${ratioMax}%</strong>
        ${Number.isFinite(Number(data.holding_quantity)) && Number.isFinite(Number(ratioMinValue)) && Number.isFinite(Number(ratioMaxValue)) ? `<span style="color: #7c2d12; margin-left: 12px;">→ 보유 ${safeNum(data.holding_quantity)}주 중 ${Math.floor(Number(data.holding_quantity) * ratioMinValue)}~${Math.floor(Number(data.holding_quantity) * ratioMaxValue)}주 매도 권장</span>` : ''}
      </div>
    `;
  }

  const html = `
    <div class="result-card">
      <div class="result-header">
        <h3>${escapeHtml(data.symbol)} ${escapeHtml(data.name)}</h3>
        <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
          <span class="stage-badge ${stageClass}">${getStageDisplayName(currentStage)}</span>
          <span class="phase-badge ${phaseClass}">${getPhaseDisplayName(data.sell_phase, data.sell_phase_name)}</span>
        </div>
      </div>

      ${sellRatioHtml}

      <div class="phase-indicator">
        ${stageIndicatorHtml}
      </div>

      ${profitSectionHtml}

      <div class="indicator-grid">
        <div class="indicator-card">
          <div class="label">현재가</div>
          <div class="value">${formatNumber(data.current_price)}</div>
        </div>
        <div class="indicator-card">
          <div class="label">MA55 / MA165</div>
          <div class="value">${formatNumber(data.ma_short)} / ${formatNumber(data.ma_long)}</div>
          <span class="status ${maStatus}">${data.is_death_cross ? '데드크로스' : '골든크로스'}</span>
        </div>
        <div class="indicator-card">
          <div class="label">MA 갭</div>
          <div class="value">${Number(data.ma_gap_ratio).toFixed(2)}%</div>
        </div>
        <div class="indicator-card">
          <div class="label">Stochastic %K</div>
          <div class="value">${Number(data.stoch_k).toFixed(1)}</div>
          <span class="status ${stochStatus}">${data.is_stoch_overbought ? '과매수' : '정상'}</span>
          <canvas class="indicator-gauge" id="gauge_stoch_k"></canvas>
        </div>
        <div class="indicator-card">
          <div class="label">Stochastic %D</div>
          <div class="value">${Number(data.stoch_d).toFixed(1)}</div>
          <canvas class="indicator-gauge" id="gauge_stoch_d"></canvas>
        </div>
        <div class="indicator-card">
          <div class="label">RSI (14)</div>
          <div class="value">${Number(data.rsi).toFixed(1)}</div>
          <span class="status ${rsiStatus}">${data.is_rsi_overbought ? '과매수' : '정상'}</span>
          <canvas class="indicator-gauge" id="gauge_rsi"></canvas>
        </div>
        ${trailingStopHtml}
      </div>

      ${volumeSectionHtml}

      ${adxSectionHtml}

      ${stageReasons.length > 0 ? `
      <div class="reasons-list" style="background: #fef2f2; border-color: #fecaca;">
        <h4 style="color: #991b1b;">비중축소 판단 근거</h4>
        <ul>
          ${stageReasons.map(r => `<li style="color: #7c2d12;">${escapeHtml(r)}</li>`).join('')}
        </ul>
      </div>
      ` : ''}

      ${sellReasons.length > 0 ? `
      <div class="reasons-list">
        <h4>매도 근거</h4>
        <ul>
          ${sellReasons.map(r => `<li>${escapeHtml(r)}</li>`).join('')}
        </ul>
      </div>
      ` : ''}

      <p style="margin-top: 16px; font-size: 12px; color: #64748b;">
        분석 시간: ${formatDateTime(data.analyzed_at)}
        ${Number.isFinite(Number(data.candle_count)) ? ` | 사용된 캔들: ${safeNum(data.candle_count)}개` : ''}
      </p>
    </div>
  `;

  document.getElementById("result_container").innerHTML = html;

  // canvas 게이지 렌더링 (layout 확정 후)
  const stochOpts = {
    ticks: [20, 50, 70, 80],
    zones: [
      { from: 0, to: 20, color: 'rgba(22,163,74,0.12)' },
      { from: 70, to: 100, color: 'rgba(220,38,38,0.12)' }
    ],
    highThreshold: 70,
    lowThreshold: 20
  };
  const rsiOpts = {
    ticks: [30, 50, 70],
    zones: [
      { from: 0, to: 30, color: 'rgba(22,163,74,0.12)' },
      { from: 70, to: 100, color: 'rgba(220,38,38,0.12)' }
    ],
    highThreshold: 70,
    lowThreshold: 30
  };
  const adxOpts = data.adx !== null && data.adx !== undefined ? {
    ticks: [10, 25, 40],
    zones: [{ from: 25, to: 60, color: 'rgba(37,99,235,0.12)' }],
    barColor: '#2563eb',
    highThreshold: 60,
    lowThreshold: 0
  } : null;

  const redrawGauges = () => {
    drawGauge('gauge_stoch_k', data.stoch_k, 0, 100, stochOpts);
    drawGauge('gauge_stoch_d', data.stoch_d, 0, 100, stochOpts);
    drawGauge('gauge_rsi', data.rsi, 0, 100, rsiOpts);
    if (adxOpts) drawGauge('gauge_adx', data.adx, 0, 60, adxOpts);
  };

  const resultContainer = document.getElementById('result_container');

  // 이전 RAF 취소 후 새로 등록 (stale 콜백 방지)
  if (resultContainer?._gaugeRafId) cancelAnimationFrame(resultContainer._gaugeRafId);
  if (resultContainer) resultContainer._gaugeRafId = requestAnimationFrame(redrawGauges);

  // 리사이즈 시 재렌더링 (ResizeObserver)
  if (resultContainer && window.ResizeObserver) {
    const existingRo = resultContainer._gaugeRo;
    if (existingRo) existingRo.disconnect();
    const ro = new ResizeObserver(() => {
      if (resultContainer._gaugeRafId) cancelAnimationFrame(resultContainer._gaugeRafId);
      resultContainer._gaugeRafId = requestAnimationFrame(redrawGauges);
    });
    ro.observe(resultContainer);
    resultContainer._gaugeRo = ro;
  }
};

const renderUniverseBacktest = (data) => {
  const container = document.getElementById("universe_backtest_container");
  if (!container) return;

  if (!data || !data.summary) {
    container.innerHTML = `<div class="placeholder-message">유니버스 백테스트 결과가 없습니다.</div>`;
    return;
  }

  const summary = data.summary;
  const bestSymbols = (summary.best_symbols || []).map(item => `
    <li>
      <span>${escapeHtml(item.symbol)}</span>
      <strong class="universe-positive">${Number(item.total_return).toFixed(2)}%</strong>
    </li>
  `).join('') || '<li><span>데이터 없음</span><span>-</span></li>';

  const worstSymbols = (summary.worst_symbols || []).map(item => `
    <li>
      <span>${escapeHtml(item.symbol)}</span>
      <strong class="universe-negative">${Number(item.total_return).toFixed(2)}%</strong>
    </li>
  `).join('') || '<li><span>데이터 없음</span><span>-</span></li>';

  const config = data.config_summary || {};
  const comparisonRows = (config.comparison_results || []).map(item => `
    <li>
      <span>${escapeHtml(item.label)}</span>
      <strong>${Number(item.average_return).toFixed(2)}% / ${Number(item.average_win_rate).toFixed(2)}% / ${Number(item.average_holding_days).toFixed(1)}일</strong>
    </li>
  `).join('');

  container.innerHTML = `
    <div class="result-header">
      <h3>유니버스 백테스트 요약</h3>
      <div style="font-size: 12px; color: #64748b;">
        ${escapeHtml(data.market || '전체')} · ${Array.isArray(data.symbols) ? data.symbols.length : 0}종목 · ${escapeHtml(data.start_date?.slice(0,10) || '')} ~ ${escapeHtml(data.end_date?.slice(0,10) || '')}
      </div>
    </div>
    <div style="font-size: 13px; color: #475569; margin-bottom: 8px;">
      전략: ${escapeHtml(config.label || '공격형 중단기 스윙 매도 v3')}
      (손절 ${formatPercent(Math.abs(config.stop_loss || 0))} / 본전보호 ${formatPercent(config.breakeven_activation || 0)} / 1차익절 ${formatPercent(config.partial_take_profit_1 || 0)} / 2차익절 ${formatPercent(config.partial_take_profit_2 || 0)} / trailing ${formatPercent(config.trailing_stop || 0)})
    </div>
    <div class="universe-summary-grid">
      <div class="universe-summary-card"><div class="label">평균 수익률</div><div class="value ${summary.average_return >= 0 ? 'universe-positive' : 'universe-negative'}">${Number(summary.average_return).toFixed(2)}%</div></div>
      <div class="universe-summary-card"><div class="label">평균 승률</div><div class="value">${Number(summary.average_win_rate).toFixed(2)}%</div></div>
      <div class="universe-summary-card"><div class="label">수익 종목 비율</div><div class="value">${Number(summary.profitable_ratio).toFixed(2)}%</div></div>
      <div class="universe-summary-card"><div class="label">평균 MDD</div><div class="value">${Number(summary.average_mdd).toFixed(2)}%</div></div>
      <div class="universe-summary-card"><div class="label">평균 보유일</div><div class="value">${Number(summary.average_holding_days).toFixed(1)}일</div></div>
      <div class="universe-summary-card"><div class="label">총 거래 수</div><div class="value">${formatNumber(summary.total_trades)}</div></div>
    </div>
    <div class="universe-ranking">
      <div class="panel">
        <h4>상위 수익 종목</h4>
        <ul>${bestSymbols}</ul>
      </div>
      <div class="panel">
        <h4>하위 수익 종목</h4>
        <ul>${worstSymbols}</ul>
      </div>
    </div>
    ${comparisonRows ? `
    <div class="panel" style="margin-top:16px; background:#fff; border:1px solid #e2e8f0; border-radius:10px; padding:16px;">
      <h4>비교군 요약 (평균수익률 / 평균승률 / 평균보유일)</h4>
      <ul style="list-style:none; padding:0; margin:0;">
        ${comparisonRows}
      </ul>
    </div>` : ''}
  `;
};

const runUniverseBacktest = async () => {
  const container = document.getElementById("universe_backtest_container");
  const market = document.getElementById("universe_market_filter")?.value || null;
  const limit = parseInt(document.getElementById("universe_limit")?.value || '20', 10);
  const eligibleOnly = !!document.getElementById("universe_eligible_only")?.checked;
  const startDate = document.getElementById("universe_start_date")?.value;
  const endDate = document.getElementById("universe_end_date")?.value;

  if (!startDate || !endDate) {
    alert('백테스트 기간을 입력해주세요.');
    return;
  }

  container.innerHTML = `<div class="placeholder-message">유니버스 백테스트 실행 중...</div>`;

  try {
    const response = await fetch('/api/v1/backtest/run-universe-golden-cross', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        market: market || null,
        eligible_only: eligibleOnly,
        limit,
        start_date: `${startDate}T00:00:00`,
        end_date: `${endDate}T00:00:00`
      })
    });
    const result = await response.json();
    renderUniverseBacktest(result);
  } catch (e) {
    console.error('Failed to run universe backtest:', e);
    container.innerHTML = `<div class="placeholder-message" style="color:#dc2626;">유니버스 백테스트 실행 실패</div>`;
  }
};

const renderHistoryTable = () => {
  const tbody = document.getElementById("history_body");
  if (!tbody) return;

  try {
    if (!Array.isArray(analysisHistory) || analysisHistory.length === 0) {
      tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #94a3b8;">분석 기록이 없습니다</td></tr>';
      return;
    }

    tbody.innerHTML = analysisHistory.map(item => {
      const displayStage = resolveDisplayStage(item);
      const stageClass = `stage-${sanitizeCssClass(displayStage)}`;
      const activeIcon = item.is_active ? '●' : '○';
      const activeClass = item.is_active ? 'active' : 'inactive';
      const selectedClass = item.id === selectedHistoryId ? 'selected' : '';

      const entryPriceBadge = item.entry_price ? `<span class="entry-price-badge">진입가: ${formatNumber(item.entry_price)}</span>` : '';
      const stageName = getStageDisplayName(displayStage).replace(' 비중 축소', '').replace('보유 유지', '보유');
      const adxValue = item.adx !== null && item.adx !== undefined ? Number(item.adx) : null;
      const adxDisplay = adxValue !== null && !Number.isNaN(adxValue) ? adxValue.toFixed(1) : '-';
      const adxBadge = item.is_strong_uptrend ? '↑' : ((adxValue !== null && adxValue > 25) ? '↓' : '');
      const stochDisplay = item.stoch_k !== null && item.stoch_k !== undefined ? Number(item.stoch_k).toFixed(1) : '-';
      const rsiDisplay = item.rsi !== null && item.rsi !== undefined ? Number(item.rsi).toFixed(1) : '-';

      const safeId = parseInt(item.id, 10);
      return `<tr class="${selectedClass}" onclick="showHistoryDetail(${safeId})">
        <td>
          <span class="active-toggle ${activeClass}" onclick="toggleActive(${safeId}, event)" title="${item.is_active ? '활성 추적 중' : '추적 중지됨'}">${activeIcon}</span>
        </td>
        <td><strong>${escapeHtml(item.symbol)}</strong>${entryPriceBadge}</td>
        <td>${escapeHtml(item.name || '-')}</td>
        <td>${formatNumber(item.current_price)}</td>
        <td><span class="stage-badge ${stageClass}" style="font-size: 11px; padding: 4px 8px;">${stageName}</span></td>
        <td>${adxDisplay} ${adxBadge}</td>
        <td>${stochDisplay}</td>
        <td>${rsiDisplay}</td>
        <td>${formatTime(item.analyzed_at)}</td>
        <td>
          <button class="btn-edit" onclick="openEditModal(${safeId}, event)">수정</button>
          <button class="btn-delete" onclick="deleteHistory(${safeId}, event)">삭제</button>
        </td>
      </tr>`;
    }).join('');
  } catch (e) {
    console.error('renderHistoryTable failed:', e, analysisHistory);
    tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #ef4444;">추적 종목 렌더링 실패</td></tr>';
  }
};

document.addEventListener('DOMContentLoaded', () => {
  try {
    const resultSection = document.getElementById("result_section");
    const resultContainer = document.getElementById("result_container");

    const cached = loadLastAnalysis();
    if (cached?.data && resultSection) {
      displayResult({
        ...cached.data,
        sell_reasons: normalizeSellReasons(cached.data)
      });
      updateLastAnalysisLabel(cached.data, cached.isStale);
      resultSection.style.display = "block";
    } else if (resultSection && resultContainer) {
      resultSection.style.display = "block";
      resultContainer.innerHTML = `
        <div class="placeholder-message">
          종목 코드를 입력하고 <strong>매도 시그널 분석</strong> 버튼을 클릭하세요.<br>
          <small style="color: #94a3b8; margin-top: 8px; display: block;">분석 결과는 자동으로 저장되어 다음 방문 시에도 표시됩니다.</small>
        </div>
      `;
    }
  } catch (e) {
    console.error('initial result render failed:', e);
  }

  try {
    const cachedRefresh = loadLastRefresh();
    if (cachedRefresh?.data) {
      updateLastRefreshLabel(cachedRefresh.data, cachedRefresh.isStale);
    }
  } catch (e) {
    console.error('refresh label restore failed:', e);
  }

  loadHistory();
  loadPortfolioCashPlan();
});

document.getElementById("symbol_input").addEventListener("keypress", (e) => {
  if (e.key === "Enter") analyzeSellSignal();
});

const openEditModal = (id, event) => {
  event.stopPropagation();
  const item = analysisHistory.find(h => h.id === id);
  if (!item) return;

  document.getElementById("edit_history_id").value = id;
  document.getElementById("edit_symbol_display").value = `${item.symbol} - ${item.name || ''}`;
  document.getElementById("edit_current_price").value = formatNumber(item.current_price);
  document.getElementById("edit_entry_price").value = item.entry_price || '';
  document.getElementById("edit_note").value = item.note || '';
  document.getElementById("modal_title").textContent = `${item.symbol} 수정`;

  document.getElementById("edit_modal").classList.add("show");
};

const closeEditModal = (event) => {
  if (event && event.target !== event.currentTarget) return;
  document.getElementById("edit_modal").classList.remove("show");
};

const saveHistoryEdit = async () => {
  const historyId = document.getElementById("edit_history_id").value;
  const entryPrice = document.getElementById("edit_entry_price").value;
  const note = document.getElementById("edit_note").value;

  const payload = {};
  if (entryPrice) {
    payload.entry_price = parseFloat(entryPrice);
  }
  if (note !== null) {
    payload.note = note || null;
  }

  try {
    const response = await fetch(`/api/v1/strategies/analysis-history/${historyId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    if (result.success && result.data) {
      const idx = analysisHistory.findIndex(h => h.id == historyId);
      if (idx >= 0) {
        analysisHistory[idx] = result.data;
        renderHistoryTable();
        loadPortfolioCashPlan();
      }
      closeEditModal();
      alert('수정되었습니다.');
    } else {
      alert('수정 실패: ' + (result.error || result.detail || '알 수 없는 오류'));
    }
  } catch (e) {
    console.error('Failed to update history:', e);
    alert('수정 실패');
  }
};

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeEditModal();
  }
});
