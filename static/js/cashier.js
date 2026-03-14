'use strict';

/**
 * Octos — Cashier Portal
 *
 * API:
 *   GET  /api/v1/jobs/cashier/queue/          — PENDING_PAYMENT jobs for branch
 *   POST /api/v1/jobs/<id>/cashier/confirm/   — { deposit_percentage, notes }
 *   GET  /api/v1/organization/me/             — branch/user context
 */

const Cashier = (() => {

  // ── State ──────────────────────────────────────────────────
  let queue          = [];
  let pollTimer      = null;
  let activeJob      = null;   // job object currently in confirm modal
  let selectedDeposit = 100;   // default to full payment

  const POLL_INTERVAL = 8000;  // 8 seconds

  // ── Bootstrap ──────────────────────────────────────────────
  async function init() {
    Auth.guard();
    await loadContext();
    await loadQueue();
    _startPolling();
  }

  // ── Context ────────────────────────────────────────────────
  async function loadContext() {
    try {
      const res = await Auth.fetch('/api/v1/organization/me/');
      if (!res.ok) return;
      const data = await res.json();

      const user   = data.user   || {};
      const branch = data.branch || {};

      document.getElementById('cashier-branch-name').textContent = branch.name || '—';
      document.getElementById('cashier-user-name').textContent   = user.full_name || user.email || '—';

      const initials = (user.full_name || '')
        .split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() || '??';
      document.getElementById('cashier-user-initials').textContent = initials;

    } catch (e) {
      console.warn('loadContext failed:', e);
    }
  }

  // ── Queue ──────────────────────────────────────────────────
  async function loadQueue() {
    try {
      const res = await Auth.fetch('/api/v1/jobs/cashier/queue/');
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      queue = data.results || data;
      _renderQueue();
    } catch (e) {
      console.error('loadQueue failed:', e);
      _renderQueueError();
    }
  }

  function _renderQueue() {
    const list = document.getElementById('queue-list');

    // Update count
    document.getElementById('queue-count-num').textContent = queue.length;

    if (!queue.length) {
      list.innerHTML = `
        <div class="queue-empty">
          <div class="queue-empty-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="#ccc" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
          </div>
          <div class="queue-empty-title">Queue is clear</div>
          <div class="queue-empty-sub">No jobs waiting for payment right now</div>
        </div>`;
      return;
    }

    list.innerHTML = queue.map((job, i) => {
      const cost = job.estimated_cost
        ? `GHS ${parseFloat(job.estimated_cost).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
        : '—';

      const typeClass = job.job_type || '';
      const attendant = _esc(job.intake_by_name || 'Attendant');
      const customer  = _esc(job.customer_name  || 'Walk-in');
      const timeAgo   = _timeAgo(job.created_at);

      return `
        <div class="queue-card" onclick="Cashier.openConfirm(${job.id})">
          <div class="queue-card-index">${String(i + 1).padStart(2, '0')}</div>
          <div class="queue-card-info">
            <div class="queue-card-title">${_esc(job.title || '—')}</div>
            <div class="queue-card-meta">
              <span class="queue-card-ref">${_esc(job.job_number || '#' + job.id)}</span>
              <span class="type-pill ${typeClass}">${typeClass}</span>
              <span class="queue-card-attendant">by ${attendant} · ${timeAgo}</span>
            </div>
          </div>
          <div class="queue-card-cost">
            <div class="cost-amount">${cost}</div>
            <div class="cost-label">${_esc(customer)}</div>
          </div>
          <button class="confirm-btn" onclick="event.stopPropagation();Cashier.openConfirm(${job.id})">
            Collect Payment
          </button>
        </div>`;
    }).join('');
  }

  function _renderQueueError() {
    document.getElementById('queue-list').innerHTML = `
      <div class="queue-empty">
        <div class="queue-empty-title" style="color:#cc3300;">Failed to load queue</div>
        <div class="queue-empty-sub">Check your connection and refresh</div>
      </div>`;
  }

  // ── Polling ────────────────────────────────────────────────
  function _startPolling() {
    pollTimer = setInterval(loadQueue, POLL_INTERVAL);
  }

  // ── Confirm modal ──────────────────────────────────────────
  function openConfirm(jobId) {
    activeJob = queue.find(j => j.id === jobId);
    if (!activeJob) return;

    // Reset to 100% default
    selectDeposit(100);

    // Populate modal
    document.getElementById('confirm-job-ref').textContent =
      activeJob.job_number || '#' + activeJob.id;

    document.getElementById('confirm-job-name').textContent =
      activeJob.title || '—';

    document.getElementById('confirm-attendant').textContent =
      activeJob.intake_by_name || '—';

    document.getElementById('confirm-type').textContent =
      activeJob.job_type || '—';

    document.getElementById('confirm-customer').textContent =
      activeJob.customer_name || 'Walk-in';

    const cost = activeJob.estimated_cost
      ? `GHS ${parseFloat(activeJob.estimated_cost).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
      : '—';
    document.getElementById('confirm-est-cost').textContent = cost;

    document.getElementById('confirm-notes').value = '';
    document.getElementById('confirm-submit-btn').disabled = false;
    document.getElementById('confirm-submit-btn').textContent = '✓ Confirm Payment';

    _updateAmountDue();

    document.getElementById('confirm-overlay').classList.add('open');
  }

  function closeConfirm() {
    document.getElementById('confirm-overlay').classList.remove('open');
    activeJob = null;
  }

  function selectDeposit(pct) {
    selectedDeposit = pct;

    // Update visual selection
    document.getElementById('opt-100').classList.toggle('selected', pct === 100);
    document.getElementById('opt-70').classList.toggle('selected', pct === 70);

    _updateAmountDue();
  }

  function _updateAmountDue() {
    const el = document.getElementById('confirm-amount-due');
    if (!activeJob || !activeJob.estimated_cost) {
      el.textContent = '—';
      return;
    }
    const due = parseFloat(activeJob.estimated_cost) * selectedDeposit / 100;
    el.textContent = `GHS ${due.toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
  }

  // ── Confirm payment ────────────────────────────────────────
  async function confirmPayment() {
    if (!activeJob) return;

    const notes = document.getElementById('confirm-notes').value.trim();
    const btn   = document.getElementById('confirm-submit-btn');

    btn.disabled    = true;
    btn.textContent = 'Processing…';

    try {
      const res = await Auth.fetch(`/api/v1/jobs/${activeJob.id}/cashier/confirm/`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({
          deposit_percentage : selectedDeposit,
          notes,
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Payment confirmation failed.', 'error');
        return;
      }

      const result  = await res.json();
      const jobRef  = result.job_number || '#' + activeJob.id;
      const paidStr = result.amount_paid
        ? `GHS ${parseFloat(result.amount_paid).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
        : '';

      _toast(`${jobRef} — payment confirmed. ${paidStr}`, 'success');
      closeConfirm();

      // Immediately refresh queue
      await loadQueue();

    } catch (e) {
      _toast('Network error. Please try again.', 'error');
    } finally {
      btn.disabled    = false;
      btn.textContent = '✓ Confirm Payment';
    }
  }

  // ── Toast ──────────────────────────────────────────────────
  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    const el        = document.createElement('div');
    el.className    = `toast ${type}`;
    el.textContent  = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  // ── Helpers ────────────────────────────────────────────────
  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _timeAgo(isoStr) {
    if (!isoStr) return '';
    const diff = Math.floor((Date.now() - new Date(isoStr)) / 1000);
    if (diff < 60)   return `${diff}s ago`;
    if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
    return `${Math.floor(diff / 3600)}h ago`;
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    init,
    openConfirm,
    closeConfirm,
    selectDeposit,
    confirmPayment,
  };

})();

document.addEventListener('DOMContentLoaded', Cashier.init);