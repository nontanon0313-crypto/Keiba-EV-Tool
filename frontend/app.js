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
  var tabPredict = $("tab-predict"), tabAnalytics = $("tab-analytics"), tabBets = $("tab-bets");
  var fMinProb = $("f-minprob"), fMinOdds = $("f-minodds"), fCollateral = $("f-collateral"), fMaxInv = $("f-maxinv");
  var anaSummary = $("ana-summary"), anaView = $("ana-view");
  var anaScopeTabs = $("ana-scope-tabs"), anaViewTabs = $("ana-view-tabs");
  var betsSummary = $("bets-summary"), betsList = $("bets-list"), curveCanvas = $("curve-chart");
  var analyticsData = null, currentScope = "all", currentView = "ev", filters = {}, currentBets = [];

  function esc(s){ return String(s == null ? "" : s).replace(/[&<>\x27]/g, function(c){ return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","\x27":"&#39;"}[c]; }); }
  function fmtPct(v, d){ return (v * 100).toFixed(d == null ? 2 : d) + "%"; }
  function fmtNum(v, d){ return Number(v).toFixed(d == null ? 2 : d); }
  function fmtInt(v){ return String(Math.round(v)); }
  function fmtYen(v){ return fmtInt(v) + "円"; }
  function fmtSigned(v, d){ return (v >= 0 ? "+" : "") + fmtNum(v, d); }

  function readFilters(){
    filters.minProb = Math.max(0, Number(fMinProb.value || 0)) / 100;
    filters.minOdds = Math.max(0, Number(fMinOdds.value || 0));
    filters.collateral = Math.max(1000, Math.round(Number(fCollateral.value || 100000)));
    filters.maxInvestment = Math.max(100, Math.round(Number(fMaxInv.value || 10000)));
  }

  function sortRaces(races){ return races.slice().sort(function(a, b){ var sa = a.start_at || "", sb = b.start_at || ""; return sa < sb ? -1 : sa > sb ? 1 : 0; }); }
  function isFinished(r){ if (!r.start_at) return false; var t = Date.parse(r.start_at); if (isNaN(t)) return false; return (Date.now() - t) > FINISH_GRACE_MS; }

  function renderList(races){
    var visible = sortRaces(races.filter(function(r){ return !isFinished(r); }));
    if (!visible.length) { list.textContent = "本日のレースはありません（終了分を除く）"; return; }
    var html = "";
    visible.forEach(function(r){
      var no = r.race_number || r.race_no || 1, venue = r.venue || r.course || "";
      var surface = r.surface || "", dist = r.distance || "";
      var time = (r.start_at || "").slice(11, 16);
      var runners = (r.runners || []).length;
      var waku = KeibaTheme.wakuClass(no);
      html += "<div class=\"race\" data-race-id=\"" + esc(r.race_id) + "\" role=\"button\" tabindex=\"0\">" + "<span class=\"" + waku + "\">" + no + "</span> " + "<strong>" + esc(venue) + "</strong> " + no + "R " + esc(surface) + " " + esc(dist) + "m " + esc(time) + " 発走 / " + runners + "頭" + "</div>";
    });
    list.innerHTML = html;
  }

  function renderDetail(race){
    detailTitle.textContent = (race.venue || "") + " " + (race.race_number || "") + "R";
    var html = "<h3 class=\"ev-title\">EV上位の買い目 (3連単)</h3><div id=\"ev-table\">読み込み中...</div>";
    html += "<h3 class=\"ev-title\">出走馬</h3>";
    var runners = race.runners || [];
    if (!runners.length) { html += "<p>出走馬データがありません</p>"; }
    else {
      html += "<table class=\"horse-table\"><thead><tr><th>枠</th><th>番</th><th>馬名</th><th>騎手</th><th>斤量</th><th>単勝</th><th>人気</th></tr></thead><tbody>";
      runners.forEach(function(h){
        var frame = h.frame_number || h.waku || 0, num = h.horse_number || h.num || 0;
        var waku = KeibaTheme.wakuClass(frame || num);
        html += "<tr><td><span class=\"" + waku + "\">" + frame + "</span></td><td>" + num + "</td><td>" + esc(h.horse_name || "") + "</td><td>" + esc(h.jockey || "") + "</td><td>" + (h.weight || h.wEight || "") + "</td><td>" + (h.odds_win || h["勝ちオッズ"] || "") + "</td><td>" + (h["人気"] || h.popularity || "") + "</td></tr>";
      });
      html += "</tbody></table>";
    }
    detailBody.innerHTML = html;
    racesSection.hidden = true;
    detail.hidden = false;
    window.scrollTo(0, 0);
    loadEvTable(race.race_id);
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
      html += "<tr class=\"" + cls + "\"><td>" + esc(b.combination) + "</td><td>" + fmtPct(b.prob) + "</td><td>" + fmtNum(b.odds, 1) + "</td><td>" + fmtSigned(b.ev, 3) + "</td><td>" + fmtYen(b.amount) + "</td><td><button class=\"bet-btn\" data-idx=\"" + idx + "\" type=\"button\">投票</button></td></tr>";
    });
    html += "</tbody></table>";
    box.innerHTML = html;
    box.querySelectorAll(".bet-btn").forEach(function(btn){
      btn.addEventListener("click", function(){ recordBet(raceId, currentBets[Number(btn.getAttribute("data-idx"))]); });
    });
  }

  function recordBet(raceId, b){
    fetchWithTimeout(API_BASE + "/bets", TIMEOUT_MS, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ race_id: raceId, combo: b.combination, amount: b.amount, odds: b.odds, prob: b.prob, ev: b.ev }) })
      .then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); })
      .then(function(){ alert("投票を記録しました"); })
      .catch(function(err){ alert("記録失敗: " + err.message); });
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
    var qs = "?race_id=" + encodeURIComponent(raceId) + "&min_prob=" + encodeURIComponent(filters.minProb) + "&min_odds=" + encodeURIComponent(filters.minOdds) + "&collateral=" + encodeURIComponent(filters.collateral) + "&max_investment=" + encodeURIComponent(filters.maxInvestment);
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
    var html = "<table class=\"ev-table\"><thead><tr><th>" + label + "</th><th>件数</th><th>予想的中率</th><th>オッズ平均</th><th>想定利益%</th><th>実的中率</th><th>実利益%</th></tr></thead><tbody>";
    rows.forEach(function(r){
      var cls = KeibaTheme.evClass(r.expected_profit_pct / 100, EV_THRESHOLD);
      var actual = r.actual_rate == null ? "-" : fmtPct(r.actual_rate);
      var ap = r.actual_profit_pct == null ? "-" : fmtSigned(r.actual_profit_pct, 1);
      html += "<tr class=\"" + cls + "\"><td>" + esc(r.range) + "</td><td>" + r.count + "</td><td>" + fmtPct(r.avg_prob) + "</td><td>" + fmtNum(r.avg_odds, 1) + "</td><td>" + fmtSigned(r.expected_profit_pct, 1) + "</td><td>" + actual + "</td><td>" + ap + "</td></tr>";
    });
    html += "</tbody></table>";
    return html;
  }

  function featuresView(features){
    if (!features || !features.length) return "<p>該当データなし</p>";
    var html = "";
    features.forEach(function(f){
      html += "<h4 class=\"feature-title\">" + esc(f.label) + "</h4>";
      html += tableRows(f.rows || [], "範囲");
    });
    return html;
  }

  function renderAnaSummary(s){
    if (!s) { anaSummary.innerHTML = ""; return; }
    var cnt = s.count || 0;
    var voted = s.voted_count == null ? 0 : s.voted_count;
    var total = s.total_count == null ? cnt : s.total_count;
    var ratio = currentScope === "all" ? (voted + "/" + total + " が投票対象") : (cnt + " 件");
    anaSummary.innerHTML = "<div>件数: " + cnt + " (" + ratio + ")</div>"
      + "<div>実的中率: " + (s.actual_rate == null ? "-" : fmtPct(s.actual_rate)) + "</div>"
      + "<div>想定利益%: " + fmtSigned(s.avg_expected_profit_pct, 2) + "</div>";
  }

  function renderView(){
    if (!analyticsData) return;
    var ticket = (analyticsData.by_ticket || [])[0] || { scopes: {} };
    var s = (ticket.scopes || {})[currentScope] || { summary: null, prob_bins: [], odds_bins: [], ev_bins: [], features: [] };
    renderAnaSummary(s.summary);
    if (currentView === "prob") { anaView.innerHTML = tableRows(s.prob_bins || [], "確率帯"); return; }
    if (currentView === "odds") { anaView.innerHTML = tableRows(s.odds_bins || [], "オッズ帯"); return; }
    if (currentView === "features") { anaView.innerHTML = featuresView(s.features || []); return; }
    anaView.innerHTML = tableRows(s.ev_bins || [], "期待値帯");
  }

  function loadAnalytics(){
    anaSummary.textContent = "読み込み中..."; anaView.textContent = "読み込み中...";
    fetchWithTimeout(API_BASE + "/analytics", TIMEOUT_MS)
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
    function line(points, color){ if (!points.length) return; ctx.strokeStyle = color; ctx.lineWidth = 2; ctx.beginPath(); points.forEach(function(p, i){ var x = sx(p.x), y = sy(p.y); if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y); }); ctx.stroke(); }
    line(exp, "#D4AF37"); line(act, "#ff4d4d");
    ctx.fillStyle = "#D4AF37"; ctx.fillText("想定", W - 60, 20);
    ctx.fillStyle = "#ff4d4d"; ctx.fillText("実績", W - 60, 36);
  }

  function renderBetsSummary(s){
    if (!s) { betsSummary.textContent = "データなし"; return; }
    var cls = s.total_profit >= 0 ? "ev-mid" : "ev-neg";
    betsSummary.innerHTML = "<div>投票数: " + s.total_bets + "</div>"
      + "<div>投資: " + fmtYen(s.total_stake) + " / 払戻: " + fmtYen(s.total_return) + "</div>"
      + "<div class=\"" + cls + "\">損益: " + (s.total_profit >= 0 ? "+" : "") + fmtYen(s.total_profit) + " (想定: " + fmtSigned(s.expected_profit, 0) + "円)</div>"
      + "<div>実的中率: " + fmtPct(s.hit_rate, 1) + " / 想定的中率: " + fmtPct(s.expected_hit_rate, 1) + "</div>"
      + "<div>実ROI: " + fmtPct(s.roi, 1) + " / 想定ROI: " + fmtPct(s.expected_roi, 1) + "</div>"
      + "<div>平均オッズ: " + fmtNum(s.avg_odds, 1) + " / 加重平均: " + fmtNum(s.weighted_avg_odds, 1) + "</div>";
  }

  function renderBetsList(rows){
    if (!rows || !rows.length) { betsList.textContent = "投票履歴はありません"; return; }
    var html = "<table class=\"ev-table\"><thead><tr><th>レース</th><th>買い目</th><th>金額</th><th>オッズ</th><th>状態</th><th>損益</th><th></th></tr></thead><tbody>";
    rows.forEach(function(r){
      var cls = r.profit > 0 ? "ev-mid" : r.profit < 0 ? "ev-neg" : "";
      var statusLabel = r.status === "hit" ? "的中" : r.status === "miss" ? "不的中" : r.status === "pending" ? "確定待ち" : r.status;
      html += "<tr class=\"" + cls + "\"><td>" + esc(r.race_id) + "</td><td>" + esc(r.combo) + "</td><td>" + fmtYen(r.amount) + "</td><td>" + fmtNum(r.odds, 1) + "</td><td>" + statusLabel + "</td><td>" + (r.profit >= 0 ? "+" : "") + fmtYen(r.profit) + "</td><td><button class=\"del-btn\" data-id=\"" + r.id + "\" type=\"button\">削除</button></td></tr>";
    });
    html += "</tbody></table>";
    betsList.innerHTML = html;
    betsList.querySelectorAll(".del-btn").forEach(function(btn){
      btn.addEventListener("click", function(){ var id = btn.getAttribute("data-id"); fetchWithTimeout(API_BASE + "/bets/" + id, TIMEOUT_MS, { method: "DELETE" }).then(function(){ loadBets(); }).catch(function(){ alert("削除失敗"); }); });
    });
  }

  function loadBets(){
    betsSummary.textContent = "読み込み中..."; betsList.textContent = "読み込み中...";
    fetchWithTimeout(API_BASE + "/bets/summary", TIMEOUT_MS).then(function(res){ return res.json(); }).then(renderBetsSummary).catch(function(err){ betsSummary.textContent = "取得失敗: " + err.message; });
    fetchWithTimeout(API_BASE + "/bets/curve", TIMEOUT_MS).then(function(res){ return res.json(); }).then(drawCurve).catch(function(){ drawCurve(null); });
    fetchWithTimeout(API_BASE + "/bets", TIMEOUT_MS).then(function(res){ return res.json(); }).then(renderBetsList).catch(function(err){ betsList.textContent = "取得失敗: " + err.message; });
  }

  function switchTab(name){
    document.querySelectorAll(".tab").forEach(function(t){ t.classList.toggle("active", t.getAttribute("data-tab") === name); });
    tabPredict.hidden = name !== "predict";
    tabAnalytics.hidden = name !== "analytics";
    tabBets.hidden = name !== "bets";
    window.scrollTo(0, 0);
    if (name === "analytics") loadAnalytics();
    if (name === "bets") loadBets();
  }

  document.querySelectorAll(".tab").forEach(function(t){ t.addEventListener("click", function(){ switchTab(t.getAttribute("data-tab")); }); });
  anaScopeTabs.querySelectorAll(".subtab").forEach(function(t){
    t.addEventListener("click", function(){
      anaScopeTabs.querySelectorAll(".subtab").forEach(function(x){ x.classList.remove("active"); });
      t.classList.add("active"); currentScope = t.getAttribute("data-scope"); renderView();
    });
  });
  anaViewTabs.querySelectorAll(".subtab").forEach(function(t){
    t.addEventListener("click", function(){
      anaViewTabs.querySelectorAll(".subtab").forEach(function(x){ x.classList.remove("active"); });
      t.classList.add("active"); currentView = t.getAttribute("data-view"); renderView();
    });
  });
  [fMinProb, fMinOdds, fCollateral, fMaxInv].forEach(function(el){ el.addEventListener("change", function(){ if (detail && !detail.hidden && detail.dataset.raceId) loadEvTable(detail.dataset.raceId); }); });
  list.addEventListener("click", function(e){ var el = e.target.closest(".race"); if (!el) return; detail.dataset.raceId = el.getAttribute("data-race-id"); loadDetail(el.getAttribute("data-race-id")); });
  list.addEventListener("keydown", function(e){ if (e.key !== "Enter" && e.key !== " ") return; var el = e.target.closest(".race"); if (!el) return; e.preventDefault(); detail.dataset.raceId = el.getAttribute("data-race-id"); loadDetail(el.getAttribute("data-race-id")); });
  backBtn.addEventListener("click", showList);

  readFilters();
  list.textContent = "読み込み中... (サーバー起動待ちの場合があります)";
  fetchWithTimeout(API_BASE + "/races", TIMEOUT_MS).then(function(res){ if (!res.ok) throw new Error("HTTP " + res.status); return res.json(); }).then(function(data){ var races = Array.isArray(data) ? data : (data.races || data.items || []); renderList(races); }).catch(function(err){ list.textContent = "API取得失敗: " + err.message + " — 再読み込みしてください"; });
})();
