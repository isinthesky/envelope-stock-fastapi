// Public Strategy Recommendations page (/page/recommendations/)
// - GET /api/v1/public/strategies/recommendations (스케줄러 스냅샷 캐시 전용)
// - available=false면 빈 화면 안내 (페이지 조회는 스캔을 유발하지 않음)
// - 모든 API 문자열은 escapeHtml로 이스케이프 후 렌더링

(function () {
  "use strict";

  var RECO_ENDPOINT = "/api/v1/public/strategies/recommendations";

  var statusEl = document.getElementById("public-reco-status");
  var contentEl = document.getElementById("public-reco-content");
  var emptyEl = document.getElementById("public-reco-empty");
  var tableBody = document.getElementById("public-reco-table-body");
  var industriesEl = document.getElementById("public-reco-industries");
  var criteriaEl = document.getElementById("public-reco-criteria");

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

  var showEmpty = function () {
    statusEl.textContent = "";
    contentEl.hidden = true;
    emptyEl.hidden = false;
  };

  var render = function (data) {
    statusEl.textContent = "";
    emptyEl.hidden = true;

    setText("public-reco-generated", "생성 시각: " + formatKstTime(data.generated_at));
    setText("public-reco-scan-time", "기준 스캔 시각: " + formatKstTime(data.scan_time));
    setText("public-reco-count", "매수 후보 종목 수: " + safeNum(data.buy_candidate_count));

    var stocks = Array.isArray(data.top_stocks) ? data.top_stocks : [];
    if (stocks.length === 0) {
      tableBody.innerHTML =
        '<tr class="empty-row"><td colspan="6">추천 종목이 없습니다.</td></tr>';
    } else {
      tableBody.innerHTML = stocks
        .map(function (stock) {
          var state = String(stock.gc_state || "");
          var stateClass = STATE_CLASS[state] || "state-not-gc";
          var stateLabel = STATE_LABEL[state] || state;
          return (
            "<tr>" +
            "<td><strong>" + escapeHtml(stock.symbol) + "</strong></td>" +
            "<td>" + escapeHtml(stock.name) + "</td>" +
            "<td>" + escapeHtml(stock.market) + "</td>" +
            '<td class="indicator">' + safeNum(stock.current_price) + "</td>" +
            '<td><span class="state-badge ' + stateClass + '">' + escapeHtml(stateLabel) + "</span></td>" +
            '<td class="indicator">' + safeNum(stock.recommendation_score, 1) + "</td>" +
            "</tr>"
          );
        })
        .join("");
    }

    var industries = Array.isArray(data.top_industries) ? data.top_industries : [];
    industriesEl.innerHTML =
      industries.length === 0
        ? "<li>업종 정보가 없습니다.</li>"
        : industries
            .map(function (industry) {
              return (
                "<li>" +
                escapeHtml(industry.industry_name || "기타") +
                " · " + safeNum(industry.count) + "종목" +
                "</li>"
              );
            })
            .join("");

    var criteria = Array.isArray(data.selection_criteria) ? data.selection_criteria : [];
    criteriaEl.innerHTML =
      criteria.length === 0
        ? "<li>선정 기준 정보가 없습니다.</li>"
        : criteria
            .map(function (item) {
              return "<li>" + escapeHtml(item) + "</li>";
            })
            .join("");

    contentEl.hidden = false;
  };

  var load = function () {
    fetch(RECO_ENDPOINT, { method: "GET" })
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
          statusEl.textContent = "추천 데이터를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
          statusEl.classList.add("is-error");
          return;
        }
        var data = result.body.data;
        if (!data.available) {
          showEmpty();
          return;
        }
        render(data);
      })
      .catch(function () {
        statusEl.textContent = "네트워크 오류로 추천 데이터를 불러오지 못했습니다.";
        statusEl.classList.add("is-error");
      });
  };

  document.addEventListener("DOMContentLoaded", load);
  if (document.readyState !== "loading") load();
})();
