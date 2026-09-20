(function(global){
  function evClass(ev, threshold){
    if (ev < 0) return "ev-neg";
    if (ev < threshold) return "ev-low";
    if (ev < 0.3) return "ev-mid";
    return "ev-high";
  }
  function wakuClass(n){
    var i = ((n - 1) % 8 + 8) % 8 + 1;
    return "waku waku-" + i;
  }
  global.KeibaTheme = { evClass: evClass, wakuClass: wakuClass };
})(typeof window !== "undefined" ? window : this);
