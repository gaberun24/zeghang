/* ==============================================
   Zalaegerszeg Hangja — Frontend JavaScript
   ============================================== */

// ── THEME ──
function getThemePreference() {
    return localStorage.getItem('theme') || 'system';
}

function applyTheme(pref) {
    var html = document.documentElement;
    if (pref === 'dark') {
        html.setAttribute('data-theme', 'dark');
    } else if (pref === 'light') {
        html.removeAttribute('data-theme');
    } else {
        // system
        if (window.matchMedia('(prefers-color-scheme: dark)').matches) {
            html.setAttribute('data-theme', 'dark');
        } else {
            html.removeAttribute('data-theme');
        }
    }
}

function setTheme(pref) {
    localStorage.setItem('theme', pref);
    applyTheme(pref);
    // Save to server if logged in
    var csrfEl = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfEl ? csrfEl.getAttribute('content') : '';
    fetch('/api/settings/theme', {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrfToken},
        body: JSON.stringify({theme: pref})
    }).catch(function() {});
}

// Apply immediately (before page renders to avoid flash)
applyTheme(getThemePreference());

// Listen for system theme changes
window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function() {
    if (getThemePreference() === 'system') applyTheme('system');
});

// CSRF token from meta tag
function getCsrf() {
  const el = document.querySelector('meta[name="csrf-token"]');
  return el ? el.getAttribute('content') : '';
}

// ── VOTING ──
function vote(btn, direction) {
  const col = btn.closest('.vote-col');
  const issueId = col.dataset.issueId;
  const countEl = col.querySelector('.vote-count');

  fetch(`/issue/${issueId}/vote`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrf(),
    },
    body: JSON.stringify({ direction: direction }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        countEl.textContent = data.vote_score;
        const upBtn = col.querySelectorAll('.vote-btn')[0];
        const downBtn = col.querySelectorAll('.vote-btn')[1];
        upBtn.classList.toggle('upvoted', data.user_vote === 1);
        downBtn.classList.toggle('downvoted', data.user_vote === -1);
      }
    })
    .catch(() => {});
}

// ── FILTER PILLS ──
function toggleFilter(el) {
  const parent = el.closest('.filter-bar');
  const pills = parent.querySelectorAll('.filter-pill');
  const allPill = pills[0]; // "Mind" is first

  if (el === allPill) {
    pills.forEach(p => p.classList.remove('active'));
    allPill.classList.add('active');
  } else {
    allPill.classList.remove('active');
    el.classList.toggle('active');
    if (!parent.querySelector('.filter-pill.active')) {
      allPill.classList.add('active');
    }
  }

  applyFilters();
}

function applyFilters() {
  const activePills = document.querySelectorAll('.filter-bar .filter-pill.active');
  const activeCategories = [];
  activePills.forEach(p => {
    const cat = p.dataset.category;
    if (cat && cat !== 'all') activeCategories.push(cat);
  });

  const issues = document.querySelectorAll('.issue');
  issues.forEach(issue => {
    if (activeCategories.length === 0) {
      issue.style.display = '';
    } else {
      const issueCat = issue.dataset.category;
      issue.style.display = activeCategories.includes(issueCat) ? '' : 'none';
    }
  });
}

// ── TABS ──
function switchTab(el) {
  el.closest('.tabs').querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  el.classList.add('active');
  // Navigate to the tab URL
  const url = el.dataset.url;
  if (url) window.location.href = url;
}

// ── SORT ──
function applySort(selectEl) {
  const val = selectEl.value;
  const url = new URL(window.location);
  url.searchParams.set('sort', val);
  window.location.href = url.toString();
}

// ── NEW ISSUE FORM (MODAL) ──
function openForm() {
  const overlay = document.getElementById('formOverlay');
  if (overlay) {
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
  }
}

function closeForm() {
  const overlay = document.getElementById('formOverlay');
  if (overlay) {
    overlay.classList.remove('active');
    document.body.style.overflow = '';
  }
}

// Close on backdrop click
document.addEventListener('click', function (e) {
  if (e.target && e.target.id === 'formOverlay') closeForm();
});

// ESC to close
document.addEventListener('keydown', function (e) {
  if (e.key === 'Escape') closeForm();
});

// Category chip selection
function selectCat(el) {
  el.parentElement.querySelectorAll('.cat-chip').forEach(c => c.classList.remove('selected'));
  el.classList.add('selected');
  // Set hidden input
  const input = document.getElementById('categoryInput');
  if (input) input.value = el.dataset.category;
}

