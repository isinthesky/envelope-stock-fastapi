let allStocks = [];
let universeStocks = [];
let gcScanStocks = [];
let gcScanMeta = null;  // 원본 스캔 메타데이터 보존
let buyHistory = [];
let addedSymbols = new Set();
let currentFilter = 'all';
let universeFilter = 'all';
let gcFilter = 'all';

// MA5 전략 관련 변수
let ma5ScanStocks = [];
let ma5Filter = 'BREAKOUT';

// 스캔 진행 상태
let scanInProgress = { gc: false, ma5: false };

// 캐시 설정
const CACHE_SCHEMA_VERSION = 1;
const CACHE_TTL_MS = 3600000;  // 1시간
const SCAN_COOLDOWNS = {
  gc: 300000,   // 5분
  ma5: 180000   // 3분
};
const REFRESH_COOLDOWN_MS = 60000;  // 1분

const BUY_STORAGE_KEYS = {
  gc: 'buyStrategy.gcScan',
  ma5: 'buyStrategy.ma5Scan',
  refresh: 'buyStrategy.lastRefresh'
};

// 전략 탭 전환
const showStrategy = (strategy) => {
  document.querySelectorAll('.strategy-tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.strategy-content').forEach(c => c.classList.remove('active'));

  if (strategy === 'golden_cross') {
    document.querySelector('.strategy-tab:not(.ma5)').classList.add('active');
    document.getElementById('strategy_golden_cross').classList.add('active');
  } else {
    document.querySelector('.strategy-tab.ma5').classList.add('active');
    document.getElementById('strategy_ma5_breakout').classList.add('active');
  }
};

const formatDateTime = (dateStr) => {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return '-';
  return date.toLocaleString('ko-KR', { timeZone: 'Asia/Seoul' });
};

// 상대 시간 표시 (안전한 파싱)
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

// 캐시 유효성 검사
const isCacheStale = (savedAt) => {
  if (!savedAt) return true;
  return (Date.now() - savedAt) > CACHE_TTL_MS;
};

// 스캔 가능 여부 확인
const canScan = (scanType) => {
  if (scanInProgress[scanType]) {
    return { allowed: false, reason: '스캔 진행 중...' };
  }

  const cached = loadLastScan(BUY_STORAGE_KEYS[scanType]);
  if (!cached?.savedAt) return { allowed: true };

  const elapsed = Date.now() - cached.savedAt;
  const cooldown = SCAN_COOLDOWNS[scanType] || 300000;

  if (elapsed < cooldown) {
    const remaining = Math.ceil((cooldown - elapsed) / 60000);
    return {
      allowed: false,
      reason: `${remaining}분 후 재검색 가능`,
      forceAllowed: true
    };
  }
  return { allowed: true };
};

const updateLastSearchLabel = (elementId, timestamp, count, isStale = false) => {
  const label = document.getElementById(elementId);
  if (!label) return;

  const timeText = timestamp ? formatDateTime(timestamp) : '-';
  const relTime = getRelativeTime(timestamp);
  const countText = typeof count === 'number' ? `${count}개 종목` : '';

  // 스타일 클래스 적용
  label.classList.toggle('stale', isStale);

  label.innerHTML = `
    <span class="time-badge">${relTime || '알 수 없음'}</span>
    <span>마지막 검색: ${timeText} ${countText ? `- ${countText}` : ''}</span>
    <span class="cache-indicator ${isStale ? 'cached' : 'fresh'}">${isStale ? '캐시됨' : '최신'}</span>
  `;
};

const saveLastScan = (key, data, timestamp) => {
  try {
    localStorage.setItem(key, JSON.stringify({
      schemaVersion: CACHE_SCHEMA_VERSION,
      savedAt: Date.now(),
      timestamp,
      data
    }));
  } catch (e) {
    console.warn('Failed to save last scan:', e);
  }
};

const loadLastScan = (key) => {
  try {
    const raw = localStorage.getItem(key);
    if (!raw) return null;

    const cached = JSON.parse(raw);

    // 구버전 형식 호환
    if (!cached.schemaVersion) {
      return { data: cached.data, timestamp: cached.timestamp, isStale: true };
    }

    if (cached.schemaVersion !== CACHE_SCHEMA_VERSION) {
      localStorage.removeItem(key);
      return null;
    }

    const isStale = isCacheStale(cached.savedAt);
    return { ...cached, isStale };
  } catch (e) {
    console.warn('Failed to load last scan:', e);
    return null;
  }
};

