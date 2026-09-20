const API_BASE = "https://keiba-ev-tool.onrender.com";
(function(){
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("./sw.js");
  }
  var list = document.getElementById("race-list");
  function render(races){
    if (!races || !races.length) { list.textContent = "レースなし"; return; }
    var html = "";
    races.forEach(function(r){
      var waku = KeibaTheme.wakuClass(r.race_no || 1);
      html += "<div class=\"race\"><span class=\"" + waku + "\">" + (r.race_no || 1) + "</span> " + (r.course || "") + " " + (r.race_id || "") + "</div>";
    });
    list.innerHTML = html;
  }
  fetch(API_BASE + "/races").then(function(res){ return res.json(); }).then(render).catch(function(){
    render([{race_id:"keiba-mock-001",course:"東京",race_no:3}]);
  });
})();
