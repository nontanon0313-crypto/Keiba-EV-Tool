const API_BASE = "https://keiba-ev-tool.onrender.com";
const TIMEOUT_MS = 60000;
const EV_THRESHOLD = 0.12;

(function(){
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js", { updateViaCache: "none" }).then(function(reg){
      reg.update();
    });
    navigator.serviceWorker.addEventListener("controllerchange", function(){ window.location.reload(); });
  }

  var list = document.getElementById("race-list");
  var detail = document.getElementById("detail");
  var detailTitle = document.getElementById("detail-title");
  var detailBody = document.getElementById("detail-body");
  var backBtn = document.getElementById("back-btn");
  var racesSection = document.getElementById("races");

  function esc(s){
    return String(s == null ? "" : s).replace(/[&<>\x27]/g, function(c){
      return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","\x27":"&#39;"}[c];
    });
  }

  function renderList(races){
    if (!races || !races.length) { list.textContent = "本日のレースはありません"; return; }
    var html = "";
    races.forEach(function(r){
      var no = r.race_number || r.race_no || 1;
      var venue = r.venue || r.course || "";
      var surface = r.surface || "";
      var dist = r.distance || "";
      var time = (r.start_at || "").slice(11, 16);
      var runners = (r.runners || []).length;
      var waku = KeibaTheme.wakuClass(no);
      html += "<div class=\"race\" data-race-id=\"" + esc(r.race_id) + "\" role=\"button\" tabindex=\"0\">"
            + "<span class=\"" + waku + "\">" + no + "</span> "
            + "<strong>" + esc(venue) + "</strong> " + no + "R "
            + esc(surface) + " " + esc(dist) + "m "
            + esc(time) + " 発走 / " + runners + "頭"
            + "</div>";
    });
    list.innerHTML = html;
  }

  function renderDetail(race){
    var title = (race.venue || "") + " " + (race.race_number || "") + "R";
    detailTitle.textContent = title;
    var html = "";
    html += "<h3 class=\"ev-title\">EV上位の買い目 (3連単)</h3>"
          + "<div id=\"ev-table\">読み込み中...</div>";
    html += "<h3 class=\"ev-title\">出走馬</h3>";
    var runners = race.runners || [];
    if (!runners.length) {
      html += "<p>出走馬データがありません</p>";
    } else {
      html += "<table class=\"horse-table\"><thead><tr>"
            + "<th>枠</th><th>番</th><th>馬名</th><th>騎手</th><th>斤量</th><th>単勝</th><th>人気</th>"
            + "</tr></thead><tbody>";
      runners.forEach(function(h){
        var frame = h.frame_number || h.waku || 0;
        var num = h.horse_number || h.num || 0;
        var waku = KeibaTheme.wakuClass(frame || num);
        html += "<tr>"
              + "<td><span class=\"" + waku + "\">" + frame + "</span></td>"
              + "<td>" + num + "</td>"
              + "<td>" + esc(h.horse_name || "") + "</td>"
              + "<td>" + esc(h.jockey || "") + "</td>"
              + "<td>" + (h.weight || h.wEight || "") + "</td>"
              + "<td>" + (h.odds_win || h["勝ちオッズ"] || "") + "</td>"
              + "<td>" + (h["人気"] || h.popularity || "") + "</td>"
              + "</tr>";
      });
      html += "</tbody></table>";
    }
    detailBody.innerHTML = html;
    racesSection.hidden = true;
    detail.hidden = false;
    window.scrollTo(0, 0);
    loadEvTable(race.race_id);
  }

  function renderEvTable(bets, totalAmount){
    var box = document.getElementById("ev-table");
    if (!box) return;
    if (!bets || !bets.length) {
      box.textContent = "EV閾値超えの買い目はありません";
      return;
    }
    var html = "<p class=\"ev-total\">推奨合計: " + totalAmount + "円</p>";
    html += "<table class=\"ev-table\"><thead><tr>"
          + "<th>買い目</th><th>確率</th><th>オッズ</th><th>EV</th><th>金額</th>"
          + "</tr></thead><tbody>";
    bets.forEach(function(b){
      var cls = KeibaTheme.evClass(b.ev, EV_THRESHOLD);
      html += "<tr class=\"" + cls + "\">"
            + "<td>" + esc(b.combination) + "</td>"
            + "<td>" + (b.prob * 100).toFixed(2) + "%</td>"
            + "<td>" + b.odds.toFixed(1) + "</td>"
            + "<td>" + (b.ev >= 0 ? "+" : "") + b.ev.toFixed(3) + "</td>"
            + "<td>" + b.amount + "円</td>"
            + "</tr>";
    });
    html += "</tbody></table>";
    box.innerHTML = html;
  }

  function showList(){
    detail.hidden = true;
    racesSection.hidden = false;
    window.scrollTo(0, 0);
  }

  function fetchWithTimeout(url, ms, opts){
    var ctrl = new AbortController();
    var timer = setTimeout(function(){ ctrl.abort(); }, ms);
    var o = opts || {};
    o.signal = ctrl.signal;
    return fetch(url, o).finally(function(){ clearTimeout(timer); });
  }

  function loadEvTable(raceId){
    var box = document.getElementById("ev-table");
    if (!box) return;
    box.textContent = "EV計算中...";
    fetchWithTimeout(API_BASE + "/vote-plans?race_id=" + encodeURIComponent(raceId) + "&budget=2000", TIMEOUT_MS, { method: "POST" })
      .then(function(res){
        if (res.status === 204) { renderEvTable([], 0); return null; }
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function(data){
        if (!data) return;
        var plan = data.plan || {};
        renderEvTable(plan.bets || [], plan.total_amount || 0);
      })
      .catch(function(err){
        if (box) box.textContent = "EV取得失敗: " + err.message;
      });
  }

  function loadDetail(raceId){
    detail.hidden = false;
    racesSection.hidden = true;
    detailTitle.textContent = "読み込み中...";
    detailBody.innerHTML = "";
    fetchWithTimeout(API_BASE + "/races/" + encodeURIComponent(raceId), TIMEOUT_MS)
      .then(function(res){
        if (!res.ok) throw new Error("HTTP " + res.status);
        return res.json();
      })
      .then(function(race){ renderDetail(race); })
      .catch(function(err){ detailBody.textContent = "取得失敗: " + err.message; });
  }

  list.addEventListener("click", function(e){
    var el = e.target.closest(".race");
    if (!el) return;
    loadDetail(el.getAttribute("data-race-id"));
  });
  list.addEventListener("keydown", function(e){
    if (e.key !== "Enter" && e.key !== " ") return;
    var el = e.target.closest(".race");
    if (!el) return;
    e.preventDefault();
    loadDetail(el.getAttribute("data-race-id"));
  });
  backBtn.addEventListener("click", showList);

  list.textContent = "読み込み中... (サーバー起動待ちの場合があります)";
  fetchWithTimeout(API_BASE + "/races", TIMEOUT_MS)
    .then(function(res){
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function(data){
      var races = Array.isArray(data) ? data : (data.races || data.items || []);
      renderList(races);
    })
    .catch(function(err){
      list.textContent = "API取得失敗: " + err.message + " — 再読み込みしてください";
    });
})();
