

const API_BASE = "https://keiba-ev-tool.onrender.com";
const TIMEOUT_MS = 60000;
const EV_THRESHOLD = 0.12;
const FINISH_GRACE_MS = 30 * 60 * 1000;

(function(){
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js", { updateViaCache: "none" }).then(function(reg){ reg.update(); });
    navigator.serviceWorker.addEventListener("controllerchange", function(){ window.location.reload(); });
  }

  var $ = function(id){ return document.getElementById(id); };
  var list = $("race-list"), detail = $("detail"), detailTitle = $("detail-title"), detailBody = $("detail-body");
  var backBtn = $("back-btn"), racesSection = $("races");
  var tabPredict = $("tab-predict"), tabAnalytics = $("tab-analytics"), tabBets = $("tab-bets"), tabHorse = $("tab-horse");
  var fMinProb = $("f-minprob"), fMinOdds = $("f-minodds"), fCollateral = $("f-collateral"), fMaxInv = $("f-maxinv"), fBetUnit = $("f-betunit"), fBetMode = $("f-betmode");
  var anaSummary = $("ana-summary"), anaView = $("ana-view");
  var anaViewTabs = $("ana-view-tabs");
  var betsSummary = $("bets-summary"), betsList = $("bets-list"), curveCanvas = $("curve-chart");
  var analyticsData = null, currentScope = "all", currentView = "ev", filters = {}, currentBets = [];
  var currentFeatureTab = null;
  var analyticsFeaturesData = null;
  var analyticsMultiData = null;
  var analyticsFrameData = null;
  var frameTabFilter = { venue: "", surface: "", distance_band: "", track_condition: "" };
  var currentMultiTicket = null;
  var currentMultiFeature = null;
  var currentFeatureFilter = "all";
  var currentRaceTableFeature = null;
  var currentSingleFeature = null;
  var singleFeatureFilter = "sig";
  var currentTicket = "mixed";
  var currentAnaScope = "all";
  var currentTabName = "predict";
  var ticketStats = null;
  var currentModelVersion = null;
  var anaModelFilter = null;
  var currentModelFilter = "";
  var currentRaceRunners = [];
  var runnerSort = "num";
  var storageBadge = $("storage-badge");

  function esc(s){ return String(s == null ? "" : s).replace(/[&<>\x27]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","\x27":"&#39;"}[c]; }); }
  function ticketLabel(t){ return ({mixed:"馬連",trifecta:"3連単",trio:"3連複",exacta:"馬単",quinella:"馬連",wide:"ワイド",win:"単勝",place:"複勝"}[t] || t); }
  var TRACK_NAMES = {"12":"水沢","42":"笠松","51":"園田","31":"浦和","06":"水沢","20":"笠松","26":"園田","13":"浦和","11":"門別","55":"大井","61":"川崎","03":"船橋","41":"名古屋","43":"金沢"};
  function raceLabel(raceId, fallbackVenue, fallbackRn){
    if (!raceId) return "";
    // nar-YYYYMMDD-trackcd-racenb 形式
    var m = String(raceId).match(/^nar-(\d{8})-(\d+)-(\d+)$/);
    if (m){
      var track = m[2];
      var rn = parseInt(m[3], 10);
      var venue = TRACK_NAMES[track] || (fallbackVenue || "");
      return venue + " " + rn + "R";
    }
    return raceId;
  }
  function fmtPct(v, d){ return Number(v).toFixed(d == null ? 2 : d) + "%"; }
  function fmtNum(v, d){ return Number(v).toFixed(d == null ? 2 : d); }
  function fmtSignedPct(v, d){ return (v >= 0 ? "+" : "") + Number(v).toFixed(d == null ? 2 : d) + "%"; }
  function fmtInt(v){ return String(Math.round(v)); }
  function fmtYen(v){ return fmtInt(v) + "円"; }
  function fmtSigned(v, d){ return (v >= 0 ? "+" : "") + fmtNum(v, d); }

  var FILTER_KEY = "keiba-filters-v1";

  function loadFiltersFromStorage(){
    try {
      var raw = localStorage.getItem(FILTER_KEY);
      if (!raw) return;
      var o = JSON.parse(raw);
      if (o && typeof o === "object") {
        if (o.minProb != null) fMinProb.value = o.minProb;
        if (o.minOdds != null) fMinOdds.value = o.minOdds;
        if (o.collateral != null) fCollateral.value = o.collateral;
        if (o.maxInvestment != null) fMaxInv.value = o.maxInvestment;
        if (o.betUnit != null) fBetUnit.value = o.betUnit;
        if (o.betMode && fBetMode) fBetMode.value = o.betMode;
      }
    } catch (e) {}
  }

  function saveFiltersToStorage(){
    try {
      localStorage.setItem(FILTER_KEY, JSON.stringify({ minProb: fMinProb.value, minOdds: fMinOdds.value, collateral: fCollateral.value, maxInvestment: fMaxInv.value, betUnit: fBetUnit.value, betMode: (fBetMode ? fBetMode.value : "compound") }));
    } catch (e) {}
  }

  function readFilters(){
    filters.minProb = Math.max(0, Number(fMinProb.value || 0)) / 100;
    filters.minOdds = Math.max(0, Number(fMinOdds.value || 0));
    filters.collateral = Math.max(1000, Math.round(Number(fCollateral.value || 100000)));
    filters.maxInvestment = Math.max(100, Math.round(Number(fMaxInv.value || 10000)));
    filters.betUnit = Math.max(100, Math.round(Number(fBetUnit.value || 500)));
    filters.betMode = fBetMode ? fBetMode.value : "compound";
  }

  function sortRaces(races){ return races.slice().sort(function(a, b){ var sa = a.start_at || "", sb = b.start_at || ""; return sa < sb ? -1 : sa > sb ? 1 : 0; }); }
  function isFinished(r){ var t = null; if (r.deadline_at) t = Date.parse(r.deadline_at); else if (r.start_at) t = Date.parse(r.start_at) - 120000; if (t == null || isNaN(t)) return false; return Date.now() > t; }

  function renderList(races){
    var visible = sortRaces(races.filter(function(r){ return !isFinished(r); }));
    if (!visible.length) { list.textContent = "本日のレースはありません（終了分を除く）"; return; }
    var groups = {};
    var order = [];
    visible.forEach(function(r){
      var v = r.venue || r.course || "その他";
      if (!groups[v]) { groups[v] = []; order.push(v); }
      groups[v].push(r);
    });
    var html = "";
    order.forEach(function(v){
      html += "<div class=\"venue-group\"><h3>" + esc(v) + "</h3>";
      groups[v].forEach(function(r){
        var no = r.race_number || r.race_no || 1;
        var surface = r.surface || "", dist = r.distance || "";
        var time = (r.start_at || "").slice(11, 16);
        var runners = (r.runners || []).length;
        var waku = KeibaTheme.wakuClass(no);
        html += "<div class=\"race\" data-race-id=\"" + esc(r.race_id) + "\" role=\"button\" tabindex=\"0\">" + "<span class=\"" + waku + "\">" + no + "</span> " + no + "R " + esc(surface) + " " + esc(dist) + "m " + esc(time) + " 発走 / " + runners + "頭" + "</div>";
      });
      html += "</div>";
    });
    list.innerHTML = html;
  }

  function renderDetail(race){
    detailTitle.textContent = (race.venue || "") + " " + (race.race_number || "") + "R";
    var evLabel = document.getElementById("ev-title-label");
    if (evLabel) evLabel.textContent = "EV上位の買い目 (" + ticketLabel(currentTicket) + ")";
    var html = "<h3 class=\"ev-title\" id=\"ev-title-label\">EV上位の買い目</h3><div id=\"ev-table\">読み込み中...</div>";
    html += "<h3 class=\"ev-title\">出走馬</h3>";
    html += "<div class=\"sort-bar\" id=\"runner-sort-bar\">" +
            "<button class=\"sort-btn active\" data-sort=\"num\" type=\"button\">馬番</button>" +
            "<button class=\"sort-btn\" data-sort=\"pop\" type=\"button\">人気</button>" +
            "<button class=\"sort-btn\" data-sort=\"odds\" type=\"button\">単勝</button>" +
            "<button class=\"sort-btn\" data-sort=\"weight\" type=\"button\">斤量</button>" +
            "</div>";
    html += "<div id=\"runner-table-wrap\"></div>";
    currentRaceRunners = race.runners || [];
    var runners = [];
    if (!currentRaceRunners.length) { html += "<p>出走馬データがありません</p>"; }
    detailBody.innerHTML = html;
    racesSection.hidden = true;
    detail.hidden = false;
    window.scrollTo(0, 0);
    renderRunnerTable();
    bindSortBar();
    loadEvTable(race.race_id);
  }

  function renderRunnerTable(){
    var wrap = document.getElementById("runner-table-wrap");
    if (!wrap) return;
    var arr = currentRaceRunners.slice();
    if (runnerSort === "num") {
      arr.sort(function(a, b){ return (a.horse_number || 0) - (b.horse_number || 0); });
    } else if (runnerSort === "pop") {
      arr.sort(function(a, b){ var pa = a.popularity || a["人気"] || 999; var pb = b.popularity || b["人気"] || 999; return pa - pb; });
    } else if (runnerSort === "odds") {
      arr.sort(function(a, b){ var oa = a.odds_win || a["勝ちオッズ"] || 9999; var ob = b.odds_win || b["勝ちオッズ"] || 9999; return oa - ob; });
    } else if (runnerSort === "weight") {
      arr.sort(function(a, b){ var wa = a.weight || a.wEight || 0; var wb = b.weight || b.wEight || 0; return wb - wa; });
    }
    var html = "<table class=\"horse-table\"><thead><tr><th>枠</th><th>番</th><th>馬名</th><th>騎手</th><th>斤量</th><th>単勝</th><th>人気</th></tr></thead><tbody>";
    arr.forEach(function(h){
      var frame = h.frame_number || h.waku || 0, num = h.horse_number || h.num || 0;
      var waku = KeibaTheme.wakuClass(frame || num);
      var ln = h.lineage_nb || h.horse_id || "";
      var nameHtml = "";
      if (ln) {
        nameHtml = "<a class=\"horse-link\" href=\"#\" data-horse-link=\"" + esc(ln) + "\">" + esc(h.horse_name || "") + "</a>";
      } else {
        nameHtml = esc(h.horse_name || "");
      }
      html += "<tr><td><span class=\"" + waku + "\">" + frame + "</span></td><td>" + num + "</td><td>" + nameHtml + "</td><td>" + esc(h.jockey || "") + "</td><td>" + (h.weight || h.wEight || "") + "</td><td>" + (h.odds_win || h["勝ちオッズ"] || "") + "</td><td>" + (h["人気"] || h.popularity || "") + "</td></tr>";
    });
    html += "</tbody></table>";
    wrap.innerHTML = html;
    var links = wrap.querySelectorAll("[data-horse-link]");
    for (var i = 0; i < links.length; i++) {
      links[i].addEventListener("click", function(e){
        e.preventDefault();
        var ln = this.getAttribute("data-horse-link");
        if (ln) openHorseByLineage(ln);
      });
    }
  }
  function openHorseByLineage(lineageNb){
    switchTab("horse");
    var idEl = $("horse-id");
    if (idEl) idEl.value = lineageNb;
    loadHorse();
  }

  function bindSortBar(){
    var bar = document.getElementById("runner-sort-bar");
    if (!bar) return;
    bar.querySelectorAll(".sort-btn").forEach(function(btn){
      btn.addEventListener("click", function(){
        bar.querySelectorAll(".sort-btn").forEach(function(x){ x.classList.remove("active"); });
        btn.classList.add("active");
        runnerSort = btn.getAttribute("data-sort");
        renderRunnerTable();
      });
    });
  }

  function renderEvTable(raceId, bets, totalAmount){
    var box = $("ev-table");
    if (!box) return;
    currentBets = bets || [];
    if (!currentBets.length) { box.textContent = "条件に合う買い目はありません"; return; }
    var html = "<p class=\"ev-total\">推奨合計: " + fmtYen(totalAmount) + " / " + currentBets.length + "点</p>";
    html += "<table class=\"ev-table\"><thead><tr><th>買い目</th><th>確率</th><th>オッズ</th><th>EV</th><th>金額</th><th></th></tr></thead><tbody>";
    currentBets.forEach(function(b, idx){
      var cls = KeibaTheme.evClass(b.ev, EV_THRESHOLD);
      html += "<tr class=\"" + cls + "\"><td>" + esc(b.combination) + "</td><td>" + fmtPct(b.prob) + "</td><td>" + fmtNum(b.odds, 1) + "</td><td>" + fmtSigned(b.ev, 3) + "</td><td>" + "<input type=\"number\" class=\"amt-input\" step=\"100\" min=\"100\" value=\"" + b.amount + "\" data-idx=\"" + idx + "\">" + "</td><td><button class=\"bet-btn\" data-idx=\"" + idx + "\" type=\"button\">投票</button></td></tr>";
    });
    html += "</tbody></table>";
    html += "<button class=\"bulk-btn\" id=\"bulk-bet\" type=\"button\">全買い目を一括投票</button>";
    box.innerHTML = html;
    box.querySelectorAll(".bet-btn").forEach(function(btn){
      btn.addEventListener("click", function(){
        var idx = Number(btn.getAttribute("data-idx"));
        var amt = readAmt(box, idx, currentBets[idx].amount);
        recordBet(raceId, currentBets[idx], amt);
      });
    });
    var bulkBtn = box.querySelector("#bulk-bet");
    if (bulkBtn) bulkBtn.addEventListener("click", function(){
      var items = currentBets.map(function(b, i){ return { bet: b, amt: readAmt(box, i, b.amount) }; });
      recordBulk(raceId, items);
    });
  }

  function readAmt(box, idx, fallback){
    var el = box.querySelector(".amt-input[data-idx=\"" + idx + "\"]");
    if (!el) return fallback;
    var v = Math.round(Number(el.value || fallback));
    if (!(v > 0)) return fallback;
    return v;
  }

  function postBet(raceId, b, amount){
    return fetchWithTimeout(API_BASE + "/bets", TIMEOUT_MS, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ race_id: raceId, combo: b.combination, amount: amount, odds: b.odds, prob: b.prob, ev: b.ev, ticket_type: currentTicket, model_version: currentModelVersion }) })
      .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); });
  }

  function recordBet(raceId, b, amount){
    postBet(raceId, b, amount).then(function(){ alert("投票を記録しました"); }).catch(function(err){ alert("記録失敗: " + err.message); });
  }

  function recordBulk(raceId, items){
    if (!items.length) { alert("投票対象なし"); return; }
    var chain = Promise.resolve();
    var okCount = 0, failCount = 0;
    items.forEach(function(it){
      chain = chain.then(function(){
        return postBet(raceId, it.bet, it.amt).then(function(){ okCount++; }).catch(function(){ failCount++; });
      });
    });
    chain.then(function(){ alert("一括投票完了: 成功 " + okCount + " / 失敗 " + failCount); });
  }

  function showList(){ detail.hidden = true; racesSection.hidden = false; window.scrollTo(0, 0); }

  function fetchWithTimeout(url, ms, opts){
    var ctrl = new AbortController();
    var timer = setTimeout(function(){ ctrl.abort(); }, ms);
    var o = opts || {}; o.signal = ctrl.signal;
    return fetch(url, o).finally(function(){ clearTimeout(timer); });
  }

  function loadEvTable(raceId){
    var box = $("ev-table");
    if (!box) return;
    box.textContent = "EV計算中...";
    readFilters();
    var qs = "?race_id=" + encodeURIComponent(raceId) + "&ticket_type=" + encodeURIComponent(currentTicket) + "&bet_mode=" + encodeURIComponent(filters.betMode || "compound") + "&min_prob=" + encodeURIComponent(filters.minProb) + "&min_odds=" + encodeURIComponent(filters.minOdds) + "&collateral=" + encodeURIComponent(filters.collateral) + "&max_investment=" + encodeURIComponent(filters.maxInvestment);
    fetchWithTimeout(API_BASE + "/vote-plans" + qs, TIMEOUT_MS, { method: "POST" })
      .then(function(res){ if (res.status === 204) { renderEvTable(raceId, [], 0); return null; } if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function(data){ if (!data) return; var plan = data.plan || {}; renderEvTable(raceId, plan.bets || [], plan.total_amount || 0); })
      .catch(function(err){ if (box) box.textContent = "EV取得失敗: " + err.message; });
  }

  function loadDetail(raceId){
    detail.hidden = false; racesSection.hidden = true;
    detailTitle.textContent = "読み込み中..."; detailBody.innerHTML = "";
    fetchWithTimeout(API_BASE + "/races/" + encodeURIComponent(raceId), TIMEOUT_MS)
      .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function(race){ renderDetail(race); })
      .catch(function(err){ detailBody.textContent = "取得失敗: " + err.message; });
  }

  function tableRows(rows, label){
    if (!rows || !rows.length) return "<p>該当データなし</p>";
    var html = "<table class=\"ev-table ev-table-13col2\"><thead><tr>";
    html += "<th>" + label + "</th><th>件数</th><th>予想的中率</th><th>オッズ平均</th><th>想定利益%</th>";
    html += "<th>実的中率</th><th>CI下限</th><th>CI上限</th><th>市場的中率</th>";
    html += "<th>実利益%</th><th>CI下限</th><th>CI上限</th><th>市場利益%</th>";
    html += "</tr></thead><tbody>";
    rows.forEach(function(r){
      var actual = r.actual_hit_rate_pct == null ? "-" : fmtPct(r.actual_hit_rate_pct, 2);
      var ap = r.actual_profit_pct == null ? "-" : fmtSignedPct(r.actual_profit_pct, 1);
      var ep = r.expected_profit_pct == null ? "-" : fmtSignedPct(r.expected_profit_pct, 1);
      var ehr = r.expected_hit_rate_pct == null ? "-" : fmtPct(r.expected_hit_rate_pct, 2);
      var hr_ci_lo = r.actual_hit_rate_ci_lo_pct == null ? "-" : fmtPct(r.actual_hit_rate_ci_lo_pct, 2);
      var hr_ci_hi = r.actual_hit_rate_ci_hi_pct == null ? "-" : fmtPct(r.actual_hit_rate_ci_hi_pct, 2);
      var roi_ci_lo = r.actual_profit_ci_lo_pct == null ? "-" : fmtSignedPct(r.actual_profit_ci_lo_pct, 1);
      var roi_ci_hi = r.actual_profit_ci_hi_pct == null ? "-" : fmtSignedPct(r.actual_profit_ci_hi_pct, 1);
      var mhr = r.market_hit_rate_pct == null ? "-" : fmtPct(r.market_hit_rate_pct, 2);
      var mp = r.market_profit_pct == null ? "-" : fmtSignedPct(r.market_profit_pct, 1);
      // 色付け: 実 vs 市場
      var hr_cls = "";
      if (r.actual_hit_rate_pct != null && r.market_hit_rate_pct != null) {
        if (r.actual_hit_rate_pct > r.market_hit_rate_pct) hr_cls = "ev-mid";
        else if (r.actual_hit_rate_pct < r.market_hit_rate_pct) hr_cls = "ev-neg";
      }
      var roi_cls = "";
      if (r.actual_profit_pct != null && r.market_profit_pct != null) {
        if (r.actual_profit_pct > r.market_profit_pct) roi_cls = "ev-mid";
        else if (r.actual_profit_pct < r.market_profit_pct) roi_cls = "ev-neg";
      }
      var ratio = "";
      if (window._anaTotalCount && window._anaTotalCount > 0) {
        ratio = " (" + (r.count / window._anaTotalCount * 100).toFixed(1) + "%)";
      }
      html += "<tr>";
      html += "<td>" + esc(r.range) + "</td>";
      html += "<td>" + r.count + ratio + "</td>";
      html += "<td>" + ehr + "</td>";
      html += "<td>" + fmtNum(r.avg_odds, 1) + "</td>";
      html += "<td>" + ep + "</td>";
      html += "<td class=\"" + hr_cls + "\">" + actual + "</td>";
      html += "<td>" + hr_ci_lo + "</td>";
      html += "<td>" + hr_ci_hi + "</td>";
      html += "<td>" + mhr + "</td>";
      html += "<td class=\"" + roi_cls + "\">" + ap + "</td>";
      html += "<td>" + roi_ci_lo + "</td>";
      html += "<td>" + roi_ci_hi + "</td>";
      html += "<td>" + mp + "</td>";
      html += "</tr>";
    });
    html += "</tbody></table>";
    return html;
  }



  function renderAnaSummary(s, races){
    if (!s) { anaSummary.innerHTML = ""; return; }
    var cnt = s.total_count || 0;
    var hits = s.total_hits || 0;
    var hr = s.hit_rate_pct || 0;
    var racesN = races || 0;
    anaSummary.innerHTML = "<div>対象レース: " + racesN + " / 買い目 " + cnt + " 件</div>"
      + "<div>的中: " + hits + " (" + fmtPct(hr, 2) + ")</div>";
  }

  function renderCumTable(rows, label){
    if (!rows || !rows.length) return "<p>該当データなし</p>";
    var html = "<h4 class=\"feature-title\">" + label + " (累積)</h4>";
    html += "<table class=\"ev-table ev-table-13col2\"><thead><tr>";
    html += "<th>範囲</th><th>件数</th><th>予想的中率</th><th>オッズ平均</th><th>想定利益%</th>";
    html += "<th>実的中率</th><th>CI下限</th><th>CI上限</th><th>市場的中率</th>";
    html += "<th>実利益%</th><th>CI下限</th><th>CI上限</th><th>市場利益%</th>";
    html += "</tr></thead><tbody>";
    rows.forEach(function(r){
      var actual = r.actual_hit_rate_pct == null ? "-" : fmtPct(r.actual_hit_rate_pct, 2);
      var ap = r.actual_profit_pct == null ? "-" : fmtSignedPct(r.actual_profit_pct, 1);
      var ep = r.expected_profit_pct == null ? "-" : fmtSignedPct(r.expected_profit_pct, 1);
      var ehr = r.expected_hit_rate_pct == null ? "-" : fmtPct(r.expected_hit_rate_pct, 2);
      var hr_ci_lo = r.actual_hit_rate_ci_lo_pct == null ? "-" : fmtPct(r.actual_hit_rate_ci_lo_pct, 2);
      var hr_ci_hi = r.actual_hit_rate_ci_hi_pct == null ? "-" : fmtPct(r.actual_hit_rate_ci_hi_pct, 2);
      var roi_ci_lo = r.actual_profit_ci_lo_pct == null ? "-" : fmtSignedPct(r.actual_profit_ci_lo_pct, 1);
      var roi_ci_hi = r.actual_profit_ci_hi_pct == null ? "-" : fmtSignedPct(r.actual_profit_ci_hi_pct, 1);
      var mhr = r.market_hit_rate_pct == null ? "-" : fmtPct(r.market_hit_rate_pct, 2);
      var mp = r.market_profit_pct == null ? "-" : fmtSignedPct(r.market_profit_pct, 1);
      var hr_cls = "";
      if (r.actual_hit_rate_pct != null && r.market_hit_rate_pct != null) {
        if (r.actual_hit_rate_pct > r.market_hit_rate_pct) hr_cls = "ev-mid";
        else if (r.actual_hit_rate_pct < r.market_hit_rate_pct) hr_cls = "ev-neg";
      }
      var roi_cls = "";
      if (r.actual_profit_pct != null && r.market_profit_pct != null) {
        if (r.actual_profit_pct > r.market_profit_pct) roi_cls = "ev-mid";
        else if (r.actual_profit_pct < r.market_profit_pct) roi_cls = "ev-neg";
      }
      var ratio2 = "";
      if (window._anaTotalCount && window._anaTotalCount > 0) {
        ratio2 = " (" + (r.count / window._anaTotalCount * 100).toFixed(1) + "%)";
      }
      html += "<tr>";
      html += "<td>" + esc(r.range) + "</td>";
      html += "<td>" + r.count + ratio2 + "</td>";
      html += "<td>" + ehr + "</td>";
      html += "<td>" + fmtNum(r.avg_odds, 1) + "</td>";
      html += "<td>" + ep + "</td>";
      html += "<td class=\"" + hr_cls + "\">" + actual + "</td>";
      html += "<td>" + hr_ci_lo + "</td>";
      html += "<td>" + hr_ci_hi + "</td>";
      html += "<td>" + mhr + "</td>";
      html += "<td class=\"" + roi_cls + "\">" + ap + "</td>";
      html += "<td>" + roi_ci_lo + "</td>";
      html += "<td>" + roi_ci_hi + "</td>";
      html += "<td>" + mp + "</td>";
      html += "</tr>";
    });
    html += "</tbody></table>";
    return html;
  }

  function renderTicketStatsFromData(){
    if (!analyticsData) return;
    var rows = analyticsData.ticket_stats || [];
    if (!rows.length) { anaView.textContent = "データなし"; return; }
    var html = "<table class=\"ev-table ev-table-13col\"><thead><tr>";
    html += "<th>券種</th><th>件数</th><th>予想的中率</th><th>オッズ平均</th><th>想定利益%</th>";
    html += "<th>実的中率</th><th>CI下限</th><th>CI上限</th>";
    html += "<th>実利益%</th><th>CI下限</th><th>CI上限</th>";
    html += "<th>市場利益%</th><th>理論控除率%</th>";
    html += "</tr></thead><tbody>";
    rows.forEach(function(r){
      var ehr = r.expected_hit_rate_pct == null ? "-" : fmtPct(r.expected_hit_rate_pct, 2);
      var ahr = r.actual_hit_rate_pct == null ? "-" : fmtPct(r.actual_hit_rate_pct, 2);
      var hr_ci_lo = r.actual_hit_rate_ci_lo_pct == null ? "-" : fmtPct(r.actual_hit_rate_ci_lo_pct, 2);
      var hr_ci_hi = r.actual_hit_rate_ci_hi_pct == null ? "-" : fmtPct(r.actual_hit_rate_ci_hi_pct, 2);
      var ep = r.expected_profit_pct == null ? "-" : fmtSignedPct(r.expected_profit_pct, 1);
      var ap = r.actual_profit_pct == null ? "-" : fmtSignedPct(r.actual_profit_pct, 1);
      var roi_ci_lo = r.actual_profit_ci_lo_pct == null ? "-" : fmtSignedPct(r.actual_profit_ci_lo_pct, 1);
      var roi_ci_hi = r.actual_profit_ci_hi_pct == null ? "-" : fmtSignedPct(r.actual_profit_ci_hi_pct, 1);
      // 市場利益% = -(実測控除率%)
      var market_profit_pct = (r.measured_deduction_pct == null) ? null : -r.measured_deduction_pct;
      // 実利益%セルの色: 実 > 市場 → 緑、実 < 市場 → 赤
      var ap_cls = "";
      if (r.actual_profit_pct != null && market_profit_pct != null) {
        if (r.actual_profit_pct > market_profit_pct) ap_cls = "ev-mid";
        else if (r.actual_profit_pct < market_profit_pct) ap_cls = "ev-neg";
      }
      html += "<tr><td>" + esc(r.label) + "</td>"
            + "<td>" + r.count + "</td>"
            + "<td>" + ehr + "</td>"
            + "<td>" + (r.avg_odds == null ? "-" : fmtNum(r.avg_odds, 1)) + "</td>"
            + "<td>" + ep + "</td>"
            + "<td>" + ahr + "</td>"
            + "<td>" + hr_ci_lo + "</td>"
            + "<td>" + hr_ci_hi + "</td>"
            + "<td class=\"" + ap_cls + "\">" + ap + "</td>"
            + "<td>" + roi_ci_lo + "</td>"
            + "<td>" + roi_ci_hi + "</td>"
            + "<td>" + (market_profit_pct == null ? "-" : fmtSignedPct(market_profit_pct, 1)) + "</td>"
            + "<td>" + (r.theory_deduction_pct == null ? "-" : fmtPct(r.theory_deduction_pct, 1)) + "</td></tr>";
    });
    html += "</tbody></table>";
    anaView.innerHTML = html;
  }






  function renderFeatureFilterTabs(){
    var html = "<div class=\"subtabs\">";
    html += "<button class=\"subtab" + (currentFeatureFilter === "all" ? " active" : "") + "\" data-feature-filter=\"all\" type=\"button\">全体</button>";
    html += "<button class=\"subtab" + (currentFeatureFilter === "on" ? " active" : "") + "\" data-feature-filter=\"on\" type=\"button\">適用</button>";
    html += "<button class=\"subtab" + (currentFeatureFilter === "off" ? " active" : "") + "\" data-feature-filter=\"off\" type=\"button\">適用外</button>";
    html += "</div>";
    return html;
  }

  function renderFeatureTable(rows, mode, filter){
    if (!rows || !rows.length) return "<p>該当データなし</p>";
    // 列数: all=13列、on/off=8列
    var colCls = (filter === "all") ? " ev-table-feat-13col" : " ev-table-8col2";
    var html = "<table class=\"ev-table" + colCls + "\"><thead><tr>";
    html += "<th>ビン</th><th>件数</th>";
    if (mode === "roi") {
      if (filter === "all" || filter === "on") html += "<th>適用 実%</th><th>CI下限</th><th>CI上限</th><th>適用 市場%</th><th>適用 差</th>";
      if (filter === "all" || filter === "off") html += "<th>適用外 実%</th><th>CI下限</th><th>CI上限</th><th>適用外 市場%</th><th>適用外 差</th>";
      html += "<th>有意</th>";
    } else {
      if (filter === "all" || filter === "on") html += "<th>適用 実的中率</th><th>CI下限</th><th>CI上限</th><th>適用 市場的中率</th><th>適用 差</th>";
      if (filter === "all" || filter === "off") html += "<th>適用外 実的中率</th><th>CI下限</th><th>CI上限</th><th>適用外 市場的中率</th><th>適用外 差</th>";
      html += "<th>有意</th>";
    }
    html += "</tr></thead><tbody>";
    rows.forEach(function(r){
      html += "<tr>";
      html += "<td>" + esc(r.label) + "</td>";
      var total_n = r.n + (r.n_other || 0);
      var n_display = (filter === "off") ? (r.n_other || 0) : r.n;
      var ratio_str = "";
      if (total_n > 0) {
        ratio_str = " (" + (n_display / total_n * 100).toFixed(1) + "%)";
      }
      html += "<td>" + n_display + ratio_str + "</td>";
      if (mode === "roi") {
        var real_on = r.roi_pct;
        var market_on = -(r.market_rho_pct || 0);
        var diff_on = real_on - market_on;
        var real_off = r.roi_other_pct;
        var market_off = -(r.market_rho_other_pct || 0);
        var diff_off = real_off - market_off;
        // 色付け: 適用/適用外の比較 または 実 vs 市場
        var on_cls = "";
        var off_cls = "";
        if (filter === "all") {
          if (real_on != null && real_off != null) {
            if (real_on > real_off) on_cls = "ev-mid";
            else if (real_on < real_off) on_cls = "ev-neg";
            if (real_off > real_on) off_cls = "ev-mid";
            else if (real_off < real_on) off_cls = "ev-neg";
          }
        } else if (filter === "on") {
          if (real_on != null && market_on != null) {
            if (real_on > market_on) on_cls = "ev-mid";
            else if (real_on < market_on) on_cls = "ev-neg";
          }
        } else if (filter === "off") {
          if (real_off != null && market_off != null) {
            if (real_off > market_off) off_cls = "ev-mid";
            else if (real_off < market_off) off_cls = "ev-neg";
          }
        }
        var cls_diff_on = KeibaTheme.evClass(diff_on / 100, 0);
        var cls_diff_off = KeibaTheme.evClass(diff_off / 100, 0);
        if (filter === "all" || filter === "on") {
          html += "<td class=\"" + on_cls + "\">" + fmtSignedPct(real_on, 1) + "</td>";
          html += "<td>" + (r.roi_b_ci_lo_pct == null ? "-" : fmtSignedPct(r.roi_b_ci_lo_pct, 1)) + "</td>";
          html += "<td>" + (r.roi_b_ci_hi_pct == null ? "-" : fmtSignedPct(r.roi_b_ci_hi_pct, 1)) + "</td>";
          html += "<td>" + fmtSignedPct(market_on, 1) + "</td>";
          html += "<td class=\"" + cls_diff_on + "\">" + fmtSignedPct(diff_on, 1) + "</td>";
        }
        if (filter === "all" || filter === "off") {
          html += "<td class=\"" + off_cls + "\">" + fmtSignedPct(real_off, 1) + "</td>";
          html += "<td>" + (r.roi_c_ci_lo_pct == null ? "-" : fmtSignedPct(r.roi_c_ci_lo_pct, 1)) + "</td>";
          html += "<td>" + (r.roi_c_ci_hi_pct == null ? "-" : fmtSignedPct(r.roi_c_ci_hi_pct, 1)) + "</td>";
          html += "<td>" + fmtSignedPct(market_off, 1) + "</td>";
          html += "<td class=\"" + cls_diff_off + "\">" + fmtSignedPct(diff_off, 1) + "</td>";
        }
        var sig_roi = r.roi_sig_up ? "優位" : (r.roi_sig_down ? "劣位" : "-");
        html += "<td>" + sig_roi + "</td>";
      } else {
        var hr_real_on = r.hit_rate_pct;
        var hr_mkt_on = r.market_hit_rate_pct;
        var hr_diff_on = hr_real_on - hr_mkt_on;
        var hr_real_off = r.hit_rate_other_pct;
        var hr_mkt_off = r.market_hit_rate_other_pct;
        var hr_diff_off = hr_real_off - hr_mkt_off;
        var hon_cls = "";
        var hoff_cls = "";
        if (filter === "all") {
          if (hr_real_on != null && hr_real_off != null) {
            if (hr_real_on > hr_real_off) hon_cls = "ev-mid";
            else if (hr_real_on < hr_real_off) hon_cls = "ev-neg";
            if (hr_real_off > hr_real_on) hoff_cls = "ev-mid";
            else if (hr_real_off < hr_real_on) hoff_cls = "ev-neg";
          }
        } else if (filter === "on") {
          if (hr_real_on != null && hr_mkt_on != null) {
            if (hr_real_on > hr_mkt_on) hon_cls = "ev-mid";
            else if (hr_real_on < hr_mkt_on) hon_cls = "ev-neg";
          }
        } else if (filter === "off") {
          if (hr_real_off != null && hr_mkt_off != null) {
            if (hr_real_off > hr_mkt_off) hoff_cls = "ev-mid";
            else if (hr_real_off < hr_mkt_off) hoff_cls = "ev-neg";
          }
        }
        var hcls_on = KeibaTheme.evClass(hr_diff_on / 100, 0);
        var hcls_off = KeibaTheme.evClass(hr_diff_off / 100, 0);
        if (filter === "all" || filter === "on") {
          html += "<td class=\"" + hon_cls + "\">" + fmtPct(hr_real_on, 2) + "</td>";
          html += "<td>" + (r.hr_b_ci_lo_pct == null ? "-" : fmtPct(r.hr_b_ci_lo_pct, 2)) + "</td>";
          html += "<td>" + (r.hr_b_ci_hi_pct == null ? "-" : fmtPct(r.hr_b_ci_hi_pct, 2)) + "</td>";
          html += "<td>" + fmtPct(hr_mkt_on, 2) + "</td>";
          html += "<td class=\"" + hcls_on + "\">" + fmtSignedPct(hr_diff_on, 2) + "</td>";
        }
        if (filter === "all" || filter === "off") {
          html += "<td class=\"" + hoff_cls + "\">" + fmtPct(hr_real_off, 2) + "</td>";
          html += "<td>" + (r.hr_c_ci_lo_pct == null ? "-" : fmtPct(r.hr_c_ci_lo_pct, 2)) + "</td>";
          html += "<td>" + (r.hr_c_ci_hi_pct == null ? "-" : fmtPct(r.hr_c_ci_hi_pct, 2)) + "</td>";
          html += "<td>" + fmtPct(hr_mkt_off, 2) + "</td>";
          html += "<td class=\"" + hcls_off + "\">" + fmtSignedPct(hr_diff_off, 2) + "</td>";
        }
        var sig_hr = r.hr_sig_up ? "優位" : (r.hr_sig_down ? "劣位" : "-");
        html += "<td>" + sig_hr + "</td>";
      }
      html += "</tr>";
    });
    html += "</tbody></table>";
    return html;
  }

  function renderWeightHandicapTable(whData){
    if (!whData || !whData.rows || !whData.rows.length) return "<p>該当データなし</p>";
    var html = "<table class=\"ev-table\"><thead><tr>";
    html += "<th>斤量</th>";
    html += "<th>減量あり n</th><th>減量なし n</th>";
    html += "<th>減量あり 実%</th><th>減量なし 実%</th>";
    html += "<th>減量あり 的中率</th><th>減量なし 的中率</th>";
    html += "</tr></thead><tbody>";
    whData.rows.forEach(function(r){
      function fmtOrDash(v, d, signed){
        if (v == null) return "-";
        if (signed) return fmtSignedPct(v, d);
        return fmtPct(v, d);
      }
      // 色付け: 大きい方だけ緑（マイナス方向の色付けはしない）
      var cls_roi_y = "";
      var cls_roi_n = "";
      if (r.roi_pct_yes != null && r.roi_pct_no != null) {
        if (r.roi_pct_yes > r.roi_pct_no) cls_roi_y = "ev-mid";
        else if (r.roi_pct_no > r.roi_pct_yes) cls_roi_n = "ev-mid";
      }
      html += "<tr>";
      html += "<td>" + esc(r.weight_label) + "</td>";
      html += "<td>" + r.n_yes + "</td>";
      html += "<td>" + r.n_no + "</td>";
      html += "<td class=\"" + cls_roi_y + "\">" + fmtOrDash(r.roi_pct_yes, 1, true) + "</td>";
      html += "<td class=\"" + cls_roi_n + "\">" + fmtOrDash(r.roi_pct_no, 1, true) + "</td>";
      html += "<td>" + fmtOrDash(r.hr_pct_yes, 2, false) + "</td>";
      html += "<td>" + fmtOrDash(r.hr_pct_no, 2, false) + "</td>";
      html += "</tr>";
    });
    html += "</tbody></table>";
    return html;
  }

  var FRAME_Z = 1.96;

  function emptyAcc() {
    return { n: 0, sum_profit: 0, sum_profit_sq: 0, sum_hit: 0,
             sum_payout: 0, sum_market_prob: 0, sum_rho: 0 };
  }

  function frameRowStats(acc) {
    if (!acc || acc.n === 0) return null;
    var n = acc.n;
    var mean_profit = acc.sum_profit / n;
    var var_profit = acc.sum_profit_sq / n - mean_profit * mean_profit;
    if (var_profit < 0) var_profit = 0;
    var se_profit = Math.sqrt(var_profit / n);
    var roi_pct = mean_profit * 100;
    var roi_ci_lo = (mean_profit - FRAME_Z * se_profit) * 100;
    var roi_ci_hi = (mean_profit + FRAME_Z * se_profit) * 100;
    var p_hat = acc.sum_hit / n;
    var se_p = Math.sqrt(p_hat * (1 - p_hat) / n);
    var hr_pct = p_hat * 100;
    var hr_ci_lo = (p_hat - FRAME_Z * se_p) * 100;
    var hr_ci_hi = (p_hat + FRAME_Z * se_p) * 100;
    return {
      n: n,
      roi_pct: roi_pct,
      roi_ci_lo: roi_ci_lo,
      roi_ci_hi: roi_ci_hi,
      roi_sig_up: roi_ci_lo > 0,
      roi_sig_down: roi_ci_hi < 0,
      hr_pct: hr_pct,
      hr_ci_lo: hr_ci_lo,
      hr_ci_hi: hr_ci_hi,
      hr_sig_up: hr_ci_lo > 0,
      hr_sig_down: hr_ci_hi < 0,
      market_hr_pct: (acc.sum_market_prob / n) * 100,
      rho_pct: (acc.sum_rho / n) * 100
    };
  }

  function aggregateFrameConditionRows() {
    if (!analyticsFrameData) return null;
    var cells = analyticsFrameData.cells || [];
    var matched = cells.filter(function(c){
      if (frameTabFilter.venue && c.venue !== frameTabFilter.venue) return false;
      if (frameTabFilter.surface && c.surface !== frameTabFilter.surface) return false;
      if (frameTabFilter.distance_band && c.distance_band !== frameTabFilter.distance_band) return false;
      if (frameTabFilter.track_condition && c.track_condition !== frameTabFilter.track_condition) return false;
      return true;
    });
    if (!matched.length) return null;
    var perFrame = {};
    for (var f = 1; f <= 8; f++) perFrame[f] = emptyAcc();
    var total = emptyAcc();
    matched.forEach(function(c){
      c.frames.forEach(function(fr){
        if (!fr.n || fr.n === 0) return;
        var a = perFrame[fr.frame];
        a.n += fr.n;
        a.sum_profit += fr.sum_profit || 0;
        a.sum_profit_sq += fr.sum_profit_sq || 0;
        a.sum_hit += fr.sum_hit || 0;
        a.sum_payout += fr.sum_payout || 0;
        a.sum_market_prob += fr.sum_market_prob || 0;
        a.sum_rho += fr.sum_rho || 0;
        total.n += fr.n;
        total.sum_profit += fr.sum_profit || 0;
        total.sum_profit_sq += fr.sum_profit_sq || 0;
        total.sum_hit += fr.sum_hit || 0;
        total.sum_payout += fr.sum_payout || 0;
        total.sum_market_prob += fr.sum_market_prob || 0;
        total.sum_rho += fr.sum_rho || 0;
      });
    });
    var rows = [];
    for (var f = 1; f <= 8; f++) {
      var A = frameRowStats(perFrame[f]);
      var otherAcc = {
        n: total.n - perFrame[f].n,
        sum_profit: total.sum_profit - perFrame[f].sum_profit,
        sum_profit_sq: total.sum_profit_sq - perFrame[f].sum_profit_sq,
        sum_hit: total.sum_hit - perFrame[f].sum_hit,
        sum_payout: total.sum_payout - perFrame[f].sum_payout,
        sum_market_prob: total.sum_market_prob - perFrame[f].sum_market_prob,
        sum_rho: total.sum_rho - perFrame[f].sum_rho
      };
      var O = frameRowStats(otherAcc);
      rows.push({
        label: "枠" + f,
        n: A ? A.n : 0,
        n_other: O ? O.n : total.n,
        roi_pct: A ? A.roi_pct : null,
        roi_other_pct: O ? O.roi_pct : null,
        roi_b_ci_lo_pct: A ? A.roi_ci_lo : null,
        roi_b_ci_hi_pct: A ? A.roi_ci_hi : null,
        roi_c_ci_lo_pct: O ? O.roi_ci_lo : null,
        roi_c_ci_hi_pct: O ? O.roi_ci_hi : null,
        market_rho_pct: A ? A.rho_pct : null,
        market_rho_other_pct: O ? O.rho_pct : null,
        hit_rate_pct: A ? A.hr_pct : null,
        hit_rate_other_pct: O ? O.hr_pct : null,
        hr_b_ci_lo_pct: A ? A.hr_ci_lo : null,
        hr_b_ci_hi_pct: A ? A.hr_ci_hi : null,
        hr_c_ci_lo_pct: O ? O.hr_ci_lo : null,
        hr_c_ci_hi_pct: O ? O.hr_ci_hi : null,
        market_hit_rate_pct: A ? A.market_hr_pct : null,
        market_hit_rate_other_pct: O ? O.market_hr_pct : null,
        roi_sig_up: A ? A.roi_sig_up : false,
        roi_sig_down: A ? A.roi_sig_down : false,
        hr_sig_up: A ? A.hr_sig_up : false,
        hr_sig_down: A ? A.hr_sig_down : false
      });
    }
    return { rows: rows, matched_count: matched.length };
  }

  function aggByDimension(dimKey, minN) {
  if (!analyticsFrameData) return null;
  var cells = analyticsFrameData.cells || [];
  var otherKeys = ["venue","surface","distance_band","track_condition"].filter(function(k){ return k !== dimKey; });
  var buckets = {};
  cells.forEach(function(c){
    for (var i = 0; i < otherKeys.length; i++) {
      var k = otherKeys[i];
      if (frameTabFilter[k] && c[k] !== frameTabFilter[k]) return;
    }
    var v = c[dimKey];
    if (!buckets[v]) {
      buckets[v] = { total: emptyAcc(), perFrame: {} };
      for (var f = 1; f <= 8; f++) buckets[v].perFrame[f] = emptyAcc();
    }
    var b = buckets[v];
    c.frames.forEach(function(fr){
      if (!fr.n || fr.n === 0) return;
      var a = b.perFrame[fr.frame];
      a.n += fr.n; a.sum_profit += fr.sum_profit || 0; a.sum_profit_sq += fr.sum_profit_sq || 0;
      a.sum_hit += fr.sum_hit || 0; a.sum_payout += fr.sum_payout || 0;
      a.sum_market_prob += fr.sum_market_prob || 0; a.sum_rho += fr.sum_rho || 0;
      b.total.n += fr.n; b.total.sum_profit += fr.sum_profit || 0; b.total.sum_profit_sq += fr.sum_profit_sq || 0;
      b.total.sum_hit += fr.sum_hit || 0; b.total.sum_payout += fr.sum_payout || 0;
      b.total.sum_market_prob += fr.sum_market_prob || 0; b.total.sum_rho += fr.sum_rho || 0;
    });
  });
  var rows = [];
  Object.keys(buckets).forEach(function(v){
    var b = buckets[v];
    if (b.total.n < minN) return;
    var frs = [];
    for (var f = 1; f <= 8; f++) {
      var A = frameRowStats(b.perFrame[f]);
      frs.push({ frame: f, n: A ? A.n : 0, hr_pct: A ? A.hr_pct : null, market_hr_pct: A ? A.market_hr_pct : null, roi_pct: A ? A.roi_pct : null });
    }
    var inAcc = emptyAcc(), outAcc = emptyAcc();
    [1,2,3].forEach(function(f){ var a = b.perFrame[f]; inAcc.n += a.n; inAcc.sum_profit += a.sum_profit; inAcc.sum_profit_sq += a.sum_profit_sq; inAcc.sum_hit += a.sum_hit; inAcc.sum_market_prob += a.sum_market_prob; });
    [6,7,8].forEach(function(f){ var a = b.perFrame[f]; outAcc.n += a.n; outAcc.sum_profit += a.sum_profit; outAcc.sum_profit_sq += a.sum_profit_sq; outAcc.sum_hit += a.sum_hit; outAcc.sum_market_prob += a.sum_market_prob; });
    var inStats = frameRowStats(inAcc), outStats = frameRowStats(outAcc);
    var inDiff = inStats ? (inStats.hr_pct - inStats.market_hr_pct) : null;
    var outDiff = outStats ? (outStats.hr_pct - outStats.market_hr_pct) : null;
    var diffGap = (inDiff != null && outDiff != null) ? (outDiff - inDiff) : null;
    function diffSe(st) { if (!st || !st.n) return null; var p = st.hr_pct/100; return Math.sqrt(p*(1-p)/st.n) * 100; }
    var seIn = diffSe(inStats), seOut = diffSe(outStats);
    var gapSe = (seIn != null && seOut != null) ? Math.sqrt(seIn*seIn + seOut*seOut) : null;
    var gapLo = (diffGap != null && gapSe != null) ? (diffGap - 1.96*gapSe) : null;
    var gapHi = (diffGap != null && gapSe != null) ? (diffGap + 1.96*gapSe) : null;
    var verdict = "中立";
    if (gapLo != null && gapLo > 0) verdict = "外有利";
    else if (gapHi != null && gapHi < 0) verdict = "内有利";
    rows.push({ label: v, n_total: b.total.n, frames: frs, in_diff: inDiff, out_diff: outDiff, diff_gap: diffGap, verdict: verdict });
  });
  rows.sort(function(a,b){ return b.n_total - a.n_total; });
  return rows;
}
function renderFrameDecompositionTable(title, rows) {
  if (!rows || !rows.length) return "";
  var h = "<h4 class=\"feature-title\">" + title + "</h4>";
  h += "<div class=\"decomp-scroll\"><table class=\"ev-table-decomp\"><thead><tr>";
  h += "<th>条件</th><th>n</th>";
  for (var f = 1; f <= 8; f++) h += "<th>" + f + "</th>";
  h += "<th>内diff</th><th>外diff</th><th>内外差</th><th>判定</th>";
  h += "</tr></thead><tbody>";
  rows.forEach(function(r){
    h += "<tr><td>" + esc(r.label) + "</td><td>" + r.n_total + "</td>";
    r.frames.forEach(function(cell){
      if (cell.hr_pct == null) { h += "<td>-</td>"; return; }
      var d = cell.hr_pct - cell.market_hr_pct;
      var dCls = d > 0.5 ? "ev-mid" : (d < -0.5 ? "ev-neg" : "");
      var roi = (cell.roi_pct != null) ? cell.roi_pct : 0;
      var rCls = roi > 0 ? "ev-mid" : (roi < -20 ? "ev-neg" : "");
      h += "<td class=\"" + dCls + "\">" + (d>=0?"+":"") + d.toFixed(1) + "<br><span class=\"" + rCls + "\">" + (roi>=0?"+":"") + roi.toFixed(1) + "</span></td>";
    });
    function fD(x){ return (x == null) ? "-" : ((x>=0?"+":"") + x.toFixed(2)); }
    h += "<td>" + fD(r.in_diff) + "</td><td>" + fD(r.out_diff) + "</td><td>" + fD(r.diff_gap) + "</td>";
    var vCls = r.verdict === "外有利" ? "ev-mid" : (r.verdict === "内有利" ? "ev-neg" : "");
    h += "<td class=\"" + vCls + "\">" + r.verdict + "</td></tr>";
  });
  h += "</tbody></table></div>";
  return h;
}
function renderFrameTabConditionFilter() {
    if (!analyticsFrameData) {
      fetchWithTimeout(API_BASE + "/analytics/frame_by_condition", 60000)
        .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
        .then(function(d){ analyticsFrameData = d; renderView(); })
        .catch(function(err){});
      return "<p>条件データ読み込み中...</p>";
    }
    var cells = analyticsFrameData.cells || [];
    var venues = {}, surfaces = {}, dists = {}, babas = {};
    cells.forEach(function(c){
      venues[c.venue] = 1;
      surfaces[c.surface] = 1;
      dists[c.distance_band] = 1;
      babas[c.track_condition] = 1;
    });
    function opts(obj, current){
      var keys = Object.keys(obj).sort();
      var html = "<option value=\"\">すべて</option>";
      keys.forEach(function(k){
        var sel = (current === k) ? " selected" : "";
        html += "<option value=\"" + esc(k) + "\"" + sel + ">" + esc(k) + "</option>";
      });
      return html;
    }
    var html = "<div class=\"frame-filters\">";
    html += "<label>会場<select data-frame-tab-filter=\"venue\">" + opts(venues, frameTabFilter.venue) + "</select></label>";
    html += "<label>芝/ダート<select data-frame-tab-filter=\"surface\">" + opts(surfaces, frameTabFilter.surface) + "</select></label>";
    html += "<label>距離帯<select data-frame-tab-filter=\"distance_band\">" + opts(dists, frameTabFilter.distance_band) + "</select></label>";
    html += "<label>馬場<select data-frame-tab-filter=\"track_condition\">" + opts(babas, frameTabFilter.track_condition) + "</select></label>";
    html += "</div>";
    return html;
  }

  function bindFrameTabConditionFilter() {
    var sels = anaView.querySelectorAll("[data-frame-tab-filter]");
    for (var i = 0; i < sels.length; i++) {
      (function(sel){
        sel.addEventListener("change", function(){
          var key = sel.getAttribute("data-frame-tab-filter");
          frameTabFilter[key] = sel.value || "";
          renderView();
        });
      })(sels[i]);
    }
  }

  function frameTabHasCondition() {
    return frameTabFilter.venue || frameTabFilter.surface
        || frameTabFilter.distance_band || frameTabFilter.track_condition;
  }

  function renderFeatureGroup(features, currentKey){
    if (!features || !features.length) return "<p>該当データなし</p>";
    var tabsHtml = "<div class=\"subtabs\">";
    features.forEach(function(f, i){
      var active = (currentKey === f.feature || (!currentKey && i === 0)) ? " active" : "";
      tabsHtml += "<button class=\"subtab" + active + "\" data-feature-group=\"" + esc(f.feature) + "\" type=\"button\">" + esc(f.label) + "</button>";
    });
    tabsHtml += "</div>";
    var target = null;
    features.forEach(function(f){ if (f.feature === currentKey) target = f; });
    if (!target) target = features[0];
    var bodyHtml = "";
    // 順位相関と最大ROIビン
    if (target.order_corr && target.order_corr.rho != null) {
      var rho = target.order_corr.rho;
      var pv = target.order_corr.p_value;
      var sig = (pv < 0.05) ? "有意" : "有意でない";
      var rhoStr = (rho >= 0 ? "+" : "") + rho.toFixed(3);
      var pvStr = pv < 0.001 ? "<0.001" : pv.toFixed(3);
      bodyHtml += "<div class=\"order-corr\">";
      bodyHtml += "順位相関: " + rhoStr + "（p=" + pvStr + ", " + sig + "）";
      bodyHtml += "</div>";
    }
    if (target.max_roi_label != null) {
      bodyHtml += "<div class=\"order-corr\">";
      bodyHtml += "最大ROIビン: " + esc(target.max_roi_label)
                + " (" + fmtSignedPct(target.max_roi_pct, 1) + ")";
      bodyHtml += "</div>";
    }
    // 枠番タブの場合、条件フィルタを表示
    var isFrameTab = (target.feature === "frame");
    var displayRows = target.rows;
    if (isFrameTab) {
      bodyHtml += renderFrameTabConditionFilter();
      if (frameTabHasCondition()) {
        var agg = aggregateFrameConditionRows();
        if (agg) {
          displayRows = agg.rows;
          bodyHtml += "<div class=\"frame-count\">該当セル: " + agg.matched_count + " 件</div>";
        } else {
          bodyHtml += "<p>該当セルなし</p>";
          return tabsHtml + "<div>" + bodyHtml + "</div>";
        }
      }
    }
      if (isFrameTab) {
    var dims = [
      { key: "venue", label: "会場別（枠番 実−市場 / ROI）", min: 1000 },
      { key: "surface", label: "芝/ダート別（枠番 実−市場 / ROI）", min: 500 },
      { key: "distance_band", label: "距離帯別（枠番 実−市場 / ROI）", min: 500 },
      { key: "track_condition", label: "馬場別（枠番 実−市場 / ROI）", min: 500 }
    ];
    dims.forEach(function(d){
      if (frameTabFilter[d.key]) return;
      var drows = aggByDimension(d.key, d.min);
      bodyHtml += renderFrameDecompositionTable(d.label, drows);
    });
  }
bodyHtml += "<h4 class=\"feature-title\">利益率</h4>";
    bodyHtml += renderFeatureTable(displayRows, "roi", currentFeatureFilter);
    bodyHtml += "<h4 class=\"feature-title\">的中率</h4>";
    bodyHtml += renderFeatureTable(displayRows, "hr", currentFeatureFilter);
    // 斤量タブのときだけ、斤量×減量騎手の交差表を追加
    if (target.feature === "weight" && analyticsFeaturesData && analyticsFeaturesData.weight_x_handicap) {
      bodyHtml += "<h4 class=\"feature-title\">斤量 × 減量騎手</h4>";
      bodyHtml += renderWeightHandicapTable(analyticsFeaturesData.weight_x_handicap);
    }
    return tabsHtml + "<div>" + bodyHtml + "</div>";
  }

  function bindFeatureFilterTabs(){
    var tabs = anaView.querySelectorAll("[data-feature-filter]");
    for (var i = 0; i < tabs.length; i++) {
      (function(t){
        t.addEventListener("click", function(){
          currentFeatureFilter = t.getAttribute("data-feature-filter");
          renderView();
        });
      })(tabs[i]);
    }
  }

  function bindFeatureGroupTabs(features, setterFn){
    var tabs = anaView.querySelectorAll("[data-feature-group]");
    for (var i = 0; i < tabs.length; i++) {
      (function(t){
        t.addEventListener("click", function(){
          setterFn(t.getAttribute("data-feature-group"));
          renderView();
        });
      })(tabs[i]);
    }
  }

  function ensureFeaturesData(cb){
    if (analyticsFeaturesData) { cb(); return; }
    anaView.textContent = "読み込み中...";
    fetchWithTimeout(API_BASE + "/analytics/features", 60000)
      .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function(d){ analyticsFeaturesData = d; cb(); })
      .catch(function(err){ anaView.textContent = "取得失敗: " + err.message; });
  }

  function renderSingleFeatures(){
    ensureFeaturesData(function(){
      var features = analyticsFeaturesData.single || [];
      var html = renderFeatureFilterTabs();
      html += renderFeatureGroup(features, currentSingleFeature);
      anaView.innerHTML = html;
      bindFeatureFilterTabs();
      bindFeatureGroupTabs(features, function(k){ currentSingleFeature = k; });
      bindFrameTabConditionFilter();
    });
  }

  function renderRaceTable(){
    ensureFeaturesData(function(){
      var features = analyticsFeaturesData.race_table || [];
      var html = renderFeatureFilterTabs();
      html += renderFeatureGroup(features, currentRaceTableFeature);
      anaView.innerHTML = html;
      bindFeatureFilterTabs();
      bindFeatureGroupTabs(features, function(k){ currentRaceTableFeature = k; });
      bindFrameTabConditionFilter();
    });
  }

  var MULTI_TICKET_LABELS = {
    quinella: "馬連", wide: "ワイド", exacta: "馬単",
    trio: "3連複", trifecta: "3連単",
  };
  var MULTI_FEATURE_LABELS = {
    distance: "距離", n_runners: "頭数", surface: "馬場", venue: "会場",
    win1_age: "1頭目 年齢", win2_age: "2頭目 年齢", win3_age: "3頭目 年齢",
    win1_sex: "1頭目 性別", win2_sex: "2頭目 性別", win3_sex: "3頭目 性別",
    win1_weight: "1頭目 斤量", win2_weight: "2頭目 斤量", win3_weight: "3頭目 斤量",
    win1_hw: "1頭目 馬体重", win2_hw: "2頭目 馬体重", win3_hw: "3頭目 馬体重",
    win1_hw_chg: "1頭目 体重増減", win2_hw_chg: "2頭目 体重増減", win3_hw_chg: "3頭目 体重増減",
    win1_pop: "1頭目 人気", win2_pop: "2頭目 人気", win3_pop: "3頭目 人気",
    win1_win_odds: "1頭目 単勝", win2_win_odds: "2頭目 単勝", win3_win_odds: "3頭目 単勝",
    win1_frame: "1頭目 枠", win2_frame: "2頭目 枠", win3_frame: "3頭目 枠",
    win1_jockey: "1頭目 騎手", win2_jockey: "2頭目 騎手", win3_jockey: "3頭目 騎手",
  };


  function renderMultiTableBvsC(rows){
    if (!rows || !rows.length) return "<p>該当データなし</p>";
    var html = "<table class=\"ev-table ev-table-13col\"><thead><tr>";
    html += "<th>ビン</th><th>件数</th>";
    html += "<th>ROI(B)</th><th>CI下限</th><th>CI上限</th>";
    html += "<th>ROI(B^c)</th><th>CI下限</th><th>CI上限</th>";
    html += "<th>差</th>";
    html += "<th>実的中率</th><th>CI下限</th><th>CI上限</th>";
    html += "<th>的中率差</th>";
    html += "</tr></thead><tbody>";
    rows.forEach(function(r){
      var roi_diff_pct = r.roi_diff * 100;
      var hr_diff_pct = r.hr_diff * 100;
      var cls = KeibaTheme.evClass(roi_diff_pct / 100, 0);
      var hcls = KeibaTheme.evClass(hr_diff_pct / 100, 0);
      var roi_b_lo = r.roi_b_ci_lo == null ? "-" : fmtSignedPct(r.roi_b_ci_lo, 1);
      var roi_b_hi = r.roi_b_ci_hi == null ? "-" : fmtSignedPct(r.roi_b_ci_hi, 1);
      var roi_c_lo = r.roi_c_ci_lo == null ? "-" : fmtSignedPct(r.roi_c_ci_lo, 1);
      var roi_c_hi = r.roi_c_ci_hi == null ? "-" : fmtSignedPct(r.roi_c_ci_hi, 1);
      var hr_b_lo = r.hr_b_ci_lo == null ? "-" : fmtPct(r.hr_b_ci_lo, 2);
      var hr_b_hi = r.hr_b_ci_hi == null ? "-" : fmtPct(r.hr_b_ci_hi, 2);
      html += "<tr>";
      html += "<td>" + esc(r.label) + "</td>";
      html += "<td>" + r.n + "</td>";
      html += "<td>" + fmtSignedPct(r.roi * 100, 1) + "</td>";
      html += "<td>" + roi_b_lo + "</td>";
      html += "<td>" + roi_b_hi + "</td>";
      html += "<td>" + fmtSignedPct(r.roi_other * 100, 1) + "</td>";
      html += "<td>" + roi_c_lo + "</td>";
      html += "<td>" + roi_c_hi + "</td>";
      html += "<td class=\"" + cls + "\">" + fmtSignedPct(roi_diff_pct, 2) + "</td>";
      html += "<td>" + fmtPct(r.real_hr * 100, 2) + "</td>";
      html += "<td>" + hr_b_lo + "</td>";
      html += "<td>" + hr_b_hi + "</td>";
      html += "<td class=\"" + hcls + "\">" + fmtSignedPct(hr_diff_pct, 2) + "</td>";
      html += "</tr>";
    });
    html += "</tbody></table>";
    return html;
  }

  function renderMultiTableVsMarket(rows){
    if (!rows || !rows.length) return "<p>該当データなし</p>";
    var html = "<table class=\"ev-table ev-table-12col\"><thead><tr>";
    html += "<th>ビン</th><th>件数</th>";
    html += "<th>実的中率</th><th>CI下限</th><th>CI上限</th>";
    html += "<th>市場的中率</th><th>差</th>";
    html += "<th>実利益%</th><th>CI下限</th><th>CI上限</th>";
    html += "<th>市場利益%</th><th>差</th>";
    html += "</tr></thead><tbody>";
    rows.forEach(function(r){
      var hr_diff_pct = r.hr_vm_mean * 100;
      var roi_diff_pct = r.roi_vm_mean * 100;
      // 実利益%: roi = 実ROI(利益率). 市場利益%: -rho
      var real_profit_pct = r.roi * 100;
      var market_profit_pct = real_profit_pct - roi_diff_pct;
      var cls_hr = KeibaTheme.evClass(hr_diff_pct / 100, 0);
      var cls_roi = KeibaTheme.evClass(roi_diff_pct / 100, 0);
      var hr_b_lo = r.hr_b_ci_lo == null ? "-" : fmtPct(r.hr_b_ci_lo, 2);
      var hr_b_hi = r.hr_b_ci_hi == null ? "-" : fmtPct(r.hr_b_ci_hi, 2);
      var roi_b_lo = r.roi_b_ci_lo == null ? "-" : fmtSignedPct(r.roi_b_ci_lo, 1);
      var roi_b_hi = r.roi_b_ci_hi == null ? "-" : fmtSignedPct(r.roi_b_ci_hi, 1);
      html += "<tr>";
      html += "<td>" + esc(r.label) + "</td>";
      html += "<td>" + r.n + "</td>";
      html += "<td>" + fmtPct(r.real_hr * 100, 2) + "</td>";
      html += "<td>" + hr_b_lo + "</td>";
      html += "<td>" + hr_b_hi + "</td>";
      html += "<td>" + fmtPct(r.market_hr * 100, 2) + "</td>";
      html += "<td class=\"" + cls_hr + "\">" + fmtSignedPct(hr_diff_pct, 3) + "</td>";
      html += "<td>" + fmtSignedPct(real_profit_pct, 1) + "</td>";
      html += "<td>" + roi_b_lo + "</td>";
      html += "<td>" + roi_b_hi + "</td>";
      html += "<td>" + fmtSignedPct(market_profit_pct, 1) + "</td>";
      html += "<td class=\"" + cls_roi + "\">" + fmtSignedPct(roi_diff_pct, 2) + "</td>";
      html += "</tr>";
    });
    html += "</tbody></table>";
    return html;
  }

  function renderMultiFeatureGroup(featureData, currentFeature){
    if (!featureData || !featureData.length) return "<p>該当データなし</p>";
    // featureData: [{label, rows}, ...] を想定 → 実際は dict 形式
    return "";
  }

  function buildMultiTicketTabsHtml(tickets){
    var ticketKeys = ["quinella", "wide", "exacta", "trio", "trifecta"];
    var html = "<div class=\"subtabs\">";
    ticketKeys.forEach(function(tk){
      var label = MULTI_TICKET_LABELS[tk] || tk;
      var exists = !!tickets[tk];
      var active = (currentMultiTicket === tk) ? " active" : "";
      var suffix = exists ? "" : " (準備中)";
      var disabled = exists ? "" : " disabled";
      html += "<button class=\"subtab" + active + disabled + "\" data-multi-ticket=\"" + tk + "\" type=\"button\">" + label + suffix + "</button>";
    });
    html += "</div>";
    return html;
  }

  function buildMultiTicketBodyHtml(ticketData){
    var results = ticketData.results || {};
    var featureKeys = Object.keys(results);
    if (!featureKeys.length) {
      return "<p>データなし</p>";
    }
    var html = "<div class=\"subtabs\">";
    featureKeys.forEach(function(fk, i){
      var label = MULTI_FEATURE_LABELS[fk] || fk;
      var active = (currentMultiFeature === fk || (!currentMultiFeature && i === 0)) ? " active" : "";
      html += "<button class=\"subtab" + active + "\" data-multi-feature=\"" + esc(fk) + "\" type=\"button\">" + esc(label) + "</button>";
    });
    html += "</div>";
    var target = currentMultiFeature || featureKeys[0];
    var rows = results[target] || [];
    html += "<h4 class=\"feature-title\">実 vs 市場</h4>";
    html += renderMultiTableVsMarket(rows);
    html += "<h4 class=\"feature-title\">B vs B^c</h4>";
    html += renderMultiTableBvsC(rows);
    return html;
  }

  function renderMultiView(){
    if (!analyticsMultiData) {
      anaView.textContent = "読み込み中...";
      fetchWithTimeout(API_BASE + "/analytics/multi", 120000)
        .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
        .then(function(d){ analyticsMultiData = d; renderMultiView(); })
        .catch(function(err){ anaView.textContent = "取得失敗: " + err.message; });
      return;
    }
    var tickets = analyticsMultiData.tickets || {};
    var html = buildMultiTicketTabsHtml(tickets);
    var bodyReady = currentMultiTicket && tickets[currentMultiTicket];
    if (bodyReady) {
      html += buildMultiTicketBodyHtml(tickets[currentMultiTicket]);
    }
    anaView.innerHTML = html;
    bindMultiTicketTabs();
    if (bodyReady) {
      bindMultiFeatureTabs();
    }
  }

  function bindMultiTicketTabs(){
    var tabs = anaView.querySelectorAll("[data-multi-ticket]");
    for (var i = 0; i < tabs.length; i++) {
      (function(t){
        if (t.disabled) return;
        t.addEventListener("click", function(){
          currentMultiTicket = t.getAttribute("data-multi-ticket");
          currentMultiFeature = null;
          renderMultiView();
        });
      })(tabs[i]);
    }
  }

  function bindMultiFeatureTabs(){
    var tabs = anaView.querySelectorAll("[data-multi-feature]");
    for (var i = 0; i < tabs.length; i++) {
      (function(t){
        t.addEventListener("click", function(){
          currentMultiFeature = t.getAttribute("data-multi-feature");
          renderMultiView();
        });
      })(tabs[i]);
    }
  }

  function renderView(){
    if (currentView === "features") {
      renderRaceTable();
      return;
    }
    if (currentView === "single_features") {
      renderSingleFeatures();
      return;
    }
    if (currentView === "multi") {
      renderMultiView();
      return;
    }
    if (currentView === "feature_single") {
      renderFeatureSingleView();
      return;
    }
    if (currentView === "feature_interactions") {
      renderFeatureInteractionsView();
      return;
    }
    if (!analyticsData) return;
    var scopeData = (analyticsData.scopes || {})[currentAnaScope] || {};
    var races = (analyticsData.meta || {}).races || 0;
    var allCombos = (analyticsData.scopes || {}).all_combos || {};
    window._anaTotalCount = ((allCombos.summary || {}).total_count) || 0;
    renderAnaSummary(scopeData.summary, races);
    if (currentView === "prob") {
      anaView.innerHTML = tableRows(scopeData.prob_bins || [], "確率帯") + renderCumTable(scopeData.prob_cum || [], "確率帯");
      return;
    }
    if (currentView === "odds") {
      anaView.innerHTML = tableRows(scopeData.odds_bins || [], "オッズ帯") + renderCumTable(scopeData.odds_cum || [], "オッズ帯");
      return;
    }
    if (currentView === "tickets") {
      renderTicketStatsFromData();
      return;
    }
    anaView.innerHTML = tableRows(scopeData.ev_bins || [], "期待値帯") + renderCumTable(scopeData.ev_cum || [], "期待値帯");
  }

  function loadModelOptions(){
    if (!anaModelFilter) return;
    fetchWithTimeout(API_BASE + "/models", TIMEOUT_MS).then(function(res){ return res.json(); }).then(function(d){
      var cur = anaModelFilter.value;
      var html = "<option value=\"\">すべて</option>";
      (d.models || []).forEach(function(m){
        html += "<option value=\"" + esc(m.model_version) + "\">" + esc(m.model_version) + " (" + m.count + ")</option>";
      });
      anaModelFilter.innerHTML = html;
      if (cur) anaModelFilter.value = cur;
    }).catch(function(){});
  }

  function loadAnalytics(){
    anaSummary.textContent = "読み込み中..."; anaView.textContent = "読み込み中...";
    loadModelOptions();
    var q = currentModelFilter ? "?model_version=" + encodeURIComponent(currentModelFilter) : "";
    fetchWithTimeout(API_BASE + "/analytics" + q, 120000)
      .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function(data){ analyticsData = data; renderView(); })
      .catch(function(err){ anaSummary.textContent = "取得失敗: " + err.message; anaView.textContent = ""; });
  }

  function drawCurve(data){
    if (!curveCanvas || !data) return;
    var ctx = curveCanvas.getContext("2d");
    var W = curveCanvas.width, H = curveCanvas.height, pad = 40;
    ctx.clearRect(0, 0, W, H);
    var act = data.actual || [], exp = data.expected || [];
    var all = act.concat(exp);
    if (!all.length) { ctx.fillStyle = "#E8E8E8"; ctx.font = "14px sans-serif"; ctx.fillText("データなし", 20, 30); return; }
    var maxX = Math.max.apply(null, all.map(function(p){ return p.x; })) || 1;
    var maxY = Math.max.apply(null, all.map(function(p){ return p.y; })) || 1;
    var minY = Math.min.apply(null, all.map(function(p){ return p.y; }));
    if (minY > 0) minY = 0;
    if (maxY < 0) maxY = 0;
    var rangeY = (maxY - minY) || 1;
    var sx = function(x){ return pad + (x / maxX) * (W - pad * 2); };
    var sy = function(y){ return H - pad - ((y - minY) / rangeY) * (H - pad * 2); };
    ctx.strokeStyle = "rgba(212,175,55,0.3)"; ctx.lineWidth = 1;
    ctx.beginPath(); ctx.moveTo(pad, sy(0)); ctx.lineTo(W - pad, sy(0)); ctx.stroke();
    ctx.fillStyle = "#E8E8E8"; ctx.font = "11px sans-serif";
    ctx.fillText("投資 " + fmtInt(maxX) + "円", W - 130, H - 10);
    ctx.fillText("損益 " + fmtInt(maxY) + "円", 4, sy(maxY) + 12);
    function line(points, color){ if (!points.length) return; ctx.strokeStyle = color; ctx.lineWidth = 2.5; ctx.beginPath(); points.forEach(function(p, i){ var x = sx(p.x), y = sy(p.y); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); }); ctx.stroke(); var last = points[points.length - 1]; ctx.fillStyle = color; ctx.beginPath(); ctx.arc(sx(last.x), sy(last.y), 4, 0, Math.PI * 2); ctx.fill(); }
    line(exp, "#D4AF37"); line(act, "#ff4d4d");
    var expLast = exp.length ? exp[exp.length - 1] : { x: 0, y: 0 };
    var actLast = act.length ? act[act.length - 1] : { x: 0, y: 0 };
    ctx.font = "11px sans-serif";
    ctx.fillStyle = "#D4AF37"; ctx.fillText("想定 " + (expLast.y >= 0 ? "+" : "") + fmtInt(expLast.y) + "円", 4, H - 24);
    ctx.fillStyle = "#ff4d4d"; ctx.fillText("実績 " + (actLast.y >= 0 ? "+" : "") + fmtInt(actLast.y) + "円", 4, H - 8);
  }

  function renderBetsSummary(s){
    if (!s) { betsSummary.textContent = "データなし"; return; }
    var cls = s.total_profit >= 0 ? "ev-mid" : "ev-neg";
    var bankroll = 50000 + (s.total_profit || 0);
    var betUnit = Math.max(100, Math.floor(bankroll * 0.005 / 100) * 100);
    betsSummary.innerHTML = "<div>現在の資金: " + fmtYen(bankroll) + " (賭け金: " + fmtYen(betUnit) + ")</div>"
      + "<div>投票数: " + s.total_bets + "</div>"
      + "<div>投資: " + fmtYen(s.total_stake) + " / 払戻: " + fmtYen(s.total_return) + "</div>"
      + "<div class=\"" + cls + "\">損益: " + (s.total_profit >= 0 ? "+" : "") + fmtYen(s.total_profit) + " (想定: " + fmtSigned(s.expected_profit, 0) + "円)</div>"
      + "<div>実的中率: " + fmtPct(s.hit_rate, 1) + " (" + s.hits + "/" + s.total_bets + ") / 想定的中率: " + fmtPct(s.expected_hit_rate, 1) + "</div>"
      + "<div>実ROI: " + fmtPct(s.roi, 1) + " / 想定ROI: " + fmtPct(s.expected_roi, 1) + "</div>"
      + "<div>平均オッズ: " + fmtNum(s.avg_odds, 1) + " / 加重平均: " + fmtNum(s.weighted_avg_odds, 1) + "</div>";
  }

  function settleCell(r){
    if (r.status !== "pending") {
      var p = r.payout;
      return p == null ? "-" : fmtYen(p);
    }
    return "<input type=\"number\" class=\"payout-input\" step=\"10\" min=\"0\" placeholder=\"0\" data-id=\"" + r.id + "\"><button class=\"settle-btn\" data-id=\"" + r.id + "\" type=\"button\">確定</button>";
  }

  function renderBetsList(rows){
    if (!rows || !rows.length) { betsList.textContent = "投票履歴はありません"; return; }
    var html = "<table class=\"ev-table\"><thead><tr><th>レース</th><th>券種</th><th>買い目</th><th>金額</th><th>オッズ</th><th>状態</th><th>損益</th><th>払戻</th><th></th></tr></thead><tbody>";
    rows.forEach(function(r){
      var cls = r.profit > 0 ? "ev-mid" : r.profit < 0 ? "ev-neg" : "";
      var statusLabel = r.status === "hit" ? "的中" : r.status === "miss" ? "不的中" : r.status === "pending" ? "確定待ち" : r.status;
      html += "<tr class=\"" + cls + "\"><td>" + raceLabel(r.race_id) + "</td><td>" + esc(ticketLabel(r.ticket_type || "")) + "</td><td>" + esc(r.combo) + "</td><td>" + fmtYen(r.amount) + "</td><td>" + fmtNum(r.odds, 1) + "</td><td>" + statusLabel + "</td><td>" + (r.profit >= 0 ? "+" : "") + fmtYen(r.profit) + "</td><td>" + settleCell(r) + "</td><td><button class=\"del-btn\" data-id=\"" + r.id + "\" type=\"button\">削除</button></td></tr>";
    });
    html += "</tbody></table>";
    betsList.innerHTML = html;
    betsList.querySelectorAll(".del-btn").forEach(function(btn){
      btn.addEventListener("click", function(){ var id = btn.getAttribute("data-id"); fetchWithTimeout(API_BASE + "/bets/" + id, TIMEOUT_MS, { method: "DELETE" }).then(function(){ loadBets(); }).catch(function(){ alert("削除失敗"); }); });
    });
    betsList.querySelectorAll(".settle-btn").forEach(function(btn){
      btn.addEventListener("click", function(){
        var id = btn.getAttribute("data-id");
        var inp = betsList.querySelector(".payout-input[data-id=\"" + id + "\"]");
        var v = Math.max(0, Math.round(Number(inp && inp.value || 0)));
        fetchWithTimeout(API_BASE + "/bets/" + id + "/settle", TIMEOUT_MS, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ payout: v }) }).then(function(){ loadBets(); }).catch(function(){ alert("確定失敗"); });
      });
    });
  }

  function exportBets(){
    fetchWithTimeout(API_BASE + "/bets/export", TIMEOUT_MS)
      .then(function(res){
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function(data){
        var blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url;
        a.download = "keiba-bets-" + new Date().toISOString().slice(0, 10) + ".json";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
      })
      .catch(function(err){ alert("バックアップ失敗: " + err.message); });
  }

  function importBets(file){
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function(e){
      try {
        var payload = JSON.parse(e.target.result);
        if (!Array.isArray(payload)) throw new Error("JSONは配列である必要があります");
        fetchWithTimeout(API_BASE + "/bets/import", TIMEOUT_MS, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        }).then(function(res){
          if (!res.ok) throw new Error("HTTP " + res.status);
          return res.json();
        }).then(function(r){
          alert("復元完了: " + (r.imported || 0) + "件");
          loadBets();
        }).catch(function(err){ alert("復元失敗: " + err.message); });
      } catch (err) {
        alert("読み込み失敗: " + err.message);
      }
    };
    reader.readAsText(file);
  }

  function settleAllZero(){
    fetchWithTimeout(API_BASE + "/bets", TIMEOUT_MS).then(function(res){ return res.json(); }).then(function(rows){
      var pending = (rows || []).filter(function(r){ return r.status === "pending"; });
      if (!pending.length) { alert("未確定はありません"); return; }
      var chain = Promise.resolve();
      var ok = 0, fail = 0;
      pending.forEach(function(r){
        chain = chain.then(function(){
          return fetchWithTimeout(API_BASE + "/bets/" + r.id + "/settle", TIMEOUT_MS, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ payout: 0 }) })
            .then(function(){ ok++; }).catch(function(){ fail++; });
        });
      });
      chain.then(function(){ alert("一括0円確定: 成功 " + ok + " / 失敗 " + fail); loadBets(); });
    }).catch(function(err){ alert("取得失敗: " + err.message); });
  }

  function loadStorageBadge(){
    if (!storageBadge) return;
    fetchWithTimeout(API_BASE + "/storage", TIMEOUT_MS)
      .then(function(res){ return res.json(); })
      .then(function(d){
        var label = d.backend || "unknown";
        var color = label === "postgres" ? "storage-pg" : label === "turso" ? "storage-turso" : "storage-file";
        storageBadge.className = "storage-badge " + color;
        storageBadge.textContent = "DB: " + label;
      })
      .catch(function(){ storageBadge.textContent = "DB: ?"; });
  }

  function loadBets(){
    loadStorageBadge();
    betsSummary.textContent = "読み込み中..."; betsList.textContent = "読み込み中...";
    fetchWithTimeout(API_BASE + "/bets/summary", TIMEOUT_MS).then(function(res){ return res.json(); }).then(renderBetsSummary).catch(function(err){ betsSummary.textContent = "取得失敗: " + err.message; });
    fetchWithTimeout(API_BASE + "/bets/curve", TIMEOUT_MS).then(function(res){ return res.json(); }).then(drawCurve).catch(function(){ drawCurve(null); });
    fetchWithTimeout(API_BASE + "/bets", TIMEOUT_MS).then(function(res){ return res.json(); }).then(renderBetsList).catch(function(err){ betsList.textContent = "取得失敗: " + err.message; });
  }

  function switchTab(name){
    currentTabName = name;
    try { localStorage.setItem("keiba-current-tab", name); } catch (e) {}
    document.querySelectorAll(".tab").forEach(function(t){ t.classList.toggle("active", t.getAttribute("data-tab") === name); });
    tabPredict.hidden = name !== "predict";
    tabAnalytics.hidden = name !== "analytics";
    tabBets.hidden = name !== "bets";
    if (tabHorse) tabHorse.hidden = name !== "horse";
    window.scrollTo(0, 0);
    if (name === "analytics") loadAnalytics();
    if (name === "bets") loadBets();
  }

  document.querySelectorAll(".tab").forEach(function(t){ t.addEventListener("click", function(){ switchTab(t.getAttribute("data-tab")); }); });
  var anaScopeTabs = document.getElementById("ana-scope-tabs");
  if (anaScopeTabs) {
    anaScopeTabs.querySelectorAll(".subtab").forEach(function(t){
      t.addEventListener("click", function(){
        anaScopeTabs.querySelectorAll(".subtab").forEach(function(x){ x.classList.remove("active"); });
        t.classList.add("active");
        currentAnaScope = t.getAttribute("data-ana-scope") || "all";
        renderView();
      });
    });
  }

  anaViewTabs.querySelectorAll(".subtab").forEach(function(t){
    t.addEventListener("click", function(){
      anaViewTabs.querySelectorAll(".subtab").forEach(function(x){ x.classList.remove("active"); });
      t.classList.add("active"); currentView = t.getAttribute("data-view"); renderView();
    });
  });
  [fMinProb, fMinOdds, fCollateral, fMaxInv, fBetUnit, fBetMode].forEach(function(el){
    el.addEventListener("change", function(){
      saveFiltersToStorage();
      readFilters();
      if (detail && !detail.hidden && detail.dataset.raceId) loadEvTable(detail.dataset.raceId);
    });
  });

  var settingsBtn = $("settings-btn");
  var settingsModal = $("settings-modal");
  var settingsClose = $("settings-close");
  if (settingsBtn) settingsBtn.addEventListener("click", function(){ settingsModal.hidden = false; });
  if (settingsClose) settingsClose.addEventListener("click", function(){ settingsModal.hidden = true; });
  if (settingsModal) settingsModal.addEventListener("click", function(e){ if (e.target === settingsModal) settingsModal.hidden = true; });

  loadFiltersFromStorage();
  anaModelFilter = document.getElementById("ana-model-filter");
  if (anaModelFilter) anaModelFilter.addEventListener("change", function(){ currentModelFilter = anaModelFilter.value || ""; ticketStats = null; renderView(); });
  var ticketTabs = document.getElementById("ticket-tabs");
  if (ticketTabs) ticketTabs.querySelectorAll(".subtab").forEach(function(t){
    t.addEventListener("click", function(){
      ticketTabs.querySelectorAll(".subtab").forEach(function(x){ x.classList.remove("active"); });
      t.classList.add("active");
      currentTicket = t.getAttribute("data-ticket");
      var lbl = document.getElementById("ev-title-label");
      if (lbl) lbl.textContent = "EV上位の買い目 (" + ticketLabel(currentTicket) + ")";
      if (detail && !detail.hidden && detail.dataset.raceId) loadEvTable(detail.dataset.raceId);
    });
  });
  list.addEventListener("click", function(e){ var el = e.target.closest(".race"); if (!el) return; detail.dataset.raceId = el.getAttribute("data-race-id"); loadDetail(el.getAttribute("data-race-id")); });
  list.addEventListener("keydown", function(e){ if (e.key !== "Enter" && e.key !== " ") return; var el = e.target.closest(".race"); if (!el) return; e.preventDefault(); detail.dataset.raceId = el.getAttribute("data-race-id"); loadDetail(el.getAttribute("data-race-id")); });
  backBtn.addEventListener("click", showList);
  var sAllZero = document.getElementById("settle-all-zero");
  if (sAllZero) sAllZero.addEventListener("click", settleAllZero);
  var expBtn = document.getElementById("export-bets");
  if (expBtn) expBtn.addEventListener("click", exportBets);
  var impInput = document.getElementById("import-bets");
  if (impInput) impInput.addEventListener("change", function(e){ importBets(e.target.files && e.target.files[0]); e.target.value = ""; });

  readFilters();

  // タブ復元
  try {
    var savedTab = localStorage.getItem("keiba-current-tab") || "predict";
    if (savedTab !== "predict") switchTab(savedTab);
  } catch (e) {}

  list.textContent = "読み込み中... (サーバー起動待ちの場合があります)";
  (function loadTodayRaces(retryCount){
    var n = retryCount || 0;
    fetchWithTimeout(API_BASE + "/races/today", TIMEOUT_MS).then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); }).then(function(data){
      var races = Array.isArray(data) ? data : (data.races || data.items || []);
      var pref = (data && data.prefetch) || {};
      if (!races.length && pref.running && n < 30) {
        list.textContent = "出走表を取得中... (" + (n+1) + ")";
        setTimeout(function(){ loadTodayRaces(n+1); }, 10000);
        return;
      }
      if (!races.length && n >= 30) {
        list.textContent = "取得に時間がかかっています。しばらくしてから再読み込みしてください。";
        return;
      }
      renderList(races);
    }).catch(function(err){ list.textContent = "API取得失敗: " + err.message + " — 再読み込みしてください"; });
  })(0);
  var horseData = null;
  var horseViewTab = "basic";

  function histRow(hist, row){
    var o = {};
    var hh = hist.header || [];
    for (var i = 0; i < hh.length && i < row.length; i++) o[hh[i]] = row[i];
    return o;
  }
  function histCell(o, key1, key2){
    return o[key1] != null ? o[key1] : (key2 && o[key2] != null ? o[key2] : "");
  }
  function horseAggBy(hist, keyFn){
    var buckets = {};
    (hist.rows || []).forEach(function(row){
      var o = histRow(hist, row);
      var k = keyFn(o);
      if (k == null || k === "") return;
      if (!buckets[k]) buckets[k] = {n:0,w:0,p:0,s:0,u:0,fs:0};
      var b = buckets[k];
      var f = parseInt(o["着順"]) || 0;
      if (!f) return;
      b.n++; b.fs += f;
      if (f === 1) b.w++; else if (f === 2) b.p++; else if (f === 3) b.s++; else b.u++;
    });
    var rows = [];
    Object.keys(buckets).forEach(function(k){
      var b = buckets[k];
      if (!b.n) return;
      rows.push({
        label: k, n: b.n, w: b.w, p: b.p, s: b.s, u: b.u,
        win_pct: (b.w/b.n*100).toFixed(1),
        place_pct: ((b.w+b.p)/b.n*100).toFixed(1),
        show_pct: ((b.w+b.p+b.s)/b.n*100).toFixed(1),
        avg_finish: (b.fs/b.n).toFixed(1)
      });
    });
    return rows;
  }
  function renderHorseAggTable(rows, sortNumeric){
    if (!rows.length) return "<p>該当データなし</p>";
    if (sortNumeric) rows.sort(function(a,b){ return (parseFloat(a.label)||0) - (parseFloat(b.label)||0); });
    else rows.sort(function(a,b){ return b.n - a.n; });
    var h = "<table class=\"ev-table\"><thead><tr>";
    h += "<th>種別</th><th>出走</th><th>1着</th><th>2着</th><th>3着</th><th>着外</th>";
    h += "<th>勝率</th><th>連対率</th><th>3連対率</th><th>平均着順</th>";
    h += "</tr></thead><tbody>";
    rows.forEach(function(r){
      h += "<tr><td>" + esc(r.label) + "</td><td>" + r.n + "</td><td>" + r.w + "</td><td>" + r.p + "</td><td>" + r.s + "</td><td>" + r.u + "</td>";
      h += "<td>" + r.win_pct + "%</td><td>" + r.place_pct + "%</td><td>" + r.show_pct + "%</td><td>" + r.avg_finish + "</td></tr>";
    });
    h += "</tbody></table>";
    return h;
  }
  function renderHorseBasic(d){
    var h = "<h3 class=\"feature-title\">基本</h3>";
    h += "<table class=\"ev-table\"><tbody>";
    var basics = d.basic || {};
    Object.keys(basics).forEach(function(k){
      h += "<tr><td>" + esc(k) + "</td><td>" + esc(basics[k]) + "</td></tr>";
    });
    h += "</tbody></table>";
    if (d.summaries && d.summaries.length) {
      h += "<h3 class=\"feature-title\">成績サマリ</h3>";
      d.summaries.forEach(function(blk){
        h += "<table class=\"ev-table\"><thead><tr>";
        (blk.header||[]).forEach(function(x){ h += "<th>" + esc(x) + "</th>"; });
        h += "</tr></thead><tbody>";
        (blk.rows||[]).forEach(function(row){
          h += "<tr>";
          row.forEach(function(x){ h += "<td>" + esc(x) + "</td>"; });
          h += "</tr>";
        });
        h += "</tbody></table>";
      });
    }
    return h;
  }
  function renderHorseHistory(d){
    var hist = d.history;
    if (!hist || !hist.rows || !hist.rows.length) return "<p>走歴なし</p>";
    var h = "<h3 class=\"feature-title\">走歴</h3>";
    h += "<div class=\"decomp-scroll\"><table class=\"ev-table-decomp\"><thead><tr>";
    (hist.header||[]).forEach(function(x){ h += "<th>" + esc(x) + "</th>"; });
    h += "</tr></thead><tbody>";
    hist.rows.forEach(function(row){
      h += "<tr>";
      row.forEach(function(x){ h += "<td>" + esc(x) + "</td>"; });
      h += "</tr>";
    });
    h += "</tbody></table></div>";
    return h;
  }
  function renderHorseDistance(d){
    var hist = d.history;
    if (!hist) return "<p>走歴なし</p>";
    var rows = horseAggBy(hist, function(o){
      var v = o["距離"] || "";
      var m = v.match(/(\d+)/);
      return m ? m[1] : "";
    });
    return "<h3 class=\"feature-title\">距離別</h3>" + renderHorseAggTable(rows, true);
  }
  function renderHorseSurfaceCond(d){
    var hist = d.history;
    if (!hist) return "<p>走歴なし</p>";
    var rows = horseAggBy(hist, function(o){
      var v = o["馬場(天候)"] || "";
      var m = v.match(/^(良|稍重|重|不良)/);
      return m ? m[1] : v.slice(0,2);
    });
    return "<h3 class=\"feature-title\">馬場別</h3>" + renderHorseAggTable(rows, false);
  }
  function renderHorseVenue(d){
    var hist = d.history;
    if (!hist) return "<p>走歴なし</p>";
    var rows = horseAggBy(hist, function(o){ return o["競馬場"] || ""; });
    return "<h3 class=\"feature-title\">会場別</h3>" + renderHorseAggTable(rows, false);
  }
  function renderHorseStyle(d){
    var hist = d.history;
    if (!hist || !hist.rows || !hist.rows.length) return "<p>走歴なし</p>";
    var ratios = [];
    hist.rows.forEach(function(row){
      var o = histRow(hist, row);
      var corner = histCell(o, "通過順位", "通過\u200b順位");
      var n = parseInt(o["頭数"]) || 0;
      var m = (corner||"").match(/^(\d+)/);
      if (m && n) ratios.push(parseInt(m[1]) / n);
    });
    if (!ratios.length) return "<p>脚質データなし</p>";
    var avg = ratios.reduce(function(a,b){ return a+b; }, 0) / ratios.length;
    var style = avg < 0.2 ? "逃げ" : avg < 0.4 ? "先行" : avg < 0.7 ? "差し" : "追込";
    var h = "<h3 class=\"feature-title\">脚質</h3>";
    h += "<table class=\"ev-table\"><tbody>";
    h += "<tr><td>平均先行度</td><td>" + avg.toFixed(3) + "</td></tr>";
    h += "<tr><td>判定</td><td>" + style + "</td></tr>";
    h += "<tr><td>サンプル数</td><td>" + ratios.length + "</td></tr>";
    h += "</tbody></table>";
    return h;
  }
  function renderHorseRecent(d){
    var hist = d.history;
    if (!hist || !hist.rows || !hist.rows.length) return "<p>走歴なし</p>";
    var h = "<h3 class=\"feature-title\">近走（直近5走）</h3>";
    h += "<div class=\"decomp-scroll\"><table class=\"ev-table-decomp\"><thead><tr>";
    h += "<th>年月日</th><th>会場</th><th>距離</th><th>馬場</th><th>人気</th><th>着順</th><th>上3F</th><th>通過</th>";
    h += "</tr></thead><tbody>";
    hist.rows.slice(0, 5).forEach(function(row){
      var o = histRow(hist, row);
      h += "<tr>";
      h += "<td>" + esc(o["年月日"] || "") + "</td>";
      h += "<td>" + esc(o["競馬場"] || "") + "</td>";
      h += "<td>" + esc(o["距離"] || "") + "</td>";
      h += "<td>" + esc((o["馬場(天候)"] || "").slice(0,2)) + "</td>";
      h += "<td>" + esc(o["人気"] || "") + "</td>";
      h += "<td>" + esc(o["着順"] || "") + "</td>";
      h += "<td>" + esc(o["上3F"] || "") + "</td>";
      h += "<td>" + esc(histCell(o, "通過順位", "通過\u200b順位")) + "</td>";
      h += "</tr>";
    });
    h += "</tbody></table></div>";
    return h;
  }
  function renderHorsePedigree(d){
    var pg = d.pedigree || {};
    if (!pg.sire && !pg.dam) return "<p>血統データなし</p>";
    var h = "<h3 class=\"feature-title\">血統</h3>";
    h += "<table class=\"ev-table\"><tbody>";
    h += "<tr><td>父</td><td>" + esc(pg.sire || "") + "</td></tr>";
    h += "<tr><td>父父</td><td>" + esc(pg.sire_sire || "") + "</td></tr>";
    h += "<tr><td>父母</td><td>" + esc(pg.sire_dam || "") + "</td></tr>";
    h += "<tr><td>母</td><td>" + esc(pg.dam || "") + "</td></tr>";
    h += "<tr><td>母父</td><td>" + esc(pg.dam_sire || "") + "</td></tr>";
    h += "<tr><td>母母</td><td>" + esc(pg.dam_dam || "") + "</td></tr>";
    h += "</tbody></table>";
    return h;
  }
  function renderHorseTab(tab){
    var d = horseData;
    if (!d) return "<p>データなし</p>";
    if (tab === "basic") return renderHorseBasic(d);
    if (tab === "history") return renderHorseHistory(d);
    if (tab === "distance") return renderHorseDistance(d);
    if (tab === "surface_cond") return renderHorseSurfaceCond(d);
    if (tab === "venue") return renderHorseVenue(d);
    if (tab === "style") return renderHorseStyle(d);
    if (tab === "recent") return renderHorseRecent(d);
    if (tab === "pedigree") return renderHorsePedigree(d);
    return "<p>不明なタブ</p>";
  }
  function syncHorseSubtabs(){
    var tabsEl = document.getElementById("horse-view-tabs");
    if (!tabsEl) return;
    var btns = tabsEl.querySelectorAll("[data-hv]");
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle("active", btns[i].getAttribute("data-hv") === horseViewTab);
    }
  }
  function renderHorseView(d){
    if (!d) return "<p>データなし</p>";
    horseData = d;
    var tabsEl = document.getElementById("horse-view-tabs");
    if (tabsEl) tabsEl.hidden = false;
    syncHorseSubtabs();
    return renderHorseTab(horseViewTab);
  }

  function renderHorseSearchResult(items){
    if (!items || !items.length) return "<p>該当馬なし</p>";
    var h = "<h4 class=\"feature-title\">検索結果 " + items.length + "件</h4>";
    h += "<table class=\"ev-table\"><thead><tr><th>馬名</th><th>性齢</th><th>所属</th><th></th></tr></thead><tbody>";
    items.forEach(function(x){
      h += "<tr>";
      h += "<td>" + esc(x.name) + "</td>";
      h += "<td>" + esc(x.age_sex || "") + "</td>";
      h += "<td>" + esc(x.affiliation || "") + "</td>";
      h += "<td><button class=\"bet-btn\" data-horse-load=\"" + esc(x.lineage_nb) + "\" type=\"button\">詳細</button></td>";
      h += "</tr>";
    });
    h += "</tbody></table>";
    return h;
  }
  function loadHorseDetail(lineageNb){
    var view = $("horse-view");
    if (!view) return;
    view.innerHTML = "<p>読み込み中...</p>";
    fetchWithTimeout(API_BASE + "/horses/" + encodeURIComponent(lineageNb), 30000)
      .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function(d){ view.innerHTML = renderHorseView(d); })
      .catch(function(err){ view.innerHTML = "<p>取得失敗: " + esc(err.message) + "</p>"; });
  }
  function loadHorse(){
    var idEl = $("horse-id");
    var res = $("horse-search-result");
    var view = $("horse-view");
    if (!idEl || !res) return;
    var q = (idEl.value || "").trim();
    if (!q) { res.innerHTML = "<p>馬名 or 馬IDを入力してください</p>"; return; }
    if (view) view.innerHTML = "";
    res.innerHTML = "<p>検索中...</p>";
    fetchWithTimeout(API_BASE + "/horses/search?q=" + encodeURIComponent(q) + "&limit=50", 20000)
      .then(function(r){ if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function(d){
        var items = (d && d.items) || [];
        res.innerHTML = renderHorseSearchResult(items);
        var btns = res.querySelectorAll("[data-horse-load]");
        for (var i = 0; i < btns.length; i++) {
          (function(b){
            b.addEventListener("click", function(){
              loadHorseDetail(b.getAttribute("data-horse-load"));
            });
          })(btns[i]);
        }
        if (items.length === 1) loadHorseDetail(items[0].lineage_nb);
      })
      .catch(function(err){ res.innerHTML = "<p>検索失敗: " + esc(err.message) + "</p>"; });
  }
  (function(){
    var btn = $("horse-load");
    if (btn) btn.addEventListener("click", loadHorse);
    var idEl = $("horse-id");
    if (idEl) idEl.addEventListener("keydown", function(e){ if (e.key === "Enter") loadHorse(); });
  })();
  (function(){
    var tabsEl = document.getElementById("horse-view-tabs");
    if (!tabsEl) return;
    tabsEl.addEventListener("click", function(e){
      var b = e.target.closest("[data-hv]");
      if (!b) return;
      horseViewTab = b.getAttribute("data-hv");
      syncHorseSubtabs();
      var view = document.getElementById("horse-view");
      if (view && horseData) view.innerHTML = renderHorseTab(horseViewTab);
    });
  })();

  var featureSingleData = null;
  var featureInteractionsData = null;

  function loadFeatureSingleIfNeeded(cb){
    if (featureSingleData) { cb(); return; }
    fetchWithTimeout(API_BASE + "/analytics/feature_single", 120000)
      .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function(d){ featureSingleData = d; cb(); })
      .catch(function(err){ anaView.textContent = "取得失敗: " + err.message; });
  }
  function loadFeatureInteractionsIfNeeded(cb){
    if (featureInteractionsData) { cb(); return; }
    fetchWithTimeout(API_BASE + "/analytics/feature_interactions", 120000)
      .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function(d){ featureInteractionsData = d; cb(); })
      .catch(function(err){ anaView.textContent = "取得失敗: " + err.message; });
  }

  function renderFeatureSingleView(){
    anaView.textContent = "読み込み中...";
    loadFeatureSingleIfNeeded(function(){
      var d = featureSingleData || {};
      var feats = d.features || {};
      var h = "<h3 class=\"feature-title\">単一特徴の市場比較（サンプル " + (d.samples || 0) + "行）</h3>";
      h += "<p class=\"hint\">各特徴を10分位に分割し、実1着率と市場期待1着率を比較。ROI は単勝100円購入時の回収率。</p>";
      var names = Object.keys(feats);
      if (!names.length) { anaView.innerHTML = h + "<p>データなし</p>"; return; }
      h += "<div class=\"decomp-scroll\"><table class=\"ev-table-decomp\"><thead><tr>";
      h += "<th>特徴</th><th>分位</th><th>n</th><th>実1着%</th><th>市場%</th><th>差</th><th>ROI%</th>";
      h += "</tr></thead><tbody>";
      names.forEach(function(name){
        (feats[name] || []).forEach(function(x){
          var dcls = x.diff_pct > 1 ? "ev-mid" : (x.diff_pct < -1 ? "ev-neg" : "");
          var rcls = (x.roi_pct != null && x.roi_pct > 0) ? "ev-mid" : "ev-neg";
          h += "<tr>";
          h += "<td>" + esc(name) + "</td>";
          h += "<td>" + esc(x.label) + "</td>";
          h += "<td>" + x.n + "</td>";
          h += "<td>" + x.hit_pct.toFixed(2) + "</td>";
          h += "<td>" + (x.market_pct != null ? x.market_pct.toFixed(2) : "-") + "</td>";
          h += "<td class=\"" + dcls + "\">" + (x.diff_pct >= 0 ? "+" : "") + x.diff_pct.toFixed(2) + "</td>";
          h += "<td class=\"" + rcls + "\">" + (x.roi_pct != null ? (x.roi_pct >= 0 ? "+" : "") + x.roi_pct.toFixed(1) : "-") + "</td>";
          h += "</tr>";
        });
      });
      h += "</tbody></table></div>";
      anaView.innerHTML = h;
    });
  }

  function renderFeatureInteractionsView(){
    anaView.textContent = "読み込み中...";
    loadFeatureInteractionsIfNeeded(function(){
      var d = featureInteractionsData || {};
      var h = "<h3 class=\"feature-title\">特徴量の交互作用（サンプル " + (d.samples || 0) + "行 / " + (d.total_cells || 0) + "セル）</h3>";
      h += "<p class=\"hint\">2特徴を3分位に分割したセル。有意 = 実1着率が市場期待を有意に上回る（95%CI下限が+）。</p>";
      // 有意セル（promising_diff）
      var sig = (d.promising_diff || []).slice();
      sig.sort(function(a,b){ return b.diff_pct - a.diff_pct; });
      h += "<h4 class=\"feature-title\">市場超過セル（上位50）</h4>";
      h += "<div class=\"decomp-scroll\"><table class=\"ev-table-decomp\"><thead><tr>";
      h += "<th>特徴A</th><th>QA</th><th>特徴B</th><th>QB</th><th>n</th><th>実%</th><th>市場%</th><th>差</th><th>有意</th><th>ROI%</th>";
      h += "</tr></thead><tbody>";
      sig.slice(0, 50).forEach(function(x){
        var rcls = (x.roi_pct != null && x.roi_pct > 0) ? "ev-mid" : "ev-neg";
        h += "<tr>";
        h += "<td>" + esc(x.fa) + "</td><td>Q" + (x.a_q + 1) + "</td>";
        h += "<td>" + esc(x.fb) + "</td><td>Q" + (x.b_q + 1) + "</td>";
        h += "<td>" + x.n + "</td>";
        h += "<td>" + x.hit_pct.toFixed(2) + "</td>";
        h += "<td>" + x.market_pct.toFixed(2) + "</td>";
        h += "<td class=\"ev-mid\">+" + x.diff_pct.toFixed(2) + "</td>";
        h += "<td>" + esc(x.sig || "-") + "</td>";
        h += "<td class=\"" + rcls + "\">" + (x.roi_pct != null ? (x.roi_pct >= 0 ? "+" : "") + x.roi_pct.toFixed(1) : "-") + "</td>";
        h += "</tr>";
      });
      h += "</tbody></table></div>";
      // ROI プラスセル
      var roi_pos = (d.promising_roi || []).slice();
      roi_pos.sort(function(a,b){ return (b.roi_pct||0) - (a.roi_pct||0); });
      h += "<h4 class=\"feature-title\">ROI プラスセル " + roi_pos.length + "件</h4>";
      h += "<div class=\"decomp-scroll\"><table class=\"ev-table-decomp\"><thead><tr>";
      h += "<th>特徴A</th><th>QA</th><th>特徴B</th><th>QB</th><th>n</th><th>実%</th><th>市場%</th><th>差</th><th>有意</th><th>ROI%</th>";
      h += "</tr></thead><tbody>";
      roi_pos.slice(0, 50).forEach(function(x){
        h += "<tr>";
        h += "<td>" + esc(x.fa) + "</td><td>Q" + (x.a_q + 1) + "</td>";
        h += "<td>" + esc(x.fb) + "</td><td>Q" + (x.b_q + 1) + "</td>";
        h += "<td>" + x.n + "</td>";
        h += "<td>" + x.hit_pct.toFixed(2) + "</td>";
        h += "<td>" + x.market_pct.toFixed(2) + "</td>";
        h += "<td>" + (x.diff_pct >= 0 ? "+" : "") + x.diff_pct.toFixed(2) + "</td>";
        h += "<td>" + esc(x.sig || "-") + "</td>";
        h += "<td class=\"ev-mid\">+" + x.roi_pct.toFixed(1) + "</td>";
        h += "</tr>";
      });
      h += "</tbody></table></div>";
      anaView.innerHTML = h;
    });
  }

})();
