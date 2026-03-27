/* ==============================================
   Zalaegerszeg Hangja — Frontend JavaScript
   ============================================== */

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

  fetch('/issue/new', {
    method: 'POST',
    headers: { 'X-CSRFToken': getCsrf() },
    body: formData,
  })
    .then(r => r.json())
    .then(data => {
      if (data.ok) {
        closeForm();
        showToast('✓ Bejelentés elküldve — megjelenik a körzeti listán');
        setTimeout(() => window.location.reload(), 1500);
      } else if (data.duplicate) {
        // Duplicate warning — ask user to confirm
        if (btn) { btn.disabled = false; btn.textContent = 'Bejelentés küldése →'; }
        showDuplicateWarning(data.duplicate_id, data.duplicate_title);
      } else {
        if (btn) { btn.disabled = false; btn.textContent = 'Bejelentés küldése →'; }
        showToast('⚠ ' + (data.error || 'Hiba történt a küldés során.'), true);
      }
    })
    .catch(() => {
      if (btn) { btn.disabled = false; btn.textContent = 'Bejelentés küldése →'; }
      alert('Hiba történt a küldés során.');
    });
}

function showDuplicateWarning(dupId, dupTitle) {
  // Remove existing warning if any
  var existing = document.getElementById('dupWarning');
  if (existing) existing.remove();

  var warning = document.createElement('div');
  warning.id = 'dupWarning';
  warning.style.cssText = 'background:#fff3cd; border:1.5px solid #f0c040; border-radius:8px; padding:16px; margin-bottom:1rem;';
  warning.innerHTML =
    '<div style="font-weight:600; margin-bottom:6px;">🤖 Hasonló bejelentés már létezik:</div>' +
    '<div style="font-size:14px; margin-bottom:12px;">„<a href="/issue/' + dupId + '" target="_blank" style="color:#1B4F8A; font-weight:600;">' +
    dupTitle + '</a>"</div>' +
    '<div style="font-size:13px; color:#666; margin-bottom:12px;">Ha ugyanarról a problémáról van szó, szavazz a meglévőre! Ha mégis új bejelentést szeretnél, kattints a küldésre.</div>' +
    '<div style="display:flex; gap:8px;">' +
    '<button onclick="window.location.href=\'/issue/' + dupId + '\'" style="padding:8px 16px; border:1.5px solid #1B4F8A; background:white; color:#1B4F8A; border-radius:6px; cursor:pointer; font-size:13px; font-weight:600;">Meglévőre szavazok ↑</button>' +
    '<button onclick="submitIssue(null, true)" style="padding:8px 16px; border:none; background:#95a5a6; color:white; border-radius:6px; cursor:pointer; font-size:13px;">Mégis küldöm →</button>' +
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
        districtHint.textContent = `📍 Felismert körzet: ${String(data.district).padStart(2, '0')}. körzet — ${data.name}`;
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
function acceptCookies() {
  localStorage.setItem('zh_cookies', '1');
  var el = document.getElementById('cookieBanner');
  if (el) el.style.display = 'none';
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
  if (cookie && localStorage.getItem('zh_cookies')) cookie.style.display = 'none';

  var disc = document.getElementById('disclaimerBanner');
  if (disc && sessionStorage.getItem('zh_disclaimer')) disc.style.display = 'none';
});

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