// ── AI CATEGORIZE (AJAX) ──
let aiTimer;
function aiCategorize() {
  clearTimeout(aiTimer);
  const title = document.getElementById('issueTitle');
  if (!title || title.value.length < 8) {
    const badge = document.getElementById('aiSuggest');
    if (badge) badge.style.display = 'none';
    return;
  }

  aiTimer = setTimeout(() => {
    fetch('/api/ai-categorize', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': getCsrf(),
      },
      body: JSON.stringify({ title: title.value }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.category) {
          const chips = document.querySelectorAll('.cat-chip');
          chips.forEach(c => {
            c.classList.toggle('selected', c.dataset.category === data.category);
          });
          const input = document.getElementById('categoryInput');
          if (input) input.value = data.category;
          const badge = document.getElementById('aiSuggest');
          if (badge) badge.style.display = 'inline-flex';
        }
      })
      .catch(() => {});
  }, 600);
}

// ── ISSUE FORM SUBMIT ──
function submitIssue(e, confirmDuplicate) {
  if (e) e.preventDefault();

  const title = document.getElementById('issueTitle').value.trim();
  const desc = document.getElementById('issueDesc').value.trim();
  const category = document.getElementById('categoryInput').value;
  const location = document.getElementById('issueLocation')
    ? document.getElementById('issueLocation').value.trim()
    : '';

  if (!title) {
    alert('Kérlek add meg a bejelentés címét!');
    return;
  }
  if (!desc) {
    alert('Kérlek add meg a leírást!');
    return;
  }

  const formData = new FormData();
  formData.append('title', title);
  formData.append('description', desc);
  formData.append('category', category || 'other');
  formData.append('location', location);

  // If user confirmed duplicate, pass flag
  if (confirmDuplicate) {
    formData.append('confirm_duplicate', 'true');
  }

  // Add map coordinates if set
  var latEl = document.getElementById('issueLat');
  var lngEl = document.getElementById('issueLng');
  if (latEl && latEl.value) formData.append('lat', latEl.value);
  if (lngEl && lngEl.value) formData.append('lng', lngEl.value);

  // Add photos if any
  const photoInput = document.getElementById('photoInput');
  if (photoInput && photoInput.files) {
    for (let i = 0; i < photoInput.files.length; i++) {
      formData.append('photos', photoInput.files[i]);
    }
  }

  // Disable button to prevent double submit
  var btn = document.querySelector('.btn-submit');
  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Küldés...';
  }

  // Show progress bar if there are photos
  var hasPhotos = photoInput && photoInput.files && photoInput.files.length > 0;
  var progressWrap = document.getElementById('uploadProgress');
  var progressBar = document.getElementById('uploadBar');
  var progressText = document.getElementById('uploadText');
  if (hasPhotos && progressWrap) {
    progressWrap.style.display = 'block';
    progressBar.style.width = '0%';
    progressText.textContent = 'Feltöltés...';
  }

  var xhr = new XMLHttpRequest();
  xhr.open('POST', '/issue/new');
  xhr.setRequestHeader('X-CSRFToken', getCsrf());

  xhr.upload.onprogress = function(e) {
    if (e.lengthComputable && progressBar) {
      var pct = Math.round((e.loaded / e.total) * 100);
      progressBar.style.width = pct + '%';
      progressText.textContent = 'Feltöltés... ' + pct + '%';
    }
  };

  xhr.onload = function() {
    if (progressWrap) progressWrap.style.display = 'none';
    try {
      var data = JSON.parse(xhr.responseText);
      if (data.ok) {
        closeForm();
        showToast('✓ Bejelentés elküldve — megjelenik a körzeti listán');
        setTimeout(function() { window.location.reload(); }, 1500);
      } else if (data.duplicate) {
        if (btn) { btn.disabled = false; btn.textContent = 'Bejelentés küldése →'; }
        showDuplicateWarning(data);
      } else {
        if (btn) { btn.disabled = false; btn.textContent = 'Bejelentés küldése →'; }
        showToast('⚠ ' + (data.error || 'Hiba történt a küldés során.'), true);
      }
    } catch(e) {
      if (btn) { btn.disabled = false; btn.textContent = 'Bejelentés küldése →'; }
      showToast('⚠ Hiba történt a küldés során.', true);
    }
  };

  xhr.onerror = function() {
    if (progressWrap) progressWrap.style.display = 'none';
    if (btn) { btn.disabled = false; btn.textContent = 'Bejelentés küldése →'; }
    alert('Hiba történt a küldés során.');
  };

  xhr.send(formData);
}

