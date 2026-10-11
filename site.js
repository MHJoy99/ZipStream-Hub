(function () {
  var d = document;
  // copy buttons
  d.querySelectorAll('.copy').forEach(function (b) {
    b.addEventListener('click', function () {
      var t = b.getAttribute('data-copy') || '';
      var done = function () { var o = b.textContent; b.textContent = 'Copied'; setTimeout(function () { b.textContent = o; }, 1400); };
      if (navigator.clipboard && navigator.clipboard.writeText) { navigator.clipboard.writeText(t).then(done, fallback); } else { fallback(); }
      function fallback() {
        var a = d.createElement('textarea'); a.value = t; a.style.position = 'fixed'; a.style.opacity = '0';
        d.body.appendChild(a); a.select();
        try { d.execCommand('copy'); done(); } catch (e) {}
        d.body.removeChild(a);
      }
    });
  });
  // reveal on scroll
  var els = d.querySelectorAll('.rv');
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (!('IntersectionObserver' in window) || reduce) { els.forEach(function (e) { e.classList.add('in'); }); return; }
  var io = new IntersectionObserver(function (en) {
    en.forEach(function (x) { if (x.isIntersecting) { x.target.classList.add('in'); io.unobserve(x.target); } });
  }, { rootMargin: '0px 0px -8% 0px', threshold: 0.06 });
  els.forEach(function (e, i) { e.style.transitionDelay = (i % 3) * 70 + 'ms'; io.observe(e); });
})();
