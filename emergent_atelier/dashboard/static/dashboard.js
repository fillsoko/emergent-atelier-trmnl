/* ── Hero Slider ──────────────────────────────── */
(function () {
  var SLIDE_COUNT = 5;
  var AUTO_DELAY  = 5000;
  var current     = 0;
  var timer       = null;

  var track  = document.getElementById('hero-track');
  var dots   = document.getElementById('hero-dots');
  var prev   = document.getElementById('hero-prev');
  var next   = document.getElementById('hero-next');
  var ctr    = document.getElementById('hero-counter');

  // Build dots
  for (var i = 0; i < SLIDE_COUNT; i++) {
    var btn = document.createElement('button');
    btn.className = 'hero-dot' + (i === 0 ? ' active' : '');
    btn.setAttribute('role', 'tab');
    btn.setAttribute('aria-label', 'Go to slide ' + (i + 1));
    btn.setAttribute('aria-selected', i === 0 ? 'true' : 'false');
    btn.dataset.idx = i;
    btn.addEventListener('click', function () { goTo(+this.dataset.idx, true); });
    dots.appendChild(btn);
  }

  function goTo(idx, manual) {
    current = (idx + SLIDE_COUNT) % SLIDE_COUNT;
    track.style.transform = 'translateX(-' + (current * 100) + '%)';

    var allDots = dots.querySelectorAll('.hero-dot');
    allDots.forEach(function (d, di) {
      d.classList.toggle('active', di === current);
      d.setAttribute('aria-selected', di === current ? 'true' : 'false');
    });

    ctr.textContent = (current + 1) + ' / ' + SLIDE_COUNT;

    if (manual) { resetTimer(); }
  }

  function resetTimer() {
    clearInterval(timer);
    timer = setInterval(function () { goTo(current + 1, false); }, AUTO_DELAY);
  }

  prev.addEventListener('click', function () { goTo(current - 1, true); });
  next.addEventListener('click', function () { goTo(current + 1, true); });

  // Keyboard navigation
  document.addEventListener('keydown', function (e) {
    if (e.key === 'ArrowLeft')  { goTo(current - 1, true); }
    if (e.key === 'ArrowRight') { goTo(current + 1, true); }
  });

  // Pause on hover
  var hero = document.querySelector('.hero');
  hero.addEventListener('mouseenter', function () { clearInterval(timer); });
  hero.addEventListener('mouseleave', function () { resetTimer(); });

  // Touch / swipe support
  var touchStartX = null;
  hero.addEventListener('touchstart', function (e) {
    touchStartX = e.touches[0].clientX;
  }, { passive: true });
  hero.addEventListener('touchend', function (e) {
    if (touchStartX === null) return;
    var dx = e.changedTouches[0].clientX - touchStartX;
    if (Math.abs(dx) > 40) { goTo(dx < 0 ? current + 1 : current - 1, true); }
    touchStartX = null;
  });

  // Init
  goTo(0, false);
  resetTimer();
}());

/* ── Dashboard ───────────────────────────────── */
var cycleInfo = document.getElementById('cycle-info');
var agentsList = document.getElementById('agents-list');
var filmstrip = document.getElementById('filmstrip');
var liveCanvas = document.getElementById('live-canvas');
var statusMsg = document.getElementById('status-msg');

async function fetchStatus() {
  var res = await fetch('/api/status');
  var data = await res.json();
  agentsList.innerHTML = '';
  data.agents.forEach(function (a) {
    var card = document.createElement('div');
    card.className = 'agent-card' + (a.enabled ? ' enabled' : '');

    var nameDiv = document.createElement('div');
    nameDiv.className = 'name';
    var statusSpan = document.createElement('span');
    statusSpan.className = 'status';
    nameDiv.appendChild(statusSpan);
    nameDiv.appendChild(document.createTextNode(a.name));

    var roleDiv = document.createElement('div');
    roleDiv.className = 'role';
    roleDiv.textContent = a.role + ' \xb7 ' + a.algorithm;

    card.appendChild(nameDiv);
    card.appendChild(roleDiv);
    agentsList.appendChild(card);
  });
}

async function fetchHistory() {
  var res = await fetch('/api/history?limit=12');
  var frames = await res.json();
  filmstrip.innerHTML = '';
  frames.forEach(function (f) {
    var el = document.createElement('div');
    el.className = 'strip-frame';

    var img = document.createElement('img');
    img.src = 'data:image/png;base64,' + f.thumbnail_b64;
    img.alt = 'cycle ' + f.cycle;

    var meta = document.createElement('div');
    meta.className = 'meta';

    var cycleSpan = document.createElement('span');
    cycleSpan.textContent = '#' + f.cycle;

    var deltaSpan = document.createElement('span');
    deltaSpan.className = 'delta';
    deltaSpan.textContent = ' \xb7 \u0394' + f.delta_pct.toFixed(1) + '%';

    meta.appendChild(cycleSpan);
    meta.appendChild(deltaSpan);
    el.appendChild(img);
    el.appendChild(meta);
    filmstrip.appendChild(el);
  });
}

function refreshCanvas() {
  liveCanvas.src = '/image.png?t=' + Date.now();
}

document.getElementById('btn-refresh').addEventListener('click', function () {
  refreshCanvas();
  fetchStatus();
  fetchHistory();
});

fetchStatus();
fetchHistory();

setInterval(function () {
  fetchStatus();
  fetchHistory();
  refreshCanvas();
}, 30000);