function showDuplicateWarning(data) {
  var existing = document.getElementById('dupWarning');
  if (existing) existing.remove();

  var statusLabels = { new: 'Új', progress: 'Vizsgálat alatt', done: 'Megoldva ✓' };
  var statusClass = data.duplicate_status === 'done' ? '#27ae60' : (data.duplicate_status === 'progress' ? '#f39c12' : '#3498db');

  var warning = document.createElement('div');
  warning.id = 'dupWarning';
  warning.style.cssText = 'background:#fff3cd; border:1.5px solid #f0c040; border-radius:10px; padding:18px; margin-bottom:1rem;';
  warning.innerHTML =
    '<div style="font-weight:700; font-size:15px; margin-bottom:12px;">🤖 Hasonló bejelentés már létezik!</div>' +
    // Mini issue card
    '<a href="/issue/' + data.duplicate_id + '" target="_blank" style="display:block; background:white; border:1.5px solid #e0e0e0; border-radius:8px; padding:14px; text-decoration:none; color:inherit; margin-bottom:14px;">' +
      '<div style="display:flex; align-items:center; gap:8px; margin-bottom:6px;">' +
        '<span style="background:' + statusClass + '; color:white; font-size:11px; padding:2px 8px; border-radius:4px; font-weight:600;">' + (statusLabels[data.duplicate_status] || 'Új') + '</span>' +
        '<span style="font-size:12px; color:#888;">📅 ' + data.duplicate_date + '</span>' +
        '<span style="font-size:12px; color:#888; margin-left:auto;">↑ ' + data.duplicate_votes + ' szavazat</span>' +
      '</div>' +
      '<div style="font-weight:600; font-size:15px; margin-bottom:4px;">' + data.duplicate_title + '</div>' +
      '<div style="font-size:13px; color:#666; line-height:1.5;">' + data.duplicate_desc + (data.duplicate_desc.length >= 200 ? '...' : '') + '</div>' +
    '</a>' +
    '<div style="font-size:13px; color:#666; margin-bottom:14px;">Ha ugyanarról a problémáról van szó, szavazz a meglévőre — így nagyobb súlya lesz! Ha mégis más a probléma, küldd el újként.</div>' +
    '<div style="display:flex; gap:8px; flex-wrap:wrap;">' +
      '<button onclick="window.location.href=\'/issue/' + data.duplicate_id + '\'" style="padding:10px 18px; border:none; background:#1B4F8A; color:white; border-radius:6px; cursor:pointer; font-size:13px; font-weight:600;">Meglévőre szavazok ↑</button>' +
      '<button onclick="submitIssue(null, true)" style="padding:10px 18px; border:1.5px solid #ccc; background:white; color:#666; border-radius:6px; cursor:pointer; font-size:13px;">Más probléma, mégis küldöm →</button>' +
    '</div>';

  var formBody = document.querySelector('.form-body');
  if (formBody) formBody.insertBefore(warning, formBody.firstChild);
  warning.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
}

// ── TOAST ──
function showToast(message, isError) {
  const toast = document.getElementById('toast');
  if (!toast) return;
  toast.textContent = message;
  toast.classList.toggle('toast-error', !!isError);
  toast.classList.add('show');
  setTimeout(() => { toast.classList.remove('show'); toast.classList.remove('toast-error'); }, isError ? 5000 : 3500);
}

// ── COMMENT FORM ──
function submitComment(e) {
  if (e) e.preventDefault();
  const form = e.target;
  const textarea = form.querySelector('textarea');
  const issueId = form.dataset.issueId;
  const content = textarea.value.trim();

  if (!content) return;

  fetch(`/issue/${issueId}/comment`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrf(),
    },
    body: JSON.stringify({ content: content }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        window.location.reload();
      }
    })
    .catch(() => {});
}

// ── RESOLUTION VOTING ──
function startResolution(issueId) {
  if (!confirm('Biztos, hogy szerinted megoldódott ez a probléma?\n\nEzzel 7 napos szavazás indul, ahol a közösség megerősítheti vagy cáfolhatja.')) return;

  fetch(`/issue/${issueId}/resolve`, {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrf() },
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        window.location.reload();
      } else {
        showToast('\u26a0 ' + (data.error || 'Hiba történt.'), true);
      }
    })
    .catch(() => showToast('\u26a0 Hiba történt.', true));
}

