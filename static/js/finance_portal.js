'use strict';

const FinancePortal = (() => {

  let _clarifyCloseId = null;
  let _clearCloseId   = null;

  // ── Boot ──────────────────────────────────────────────────
  async function init() {
    await Auth.guard(['FINANCE', 'SUPER_ADMIN']);
    await _loadContext();
    await _loadQueue();
  }

  async function _loadContext() {
    try {
      const res = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const user = await res.json();
      const name = user.full_name || user.email || '—';
      const ini  = name.split(' ').slice(0,2).map(w => w[0]?.toUpperCase() || '').join('');
      _set('fin-user-name', name);
      _set('fin-avatar',    ini);
    } catch { /* silent */ }
  }

  // ── Pane switching ────────────────────────────────────────
  function switchPane(pane) {
    document.querySelectorAll('.sidebar-item').forEach(el => {
      el.classList.toggle('active', el.dataset.pane === pane);
    });
    document.querySelectorAll('.pane').forEach(el => {
      el.classList.toggle('active', el.id === `pane-${pane}`);
    });

    if (pane === 'queue')   _loadQueue();
    if (pane === 'history') _loadHistory();
  }

  // ── Queue ─────────────────────────────────────────────────
  async function _loadQueue() {
    const container = document.getElementById('queue-content');
    if (!container) return;
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    try {
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/my-queue/');
      if (!res.ok) throw new Error();
      const data = await res.json();

      const badge = document.getElementById('queue-badge');
      if (badge) {
        badge.textContent   = data.length;
        badge.style.display = data.length ? 'flex' : 'none';
      }

      if (!data.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"
              viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1" style="opacity:0.3;margin-bottom:16px;
              display:block;margin:0 auto 16px;">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            <div style="font-size:14px;font-weight:600;color:var(--text);
              margin-bottom:4px;">All caught up</div>
            <div style="font-size:13px;">No monthly closes in your queue.</div>
          </div>`;
        return;
      }

      container.innerHTML = data.map(c => _renderQueueItem(c)).join('');

    } catch {
      container.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">
        Could not load your queue.</div>`;
    }
  }

  function _renderQueueItem(c) {
    const monthNames = ['January','February','March','April','May','June',
      'July','August','September','October','November','December'];
    const monthName    = monthNames[(c.month || 1) - 1];
    const submittedAt  = c.submitted_at
      ? new Date(c.submitted_at).toLocaleDateString('en-GB',
          {day:'numeric', month:'short', year:'numeric',
           hour:'2-digit', minute:'2-digit'})
      : '—';

    const isResubmitted = c.status === 'RESUBMITTED';

    // Risk badge
    const score     = c.risk_score ?? null;
    const riskBadge = score === null ? '' : (() => {
      let cls   = 'low';
      let label = `Risk ${score}`;
      if (score >= 40) cls = 'critical';
      else if (score >= 25) cls = 'high';
      else if (score >= 10) cls = 'medium';
      return `<span class="risk-badge ${cls}">${label}</span>`;
    })();

    // Status pill
    const statusLabel = isResubmitted
      ? '<span style="padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;background:var(--amber-bg);color:var(--amber-text);">Resubmitted</span>'
      : '<span style="padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;background:var(--blue-bg,#dbeafe);color:var(--blue-text,#1e40af);">Reviewing</span>';

    // Resubmitted banner + clarification thread
    const resubBanner = isResubmitted ? `
      <div class="resubmitted-banner">
        ⚠ Branch Manager has responded to your clarification request.
      </div>
      ${c.clarification_request ? `
        <div class="notes-box" style="margin-bottom:8px;">
          <div class="notes-box-label">Your Clarification Request</div>
          ${_esc(c.clarification_request)}
        </div>` : ''}
      ${c.clarification_response ? `
        <div class="notes-box" style="border-color:var(--amber-text);margin-bottom:8px;">
          <div class="notes-box-label" style="color:var(--amber-text);">
            BM Response
          </div>
          ${_esc(c.clarification_response)}
        </div>` : ''}
    ` : '';

    return `
      <div class="close-item">

        <!-- Header -->
        <div class="close-item-header">
          <div>
            <div style="font-size:15px;font-weight:700;color:var(--text);">
              ${_esc(c.branch)} — ${monthName} ${c.year}
            </div>
            <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
              Submitted by ${_esc(c.submitted_by)} · ${submittedAt}
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;">
            ${riskBadge}
            ${statusLabel}
          </div>
        </div>

        <!-- Body -->
        <div class="close-item-body">

          ${resubBanner}

          <div class="stat-grid">
            <div class="stat-cell">
              <div class="stat-label">Total Collected</div>
              <div class="stat-value">GHS ${parseFloat(c.total_collected || 0)
                .toLocaleString('en-GH', {minimumFractionDigits:2})}</div>
            </div>
            <div class="stat-cell">
              <div class="stat-label">Total Jobs</div>
              <div class="stat-value" style="font-family:inherit;">${c.total_jobs}</div>
            </div>
            <div class="stat-cell">
              <div class="stat-label">Branch Code</div>
              <div class="stat-value">${_esc(c.branch_code)}</div>
            </div>
          </div>

          ${c.bm_notes ? `
            <div class="notes-box">
              <div class="notes-box-label">BM Notes</div>
              ${_esc(c.bm_notes)}
            </div>` : ''}

        </div>

        <!-- Actions -->
        <div class="close-item-actions">
          <textarea id="fin-notes-${c.id}" rows="2"
            placeholder="Finance notes (optional — saved on clear)…"
            style="width:100%;padding:8px 12px;border:1px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:12px;resize:none;box-sizing:border-box;
              font-family:'DM Sans',sans-serif;"></textarea>
          <div class="close-item-action-row">
            <button class="btn-clarify"
              onclick="FinancePortal.openClarifyModal(${c.id})">
              Request Clarification
            </button>
            <button class="btn-clear"
              onclick="FinancePortal.openClearModal(${c.id})">
              ✓ Clear
            </button>
          </div>
        </div>

      </div>`;
  }

  // ── Clarification modal ───────────────────────────────────
  function openClarifyModal(id) {
    _clarifyCloseId = id;
    document.getElementById('clarify-text').value         = '';
    document.getElementById('clarify-error').style.display = 'none';
    document.getElementById('clarify-modal-overlay').style.display = 'flex';
    setTimeout(() => document.getElementById('clarify-text')?.focus(), 100);
  }

  function closeClarifyModal() {
    document.getElementById('clarify-modal-overlay').style.display = 'none';
    _clarifyCloseId = null;
  }

  async function confirmClarify() {
    const text    = document.getElementById('clarify-text')?.value.trim();
    const errorEl = document.getElementById('clarify-error');
    errorEl.style.display = 'none';

    if (!text) {
      errorEl.textContent   = 'Clarification request cannot be empty.';
      errorEl.style.display = 'block';
      return;
    }

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/monthly-close/${_clarifyCloseId}/request-clarification/`, {
          method : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body   : JSON.stringify({ clarification: text }),
        }
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent   = err.detail || 'Request failed.';
        errorEl.style.display = 'block';
        return;
      }

      closeClarifyModal();
      _toast('Clarification requested. Branch Manager has 24 hours to respond.', 'success');
      await _loadQueue();

    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    }
  }

  // ── Clear modal ───────────────────────────────────────────
  function openClearModal(id) {
    _clearCloseId = id;
    // Pre-fill notes from the inline textarea if the user typed there
    const inlineNotes = document.getElementById(`fin-notes-${id}`)?.value.trim() || '';
    document.getElementById('clear-notes').value         = inlineNotes;
    document.getElementById('clear-error').style.display = 'none';
    document.getElementById('clear-modal-overlay').style.display = 'flex';
  }

  function closeClearModal() {
    document.getElementById('clear-modal-overlay').style.display = 'none';
    _clearCloseId = null;
  }

  async function confirmClear() {
    const notes   = document.getElementById('clear-notes')?.value.trim() || '';
    const errorEl = document.getElementById('clear-error');
    errorEl.style.display = 'none';

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/monthly-close/${_clearCloseId}/clear/`, {
          method : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body   : JSON.stringify({ finance_notes: notes }),
        }
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent   = err.detail || 'Clear failed.';
        errorEl.style.display = 'block';
        return;
      }

      closeClearModal();
      _toast('Monthly close cleared. Regional Manager notified.', 'success');
      await _loadQueue();

    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    }
  }

  // ── History ───────────────────────────────────────────────
  async function _loadHistory() {
    const container = document.getElementById('history-content');
    if (!container) return;
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    try {
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/my-history/');
      if (!res.ok) throw new Error();
      const data = await res.json();

      if (!data.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:48px;color:var(--text-3);font-size:13px;">
            No cleared monthly closes yet.
          </div>`;
        return;
      }

      const monthNames = ['January','February','March','April','May','June',
        'July','August','September','October','November','December'];

      container.innerHTML = data.map(c => {
        const monthName  = monthNames[(c.month || 1) - 1];
        const clearedAt  = c.finance_cleared_at
          ? new Date(c.finance_cleared_at).toLocaleDateString('en-GB',
              {day:'numeric', month:'short', year:'numeric'})
          : '—';
        return `
          <div class="history-item">
            <div>
              <div style="font-size:14px;font-weight:700;color:var(--text);">
                ${_esc(c.branch)} — ${monthName} ${c.year}
              </div>
              <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
                Cleared ${clearedAt}
              </div>
            </div>
            <span style="padding:4px 12px;border-radius:20px;font-size:11px;
              font-weight:700;background:var(--green-bg);color:var(--green-text);">
              ${c.status === 'ENDORSED' || c.status === 'LOCKED' ? 'Endorsed' : 'Cleared'}
            </span>
          </div>`;
      }).join('');

    } catch {
      container.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">
        Could not load history.</div>`;
    }
  }

  // ── Helpers ───────────────────────────────────────────────
  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function _esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g,'&amp;')
      .replace(/</g,'&lt;')
      .replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;');
  }

  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el       = document.createElement('div');
    el.className   = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  return {
    init,
    switchPane,
    openClarifyModal,
    closeClarifyModal,
    confirmClarify,
    openClearModal,
    closeClearModal,
    confirmClear,
  };

})();

document.addEventListener('DOMContentLoaded', FinancePortal.init);