// 갱신 결과 저장/로드
const saveLastRefresh = (data) => {
  try {
    // 메타데이터만 저장 (items 배열 제외하여 localStorage 용량 절약)
    localStorage.setItem(BUY_STORAGE_KEYS.refresh, JSON.stringify({
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
    const raw = localStorage.getItem(BUY_STORAGE_KEYS.refresh);
    if (!raw) return null;

    const cached = JSON.parse(raw);

    // 스키마 불일치 시 제거
    if (!cached.schemaVersion || cached.schemaVersion !== CACHE_SCHEMA_VERSION) {
      localStorage.removeItem(BUY_STORAGE_KEYS.refresh);
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
  const label = document.getElementById("buy_last_refresh");
  if (!label) return;

  const refreshedAt = data?.refreshedAt;
  const timeText = formatDateTime(refreshedAt);
  const relTime = getRelativeTime(refreshedAt);
  const countText = data?.updated_count != null ? `${data.updated_count}개 종목` : '';

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

// MA5 돌파 스캔 (유니버스 전체)
const scanMA5Breakout = async (forceRefresh = false) => {
  // 중복 클릭 방지
  if (!forceRefresh) {
    const check = canScan('ma5');
    if (!check.allowed) {
      if (check.forceAllowed) {
        if (!confirm(`${check.reason}\n강제로 다시 스캔하시겠습니까?`)) {
          return;
        }
      } else {
        alert(check.reason);
        return;
      }
    }
  }

  scanInProgress.ma5 = true;
  document.getElementById("ma5_scan_output").textContent = "MA5 돌파 스캔 중...";

  const shortPeriod = parseInt(document.getElementById("ma5_short_period").value) || 5;
  const longPeriod = parseInt(document.getElementById("ma5_long_period").value) || 300;
  const envelopePct = parseFloat(document.getElementById("ma5_envelope_pct").value) || 0.7;
  const useVolume = document.getElementById("ma5_use_volume").checked;

  const url = `/api/v1/strategies/universe/ma5-breakout-scan?short_period=${shortPeriod}&long_period=${longPeriod}&envelope_pct=${envelopePct}&use_volume_filter=${useVolume}`;

  try {
    const response = await fetch(url);
    const result = await response.json();

    if (result.success && result.data) {
      displayMA5ScanResults(result.data);
      document.getElementById("ma5_scan_output").textContent =
        `스캔 완료: ${result.data.stocks?.length || 0}개 종목 발견 (총 ${result.data.total_scanned}개 스캔)`;
    } else {
      document.getElementById("ma5_scan_output").textContent = `스캔 실패: ${result.message || 'Unknown error'}`;
    }
  } catch (e) {
    console.error('MA5 scan failed:', e);
    document.getElementById("ma5_scan_output").textContent = `스캔 실패: ${e.message}`;
  } finally {
    scanInProgress.ma5 = false;
  }
};

// MA5 돌파 직접 입력 스캔
const scanMA5Symbols = async (forceRefresh = false) => {
  // 중복 클릭 방지
  if (!forceRefresh && scanInProgress.ma5) {
    alert('스캔 진행 중...');
    return;
  }

  const symbolsText = document.getElementById("ma5_symbols").value.trim();
  if (!symbolsText) {
    alert("종목코드를 입력하세요.");
    return;
  }

  const symbolList = symbolsText.split(/[\n,]/)
    .map(s => s.trim())
    .filter(s => s.length > 0)
    .map(symbol => ({ symbol, name: null, market: "UNKNOWN" }));

  if (symbolList.length === 0) {
    alert("유효한 종목코드가 없습니다.");
    return;
  }

  scanInProgress.ma5 = true;
  document.getElementById("ma5_scan_output").textContent = `${symbolList.length}개 종목 MA5 스캔 중...`;

  const shortPeriod = parseInt(document.getElementById("ma5_short_period").value) || 5;
  const longPeriod = parseInt(document.getElementById("ma5_long_period").value) || 300;
  const envelopePct = parseFloat(document.getElementById("ma5_envelope_pct").value) || 0.7;
  const useVolume = document.getElementById("ma5_use_volume").checked;

  try {
    const response = await fetch(
      `/api/v1/strategies/universe/ma5-breakout-scan-symbols?short_period=${shortPeriod}&long_period=${longPeriod}&envelope_pct=${envelopePct}&use_volume_filter=${useVolume}`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(symbolList)
      }
    );

    const result = await response.json();
    if (result.success && result.data) {
      displayMA5ScanResults(result.data);
      document.getElementById("ma5_scan_output").textContent =
        `스캔 완료: ${result.data.stocks?.length || 0}개 종목 발견`;
    } else {
      document.getElementById("ma5_scan_output").textContent = `스캔 실패: ${result.message || 'Unknown error'}`;
    }
  } catch (e) {
    console.error('MA5 symbol scan failed:', e);
    document.getElementById("ma5_scan_output").textContent = `스캔 실패: ${e.message}`;
  } finally {
    scanInProgress.ma5 = false;
  }
};

// MA5 스캔 결과 표시
const displayMA5ScanResults = (data, options = { persist: true }) => {
  ma5ScanStocks = data.stocks || [];

  document.getElementById("ma5_scan_container").style.display = "block";
  document.getElementById("ma5_stats_row").style.display = "flex";

  // 통계 계산
  const breakoutCount = ma5ScanStocks.filter(s => s.ma5_state === 'BREAKOUT').length;
  const aboveCount = ma5ScanStocks.filter(s => s.ma5_state === 'ABOVE').length;
  const belowCount = ma5ScanStocks.filter(s => s.ma5_state === 'BELOW').length;

  document.getElementById("ma5_stat_total").textContent = data.total_scanned || ma5ScanStocks.length;
  document.getElementById("ma5_stat_breakout").textContent = breakoutCount;
  document.getElementById("ma5_stat_above").textContent = aboveCount;
  document.getElementById("ma5_stat_below").textContent = belowCount;

  ma5Filter = 'BREAKOUT';
  renderMA5ScanTable(ma5ScanStocks);

  const scanTime = data.scan_time || new Date().toISOString();
  if (options.persist) {
    saveLastScan(BUY_STORAGE_KEYS.ma5, data, scanTime);
  }
  updateLastSearchLabel("ma5_last_search", scanTime, data.stocks?.length, !options.persist);
};

// MA5 테이블 렌더링
const renderMA5ScanTable = (stocks) => {
  let filtered;
  if (ma5Filter === 'all') {
    filtered = stocks;
  } else if (ma5Filter === 'BREAKOUT') {
    filtered = stocks.filter(s => s.ma5_state === 'BREAKOUT');
  } else if (ma5Filter === 'ABOVE') {
    filtered = stocks.filter(s => s.ma5_state === 'ABOVE' || s.ma5_state === 'BREAKOUT');
  } else {
    filtered = stocks.filter(s => s.ma5_state === ma5Filter);
  }

  const tbody = document.getElementById("ma5_scan_table_body");

  // 필터 결과가 없으면 안내 메시지 표시
  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="9" class="placeholder-message" style="border: none;">
      해당 조건에 맞는 종목이 없습니다.
    </td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(stock => {
    const stateClass = getMA5StateClass(stock.ma5_state);
    const stateLabel = getMA5StateLabel(stock.ma5_state);
    const gapClass = stock.gap_ratio > 0 ? 'bullish' : 'bearish';
    const volRatioClass = stock.volume_ratio >= 1 ? 'bullish' : '';

    return `<tr>
      <td><strong>${stock.symbol}</strong></td>
      <td>${stock.name || '-'}</td>
      <td><span class="state-badge ${stateClass}">${stateLabel}</span></td>
      <td class="indicator">${formatNumber(stock.current_price)}</td>
      <td class="indicator">${formatNumber(stock.ma5)}</td>
      <td class="indicator">${formatNumber(stock.ma300)}</td>
      <td class="indicator">${formatNumber(stock.upper_band)}</td>
      <td class="indicator ${gapClass}">${stock.gap_ratio?.toFixed(2) || '-'}%</td>
      <td class="indicator ${volRatioClass}">${stock.volume_ratio?.toFixed(2) || '-'}x</td>
    </tr>`;
  }).join('');
};

const showMA5Tab = (filter) => {
  ma5Filter = filter;
  document.querySelectorAll('#ma5_scan_container .tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  renderMA5ScanTable(ma5ScanStocks);
};

const getMA5StateClass = (state) => {
  const map = {
    'BREAKOUT': 'state-ma5-breakout',
    'ABOVE': 'state-ma5-above',
    'BELOW': 'state-ma5-below'
  };
  return map[state] || '';
};

const getMA5StateLabel = (state) => {
  const map = {
    'BREAKOUT': '돌파',
    'ABOVE': '상단 위',
    'BELOW': '상단 아래'
  };
  return map[state] || state;
};

// 페이지 로드 시 히스토리 조회
const loadBuyHistory = async () => {
  try {
    const response = await fetch('/api/v1/strategies/analysis-history?analysis_type=buy&limit=50');
    const data = await response.json();

    if (data.success && data.data) {
      buyHistory = data.data.items;
      addedSymbols = new Set(buyHistory.map(h => h.symbol));
      renderBuyHistoryTable();
    }
  } catch (e) {
    console.error('Failed to load buy history:', e);
    document.getElementById("buy_history_body").innerHTML =
      '<tr><td colspan="10" style="text-align: center; color: #ef4444;">히스토리 로딩 실패</td></tr>';
  }
};

// 골든크로스 종목을 히스토리에 추가
const addToHistory = async (stock, event) => {
  event.stopPropagation();

  if (addedSymbols.has(stock.symbol)) return;

  try {
    const payload = {
      analysis_type: 'buy',
      symbol: stock.symbol,
      name: stock.name || null,
      current_price: stock.current_price,
      ma_short: stock.ma_short,
      ma_long: stock.ma_long,
      ma_gap_ratio: stock.ma_gap_ratio,
      stoch_k: stock.stoch_k,
      stoch_d: stock.stoch_d,
      gc_state: stock.gc_state,
      is_gc_active: stock.is_gc_active,
      is_active: true
    };

    const response = await fetch('/api/v1/strategies/analysis-history', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const result = await response.json();
    if (result.success && result.data) {
      buyHistory.unshift(result.data);
      addedSymbols.add(stock.symbol);
      renderBuyHistoryTable();
      renderGcScanTable(gcScanStocks); // 버튼 상태 업데이트
    }
  } catch (e) {
    console.error('Failed to add to history:', e);
    alert('추가 실패');
  }
};

// 히스토리 삭제
const deleteBuyHistory = async (id, symbol, event) => {
  event.stopPropagation();
  if (!confirm('이 종목을 히스토리에서 삭제하시겠습니까?')) return;

  try {
    const response = await fetch(`/api/v1/strategies/analysis-history/${id}`, {
      method: 'DELETE'
    });

    if (response.ok) {
      buyHistory = buyHistory.filter(h => h.id !== id);
      addedSymbols.delete(symbol);
      renderBuyHistoryTable();
      renderGcScanTable(gcScanStocks); // 버튼 상태 업데이트
    }
  } catch (e) {
    console.error('Failed to delete history:', e);
    alert('삭제 실패');
  }
};

// 활성 상태 토글
const toggleBuyActive = async (id, event) => {
  event.stopPropagation();
  const item = buyHistory.find(h => h.id === id);
  if (!item) return;

  const newActive = !item.is_active;

  try {
    const response = await fetch(`/api/v1/strategies/analysis-history/${id}/active?is_active=${newActive}`, {
      method: 'PATCH'
    });

    const result = await response.json();
    if (result.success && result.data) {
      const idx = buyHistory.findIndex(h => h.id === id);
      if (idx >= 0) {
        buyHistory[idx] = result.data;
        renderBuyHistoryTable();
      }
    }
  } catch (e) {
    console.error('Failed to toggle active:', e);
  }
};

// 활성 종목 일괄 갱신
// 중복 갱신 방지
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

const refreshBuyHistory = async (forceRefresh = false) => {
  // 중복 클릭 방지
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

  const tbody = document.getElementById("buy_history_body");
  const refreshBtn = document.querySelector('.history-section .btn-refresh');
  tbody.classList.add('loading');
  refreshInProgress = true;

  // 버튼 비활성화 및 진행 상태 표시
  if (refreshBtn) {
    refreshBtn.disabled = true;
    refreshBtn.textContent = '갱신 중...';
  }

  try {
    const response = await fetch('/api/v1/strategies/analysis-history/refresh?analysis_type=buy', {
      method: 'POST'
    });

    const result = await response.json();
    if (result.success && result.data) {
      // 갱신된 항목들로 기존 데이터 업데이트
      const items = result.data.items || [];
      items.forEach(updated => {
        const idx = buyHistory.findIndex(h => h.symbol === updated.symbol && h.is_active);
        if (idx >= 0) {
          buyHistory[idx] = updated;
        }
      });
      renderBuyHistoryTable();

      // 갱신 결과 저장 및 라벨 업데이트 (updated_count 기본값 처리)
      const updatedCount = result.data.updated_count ?? items.length ?? 0;
      const refreshData = {
        updated_count: updatedCount,
        refreshedAt: new Date().toISOString()
      };
      saveLastRefresh(refreshData);
      updateLastRefreshLabel(refreshData, false);

      alert(`${updatedCount}개 종목 갱신 완료`);
    } else {
      // API 실패 시 사용자 피드백
      const errorMsg = result.message || result.error || '알 수 없는 오류';
      alert(`갱신 실패: ${errorMsg}`);
    }
  } catch (e) {
    console.error('Failed to refresh:', e);
    alert(`갱신 실패: ${e.message}`);
  } finally {
    tbody.classList.remove('loading');
    refreshInProgress = false;

    // 버튼 원래 상태로 복원
    if (refreshBtn) {
      refreshBtn.disabled = false;
      refreshBtn.textContent = '활성 종목 갱신';
    }
  }
};

// 매수 히스토리 테이블 렌더링
const renderBuyHistoryTable = () => {
  const tbody = document.getElementById("buy_history_body");

  if (buyHistory.length === 0) {
    tbody.innerHTML = '<tr><td colspan="10" style="text-align: center; color: #94a3b8;">추적 중인 종목이 없습니다. 골든크로스 스캔 후 + 버튼으로 추가하세요.</td></tr>';
    return;
  }

  tbody.innerHTML = buyHistory.map(item => {
    const stateClass = getGcStateClass(item.gc_state);
    const stateLabel = getGcStateLabel(item.gc_state);
    const activeIcon = item.is_active ? '●' : '○';
    const activeClass = item.is_active ? 'active' : 'inactive';
    const maGapClass = item.ma_gap_ratio > 0 ? 'bullish' : 'bearish';

    return `<tr>
      <td>
        <span class="active-toggle ${activeClass}" onclick="toggleBuyActive(${item.id}, event)" title="${item.is_active ? '활성 추적 중' : '추적 중지됨'}">${activeIcon}</span>
      </td>
      <td><strong>${item.symbol}</strong></td>
            <td><span class="state-badge ${stateClass}">${stateLabel}</span></td>
      <td class="indicator">${formatNumber(item.current_price)}</td>
      <td class="indicator ${maGapClass}">${Number(item.ma_gap_ratio).toFixed(2)}%</td>
      <td class="indicator">${Number(item.stoch_k).toFixed(1)}</td>
      <td class="indicator">${Number(item.stoch_d).toFixed(1)}</td>
      <td>${formatTime(item.analyzed_at)}</td>
      <td>
        <button class="btn-delete" onclick="deleteBuyHistory(${item.id}, '${item.symbol}', event)">삭제</button>
      </td>
    </tr>`;
  }).join('');
};

const scanStocks = async () => {
  document.getElementById("scan_output").textContent = "스캔 중...";
  const data = await getJson("/api/v1/strategies/universe?eligible_only=false&limit=500", null);
  if (data && data.data) {
    displayUniverseStocks(data.data);
    document.getElementById("scan_output").textContent = `${data.data.total_count}개 종목 스캔 완료 (스크리닝 통과: ${data.data.eligible_count}개)`;
  }
};

const refreshUniverse = async () => {
  document.getElementById("scan_output").textContent = "유니버스 갱신 중...";
  await postJson("/api/v1/strategies/universe/refresh", {}, "scan_output");
};

// Golden Cross 스캔
const scanGoldenCross = async (forceRefresh = false) => {
  // 중복 클릭 방지
  if (!forceRefresh) {
    const check = canScan('gc');
    if (!check.allowed) {
      if (check.forceAllowed) {
        if (!confirm(`${check.reason}\n강제로 다시 스캔하시겠습니까?`)) {
          return;
        }
      } else {
        alert(check.reason);
        return;
      }
    }
  }

  scanInProgress.gc = true;
  document.getElementById("scan_output").textContent = "골든크로스 스캔 중... (OHLCV 데이터 조회 및 지표 계산)";

  try {
    const stochThreshold = document.getElementById("stoch_threshold").value || 30;
    const gcOnly = document.getElementById("gc_only").checked;
    const includeEtf = true; // always include ETF

    const url = `/api/v1/strategies/universe/golden-cross-scan?stoch_threshold=${stochThreshold}&gc_only=${gcOnly}&include_etf=${includeEtf}`;
    const data = await getJson(url, null);

    if (data && data.data) {
      displayGcScanResults(data.data);
      const scanTime = formatTime(data.data.scan_time);
      const etfLabel = ''; // ETF always included
      document.getElementById("scan_output").textContent =
        `스캔 완료${etfLabel} (${scanTime}): ${data.data.stocks?.length || 0}개 종목 발견 ` +
        `(총 ${data.data.total_scanned}개 스캔, 오류 ${data.data.errors?.length || 0}개)`;
    }
  } finally {
    scanInProgress.gc = false;
  }
};

// 재무 필터 적용 (2차 필터)
const applyFinancialFilter = async () => {
  if (!gcScanStocks || gcScanStocks.length === 0) {
    alert('먼저 골든크로스 스캔을 실행하세요.');
    return;
  }

  // 매수 대상 종목만 필터링 (OPTIMAL_BUY, BUY_INTEREST, READY_TO_BUY)
  const buyTargetStates = ['OPTIMAL_BUY', 'BUY_INTEREST', 'READY_TO_BUY'];
  const targetStocks = gcScanStocks.filter(s => buyTargetStates.includes(s.gc_state));

  if (targetStocks.length === 0) {
    alert('재무 필터를 적용할 매수 대상 종목이 없습니다.');
    return;
  }

  document.getElementById("scan_output").textContent = `재무 필터 적용 중... (${targetStocks.length}개 종목)`;

  try {
    // 원본 메타데이터 사용 (gcScanMeta가 없으면 현재 데이터로 계산)
    const meta = gcScanMeta || {
      total_scanned: gcScanStocks.length,
      gc_active_count: gcScanStocks.filter(s => s.is_gc_active).length,
      pullback_waiting_count: gcScanStocks.filter(s => s.gc_state === 'WAITING_FOR_PULLBACK').length,
      ready_to_buy_count: gcScanStocks.filter(s => s.gc_state === 'READY_TO_BUY').length,
      buy_interest_count: gcScanStocks.filter(s => s.gc_state === 'BUY_INTEREST').length,
      optimal_buy_count: gcScanStocks.filter(s => s.gc_state === 'OPTIMAL_BUY').length,
    };

    // 원본 메타데이터와 함께 API로 전송
    const scanResult = {
      stocks: gcScanStocks,
      total_scanned: meta.total_scanned,
      gc_active_count: meta.gc_active_count,
      pullback_waiting_count: meta.pullback_waiting_count,
      ready_to_buy_count: meta.ready_to_buy_count,
      buy_interest_count: meta.buy_interest_count,
      optimal_buy_count: meta.optimal_buy_count,
      scan_time: new Date().toISOString()
    };

    const response = await fetch('/api/v1/strategies/universe/financial-filter?target_states=OPTIMAL_BUY&target_states=BUY_INTEREST&target_states=READY_TO_BUY', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(scanResult)
    });

    const result = await response.json();
    if (result.success && result.data) {
      displayGcScanResults(result.data);
      document.getElementById("scan_output").textContent =
        `재무 필터 완료: 통과 ${result.data.financial_pass_count || 0}개, ` +
        `턴어라운드 ${result.data.turnaround_count || 0}개, ` +
        `미통과 ${result.data.financial_fail_count || 0}개`;
    } else {
      document.getElementById("scan_output").textContent = `재무 필터 실패: ${result.message || 'Unknown error'}`;
    }
  } catch (e) {
    console.error('Financial filter failed:', e);
    document.getElementById("scan_output").textContent = `재무 필터 실패: ${e.message}`;
  }
};

// Golden Cross 스캔 결과 표시
const displayGcScanResults = (data, options = { persist: true }) => {
  gcScanStocks = data.stocks || [];

  // 원본 메타데이터 저장 (재무 필터 적용 시 사용)
  gcScanMeta = {
    total_scanned: data.total_scanned,
    gc_active_count: data.gc_active_count,
    pullback_waiting_count: data.pullback_waiting_count,
    ready_to_buy_count: data.ready_to_buy_count || 0,
    buy_interest_count: data.buy_interest_count || 0,
    optimal_buy_count: data.optimal_buy_count || 0,
  };

  document.getElementById("gc_scan_container").style.display = "block";
  document.getElementById("universe_list_container").style.display = "none";
  { const el = document.getElementById("stock_list_container"); if (el) el.style.display = "none"; }
  document.getElementById("stats_row").style.display = "flex";

  // 매수 관심/적기 종목만 필터링
  const buyTargetStates = ['OPTIMAL_BUY', 'BUY_INTEREST', 'READY_TO_BUY'];
  const buyTargetStocks = gcScanStocks.filter(s => buyTargetStates.includes(s.gc_state));

  // 통계 업데이트 (원본 메타데이터 사용)
  document.getElementById("stat_total").textContent = gcScanMeta.total_scanned;
  document.getElementById("stat_gc").textContent = gcScanMeta.gc_active_count;
  document.getElementById("stat_pullback").textContent = gcScanMeta.pullback_waiting_count;
  document.getElementById("stat_ready").textContent = gcScanMeta.ready_to_buy_count + gcScanMeta.buy_interest_count;
  document.getElementById("stat_optimal").textContent = gcScanMeta.optimal_buy_count;
  document.getElementById("stat_position").textContent = '-';

  // 재무 필터 통계 업데이트 (ERROR 통계 포함)
  const hasFinancialData = data.financial_pass_count != null || data.financial_pending_count != null;
  if (hasFinancialData) {
    document.getElementById("fin_stats_row").style.display = "flex";
    document.getElementById("stat_fin_pass").textContent = data.financial_pass_count || 0;
    document.getElementById("stat_fin_turnaround").textContent = data.turnaround_count || 0;
    // FAIL과 ERROR를 합산하여 표시 (UI에 ERROR 카드가 없으므로)
    const failCount = (data.financial_fail_count || 0) + (data.financial_error_count || 0);
    document.getElementById("stat_fin_fail").textContent = failCount;
    document.getElementById("stat_fin_pending").textContent = data.financial_pending_count || 0;
  } else {
    document.getElementById("fin_stats_row").style.display = "none";
  }

  // 기본값: 매수 대상 종목만 표시
  gcFilter = 'BUY_TARGETS';
  renderGcScanTable(gcScanStocks);

  const scanTime = data.scan_time || new Date().toISOString();
  if (options.persist) {
    saveLastScan(BUY_STORAGE_KEYS.gc, data, scanTime);
  }
  updateLastSearchLabel("gc_last_search", scanTime, data.stocks?.length, !options.persist);
};

// Golden Cross 테이블 렌더링
const renderGcScanTable = (stocks) => {
  const buyTargetStates = ['OPTIMAL_BUY', 'BUY_INTEREST', 'READY_TO_BUY'];
  let filtered;

  if (gcFilter === 'all') {
    filtered = stocks;
  } else if (gcFilter === 'BUY_TARGETS') {
    filtered = stocks.filter(s => buyTargetStates.includes(s.gc_state));
  } else if (gcFilter === 'FIN_PASS') {
    filtered = stocks.filter(s => s.financial_filter_status === 'PASS');
  } else if (gcFilter === 'FIN_TURNAROUND') {
    filtered = stocks.filter(s => s.financial_filter_status === 'TURNAROUND');
  } else {
    filtered = stocks.filter(s => s.gc_state === gcFilter);
  }

  const tbody = document.getElementById("gc_scan_table_body");

  // 필터 결과가 없으면 안내 메시지 표시
  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="11" class="placeholder-message" style="border: none;">
      해당 조건에 맞는 종목이 없습니다.
    </td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(stock => {
    const stateClass = getGcStateClass(stock.gc_state);
    const stateLabel = getGcStateLabel(stock.gc_state);
    const finClass = getFinStatusClass(stock.financial_filter_status);
    const finLabel = getFinStatusLabel(stock.financial_filter_status);
    const maGapClass = stock.ma_gap_ratio > 0 ? 'bullish' : 'bearish';
    const stochClass = stock.stoch_k < 30 ? 'bearish' : stock.stoch_k > 70 ? 'bullish' : '';
    const isAdded = addedSymbols.has(stock.symbol);
    const btnClass = isAdded ? 'btn-add added' : 'btn-add';
    const btnText = isAdded ? '추가됨' : '+';
    const stockJson = JSON.stringify(stock).replace(/'/g, "\\'");

    // 재무 데이터 포맷
    const revenueYoy = stock.revenue_yoy != null ? `${stock.revenue_yoy >= 0 ? '+' : ''}${Number(stock.revenue_yoy).toFixed(1)}%` : '-';
    const revenueYoyClass = stock.revenue_yoy != null ? (stock.revenue_yoy >= 0 ? 'bullish' : 'bearish') : '';
    const opMargin = stock.operating_margin != null ? `${Number(stock.operating_margin).toFixed(1)}%` : '-';
    const opMarginClass = stock.operating_margin != null ? (stock.operating_margin > 0 ? 'bullish' : 'bearish') : '';

    return `<tr>
      <td>
        <button class="${btnClass}" onclick='addToHistory(${stockJson}, event)' ${isAdded ? 'disabled' : ''}>${btnText}</button>
      </td>
      <td><strong>${stock.symbol}</strong></td>
      <td>${stock.name}</td>
      <td><span class="state-badge ${stateClass}">${stateLabel}</span></td>
      <td><span class="state-badge ${finClass}">${finLabel}</span></td>
      <td style="font-size:12px; color:#94a3b8;">${stock.industry_name || '-'}</td>
      <td class="indicator">${formatNumber(stock.current_price)}</td>
      <td class="indicator ${maGapClass}">${stock.ma_gap_ratio.toFixed(2)}%</td>
      <td class="indicator ${stochClass}">${stock.stoch_k.toFixed(1)} / ${stock.stoch_d.toFixed(1)}</td>
      <td class="indicator ${revenueYoyClass}">${revenueYoy}</td>
      <td class="indicator ${opMarginClass}">${opMargin}</td>
    </tr>`;
  }).join('');
};

// 재무 필터 상태 클래스
const getFinStatusClass = (status) => {
  const map = {
    'PASS': 'fin-pass',
    'FAIL': 'fin-fail',
    'TURNAROUND': 'fin-turnaround',
    'PENDING': 'fin-pending',
    'ERROR': 'fin-error'
  };
  return map[status] || 'fin-pending';
};

// 재무 필터 상태 라벨
const getFinStatusLabel = (status) => {
  const map = {
    'PASS': '통과',
    'FAIL': '미통과',
    'TURNAROUND': '턴어라운드',
    'PENDING': '미조회',
    'ERROR': '오류'
  };
  return map[status] || '미조회';
};

const showGcTab = (filter) => {
  gcFilter = filter;
  document.querySelectorAll('#gc_scan_container .tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  renderGcScanTable(gcScanStocks);
};

const getGcStateClass = (state) => {
  const map = {
    'NOT_GC': 'state-waiting-gc',
    'GC_ACTIVE': 'state-waiting-pullback',
    'WAITING_FOR_PULLBACK': 'state-waiting-pullback',
    'READY_TO_BUY': 'state-ready-buy',
    'BUY_INTEREST': 'state-buy-interest',
    'OPTIMAL_BUY': 'state-optimal-buy'
  };
  return map[state] || '';
};

const getGcStateLabel = (state) => {
  const map = {
    'NOT_GC': 'GC 비활성',
    'GC_ACTIVE': 'GC 활성',
    'WAITING_FOR_PULLBACK': '눌림목 대기',
    'READY_TO_BUY': '매수 관심',
    'BUY_INTEREST': '매수 관심',
    'OPTIMAL_BUY': '매수 적기'
  };
  return map[state] || state;
};

// Universe API 응답 처리 (종목 스캔)
const displayUniverseStocks = (data) => {
  universeStocks = data.stocks || [];
  document.getElementById("universe_list_container").style.display = "block";
  { const el = document.getElementById("stock_list_container"); if (el) el.style.display = "none"; }
  document.getElementById("gc_scan_container").style.display = "none";
  document.getElementById("stats_row").style.display = "flex";

  // 통계 업데이트
  const total = universeStocks.length;
  const kospiCount = universeStocks.filter(s => s.market === 'KOSPI').length;
  const kosdaqCount = universeStocks.filter(s => s.market === 'KOSDAQ').length;
  const eligibleCount = universeStocks.filter(s => s.is_eligible).length;

  document.getElementById("stat_total").textContent = total;
  document.getElementById("stat_gc").textContent = kospiCount;
  document.getElementById("stat_pullback").textContent = kosdaqCount;
  document.getElementById("stat_ready").textContent = eligibleCount;
  document.getElementById("stat_optimal").textContent = '-';
  document.getElementById("stat_position").textContent = '-';

  renderUniverseTable(universeStocks);
};

const renderUniverseTable = (stocks) => {
  const filtered = universeFilter === 'all' ? stocks :
    stocks.filter(s => s.market === universeFilter);

  const tbody = document.getElementById("universe_table_body");
  tbody.innerHTML = filtered.map(stock => {
    const marketClass = stock.market === 'KOSPI' ? 'state-waiting-pullback' : 'state-waiting-gc';
    const score = parseFloat(stock.screening_score) || 0;
    const scoreClass = score >= 70 ? 'bullish' : score >= 50 ? '' : 'bearish';

    return `<tr>
      <td><strong>${stock.symbol}</strong></td>
      <td>${stock.name || '-'}</td>
      <td><span class="state-badge ${marketClass}">${stock.market}</span></td>
      <td>${stock.sector || '-'}</td>
      <td class="indicator">${formatMarketCap(stock.market_cap)}</td>
      <td class="indicator">${formatNumber(stock.current_price)}</td>
      <td class="indicator">${formatVolume(stock.avg_volume_20d)}</td>
      <td class="indicator ${scoreClass}">${score.toFixed(0)}</td>
    </tr>`;
  }).join('');
};

const showUniverseTab = (filter) => {
  universeFilter = filter;
  document.querySelectorAll('#universe_list_container .tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  renderUniverseTable(universeStocks);
};

// Symbol States API 응답 처리 (전략 종목 상태)
const displayStockList = (data) => {
  allStocks = data.states || [];
  const stockListEl = document.getElementById("stock_list_container");
  if (stockListEl) stockListEl.style.display = "block";
  document.getElementById("universe_list_container").style.display = "none";
  document.getElementById("gc_scan_container").style.display = "none";
  document.getElementById("stats_row").style.display = "flex";

  // 통계 업데이트
  const total = allStocks.length;
  const gcCount = allStocks.filter(s => s.state === 'WAITING_FOR_GC').length;
  const pullbackCount = allStocks.filter(s => s.state === 'WAITING_FOR_PULLBACK').length;
  const readyCount = allStocks.filter(s => s.state === 'READY_TO_BUY').length;
  const positionCount = allStocks.filter(s => s.state === 'IN_POSITION').length;

  document.getElementById("stat_total").textContent = total;
  document.getElementById("stat_gc").textContent = gcCount;
  document.getElementById("stat_pullback").textContent = pullbackCount;
  document.getElementById("stat_ready").textContent = readyCount;
  document.getElementById("stat_optimal").textContent = '-';
  document.getElementById("stat_position").textContent = positionCount;

  renderTable(allStocks);
};

const renderTable = (stocks) => {
  const filtered = currentFilter === 'all' ? stocks :
    currentFilter === 'ready' ? stocks.filter(s => s.state === 'READY_TO_BUY') :
    currentFilter === 'pullback' ? stocks.filter(s => s.state === 'WAITING_FOR_PULLBACK') :
    currentFilter === 'position' ? stocks.filter(s => s.state === 'IN_POSITION') : stocks;

  const tbody = document.getElementById("stock_table_body");
  if (!tbody) return;
  tbody.innerHTML = filtered.map(stock => {
    const stateClass = getStateClass(stock.state);
    const stateLabel = getStateLabel(stock.state);
    const pnl = stock.unrealized_pnl_ratio ? (stock.unrealized_pnl_ratio * 100).toFixed(2) + '%' : '-';
    const pnlClass = stock.unrealized_pnl_ratio > 0 ? 'bullish' : stock.unrealized_pnl_ratio < 0 ? 'bearish' : '';

    return `<tr>
      <td><strong>${stock.symbol}</strong></td>
      <td>${stock.name || '-'}</td>
      <td><span class="state-badge ${stateClass}">${stateLabel}</span></td>
      <td class="indicator">${formatNumber(stock.last_close)}</td>
      <td class="indicator">${formatNumber(stock.last_ma_short)}</td>
      <td class="indicator">${formatNumber(stock.last_ma_long)}</td>
      <td class="indicator">${stock.last_stoch_k ? stock.last_stoch_k.toFixed(1) : '-'}</td>
      <td class="indicator ${pnlClass}">${pnl}</td>
    </tr>`;
  }).join('');
};

const showTab = (filter) => {
  currentFilter = filter;
  document.querySelectorAll('#stock_list_container .tab').forEach(t => t.classList.remove('active'));
  event.target.classList.add('active');
  renderTable(allStocks);
};

const getStateClass = (state) => {
  const map = {
    'WAITING_FOR_GC': 'state-waiting-gc',
    'WAITING_FOR_PULLBACK': 'state-waiting-pullback',
    'READY_TO_BUY': 'state-ready-buy',
    'IN_POSITION': 'state-in-position'
  };
  return map[state] || '';
};

const getStateLabel = (state) => {
  const map = {
    'WAITING_FOR_GC': 'GC 대기',
    'WAITING_FOR_PULLBACK': '눌림목 대기',
    'READY_TO_BUY': '매수 대기',
    'IN_POSITION': '보유 중'
  };
  return map[state] || state;
};

const formatNumber = (num) => {
  if (!num) return '-';
  return Number(num).toLocaleString();
};

const formatTime = (dateStr) => {
  if (!dateStr) return '-';
  const date = new Date(dateStr);
  if (isNaN(date.getTime())) return '-';
  return date.toLocaleTimeString('ko-KR', { timeZone: 'Asia/Seoul' });
};

const formatMarketCap = (cap) => {
  if (!cap) return '-';
  const num = parseFloat(cap);
  if (num >= 1e12) return (num / 1e12).toFixed(1) + '조';
  if (num >= 1e8) return (num / 1e8).toFixed(0) + '억';
  return num.toLocaleString();
};

const formatVolume = (vol) => {
  if (!vol) return '-';
  const num = parseFloat(vol);
  if (num >= 1e6) return (num / 1e6).toFixed(1) + 'M';
  if (num >= 1e3) return (num / 1e3).toFixed(0) + 'K';
  return num.toLocaleString();
};

const loadSavedScans = () => {
  const gcSaved = loadLastScan(BUY_STORAGE_KEYS.gc);
  if (gcSaved?.data) {
    // persist: false로 캐시 데이터 표시 (savedAt 갱신 방지)
    displayGcScanResults(gcSaved.data, { persist: false });
    updateLastSearchLabel("gc_last_search", gcSaved.timestamp, gcSaved.data.stocks?.length, gcSaved.isStale);
    const staleText = gcSaved.isStale ? ' (캐시됨)' : '';
    document.getElementById("scan_output").textContent =
      `마지막 스캔${staleText} (${formatDateTime(gcSaved.timestamp)}): ` +
      `${gcSaved.data.stocks?.length || 0}개 종목`;
  } else {
    // 저장된 결과 없음 - 안내 메시지 표시
    document.getElementById("gc_scan_container").style.display = "block";
    document.getElementById("gc_scan_table_body").innerHTML = `
      <tr><td colspan="11" class="placeholder-message" style="border: none;">
        저장된 스캔 결과가 없습니다.<br>
        <small style="color: #94a3b8;">골든크로스 스캔 버튼을 클릭하세요.</small>
      </td></tr>
    `;
  }

  const ma5Saved = loadLastScan(BUY_STORAGE_KEYS.ma5);
  if (ma5Saved?.data) {
    // persist: false로 캐시 데이터 표시 (savedAt 갱신 방지)
    displayMA5ScanResults(ma5Saved.data, { persist: false });
    updateLastSearchLabel("ma5_last_search", ma5Saved.timestamp, ma5Saved.data.stocks?.length, ma5Saved.isStale);
    const staleText = ma5Saved.isStale ? ' (캐시됨)' : '';
    document.getElementById("ma5_scan_output").textContent =
      `마지막 스캔${staleText} (${formatDateTime(ma5Saved.timestamp)}): ` +
      `${ma5Saved.data.stocks?.length || 0}개 종목`;
  } else {
    // 저장된 결과 없음 - 안내 메시지 표시
    document.getElementById("ma5_scan_container").style.display = "block";
    document.getElementById("ma5_scan_table_body").innerHTML = `
      <tr><td colspan="9" class="placeholder-message" style="border: none;">
        저장된 스캔 결과가 없습니다.<br>
        <small style="color: #94a3b8;">MA5 돌파 스캔 버튼을 클릭하세요.</small>
      </td></tr>
    `;
  }
};

// 페이지 로드 시 히스토리 로드 + 마지막 스캔 복원
document.addEventListener('DOMContentLoaded', () => {
  loadBuyHistory();
  loadSavedScans();

  // localStorage에서 마지막 갱신 정보 로드
  const cachedRefresh = loadLastRefresh();
  if (cachedRefresh?.data) {
    updateLastRefreshLabel(cachedRefresh.data, cachedRefresh.isStale);
  }

  // 전략 목록 로드(선택)
  if (document.getElementById('strategy_list_table_body') && typeof loadStrategies === "function") {
    loadStrategies();
  }

  const controlInput = document.getElementById('control_strategy_id');
  if (controlInput) {
    controlInput.addEventListener('input', () => {
      const id = parseInt(controlInput.value, 10);
      updateSelectedStrategyLabel(!Number.isNaN(id) && id > 0 ? id : null);
    });
  }
});


// ==================== Strategy Control (CRUD/Lifecycle) ====================

const getControlStrategyId = () => {
  const raw = document.getElementById('control_strategy_id')?.value;
  const id = raw ? parseInt(raw, 10) : NaN;
  if (!id || Number.isNaN(id)) {
    alert('Strategy ID를 입력해줘');
    return null;
  }
  return id;
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

const setControlOutput = (msg) => {
  const el = document.getElementById('strategy_control_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
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
    const data = await getJson('/api/v1/strategies/scheduler/status', null);
    setControlOutput(data);
  } catch (e) {
    setControlOutput(`오류: ${e.message}`);
  }
};

// expose to window (onclick handlers)
window.startStrategy = startStrategy;
window.pauseStrategy = pauseStrategy;
window.stopStrategy = stopStrategy;
window.executeStrategy = executeStrategy;
window.getSchedulerStatus = getSchedulerStatus;


// ==================== Strategy List / CRUD (minimal) ====================

function setStrategyDetailOutput(msg) {
  const el = document.getElementById('strategy_detail_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
}

function setStrategyPatchOutput(msg) {
  const el = document.getElementById('strategy_patch_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
}

function setStrategyConfigOutput(msg) {
  const el = document.getElementById('strategy_config_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
}

function setSymbolStatesOutput(msg) {
  const el = document.getElementById('symbol_states_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
}

function setSignalsOutput(msg) {
  const el = document.getElementById('signals_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
}

function setSignalsStatisticsOutput(msg) {
  const el = document.getElementById('signals_statistics_output');
  if (!el) return;
  el.textContent = typeof msg === 'string' ? msg : JSON.stringify(msg, null, 2);
}

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
      data: { success: false, status: res.status, detail: 'JSON 파싱 실패' }
    };
  }
};

const getStrategyFromResponse = (payload) => {
  if (!payload) return null;
  if (payload.data?.strategy) return payload.data.strategy;
  if (payload.data?.id) return payload.data;
  if (payload.strategy) return payload.strategy;
  if (payload.id) return payload;
  return null;
};

const updateSelectedStrategyLabel = (id) => {
  const el = document.getElementById('selected_strategy_label');
  if (!el) return;
  el.textContent = id ? `ID ${id}` : '-';
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
    const list = Array.isArray(strategy.symbols) ? strategy.symbols.join(',') : (strategy.symbols || '');
    symbols.value = list;
  }
};

const resetStrategyPatchForm = () => {
  const ids = [
    'patch_strategy_name',
    'patch_strategy_status',
    'patch_strategy_description',
    'patch_strategy_symbols'
  ];
  ids.forEach((id) => {
    const el = document.getElementById(id);
    if (!el) return;
    if (el.tagName === 'SELECT') {
      el.value = '';
    } else {
      el.value = '';
    }
  });
  setStrategyPatchOutput('(PATCH 결과가 여기에 표시됩니다)');
};

function renderStrategyList(strategies) {
  const body = document.getElementById('strategy_list_table_body');
  if (!body) return;

  if (!strategies || !strategies.length) {
    body.innerHTML = `<tr><td colspan="6" class="placeholder-message" style="border:none;">전략이 없습니다.</td></tr>`;
    return;
  }

  body.innerHTML = strategies.map((s) => {
    const symbols = Array.isArray(s.symbols) ? s.symbols.join(', ') : (s.symbols || '');
    return `
      <tr onclick="selectStrategy(${s.id})">
        <td>${s.id}</td>
        <td>${s.name || '-'}</td>
        <td>${s.strategy_type || '-'}</td>
        <td>${s.status || '-'}</td>
        <td style="max-width: 360px; overflow:hidden; text-overflow: ellipsis; white-space: nowrap;">${symbols}</td>
        <td>
          <button class="secondary" onclick="event.stopPropagation(); selectStrategy(${s.id})">Select</button>
          <button class="secondary" onclick="event.stopPropagation(); startStrategyById(${s.id})">Start</button>
          <button class="secondary" onclick="event.stopPropagation(); pauseStrategyById(${s.id})">Pause</button>
          <button class="secondary" onclick="event.stopPropagation(); stopStrategyById(${s.id})">Stop</button>
          <button onclick="event.stopPropagation(); deleteStrategy(${s.id})" style="background:#fecaca;color:#991b1b;">Delete</button>
        </td>
      </tr>
    `;
  }).join('');
}

async function loadStrategies() {
  setStrategyDetailOutput('전략 목록 로딩 중...');
  try {
    const res = await fetch('/api/v1/strategies');
    const parsed = await readJsonSafely(res);
    if (parsed.ok && parsed.data?.success && parsed.data?.data) {
      renderStrategyList(parsed.data.data.strategies || []);
      return;
    }
    // 오류일 때만 상세 출력 영역에 표시(목록 새로고침이 상세 JSON을 덮어쓰지 않도록)
    setStrategyDetailOutput(parsed.data);
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
}

async function selectStrategy(id) {
  const input = document.getElementById('control_strategy_id');
  if (input) input.value = String(id);
  updateSelectedStrategyLabel(id);

  setStrategyDetailOutput(`전략 ${id} 상세 로딩 중...`);
  try {
    const res = await fetch(`/api/v1/strategies/${id}`);
    const parsed = await readJsonSafely(res);
    setStrategyDetailOutput(parsed.data);
    if (parsed.ok) {
      const strategy = getStrategyFromResponse(parsed.data);
      if (strategy) {
        fillStrategyPatchForm(strategy);
      }
    }
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
}

function parseSymbols(raw) {
  if (!raw) return [];
  return raw.split(',').map(s => s.trim()).filter(Boolean);
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
      if (parsed.data?.data?.id) {
        await selectStrategy(parsed.data.data.id);
      }
    }
  } catch (e) {
    setStrategyDetailOutput(`오류: ${e.message}`);
  }
}

async function deleteStrategy(id) {
  if (!confirm(`전략 ${id}를 삭제할까?`)) return;
  setStrategyDetailOutput('전략 삭제 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}`, { method: 'DELETE' });
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

// ==================== Strategy Patch / Config / Signals ====================

const loadSelectedStrategyDetail = async () => {
  const id = getSelectedStrategyId('strategy_detail_output');
  if (!id) return;
  await selectStrategy(id);
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
      await loadStrategies();
      await selectStrategy(id);
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
    // 혹시 wrapper 형태로 복사해둔 경우 자동 언랩
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

const renderSymbolStatesTable = (items) => {
  const body = document.getElementById('symbol_states_table_body');
  if (!body) return;

  if (!items || items.length === 0) {
    body.innerHTML = `<tr><td colspan="4" class="placeholder-message" style="border:none;">결과가 없습니다.</td></tr>`;
    return;
  }

  body.innerHTML = items.map((item) => {
    return `
      <tr>
        <td>${item.symbol || '-'}</td>
        <td>${item.state || '-'}</td>
        <td>${item.last_close ?? '-'}</td>
        <td>${item.unrealized_pnl_ratio ?? '-'}</td>
      </tr>
    `;
  }).join('');
};

const loadSymbolStates = async () => {
  const id = getSelectedStrategyId('symbol_states_output');
  if (!id) return;

  setSymbolStatesOutput('Symbol States 조회 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/symbol-states`);
    const parsed = await readJsonSafely(res);
    setSymbolStatesOutput(parsed.data);
    if (parsed.ok) {
      const list =
        parsed.data?.data?.items ||
        parsed.data?.data?.symbol_states ||
        parsed.data?.data?.states ||
        parsed.data?.data?.symbols ||
        parsed.data?.items ||
        parsed.data?.symbol_states ||
        parsed.data?.states ||
        parsed.data?.symbols ||
        [];
      renderSymbolStatesTable(Array.isArray(list) ? list : []);
    }
  } catch (e) {
    setSymbolStatesOutput(`오류: ${e.message}`);
  }
};

const renderSignalsTable = (items) => {
  const body = document.getElementById('signals_table_body');
  if (!body) return;

  if (!items || items.length === 0) {
    body.innerHTML = `<tr><td colspan="6" class="placeholder-message" style="border:none;">결과가 없습니다.</td></tr>`;
    return;
  }

  body.innerHTML = items.map((item) => {
    const ts = item.signal_at || item.created_at || item.time || item.timestamp || '-';
    return `
      <tr>
        <td>${ts}</td>
        <td>${item.symbol || '-'}</td>
        <td>${item.signal_type || '-'}</td>
        <td>${item.signal_status || '-'}</td>
        <td>${item.signal_price ?? '-'}</td>
        <td>${item.target_quantity ?? item.executed_quantity ?? '-'}</td>
      </tr>
    `;
  }).join('');
};

const loadSignals = async () => {
  const id = getSelectedStrategyId('signals_output');
  if (!id) return;

  const limit = parseInt(document.getElementById('signals_limit')?.value || '50', 10);
  const offset = parseInt(document.getElementById('signals_offset')?.value || '0', 10);

  setSignalsOutput('Signals 조회 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/signals?limit=${limit}&offset=${offset}`);
    const parsed = await readJsonSafely(res);
    setSignalsOutput(parsed.data);
    if (parsed.ok) {
      const list =
        parsed.data?.data?.signals ||
        parsed.data?.data?.items ||
        parsed.data?.signals ||
        parsed.data?.items ||
        [];
      renderSignalsTable(Array.isArray(list) ? list : []);
    }
  } catch (e) {
    setSignalsOutput(`오류: ${e.message}`);
  }
};

const loadSignalStatistics = async () => {
  const id = getSelectedStrategyId('signals_statistics_output');
  if (!id) return;

  setSignalsStatisticsOutput('Signals statistics 조회 중...');
  try {
    const res = await fetch(`/api/v1/strategies/${id}/signals/statistics`);
    const parsed = await readJsonSafely(res);
    setSignalsStatisticsOutput(parsed.data);
  } catch (e) {
    setSignalsStatisticsOutput(`오류: ${e.message}`);
  }
};

// wrappers for list action buttons
const setControlStrategyId = (id) => {
  const el = document.getElementById("control_strategy_id");
  if (!el) return false;
  el.value = String(id);
  updateSelectedStrategyLabel(id);
  return true;
};

const startStrategyById = (id) => { if (setControlStrategyId(id)) startStrategy(); };
const pauseStrategyById = (id) => { if (setControlStrategyId(id)) pauseStrategy(); };
const stopStrategyById = (id) => { if (setControlStrategyId(id)) stopStrategy(); };

window.loadStrategies = loadStrategies;
window.selectStrategy = selectStrategy;
window.createStrategy = createStrategy;
window.deleteStrategy = deleteStrategy;
window.startStrategyById = startStrategyById;
window.pauseStrategyById = pauseStrategyById;
window.stopStrategyById = stopStrategyById;
window.resetStrategyPatchForm = resetStrategyPatchForm;
window.loadSelectedStrategyDetail = loadSelectedStrategyDetail;
window.patchStrategy = patchStrategy;
window.getStrategyConfig = getStrategyConfig;
window.patchStrategyConfig = patchStrategyConfig;
window.loadSymbolStates = loadSymbolStates;
window.loadSignals = loadSignals;
window.loadSignalStatistics = loadSignalStatistics;
