'use strict';

const BeltManager = (() => {

  let _rejectCloseId = null;

  // ── Boot ──────────────────────────────────────────────────
  async function init() {
    await Auth.guard(['BELT_MANAGER', 'SUPER_ADMIN']);
    await _loadContext();
    await _loadPending();
  }

  async function _loadContext() {
    try {
      const res = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const user = await res.json();
      const name = user.full_name || user.email || '—';
      const ini  = name.split(' ').slice(0,2).map(w => w[0]?.toUpperCase() || '').join('');
      _set('bm-user-name', name);
      _set('bm-avatar',    ini);
    } catch { /* silent */ }
  }

  // ── Pane switching ────────────────────────────────────────
  function switchPane(pane) {
    document.querySelectorAll('.bm-sidebar-item').forEach(el => {
      el.classList.toggle('active', el.dataset.pane === pane);
    });
    document.getElementById('pane-pending').style.display  = pane === 'pending'  ? '' : 'none';
    document.getElementById('pane-history').style.display  = pane === 'history'  ? '' : 'none';

    if (pane === 'pending') _loadPending();
    if (pane === 'history') _loadHistory();
  }

  // ── Pending endorsements ──────────────────────────────────
  async function _loadPending() {
    const container = document.getElementById('pending-content');
    if (!container) return;
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    try {
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/pending/');
      if (!res.ok) throw new Error();
      const data = await res.json();

      // Update badge
      const badge = document.getElementById('pending-badge');
      if (badge) {
        badge.textContent   = data.length;
        badge.style.display = data.length ? 'flex' : 'none';
      }

      if (!data.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"
              viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1" style="opacity:0.3;margin-bottom:16px;display:block;margin:0 auto 16px;">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">
              All caught up
            </div>
            <div style="font-size:13px;">No monthly closes awaiting endorsement.</div>
          </div>`;
        return;
      }

      container.innerHTML = data.map(c => _renderPendingItem(c)).join('');

    } catch {
      container.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">
        Could not load pending submissions.</div>`;
    }
  }

  function _renderPendingItem(c) {
    const monthNames = ['January','February','March','April','May','June',
      'July','August','September','October','November','December'];
    const monthName = monthNames[(c.month || 1) - 1];
    const submittedAt = c.submitted_at
      ? new Date(c.submitted_at).toLocaleDateString('en-GB',
          {day:'numeric', month:'short', year:'numeric', hour:'2-digit', minute:'2-digit'})
      : '—';

    return `
      <div class="pending-close-item">

        <!-- Header -->
        <div class="pending-close-header">
          <div>
            <div style="font-size:15px;font-weight:700;color:var(--text);">
              ${c.branch} — ${monthName} ${c.year}
            </div>
            <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
              Submitted by ${c.submitted_by} · ${submittedAt}
            </div>
          </div>
          <span style="padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;
            background:var(--amber-bg);color:var(--amber-text);">
            Awaiting Endorsement
          </span>
        </div>

        <!-- Summary -->
        <div class="pending-close-body">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:12px;">
            <div>
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">
                Total Collected</div>
              <div style="font-size:16px;font-weight:800;color:var(--text);
                font-family:'JetBrains Mono',monospace;">
                GHS ${parseFloat(c.total_collected || 0).toLocaleString('en-GH',
                  {minimumFractionDigits:2})}</div>
            </div>
            <div>
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">
                Total Jobs</div>
              <div style="font-size:16px;font-weight:800;color:var(--text);">
                ${c.total_jobs}</div>
            </div>
            <div>
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">
                Branch Code</div>
              <div style="font-size:14px;font-weight:700;color:var(--text);
                font-family:'JetBrains Mono',monospace;">${c.branch_code}</div>
            </div>
          </div>

          ${c.bm_notes ? `
            <div style="background:var(--bg);border:1px solid var(--border);
              border-radius:var(--radius-sm);padding:10px 14px;font-size:13px;
              color:var(--text-2);">
              <span style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;display:block;
                margin-bottom:4px;">BM Notes</span>
              ${c.bm_notes}
            </div>` : ''}
        </div>

        <!-- Belt Manager notes + actions -->
        <div class="pending-close-actions" style="flex-direction:column;gap:10px;">
          <textarea id="belt-notes-${c.id}" rows="2"
            placeholder="Add endorsement notes (optional)…"
            style="width:100%;padding:8px 12px;border:1px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:12px;resize:none;box-sizing:border-box;
              font-family:'DM Sans',sans-serif;"></textarea>
          <div style="display:flex;gap:8px;justify-content:flex-end;">
            <button class="btn-reject" onclick="BeltManager.openRejectModal(${c.id})">
              Reject
            </button>
            <button class="btn-endorse" onclick="BeltManager.endorse(${c.id})">
              ✓ Endorse & Finalise
            </button>
          </div>
        </div>

      </div>`;
  }

  // ── Endorse ───────────────────────────────────────────────
  async function endorse(id) {
    const notes = document.getElementById(`belt-notes-${id}`)?.value.trim() || '';
    const btn   = document.querySelector(`[onclick="BeltManager.endorse(${id})"]`);

    if (btn) { btn.disabled = true; btn.textContent = 'Endorsing…'; }

    try {
      const res = await Auth.fetch(`/api/v1/finance/monthly-close/${id}/endorse/`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ belt_notes: notes }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Endorsement failed.', 'error');
        if (btn) { btn.disabled = false; btn.textContent = '✓ Endorse & Finalise'; }
        return;
      }

      _toast('Monthly close endorsed and finalised.', 'success');
      await _loadPending();

    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = '✓ Endorse & Finalise'; }
    }
  }

  // ── Reject ────────────────────────────────────────────────
  function openRejectModal(id) {
    _rejectCloseId = id;
    document.getElementById('reject-reason').value        = '';
    document.getElementById('reject-error').style.display = 'none';
    document.getElementById('reject-modal-overlay').style.display = 'flex';
    setTimeout(() => document.getElementById('reject-reason')?.focus(), 100);
  }

  function closeRejectModal() {
    document.getElementById('reject-modal-overlay').style.display = 'none';
    _rejectCloseId = null;
  }

  async function confirmReject() {
    const reason  = document.getElementById('reject-reason')?.value.trim();
    const errorEl = document.getElementById('reject-error');
    errorEl.style.display = 'none';

    if (!reason) {
      errorEl.textContent   = 'Rejection reason is required.';
      errorEl.style.display = 'block';
      return;
    }

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/monthly-close/${_rejectCloseId}/reject/`, {
          method : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body   : JSON.stringify({ reason }),
        }
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent   = err.detail || 'Rejection failed.';
        errorEl.style.display = 'block';
        return;
      }

      closeRejectModal();
      _toast('Monthly close rejected. Branch Manager notified.', 'success');
      await _loadPending();

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
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/pending/');
      if (!res.ok) throw new Error();

      // For now show all — in future add a history endpoint
      container.innerHTML = `
        <div style="text-align:center;padding:48px;color:var(--text-3);font-size:13px;">
          Full endorsement history coming soon.
        </div>`;
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
    endorse,
    openRejectModal,
    closeRejectModal,
    confirmReject,
  };

})();

document.addEventListener('DOMContentLoaded', BeltManager.init);