function resolutionVote(issueId, vote) {
  fetch(`/issue/${issueId}/resolve-vote`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'X-CSRFToken': getCsrf(),
    },
    body: JSON.stringify({ vote: vote }),
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        document.getElementById('resYes').textContent = data.yes;
        document.getElementById('resNo').textContent = data.no;
        var btnYes = document.getElementById('btnResYes');
        var btnNo = document.getElementById('btnResNo');
        if (btnYes) btnYes.style.opacity = data.user_vote === true ? '0.5' : '1';
        if (btnNo) btnNo.style.opacity = data.user_vote === false ? '0.5' : '1';
        showToast('\u2713 Szavazat rögzítve!');
      } else {
        showToast('\u26a0 ' + (data.error || 'Hiba történt.'), true);
      }
    })
    .catch(() => showToast('\u26a0 Hiba történt.', true));
}

// ── STREET AUTOCOMPLETE ──
var _streetList = null;

function streetAutocomplete(val) {
  var box = document.getElementById('streetSuggestions');
  if (!box) return;

  if (!val || val.length < 2) {
    box.style.display = 'none';
    return;
  }

  // Load street list once
  if (!_streetList) {
    fetch('/api/streets')
      .then(function(r) { return r.json(); })
      .then(function(data) {
        _streetList = data;
        streetAutocomplete(val);
      });
    return;
  }

  var query = val.toLowerCase();
  var matches = _streetList.filter(function(s) {
    return s.toLowerCase().indexOf(query) !== -1;
  }).slice(0, 8);

  if (matches.length === 0) {
    box.style.display = 'none';
    return;
  }

  box.innerHTML = matches.map(function(s) {
    return '<div style="padding:8px 12px; cursor:pointer; font-size:14px; border-bottom:1px solid var(--border, #334155);" '
      + 'onmouseover="this.style.background=\'rgba(255,255,255,0.1)\'" onmouseout="this.style.background=\'transparent\'" '
      + 'onmousedown="selectStreet(this)" data-street="' + s + '">'
      + s.replace(new RegExp('(' + query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ')', 'gi'), '<strong>$1</strong>')
      + '</div>';
  }).join('');
  box.style.display = 'block';
}

function selectStreet(el) {
  var input = document.getElementById('issueLocation');
  if (input) input.value = el.dataset.street;
  var box = document.getElementById('streetSuggestions');
  if (box) box.style.display = 'none';
}

// Close suggestions on outside click
document.addEventListener('click', function(e) {
  var box = document.getElementById('streetSuggestions');
  if (box && !box.contains(e.target) && e.target.id !== 'issueLocation') {
    box.style.display = 'none';
  }
});

// ── DISTRICT AUTO-DETECT (registration) ──
function checkDistrict() {
  const streetInput = document.getElementById('addressStreet');
  const districtHint = document.getElementById('districtHint');
  const districtSelect = document.getElementById('districtSelect');

  if (!streetInput || !districtHint) return;

  const street = streetInput.value.trim();
  if (street.length < 3) {
    districtHint.textContent = '';
    return;
  }

  fetch('/api/check-district?' + new URLSearchParams({ street: street }))
    .then(r => r.json())
    .then(data => {
      if (data.district) {
        var rep = data.representative_name ? ` — ${data.representative_name}` : '';
        districtHint.textContent = `📍 Felismert körzet: ${String(data.district).padStart(2, '0')}.${rep}`;
        districtHint.className = 'field-hint success';
        if (districtSelect) districtSelect.value = data.district;
      } else {
        districtHint.textContent = 'Nem sikerült automatikusan felismerni a körzetet — válaszd ki kézzel.';
        districtHint.className = 'field-hint';
      }
    })
    .catch(() => {});
}

// ── COOKIE CONSENT ──
// A consent verzió. Ha az Adatvédelmi tájékoztató érdemben módosul, emeld eggyel:
// a bannert újra megmutatja minden meglévő felhasználónak.
var COOKIE_CONSENT_VERSION = 1;
var COOKIE_CONSENT_KEY = 'zh_consent';

