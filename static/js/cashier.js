'use strict';

/**
 * Octos — Cashier Portal
 *
 * API:
 *   GET  /api/v1/jobs/cashier/queue/          — PENDING_PAYMENT jobs for branch
 *   POST /api/v1/jobs/<id>/cashier/confirm/   — confirm payment
 *   GET  /api/v1/accounts/me/                 — user/branch context
 *   POST /api/v1/finance/receipts/<id>/send-whatsapp/ — send receipt
 */

const Cashier = (() => {

  // ── State ──────────────────────────────────────────────────
  let queue           = [];
  let pollTimer       = null;
  let activeJob       = null;
  let selectedDeposit = 100;
  let selectedMethod  = 'CASH';
  let lastReceipt     = null;   // result from last confirmed payment

  // Daily running totals (frontend-only, refreshed on each queue load)
  const totals = { CASH: 0, MOMO: 0, POS: 0, count: 0 };

  const POLL_INTERVAL   = 8000;
  const WAIT_AMBER_MINS = 10;
  const WAIT_RED_MINS   = 20;

  // ── Bootstrap ──────────────────────────────────────────────
async function init() {
    Auth.guard();
    await loadContext();
    await loadSummary();
    await loadQueue();
    _startPolling();
  }

  async function loadSummary() {
    try {
      const res = await Auth.fetch('/api/v1/jobs/cashier/summary/');
      if (!res.ok) return;
      const data = await res.json();

      totals.CASH  = parseFloat(data.CASH?.total  || 0);
      totals.MOMO  = parseFloat(data.MOMO?.total  || 0);
      totals.POS   = parseFloat(data.POS?.total   || 0);
      totals.count = data.total?.count || 0;

      _updateSummaryStrip();
    } catch (e) {
      console.warn('loadSummary failed:', e);
    }
  }

  // ── Context ────────────────────────────────────────────────
  async function loadContext() {
    try {
      const res = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const data = await res.json();

      const user   = data.user   || data;
      const branch = data.branch || {};

      document.getElementById('cashier-branch-name').textContent =
        branch.name || '—';
      document.getElementById('cashier-user-name').textContent =
        user.full_name || user.email || '—';

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
    const list  = document.getElementById('queue-list');
    const count = queue.length;

    // Update count badges
    document.getElementById('queue-count-num').textContent        = count;
    document.getElementById('sidebar-queue-count').textContent    = count;
    document.getElementById('sidebar-queue-count').style.display  =
      count > 0 ? 'flex' : 'none';

    if (!count) {
      list.innerHTML = `
        <div class="queue-empty">
          <div class="queue-empty-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22"
              viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
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

      const priority  = job.priority || 'NORMAL';
      const waitClass = _waitClass(job.created_at);
      const waitLabel = _waitLabel(job.created_at);
      const customer  = _esc(job.customer_name || 'Walk-in');
      const attendant = _esc(job.intake_by_name || '—');

      const priorityTag = priority !== 'NORMAL'
        ? `<span class="priority-tag ${priority}">${priority}</span>`
        : '';

      return `
        <div class="queue-card priority-${priority}"
          onclick="Cashier.openConfirm(${job.id})">
          <div class="queue-card-index">${String(i + 1).padStart(2, '0')}</div>
          <div class="queue-card-info">
            <div class="queue-card-title">${_esc(job.title || '—')}</div>
            <div class="queue-card-meta">
              <span class="queue-card-ref">${_esc(job.job_number || '#' + job.id)}</span>
              <span class="type-pill ${job.job_type || ''}">${job.job_type || ''}</span>
              ${priorityTag}
              <span class="queue-card-attendant">by ${attendant}</span>
              <span class="wait-tag ${waitClass}">${waitLabel}</span>
            </div>
          </div>
          <div class="queue-card-right">
            <div>
              <div class="cost-amount">${cost}</div>
              <div class="cost-customer">${customer}</div>
            </div>
            <button class="collect-btn"
              onclick="event.stopPropagation();Cashier.openConfirm(${job.id})">
              Collect Payment
            </button>
          </div>
        </div>`;
    }).join('');
  }

  function _renderQueueError() {
    document.getElementById('queue-list').innerHTML = `
      <div class="queue-empty">
        <div class="queue-empty-title" style="color:#cc3300;">
          Failed to load queue
        </div>
        <div class="queue-empty-sub">Check your connection and refresh</div>
      </div>`;
  }

  // ── Wait time helpers ──────────────────────────────────────
  function _waitMins(isoStr) {
    if (!isoStr) return 0;
    return Math.floor((Date.now() - new Date(isoStr)) / 60000);
  }

  function _waitClass(isoStr) {
    const m = _waitMins(isoStr);
    if (m >= WAIT_RED_MINS)   return 'urgent';
    if (m >= WAIT_AMBER_MINS) return 'amber';
    return 'fresh';
  }

  function _waitLabel(isoStr) {
    const m = _waitMins(isoStr);
    if (m < 1)  return 'just now';
    if (m < 60) return `${m}m ago`;
    return `${Math.floor(m / 60)}h ago`;
  }

  // ── Polling ────────────────────────────────────────────────
  function _startPolling() {
    pollTimer = setInterval(loadQueue, POLL_INTERVAL);
  }

  // ── Confirm modal ──────────────────────────────────────────
  function openConfirm(jobId) {
    activeJob = queue.find(j => j.id === jobId);
    if (!activeJob) return;

    // Reset state
    selectedDeposit = 100;
    selectedMethod  = 'CASH';

    // Populate job summary
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

    // Pre-fill phone if customer has one
    document.getElementById('confirm-phone').value =
      activeJob.customer_phone || '';

    // Reset fields
    document.getElementById('confirm-notes').value = '';
    document.getElementById('momo-ref').value       = '';
    document.getElementById('pos-ref').value        = '';

    // Reset UI state
    selectMethod('CASH');
    selectDeposit(100);

    const btn = document.getElementById('confirm-submit-btn');
    btn.disabled    = false;
    btn.textContent = '✓ Confirm Payment';

    document.getElementById('confirm-overlay').classList.add('open');
  }

  function closeConfirm() {
    document.getElementById('confirm-overlay').classList.remove('open');
    activeJob = null;
  }

  // ── Payment method selection ───────────────────────────────
  function selectMethod(method) {
    selectedMethod = method;

    // Update button states
    ['CASH', 'MOMO', 'POS'].forEach(m => {
      const btn = document.getElementById(`pm-${m.toLowerCase()}`);
      if (btn) btn.classList.toggle('selected', m === method);
    });

    // Show/hide reference fields
    const momoField = document.getElementById('momo-ref-field');
    const posField  = document.getElementById('pos-ref-field');
    if (momoField) momoField.classList.toggle('visible', method === 'MOMO');
    if (posField)  posField.classList.toggle('visible',  method === 'POS');

    // Update amount due box color
    _updateAmountDue();
  }

  // ── Deposit selection ──────────────────────────────────────
  function selectDeposit(pct) {
    selectedDeposit = pct;
    document.getElementById('opt-100').classList.toggle('selected', pct === 100);
    document.getElementById('opt-70').classList.toggle('selected',  pct === 70);
    _updateAmountDue();
  }

  function _updateAmountDue() {
    const box = document.getElementById('amount-due-box');
    const val = document.getElementById('confirm-amount-due');
    const btn = document.getElementById('confirm-submit-btn');

    // Update box color class
    if (box) {
      box.classList.remove('cash', 'momo', 'pos');
      box.classList.add(selectedMethod.toLowerCase());
    }

    // Update confirm button color
    if (btn) {
      btn.classList.remove('cash', 'momo', 'pos');
      btn.classList.add(selectedMethod.toLowerCase());
    }

    if (!activeJob || !activeJob.estimated_cost) {
      if (val) val.textContent = '—';
      return;
    }

    const due = parseFloat(activeJob.estimated_cost) * selectedDeposit / 100;
    if (val) {
      val.textContent = `GHS ${due.toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
    }
  }

  // ── Confirm payment ────────────────────────────────────────
  async function confirmPayment() {
    if (!activeJob) return;

    // Validate references
    if (selectedMethod === 'MOMO') {
      const ref = document.getElementById('momo-ref').value.trim();
      if (!ref) {
        _toast('MoMo reference number is required.', 'error');
        document.getElementById('momo-ref').focus();
        return;
      }
    }

    if (selectedMethod === 'POS') {
      const code = document.getElementById('pos-ref').value.trim();
      if (!code) {
        _toast('POS approval code is required.', 'error');
        document.getElementById('pos-ref').focus();
        return;
      }
    }

    const notes    = document.getElementById('confirm-notes').value.trim();
    const phone    = document.getElementById('confirm-phone').value.trim();
    const momoRef  = document.getElementById('momo-ref').value.trim();
    const posCode  = document.getElementById('pos-ref').value.trim();
    const btn      = document.getElementById('confirm-submit-btn');

    btn.disabled    = true;
    btn.textContent = 'Processing…';

    try {
      const body = {
        deposit_percentage : selectedDeposit,
        payment_method     : selectedMethod,
        notes,
      };

      if (selectedMethod === 'MOMO') body.momo_reference    = momoRef;
      if (selectedMethod === 'POS')  body.pos_approval_code = posCode;
      if (phone)                     body.customer_phone    = phone;

      const res = await Auth.fetch(
        `/api/v1/jobs/${activeJob.id}/cashier/confirm/`, {
          method : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body   : JSON.stringify(body),
        }
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Payment confirmation failed.', 'error');
        return;
      }

      const result = await res.json();
      lastReceipt  = result;

      // Update running totals
      const paid = parseFloat(result.amount_paid || 0);
      if (totals[selectedMethod] !== undefined) {
        totals[selectedMethod] += paid;
      }
      totals.count += 1;
      _updateSummaryStrip();

      closeConfirm();
      await loadQueue();
      _showReceiptModal(result);

    } catch (e) {
      _toast('Network error. Please try again.', 'error');
    } finally {
      btn.disabled    = false;
      btn.textContent = '✓ Confirm Payment';
    }
  }

  // ── Summary strip ──────────────────────────────────────────
  function _updateSummaryStrip() {
    const fmt = n =>
      `GHS ${n.toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;

    document.getElementById('sum-cash').textContent  = fmt(totals.CASH);
    document.getElementById('sum-momo').textContent  = fmt(totals.MOMO);
    document.getElementById('sum-pos').textContent   = fmt(totals.POS);

    const total = totals.CASH + totals.MOMO + totals.POS;
    document.getElementById('sum-total').textContent = fmt(total);
    document.getElementById('sum-total-count').textContent =
      `${totals.count} job${totals.count !== 1 ? 's' : ''} confirmed`;
  }

  // ── Receipt modal ──────────────────────────────────────────
  function _showReceiptModal(result) {
    const fmt = n => n
      ? `GHS ${parseFloat(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
      : 'GHS 0.00';

    document.getElementById('receipt-job-ref').textContent =
      result.job_number || '—';
    document.getElementById('receipt-amount').textContent =
      fmt(result.amount_paid);
    document.getElementById('receipt-balance').textContent =
      fmt(result.balance_due || 0);
    document.getElementById('receipt-method').textContent =
      selectedMethod;
    document.getElementById('receipt-number').textContent =
      result.receipt_number || '—';

    // Disable WhatsApp button if no phone
    const waBtn = document.getElementById('btn-send-whatsapp');
    const phone = document.getElementById('confirm-phone')?.value?.trim() || '';
    if (waBtn) waBtn.disabled = !phone;

    document.getElementById('receipt-overlay').classList.add('open');
  }

  function closeReceipt() {
    document.getElementById('receipt-overlay').classList.remove('open');
    lastReceipt = null;
  }

  async function sendWhatsApp() {
    if (!lastReceipt || !lastReceipt.receipt_id) {
      _toast('Receipt not available for WhatsApp delivery.', 'error');
      return;
    }

    const btn = document.getElementById('btn-send-whatsapp');
    btn.disabled    = true;
    btn.textContent = 'Sending…';

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/receipts/${lastReceipt.receipt_id}/send-whatsapp/`,
        { method: 'POST' }
      );

      if (res.ok) {
        _toast('Receipt sent via WhatsApp.', 'success');
        closeReceipt();
      } else {
        _toast('WhatsApp delivery failed.', 'error');
        btn.disabled    = false;
        btn.textContent = 'Send via WhatsApp';
      }
    } catch (e) {
      _toast('Network error.', 'error');
      btn.disabled    = false;
      btn.textContent = 'Send via WhatsApp';
    }
  }

  async function printReceipt() {
    if (!lastReceipt || !lastReceipt.receipt_id) {
      _toast('Receipt not available for printing.', 'error');
      return;
    }

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/receipts/${lastReceipt.receipt_id}/thermal/`
      );

      if (!res.ok) {
        _toast('Could not load receipt for printing.', 'error');
        return;
      }

      const data   = await res.json();
      const win    = window.open('', '_blank', 'width=300,height=600');
      if (win) {
        win.document.write(
          `<pre style="font-family:monospace;font-size:12px;padding:8px;">`
          + data.text
          + `</pre>`
        );
        win.document.close();
        win.print();
      }

      closeReceipt();
    } catch (e) {
      _toast('Print error.', 'error');
    }
  }

  // ── Toast ──────────────────────────────────────────────────
  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el     = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  // ── Helpers ────────────────────────────────────────────────
  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── Public API ─────────────────────────────────────────────
return {
    init,
    loadSummary,
    openConfirm,
    closeConfirm,
    selectMethod,
    selectDeposit,
    confirmPayment,
    closeReceipt,
    sendWhatsApp,
    printReceipt,
  };

})();

document.addEventListener('DOMContentLoaded', Cashier.init);