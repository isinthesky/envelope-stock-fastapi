// Public sell signal analysis (/page/sell-analysis/)
(function () {
  "use strict";

  var ENDPOINT = "/api/v1/public/strategies/sell-analysis";
  var LEGACY_STORAGE_KEY = "publicSellAnalysisResult:v1";
  var HISTORY_STORAGE_KEY = "publicSellAnalysisHistory:v2";
  var HISTORY_STORAGE_VERSION = 2;
  var MAX_HISTORY_RESULTS = 20;
  var form = document.getElementById("public-sell-form");
  var symbolInput = document.getElementById("public-sell-symbol");
  var runButton = document.getElementById("public-sell-run");
  var statusEl = document.getElementById("public-sell-status");
  var resultEl = document.getElementById("public-sell-result");
  var resultHeading = document.getElementById("public-sell-result-heading");
  var historySection = document.getElementById("public-sell-history-section");
  var historyList = document.getElementById("public-sell-history-list");
  var lastResult = null;
  var historyResults = [];

  var STAGE_CLASS = {
    HOLD: "state-hold",
    REDUCE_1: "state-reduce-1",
    REDUCE_2: "state-reduce-2",
    EXIT_ALL: "state-exit-all",
  };

  var setText = function (id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value == null || value === "" ? "-" : String(value);
  };

  var setStatus = function (message, kind) {
    statusEl.textContent = message || "";
    statusEl.classList.remove("is-error", "is-warn");
    if (kind === "error") statusEl.classList.add("is-error");
    if (kind === "warn") statusEl.classList.add("is-warn");
  };

  var number = function (value, digits) {
    var parsed = Number(value);
    if (!Number.isFinite(parsed)) return "-";
    return digits == null ? parsed.toLocaleString("ko-KR") : parsed.toFixed(digits);
  };

  var percentRange = function (min, max) {
    var low = Number(min) * 100;
    var high = Number(max) * 100;
    if (!Number.isFinite(low) || !Number.isFinite(high)) return "-";
    if (low === high) return low.toFixed(0) + "%";
    return low.toFixed(0) + "~" + high.toFixed(0) + "%";
  };

  var formatKstTime = function (iso) {
    var date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "시각 확인 불가";
    return date.toLocaleString("ko-KR", { timeZone: "Asia/Seoul" }) + " KST";
  };

  var formatRelativeTime = function (iso) {
    var date = new Date(iso);
    if (Number.isNaN(date.getTime())) return "시각 확인 불가";
    var seconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
    if (seconds < 60) return "방금 전";
    var minutes = Math.floor(seconds / 60);
    if (minutes < 60) return minutes + "분 전";
    var hours = Math.floor(minutes / 60);
    if (hours < 24) return hours + "시간 전";
    return Math.floor(hours / 24) + "일 전";
  };

  var freshnessLabel = function (iso) {
    var ageMs = Date.now() - new Date(iso).getTime();
    if (ageMs >= 24 * 60 * 60 * 1000) return " · 오래된 결과";
    if (ageMs >= 5 * 60 * 1000) return " · 다시 분석 권장";
    return "";
  };

  var updateTime = function () {
    if (!lastResult) return;
    setText("public-sell-age", formatRelativeTime(lastResult.analyzed_at) + freshnessLabel(lastResult.analyzed_at));
    setText("public-sell-time", formatKstTime(lastResult.analyzed_at));
    document.querySelectorAll("[data-history-analyzed-at]").forEach(function (element) {
      element.textContent = formatRelativeTime(element.dataset.historyAnalyzedAt);
    });
  };

  var sanitize = function (data) {
    var allowed = [
      "symbol", "name", "current_price", "analyzed_at", "is_cached", "candle_count",
      "ma_short", "ma_long", "ma_gap_ratio", "is_death_cross", "is_gc_active",
      "stoch_k", "stoch_d", "is_stoch_overbought", "is_stoch_dead_cross", "rsi",
      "is_rsi_overbought", "sell_phase", "sell_phase_name", "sell_phase_action",
      "final_stage", "final_stage_name", "final_ratio_min", "final_ratio_max",
      "sell_reasons", "sell_stage_reasons", "volume_ratio", "is_volume_spike",
      "price_drop_ratio", "is_volume_sell_signal", "adx", "plus_di", "minus_di",
      "is_strong_uptrend", "is_strong_downtrend", "overbought_sell_blocked"
    ];
    var safe = {};
    allowed.forEach(function (key) { safe[key] = data[key]; });
    safe.sell_reasons = Array.isArray(data.sell_reasons) ? data.sell_reasons.slice(0, 10) : [];
    safe.sell_stage_reasons = Array.isArray(data.sell_stage_reasons) ? data.sell_stage_reasons.slice(0, 10) : [];
    return safe;
  };

  var isValidStoredResult = function (data) {
    return !!(
      data &&
      typeof data === "object" &&
      /^[0-9A-Z]{6}$/.test(data.symbol) &&
      !Number.isNaN(new Date(data.analyzed_at).getTime())
    );
  };

  var persistHistory = function () {
    try {
      window.localStorage.setItem(
        HISTORY_STORAGE_KEY,
        JSON.stringify({ version: HISTORY_STORAGE_VERSION, entries: historyResults })
      );
    } catch (_error) { /* 저장 불가 환경은 결과 표시에 영향 없음 */ }
  };

  var removeStoredHistory = function () {
    try { window.localStorage.removeItem(HISTORY_STORAGE_KEY); } catch (_error) { /* 무시 */ }
  };

  var loadLegacyResult = function () {
    try {
      var raw = window.localStorage.getItem(LEGACY_STORAGE_KEY);
      if (!raw) return null;
      var stored = JSON.parse(raw);
      return stored && stored.version === 1 && isValidStoredResult(stored.data)
        ? sanitize(stored.data)
        : null;
    } catch (_error) {
      return null;
    } finally {
      try { window.localStorage.removeItem(LEGACY_STORAGE_KEY); } catch (_error) { /* 무시 */ }
    }
  };

  var loadHistory = function () {
    try {
      var raw = window.localStorage.getItem(HISTORY_STORAGE_KEY);
      if (raw) {
        var stored = JSON.parse(raw);
        if (stored && stored.version === HISTORY_STORAGE_VERSION && Array.isArray(stored.entries)) {
          historyResults = stored.entries
            .filter(isValidStoredResult)
            .slice(0, MAX_HISTORY_RESULTS)
            .map(sanitize);
          if (historyResults.length !== stored.entries.length) persistHistory();
          return;
        }
        removeStoredHistory();
      }
      var legacy = loadLegacyResult();
      historyResults = legacy ? [legacy] : [];
      if (legacy) persistHistory();
    } catch (_error) {
      historyResults = [];
      removeStoredHistory();
    }
  };

  var saveToHistory = function (data) {
    var safe = sanitize(data);
    // 새 분석에서 종목명이 확인되면 같은 종목의 과거 무명 이력도 보강한다.
    // 분석 당시의 지표/시각은 그대로 유지하고 표시용 이름만 갱신한다.
    if (safe.name) {
      historyResults = historyResults.map(function (entry) {
        if (entry.symbol !== safe.symbol || entry.name) return entry;
        var enriched = sanitize(entry);
        enriched.name = safe.name;
        return enriched;
      });
    }
    historyResults = historyResults.filter(function (entry) {
      return !(entry.symbol === safe.symbol && entry.analyzed_at === safe.analyzed_at);
    });
    historyResults.unshift(safe);
    historyResults = historyResults.slice(0, MAX_HISTORY_RESULTS);
    persistHistory();
    renderHistory();
  };

  var renderHistory = function () {
    while (historyList.firstChild) historyList.removeChild(historyList.firstChild);
    historySection.hidden = historyResults.length === 0;
    setText("public-sell-history-count", historyResults.length + " / " + MAX_HISTORY_RESULTS);

    historyResults.forEach(function (entry, index) {
      var item = document.createElement("li");
      var button = document.createElement("button");
      var identity = document.createElement("span");
      var stage = document.createElement("span");
      var time = document.createElement("span");
      var relative = document.createElement("span");

      button.type = "button";
      button.className = "sell-history-item";
      button.dataset.historyIndex = String(index);
      button.setAttribute(
        "aria-label",
        entry.symbol + " " + (entry.name || "") + ", " + formatKstTime(entry.analyzed_at) + " 분석 보기"
      );
      identity.className = "sell-history-identity";
      identity.textContent = entry.symbol + (entry.name ? " · " + entry.name : "");
      stage.className = "state-badge " + (STAGE_CLASS[entry.final_stage] || "state-hold");
      stage.textContent = entry.final_stage_name || "보유 유지";
      time.className = "sell-history-time";
      time.textContent = formatKstTime(entry.analyzed_at);
      relative.className = "sell-history-relative";
      relative.dataset.historyAnalyzedAt = entry.analyzed_at;
      relative.textContent = formatRelativeTime(entry.analyzed_at);

      button.appendChild(identity);
      button.appendChild(stage);
      button.appendChild(time);
      button.appendChild(relative);
      item.appendChild(button);
      historyList.appendChild(item);
    });
  };

  var renderReasons = function (data) {
    var list = document.getElementById("public-sell-reasons");
    while (list.firstChild) list.removeChild(list.firstChild);
    var reasons = (data.sell_stage_reasons || []).concat(data.sell_reasons || []).slice(0, 20);
    if (reasons.length === 0) reasons = ["현재 뚜렷한 매도 신호가 없습니다."];
    reasons.forEach(function (reason) {
      var item = document.createElement("li");
      item.textContent = String(reason);
      list.appendChild(item);
    });
  };

  var renderResult = function (data, options) {
    var opts = options || {};
    lastResult = sanitize(data);
    symbolInput.value = lastResult.symbol;
    setText("public-sell-stock", lastResult.symbol + (lastResult.name ? " · " + lastResult.name : ""));
    setText("public-sell-stage-name", lastResult.final_stage_name);
    setText("public-sell-ratio", percentRange(lastResult.final_ratio_min, lastResult.final_ratio_max));
    setText("public-sell-price", number(lastResult.current_price));
    setText("public-sell-ma", number(lastResult.ma_short, 2) + " / " + number(lastResult.ma_long, 2));
    setText("public-sell-ma-state", lastResult.is_death_cross ? "데드크로스" : (lastResult.is_gc_active ? "골든크로스 유지" : "중립"));
    setText("public-sell-stoch", number(lastResult.stoch_k, 1) + " / " + number(lastResult.stoch_d, 1));
    setText("public-sell-stoch-state", lastResult.is_stoch_overbought ? "과매수" : (lastResult.is_stoch_dead_cross ? "하락 교차" : "중립"));
    setText("public-sell-rsi", number(lastResult.rsi, 1));
    setText("public-sell-rsi-state", lastResult.is_rsi_overbought ? "과매수" : "중립");
    setText("public-sell-volume", lastResult.volume_ratio == null ? "-" : number(Number(lastResult.volume_ratio) * 100, 0) + "%");
    setText("public-sell-volume-state", lastResult.is_volume_sell_signal ? "거래량 매도 신호" : (lastResult.is_volume_spike ? "거래량 급증" : "특이 신호 없음"));
    setText("public-sell-adx", lastResult.adx == null ? "-" : number(lastResult.adx, 1) + " / " + number(lastResult.plus_di, 1) + " / " + number(lastResult.minus_di, 1));
    setText("public-sell-trend-state", lastResult.is_strong_downtrend ? "강한 하락 추세" : (lastResult.is_strong_uptrend ? "강한 상승 추세" : "약한 추세/횡보"));
    setText("public-sell-candles", number(lastResult.candle_count));
    setText("public-sell-phase-name", lastResult.sell_phase_name || "판단 요약");
    setText("public-sell-phase-action", lastResult.sell_phase_action);

    var stageEl = document.getElementById("public-sell-stage");
    stageEl.className = "state-badge " + (STAGE_CLASS[lastResult.final_stage] || "state-hold");
    stageEl.textContent = lastResult.final_stage_name || "보유 유지";
    document.getElementById("public-sell-local-badge").hidden = !opts.restored;
    document.getElementById("public-sell-server-cache-badge").hidden = !lastResult.is_cached;
    renderReasons(lastResult);
    updateTime();
    resultEl.hidden = false;
    resultEl.setAttribute("aria-busy", "false");

    if (opts.restored) {
      setStatus(opts.fromHistory
        ? "저장된 분석 이력을 열었습니다. 분석 시점을 확인하고 필요하면 다시 분석해 주세요."
        : "이 브라우저에 저장된 최근 분석을 복원했습니다. 필요하면 다시 분석할 수 있습니다.");
    } else {
      setStatus(lastResult.is_cached ? "서버에 저장된 최근 분석을 불러왔습니다." : "기술지표 분석을 완료했습니다.");
      saveToHistory(lastResult);
      resultHeading.focus();
    }
  };

  var retryText = function (seconds) {
    var value = Number(seconds);
    if (!Number.isFinite(value) || value <= 0) return "잠시 후";
    return value >= 60 ? "약 " + Math.ceil(value / 60) + "분 후" : "약 " + Math.ceil(value) + "초 후";
  };

  var submit = function (event) {
    event.preventDefault();
    var symbol = symbolInput.value.trim().toUpperCase();
    symbolInput.value = symbol;
    if (!/^[0-9A-Z]{6}$/.test(symbol)) {
      setStatus("6자리 KRX 종목코드를 입력해 주세요.", "error");
      symbolInput.focus();
      return;
    }

    runButton.disabled = true;
    runButton.textContent = "분석 중…";
    resultEl.setAttribute("aria-busy", "true");
    setStatus("기술지표를 분석하고 있습니다. 잠시만 기다려 주세요.");

    fetch(ENDPOINT, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol: symbol }),
    })
      .then(function (response) {
        return response.json().catch(function () { return null; }).then(function (body) {
          return { status: response.status, ok: response.ok, body: body };
        });
      })
      .then(function (result) {
        var details = result.body && result.body.error ? result.body.error.details || {} : {};
        if (result.status === 422) {
          setStatus("종목코드 형식을 확인해 주세요. 6자리 숫자 또는 영문 코드를 사용할 수 있습니다.", "error");
        } else if (result.status === 409) {
          setStatus("해당 종목의 분석 데이터가 없거나 충분하지 않습니다.", "warn");
        } else if (result.status === 429) {
          setStatus("요청이 제한되었습니다. " + retryText(details.retry_after) + " 다시 시도해 주세요.", "warn");
        } else if (result.status === 503) {
          setStatus("분석 서비스가 일시적으로 이용 불가합니다. 잠시 후 다시 시도해 주세요.", "error");
        } else if (!result.ok || !result.body || result.body.success !== true || !result.body.data) {
          setStatus("분석에 실패했습니다. 잠시 후 다시 시도해 주세요.", "error");
        } else {
          renderResult(result.body.data);
        }
      })
      .catch(function () {
        setStatus("네트워크 오류로 분석에 실패했습니다. 연결 상태를 확인해 주세요.", "error");
      })
      .finally(function () {
        runButton.disabled = false;
        runButton.textContent = "분석하기";
        resultEl.setAttribute("aria-busy", "false");
      });
  };

  var init = function () {
    loadHistory();
    renderHistory();
    if (historyResults.length > 0) renderResult(historyResults[0], { restored: true });
  };

  form.addEventListener("submit", submit);
  historyList.addEventListener("click", function (event) {
    var button = event.target.closest("[data-history-index]");
    if (!button || !historyList.contains(button)) return;
    var selected = historyResults[Number(button.dataset.historyIndex)];
    if (selected) {
      renderResult(selected, { restored: true, fromHistory: true });
      resultHeading.focus();
    }
  });
  window.setInterval(updateTime, 30000);
  document.addEventListener("visibilitychange", updateTime);
  document.addEventListener("DOMContentLoaded", init);
  if (document.readyState !== "loading") init();
})();