function acceptCookies(level) {
  var consent = {
    version: COOKIE_CONSENT_VERSION,
    level: level === 'all' ? 'all' : 'necessary',
    timestamp: new Date().toISOString()
  };
  try {
    localStorage.setItem(COOKIE_CONSENT_KEY, JSON.stringify(consent));
    localStorage.removeItem('zh_cookies'); // régi kulcs takarítása
  } catch (e) {}
  var el = document.getElementById('cookieBanner');
  if (el) el.style.display = 'none';
}

function hasValidConsent() {
  try {
    var raw = localStorage.getItem(COOKIE_CONSENT_KEY);
    if (!raw) return false;
    var c = JSON.parse(raw);
    return c && c.version === COOKIE_CONSENT_VERSION;
  } catch (e) {
    return false;
  }
}

function resetCookieConsent() {
  try {
    localStorage.removeItem(COOKIE_CONSENT_KEY);
    localStorage.removeItem('zh_cookies');
  } catch (e) {}
  var el = document.getElementById('cookieBanner');
  if (el) el.style.display = '';
}

// ── DISCLAIMER ──
function dismissDisclaimer() {
  sessionStorage.setItem('zh_disclaimer', '1');
  var el = document.getElementById('disclaimerBanner');
  if (el) el.style.display = 'none';
}

// Show/hide banners on load
document.addEventListener('DOMContentLoaded', function() {
  var cookie = document.getElementById('cookieBanner');
  if (cookie && hasValidConsent()) cookie.style.display = 'none';

  var disc = document.getElementById('disclaimerBanner');
  if (disc && sessionStorage.getItem('zh_disclaimer')) disc.style.display = 'none';

  initPasswordToggles();
  initBirthDateMax();
});

// ── ISSUE WITHDRAW / RESTORE (owner only) ──
function _postIssueAction(issueId, action, confirmMsg) {
  if (!confirm(confirmMsg)) return;
  var csrfEl = document.querySelector('meta[name="csrf-token"]');
  var csrf = csrfEl ? csrfEl.getAttribute('content') : '';
  fetch('/issue/' + issueId + '/' + action, {
    method: 'POST',
    headers: { 'X-CSRFToken': csrf }
  })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      if (data.ok) {
        location.reload();
      } else {
        showToast('⚠ ' + (data.error || 'Hiba történt.'), true);
      }
    })
    .catch(function() { showToast('⚠ Hiba történt.', true); });
}

function withdrawIssue(issueId) {
  _postIssueAction(issueId, 'withdraw',
    'Biztosan visszavonod a bejelentést? A szavazatok és hozzászólások megmaradnak, de másoknak nem lesz látható. Később visszaállíthatod.');
}

function restoreIssue(issueId) {
  _postIssueAction(issueId, 'restore',
    'Visszaállítod a bejelentést? Újra publikus lesz.');
}

// ── SOCIAL SHARE (issue detail) ──
function _getShareUrl(btn) {
  var row = btn.closest('.share-row');
  return row ? row.dataset.shareUrl : location.href;
}

function shareFacebook(btn) {
  var url = _getShareUrl(btn);
  window.open(
    'https://www.facebook.com/sharer/sharer.php?u=' + encodeURIComponent(url),
    '_blank',
    'noopener,width=600,height=500'
  );
}

function shareMessenger(btn) {
  var url = _getShareUrl(btn);
  // Mobilon az fb-messenger:// scheme nyitja a Messenger appot közvetlenül.
  if (/Mobi|Android|iPhone|iPad/i.test(navigator.userAgent)) {
    window.location.href = 'fb-messenger://share/?link=' + encodeURIComponent(url);
    return;
  }
  // Desktopon: Web Share API (ha elérhető), különben clipboard fallback.
  if (navigator.share) {
    navigator.share({ url: url }).catch(function() {});
    return;
  }
  copyShareLink(btn);
}

function copyShareLink(btn) {
  var url = _getShareUrl(btn);
  if (navigator.clipboard && navigator.clipboard.writeText) {
    navigator.clipboard.writeText(url)
      .then(function() { showToast('✓ Link vágólapra másolva'); })
      .catch(function() { showToast('⚠ Másolás sikertelen', true); });
  } else {
    // Fallback régi böngészőkre
    var ta = document.createElement('textarea');
    ta.value = url;
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); showToast('✓ Link vágólapra másolva'); }
    catch (e) { showToast('⚠ Másolás sikertelen', true); }
    document.body.removeChild(ta);
  }
}

