'use strict';

/**
 * Octos — Cashier Portal
 *
 * API:
 *   GET  /api/v1/jobs/cashier/queue/           — PENDING_PAYMENT jobs for branch
 *   GET  /api/v1/jobs/cashier/summary/         — today's totals per payment method
 *   POST /api/v1/jobs/<id>/cashier/confirm/    — confirm payment
 *   GET  /api/v1/accounts/me/                  — user/branch context
 *   POST /api/v1/finance/receipts/<id>/send-whatsapp/ — send receipt
 */

const Cashier = (() => {

  // ── State ──────────────────────────────────────────────────
  let queue           = [];
  let pollTimer       = null;
  let activeJob       = null;
  let selectedDeposit = 100;
  let selectedMethod  = 'CASH';
  let lastReceipt     = null;
  let currentPane     = 'queue';

  const totals = { CASH: 0, MOMO: 0, POS: 0, count: 0 };

  const POLL_INTERVAL   = 4000;
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

  // ── Context ────────────────────────────────────────────────
  async function loadContext() {
    try {
      const res = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const data = await res.json();

      const user = data;

      const branchEl = document.getElementById('cashier-branch-name');
      const nameEl   = document.getElementById('cashier-user-name');
      const initEl   = document.getElementById('cashier-user-initials');

      // branch comes back as integer ID — fetch the branch name separately
      if (branchEl) {
        if (typeof data.branch === 'object' && data.branch) {
          branchEl.textContent = data.branch.name || '—';
        } else if (data.branch) {
          try {
            const br = await Auth.fetch(`/api/v1/organization/branches/${data.branch}/`);
            if (br.ok) {
              const b = await br.json();
              branchEl.textContent = b.name || '—';
            }
          } catch { branchEl.textContent = '—'; }
        }
      }
      if (nameEl)   nameEl.textContent   = user.full_name || user.email || '—';

      const initials = (user.full_name || '')
        .split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() || '??';
      if (initEl) initEl.textContent = initials;

    } catch (e) {
      console.warn('loadContext failed:', e);
    }
  }

  // ── Summary ────────────────────────────────────────────────
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

  // ── Pane switching ─────────────────────────────────────────
  function switchPane(paneId) {
    currentPane = paneId;

    // Update sidebar active states
    document.querySelectorAll('.sidebar-item[data-pane]').forEach(item => {
      item.classList.toggle('active', item.dataset.pane === paneId);
    });

    const main = document.getElementById('cashier-main-content');
    if (!main) return;

    if (paneId === 'queue') {
      _renderQueuePane(main);
      loadQueue();
      _updateSummaryStrip();
    } else {
      const labels = {
        receipts : 'Receipts',
        log      : "Today's Log",
        credit   : 'Credit Accounts',
      };
      main.innerHTML = `
        <div style="
          display:flex;flex-direction:column;align-items:center;
          justify-content:center;height:320px;gap:12px;
          color:var(--text-3);
        ">
          <svg xmlns="http://www.w3.org/2000/svg" width="36" height="36" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="1.5">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <div style="font-family:'Syne',sans-serif;font-size:16px;font-weight:700;color:var(--text);">
            ${labels[paneId] || paneId}
          </div>
          <div style="font-size:13px;">This section is coming soon.</div>
        </div>`;
    }
  }

  function _renderQueuePane(container) {
    container.innerHTML = `
      <!-- Summary strip -->
      <div class="summary-strip">
        <div class="summary-card cash">
          <div class="summary-label">Cash</div>
          <div class="summary-amount" id="sum-cash">GHS 0.00</div>
          <div class="summary-count" id="sum-total-count">0 transactions</div>
        </div>
        <div class="summary-card momo">
          <div class="summary-label">MoMo</div>
          <div class="summary-amount" id="sum-momo">GHS 0.00</div>
          <div class="summary-count">0 transactions</div>
        </div>
        <div class="summary-card pos">
          <div class="summary-label">POS</div>
          <div class="summary-amount" id="sum-pos">GHS 0.00</div>
          <div class="summary-count">0 transactions</div>
        </div>
        <div class="summary-card total">
          <div class="summary-label">Total Collected</div>
          <div class="summary-amount" id="sum-total">GHS 0.00</div>
          <div class="summary-count" id="sum-jobs-count">0 jobs confirmed</div>
        </div>
      </div>

      <!-- Queue header -->
      <div class="queue-header">
        <div>
          <div class="queue-title">Payment Queue</div>
          <div class="queue-subtitle">Jobs waiting for payment confirmation — oldest first</div>
        </div>
        <div class="queue-meta">
          <div class="queue-pill">
            <span id="queue-count-num">—</span> pending
          </div>
        </div>
      </div>

      <!-- Queue list -->
      <div class="queue-list" id="queue-list">
        <div class="skeleton-card">
          <div class="skel" style="width:22px;height:14px;"></div>
          <div style="flex:1;">
            <div class="skel" style="width:55%;height:14px;margin-bottom:8px;"></div>
            <div class="skel" style="width:38%;height:11px;"></div>
          </div>
          <div class="skel" style="width:90px;height:18px;"></div>
          <div class="skel" style="width:110px;height:34px;border-radius:8px;"></div>
        </div>
      </div>`;
  }

  // ── Queue ──────────────────────────────────────────────────
  async function loadQueue() {
    // Only update queue if on queue pane
    if (currentPane !== 'queue') return;

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
    if (!list) return;

    const count = queue.length;

    const countEl = document.getElementById('queue-count-num');
    const badgeEl = document.getElementById('sidebar-queue-count');
    if (countEl) countEl.textContent = count;
    if (badgeEl) {
      badgeEl.textContent    = count;
      badgeEl.style.display  = count > 0 ? 'flex' : 'none';
    }

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
      const cost      = job.estimated_cost
        ? `GHS ${parseFloat(job.estimated_cost).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
        : '—';
      const priority  = job.priority || 'NORMAL';
      const waitClass = _waitClass(job.created_at);
      const waitLabel = _waitLabel(job.created_at);
      const customer  = _esc(job.customer_name  || 'Walk-in');
      const attendant = _esc(job.intake_by_name || '—');
      const priorityTag = priority !== 'NORMAL'
        ? `<span class="priority-tag ${priority}">${priority}</span>`
        : '';

      return `
        <div class="queue-card priority-${priority}" onclick="Cashier.openConfirm(${job.id})">
          <div class="queue-card-index">${String(i + 1).padStart(2, '0')}</div>
          <div class="queue-card-info">
            <div class="queue-card-title">${_esc(job.title || '—')}</div>
            <div class="queue-card-meta">
              <span class="queue-card-ref">${_esc(job.job_number || '#' + job.id)}</span>
              <span class="type-pill ${job.job_type || ''}">${job.job_type || ''}</span>
              ${priorityTag}
              <span class="queue-card-attendant">by ${attendant}</span>
              <span class="queue-card-channel">${_esc(job.intake_channel || 'WALK_IN')}</span>
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
    const list = document.getElementById('queue-list');
    if (!list) return;
    list.innerHTML = `
      <div class="queue-empty">
        <div class="queue-empty-title" style="color:#cc3300;">Failed to load queue</div>
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
    selectedDeposit = 100;
    selectedMethod  = 'CASH';

    const _s = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    const _v = (id, val) => { const el = document.getElementById(id); if (el) el.value = val; };

    _s('confirm-job-ref',   activeJob.job_number || '#' + activeJob.id);
    _s('confirm-job-name',  activeJob.title || '—');
    _s('confirm-attendant', activeJob.intake_by_name || '—');
    _s('confirm-type',      activeJob.job_type || '—');
    _s('confirm-customer',  activeJob.customer_name || 'Walk-in');
    _s('confirm-branch-name',    activeJob.branch_name    || '—');
    _s('confirm-branch-address', activeJob.branch_address || '—');
    _s('confirm-branch-phone',   activeJob.branch_phone   || '—');

    _v('confirm-phone', activeJob.customer_phone || '');
    _v('confirm-notes', '');
    _v('momo-ref', '');
    _v('pos-ref',  '');
    // Populate line items
    const itemsEl = document.getElementById('confirm-line-items');
    if (itemsEl) {
      const items = activeJob.line_items || [];
      if (items.length) {
        itemsEl.innerHTML = items.map(li => `
          <div class="cm-item">
            <span class="cm-item-name">${li.label || li.service_name || '—'}</span>
            <span class="cm-item-qty">${li.quantity ?? 1}</span>
            <span class="cm-item-price">GHS ${parseFloat(li.line_total || li.unit_price || 0).toLocaleString('en-GH', { minimumFractionDigits: 2 })}</span>
          </div>`).join('');
      } else {
        itemsEl.innerHTML = '<div class="cm-items-empty">No line items</div>';
      }
    }

    selectMethod('CASH');
    selectDeposit(100);

    const btn = document.getElementById('confirm-submit-btn');
    if (btn) { btn.disabled = false; btn.textContent = 'Confirm Payment'; }

    document.getElementById('confirm-overlay')?.classList.add('open');
  }

  function closeConfirm() {
    document.getElementById('confirm-overlay')?.classList.remove('open');
    activeJob = null;
  }
  // ── Payment method ─────────────────────────────────────────
function selectMethod(method) {
    selectedMethod = method;
    ['CASH', 'MOMO', 'POS'].forEach(m => {
      const btn = document.getElementById(`pm-${m.toLowerCase()}`);
      if (btn) btn.classList.toggle('selected', m === method);
    });
    const momoField = document.getElementById('momo-ref-field');
    const posField  = document.getElementById('pos-ref-field');
    if (momoField) momoField.classList.toggle('visible', method === 'MOMO');
    if (posField)  posField.classList.toggle('visible',  method === 'POS');
    _updateAmountDue();
    const btn = document.getElementById('confirm-submit-btn');
    if (btn) {
      btn.className = `cm-confirm-btn ${method.toLowerCase()}`;
    }
    // Cash tendered field
    const cashTendered = document.getElementById('cash-tendered-field');
    if (cashTendered) cashTendered.classList.toggle('visible', method === 'CASH');
    if (method !== 'CASH') {
      const changeRow = document.getElementById('cm-change-row');
      if (changeRow) changeRow.style.display = 'none';
      const input = document.getElementById('cash-tendered');
      if (input) input.value = '';
    }
  }
  // ── Deposit ────────────────────────────────────────────────
function selectDeposit(pct) {
    selectedDeposit = pct;
    [100, 70].forEach(p => {
      const el = document.getElementById(`opt-${p}`);
      if (el) el.classList.toggle('selected', p === pct);
    });
    _updateAmountDue();
  }

function _updateAmountDue() {
    if (!activeJob) return;
    const total = parseFloat(activeJob.estimated_cost || activeJob.computed_total || 0);
    const due   = total * (selectedDeposit / 100);
    const el    = document.getElementById('confirm-amount-due');
    if (el) el.textContent = `GHS ${due.toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
    const costEl = document.getElementById('confirm-est-cost');
    if (costEl) costEl.textContent = `GHS ${total.toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
  }
  function calcChange() {
    if (selectedMethod !== 'CASH' || !activeJob) return;
    const due      = parseFloat(activeJob.estimated_cost || 0) * (selectedDeposit / 100);
    const tendered = parseFloat(document.getElementById('cash-tendered')?.value || 0);
    const change   = tendered - due;
    const row      = document.getElementById('cm-change-row');
    const val      = document.getElementById('cm-change-val');
    if (!row || !val) return;
    if (tendered > 0) {
      row.style.display = 'flex';
      val.textContent   = `GHS ${Math.abs(change).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
      row.style.background  = change >= 0 ? 'var(--green-bg)'  : 'var(--red-bg)';
      row.style.borderColor = change >= 0 ? 'var(--green-border)' : 'var(--red-border)';
      val.style.color       = change >= 0 ? 'var(--green-text)' : 'var(--red-text)';
      const label = document.querySelector('.cm-change-label');
      if (label) label.style.color = change >= 0 ? 'var(--green-text)' : 'var(--red-text)';
    } else {
      row.style.display = 'none';
    }
  }

  // ── Confirm payment ────────────────────────────────────────
  async function confirmPayment() {
    if (!activeJob) return;

    if (selectedMethod === 'MOMO') {
      const ref = document.getElementById('momo-ref')?.value.trim();
      if (!ref) { _toast('MoMo reference number is required.', 'error'); return; }
    }

    if (selectedMethod === 'POS') {
      const code = document.getElementById('pos-ref')?.value.trim();
      if (!code) { _toast('POS approval code is required.', 'error'); return; }
    }

    const notes   = document.getElementById('confirm-notes')?.value.trim() || '';
    const phone   = document.getElementById('confirm-phone')?.value.trim() || '';
    const momoRef = document.getElementById('momo-ref')?.value.trim()      || '';
    const posCode = document.getElementById('pos-ref')?.value.trim()       || '';
    const btn     = document.getElementById('confirm-submit-btn');

    if (btn) { btn.disabled = true; btn.textContent = 'Processing…'; }

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

      const paid = parseFloat(result.amount_paid || 0);
      if (totals[selectedMethod] !== undefined) totals[selectedMethod] += paid;
      totals.count += 1;
      _updateSummaryStrip();

      closeConfirm();
      await loadQueue();
      _showReceiptModal(result);

    } catch (e) {
      _toast('Network error. Please try again.', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = '✓ Confirm Payment'; }
    }
  }

  // ── Summary strip ──────────────────────────────────────────
  function _updateSummaryStrip() {
    const fmt = n => `GHS ${Number(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;

    const _s = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

    _s('sum-cash',  fmt(totals.CASH));
    _s('sum-momo',  fmt(totals.MOMO));
    _s('sum-pos',   fmt(totals.POS));
    _s('sum-total', fmt(totals.CASH + totals.MOMO + totals.POS));
    _s('sum-jobs-count', `${totals.count} job${totals.count !== 1 ? 's' : ''} confirmed`);
  }

  // ── Receipt modal ──────────────────────────────────────────
  function _showReceiptModal(result) {
    const fmt = n => n
      ? `GHS ${parseFloat(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
      : 'GHS 0.00';

    const _s = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

    _s('receipt-job-ref',  result.job_number || '—');
    _s('receipt-amount',   fmt(result.amount_paid));
    _s('receipt-balance',  fmt(result.balance_due || 0));
    _s('receipt-method',   selectedMethod);
    _s('receipt-number',   result.receipt_number || '—');

    const waBtn = document.getElementById('btn-send-whatsapp');
    const phone = document.getElementById('confirm-phone')?.value?.trim() || '';
    if (waBtn) waBtn.disabled = !phone;

    document.getElementById('receipt-overlay')?.classList.add('open');
  }

  function closeReceipt() {
    document.getElementById('receipt-overlay')?.classList.remove('open');
    lastReceipt = null;
  }

  async function sendWhatsApp() {
    if (!lastReceipt?.receipt_id) {
      _toast('Receipt not available for WhatsApp delivery.', 'error');
      return;
    }
    const btn = document.getElementById('btn-send-whatsapp');
    if (btn) { btn.disabled = true; btn.textContent = 'Sending…'; }

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
        if (btn) { btn.disabled = false; btn.textContent = 'Send via WhatsApp'; }
      }
    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Send via WhatsApp'; }
    }
  }

  async function printReceipt() {
    if (!lastReceipt?.receipt_id) {
      _toast('Receipt not available for printing.', 'error');
      return;
    }
    try {
      const res  = await Auth.fetch(`/api/v1/finance/receipts/${lastReceipt.receipt_id}/thermal/`);
      if (!res.ok) { _toast('Could not load receipt for printing.', 'error'); return; }
      const data = await res.json();
      const win  = window.open('', '_blank', 'width=300,height=600');
      if (win) {
        win.document.write(`<pre style="font-family:monospace;font-size:12px;padding:8px;">${data.text}</pre>`);
        win.document.close();
        win.print();
      }
      closeReceipt();
    } catch {
      _toast('Print error.', 'error');
    }
  }

  // ── Toast ──────────────────────────────────────────────────
  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className   = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  // ── Helpers ────────────────────────────────────────────────
  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    init,
    loadSummary,
    switchPane,
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