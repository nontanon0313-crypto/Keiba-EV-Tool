const API_BASE = "https://keiba-ev-tool.onrender.com";
const TIMEOUT_MS = 60000;

(function(){
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js");
  }

  var list = document.getElementById("race-list");

  function esc(s){
    return String(s == null ? "" : s).replace(/[&<>"\x27]/g, function(c){
      return {"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","\x27":"&#39;"}[c];
    });
  }

  function render(races){
    if (!races || !races.length) { list.textContent = "本日のレースはありません"; return; }
    var html = "";
    races.forEach(function(r){
      var no = r.race_number || 1;
      var venue = r.venue || "";
      var surface = r.surface || "";
      var dist = r.distance || "";
      var time = (r.start_at || "").slice(11, 16);
      var runners = (r.runners || []).length;
      var waku = KeibaTheme.wakuClass(no);
      html += "<div class=\"race\" data-race-id=\"" + esc(r.race_id) + "\">"
            + "<span class=\"" + waku + "\">" + no + "</span> "
            + "<strong>" + esc(venue) + "</strong> "
            + esc(surface) + " " + esc(dist) + "m "
            + esc(time) + " 発走 / " + runners + "頭"
            + "</div>";
    });
    list.innerHTML = html;
  }

  function fetchWithTimeout(url, ms){
    var ctrl = new AbortController();
    var timer = setTimeout(function(){ ctrl.abort(); }, ms);
    return fetch(url, { signal: ctrl.signal }).finally(function(){ clearTimeout(timer); });
  }

  list.textContent = "読み込み中... (サーバー起動待ちの場合があります)";

  fetchWithTimeout(API_BASE + "/races", TIMEOUT_MS)
    .then(function(res){
      if (!res.ok) throw new Error("HTTP " + res.status);
      return res.json();
    })
    .then(function(data){
      var races = Array.isArray(data) ? data : (data.races || data.items || []);
      render(races);
    })
    .catch(function(err){
      list.textContent = "API取得失敗: " + err.message + " — 再読み込みしてください";
    });
})();
