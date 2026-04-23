'use strict';

// Budget & Vendor module — extends FinancePortal
(function () {

  const CATEGORIES = [
    { key: 'STOCK',         label: 'Stock & Materials' },
    { key: 'PAYROLL',       label: 'Payroll' },
    { key: 'MAINTENANCE',   label: 'Maintenance' },
    { key: 'MARKETING',     label: 'Marketing' },
    { key: 'INVESTMENT',    label: 'Investment' },
    { key: 'UTILITIES',     label: 'Utilities' },
    { key: 'EQUIPMENT',     label: 'Equipment' },
    { key: 'MISCELLANEOUS', label: 'Miscellaneous' },
  ];

  // ── Budget pane ───────────────────────────────────────────
  async function loadBudget() {
    const container = document.getElementById('budget-content');
    if (!container) return;
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading...</div>';

    try {
      const res  = await Auth.fetch('/api/v1/procurement/budgets/');
      if (!res.ok) throw new Error();
      const data = await res.json();

      if (!data.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <div style="font-size:36px;margin-bottom:12px;">GHS</div>
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">
              No budgets yet</div>
            <div style="font-size:13px;">Propose the first annual budget to get started.</div>
          </div>`;
        return;
      }

      container.innerHTML = data.map(b => _renderBudgetCard(b)).join('');
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load budgets.</div>';
    }
  }

  function _renderBudgetCard(b) {
    const statusColors = {
      DRAFT:            { bg: 'var(--bg)',         text: 'var(--text-3)' },
      PENDING_APPROVAL: { bg: 'var(--amber-bg)',   text: 'var(--amber-text)' },
      APPROVED:         { bg: 'var(--green-bg)',   text: 'var(--green-text)' },
      CLOSED:           { bg: 'var(--bg)',         text: 'var(--text-3)' },
    };
    const sc = statusColors[b.status] || statusColors.DRAFT;

    const envelopeRows = (b.envelopes || [])
      .filter(e => e.period_type === 'QUARTERLY')
      .map(e => {
        const pct  = parseFloat(e.utilisation_pct || 0);
        const barColor = pct > 90 ? 'var(--red-text)' : pct > 70 ? 'var(--amber-text)' : 'var(--green-text)';
        return `
          <div style="display:flex;align-items:center;gap:12px;padding:8px 0;
            border-bottom:1px solid var(--border);">
            <div style="width:80px;font-size:11px;color:var(--text-3);">${e.period_display}</div>
            <div style="width:100px;font-size:11px;font-weight:600;color:var(--text);">${e.category_display}</div>
            <div style="flex:1;background:var(--bg);border-radius:4px;height:6px;overflow:hidden;">
              <div style="width:${Math.min(pct,100)}%;height:100%;background:${barColor};border-radius:4px;"></div>
            </div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-2);width:80px;text-align:right;">
              GHS ${parseFloat(e.available||0).toLocaleString('en-GH',{minimumFractionDigits:2})}</div>
            <div style="font-size:10px;color:${barColor};width:36px;text-align:right;">${pct}%</div>
          </div>`;
      }).join('');

    const approveBtn = b.status === 'PENDING_APPROVAL'
      ? `<button onclick="FinanceBudget.approveBudget(${b.id})"
          style="padding:7px 16px;background:var(--green-text);color:#fff;border:none;
            border-radius:var(--radius-sm);font-size:12px;font-weight:700;
            cursor:pointer;font-family:inherit;">
          Approve
        </button>` : '';

    return `
      <div style="border:1px solid var(--border);border-radius:var(--radius);
        overflow:hidden;margin-bottom:20px;">
        <div style="padding:14px 20px;background:var(--text);
          display:flex;align-items:center;justify-content:space-between;">
          <div style="font-family:'Syne',sans-serif;font-size:16px;
            font-weight:800;color:#fff;">Budget ${b.year}</div>
          <div style="display:flex;align-items:center;gap:10px;">
            ${approveBtn}
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;
              font-weight:700;background:${sc.bg};color:${sc.text};">
              ${b.status.replace('_', ' ')}
            </span>
          </div>
        </div>
        <div style="padding:20px;">
          ${envelopeRows || '<div style="font-size:13px;color:var(--text-3);">No envelopes yet.</div>'}
        </div>
        ${b.proposed_by_name ? `
          <div style="padding:10px 20px;border-top:1px solid var(--border);
            font-size:11px;color:var(--text-3);">
            Proposed by ${b.proposed_by_name}
            ${b.approved_by_name ? ' &middot; Approved by ' + b.approved_by_name : ''}
          </div>` : ''}
      </div>`;
  }

  async function approveBudget(id) {
    if (!confirm('Approve this budget? All envelopes will become active.')) return;
    try {
      const res = await Auth.fetch(`/api/v1/procurement/budgets/${id}/approve/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      const data = await res.json();
      if (!res.ok) {
        _toast(data.detail || 'Approval failed.', 'error');
        return;
      }
      _toast(data.message || 'Budget approved.', 'success');
      loadBudget();
    } catch {
      _toast('Network error.', 'error');
    }
  }

  // ── Propose Budget modal ──────────────────────────────────
  function openProposeBudgetModal() {
    const year = new Date().getFullYear();
    document.getElementById('budget-year').value = year;

    const form = document.getElementById('budget-envelopes-form');
    form.innerHTML = CATEGORIES.map(c => `
      <div style="display:flex;align-items:center;gap:12px;">
        <label style="width:140px;font-size:12px;font-weight:600;color:var(--text-2);">
          ${c.label}
        </label>
        <input type="number" id="env-${c.key}" min="0" step="0.01" placeholder="0.00"
          style="flex:1;padding:8px 12px;border:1.5px solid var(--border);
            border-radius:var(--radius-sm);font-size:13px;color:var(--text);
            background:var(--panel);font-family:'JetBrains Mono',monospace;">
      </div>`).join('');

    document.getElementById('propose-budget-error').style.display = 'none';
    document.getElementById('propose-budget-overlay').style.display = 'flex';
  }

  function closeProposeBudgetModal() {
    document.getElementById('propose-budget-overlay').style.display = 'none';
  }

  async function confirmProposeBudget() {
    const year = parseInt(document.getElementById('budget-year').value);
    const errorEl = document.getElementById('propose-budget-error');
    errorEl.style.display = 'none';

    if (!year || year < 2024) {
      errorEl.textContent   = 'Please enter a valid year.';
      errorEl.style.display = 'block';
      return;
    }

    const envelopes = CATEGORIES
      .map(c => ({
        category: c.key,
        ceiling : parseFloat(document.getElementById(`env-${c.key}`)?.value || 0),
      }))
      .filter(e => e.ceiling > 0);

    if (!envelopes.length) {
      errorEl.textContent   = 'Please enter at least one budget envelope amount.';
      errorEl.style.display = 'block';
      return;
    }

    const btn = document.getElementById('btn-propose-budget');
    btn.disabled    = true;
    btn.textContent = 'Submitting...';

    try {
      const res = await Auth.fetch('/api/v1/procurement/budgets/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ year, envelopes }),
      });
      const data = await res.json();
      if (!res.ok) {
        errorEl.textContent   = data.detail || 'Submission failed.';
        errorEl.style.display = 'block';
        return;
      }
      closeProposeBudgetModal();
      _toast(`Budget ${year} submitted for Owner approval.`, 'success');
      loadBudget();
    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Submit for Approval';
    }
  }

  // ── Vendors pane ──────────────────────────────────────────
  async function loadVendors() {
    const container = document.getElementById('vendors-content');
    if (!container) return;
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading...</div>';

    try {
      const res  = await Auth.fetch('/api/v1/procurement/vendors/');
      if (!res.ok) throw new Error();
      const data = await res.json();

      if (!data.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">
              No vendors yet</div>
            <div style="font-size:13px;">Add your first vendor to start building the pricelist.</div>
          </div>`;
        return;
      }

      container.innerHTML = data.map(v => _renderVendorCard(v)).join('');
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load vendors.</div>';
    }
  }

  function _renderVendorCard(v) {
    const itemRows = (v.items || []).map(item => `
      <div style="display:flex;align-items:center;justify-content:space-between;
        padding:8px 0;border-bottom:1px solid var(--border);">
        <div style="font-size:12px;color:var(--text-2);">${item.consumable_name}</div>
        <div style="display:flex;align-items:center;gap:12px;">
          ${item.is_preferred ? '<span style="font-size:10px;color:var(--green-text);font-weight:700;">PREFERRED</span>' : ''}
          <div style="font-family:\'JetBrains Mono\',monospace;font-size:12px;
            font-weight:700;color:var(--text);">
            GHS ${parseFloat(item.current_price||0).toFixed(2)}
          </div>
        </div>
      </div>`).join('');

    return `
      <div style="border:1px solid var(--border);border-radius:var(--radius);
        overflow:hidden;margin-bottom:16px;">
        <div style="padding:12px 18px;background:var(--bg);
          display:flex;align-items:center;justify-content:space-between;">
          <div>
            <div style="font-size:14px;font-weight:700;color:var(--text);">${v.name}</div>
            <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
              ${v.phone || ''} ${v.email ? '&middot; ' + v.email : ''}
              &middot; ${v.payment_term}
            </div>
          </div>
          <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;
            background:${v.is_active ? 'var(--green-bg)' : 'var(--bg)'};
            color:${v.is_active ? 'var(--green-text)' : 'var(--text-3)'};">
            ${v.is_active ? 'Active' : 'Inactive'}
          </span>
        </div>
        <div style="padding:12px 18px;">
          ${itemRows || '<div style="font-size:12px;color:var(--text-3);">No items on pricelist yet.</div>'}
        </div>
      </div>`;
  }

  // ── Add Vendor modal ──────────────────────────────────────
  function openAddVendorModal() {
    ['vendor-name','vendor-phone','vendor-email','vendor-address'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    document.getElementById('vendor-payment-term').value = 'CASH';
    document.getElementById('add-vendor-error').style.display = 'none';
    document.getElementById('add-vendor-overlay').style.display = 'flex';
  }

  function closeAddVendorModal() {
    document.getElementById('add-vendor-overlay').style.display = 'none';
  }

  async function confirmAddVendor() {
    const name     = document.getElementById('vendor-name')?.value?.trim();
    const errorEl  = document.getElementById('add-vendor-error');
    errorEl.style.display = 'none';

    if (!name) {
      errorEl.textContent   = 'Vendor name is required.';
      errorEl.style.display = 'block';
      return;
    }

    const btn = document.getElementById('btn-add-vendor');
    btn.disabled    = true;
    btn.textContent = 'Adding...';

    try {
      const res = await Auth.fetch('/api/v1/procurement/vendors/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({
          name         : name,
          phone        : document.getElementById('vendor-phone')?.value || '',
          email        : document.getElementById('vendor-email')?.value || '',
          address      : document.getElementById('vendor-address')?.value || '',
          payment_term : document.getElementById('vendor-payment-term')?.value || 'CASH',
        }),
      });
      const data = await res.json();
      if (!res.ok) {
        errorEl.textContent   = data.detail || JSON.stringify(data);
        errorEl.style.display = 'block';
        return;
      }
      closeAddVendorModal();
      _toast(`Vendor "${data.name}" added.`, 'success');
      loadVendors();
    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Add Vendor';
    }
  }

  // ── Helpers ───────────────────────────────────────────────
  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el       = document.createElement('div');
    el.className   = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // Budget and vendor loading is now handled by FinancePortal._loadSectionContent
  // No switchPane override needed

  // ── Expose public API ─────────────────────────────────────
  window.FinanceBudget = {
    loadBudget,
    approveBudget,
    openProposeBudgetModal,
    closeProposeBudgetModal,
    confirmProposeBudget,
    loadVendors,
    openAddVendorModal,
    closeAddVendorModal,
    confirmAddVendor,
  };

  // Wire modal functions into FinancePortal namespace
  FinancePortal.openProposeBudgetModal  = openProposeBudgetModal;
  FinancePortal.closeProposeBudgetModal = closeProposeBudgetModal;
  FinancePortal.openAddVendorModal      = openAddVendorModal;
  FinancePortal.closeAddVendorModal     = closeAddVendorModal;

})();