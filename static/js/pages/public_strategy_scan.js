// Public Strategy Scan page (/page/scan/)
// - POST /api/v1/public/strategies/golden-cross-scan (market만 전송)
// - 요청 중 버튼 비활성화, 429(쿨다운/실행 중)/503(서비스 장애) 메시지 표시
// - 모든 API 문자열은 escapeHtml로 이스케이프 후 렌더링

(function () {
  "use strict";

  var SCAN_ENDPOINT = "/api/v1/public/strategies/golden-cross-scan";

  var runButton = document.getElementById("public-scan-run");
  var marketSelect = document.getElementById("public-scan-market");
  var statusEl = document.getElementById("public-scan-status");
  var statsEl = document.getElementById("public-scan-stats");
  var resultEl = document.getElementById("public-scan-result");
  var scanTimeEl = document.getElementById("public-scan-time");
  var tableBody = document.getElementById("public-scan-table-body");

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

  var setText = function (id, value) {
    var el = document.getElementById(id);
    if (el) el.textContent = value;
  };

  var renderResult = function (data) {
    setText("stat-total", safeNum(data.total_scanned));
    setText("stat-gc", safeNum(data.gc_active_count));
    setText("stat-pullback", safeNum(data.pullback_waiting_count));
    setText(
      "stat-ready",
      safeNum((Number(data.ready_to_buy_count) || 0) + (Number(data.buy_interest_count) || 0))
    );
    setText("stat-optimal", safeNum(data.optimal_buy_count));
    statsEl.hidden = false;

    scanTimeEl.textContent = "스캔 시각: " + formatKstTime(data.scan_time);

    var stocks = Array.isArray(data.stocks) ? data.stocks : [];
    if (stocks.length === 0) {
      tableBody.innerHTML =
        '<tr class="empty-row"><td colspan="7">조건에 맞는 종목이 없습니다.</td></tr>';
    } else {
      tableBody.innerHTML = stocks
        .map(function (stock) {
          var state = String(stock.gc_state || "");
          var stateClass = STATE_CLASS[state] || "state-not-gc";
          var stateLabel = STATE_LABEL[state] || state;
          var maGap = Number(stock.ma_gap_ratio);
          var maGapClass = Number.isFinite(maGap) && maGap > 0 ? "bullish" : "bearish";
          return (
            "<tr>" +
            "<td><strong>" + escapeHtml(stock.symbol) + "</strong></td>" +
            "<td>" + escapeHtml(stock.name) + "</td>" +
            "<td>" + escapeHtml(stock.market) + "</td>" +
            '<td class="indicator">' + safeNum(stock.current_price) + "</td>" +
            '<td class="indicator ' + maGapClass + '">' + safeNum(stock.ma_gap_ratio, 2) + "%</td>" +
            '<td class="indicator">' + safeNum(stock.stoch_k, 1) + " / " + safeNum(stock.stoch_d, 1) + "</td>" +
            '<td><span class="state-badge ' + stateClass + '">' + escapeHtml(stateLabel) + "</span></td>" +
            "</tr>"
          );
        })
        .join("");
    }
    resultEl.hidden = false;

    var summary =
      "스캔 완료: " + stocks.length + "개 종목 표시 (총 " + safeNum(data.total_scanned) + "개 스캔";
    if (Number(data.error_count) > 0) {
      summary += ", 일부 종목 조회 실패 " + safeNum(data.error_count) + "개";
    }
    summary += ")";
    setStatus(summary);
  };

  var formatRetryAfter = function (seconds) {
    var n = Number(seconds);
    if (!Number.isFinite(n) || n <= 0) return "잠시 후";
    if (n >= 60) return "약 " + Math.ceil(n / 60) + "분 후";
    return "약 " + Math.ceil(n) + "초 후";
  };

  var runScan = function () {
    runButton.disabled = true;
    statsEl.hidden = true;
    resultEl.hidden = true;
    setStatus("스캔 중입니다... 종목 수에 따라 1~2분 정도 걸릴 수 있습니다.");

    var market = marketSelect && marketSelect.value ? marketSelect.value : null;

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
        runButton.disabled = false;
      });
  };

  if (runButton) {
    runButton.addEventListener("click", runScan);
  }
})();