// ── PROFANITY REAL-TIME CHECK ──
// Debounce-olt POST /api/check-text a bejelentés/hozzászólás form-okhoz.
// Ha a szöveg trágár, warning elem látható lesz.
var _profanityTimer = null;
function profanityCheck(text, warnElId) {
  clearTimeout(_profanityTimer);
  _profanityTimer = setTimeout(function() {
    var warnEl = document.getElementById(warnElId);
    if (!warnEl) return;
    if (!text || text.trim().length < 3) {
      warnEl.style.display = 'none';
      return;
    }
    var csrfEl = document.querySelector('meta[name="csrf-token"]');
    var csrf = csrfEl ? csrfEl.getAttribute('content') : '';
    fetch('/api/check-text', {
      method: 'POST',
      headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
      body: JSON.stringify({text: text})
    })
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.has_profanity) {
          warnEl.textContent = '⚠ A beírt szöveg trágár kifejezést tartalmaz — beküldéskor a bejelentés elutasításra kerül. Kérjük, fogalmazd át tárgyilagosan.';
          warnEl.style.display = 'block';
        } else {
          warnEl.style.display = 'none';
        }
      })
      .catch(function() {});
  }, 400);
}

// Prevent picking future dates on the registration birthdate field
function initBirthDateMax() {
  var el = document.getElementById('birthDate');
  if (!el) return;
  var today = new Date();
  var pad = function(n) { return n < 10 ? '0' + n : '' + n; };
  el.max = today.getFullYear() + '-' + pad(today.getMonth() + 1) + '-' + pad(today.getDate());
}

// ── PASSWORD VISIBILITY TOGGLE ──
function initPasswordToggles() {
  var buttons = document.querySelectorAll('[data-pw-toggle]');
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener('click', function(e) {
      e.preventDefault();
      var wrap = this.closest('.pw-wrap');
      if (!wrap) return;
      var input = wrap.querySelector('input');
      if (!input) return;
      var shown = this.getAttribute('data-shown') === '1';
      input.type = shown ? 'password' : 'text';
      this.setAttribute('data-shown', shown ? '0' : '1');
      this.setAttribute('aria-label', shown ? 'Jelszó megjelenítése' : 'Jelszó elrejtése');
      this.setAttribute('aria-pressed', shown ? 'false' : 'true');
    });
  }
}

// ── MOBILE MENU ──
function toggleMobileMenu() {
  var links = document.querySelector('.nav-links');
  if (links) links.classList.toggle('mobile-open');
}

// Close mobile menu on link click
document.addEventListener('click', function(e) {
  if (e.target.closest('.nav-links a')) {
    var links = document.querySelector('.nav-links');
    if (links) links.classList.remove('mobile-open');
  }
});

// ── PHOTO PREVIEW ──
function previewPhotos(input) {
  var preview = document.getElementById('photoPreview');
  var placeholder = document.getElementById('photoPlaceholder');
  if (!preview) return;

  preview.innerHTML = '';
  if (input.files && input.files.length > 0) {
    preview.style.display = 'flex';
    if (placeholder) placeholder.textContent = input.files.length + ' fotó kiválasztva';

    for (var i = 0; i < input.files.length; i++) {
      (function(file) {
        var wrap = document.createElement('div');
        wrap.style.cssText = 'position:relative; width:80px; height:80px; border-radius:8px; overflow:hidden; border:1px solid #ddd;';

        if (file.type.startsWith('image/') && !file.name.match(/\.(heic|heif)$/i)) {
          var reader = new FileReader();
          reader.onload = function(e) {
            var img = document.createElement('img');
            img.src = e.target.result;
            img.style.cssText = 'width:100%; height:100%; object-fit:cover;';
            wrap.appendChild(img);
          };
          reader.readAsDataURL(file);
        } else {
          wrap.innerHTML = '<div style="width:100%;height:100%;display:flex;align-items:center;justify-content:center;background:#f5f5f5;font-size:12px;color:#888;text-align:center;padding:4px;">📸<br>' + file.name.split('.').pop().toUpperCase() + '</div>';
        }

        preview.appendChild(wrap);
      })(input.files[i]);
    }
  } else {
    preview.style.display = 'none';
    if (placeholder) placeholder.textContent = 'Húzd ide a fotót vagy kattints a tallózáshoz';
  }
}
