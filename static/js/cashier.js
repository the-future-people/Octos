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
    WeekGreeter.init();
    if (typeof CashierNotif !== 'undefined') CashierNotif.startPolling();
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
    } else if (paneId === 'receipts') {
      _renderReceiptsPane(main);
    } else if (paneId === 'log') {
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
            Today's Log
          </div>
          <div style="font-size:13px;">This section is coming soon.</div>
        </div>`;
    } else if (paneId === 'credit') {
      _renderCreditPane(main);
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
  async function openConfirm(jobId) {
    // Open modal immediately with skeleton state
    document.getElementById('confirm-overlay')?.classList.add('open');

    // Fetch fresh job data to ensure customer_credit is current
    try {
      const res = await Auth.fetch('/api/v1/jobs/cashier/queue/');
      if (res.ok) {
        const data = await res.json();
        const jobs = data.results || data;
        activeJob = jobs.find(j => j.id === jobId);
      }
    } catch { /* silent */ }
    if (!activeJob) activeJob = queue.find(j => j.id === jobId);
    if (!activeJob) {
      document.getElementById('confirm-overlay')?.classList.remove('open');
      return;
    }
    // Show/hide partial credit button based on customer credit account
    const pcBtn = document.getElementById('pm-partial-credit');
    if (pcBtn) {
      const hasCredit = !!(activeJob.customer_credit &&
        parseFloat(activeJob.customer_credit.available_credit) > 0);
      pcBtn.style.display = hasCredit ? 'flex' : 'none';
    }
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
    _v('confirm-company', '');
    _v('confirm-notes', '');
    _v('momo-ref', '');
    _v('pos-ref',  '');
    _v('cash-tendered', '');

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

    const changeRow = document.getElementById('cm-change-row');
    if (changeRow) changeRow.style.display = 'none';

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

    ['CASH', 'MOMO', 'POS', 'SPLIT'].forEach(m => {
      const btn = document.getElementById(`pm-${m.toLowerCase()}`);
      if (btn) btn.classList.toggle('selected', m === method);
    });

    const momoField = document.getElementById('momo-ref-field');
    const posField  = document.getElementById('pos-ref-field');
    const cashField = document.getElementById('cash-tendered-field');
    if (momoField) momoField.classList.toggle('visible', method === 'MOMO');
    if (posField)  posField.classList.toggle('visible',  method === 'POS');
    if (cashField) cashField.classList.toggle('visible', method === 'CASH');
    if (method === 'SPLIT' || method === 'PARTIAL_CREDIT') {
      momoField?.classList.remove('visible');
      posField?.classList.remove('visible');
      cashField?.classList.remove('visible');
    }

    if (method !== 'CASH') {
      const changeRow = document.getElementById('cm-change-row');
      const input     = document.getElementById('cash-tendered');
      if (changeRow) changeRow.style.display = 'none';
      if (input)     input.value = '';
    }

    const splitFields = document.getElementById('split-fields');
    if (splitFields) splitFields.style.display = method === 'SPLIT' ? 'block' : 'none';
    if (method === 'SPLIT') _updateSplitFields();

    const pcFields = document.getElementById('partial-credit-fields');
    if (pcFields) pcFields.style.display = method === 'PARTIAL_CREDIT' ? 'block' : 'none';
    if (method === 'PARTIAL_CREDIT') _initPartialCredit();

    // Style the partial credit button
    const pcBtn = document.getElementById('pm-partial-credit');
    if (pcBtn) {
      pcBtn.classList.toggle('selected', method === 'PARTIAL_CREDIT');
      if (method === 'PARTIAL_CREDIT') {
        pcBtn.style.borderColor = 'var(--amber-text)';
        pcBtn.style.background  = 'var(--amber-bg)';
        pcBtn.style.color       = 'var(--amber-text)';
      } else {
        pcBtn.style.borderColor = 'var(--border)';
        pcBtn.style.background  = 'var(--bg)';
        pcBtn.style.color       = 'var(--text-2)';
      }
    }

    const btn = document.getElementById('confirm-submit-btn');
    if (btn) btn.className = `cm-confirm-btn ${method.toLowerCase()}`;

    const hint = document.getElementById('cm-payment-hint');
    if (hint) {
      hint.classList.add('visible');
      if (method === 'CASH')       hint.textContent = 'Enter cash amount tendered by customer';
      else if (method === 'MOMO')  hint.textContent = 'Enter MoMo reference number to continue';
      else if (method === 'POS')   hint.textContent = 'Enter POS approval code to continue';
      else if (method === 'SPLIT') hint.textContent = 'Enter amounts for each payment leg';
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
      row.style.background  = change >= 0 ? 'var(--green-bg)'    : 'var(--red-bg)';
      row.style.borderColor = change >= 0 ? 'var(--green-border)' : 'var(--red-border)';
      val.style.color       = change >= 0 ? 'var(--green-text)'   : 'var(--red-text)';
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
      const ref = document.getElementById('momo-ref')?.value.trim() || '';
      ready = /^\d{11}$/.test(ref);
    } else if (selectedMethod === 'POS') {
      ready = !!(document.getElementById('pos-ref')?.value.trim());
    } else if (selectedMethod === 'SPLIT') {
      ready = _validateSplitLegs().valid;
    } else if (selectedMethod === 'PARTIAL_CREDIT') {
      ready = _validatePartialCredit().valid;
    }

    btn.disabled      = !ready;
    btn.style.opacity = ready ? '1' : '0.4';

    if (ready) {
      const hint = document.getElementById('cm-payment-hint');
      if (hint) hint.classList.remove('visible');
    }
  }

  // ── Confirm payment ────────────────────────────────────────
  async function confirmPayment() {
    if (!activeJob) return;

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
    if (selectedMethod === 'PARTIAL_CREDIT') {
      const validation = _validatePartialCredit();
      if (!validation.valid) {
        _toast(validation.error, 'error'); return;
      }
    }

    const notes   = document.getElementById('confirm-notes')?.value.trim()  || '';
    const phone   = document.getElementById('confirm-phone')?.value.trim()  || '';
    const company = document.getElementById('confirm-company')?.value.trim() || '';
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
      if (selectedMethod === 'MOMO') {
        const ref = document.getElementById('momo-ref')?.value.trim() || '';
        if (!/^\d{11}$/.test(ref)) {
          _toast('MoMo reference must be exactly 11 digits.', 'error');
          if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.textContent = 'Confirm Payment'; }
          return;
        }
        body.momo_reference = ref;
      }
      if (selectedMethod === 'POS')  body.pos_approval_code = posCode;
      if (selectedMethod === 'SPLIT') {
        const validation = _validateSplitLegs();
        if (!validation.valid) {
          _toast(validation.error, 'error');
          if (btn) { btn.disabled = false; btn.style.opacity = '1'; btn.textContent = 'Confirm Payment'; }
          return;
        }
        body.split_legs = validation.legs;
      }
      if (selectedMethod === 'PARTIAL_CREDIT') {
        const validation  = _validatePartialCredit();
        const pcAmount    = parseFloat(document.getElementById('pc-amount')?.value || 0);
        const pcMethod    = document.getElementById('pc-method')?.value || 'CASH';
        const pcRef       = document.getElementById('pc-ref')?.value.trim() || '';
        const due         = parseFloat(activeJob.estimated_cost || 0);
        const creditPortion = due - pcAmount;

        body.payment_method          = pcMethod;
        body.partial_credit_amount   = creditPortion.toFixed(2);
        body.partial_credit_account  = activeJob.customer_credit.account_id;
        if (pcMethod === 'MOMO') body.momo_reference    = pcRef;
        if (pcMethod === 'POS')  body.pos_approval_code = pcRef;
      }
      if (phone)   body.customer_phone = phone;
      if (company) body.company_name   = company;
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

  function _fmtTime(isoOrTime) {
    if (!isoOrTime) return '—';
    try {
      // Handle both "19:30:00" and full ISO datetime
      const str = String(isoOrTime);
      if (str.includes('T')) {
        return new Date(str).toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' });
      }
      const [h, m] = str.split(':');
      const d = new Date();
      d.setHours(parseInt(h), parseInt(m));
      return d.toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' });
    } catch { return isoOrTime; }
  }

  // ── Shift sign-off ─────────────────────────────────────────
  let _shiftPollTimer = null;
  let _shiftStatus    = null;
  let _signOffStep    = 1;
  let _signOffFloatId = null;
  const SHIFT_POLL_MS = 60000;

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
          _lockQueue('Your shift has ended. Please complete sign-off.');
          openSignOffWizard(false);
          return;
        }
    if (s.should_prompt) {
      _showSignOffBanner(s.minutes_remaining, s.shift_end);
    }
  }

function _showSignOffBanner(minsRemaining, shiftEnd) {
    // Only show once per session
    if (document.getElementById('signoff-banner') ||
        document.getElementById('closing-warn-overlay')) return;

    const endTime  = _fmtTime(shiftEnd);
    const isUrgent = minsRemaining <= 15;

    const overlay = document.createElement('div');
    overlay.id    = 'closing-warn-overlay';
    overlay.style.cssText = `
      position:fixed;inset:0;z-index:9998;
      background:rgba(0,0,0,0.85);
      display:flex;align-items:center;justify-content:center;
      font-family:'DM Sans',sans-serif;`;

    overlay.innerHTML = `
      <div style="
        background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);width:100%;max-width:480px;
        padding:32px;text-align:center;
        box-shadow:0 24px 64px rgba(0,0,0,0.4);">

        <div style="width:64px;height:64px;border-radius:50%;
          background:${isUrgent ? 'var(--red-bg)' : 'var(--amber-bg)'};
          border:2px solid ${isUrgent ? 'var(--red-border)' : 'var(--amber-border)'};
          display:flex;align-items:center;justify-content:center;
          margin:0 auto 20px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28"
            viewBox="0 0 24 24" fill="none"
            stroke="${isUrgent ? 'var(--red-text)' : 'var(--amber-text)'}" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
        </div>

        <div style="font-family:'Syne',sans-serif;font-size:22px;
          font-weight:800;color:var(--text);margin-bottom:8px;">
          ${isUrgent ? 'Shift Ending Soon' : 'Shift Ending in 30 Minutes'}
        </div>
        <div style="font-size:14px;color:var(--text-3);margin-bottom:8px;">
          Your shift ends at <strong style="color:var(--text);">${endTime}</strong>.
        </div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:28px;">
          ${isUrgent
            ? 'Please complete any active payments and prepare for sign-off.'
            : 'Clear the payment queue and prepare for end-of-shift sign-off.'}
        </div>

        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Auto-dismissing in <span id="cashier-closing-countdown"
            style="font-weight:700;color:${isUrgent ? 'var(--red-text)' : 'var(--amber-text)'};">15</span>s
        </div>

        <div style="display:flex;gap:10px;justify-content:center;">
          <button onclick="Cashier.openSignOffWizard(true);document.getElementById('closing-warn-overlay').remove();"
            style="padding:10px 24px;
              background:${isUrgent ? 'var(--red-text)' : 'var(--text)'};
              color:#fff;border:none;border-radius:var(--radius-sm);
              font-size:14px;font-weight:700;cursor:pointer;
              font-family:'DM Sans',sans-serif;">
            Sign Off Now
          </button>
          <button onclick="document.getElementById('closing-warn-overlay').remove()"
            style="padding:10px 24px;background:none;
              border:1px solid var(--border);border-radius:var(--radius-sm);
              font-size:14px;font-weight:600;cursor:pointer;
              color:var(--text-2);font-family:'DM Sans',sans-serif;">
            Dismiss
          </button>
        </div>
      </div>`;

    document.body.appendChild(overlay);

    // Auto-dismiss after 15 seconds
    let count = 15;
    const timer = setInterval(() => {
      count--;
      const el = document.getElementById('cashier-closing-countdown');
      if (el) el.textContent = count;
      if (count <= 0) {
        clearInterval(timer);
        overlay.remove();
      }
    }, 1000);
  }

  function _lockQueue(message) {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }

    const list = document.getElementById('queue-list');
    if (!list) return;

    list.querySelectorAll('.collect-btn').forEach(btn => {
      btn.disabled    = true;
      btn.textContent = 'Queue Locked';
      btn.style.opacity = '0.4';
    });

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

  // ── Sign-off wizard ────────────────────────────────────────
  function openSignOffWizard(dismissible = true, floatId = null) {
    if (floatId) _signOffFloatId = floatId;
    _signOffStep = 1;
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

        <div style="padding:16px 24px 0;display:flex;gap:6px;">
          ${[1,2,3,4,5].map(n => `
            <div id="wizard-step-dot-${n}" style="
              flex:1;height:3px;border-radius:2px;
              background:${n === 1 ? 'var(--text)' : 'var(--border)'};
              transition:background 0.2s;">
            </div>`).join('')}
        </div>

        <div id="wizard-body" style="padding:24px;"></div>

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

    [1,2,3,4,5].forEach(n => {
      const dot = document.getElementById(`wizard-step-dot-${n}`);
      if (dot) dot.style.background = n <= step ? 'var(--text)' : 'var(--border)';
    });

    if (label)   label.textContent        = `Step ${step} of 5`;
    if (backBtn) backBtn.style.display     = step > 1 ? 'block' : 'none';
    if (nextBtn) nextBtn.textContent       = step === 5 ? 'Sign Off Shift' : 'Continue →';
    if (nextBtn) nextBtn.style.background  = step === 5 ? 'var(--red-text)' : 'var(--text)';

    const fmt = n => `GHS ${parseFloat(n || 0).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;

    const steps = {

      // ── Step 1: Queue check ─────────────────────────────────
      1: () => `
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">Queue Status</div>
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
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">Collection Summary</div>
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
            <div style="font-size:18px;font-weight:700;color:var(--text);margin-top:4px;">${fmt(totals.CASH + totals.MOMO + totals.POS)}</div>
          </div>
        </div>
        <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;font-size:13px;color:var(--text-2);">
          <input type="checkbox" id="wizard-summary-ack" style="margin-top:2px;accent-color:var(--text);">
          <span>I confirm these figures are accurate to the best of my knowledge.</span>
        </label>`,

      // ── Step 3: Closing cash count ──────────────────────────
      3: () => `
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">Closing Cash Count</div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Count the physical cash in your till and enter the total below.
        </div>
        <div style="margin-bottom:16px;">
          <label style="font-size:12px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;display:block;margin-bottom:6px;">Closing Cash Amount (GHS)</label>
          <input type="number" id="wizard-closing-cash" min="0" step="0.01" placeholder="0.00"
            oninput="Cashier._updateVariancePreview()"
            style="width:100%;padding:10px 14px;border:1px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                   font-size:15px;font-family:'JetBrains Mono',monospace;box-sizing:border-box;">
        </div>
        <div id="variance-preview" style="display:none;padding:12px 14px;border-radius:var(--radius-sm);
          border:1px solid;font-size:13px;margin-bottom:16px;"></div>
        <div>
          <label style="font-size:12px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Variance Notes <span style="color:var(--red-text);">*</span>
          </label>
          <textarea id="wizard-variance-notes" rows="3"
            placeholder="Explain any difference between expected and actual cash, or confirm cash matches…"
            style="width:100%;padding:10px 14px;border:1px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                   font-size:13px;resize:vertical;box-sizing:border-box;"></textarea>
          <div style="font-size:11px;color:var(--text-3);margin-top:4px;">Required — confirm cash matches or explain any discrepancy.</div>
        </div>`,

      // ── Step 4: Float handover ──────────────────────────────
      4: () => `
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">Float Handover</div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Physically hand over your cash float to the Branch Manager before confirming.
        </div>
        <div style="padding:16px;background:var(--bg);border:1px solid var(--border);
          border-radius:var(--radius);margin-bottom:20px;">
          <div style="font-size:12px;color:var(--text-3);margin-bottom:4px;">Amount to hand over</div>
          <div style="font-size:24px;font-weight:800;font-family:'JetBrains Mono',monospace;color:var(--text);">
            ${fmt(totals.CASH)}
          </div>
          <div style="font-size:12px;color:var(--text-3);margin-top:4px;">Total cash collected today</div>
        </div>
        <label style="display:flex;align-items:flex-start;gap:10px;cursor:pointer;font-size:13px;color:var(--text-2);">
          <input type="checkbox" id="wizard-float-ack" style="margin-top:2px;accent-color:var(--text);">
          <span>I confirm I have physically handed over the cash float to the Branch Manager.</span>
        </label>`,

      // ── Step 5: Shift notes + overtime ─────────────────────
      5: () => `
        <div style="font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">Shift Notes</div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Add any observations or incidents from your shift, then confirm sign-off.
        </div>
        <div style="margin-bottom:20px;">
          <label style="font-size:12px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;display:block;margin-bottom:6px;">Shift Notes</label>
          <textarea id="wizard-shift-notes" rows="3"
            placeholder="Any incidents, issues, or observations during your shift…"
            style="width:100%;padding:10px 14px;border:1px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                   font-size:13px;resize:vertical;box-sizing:border-box;"></textarea>
        </div>
        <div style="padding:14px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius);">
          <label style="display:flex;align-items:center;gap:10px;cursor:pointer;font-size:13px;font-weight:600;color:var(--text);">
            <input type="checkbox" id="wizard-is-overtime" onchange="Cashier._toggleOvertimeFields()"
              style="accent-color:var(--text);">
            I need to stay for overtime
          </label>
          <div id="overtime-fields" style="display:none;margin-top:12px;padding-top:12px;border-top:1px solid var(--border);">
            <div style="margin-bottom:10px;">
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
                letter-spacing:0.5px;display:block;margin-bottom:6px;">Overtime Until</label>
              <input type="datetime-local" id="wizard-overtime-until"
                style="width:100%;padding:8px 12px;border:1px solid var(--border);
                       border-radius:var(--radius-sm);background:var(--bg);
                       color:var(--text);font-size:13px;box-sizing:border-box;">
            </div>
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
                letter-spacing:0.5px;display:block;margin-bottom:6px;">Reason</label>
              <input type="text" id="wizard-overtime-reason" placeholder="Brief reason for overtime…"
                style="width:100%;padding:8px 12px;border:1px solid var(--border);
                       border-radius:var(--radius-sm);background:var(--bg);
                       color:var(--text);font-size:13px;box-sizing:border-box;">
            </div>
          </div>
        </div>`,
    };

    body.innerHTML = steps[step]?.() || '';

    // Step 1: async queue check
    if (step === 1) {
      Auth.fetch('/api/v1/jobs/cashier/queue/').then(async res => {
        if (!res.ok) return;
        const data  = await res.json();
        const jobs  = data.results || data;
        const count = jobs.length;
        const el    = document.getElementById('wizard-queue-check');
        if (!el) return;
        if (count === 0) {
          el.style.background  = 'var(--green-bg)';
          el.style.borderColor = 'var(--green-border)';
          el.style.color       = 'var(--green-text)';
          el.innerHTML         = `<strong>✓ Queue is clear</strong> — no jobs pending payment.`;
        } else {
          el.style.background  = 'var(--amber-bg)';
          el.style.borderColor = 'var(--amber-border)';
          el.style.color       = 'var(--amber-text)';
          el.innerHTML         = `<strong>⚠ ${count} job${count !== 1 ? 's' : ''} pending payment</strong> — these will carry forward to tomorrow.`;
        }
      }).catch(() => {});
    }
  }

  function _updateVariancePreview() {
    const closing  = parseFloat(document.getElementById('wizard-closing-cash')?.value || 0);
    const expected = totals.CASH;
    const variance = closing - expected;
    const el       = document.getElementById('variance-preview');
    if (!el) return;
    if (!closing && closing !== 0) { el.style.display = 'none'; return; }

    el.style.display     = 'block';
    el.style.background  = variance === 0 ? 'var(--green-bg)'     : 'var(--amber-bg)';
    el.style.borderColor = variance === 0 ? 'var(--green-border)'  : 'var(--amber-border)';
    el.style.color       = variance === 0 ? 'var(--green-text)'    : 'var(--amber-text)';

    const fmt = n => `GHS ${Math.abs(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
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

  function _wizardBack() {
    if (_signOffStep > 1) _renderWizardStep(_signOffStep - 1);
  }

  function _wizardNext() {
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
      if (cash === '' || cash === null || cash === undefined) {
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

    const body = {
      closing_cash   : parseFloat(document.getElementById('wizard-closing-cash')?.value || 0),
      variance_notes : document.getElementById('wizard-variance-notes')?.value.trim() || '',
      shift_notes    : document.getElementById('wizard-shift-notes')?.value.trim()    || '',
      is_overtime    : isOvertime,
      is_cover       : false,
    };

    if (isOvertime) {
      body.overtime_reason = document.getElementById('wizard-overtime-reason')?.value.trim() || '';
      body.overtime_until  = document.getElementById('wizard-overtime-until')?.value || null;
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

      // Overtime — extend queue access, don't sign off
      if (result.is_overtime) {
        document.getElementById('signoff-wizard')?.remove();
        document.getElementById('signoff-banner')?.remove();
        const untilStr = result.overtime_until
          ? _fmtTime(result.overtime_until)
          : 'later';
        _toast(`Overtime recorded — queue open until ${untilStr}.`, 'success');
        _startPolling();
        return;
      }

      // Full sign-off complete
      document.getElementById('signoff-wizard')?.remove();
      document.getElementById('signoff-banner')?.remove();

      // Clear queue visually
      const list = document.getElementById('queue-list');
      if (list) list.innerHTML = `
        <div class="queue-empty">
          <div class="queue-empty-icon" style="background:var(--green-bg);border-color:var(--green-border);">
            <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
              fill="none" stroke="var(--green-text)" stroke-width="1.5">
              <polyline points="20 6 9 17 4 12"/>
            </svg>
          </div>
          <div class="queue-empty-title" style="color:var(--green-text);">Shift signed off</div>
          <div class="queue-empty-sub">Your collections have been recorded. Have a great rest of your day!</div>
        </div>`;

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
        Redirecting in <span id="signoff-countdown">5</span> seconds…
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
  // ── Cashier History & Receipts Pane ──────────────────────
// ── Cashier History & Receipts Pane ──────────────────────
  function _renderReceiptsPane(container) {
    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
        <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;
          color:var(--text);letter-spacing:-0.3px;">My Activity</div>
        <div style="display:flex;gap:2px;background:var(--bg);border:1px solid var(--border);
          border-radius:10px;padding:3px;">
          <button id="tab-history"
            onclick="Cashier._switchReceiptsTab('history')"
            style="padding:5px 14px;border-radius:8px;border:none;
                   background:var(--text);color:#fff;
                   font-size:12px;font-weight:600;cursor:pointer;
                   font-family:'DM Sans',sans-serif;transition:all 0.15s;">
            History
          </button>
          <button id="tab-receipts"
            onclick="Cashier._switchReceiptsTab('receipts')"
            style="padding:5px 14px;border-radius:8px;border:none;
                   background:none;color:var(--text-3);
                   font-size:12px;font-weight:500;cursor:pointer;
                   font-family:'DM Sans',sans-serif;transition:all 0.15s;">
            Receipts
          </button>
        </div>
      </div>
      <div id="receipts-tab-content"></div>`;
    _loadAllHistoryPeriods();
  }

  function _switchReceiptsTab(tab) {
    const histBtn = document.getElementById('tab-history');
    const rcptBtn = document.getElementById('tab-receipts');
    if (histBtn) {
      histBtn.style.background = tab === 'history' ? 'var(--text)' : 'none';
      histBtn.style.color      = tab === 'history' ? '#fff' : 'var(--text-3)';
      histBtn.style.fontWeight = tab === 'history' ? '600' : '500';
    }
    if (rcptBtn) {
      rcptBtn.style.background = tab === 'receipts' ? 'var(--text)' : 'none';
      rcptBtn.style.color      = tab === 'receipts' ? '#fff' : 'var(--text-3)';
      rcptBtn.style.fontWeight = tab === 'receipts' ? '600' : '500';
    }
    const content = document.getElementById('receipts-tab-content');
    if (!content) return;
    if (tab === 'history') {
      _loadAllHistoryPeriods();
    } else {
      _loadReceiptsList();
    }
  }

  async function _loadAllHistoryPeriods() {
    const content = document.getElementById('receipts-tab-content');
    if (!content) return;

    content.innerHTML = `
      <div style="display:flex;flex-direction:column;gap:16px;">
        <div id="hist-today"  class="hist-section"></div>
        <div id="hist-week"   class="hist-section"></div>
        <div id="hist-month"  class="hist-section"></div>
        <div id="hist-year"   class="hist-section"></div>
      </div>`;

    const now   = new Date();
    const year  = now.getFullYear();
    const month = now.getMonth() + 1;

    // ISO week number
    const d = new Date(Date.UTC(now.getFullYear(), now.getMonth(), now.getDate()));
    d.setUTCDate(d.getUTCDate() + 4 - (d.getUTCDay() || 7));
    const yearStart = new Date(Date.UTC(d.getUTCFullYear(), 0, 1));
    const week = Math.ceil((((d - yearStart) / 86400000) + 1) / 7);

    const sections = [
      { id: 'hist-today', label: 'Today',      params: { level: 'day',   year, month, week } },
      { id: 'hist-week',  label: 'This Week',  params: { level: 'week',  year, month } },
      { id: 'hist-month', label: 'This Month', params: { level: 'month', year } },
      { id: 'hist-year',  label: 'This Year',  params: { level: 'year' } },
    ];

    // Load all four in parallel
    await Promise.all(sections.map(s => _loadHistorySection(s.id, s.label, s.params)));
  }

  async function _loadHistorySection(elId, label, params) {
    const el = document.getElementById(elId);
    if (!el) return;

    el.innerHTML = `
      <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
        letter-spacing:0.8px;margin-bottom:10px;">${label}</div>
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
        padding:16px 20px;display:flex;align-items:center;gap:8px;color:var(--text-3);font-size:13px;">
        <span class="spin"></span> Loading…
      </div>`;

    try {
      const qp = new URLSearchParams(params);
      const res  = await Auth.fetch(`/api/v1/finance/cashier/history/?${qp}`);
      if (!res.ok) throw new Error();
      const data = await res.json();

      // For day/week/month/year — sum all results into one total
      const results = data.results || [];
      const fmt = n => `GHS ${Number(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;

      if (!results.length) {
        el.innerHTML = `
          <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.8px;margin-bottom:10px;">${label}</div>
          <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
            padding:16px 20px;font-size:13px;color:var(--text-3);">
            No activity yet.
          </div>`;
        return;
      }

      const cash  = results.reduce((a, r) => a + r.cash,  0);
      const momo  = results.reduce((a, r) => a + r.momo,  0);
      const pos   = results.reduce((a, r) => a + r.pos,   0);
      const total = cash + momo + pos;
      const count = results.reduce((a, r) => a + r.count, 0);

      const cashPct = total > 0 ? (cash / total * 100).toFixed(0) : 0;
      const momoPct = total > 0 ? (momo / total * 100).toFixed(0) : 0;
      const posPct  = total > 0 ? (pos  / total * 100).toFixed(0) : 0;

      el.innerHTML = `
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
          letter-spacing:0.8px;margin-bottom:10px;">${label}</div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
          padding:18px 20px;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;">
            <div style="font-size:12px;color:var(--text-3);">
              ${count} receipt${count !== 1 ? 's' : ''}
            </div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:18px;
              font-weight:700;color:var(--text);">${fmt(total)}</div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
            <div style="padding:10px 12px;background:var(--cash-bg);
              border:1px solid var(--cash-border);border-radius:var(--radius-sm);">
              <div style="font-size:10px;font-weight:700;color:var(--cash-text);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">Cash</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                font-weight:700;color:var(--cash-strong);">${fmt(cash)}</div>
              <div style="font-size:10px;color:var(--cash-text);margin-top:2px;">${cashPct}%</div>
            </div>
            <div style="padding:10px 12px;background:var(--momo-bg);
              border:1px solid var(--momo-border);border-radius:var(--radius-sm);">
              <div style="font-size:10px;font-weight:700;color:var(--momo-text);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">MoMo</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                font-weight:700;color:var(--momo-strong);">${fmt(momo)}</div>
              <div style="font-size:10px;color:var(--momo-text);margin-top:2px;">${momoPct}%</div>
            </div>
            <div style="padding:10px 12px;background:var(--pos-bg);
              border:1px solid var(--pos-border);border-radius:var(--radius-sm);">
              <div style="font-size:10px;font-weight:700;color:var(--pos-text);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">POS</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                font-weight:700;color:var(--pos-strong);">${fmt(pos)}</div>
              <div style="font-size:10px;color:var(--pos-text);margin-top:2px;">${posPct}%</div>
            </div>
          </div>
        </div>`;
    } catch {
      el.innerHTML = `
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
          letter-spacing:0.8px;margin-bottom:10px;">${label}</div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
          padding:16px 20px;font-size:13px;color:var(--text-3);">
          Could not load.
        </div>`;
    }
  }

 async function _loadReceiptsList() {
    const content = document.getElementById('receipts-tab-content');
    if (!content) return;

    content.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;
        padding:60px;color:var(--text-3);gap:10px;font-size:13px;">
        <span class="spin"></span> Loading…
      </div>`;

    try {
      const res  = await Auth.fetch('/api/v1/finance/cashier/receipts/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const items = data.results || data;
      const fmt   = n => `GHS ${Number(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;

      if (!items.length) {
        content.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);font-size:13px;">
            No receipts yet.
          </div>`;
        return;
      }

      const rows = items.map(r => {
        const method = r.payment_method || '—';
        const methodColor = { CASH: 'var(--cash-text)', MOMO: 'var(--momo-text)', POS: 'var(--pos-text)' }[method] || 'var(--text-3)';
        const methodBg    = { CASH: 'var(--cash-bg)',   MOMO: 'var(--momo-bg)',   POS: 'var(--pos-bg)'   }[method] || 'var(--bg)';
        const date = r.created_at
          ? new Date(r.created_at).toLocaleString('en-GB', {
              day: 'numeric', month: 'short', year: 'numeric',
              hour: '2-digit', minute: '2-digit',
            })
          : '—';
        return `
          <tr>
            <td style="padding:12px 16px;border-bottom:1px solid var(--border);">
              <div style="font-family:'JetBrains Mono',monospace;font-size:12px;
                font-weight:600;color:var(--text);">${_esc(r.receipt_number || '—')}</div>
              <div style="font-size:11px;color:var(--text-3);margin-top:2px;">${date}</div>
            </td>
            <td style="padding:12px 16px;border-bottom:1px solid var(--border);
              font-size:13px;color:var(--text-2);">
              ${_esc(r.job_number || '—')}
            </td>
            <td style="padding:12px 16px;border-bottom:1px solid var(--border);">
              <span style="padding:2px 8px;border-radius:5px;font-size:10.5px;font-weight:700;
                background:${methodBg};color:${methodColor};">${method}</span>
            </td>
            <td style="padding:12px 16px;border-bottom:1px solid var(--border);
              text-align:right;font-family:'JetBrains Mono',monospace;font-size:13px;
              font-weight:700;color:var(--text);">${fmt(r.amount_paid)}</td>
          </tr>`;
      }).join('');

      content.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);">
                <th style="text-align:left;padding:10px 16px;font-size:10.5px;font-weight:700;
                  letter-spacing:0.8px;text-transform:uppercase;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Receipt</th>
                <th style="text-align:left;padding:10px 16px;font-size:10.5px;font-weight:700;
                  letter-spacing:0.8px;text-transform:uppercase;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Job</th>
                <th style="text-align:left;padding:10px 16px;font-size:10.5px;font-weight:700;
                  letter-spacing:0.8px;text-transform:uppercase;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Method</th>
                <th style="text-align:right;padding:10px 16px;font-size:10.5px;font-weight:700;
                  letter-spacing:0.8px;text-transform:uppercase;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Amount</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
    } catch {
      content.innerHTML = `
        <div style="text-align:center;padding:60px;color:var(--text-3);font-size:13px;">
          Could not load receipts.
        </div>`;
    }
  }

  async function _loadHistoryLevel(level, params = {}) {
    const content = document.getElementById('receipts-tab-content');
    if (!content) return;
    const qp = new URLSearchParams({ level });
    if (params.year)  qp.set('year',  params.year);
    if (params.month) qp.set('month', params.month);
    if (params.week)  qp.set('week',  params.week);
    try {
      const res  = await Auth.fetch(`/api/v1/finance/cashier/history/?${qp}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      _renderHistoryLevel(data, params);
    } catch {
      content.innerHTML = `
        <div style="text-align:center;padding:60px;color:var(--text-3);font-size:13px;">
          Could not load history.
        </div>`;
    }
  }

  async function _loadHistoryLevel(level, params = {}) {
    const content = document.getElementById('receipts-tab-content');
    if (!content) return;
    content.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;
        padding:60px;color:var(--text-3);gap:10px;font-size:13px;">
        <span class="spin"></span> Loading…
      </div>`;
    const qp = new URLSearchParams({ level });
    if (params.year)  qp.set('year',  params.year);
    if (params.month) qp.set('month', params.month);
    if (params.week)  qp.set('week',  params.week);
    try {
      const res  = await Auth.fetch(`/api/v1/finance/cashier/history/?${qp}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      _renderHistoryLevel(data, params);
    } catch {
      content.innerHTML = `
        <div style="text-align:center;padding:60px;color:var(--text-3);font-size:13px;">
          Could not load history.
        </div>`;
    }
  }

  function _renderHistoryLevel(data, params) {
    const content = document.getElementById('receipts-tab-content');
    if (!content) return;
    const results = data.results || [];
    const level   = data.level;
    const fmt     = n => `GHS ${Number(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;

    const crumbs = [];
    crumbs.push(`<span style="color:var(--text-3);cursor:pointer;font-size:12.5px;"
      onclick="Cashier._historyDrillUp('year')">All Years</span>`);
    if (params.year) {
      crumbs.push(`<span style="color:var(--text-3);">›</span>`);
      if (level === 'month') {
        crumbs.push(`<span style="color:var(--text);font-size:12.5px;font-weight:600;">${params.year}</span>`);
      } else {
        crumbs.push(`<span style="color:var(--text-3);cursor:pointer;font-size:12.5px;"
          onclick="Cashier._historyDrillUp('month',${params.year})">${params.year}</span>`);
      }
    }
    if (params.month && params.year) {
      const mn = ['','Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      crumbs.push(`<span style="color:var(--text-3);">›</span>`);
      if (level === 'week') {
        crumbs.push(`<span style="color:var(--text);font-size:12.5px;font-weight:600;">${mn[params.month]}</span>`);
      } else {
        crumbs.push(`<span style="color:var(--text-3);cursor:pointer;font-size:12.5px;"
          onclick="Cashier._historyDrillUp('week',${params.year},${params.month})">${mn[params.month]}</span>`);
      }
    }
    if (params.week) {
      crumbs.push(`<span style="color:var(--text-3);">›</span>`);
      crumbs.push(`<span style="color:var(--text);font-size:12.5px;font-weight:600;">Week ${params.week}</span>`);
    }

    const breadcrumb = crumbs.length > 1
      ? `<div style="display:flex;align-items:center;gap:6px;margin-bottom:16px;">${crumbs.join('')}</div>`
      : '';

    if (!results.length) {
      content.innerHTML = breadcrumb + `
        <div style="text-align:center;padding:60px;color:var(--text-3);font-size:13px;">
          No activity found for this period.
        </div>`;
      return;
    }

    const isDrillable = level !== 'day';
    const cards = results.map(row => {
      const total   = row.total || 0;
      const cashPct = total > 0 ? (row.cash / total * 100).toFixed(0) : 0;
      const momoPct = total > 0 ? (row.momo / total * 100).toFixed(0) : 0;
      const posPct  = total > 0 ? (row.pos  / total * 100).toFixed(0) : 0;
      const drill   = isDrillable
        ? `onclick="Cashier._historyDrillDown(${JSON.stringify(row).replace(/"/g, '&quot;')})"
           style="cursor:pointer;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;transition:border-color 0.15s;"`
        : `style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:18px 20px;"`;
      return `
        <div ${drill}>
          <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:14px;">
            <div>
              <div style="font-family:'Syne',sans-serif;font-size:15px;font-weight:700;color:var(--text);">
                ${_esc(row.label)}
              </div>
              <div style="font-size:12px;color:var(--text-3);margin-top:2px;">
                ${row.count} receipt${row.count !== 1 ? 's' : ''}
                ${isDrillable ? ' · <span style="color:var(--text-3);">drill down →</span>' : ''}
              </div>
            </div>
            <div style="text-align:right;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:16px;font-weight:700;color:var(--text);">
                ${fmt(total)}
              </div>
              <div style="font-size:11px;color:var(--text-3);margin-top:2px;">total collected</div>
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
            <div style="padding:10px 12px;background:var(--cash-bg);border:1px solid var(--cash-border);border-radius:var(--radius-sm);">
              <div style="font-size:10px;font-weight:700;color:var(--cash-text);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Cash</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:var(--cash-strong);">${fmt(row.cash)}</div>
              <div style="font-size:11px;color:var(--cash-text);margin-top:2px;">${cashPct}%</div>
            </div>
            <div style="padding:10px 12px;background:var(--momo-bg);border:1px solid var(--momo-border);border-radius:var(--radius-sm);">
              <div style="font-size:10px;font-weight:700;color:var(--momo-text);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">MoMo</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:var(--momo-strong);">${fmt(row.momo)}</div>
              <div style="font-size:11px;color:var(--momo-text);margin-top:2px;">${momoPct}%</div>
            </div>
            <div style="padding:10px 12px;background:var(--pos-bg);border:1px solid var(--pos-border);border-radius:var(--radius-sm);">
              <div style="font-size:10px;font-weight:700;color:var(--pos-text);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">POS</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:var(--pos-strong);">${fmt(row.pos)}</div>
              <div style="font-size:11px;color:var(--pos-text);margin-top:2px;">${posPct}%</div>
            </div>
          </div>
        </div>`;
    }).join('');

    content.innerHTML = breadcrumb + `<div style="display:flex;flex-direction:column;gap:10px;">${cards}</div>`;
  }

  function _historyDrillDown(row) {
    if (row.year !== undefined && row.month === undefined) {
      _loadHistoryLevel('month', { year: row.year });
    } else if (row.month !== undefined && row.week === undefined) {
      _loadHistoryLevel('week', { year: row.year, month: row.month });
    } else if (row.week !== undefined) {
      _loadHistoryLevel('day', { year: row.year, month: row.month, week: row.week });
    }
  }

  function _historyDrillUp(level, year, month) {
    if (level === 'year')       _loadHistoryLevel('year');
    else if (level === 'month') _loadHistoryLevel('month', { year });
    else if (level === 'week')  _loadHistoryLevel('week',  { year, month });
  }
  // ── Partial credit helpers ─────────────────────────────────
  function _initPartialCredit() {
    if (!activeJob?.customer_credit) return;
    const credit = activeJob.customer_credit;
    const fmt    = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

    const nameEl      = document.getElementById('pc-customer-name');
    const availEl     = document.getElementById('pc-available');
    const balanceEl   = document.getElementById('pc-balance');
    const amountInput = document.getElementById('pc-amount');
    const preview     = document.getElementById('pc-credit-preview');
    const errorEl     = document.getElementById('pc-credit-error');

    if (nameEl)    nameEl.textContent    = credit.display_name;
    if (availEl)   availEl.textContent   = fmt(credit.available_credit);
    if (balanceEl) balanceEl.textContent = fmt(credit.current_balance);
    if (amountInput) amountInput.value   = '';
    if (preview)   preview.style.display = 'none';
    if (errorEl)   errorEl.style.display = 'none';

    // Pre-fill with full amount so cashier just edits down
    const due = parseFloat(activeJob.estimated_cost || 0);
    if (amountInput) amountInput.value = due.toFixed(2);
    _updatePartialCredit();
  }

  function _updatePartialCredit() {
    if (!activeJob?.customer_credit) return;
    const credit      = activeJob.customer_credit;
    const due         = parseFloat(activeJob.estimated_cost || 0);
    const collected   = parseFloat(document.getElementById('pc-amount')?.value || 0);
    const creditPortion = due - collected;
    const available   = parseFloat(credit.available_credit);
    const fmt         = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

    const preview     = document.getElementById('pc-credit-preview');
    const errorEl     = document.getElementById('pc-credit-error');
    const creditAmtEl = document.getElementById('pc-credit-amount');
    const creditNameEl= document.getElementById('pc-credit-name');
    const method      = document.getElementById('pc-method')?.value || 'CASH';
    const refField    = document.getElementById('pc-ref-field');
    const refLabel    = document.getElementById('pc-ref-label');
    const refInput    = document.getElementById('pc-ref');

    // Show/hide reference field
    if (refField) refField.style.display = method !== 'CASH' ? 'block' : 'none';
    if (refLabel) refLabel.innerHTML = method === 'MOMO'
      ? 'MoMo Reference (11 digits) <span style="color:var(--red-text);">*</span>'
      : 'POS Approval Code <span style="color:var(--red-text);">*</span>';
    if (refInput) refInput.placeholder = method === 'MOMO' ? '11-digit reference' : 'Approval code';

    if (collected <= 0 || collected > due) {
      if (preview)  preview.style.display  = 'none';
      if (errorEl)  errorEl.style.display  = 'none';
      _updateConfirmBtn();
      return;
    }

    if (creditPortion <= 0) {
      // Full payment — no credit needed
      if (preview)  preview.style.display  = 'none';
      if (errorEl)  errorEl.style.display  = 'none';
      _updateConfirmBtn();
      return;
    }

    if (creditPortion > available) {
      if (preview) preview.style.display = 'none';
      if (errorEl) {
        errorEl.textContent   = `Credit shortfall: ${fmt(creditPortion)} needed but only ${fmt(available)} available. Customer must pay at least ${fmt(due - available)}.`;
        errorEl.style.display = 'block';
      }
      _updateConfirmBtn();
      return;
    }

    // Valid partial credit
    if (errorEl) errorEl.style.display  = 'none';
    if (preview) {
      preview.style.display = 'block';
      if (creditAmtEl)  creditAmtEl.textContent  = fmt(creditPortion);
      if (creditNameEl) creditNameEl.textContent = credit.display_name;
    }
    _updateConfirmBtn();
  }

  function _validatePartialCredit() {
    if (!activeJob?.customer_credit) return { valid: false, error: 'No credit account found.' };
    const credit      = activeJob.customer_credit;
    const due         = parseFloat(activeJob.estimated_cost || 0);
    const collected   = parseFloat(document.getElementById('pc-amount')?.value || 0);
    const method      = document.getElementById('pc-method')?.value || 'CASH';
    const ref         = document.getElementById('pc-ref')?.value.trim() || '';
    const creditPortion = due - collected;
    const available   = parseFloat(credit.available_credit);

    if (!collected || collected <= 0)
      return { valid: false, error: 'Enter the amount collected from customer.' };
    if (collected > due)
      return { valid: false, error: 'Amount collected cannot exceed the total due.' };
    if (creditPortion > available)
      return { valid: false, error: `Only ${available} available — customer must pay at least GHS ${(due - available).toFixed(2)}.` };
    if (method === 'MOMO' && !/^\d{11}$/.test(ref))
      return { valid: false, error: 'MoMo reference must be exactly 11 digits.' };
    if (method === 'POS' && !ref)
      return { valid: false, error: 'POS approval code is required.' };

    return { valid: true };
  }

  // ── Split payment helpers ──────────────────────────────────
  function _validateSplitLegs() {
    const method1 = document.getElementById('split-method-1')?.value || 'MOMO';
    const method2 = document.getElementById('split-method-2')?.value || 'CASH';
    const amount1 = parseFloat(document.getElementById('split-amount-1')?.value || 0);
    const amount2 = parseFloat(document.getElementById('split-amount-2')?.value || 0);
    const ref1    = document.getElementById('split-ref-1-input')?.value.trim() || '';
    const ref2    = document.getElementById('split-ref-2-input')?.value.trim() || '';

    if (!amount1 || amount1 <= 0) return { valid: false, error: 'Enter amount for first payment leg.' };
    if (!amount2 || amount2 <= 0) return { valid: false, error: 'Second payment amount is 0 — adjust first amount.' };

    if (method1 === 'MOMO') {
      if (!ref1) return { valid: false, error: 'MoMo reference required for first leg.' };
      if (!/^\d{11}$/.test(ref1)) return { valid: false, error: 'First leg MoMo reference must be exactly 11 digits.' };
    }
    if (method1 === 'POS') {
      if (!ref1) return { valid: false, error: 'POS approval code required for first leg.' };
    }
    if (method2 === 'MOMO') {
      if (!ref2) return { valid: false, error: 'MoMo reference required for second leg.' };
      if (!/^\d{11}$/.test(ref2)) return { valid: false, error: 'Second leg MoMo reference must be exactly 11 digits.' };
    }
    if (method2 === 'POS') {
      if (!ref2) return { valid: false, error: 'POS approval code required for second leg.' };
    }
    if (method1 === method2) return { valid: false, error: 'Both legs cannot use the same payment method.' };

    const legs = [
      { method: method1, amount: amount1.toFixed(2), reference: ref1 },
      { method: method2, amount: amount2.toFixed(2), reference: ref2 },
    ];

    return { valid: true, legs };
  }

  function _updateSplitRemainder() {
    if (!activeJob) return;
    const total   = parseFloat(activeJob.estimated_cost || 0);
    const amount1 = parseFloat(document.getElementById('split-amount-1')?.value || 0);
    const remain  = Math.max(0, total - amount1);

    const amount2El = document.getElementById('split-amount-2');
    if (amount2El) amount2El.value = remain > 0 ? remain.toFixed(2) : '';

    const indicator = document.getElementById('split-balance-indicator');
    if (indicator) {
      const fmt = n => `GHS ${n.toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
      if (amount1 > total) {
        indicator.style.color = 'var(--red-text)';
        indicator.textContent = `First leg (${fmt(amount1)}) exceeds total (${fmt(total)})`;
      } else if (amount1 > 0) {
        indicator.style.color = 'var(--text-3)';
        indicator.textContent = `${fmt(amount1)} + ${fmt(remain)} = ${fmt(total)}`;
      } else {
        indicator.textContent = '';
      }
    }
    _updateConfirmBtn();
  }

  function _updateSplitFields() {
    const method1 = document.getElementById('split-method-1')?.value || 'MOMO';
    const method2 = document.getElementById('split-method-2')?.value || 'CASH';

    // Show/hide reference fields
    const ref1El     = document.getElementById('split-ref-1');
    const ref1Label  = document.getElementById('split-ref-1-label');
    const ref1Input  = document.getElementById('split-ref-1-input');
    const ref2El     = document.getElementById('split-ref-2');
    const ref2Label  = document.getElementById('split-ref-2-label');
    const ref2Input  = document.getElementById('split-ref-2-input');

    if (ref1El) ref1El.style.display = ['MOMO','POS'].includes(method1) ? 'block' : 'none';
    if (ref1Label && ref1Input) {
      ref1Label.innerHTML = method1 === 'MOMO'
        ? 'MoMo Reference (11 digits) <span class="cm-req">*</span>'
        : 'POS Approval Code <span class="cm-req">*</span>';
      ref1Input.placeholder = method1 === 'MOMO' ? '11-digit reference' : 'Approval code';
    }

    if (ref2El) ref2El.style.display = ['MOMO','POS'].includes(method2) ? 'block' : 'none';
    if (ref2Label && ref2Input) {
      ref2Label.innerHTML = method2 === 'MOMO'
        ? 'MoMo Reference (11 digits) <span class="cm-req">*</span>'
        : 'POS Approval Code <span class="cm-req">*</span>';
      ref2Input.placeholder = method2 === 'MOMO' ? '11-digit reference' : 'Approval code';
    }

    _updateConfirmBtn();
  }

  // ── Credit Accounts pane ───────────────────────────────────
  let _creditAccounts  = [];
  let _activeAccount   = null;

function _renderCreditPane(container) {
    container.innerHTML = `
      <div style="font-family:'Syne',sans-serif;font-size:19px;font-weight:800;
        color:var(--text);letter-spacing:-0.3px;margin-bottom:4px;">Credit Accounts</div>
      <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
        All active credit accounts at this branch.
      </div>

      <!-- Search -->
      <div style="position:relative;margin-bottom:20px;">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
          fill="none" stroke="currentColor" stroke-width="2"
          style="position:absolute;left:12px;top:50%;transform:translateY(-50%);
            color:var(--text-3);pointer-events:none;">
          <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
        </svg>
        <input type="text" id="credit-search" placeholder="Filter by name, phone or company…"
          oninput="Cashier._creditFilter(this.value)"
          style="width:100%;padding:10px 14px 10px 38px;border:1.5px solid var(--border);
            border-radius:var(--radius-sm);background:var(--panel);color:var(--text);
            font-size:13px;font-family:inherit;outline:none;box-sizing:border-box;
            transition:border-color 0.15s;"
          onfocus="this.style.borderColor='var(--border-dark)'"
          onblur="this.style.borderColor='var(--border)'">
      </div>

      <!-- Results -->
      <div id="credit-results">
        <div style="text-align:center;padding:40px;color:var(--text-3);
          font-size:13px;display:flex;align-items:center;justify-content:center;gap:8px;">
          <span class="spin"></span> Loading…
        </div>
      </div>

      <!-- Settlement modal -->
      <div id="settle-overlay" style="display:none;position:fixed;inset:0;
        background:rgba(10,10,10,0.48);backdrop-filter:blur(4px);
        z-index:600;align-items:center;justify-content:center;padding:20px;">
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:20px;width:100%;max-width:440px;
          box-shadow:0 24px 64px rgba(0,0,0,0.18);overflow:hidden;">
          <div style="padding:20px 22px 16px;border-bottom:1px solid var(--border);
            display:flex;align-items:center;justify-content:space-between;">
            <div>
              <div style="font-family:'Syne',sans-serif;font-size:16px;font-weight:800;
                color:var(--text);">Settle Credit</div>
              <div style="font-size:11px;color:var(--text-3);margin-top:2px;"
                id="settle-customer-name">—</div>
            </div>
            <button onclick="Cashier._closeSettle()"
              style="width:28px;height:28px;border-radius:50%;border:1px solid var(--border);
                background:var(--bg);display:flex;align-items:center;justify-content:center;
                cursor:pointer;color:var(--text-2);font-size:16px;">×</button>
          </div>
          <div style="padding:20px 22px;display:flex;flex-direction:column;gap:14px;">
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
              <div style="padding:10px 12px;background:var(--red-bg);
                border:1px solid var(--red-border);border-radius:var(--radius-sm);">
                <div style="font-size:10px;font-weight:700;color:var(--red-text);
                  text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">Owed</div>
                <div id="settle-balance" style="font-family:'JetBrains Mono',monospace;
                  font-size:14px;font-weight:700;color:var(--red-text);">—</div>
              </div>
              <div style="padding:10px 12px;background:var(--green-bg);
                border:1px solid var(--green-border);border-radius:var(--radius-sm);">
                <div style="font-size:10px;font-weight:700;color:var(--green-text);
                  text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">Available</div>
                <div id="settle-available" style="font-family:'JetBrains Mono',monospace;
                  font-size:14px;font-weight:700;color:var(--green-text);">—</div>
              </div>
              <div style="padding:10px 12px;background:var(--bg);
                border:1px solid var(--border);border-radius:var(--radius-sm);">
                <div style="font-size:10px;font-weight:700;color:var(--text-3);
                  text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">Limit</div>
                <div id="settle-limit" style="font-family:'JetBrains Mono',monospace;
                  font-size:14px;font-weight:700;color:var(--text);">—</div>
              </div>
            </div>
            <div>
              <div style="font-size:11px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">
                Amount (GHS) <span style="color:var(--red-text);">*</span>
              </div>
              <input type="number" id="settle-amount" min="0.01" step="0.01"
                placeholder="0.00" oninput="Cashier._settleUpdateBtn()"
                style="width:100%;padding:10px 14px;border:1.5px solid var(--border);
                  border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                  font-size:16px;font-family:'JetBrains Mono',monospace;
                  box-sizing:border-box;outline:none;">
            </div>
            <div>
              <div style="font-size:11px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Method</div>
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
                ${['CASH','MOMO','POS'].map(m => `
                  <button id="settle-pm-${m}" onclick="Cashier._settleSelectMethod('${m}')"
                    style="padding:9px;border:1.5px solid var(--border);
                      border-radius:var(--radius-sm);background:var(--bg);
                      font-size:12px;font-weight:700;cursor:pointer;
                      font-family:inherit;color:var(--text-2);transition:all 0.15s;">
                    ${m}
                  </button>`).join('')}
              </div>
            </div>
            <div id="settle-ref-field" style="display:none;">
              <div style="font-size:11px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;"
                id="settle-ref-label">Reference <span style="color:var(--red-text);">*</span>
              </div>
              <input type="text" id="settle-ref" placeholder="—"
                oninput="Cashier._settleUpdateBtn()"
                style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                  border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                  font-size:13px;font-family:'JetBrains Mono',monospace;
                  box-sizing:border-box;outline:none;">
            </div>
            <div id="settle-error"
              style="display:none;font-size:12px;color:var(--red-text);
                padding:8px 12px;background:var(--red-bg);border:1px solid var(--red-border);
                border-radius:var(--radius-sm);">
            </div>
            <button id="settle-confirm-btn" onclick="Cashier._submitSettle()"
              disabled
              style="width:100%;padding:12px;background:var(--text);color:#fff;
                border:none;border-radius:var(--radius-sm);font-size:14px;font-weight:700;
                font-family:inherit;cursor:pointer;opacity:0.4;transition:opacity 0.15s;">
              Confirm Settlement
            </button>
          </div>
        </div>
      </div>`;

    // Load all accounts immediately
    _loadAllCreditAccounts();
  }

  let _settleMethod = 'CASH';

  async function _loadAllCreditAccounts() {
    const results = document.getElementById('credit-results');
    if (!results) return;
    try {
      const res  = await Auth.fetch('/api/v1/customers/credit/?status=ACTIVE');
      if (!res.ok) throw new Error();
      const data = await res.json();
      _creditAccounts = Array.isArray(data) ? data : (data.results || []);

      // Also load suspended accounts with balance
      const res2  = await Auth.fetch('/api/v1/customers/credit/?status=SUSPENDED');
      if (res2.ok) {
        const data2 = await res2.json();
        const suspended = (Array.isArray(data2) ? data2 : (data2.results || []))
          .filter(a => parseFloat(a.current_balance) > 0);
        _creditAccounts = [..._creditAccounts, ...suspended];
      }

      _renderCreditGrid(_creditAccounts);
    } catch {
      results.innerHTML = `<div style="text-align:center;padding:40px;
        color:var(--red-text);font-size:13px;">Could not load credit accounts.</div>`;
    }
  }

  function _creditFilter(query) {
    const q = query.trim().toLowerCase();
    if (!q) { _renderCreditGrid(_creditAccounts); return; }
    const filtered = _creditAccounts.filter(a =>
      (a.customer_name   || '').toLowerCase().includes(q) ||
      (a.customer_phone  || '').toLowerCase().includes(q) ||
      (a.organisation_name || '').toLowerCase().includes(q)
    );
    _renderCreditGrid(filtered);
  }

  function _renderCreditGrid(accounts) {
    const results = document.getElementById('credit-results');
    if (!results) return;

    if (!accounts.length) {
      results.innerHTML = `<div style="text-align:center;padding:60px;
        color:var(--text-3);font-size:13px;">No credit accounts found.</div>`;
      return;
    }

    const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

    results.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
        ${accounts.map(a => {
          const pct      = parseFloat(a.utilisation_pct || 0);
          const barColor = pct >= 90 ? 'var(--red-text)' : pct >= 70 ? 'var(--amber-text)' : 'var(--green-text)';
          const statusColor = { ACTIVE:'var(--green-text)', SUSPENDED:'var(--red-text)' }[a.status] || 'var(--text-3)';
          const statusBg    = { ACTIVE:'var(--green-bg)',   SUSPENDED:'var(--red-bg)'   }[a.status] || 'var(--bg)';
          const hasBalance  = parseFloat(a.current_balance) > 0;

          return `
            <div style="background:var(--panel);border:1px solid var(--border);
              border-radius:var(--radius);padding:16px 18px;display:flex;
              flex-direction:column;gap:12px;">

              <!-- Name + status -->
              <div style="display:flex;align-items:flex-start;
                justify-content:space-between;gap:8px;">
                <div style="min-width:0;">
                  <div style="font-size:14px;font-weight:700;color:var(--text);
                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                    ${_esc(a.customer_name)}
                  </div>
                  <div style="font-size:11px;color:var(--text-3);margin-top:2px;
                    white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
                    ${_esc(a.customer_phone || '—')}
                    ${a.organisation_name ? ' · ' + _esc(a.organisation_name) : ''}
                  </div>
                </div>
                <span style="flex-shrink:0;padding:2px 8px;border-radius:20px;
                  font-size:10px;font-weight:700;
                  background:${statusBg};color:${statusColor};">
                  ${a.status}
                </span>
              </div>

              <!-- Balance row -->
              <div style="display:grid;grid-template-columns:1fr 1fr;gap:6px;">
                <div style="padding:8px 10px;background:var(--red-bg);
                  border:1px solid var(--red-border);border-radius:var(--radius-sm);">
                  <div style="font-size:9px;font-weight:700;color:var(--red-text);
                    text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px;">Owed</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                    font-weight:700;color:var(--red-text);">${fmt(a.current_balance)}</div>
                </div>
                <div style="padding:8px 10px;background:var(--green-bg);
                  border:1px solid var(--green-border);border-radius:var(--radius-sm);">
                  <div style="font-size:9px;font-weight:700;color:var(--green-text);
                    text-transform:uppercase;letter-spacing:0.5px;margin-bottom:2px;">Available</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                    font-weight:700;color:var(--green-text);">${fmt(a.available_credit)}</div>
                </div>
              </div>

              <!-- Utilisation bar -->
              <div>
                <div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden;">
                  <div style="height:100%;width:${Math.min(pct,100)}%;
                    background:${barColor};border-radius:2px;"></div>
                </div>
                <div style="display:flex;justify-content:space-between;margin-top:3px;">
                  <span style="font-size:10px;color:var(--text-3);">
                    Limit: ${fmt(a.credit_limit)}
                  </span>
                  <span style="font-size:10px;font-weight:700;color:${barColor};">
                    ${pct}%
                  </span>
                </div>
              </div>

              <!-- Actions -->
              <div style="display:flex;gap:6px;margin-top:auto;">
                ${hasBalance ? `
                  <button onclick="Cashier._openSettle(${a.id})"
                    style="flex:1;padding:7px;
                      background:${a.status === 'SUSPENDED' ? 'var(--red-text)' : 'var(--text)'};
                      color:#fff;border:none;border-radius:var(--radius-sm);
                      font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;">
                      ${a.status === 'SUSPENDED' ? 'Settle to Reactivate' : 'Settle'}
                  </button>` : `
                  <div style="flex:1;padding:7px;text-align:center;font-size:12px;
                    color:var(--green-text);font-weight:600;">✓ Cleared</div>`}
                <button onclick="Cashier._viewPaymentHistory(${a.id})"
                  style="padding:7px 12px;background:none;border:1px solid var(--border);
                    border-radius:var(--radius-sm);font-size:12px;font-weight:600;
                    cursor:pointer;font-family:inherit;color:var(--text-2);
                    transition:border-color 0.15s;"
                  onmouseover="this.style.borderColor='var(--border-dark)'"
                  onmouseout="this.style.borderColor='var(--border)'">
                  History
                </button>
              </div>
            </div>`;
        }).join('')}
      </div>`;
  }

  function _renderCreditResults(accounts) {
    const results = document.getElementById('credit-results');
    if (!results) return;

    if (!accounts.length) {
      results.innerHTML = `<div style="text-align:center;padding:60px;
        color:var(--text-3);font-size:13px;">No credit accounts found.</div>`;
      return;
    }

    const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

    results.innerHTML = accounts.map(a => {
      const pct        = parseFloat(a.utilisation_pct || 0);
      const barColor   = pct >= 90 ? 'var(--red-text)' : pct >= 70 ? 'var(--amber-text)' : 'var(--green-text)';
      const statusColor = {
        ACTIVE   : 'var(--green-text)',
        PENDING  : 'var(--amber-text)',
        SUSPENDED: 'var(--red-text)',
        CLOSED   : 'var(--text-3)',
      }[a.status] || 'var(--text-3)';
      const statusBg = {
        ACTIVE   : 'var(--green-bg)',
        PENDING  : 'var(--amber-bg)',
        SUSPENDED: 'var(--red-bg)',
        CLOSED   : 'var(--bg)',
      }[a.status] || 'var(--bg)';

      return `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:18px 20px;margin-bottom:12px;">

          <!-- Customer + status -->
          <div style="display:flex;align-items:center;justify-content:space-between;
            margin-bottom:14px;">
            <div>
              <div style="font-size:15px;font-weight:700;color:var(--text);">
                ${_esc(a.customer_name)}
              </div>
              <div style="font-size:12px;color:var(--text-3);margin-top:2px;">
                ${_esc(a.customer_phone || '—')}
                ${a.organisation_name ? ' · ' + _esc(a.organisation_name) : ''}
              </div>
            </div>
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;
              background:${statusBg};color:${statusColor};">
              ${a.status}
            </span>
          </div>

          <!-- Balance grid -->
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:14px;">
            <div style="padding:10px 12px;background:var(--red-bg);
              border:1px solid var(--red-border);border-radius:var(--radius-sm);">
              <div style="font-size:10px;font-weight:700;color:var(--red-text);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">Balance</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:14px;
                font-weight:700;color:var(--red-text);">${fmt(a.current_balance)}</div>
            </div>
            <div style="padding:10px 12px;background:var(--green-bg);
              border:1px solid var(--green-border);border-radius:var(--radius-sm);">
              <div style="font-size:10px;font-weight:700;color:var(--green-text);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">Available</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:14px;
                font-weight:700;color:var(--green-text);">${fmt(a.available_credit)}</div>
            </div>
            <div style="padding:10px 12px;background:var(--bg);
              border:1px solid var(--border);border-radius:var(--radius-sm);">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">Limit</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:14px;
                font-weight:700;color:var(--text);">${fmt(a.credit_limit)}</div>
            </div>
          </div>

          <!-- Utilisation bar -->
          <div style="margin-bottom:14px;">
            <div style="display:flex;justify-content:space-between;align-items:center;
              margin-bottom:5px;">
              <span style="font-size:11px;color:var(--text-3);">Utilisation</span>
              <span style="font-size:11px;font-weight:700;color:${barColor};">${pct}%</span>
            </div>
            <div style="height:5px;background:var(--border);border-radius:3px;overflow:hidden;">
              <div style="height:100%;width:${Math.min(pct,100)}%;
                background:${barColor};border-radius:3px;transition:width 0.4s;"></div>
            </div>
          </div>

          <!-- Actions -->
          <div style="display:flex;gap:8px;">
            ${a.status === 'ACTIVE' && parseFloat(a.current_balance) > 0 ? `
              <button onclick="Cashier._openSettle(${a.id})"
                style="flex:1;padding:9px;background:var(--text);color:#fff;border:none;
                  border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                  cursor:pointer;font-family:inherit;">
                Settle Balance
              </button>` : ''}
            ${a.status === 'SUSPENDED' && parseFloat(a.current_balance) > 0 ? `
              <button onclick="Cashier._openSettle(${a.id})"
                style="flex:1;padding:9px;background:var(--red-text);color:#fff;border:none;
                  border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                  cursor:pointer;font-family:inherit;">
                Settle to Reactivate
              </button>` : ''}
            <button onclick="Cashier._viewPaymentHistory(${a.id})"
              style="padding:9px 16px;background:none;border:1px solid var(--border);
                border-radius:var(--radius-sm);font-size:13px;font-weight:600;
                cursor:pointer;font-family:inherit;color:var(--text-2);
                transition:border-color 0.15s;"
              onmouseover="this.style.borderColor='var(--border-dark)'"
              onmouseout="this.style.borderColor='var(--border)'">
              History
            </button>
          </div>
        </div>`;
    }).join('');
  }

  function _openSettle(accountId) {
    _activeAccount = _creditAccounts.find(a => a.id === accountId);
    if (!_activeAccount) return;

    const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

    const nameEl      = document.getElementById('settle-customer-name');
    const balanceEl   = document.getElementById('settle-balance');
    const availableEl = document.getElementById('settle-available');
    const limitEl     = document.getElementById('settle-limit');
    const amountEl    = document.getElementById('settle-amount');
    const errorEl     = document.getElementById('settle-error');
    const refEl       = document.getElementById('settle-ref');

    if (nameEl)      nameEl.textContent      = _activeAccount.customer_name;
    if (balanceEl)   balanceEl.textContent   = fmt(_activeAccount.current_balance);
    if (availableEl) availableEl.textContent = fmt(_activeAccount.available_credit);
    if (limitEl)     limitEl.textContent     = fmt(_activeAccount.credit_limit);
    if (amountEl)    amountEl.value          = '';
    if (errorEl)     errorEl.style.display   = 'none';
    if (refEl)       refEl.value             = '';

    _settleMethod = 'CASH';
    _settleSelectMethod('CASH');

    const overlay = document.getElementById('settle-overlay');
    if (overlay) overlay.style.display = 'flex';
  }

  function _closeSettle() {
    const overlay = document.getElementById('settle-overlay');
    if (overlay) overlay.style.display = 'none';
    _activeAccount = null;
  }

  function _settleSelectMethod(method) {
    _settleMethod = method;
    ['CASH','MOMO','POS'].forEach(m => {
      const btn = document.getElementById(`settle-pm-${m}`);
      if (!btn) return;
      const colors = {
        CASH: { border: 'var(--cash-strong)', bg: 'var(--cash-bg)', color: 'var(--cash-text)' },
        MOMO: { border: 'var(--momo-strong)', bg: 'var(--momo-bg)', color: 'var(--momo-text)' },
        POS : { border: 'var(--pos-strong)',  bg: 'var(--pos-bg)',  color: 'var(--pos-text)'  },
      };
      if (m === method) {
        btn.style.borderColor = colors[m].border;
        btn.style.background  = colors[m].bg;
        btn.style.color       = colors[m].color;
      } else {
        btn.style.borderColor = 'var(--border)';
        btn.style.background  = 'var(--bg)';
        btn.style.color       = 'var(--text-2)';
      }
    });

    const refField = document.getElementById('settle-ref-field');
    const refLabel = document.getElementById('settle-ref-label');
    const refInput = document.getElementById('settle-ref');
    if (refField) refField.style.display = method !== 'CASH' ? 'block' : 'none';
    if (refLabel) refLabel.innerHTML = method === 'MOMO'
      ? 'MoMo Reference (11 digits) <span style="color:var(--red-text);">*</span>'
      : 'POS Approval Code <span style="color:var(--red-text);">*</span>';
    if (refInput) {
      refInput.value       = '';
      refInput.placeholder = method === 'MOMO' ? '11-digit reference' : 'Approval code';
    }
    _settleUpdateBtn();
  }

  function _settleUpdateBtn() {
    const btn    = document.getElementById('settle-confirm-btn');
    const amount = parseFloat(document.getElementById('settle-amount')?.value || 0);
    const ref    = document.getElementById('settle-ref')?.value.trim() || '';
    if (!btn) return;

    let ready = amount > 0;
    if (_settleMethod === 'MOMO') ready = ready && /^\d{11}$/.test(ref);
    if (_settleMethod === 'POS')  ready = ready && ref.length > 0;

    btn.disabled      = !ready;
    btn.style.opacity = ready ? '1' : '0.4';
  }

  async function _submitSettle() {
    if (!_activeAccount) return;

    const btn    = document.getElementById('settle-confirm-btn');
    const errorEl = document.getElementById('settle-error');
    const amount = parseFloat(document.getElementById('settle-amount')?.value || 0);
    const ref    = document.getElementById('settle-ref')?.value.trim() || '';

    errorEl.style.display = 'none';

    if (!amount || amount <= 0) {
      errorEl.textContent   = 'Please enter a valid amount.';
      errorEl.style.display = 'block';
      return;
    }

    // Get sheet_id from shift status
    const sheetId = _shiftStatus?.sheet_id;
    if (!sheetId) {
      errorEl.textContent   = 'No open sheet found. Cannot process settlement.';
      errorEl.style.display = 'block';
      return;
    }

    btn.disabled    = true;
    btn.textContent = 'Processing…';

    try {
      const res = await Auth.fetch(
        `/api/v1/customers/credit/${_activeAccount.id}/settle/`, {
          method : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body   : JSON.stringify({
            amount,
            method   : _settleMethod,
            reference: ref,
            sheet_id : sheetId,
          }),
        }
      );

      const data = await res.json();

      if (!res.ok) {
        errorEl.textContent   = data.detail || Object.values(data).flat().join(' ');
        errorEl.style.display = 'block';
        return;
      }

      // Update local account balance
      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
      _closeSettle();
      _toast(`Settlement of ${fmt(amount)} recorded for ${_activeAccount.customer_name}.`, 'success');

      // Refresh results
      const query = document.getElementById('credit-search')?.value || '';
      if (query.length >= 2) _creditSearch(query);

    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Confirm Settlement';
    }
  }

  async function _viewPaymentHistory(accountId) {
    const results = document.getElementById('credit-results');
    if (!results) return;

    const account = _creditAccounts.find(a => a.id === accountId);
    const name    = account?.customer_name || 'Customer';

    results.innerHTML = `
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
        <button onclick="Cashier._renderCreditGrid(Cashier._getCreditAccounts())"
          style="padding:5px 12px;background:none;border:1px solid var(--border);
            border-radius:var(--radius-sm);font-size:12px;font-weight:600;
            cursor:pointer;color:var(--text-2);font-family:inherit;">
          ← Back
        </button>
        <span style="font-size:14px;font-weight:700;color:var(--text);">
          Payment History — ${_esc(name)}
        </span>
      </div>
      <div style="text-align:center;padding:40px;color:var(--text-3);
        font-size:13px;display:flex;align-items:center;justify-content:center;gap:8px;">
        <span class="spin"></span> Loading…
      </div>`;

    try {
      const res  = await Auth.fetch(`/api/v1/customers/credit/${accountId}/payments/`);
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const payments = Array.isArray(data) ? data : (data.results || []);
      const fmt      = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

      const backBtn = `
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;">
          <button onclick="Cashier._renderCreditGrid(Cashier._getCreditAccounts())"
            style="padding:5px 12px;background:none;border:1px solid var(--border);
              border-radius:var(--radius-sm);font-size:12px;font-weight:600;
              cursor:pointer;color:var(--text-2);font-family:inherit;">
            ← Back
          </button>
          <span style="font-size:14px;font-weight:700;color:var(--text);">
            Payment History — ${_esc(name)}
          </span>
        </div>`;

      if (!payments.length) {
        results.innerHTML = backBtn + `
          <div style="text-align:center;padding:60px;color:var(--text-3);font-size:13px;">
            No settlements recorded yet.
          </div>`;
        return;
      }

      const rows = payments.map(p => {
        const date = p.created_at
          ? new Date(p.created_at).toLocaleString('en-GB', {
              day:'numeric', month:'short', year:'numeric',
              hour:'2-digit', minute:'2-digit',
            })
          : '—';
        const methodColor = { CASH:'var(--cash-text)', MOMO:'var(--momo-text)', POS:'var(--pos-text)' }[p.payment_method] || 'var(--text-3)';
        const methodBg    = { CASH:'var(--cash-bg)',   MOMO:'var(--momo-bg)',   POS:'var(--pos-bg)'   }[p.payment_method] || 'var(--bg)';
        return `
          <tr>
            <td style="padding:12px 16px;border-bottom:1px solid var(--border);
              font-size:12px;color:var(--text-3);">${date}</td>
            <td style="padding:12px 16px;border-bottom:1px solid var(--border);">
              <span style="padding:2px 8px;border-radius:5px;font-size:11px;font-weight:700;
                background:${methodBg};color:${methodColor};">${p.payment_method}</span>
            </td>
            <td style="padding:12px 16px;border-bottom:1px solid var(--border);
              text-align:right;font-family:'JetBrains Mono',monospace;font-size:13px;
              font-weight:700;color:var(--green-text);">${fmt(p.amount)}</td>
            <td style="padding:12px 16px;border-bottom:1px solid var(--border);
              text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;
              color:var(--text-3);">${fmt(p.balance_after)}</td>
          </tr>`;
      }).join('');

      results.innerHTML = backBtn + `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);">
                <th style="padding:10px 16px;text-align:left;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Date</th>
                <th style="padding:10px 16px;text-align:left;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Method</th>
                <th style="padding:10px 16px;text-align:right;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Amount</th>
                <th style="padding:10px 16px;text-align:right;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Balance After</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
    } catch {
      results.innerHTML = `<div style="text-align:center;padding:40px;
        color:var(--red-text);font-size:13px;">Could not load history.</div>`;
    }
  }

  function _getCreditAccounts() { return _creditAccounts; }


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
    _switchReceiptsTab,
    _historyDrillDown,
    _historyDrillUp,
    _updateSplitRemainder,
    _updateSplitFields,
    _openSettle,
    _closeSettle,
    _settleSelectMethod,
    _settleUpdateBtn,
    _submitSettle,
    _viewPaymentHistory,
    _renderCreditResults,
    _getCreditAccounts,
    _creditFilter,
    _renderCreditGrid,
    _updatePartialCredit,
  };
})();

document.addEventListener('DOMContentLoaded', Cashier.init);