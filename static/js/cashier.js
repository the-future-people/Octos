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
    await Auth.guard(['CASHIER']);
    await loadContext();
    await loadSummary();
    await loadQueue();
    _startPolling();
    _startShiftPolling();
  }

  // ── Context ────────────────────────────────────────────────
  async function loadContext() {
    try {
      const res  = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const user = await res.json();

      const branchEl = document.getElementById('cashier-branch-name');
      const nameEl   = document.getElementById('cashier-user-name');
      const initEl   = document.getElementById('cashier-user-initials');

      if (branchEl) {
        if (user.branch_detail) {
          branchEl.textContent = user.branch_detail.name || '—';
        } else if (typeof user.branch === 'object' && user.branch) {
          branchEl.textContent = user.branch.name || '—';
        } else if (user.branch) {
          try {
            const br = await Auth.fetch(`/api/v1/organization/branches/${user.branch}/`);
            if (br.ok) { const b = await br.json(); branchEl.textContent = b.name || '—'; }
          } catch { branchEl.textContent = '—'; }
        }
      }

      if (nameEl) nameEl.textContent = user.full_name || user.email || '—';

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
      const res  = await Auth.fetch('/api/v1/jobs/cashier/summary/');
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
      const labels = { receipts: 'Receipts', log: "Today's Log", credit: 'Credit Accounts' };
      main.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;
          justify-content:center;height:320px;gap:12px;color:var(--text-3);">
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

      <div class="queue-header">
        <div>
          <div class="queue-title">Payment Queue</div>
          <div class="queue-subtitle">Jobs waiting for payment confirmation — oldest first</div>
        </div>
        <div class="queue-meta">
          <div class="queue-pill"><span id="queue-count-num">—</span> pending</div>
        </div>
      </div>

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
    if (currentPane !== 'queue') return;
    try {
      const res  = await Auth.fetch('/api/v1/jobs/cashier/queue/');
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
    if (!list) return;

    const count   = queue.length;
    const countEl = document.getElementById('queue-count-num');
    const badgeEl = document.getElementById('sidebar-queue-count');
    if (countEl) countEl.textContent   = count;
    if (badgeEl) {
      badgeEl.textContent   = count;
      badgeEl.style.display = count > 0 ? 'flex' : 'none';
    }

    if (!count) {
      list.innerHTML = `
        <div class="queue-empty">
          <div class="queue-empty-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
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
      const priority    = job.priority || 'NORMAL';
      const waitClass   = _waitClass(job.created_at);
      const waitLabel   = _waitLabel(job.created_at);
      const customer    = _esc(job.customer_name  || 'Walk-in');
      const attendant   = _esc(job.intake_by_name || '—');
      const channel     = _esc(job.intake_channel || 'WALK_IN');
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
              <span class="queue-card-channel">${channel}</span>
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

    _s('confirm-job-ref',        activeJob.job_number || '#' + activeJob.id);
    _s('confirm-attendant',      activeJob.intake_by_name || '—');
    _s('confirm-type',           activeJob.job_type || '—');
    _s('confirm-customer',       activeJob.customer_name || 'Walk-in');
    _s('confirm-branch-name',    activeJob.branch_name    || '—');
    _s('confirm-branch-address', activeJob.branch_address || '—');
    _s('confirm-branch-phone',   activeJob.branch_phone   || '—');

    _v('confirm-phone', activeJob.customer_phone || '');
    _v('confirm-notes', '');
    _v('momo-ref', '');
    _v('pos-ref',  '');
    _v('cash-tendered', '');

    // Populate line items
    const itemsEl = document.getElementById('confirm-line-items');
    if (itemsEl) {
      const items = activeJob.line_items || [];
      if (items.length) {
        itemsEl.innerHTML = items.map(li => `
          <div class="cm-item">
            <span class="cm-item-name">${li.label || li.service_name || '—'}</span>
            <span class="cm-item-qty">${li.pages > 1 ? li.pages + 'pp' : (li.quantity ?? 1)}</span>
            <span class="cm-item-price">GHS ${parseFloat(li.line_total || li.unit_price || 0)
              .toLocaleString('en-GH', { minimumFractionDigits: 2 })}</span>
          </div>`).join('');
      } else {
        itemsEl.innerHTML = '<div class="cm-items-empty">No line items</div>';
      }
    }

    // Reset change row
    const changeRow = document.getElementById('cm-change-row');
    if (changeRow) changeRow.style.display = 'none';

    // Reset hint
    const hint = document.getElementById('cm-payment-hint');
    if (hint) { hint.textContent = 'Select a payment method to continue'; hint.classList.add('visible'); }

    selectMethod('CASH');
    selectDeposit(100);

    const btn = document.getElementById('confirm-submit-btn');
    if (btn) { btn.disabled = true; btn.style.opacity = '0.4'; btn.textContent = 'Confirm Payment'; }

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

    // Show/hide ref fields
    const momoField   = document.getElementById('momo-ref-field');
    const posField    = document.getElementById('pos-ref-field');
    const cashField   = document.getElementById('cash-tendered-field');
    if (momoField) momoField.classList.toggle('visible', method === 'MOMO');
    if (posField)  posField.classList.toggle('visible',  method === 'POS');
    if (cashField) cashField.classList.toggle('visible', method === 'CASH');

    // Clear irrelevant fields
    if (method !== 'CASH') {
      const changeRow = document.getElementById('cm-change-row');
      const input     = document.getElementById('cash-tendered');
      if (changeRow) changeRow.style.display = 'none';
      if (input)     input.value = '';
    }

    // Update confirm button class
    const btn = document.getElementById('confirm-submit-btn');
    if (btn) btn.className = `cm-confirm-btn ${method.toLowerCase()}`;

    // Update hint
    const hint = document.getElementById('cm-payment-hint');
    if (hint) {
      hint.classList.add('visible');
      if (method === 'CASH')      hint.textContent = 'Enter cash amount tendered by customer';
      else if (method === 'MOMO') hint.textContent = 'Enter MoMo reference number to continue';
      else if (method === 'POS')  hint.textContent = 'Enter POS approval code to continue';
    }

    _updateAmountDue();
    _updateConfirmBtn();
  }

  // ── Deposit ────────────────────────────────────────────────
  function selectDeposit(pct) {
    selectedDeposit = pct;
    [100, 70].forEach(p => {
      const el = document.getElementById(`opt-${p}`);
      if (el) el.classList.toggle('selected', p === pct);
    });
    _updateAmountDue();
    _updateConfirmBtn();
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

  // ── Cash change calculator ─────────────────────────────────
  function calcChange() {
    if (selectedMethod !== 'CASH' || !activeJob) return;
    const due      = parseFloat(activeJob.estimated_cost || 0) * (selectedDeposit / 100);
    const tendered = parseFloat(document.getElementById('cash-tendered')?.value || 0);
    const change   = tendered - due;
    const row      = document.getElementById('cm-change-row');
    const val      = document.getElementById('cm-change-val');
    if (!row || !val) return;

    if (tendered > 0) {
      row.style.display     = 'flex';
      row.style.background  = change >= 0 ? 'var(--green-bg)'     : 'var(--red-bg)';
      row.style.borderColor = change >= 0 ? 'var(--green-border)'  : 'var(--red-border)';
      val.style.color       = change >= 0 ? 'var(--green-text)'    : 'var(--red-text)';
      val.textContent       = `GHS ${Math.abs(change).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
      const label = document.querySelector('.cm-change-label');
      if (label) label.style.color = change >= 0 ? 'var(--green-text)' : 'var(--red-text)';
    } else {
      row.style.display = 'none';
    }

    _updateConfirmBtn();
  }

  // ── Confirm button gate ────────────────────────────────────
  function _updateConfirmBtn() {
    const btn = document.getElementById('confirm-submit-btn');
    if (!btn) return;

    let ready = false;

    if (selectedMethod === 'CASH') {
      const due      = parseFloat(activeJob?.estimated_cost || 0) * (selectedDeposit / 100);
      const tendered = parseFloat(document.getElementById('cash-tendered')?.value || 0);
      ready = tendered >= due && tendered > 0;
    } else if (selectedMethod === 'MOMO') {
      ready = !!(document.getElementById('momo-ref')?.value.trim());
    } else if (selectedMethod === 'POS') {
      ready = !!(document.getElementById('pos-ref')?.value.trim());
    }

    btn.disabled      = !ready;
    btn.style.opacity = ready ? '1' : '0.4';

    // Hide hint when ready
    if (ready) {
      const hint = document.getElementById('cm-payment-hint');
      if (hint) hint.classList.remove('visible');
    }
  }

  // ── Confirm payment ────────────────────────────────────────
  async function confirmPayment() {
    if (!activeJob) return;

    // Final validation
    if (selectedMethod === 'CASH') {
      const tendered = parseFloat(document.getElementById('cash-tendered')?.value || 0);
      const due      = parseFloat(activeJob.estimated_cost || 0) * (selectedDeposit / 100);
      if (!tendered || tendered <= 0) {
        _toast('Please enter the cash amount tendered by customer.', 'error'); return;
      }
      if (tendered < due) {
        _toast(`Cash tendered (GHS ${tendered.toFixed(2)}) is less than amount due (GHS ${due.toFixed(2)}).`, 'error'); return;
      }
    }
    if (selectedMethod === 'MOMO') {
      if (!document.getElementById('momo-ref')?.value.trim()) {
        _toast('MoMo reference number is required.', 'error'); return;
      }
    }
    if (selectedMethod === 'POS') {
      if (!document.getElementById('pos-ref')?.value.trim()) {
        _toast('POS approval code is required.', 'error'); return;
      }
    }

    const notes   = document.getElementById('confirm-notes')?.value.trim()  || '';
    const phone   = document.getElementById('confirm-phone')?.value.trim()  || '';
    const momoRef = document.getElementById('momo-ref')?.value.trim()       || '';
    const posCode = document.getElementById('pos-ref')?.value.trim()        || '';
    const btn     = document.getElementById('confirm-submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Processing…'; }

    try {
      const body = {
        deposit_percentage: selectedDeposit,
        payment_method    : selectedMethod,
        notes,
      };
      if (selectedMethod === 'MOMO') body.momo_reference    = momoRef;
      if (selectedMethod === 'POS')  body.pos_approval_code = posCode;
      if (phone)                     body.customer_phone    = phone;
      if (selectedMethod === 'CASH') {
        const tendered = parseFloat(document.getElementById('cash-tendered')?.value || 0);
        const due      = parseFloat(activeJob.estimated_cost || 0) * (selectedDeposit / 100);
        if (tendered > 0) {
          body.cash_tendered = tendered.toFixed(2);
          body.change_given  = Math.max(0, tendered - due).toFixed(2);
        }
      }

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
        if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.textContent = 'Confirm Payment'; }
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

    } catch {
      _toast('Network error. Please try again.', 'error');
      if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.textContent = 'Confirm Payment'; }
    }
  }

  // ── Summary strip ──────────────────────────────────────────
  function _updateSummaryStrip() {
    const fmt = n => `GHS ${Number(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
    const _s  = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
    _s('sum-cash',       fmt(totals.CASH));
    _s('sum-momo',       fmt(totals.MOMO));
    _s('sum-pos',        fmt(totals.POS));
    _s('sum-total',      fmt(totals.CASH + totals.MOMO + totals.POS));
    _s('sum-jobs-count', `${totals.count} job${totals.count !== 1 ? 's' : ''} confirmed`);
  }

  // ── Receipt modal ──────────────────────────────────────────
  function _showReceiptModal(result) {
    const fmt = n => n
      ? `GHS ${parseFloat(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
      : 'GHS 0.00';
    const _s = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };

    _s('receipt-job-ref', result.job_number || '—');
    _s('receipt-amount',  fmt(result.amount_paid));
    _s('receipt-balance', fmt(result.balance_due || 0));
    _s('receipt-method',  selectedMethod);
    _s('receipt-number',  result.receipt_number || '—');

    // Cash tendered + change
    const cashRow   = document.getElementById('receipt-cash-row');
    const changeRow = document.getElementById('receipt-change-row');
    if (selectedMethod === 'CASH') {
      const tendered = parseFloat(document.getElementById('cash-tendered')?.value || 0);
      const due      = parseFloat(result.amount_paid || 0);
      const change   = Math.max(0, tendered - due);
      if (tendered > 0) {
        _s('receipt-cash-tendered', fmt(tendered));
        _s('receipt-change-given',  fmt(change));
        if (cashRow)   cashRow.style.display   = 'flex';
        if (changeRow) changeRow.style.display = 'flex';
      }
    } else {
      if (cashRow)   cashRow.style.display   = 'none';
      if (changeRow) changeRow.style.display = 'none';
    }

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
      _toast('Receipt not available for WhatsApp delivery.', 'error'); return;
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
      _toast('Receipt not available for printing.', 'error'); return;
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
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  // ── Shift sign-off ─────────────────────────────────────────
  let _shiftPollTimer  = null;
  let _shiftStatus     = null;
  let _signOffStep     = 1;
  let _signOffFloatId  = null;
  const SHIFT_POLL_MS  = 60000;

  function _startShiftPolling() {
    _pollShiftStatus();
    _shiftPollTimer = setInterval(_pollShiftStatus, SHIFT_POLL_MS);
  }

  async function _pollShiftStatus() {
    try {
      const res = await Auth.fetch('/api/v1/finance/cashier/shift-status/');
      if (!res.ok) return;
      _shiftStatus = await res.json();
      _handleShiftStatus(_shiftStatus);
    } catch { /* silent */ }
  }

  function _handleShiftStatus(s) {
    if (!s.has_shift) return;

    _signOffFloatId = s.float_id;

    if (s.is_signed_off) {
      _lockQueue('Your shift has ended. You have signed off.');
      return;
    }
    if (s.should_lock) {
      // Fire wizard immediately — non-dismissible
      _lockQueue('Your shift has ended. Please complete sign-off.');
      openSignOffWizard(false);
      return;
    }
    if (s.should_prompt) {
      _showSignOffBanner(s.minutes_remaining);
    }
  }

  function _showSignOffBanner(minsRemaining) {
    if (document.getElementById('signoff-banner')) return; // already showing
    const banner = document.createElement('div');
    banner.id    = 'signoff-banner';
    banner.style.cssText = `
      position:fixed;top:56px;left:0;right:0;z-index:900;
      background:var(--amber-bg);border-bottom:1px solid var(--amber-border);
      padding:10px 24px;display:flex;align-items:center;justify-content:space-between;
      font-size:13px;color:var(--amber-text);`;
    banner.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;">
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24"
          fill="none" stroke="currentColor" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span><strong>Your shift ends in ${minsRemaining} minute${minsRemaining !== 1 ? 's' : ''}.</strong>
        Please prepare to sign off.</span>
      </div>
      <div style="display:flex;gap:10px;">
        <button onclick="Cashier.openSignOffWizard(true)"
          style="padding:6px 14px;background:var(--amber-text);color:#fff;border:none;
                 border-radius:var(--radius-sm);font-size:12px;font-weight:700;cursor:pointer;">
          Sign Off Now
        </button>
        <button onclick="document.getElementById('signoff-banner').remove()"
          style="padding:6px 10px;background:none;border:1px solid var(--amber-border);
                 border-radius:var(--radius-sm);font-size:12px;cursor:pointer;color:var(--amber-text);">
          Dismiss
        </button>
      </div>`;
    document.body.prepend(banner);
  }

  function _lockQueue(message) {
    // Stop payment polling — no new jobs should come in
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

    const list = document.getElementById('queue-list');
    if (!list) return;

    // Disable all collect buttons
    list.querySelectorAll('.collect-btn').forEach(btn => {
      btn.disabled = true;
      btn.textContent = 'Queue Locked';
      btn.style.opacity = '0.4';
    });

    // Show locked banner inside queue
    const existing = document.getElementById('queue-lock-banner');
    if (existing) return;
    const lockBanner = document.createElement('div');
    lockBanner.id    = 'queue-lock-banner';
    lockBanner.style.cssText = `
      padding:14px 20px;background:var(--red-bg);border:1px solid var(--red-border);
      border-radius:var(--radius);margin-bottom:16px;
      display:flex;align-items:center;justify-content:space-between;gap:12px;`;
    lockBanner.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;color:var(--red-text);">
        <svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24"
          fill="none" stroke="currentColor" stroke-width="2">
          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
          <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
        </svg>
        <span style="font-size:13px;font-weight:600;">${message}</span>
      </div>
      <button onclick="Cashier.openSignOffWizard(false)"
        style="padding:6px 14px;background:var(--red-text);color:#fff;border:none;
               border-radius:var(--radius-sm);font-size:12px;font-weight:700;cursor:pointer;
               white-space:nowrap;">
        Complete Sign-Off
      </button>`;
    list.prepend(lockBanner);
  }

  function openSignOffWizard(dismissible = true) {
    _signOffStep = 1;

    // Remove existing wizard if any
    document.getElementById('signoff-wizard')?.remove();

    const overlay = document.createElement('div');
    overlay.id    = 'signoff-wizard';
    overlay.style.cssText = `
      position:fixed;inset:0;z-index:9999;
      background:rgba(0,0,0,0.7);
      display:flex;align-items:center;justify-content:center;
      font-family:'DM Sans',sans-serif;`;

    if (dismissible) {
      overlay.addEventListener('click', e => {
        if (e.target === overlay) overlay.remove();
      });
    }

    overlay.innerHTML = `
      <div style="
        background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);width:100%;max-width:540px;
        max-height:90vh;overflow-y:auto;box-shadow:0 20px 60px rgba(0,0,0,0.3);">

        <!-- Header -->
        <div style="padding:20px 24px 0;display:flex;align-items:flex-start;justify-content:space-between;">
          <div>
            <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:var(--text);">
              End of Shift Sign-Off
            </div>
            <div style="font-size:12px;color:var(--text-3);margin-top:3px;" id="wizard-step-label">
              Step 1 of 5
            </div>
          </div>
          ${dismissible ? `
            <button onclick="document.getElementById('signoff-wizard').remove()"
              style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-3);">×</button>
          ` : ''}
        </div>

        <!-- Step indicator -->
        <div style="padding:16px 24px 0;display:flex;gap:6px;">
          ${[1,2,3,4,5].map(n => `
            <div id="wizard-step-dot-${n}" style="
              flex:1;height:3px;border-radius:2px;
              background:${n === 1 ? 'var(--text)' : 'var(--border)'};
              transition:background 0.2s;">
            </div>`).join('')}
        </div>

        <!-- Body -->
        <div id="wizard-body" style="padding:24px;">
          <!-- Rendered per step -->
        </div>

        <!-- Footer -->
        <div style="padding:16px 24px 20px;border-top:1px solid var(--border);
          display:flex;justify-content:space-between;align-items:center;">
          <button id="wizard-back-btn" onclick="Cashier._wizardBack()"
            style="padding:8px 18px;background:none;border:1px solid var(--border);
                   border-radius:var(--radius-sm);font-size:13px;cursor:pointer;
                   color:var(--text-2);display:none;">
            ← Back
          </button>
          <div></div>
          <button id="wizard-next-btn" onclick="Cashier._wizardNext()"
            style="padding:8px 20px;background:var(--text);color:#fff;border:none;
                   border-radius:var(--radius-sm);font-size:13px;font-weight:700;cursor:pointer;">
            Continue →
          </button>
        </div>
      </div>`;

    document.body.appendChild(overlay);
    _renderWizardStep(1);
  }

  function _renderWizardStep(step) {
    _signOffStep = step;
    const body    = document.getElementById('wizard-body');
    const label   = document.getElementById('wizard-step-label');
    const backBtn = document.getElementById('wizard-back-btn');
    const nextBtn = document.getElementById('wizard-next-btn');
    if (!body) return;

    // Update step dots
    [1,2,3,4,5].forEach(n => {
      const dot = document.getElementById(`wizard-step-dot-${n}`);
      if (dot) dot.style.background = n <= step ? 'var(--text)' : 'var(--border)';
    });

    if (label) label.textContent = `Step ${step} of 5`;
    if (backBtn) backBtn.style.display = step > 1 ? 'block' : 'none';
    if (nextBtn) nextBtn.textContent   = step === 5 ? 'Sign Off Shift' : 'Continue →';

    const s = _shiftStatus || {};
    const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

    const steps = {

      // ── Step 1: Queue check ─────────────────────────────────
      1: () => `
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">
          Queue Status
        </div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Confirm the state of the payment queue before signing off.
        </div>
        <div id="wizard-queue-check" style="
          padding:16px;background:var(--bg);border:1px solid var(--border);
          border-radius:var(--radius);font-size:13px;color:var(--text-3);">
          Checking queue…
        </div>
        <div style="margin-top:16px;font-size:13px;color:var(--text-2);">
          <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;">
            <input type="checkbox" id="wizard-queue-ack" style="margin-top:2px;accent-color:var(--text);">
            <span>I acknowledge the current queue state and confirm any pending jobs will carry forward.</span>
          </label>
        </div>`,

      // ── Step 2: Collection summary ──────────────────────────
      2: () => `
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">
          Collection Summary
        </div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Verify your total collections for today's shift.
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:16px;">
          <div style="padding:14px;background:var(--cash-bg);border:1px solid var(--cash-border);border-radius:var(--radius-sm);">
            <div style="font-size:11px;font-weight:700;color:var(--cash-text);text-transform:uppercase;letter-spacing:0.5px;">Cash</div>
            <div style="font-size:18px;font-weight:700;color:var(--cash-strong);margin-top:4px;">${fmt(totals.CASH)}</div>
          </div>
          <div style="padding:14px;background:var(--momo-bg);border:1px solid var(--momo-border);border-radius:var(--radius-sm);">
            <div style="font-size:11px;font-weight:700;color:var(--momo-text);text-transform:uppercase;letter-spacing:0.5px;">MoMo</div>
            <div style="font-size:18px;font-weight:700;color:var(--momo-strong);margin-top:4px;">${fmt(totals.MOMO)}</div>
          </div>
          <div style="padding:14px;background:var(--pos-bg);border:1px solid var(--pos-border);border-radius:var(--radius-sm);">
            <div style="font-size:11px;font-weight:700;color:var(--pos-text);text-transform:uppercase;letter-spacing:0.5px;">POS</div>
            <div style="font-size:18px;font-weight:700;color:var(--pos-strong);margin-top:4px;">${fmt(totals.POS)}</div>
          </div>
          <div style="padding:14px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);">
            <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Total</div>
            <div style="font-size:18px;font-weight:700;color:var(--text);margin-top:4px;">${fmt(totals.CASH+totals.MOMO+totals.POS)}</div>
          </div>
        </div>
        <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;font-size:13px;color:var(--text-2);">
          <input type="checkbox" id="wizard-summary-ack" style="margin-top:2px;accent-color:var(--text);">
          <span>I confirm these figures are accurate to the best of my knowledge.</span>
        </label>`,

      // ── Step 3: Closing cash count ──────────────────────────
      3: () => `
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">
          Closing Cash Count
        </div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Count the physical cash in your till and enter the total below.
        </div>
        <div class="fg" style="margin-bottom:16px;">
          <label style="font-size:12px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;display:block;margin-bottom:6px;">Closing Cash Amount (GHS)</label>
          <input type="number" id="wizard-closing-cash" min="0" step="0.01" placeholder="0.00"
            oninput="Cashier._updateVariancePreview()"
            style="width:100%;padding:10px 14px;border:1px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);
                   color:var(--text);font-size:15px;font-family:'JetBrains Mono',monospace;
                   box-sizing:border-box;">
        </div>
        <div id="variance-preview" style="display:none;padding:12px 14px;border-radius:var(--radius-sm);
          font-size:13px;margin-bottom:16px;"></div>
        <div class="fg">
          <label style="font-size:12px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;display:block;margin-bottom:6px;">Variance Notes <span style="color:var(--red-text);">*</span></label>
          <textarea id="wizard-variance-notes" rows="3"
            placeholder="Explain any difference between expected and actual cash…"
            style="width:100%;padding:10px 14px;border:1px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);
                   color:var(--text);font-size:13px;resize:vertical;box-sizing:border-box;">
          </textarea>
          <div style="font-size:11px;color:var(--text-3);margin-top:4px;">
            Required — explain any discrepancy or confirm cash matches.
          </div>
        </div>`,

      // ── Step 4: Float handover ──────────────────────────────
      4: () => `
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">
          Float Handover
        </div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Physically hand over your cash float to the Branch Manager before confirming.
        </div>
        <div style="padding:16px;background:var(--bg);border:1px solid var(--border);
          border-radius:var(--radius);margin-bottom:20px;">
          <div style="font-size:12px;color:var(--text-3);margin-bottom:4px;">Amount to hand over</div>
          <div style="font-size:24px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--text);">
            ${fmt(totals.CASH)}
          </div>
          <div style="font-size:12px;color:var(--text-3);margin-top:4px;">
            Total cash collected today
          </div>
        </div>
        <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;font-size:13px;color:var(--text-2);">
          <input type="checkbox" id="wizard-float-ack" style="margin-top:2px;accent-color:var(--text);">
          <span>I confirm I have physically handed over the cash float to the Branch Manager.</span>
        </label>`,

      // ── Step 5: Shift notes + overtime/cover ────────────────
      5: () => `
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">
          Shift Notes & Extensions
        </div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Add any observations, incidents, or extend your shift if needed.
        </div>
        <div class="fg" style="margin-bottom:20px;">
          <label style="font-size:12px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;display:block;margin-bottom:6px;">Shift Notes</label>
          <textarea id="wizard-shift-notes" rows="3"
            placeholder="Any incidents, issues, or observations during your shift…"
            style="width:100%;padding:10px 14px;border:1px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);
                   color:var(--text);font-size:13px;resize:vertical;box-sizing:border-box;">
          </textarea>
        </div>
        <div style="padding:14px;background:var(--bg);border:1px solid var(--border);
          border-radius:var(--radius);margin-bottom:12px;">
          <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:13px;font-weight:600;color:var(--text);">
            <input type="checkbox" id="wizard-is-overtime" onchange="Cashier._toggleOvertimeFields()"
              style="accent-color:var(--text);">
            I am doing overtime
          </label>
          <div id="overtime-fields" style="display:none;margin-top:12px;padding-top:12px;
            border-top:1px solid var(--border);">
            <div class="fg" style="margin-bottom:10px;">
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
                letter-spacing:0.5px;display:block;margin-bottom:6px;">Overtime Until</label>
              <input type="datetime-local" id="wizard-overtime-until"
                style="width:100%;padding:8px 12px;border:1px solid var(--border);
                       border-radius:var(--radius-sm);background:var(--bg);
                       color:var(--text);font-size:13px;box-sizing:border-box;">
            </div>
            <div class="fg">
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
                letter-spacing:0.5px;display:block;margin-bottom:6px;">Reason</label>
              <input type="text" id="wizard-overtime-reason" placeholder="Brief reason for overtime…"
                style="width:100%;padding:8px 12px;border:1px solid var(--border);
                       border-radius:var(--radius-sm);background:var(--bg);
                       color:var(--text);font-size:13px;box-sizing:border-box;">
            </div>
          </div>
        </div>
        <div style="padding:14px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);">
          <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:13px;font-weight:600;color:var(--text);">
            <input type="checkbox" id="wizard-is-cover" onchange="Cashier._toggleCoverFields()"
              style="accent-color:var(--text);">
            I am covering someone else's shift
          </label>
          <div id="cover-fields" style="display:none;margin-top:12px;padding-top:12px;
            border-top:1px solid var(--border);">
            <div class="fg" style="margin-bottom:10px;">
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
                letter-spacing:0.5px;display:block;margin-bottom:6px;">Covering Until</label>
              <input type="datetime-local" id="wizard-cover-until"
                style="width:100%;padding:8px 12px;border:1px solid var(--border);
                       border-radius:var(--radius-sm);background:var(--bg);
                       color:var(--text);font-size:13px;box-sizing:border-box;">
            </div>
          </div>
        </div>`,
    };

    body.innerHTML = steps[step]?.() || '';

    // Step 1: load queue count async
    if (step === 1) {
      Auth.fetch('/api/v1/jobs/cashier/queue/').then(async res => {
        if (!res.ok) return;
        const data  = await res.json();
        const jobs  = data.results || data;
        const count = jobs.length;
        const el    = document.getElementById('wizard-queue-check');
        if (!el) return;
        if (count === 0) {
          el.style.background   = 'var(--green-bg)';
          el.style.borderColor  = 'var(--green-border)';
          el.style.color        = 'var(--green-text)';
          el.innerHTML = `<strong>✓ Queue is clear</strong> — no jobs pending payment.`;
        } else {
          el.style.background   = 'var(--amber-bg)';
          el.style.borderColor  = 'var(--amber-border)';
          el.style.color        = 'var(--amber-text)';
          el.innerHTML = `<strong>⚠ ${count} job${count !== 1 ? 's' : ''} pending payment</strong> — these will carry forward to tomorrow.`;
        }
      }).catch(() => {});
    }
  }

  function _updateVariancePreview() {
    const closing  = parseFloat(document.getElementById('wizard-closing-cash')?.value || 0);
    const expected = totals.CASH; // opening float + cash collected
    const variance = closing - expected;
    const el       = document.getElementById('variance-preview');
    if (!el || !closing) { if (el) el.style.display = 'none'; return; }

    el.style.display     = 'block';
    el.style.background  = variance === 0 ? 'var(--green-bg)'  : 'var(--amber-bg)';
    el.style.borderColor = variance === 0 ? 'var(--green-border)' : 'var(--amber-border)';
    el.style.color       = variance === 0 ? 'var(--green-text)'   : 'var(--amber-text)';
    el.style.border      = '1px solid';

    const fmt = n => `GHS ${Math.abs(n).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
    el.innerHTML = variance === 0
      ? `<strong>✓ No variance</strong> — cash matches expected amount.`
      : `<strong>${variance > 0 ? 'Surplus' : 'Shortage'}: ${fmt(variance)}</strong>
         — Expected ${fmt(expected)}, counted ${fmt(closing)}.`;
  }

  function _toggleOvertimeFields() {
    const checked = document.getElementById('wizard-is-overtime')?.checked;
    const fields  = document.getElementById('overtime-fields');
    if (fields) fields.style.display = checked ? 'block' : 'none';
  }

  function _toggleCoverFields() {
    const checked = document.getElementById('wizard-is-cover')?.checked;
    const fields  = document.getElementById('cover-fields');
    if (fields) fields.style.display = checked ? 'block' : 'none';
  }

  function _wizardBack() {
    if (_signOffStep > 1) _renderWizardStep(_signOffStep - 1);
  }

  function _wizardNext() {
    // Validate current step before advancing
    if (_signOffStep === 1) {
      if (!document.getElementById('wizard-queue-ack')?.checked) {
        _toast('Please acknowledge the queue status.', 'error'); return;
      }
    }
    if (_signOffStep === 2) {
      if (!document.getElementById('wizard-summary-ack')?.checked) {
        _toast('Please confirm the collection summary.', 'error'); return;
      }
    }
    if (_signOffStep === 3) {
      const cash  = document.getElementById('wizard-closing-cash')?.value;
      const notes = document.getElementById('wizard-variance-notes')?.value.trim();
      if (!cash || parseFloat(cash) < 0) {
        _toast('Please enter your closing cash count.', 'error'); return;
      }
      if (!notes) {
        _toast('Variance notes are required.', 'error'); return;
      }
    }
    if (_signOffStep === 4) {
      if (!document.getElementById('wizard-float-ack')?.checked) {
        _toast('Please confirm float handover.', 'error'); return;
      }
    }

    if (_signOffStep < 5) {
      _renderWizardStep(_signOffStep + 1);
    } else {
      _submitSignOff();
    }
  }

  async function _submitSignOff() {
    if (!_signOffFloatId) {
      _toast('No float record found. Contact your Branch Manager.', 'error'); return;
    }

    const isOvertime = document.getElementById('wizard-is-overtime')?.checked || false;
    const isCover    = document.getElementById('wizard-is-cover')?.checked    || false;

    const body = {
      closing_cash   : parseFloat(document.getElementById('wizard-closing-cash')?.value || 0),
      variance_notes : document.getElementById('wizard-variance-notes')?.value.trim() || '',
      shift_notes    : document.getElementById('wizard-shift-notes')?.value.trim()    || '',
      is_overtime    : isOvertime,
      is_cover       : isCover,
    };

    if (isOvertime) {
      body.overtime_reason = document.getElementById('wizard-overtime-reason')?.value.trim() || '';
      body.overtime_until  = document.getElementById('wizard-overtime-until')?.value || null;
    }
    if (isCover) {
      body.cover_until = document.getElementById('wizard-cover-until')?.value || null;
    }

    const btn = document.getElementById('wizard-next-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Signing off…'; }

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/floats/${_signOffFloatId}/sign-off/`, {
          method : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body   : JSON.stringify(body),
        }
      );

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Sign-off failed.', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Sign Off Shift'; }
        return;
      }

      const result = await res.json();

      // Overtime/cover — queue stays open
      if (result.is_overtime || result.is_cover) {
        document.getElementById('signoff-wizard')?.remove();
        document.getElementById('signoff-banner')?.remove();
        _toast(
          result.is_overtime
            ? `Overtime recorded until ${new Date(result.overtime_until).toLocaleTimeString('en-GH',{hour:'2-digit',minute:'2-digit'})}.`
            : 'Cover shift recorded.',
          'success'
        );
        _startPolling(); // resume queue polling
        return;
      }

      // Full sign-off complete
      document.getElementById('signoff-wizard')?.remove();
      _showSignOffComplete();

    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Sign Off Shift'; }
    }
  }

  function _showSignOffComplete() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

    const overlay = document.createElement('div');
    overlay.style.cssText = `
      position:fixed;inset:0;z-index:9999;
      background:var(--bg);
      display:flex;flex-direction:column;align-items:center;justify-content:center;
      gap:16px;font-family:'DM Sans',sans-serif;`;
    overlay.innerHTML = `
      <div style="width:64px;height:64px;border-radius:50%;background:var(--green-bg);
        border:2px solid var(--green-border);display:flex;align-items:center;justify-content:center;">
        <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24"
          fill="none" stroke="var(--green-text)" stroke-width="2.5">
          <polyline points="20 6 9 17 4 12"/>
        </svg>
      </div>
      <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--text);">
        Shift Complete
      </div>
      <div style="font-size:14px;color:var(--text-3);text-align:center;max-width:320px;">
        You have successfully signed off. Have a great rest of your day!
      </div>
      <div style="font-size:13px;color:var(--text-3);">
        This window will close in <span id="signoff-countdown">5</span> seconds…
      </div>`;

    document.body.appendChild(overlay);

    let count = 5;
    const timer = setInterval(() => {
      count--;
      const el = document.getElementById('signoff-countdown');
      if (el) el.textContent = count;
      if (count <= 0) {
        clearInterval(timer);
        window.location.href = '/portal/login/';
      }
    }, 1000);
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
    calcChange,
    _updateConfirmBtn,
    openSignOffWizard,
    _wizardBack,
    _wizardNext,
    _updateVariancePreview,
    _toggleOvertimeFields,
    _toggleCoverFields,
  };
})();

document.addEventListener('DOMContentLoaded', Cashier.init);