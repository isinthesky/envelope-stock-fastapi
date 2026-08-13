// Public Strategy Scan page (/page/scan/)
// - GET /api/v1/public/strategies/scan-capabilities (페이지 진입 시 1회, 409 이후 재조회)
//   시장 select/배지/실행 버튼은 이 capability 응답에 따라 렌더링한다.
// - POST /api/v1/public/strategies/golden-cross-scan (market만 전송)
// - 최근 스캔 결과 최대 20개를 전용 localStorage에 보관하고 페이지 재방문 시 복원
// - 요청 중 버튼 비활성화, 429(쿨다운/실행 중)/503(서비스 장애)/409(시장 비가용) 메시지 표시
// - 모든 API 문자열은 escapeHtml로 이스케이프 후 렌더링하거나 textContent로만 대입한다.

(function () {
  "use strict";

  var CAPABILITIES_ENDPOINT = "/api/v1/public/strategies/scan-capabilities";
  var SCAN_ENDPOINT = "/api/v1/public/strategies/golden-cross-scan";
  var SCAN_STORAGE_KEY = "publicStrategyScanResult:v1";
  var SCAN_STORAGE_VERSION = 1;

  var runButton = document.getElementById("public-scan-run");
  var marketSelect = document.getElementById("public-scan-market");
  var marketLabel = document.getElementById("public-scan-market-label");
  var marketBadge = document.getElementById("public-scan-market-badge");
  var statusEl = document.getElementById("public-scan-status");
  var statsEl = document.getElementById("public-scan-stats");
  var resultEl = document.getElementById("public-scan-result");
  var scanTimeEl = document.getElementById("public-scan-time");
  var scanAgeEl = document.getElementById("public-scan-age");
  var cacheBadgeEl = document.getElementById("public-scan-cache-badge");
  var tableBody = document.getElementById("public-scan-table-body");
  var lastRenderedScan = null;

  var escapeHtml = function (value) {
    return String(value)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  };

  var safeNum = function (value, digits) {
    var n = Number(value);
    if (!Number.isFinite(n)) return "-";
    return digits == null ? n.toLocaleString() : n.toFixed(digits);
  };

  var STATE_CLASS = {
    NOT_GC: "state-not-gc",
    GC_ACTIVE: "state-gc-active",
    WAITING_FOR_PULLBACK: "state-waiting-pullback",
    BUY_INTEREST: "state-buy-interest",
    READY_TO_BUY: "state-ready-buy",
    OPTIMAL_BUY: "state-optimal-buy",
    FEAR_BUY: "state-fear-buy",
  };

  var STATE_LABEL = {
    NOT_GC: "GC 비활성",
    GC_ACTIVE: "GC 활성",
    WAITING_FOR_PULLBACK: "눌림목 대기",
    BUY_INTEREST: "매수 관심",
    READY_TO_BUY: "매수 준비",
    OPTIMAL_BUY: "매수 적기",
    FEAR_BUY: "공포 매수",
  };

  // 서버의 canonical 추천 우선순위와 동일한 등급 순서. 공개 응답도 최대 20개로 제한된다.
  var STATE_ORDER = [
    "OPTIMAL_BUY",
    "BUY_INTEREST",
    "READY_TO_BUY",
    "WAITING_FOR_PULLBACK",
    "GC_ACTIVE",
    "FEAR_BUY",
    "NOT_GC",
  ];
  var MAX_DISPLAY_RESULTS = 20;

  var MARKET_TEXT = {
    KOSPI: "KOSPI",
    KOSDAQ: "KOSDAQ",
    ETF: "ETF",
  };

  var setStatus = function (message, kind) {
    statusEl.textContent = message || "";
    statusEl.classList.remove("is-error", "is-warn");
    if (kind === "error") statusEl.classList.add("is-error");
    if (kind === "warn") statusEl.classList.add("is-warn");
  };

  var formatKstTime = function (iso) {
    if (!iso) return "-";
    var d = new Date(iso);
    if (Number.isNaN(d.getTime())) return "-";
    return d.toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
  };

  var formatRelativeTime = function (iso) {
    var scannedAt = new Date(iso);
    if (Number.isNaN(scannedAt.getTime())) return "시각 확인 불가";
    var seconds = Math.max(0, Math.floor((Date.now() - scannedAt.getTime()) / 1000));
    if (seconds < 60) return "방금 전";
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + "분 전";
    var hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + "시간 전";
    return Math.floor(hours / 24) + "일 전";
  };

  var updateScanTimeDisplay = function () {
    if (!lastRenderedScan) return;
    var marketText = lastRenderedScan.market
      ? MARKET_TEXT[lastRenderedScan.market] || String(lastRenderedScan.market)
      : "전체";
    scanAgeEl.textContent = formatRelativeTime(lastRenderedScan.scanTime) + " 스캔";
    scanTimeEl.textContent =
      formatKstTime(lastRenderedScan.scanTime) + " · " + marketText + " 시장";
    cacheBadgeEl.hidden = !lastRenderedScan.restored;
  };

  var setText = function (id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  // ==================== 시장 선택 컨트롤 (capability 기반) ====================

  var clearMarketOptions = function () {
    while (marketSelect.firstChild) {
      marketSelect.removeChild(marketSelect.firstChild);
    }
  };

  // option label은 textContent로만 대입한다 (innerHTML 미사용, 서버 문자열이어도 안전).
  var addMarketOption = function (value, label) {
    var opt = document.createElement("option");
    opt.value = value;
    opt.textContent = label;
    marketSelect.appendChild(opt);
  };

  // select/badge/버튼을 "선택 불가 + placeholder" 상태로 되돌린 뒤 필요한 부분만 덮어쓴다.
  var resetControlsDisabled = function (placeholderLabel) {
    clearMarketOptions();
    addMarketOption("", placeholderLabel);
    marketSelect.disabled = true;
    marketSelect.hidden = false;
    if (marketLabel) marketLabel.hidden = false;
    marketBadge.hidden = true;
    marketBadge.textContent = "";
    runButton.disabled = true;
  };

  var showLoadingControls = function () {
    resetControlsDisabled("불러오는 중...");
    setStatus("스캔 가능한 시장 정보를 불러오는 중입니다...", null);
  };

  var showUnavailableControls = function (notice) {
    resetControlsDisabled("스캔 준비 중");
    setStatus(notice ? String(notice) : "현재 스캔 가능한 유니버스를 준비 중입니다.", "warn");
  };

  var marketBadgeText = function (marketOption) {
    var value = marketOption && marketOption.value;
    var label = (marketOption && marketOption.label) || MARKET_TEXT[value] || String(value || "");
    return label + " 전용 유니버스";
  };

  var showSingleMarketControl = function (marketOption, notice) {
    clearMarketOptions();
    addMarketOption(marketOption.value, marketOption.label || marketOption.value);
    marketSelect.value = marketOption.value;
    marketSelect.disabled = true;
    marketSelect.hidden = true;
    if (marketLabel) marketLabel.hidden = true;
    marketBadge.textContent = marketBadgeText(marketOption);
    marketBadge.hidden = false;
    runButton.disabled = false;
    setStatus(notice ? String(notice) : "", null);
  };

  var showMultiMarketControl = function (markets, allowAll, notice) {
    clearMarketOptions();
    if (allowAll) addMarketOption("", "전체");
    markets.forEach(function (m) {
      addMarketOption(m.value, m.label || m.value);
    });
    marketSelect.disabled = false;
    marketSelect.hidden = false;
    if (marketLabel) marketLabel.hidden = false;
    marketBadge.hidden = true;
    marketBadge.textContent = "";
    // 저장 결과의 시장이 여전히 지원되면 같은 범위로 바로 재스캔할 수 있게 선택한다.
    if (
      lastRenderedScan &&
      lastRenderedScan.market &&
      markets.some(function (market) {
        return market.value === lastRenderedScan.market;
      })
    ) {
      marketSelect.value = lastRenderedScan.market;
    }
    runButton.disabled = false;
    setStatus(notice ? String(notice) : "", null);
  };

  var applyCapability = function (data) {
    var capability = data && typeof data === "object" ? data : {};
    var markets = Array.isArray(capability.markets) ? capability.markets : [];
    var notice = capability.notice;

    if (!capability.scan_enabled || markets.length === 0) {
      showUnavailableControls(notice);
      return false;
    }
    if (markets.length === 1) {
      showSingleMarketControl(markets[0], notice);
      return true;
    }
    showMultiMarketControl(markets, !!capability.allow_all, notice);
    return true;
  };

  // capability 재조회. 409(MARKET_NOT_AVAILABLE/SCAN_TARGETS_CHANGED) 이후에도 재사용한다.
  var loadCapabilities = function (messageAfterRefresh) {
    showLoadingControls();
    return fetch(CAPABILITIES_ENDPOINT, { method: "GET" })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            return null;
          })
          .then(function (body) {
            return { ok: res.ok, body: body };
          });
      })
      .then(function (result) {
        if (!result.ok || !result.body || result.body.success !== true || !result.body.data) {
          resetControlsDisabled("스캔 준비 중");
          setStatus("스캔 가능 여부를 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.", "error");
          return;
        }
        var enabled = applyCapability(result.body.data);
        // 409 원인 안내가 재조회 중/성공 상태 문구에 즉시 덮이지 않게 한다.
        // 재조회 실패 또는 전체 비가용이면 그 상태가 더 중요하므로 덮어쓰지 않는다.
        if (enabled && messageAfterRefresh) {
          setStatus(messageAfterRefresh, "warn");
        }
      })
      .catch(function () {
        resetControlsDisabled("스캔 준비 중");
        setStatus("네트워크 오류로 스캔 가능 여부를 확인하지 못했습니다.", "error");
      });
  };

  // ==================== 스캔 결과 렌더링 ====================

  var sanitizeStockForStorage = function (stock) {
    return {
      symbol: String(stock.symbol || ""),
      name: String(stock.name || ""),
      market: String(stock.market || ""),
      current_price: stock.current_price,
      ma_gap_ratio: stock.ma_gap_ratio,
      stoch_k: stock.stoch_k,
      stoch_d: stock.stoch_d,
      gc_state: String(stock.gc_state || ""),
    };
  };

  var sanitizeResultForStorage = function (data) {
    return {
      stocks: (Array.isArray(data.stocks) ? data.stocks : [])
        .slice(0, MAX_DISPLAY_RESULTS)
        .map(sanitizeStockForStorage),
      total_scanned: data.total_scanned,
      gc_active_count: data.gc_active_count,
      pullback_waiting_count: data.pullback_waiting_count,
      buy_interest_count: data.buy_interest_count,
      ready_to_buy_count: data.ready_to_buy_count,
      optimal_buy_count: data.optimal_buy_count,
      scan_time: data.scan_time,
      error_count: data.error_count,
      market: data.market == null ? null : String(data.market),
      outcome: data.outcome,
    };
  };

  var saveResult = function (data) {
    try {
      window.localStorage.setItem(
        SCAN_STORAGE_KEY,
        JSON.stringify({ version: SCAN_STORAGE_VERSION, data: sanitizeResultForStorage(data) })
      );
    } catch (_error) {
      // 비공개 모드/용량 제한 등 저장 실패가 스캔 결과 표시를 방해하지 않게 한다.
    }
  };

  var removeStoredResult = function () {
    try {
      window.localStorage.removeItem(SCAN_STORAGE_KEY);
    } catch (_error) {
      // storage 접근 자체가 금지된 환경에서는 무시한다.
    }
  };

  var loadStoredResult = function () {
    try {
      var raw = window.localStorage.getItem(SCAN_STORAGE_KEY);
      if (!raw) return null;
      var stored = JSON.parse(raw);
      var data = stored && stored.version === SCAN_STORAGE_VERSION ? stored.data : null;
      if (
        !data ||
        typeof data !== "object" ||
        !Array.isArray(data.stocks) ||
        data.stocks.length > MAX_DISPLAY_RESULTS ||
        !data.scan_time ||
        Number.isNaN(new Date(data.scan_time).getTime())
      ) {
        removeStoredResult();
        return null;
      }
      return data;
    } catch (_error) {
      removeStoredResult();
      return null;
    }
  };

  var renderStockRow = function (stock) {
    var state = String(stock.gc_state || "");
    var stateClass = STATE_CLASS[state] || "state-not-gc";
    var stateLabel = STATE_LABEL[state] || state;
    var maGap = Number(stock.ma_gap_ratio);
    var maGapClass = Number.isFinite(maGap) && maGap > 0 ? "bullish" : "bearish";
    return (
      '<tr class="stock-row">' +
      "<td><strong>" + escapeHtml(stock.symbol) + "</strong></td>" +
      "<td>" + escapeHtml(stock.name) + "</td>" +
      "<td>" + escapeHtml(stock.market) + "</td>" +
      '<td class="indicator">' + safeNum(stock.current_price) + "</td>" +
      '<td class="indicator ' + maGapClass + '">' + safeNum(stock.ma_gap_ratio, 2) + "%</td>" +
      '<td class="indicator">' + safeNum(stock.stoch_k, 1) + " / " + safeNum(stock.stoch_d, 1) + "</td>" +
      '<td><span class="state-badge ' + stateClass + '">' + escapeHtml(stateLabel) + "</span></td>" +
      "</tr>"
    );
  };

  var renderSignalGroup = function (state, stocks) {
    var label = STATE_LABEL[state] || state || "기타 신호";
    var rows =
      '<tr class="signal-group-row"><th colspan="7" scope="rowgroup">' +
      escapeHtml(label) +
      '<span class="signal-group-count">' + safeNum(stocks.length) + "종목</span></th></tr>";

    if (state === "OPTIMAL_BUY" && stocks.length === 0) {
      return (
        rows +
        '<tr class="empty-row signal-empty-row"><td colspan="7">매수 적기 종목 없음</td></tr>'
      );
    }
    return rows + stocks.map(renderStockRow).join("");
  };

  var renderGroupedStocks = function (stocks) {
    var visibleStocks = stocks.slice(0, MAX_DISPLAY_RESULTS);
    var grouped = {};
    visibleStocks.forEach(function (stock) {
      var state = String(stock.gc_state || "UNKNOWN");
      if (!grouped[state]) grouped[state] = [];
      grouped[state].push(stock);
    });

    // 매수 적기는 항상 렌더링해 0건도 명시한다. 나머지 등급은 종목이 있을 때만 표시한다.
    var html = renderSignalGroup("OPTIMAL_BUY", grouped.OPTIMAL_BUY || []);
    STATE_ORDER.slice(1).forEach(function (state) {
      if (grouped[state] && grouped[state].length > 0) {
        html += renderSignalGroup(state, grouped[state]);
      }
      delete grouped[state];
    });
    delete grouped.OPTIMAL_BUY;

    // 새 신호 코드가 추가되어도 결과를 버리지 않고 마지막 기타 그룹에 표시한다.
    Object.keys(grouped).forEach(function (state) {
      html += renderSignalGroup(state, grouped[state]);
    });
    return html;
  };

  var renderResult = function (data, options) {
    var renderOptions = options || {};
    setText("stat-total", safeNum(data.total_scanned));
    setText("stat-gc", safeNum(data.gc_active_count));
    setText("stat-pullback", safeNum(data.pullback_waiting_count));
    setText(
      "stat-ready",
      safeNum((Number(data.ready_to_buy_count) || 0) + (Number(data.buy_interest_count) || 0))
    );
    setText("stat-optimal", safeNum(data.optimal_buy_count));
    statsEl.hidden = false;

    lastRenderedScan = {
      scanTime: data.scan_time,
      market: data.market,
      restored: !!renderOptions.restored,
    };
    updateScanTimeDisplay();

    var stocks = Array.isArray(data.stocks) ? data.stocks.slice(0, MAX_DISPLAY_RESULTS) : [];
    // outcome이 없는 응답(구버전 호환)은 total_scanned/stocks로 동일하게 판정한다.
    var outcome =
      data.outcome || (Number(data.total_scanned) > 0 && stocks.length === 0 ? "NO_MATCHES" : "MATCHES_FOUND");

    tableBody.innerHTML = renderGroupedStocks(stocks);
    resultEl.hidden = false;

    var summary = "스캔 완료: 추천 우선순위 " + stocks.length + "개 표시";
    if (outcome === "NO_MATCHES") {
      summary += " · 현재 조건에 맞는 종목 없음";
    }
    summary += " (최대 " + MAX_DISPLAY_RESULTS + "개, 총 " + safeNum(data.total_scanned) + "개 스캔";
    if (Number(data.error_count) > 0) {
      summary += ", 일부 종목 조회 실패 " + safeNum(data.error_count) + "개";
    }
    summary += ")";
    if (renderOptions.restored) {
      setStatus("이 브라우저에 저장된 최근 결과를 복원했습니다. 새 스캔을 실행할 수 있습니다.");
    } else {
      setStatus(summary);
      saveResult(data);
    }
  };

  var formatRetryAfter = function (seconds) {
    var n = Number(seconds);
    if (!Number.isFinite(n) || n <= 0) return "잠시 후";
    if (n >= 60) return "약 " + Math.ceil(n / 60) + "분 후";
    return "약 " + Math.ceil(n) + "초 후";
  };

  var handleConflict = function (body) {
    var details = body && body.error && body.error.details ? body.error.details : null;
    var reason = details ? details.reason : null;

    var message;
    if (reason === "MARKET_NOT_AVAILABLE") {
      message = "선택한 시장은 현재 지원되지 않습니다. 지원 가능한 시장 정보로 갱신했습니다.";
    } else if (reason === "SCAN_TARGETS_CHANGED") {
      message = "스캔 대상 유니버스가 변경되었습니다. 지원 가능한 시장 정보로 갱신했습니다.";
    } else {
      message = "요청을 처리할 수 없어 지원 가능한 시장 정보로 갱신했습니다.";
    }
    setStatus("지원 가능한 시장 정보를 다시 확인하는 중입니다...", "warn");
    // 두 사유 모두 화면이 알고 있던 시장 가용성이 오래됐다는 뜻이므로 capability를 다시 조회한다.
    loadCapabilities(message);
  };

  var runScan = function () {
    if (runButton.disabled) return;

    runButton.disabled = true;
    // 저장/기존 결과는 새 스캔 중에도 유지해 실패 시 빈 화면이 되지 않게 한다.
    if (!lastRenderedScan) {
      statsEl.hidden = true;
      resultEl.hidden = true;
    }
    setStatus("스캔 중입니다... 종목 수에 따라 1~2분 정도 걸릴 수 있습니다.");

    var market = marketSelect && marketSelect.value ? marketSelect.value : null;
    // 409 경로는 loadCapabilities()가 버튼 활성 여부를 새로 결정하므로 finally에서 되살리지 않는다.
    var reenableOnFinish = true;

    fetch(SCAN_ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ market: market }),
    })
      .then(function (res) {
        return res
          .json()
          .catch(function () {
            return null;
          })
          .then(function (body) {
            return { status: res.status, ok: res.ok, body: body };
          });
      })
      .then(function (result) {
        if (result.status === 429) {
          var retryAfter =
            result.body && result.body.error && result.body.error.details
              ? result.body.error.details.retry_after
              : null;
          setStatus(
            "요청이 제한되었습니다. 다른 스캔이 실행 중이거나 재실행 대기 시간입니다. " +
              formatRetryAfter(retryAfter) + " 다시 시도해 주세요.",
            "warn"
          );
          return;
        }
        if (result.status === 409) {
          reenableOnFinish = false;
          handleConflict(result.body);
          return;
        }
        if (result.status === 503) {
          setStatus("스캔 서비스가 일시적으로 이용 불가합니다. 잠시 후 다시 시도해 주세요.", "error");
          return;
        }
        if (!result.ok || !result.body || result.body.success !== true || !result.body.data) {
          setStatus("스캔에 실패했습니다. 잠시 후 다시 시도해 주세요.", "error");
          return;
        }
        renderResult(result.body.data);
      })
      .catch(function () {
        setStatus("네트워크 오류로 스캔에 실패했습니다. 연결 상태를 확인해 주세요.", "error");
      })
      .finally(function () {
        if (reenableOnFinish) runButton.disabled = false;
      });
  };

  if (runButton) {
    runButton.addEventListener("click", runScan);
  }

  var init = function () {
    var stored = loadStoredResult();
    if (stored) renderResult(stored, { restored: true });
    loadCapabilities();
  };

  // 열린 페이지에서도 "몇 분 전/몇 시간 전" 표시가 자연스럽게 갱신된다.
  window.setInterval(updateScanTimeDisplay, 30000);
  document.addEventListener("visibilitychange", updateScanTimeDisplay);

  document.addEventListener("DOMContentLoaded", init);
  if (document.readyState !== "loading") init();
})();
