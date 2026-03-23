/**
 * Octos — Invoice Controller
 *
 * Two modes:
 *   LINKED     — job selected from today's sheet, line items auto-filled
 *   STANDALONE — services selected from catalogue (chip + search UI)
 *
 * Depends on: Auth, State (branchId, services)
 */

'use strict';

const Invoice = (() => {

  // ── State ──────────────────────────────────────────────────
  let _mode        = 'LINKED';
  let _step        = 1;
  let _selectedJob = null;
  let _cart        = [];
  let _currentSvc  = null;
  let _priceTimer  = null;
  let _todaysJobs  = [];

  // Persisted form values across steps
  const _form = {
    invoice_type     : 'PROFORMA',
    due_date         : '',
    vat_rate         : '0',
    bm_note          : '',
    bill_to_name     : '',
    bill_to_phone    : '',
    bill_to_email    : '',
    bill_to_company  : '',
    delivery_channel : 'WHATSAPP',
  };

  // ── Helpers ────────────────────────────────────────────────
  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _fmt(n) {
    return `GHS ${parseFloat(n || 0).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
  }

  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className   = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  // ══════════════════════════════════════════════════════════
  // OPEN / CLOSE
  // ══════════════════════════════════════════════════════════

  async function open() {
    _mode        = 'LINKED';
    _step        = 1;
    _selectedJob = null;
    _cart        = [];
    _currentSvc  = null;
    _form.invoice_type     = 'PROFORMA';
    _form.due_date         = '';
    _form.vat_rate         = '0';
    _form.bm_note          = '';
    _form.bill_to_name     = '';
    _form.bill_to_phone    = '';
    _form.bill_to_email    = '';
    _form.bill_to_company  = '';
    _form.delivery_channel = 'WHATSAPP';

    document.getElementById('invoice-modal')?.classList.add('open');
    _renderStep(1);

    // Pre-fetch today's jobs for step 1
    _loadTodaysJobs();
  }

  function close() {
    document.getElementById('invoice-modal')?.classList.remove('open');
  }

  async function _loadTodaysJobs() {
    try {
      const sheetRes = await Auth.fetch('/api/v1/finance/sheets/today/');
      if (!sheetRes.ok) { _todaysJobs = []; return; }
      const sheet = await sheetRes.json();
      if (sheet.status !== 'OPEN') { _todaysJobs = []; return; }

      const res  = await Auth.fetch(`/api/v1/jobs/?daily_sheet=${sheet.id}&page_size=200`);
      if (!res.ok) { _todaysJobs = []; return; }
      const data = await res.json();
      _todaysJobs = Array.isArray(data) ? data : (data.results || []);

      // Re-render step 1 if still on it
      if (_step === 1) _renderStep(1);
    } catch { _todaysJobs = []; }
  }

  // ══════════════════════════════════════════════════════════
  // STEP RENDERING
  // ══════════════════════════════════════════════════════════

  function _renderStep(step) {
    _step = step;

    const body    = document.getElementById('invoice-modal-body');
    const title   = document.getElementById('invoice-modal-title');
    const backBtn = document.getElementById('invoice-back-btn');
    const nextBtn = document.getElementById('invoice-next-btn');
    if (!body) return;

    // Step dots
    [1,2,3,4].forEach(n => {
      const dot = document.getElementById(`inv-dot-${n}`);
      if (dot) dot.style.background = n <= step ? 'var(--text)' : 'var(--border)';
    });

    if (title) title.textContent = [
      '', 'Select Job', 'Invoice Details', 'Bill To & Delivery', 'Preview & Send'
    ][step];

    if (backBtn) backBtn.style.display = step > 1 ? 'block' : 'none';
    if (nextBtn) nextBtn.textContent   = step === 4 ? 'Generate & Send' : 'Continue →';

    const renders = { 1: _renderStep1, 2: _renderStep2, 3: _renderStep3, 4: _renderStep4 };
    body.innerHTML = '';
    renders[step]?.(body);
  }

  // ── Step 1 — Mode + Job/Service selection ──────────────────
  function _renderStep1(body) {
    body.innerHTML = `
      <!-- Mode toggle -->
      <div style="display:flex;gap:8px;margin-bottom:20px;">
        <button id="inv-mode-linked" onclick="Invoice._setMode('LINKED')"
          style="flex:1;padding:10px;border-radius:var(--radius-sm);border:2px solid var(--text);
                 background:var(--text);color:#fff;font-size:13px;font-weight:700;cursor:pointer;
                 font-family:inherit;">
          Linked to a Job
        </button>
        <button id="inv-mode-standalone" onclick="Invoice._setMode('STANDALONE')"
          style="flex:1;padding:10px;border-radius:var(--radius-sm);border:2px solid var(--border);
                 background:var(--bg);color:var(--text-2);font-size:13px;font-weight:600;
                 cursor:pointer;font-family:inherit;">
          Standalone Invoice
        </button>
      </div>

      <!-- Linked: job search -->
      <div id="inv-linked-section">
        <div style="font-size:12px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
          Select Job
        </div>
        <div style="position:relative;margin-bottom:10px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="2"
            style="position:absolute;left:10px;top:50%;transform:translateY(-50%);
                   color:var(--text-3);pointer-events:none;">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input type="text" id="inv-job-search" placeholder="Search by ref or title…"
            oninput="Invoice._filterJobs(this.value)"
            style="width:100%;padding:8px 12px 8px 32px;border:1.5px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                   font-size:13px;font-family:inherit;outline:none;box-sizing:border-box;">
        </div>
        <div id="inv-job-list" style="max-height:280px;overflow-y:auto;
          border:1px solid var(--border);border-radius:var(--radius-sm);">
          <div style="padding:20px;text-align:center;color:var(--text-3);font-size:13px;">
            <span class="spin"></span> Loading jobs…
          </div>
        </div>
      </div>

      <!-- Standalone: service chips -->
      <div id="inv-standalone-section" style="display:none;">
        <div style="font-size:12px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
          Select Services
        </div>
        <div style="position:relative;margin-bottom:8px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="2"
            style="position:absolute;left:10px;top:50%;transform:translateY(-50%);
                   color:var(--text-3);pointer-events:none;">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <input type="text" id="inv-svc-search" placeholder="Search services…"
            oninput="Invoice._filterChips(this.value)"
            style="width:100%;padding:8px 12px 8px 32px;border:1.5px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                   font-size:13px;font-family:inherit;outline:none;box-sizing:border-box;">
        </div>
        <div class="nj-service-grid" id="inv-chip-grid" style="max-height:160px;overflow-y:auto;">
          ${(State.services || []).map(s => `
            <button class="nj-service-chip" data-id="${s.id}"
              data-name="${_esc(s.name.toLowerCase())}"
              onclick="Invoice._selectChip(${s.id})">
              ${_esc(s.name)}
            </button>`).join('')}
        </div>

        <!-- Configurator -->
        <div id="inv-configurator" style="display:none;margin-top:14px;padding:14px;
          background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);">
          <div id="inv-cfg-title" style="font-size:13px;font-weight:700;
            color:var(--text);margin-bottom:10px;"></div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:4px;">
                Sheets
              </label>
              <input type="number" id="inv-pages" value="1" min="1"
                oninput="Invoice._triggerPrice()"
                style="width:100%;padding:8px;border:1.5px solid var(--border);
                       border-radius:var(--radius-sm);background:var(--panel);
                       color:var(--text);font-size:13px;box-sizing:border-box;">
            </div>
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:4px;">
                Copies
              </label>
              <input type="number" id="inv-sets" value="1" min="1"
                oninput="Invoice._triggerPrice()"
                style="width:100%;padding:8px;border:1.5px solid var(--border);
                       border-radius:var(--radius-sm);background:var(--panel);
                       color:var(--text);font-size:13px;box-sizing:border-box;">
            </div>
          </div>
          <div id="inv-line-price" style="display:none;padding:8px 12px;
            background:var(--green-bg);border:1px solid var(--green-border);
            border-radius:var(--radius-sm);font-size:13px;font-weight:700;
            color:var(--green-text);margin-bottom:10px;"></div>
          <button onclick="Invoice._addToCart()"
            style="width:100%;padding:8px;background:var(--text);color:#fff;border:none;
                   border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                   cursor:pointer;font-family:inherit;">
            + Add to Invoice
          </button>
        </div>

        <!-- Cart -->
        <div id="inv-cart" style="margin-top:12px;"></div>
      </div>`;

    // Render job list
    _renderJobList('');

    // Render cart if returning to step 1
    if (_cart.length) _renderCart();
  }

  function _filterJobs(query) {
    _renderJobList(query.toLowerCase().trim());
  }

  function _renderJobList(query) {
    const list = document.getElementById('inv-job-list');
    if (!list) return;

    const jobs = query
      ? _todaysJobs.filter(j =>
          (j.job_number || '').toLowerCase().includes(query) ||
          (j.title      || '').toLowerCase().includes(query)
        )
      : _todaysJobs;

    if (!jobs.length) {
      list.innerHTML = `<div style="padding:20px;text-align:center;
        color:var(--text-3);font-size:13px;">
        ${_todaysJobs.length ? 'No jobs match.' : 'No jobs on today\'s sheet.'}
      </div>`;
      return;
    }

    list.innerHTML = jobs.map(j => {
      const isSelected = _selectedJob?.id === j.id;
      return `
        <div onclick="Invoice._selectJob(${j.id})"
          style="padding:12px 14px;border-bottom:1px solid var(--border);
                 cursor:pointer;display:flex;align-items:center;
                 justify-content:space-between;
                 background:${isSelected ? 'var(--bg)' : 'var(--panel)'};
                 transition:background 0.12s;"
          onmouseover="this.style.background='var(--bg)'"
          onmouseout="this.style.background='${isSelected ? 'var(--bg)' : 'var(--panel)'}'">
          <div>
            <div style="font-size:13px;font-weight:600;color:var(--text);">
              ${_esc(j.title || '—')}
            </div>
            <div style="font-size:11px;color:var(--text-3);margin-top:2px;
              font-family:'JetBrains Mono',monospace;">
              ${_esc(j.job_number)} · ${j.status}
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;
              color:var(--text);">
              ${j.estimated_cost ? _fmt(j.estimated_cost) : '—'}
            </span>
            ${isSelected
              ? `<span style="color:var(--green-text);font-size:16px;">✓</span>`
              : ''}
          </div>
        </div>`;
    }).join('');
  }

  function _selectJob(jobId) {
    _selectedJob = _todaysJobs.find(j => j.id === jobId) || null;
    _renderJobList(document.getElementById('inv-job-search')?.value || '');
  }

  // ── Mode toggle ────────────────────────────────────────────
  function _setMode(mode) {
    _mode = mode;

    const linkedBtn      = document.getElementById('inv-mode-linked');
    const standaloneBtn  = document.getElementById('inv-mode-standalone');
    const linkedSection  = document.getElementById('inv-linked-section');
    const saSection      = document.getElementById('inv-standalone-section');

    const activeStyle   = 'border-color:var(--text);background:var(--text);color:#fff;';
    const inactiveStyle = 'border-color:var(--border);background:var(--bg);color:var(--text-2);';

    if (mode === 'LINKED') {
      if (linkedBtn)     linkedBtn.style.cssText     += activeStyle;
      if (standaloneBtn) standaloneBtn.style.cssText += inactiveStyle;
      if (linkedSection)  linkedSection.style.display  = 'block';
      if (saSection)      saSection.style.display      = 'none';
    } else {
      if (standaloneBtn) standaloneBtn.style.cssText += activeStyle;
      if (linkedBtn)     linkedBtn.style.cssText     += inactiveStyle;
      if (linkedSection)  linkedSection.style.display  = 'none';
      if (saSection)      saSection.style.display      = 'block';
    }
  }

  // ── Chip filter ────────────────────────────────────────────
  function _filterChips(query) {
    const q = query.toLowerCase().trim();
    document.querySelectorAll('#inv-chip-grid .nj-service-chip').forEach(chip => {
      chip.style.display = !q || chip.dataset.name.includes(q) ? '' : 'none';
    });
  }

  // ── Service chip selection ─────────────────────────────────
  function _selectChip(serviceId) {
    _currentSvc = (State.services || []).find(s => s.id === serviceId) || null;
    if (!_currentSvc) return;

    document.querySelectorAll('#inv-chip-grid .nj-service-chip').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.dataset.id) === serviceId);
    });

    const cfg   = document.getElementById('inv-configurator');
    const title = document.getElementById('inv-cfg-title');
    if (cfg)   cfg.style.display   = 'block';
    if (title) title.textContent   = _currentSvc.name;

    const d = _currentSvc.smart_defaults || {};
    const pagesEl = document.getElementById('inv-pages');
    const setsEl  = document.getElementById('inv-sets');
    if (pagesEl) pagesEl.value = d.pages || 1;
    if (setsEl)  setsEl.value  = d.sets  || 1;

    _triggerPrice();
  }

  function _triggerPrice() {
    clearTimeout(_priceTimer);
    _priceTimer = setTimeout(_calcPrice, 300);
  }

  async function _calcPrice() {
    if (!_currentSvc || !State.branchId) return;
    const pages    = parseInt(document.getElementById('inv-pages')?.value || 1);
    const sets     = parseInt(document.getElementById('inv-sets')?.value  || 1);
    const is_color = (_currentSvc.smart_defaults?.is_color) ? 'true' : 'false';

    try {
      const params = new URLSearchParams({
        service: _currentSvc.id, branch: State.branchId,
        quantity: sets, pages, is_color,
      });
      const res  = await Auth.fetch(`/api/v1/jobs/price/calculate/?${params}`);
      if (!res.ok) return;
      const data  = await res.json();
      const el    = document.getElementById('inv-line-price');
      if (el) {
        el.style.display = 'block';
        el.textContent   = `Line Total: ${_fmt(data.total || 0)}`;
      }
    } catch { /* silent */ }
  }

  function _addToCart() {
    if (!_currentSvc) return;
    const pages    = parseInt(document.getElementById('inv-pages')?.value || 1);
    const sets     = parseInt(document.getElementById('inv-sets')?.value  || 1);
    const is_color = !!(_currentSvc.smart_defaults?.is_color);

    _cart.push({
      serviceId  : _currentSvc.id,
      serviceName: _currentSvc.name,
      pages, sets,
      quantity   : sets,
      is_color,
      paper_size : _currentSvc.smart_defaults?.paper_size || 'A4',
      sides      : _currentSvc.smart_defaults?.sides      || 'SINGLE',
      unit_price : 0,
      line_total : 0,
    });

    // Get price async and update cart
    const idx = _cart.length - 1;
    const is_color_str = is_color ? 'true' : 'false';
    const params = new URLSearchParams({
      service: _currentSvc.id, branch: State.branchId,
      quantity: sets, pages, is_color: is_color_str,
    });
    Auth.fetch(`/api/v1/jobs/price/calculate/?${params}`).then(async res => {
      if (!res.ok) return;
      const data = await res.json();
      _cart[idx].unit_price = parseFloat(data.base_price || 0);
      _cart[idx].line_total = parseFloat(data.total      || 0);
      _renderCart();
    }).catch(() => {});

    // Reset configurator
    _currentSvc = null;
    document.querySelectorAll('#inv-chip-grid .nj-service-chip')
      .forEach(b => b.classList.remove('active'));
    const cfg = document.getElementById('inv-configurator');
    if (cfg) cfg.style.display = 'none';
    const search = document.getElementById('inv-svc-search');
    if (search) { search.value = ''; _filterChips(''); }

    _renderCart();
    _toast(`${_cart[idx].serviceName} added.`, 'success');
  }

  function _renderCart() {
    const el = document.getElementById('inv-cart');
    if (!el || !_cart.length) { if (el) el.innerHTML = ''; return; }

    const total = _cart.reduce((s, i) => s + i.line_total, 0);
    el.innerHTML = `
      <div style="border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden;">
        ${_cart.map((item, i) => `
          <div style="display:flex;align-items:center;justify-content:space-between;
            padding:10px 12px;border-bottom:1px solid var(--border);
            background:var(--panel);">
            <div>
              <div style="font-size:13px;font-weight:600;color:var(--text);">
                ${_esc(item.serviceName)}
              </div>
              <div style="font-size:11px;color:var(--text-3);">
                ${item.pages > 1 ? `${item.pages}pp × ${item.sets} sets` : `× ${item.sets}`}
              </div>
            </div>
            <div style="display:flex;align-items:center;gap:10px;">
              <span style="font-size:13px;font-weight:700;
                font-family:'JetBrains Mono',monospace;">
                ${_fmt(item.line_total)}
              </span>
              <button onclick="Invoice._removeFromCart(${i})"
                style="background:none;border:none;color:var(--text-3);
                       cursor:pointer;font-size:16px;line-height:1;">×</button>
            </div>
          </div>`).join('')}
        <div style="padding:10px 12px;display:flex;justify-content:space-between;
          background:var(--bg);font-size:13px;font-weight:700;">
          <span>Total</span>
          <span style="font-family:'JetBrains Mono',monospace;">${_fmt(total)}</span>
        </div>
      </div>`;
  }

  function _removeFromCart(idx) {
    _cart.splice(idx, 1);
    _renderCart();
  }

  // ── Step 2 — Invoice details ───────────────────────────────
  function _renderStep2(body) {
    const isJobLinked = _mode === 'LINKED' && _selectedJob;
    const defaultType = _form.invoice_type ||
      (isJobLinked && _selectedJob?.status === 'COMPLETE' ? 'TAX' : 'PROFORMA');

    body.innerHTML = `
      <!-- Invoice type -->
      <div style="margin-bottom:16px;">
        <label style="font-size:11px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:8px;">
          Invoice Type
        </label>
        <div style="display:flex;gap:8px;">
          <button id="inv-type-proforma" onclick="Invoice._setInvType('PROFORMA')"
            style="flex:1;padding:10px;border-radius:var(--radius-sm);cursor:pointer;
                   font-size:13px;font-weight:700;font-family:inherit;
                   border:2px solid ${defaultType === 'PROFORMA' ? 'var(--blue-text)' : 'var(--border)'};
                   background:${defaultType === 'PROFORMA' ? 'var(--blue-bg)' : 'var(--bg)'};
                   color:${defaultType === 'PROFORMA' ? 'var(--blue-text)' : 'var(--text-2)'};">
            Proforma
          </button>
          <button id="inv-type-tax" onclick="Invoice._setInvType('TAX')"
            style="flex:1;padding:10px;border-radius:var(--radius-sm);cursor:pointer;
                   font-size:13px;font-weight:700;font-family:inherit;
                   border:2px solid ${defaultType === 'TAX' ? 'var(--green-text)' : 'var(--border)'};
                   background:${defaultType === 'TAX' ? 'var(--green-bg)' : 'var(--bg)'};
                   color:${defaultType === 'TAX' ? 'var(--green-text)' : 'var(--text-2)'};">
            Tax Invoice
          </button>
        </div>
        <input type="hidden" id="inv-type-val" value="${defaultType}">
      </div>

      <!-- Due date -->
      <div style="margin-bottom:16px;">
        <label style="font-size:11px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
          Due Date <span style="color:var(--text-3);font-weight:400;">(optional)</span>
        </label>
        <input type="date" id="inv-due-date" value="${_form.due_date}"
          style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                 border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                 font-size:13px;font-family:inherit;outline:none;box-sizing:border-box;">
      </div>

      <!-- VAT -->
      <div style="margin-bottom:16px;">
        <label style="font-size:11px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
          VAT Rate (%)
        </label>
        <input type="number" id="inv-vat" value="${_form.vat_rate || 0}" min="0" max="100" step="0.5"
          style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                 border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                 font-size:13px;font-family:inherit;outline:none;box-sizing:border-box;">
        <div style="font-size:11px;color:var(--text-3);margin-top:4px;">
          Set to 0 if not VAT registered or not applicable.
        </div>
      </div>

      <!-- BM Note -->
      <div>
        <label style="font-size:11px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
          Message to Customer
        </label>
        <textarea id="inv-bm-note" rows="3" placeholder="Please find attached your invoice for services rendered…" style="width:100%;padding:9px 12px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:inherit;outline:none;resize:vertical;box-sizing:border-box;">${_form.bm_note}</textarea>
          style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                 border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                 font-size:13px;font-family:inherit;outline:none;resize:vertical;
                 box-sizing:border-box;"></textarea>
      </div>`;
  }

  function _setInvType(type) {
    const proBtn = document.getElementById('inv-type-proforma');
    const taxBtn = document.getElementById('inv-type-tax');
    const val    = document.getElementById('inv-type-val');
    if (val) val.value = type;

    if (proBtn) {
      proBtn.style.borderColor = type === 'PROFORMA' ? 'var(--blue-text)'  : 'var(--border)';
      proBtn.style.background  = type === 'PROFORMA' ? 'var(--blue-bg)'    : 'var(--bg)';
      proBtn.style.color       = type === 'PROFORMA' ? 'var(--blue-text)'  : 'var(--text-2)';
    }
    if (taxBtn) {
      taxBtn.style.borderColor = type === 'TAX' ? 'var(--green-text)' : 'var(--border)';
      taxBtn.style.background  = type === 'TAX' ? 'var(--green-bg)'   : 'var(--bg)';
      taxBtn.style.color       = type === 'TAX' ? 'var(--green-text)' : 'var(--text-2)';
    }
  }

  // ── Step 3 — Bill To + Delivery ────────────────────────────
  function _renderStep3(body) {
    // Pre-fill from job customer if linked
    const job = _selectedJob;
    body.innerHTML = `
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:14px;">
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Name <span style="color:var(--red-text);">*</span>
          </label>
          <input type="text" id="inv-bill-name"
            value="${_esc(_form.bill_to_name || job?.customer_name || '')}"
            placeholder="Customer or company name"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                   font-size:13px;font-family:inherit;outline:none;box-sizing:border-box;">
        </div>
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Company <span style="color:var(--text-3);font-weight:400;">(optional)</span>
          </label>
          <input type="text" id="inv-bill-company" placeholder="Organisation name"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                   font-size:13px;font-family:inherit;outline:none;box-sizing:border-box;">
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px;">
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Phone
          </label>
          <input type="tel" id="inv-bill-phone"
            value="${_esc(_form.bill_to_phone || job?.customer_phone || '')}"
            placeholder="+233…"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                   font-size:13px;font-family:inherit;outline:none;box-sizing:border-box;">
        </div>
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Email
          </label>
          <input type="email" id="inv-bill-email" placeholder="customer@example.com"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                   font-size:13px;font-family:inherit;outline:none;box-sizing:border-box;">
        </div>
      </div>

      <!-- Delivery channel -->
      <div>
        <label style="font-size:11px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:8px;">
          Delivery Channel
        </label>
        <div style="display:flex;gap:8px;">
          ${['WHATSAPP','EMAIL','BOTH'].map(ch => `
            <button id="inv-ch-${ch}" onclick="Invoice._setChannel('${ch}')"
              style="flex:1;padding:9px;border-radius:var(--radius-sm);cursor:pointer;
                     font-size:12px;font-weight:700;font-family:inherit;
                     border:2px solid ${ch === 'WHATSAPP' ? 'var(--green-text)' : 'var(--border)'};
                     background:${ch === 'WHATSAPP' ? 'var(--green-bg)' : 'var(--bg)'};
                     color:${ch === 'WHATSAPP' ? 'var(--green-text)' : 'var(--text-2)'};">
              ${ch === 'BOTH' ? 'Both' : ch === 'WHATSAPP' ? 'WhatsApp' : 'Email'}
            </button>`).join('')}
        </div>
        <input type="hidden" id="inv-channel-val" value="WHATSAPP">
      </div>`;
  }

  function _setChannel(ch) {
    const val = document.getElementById('inv-channel-val');
    if (val) val.value = ch;

    ['WHATSAPP','EMAIL','BOTH'].forEach(c => {
      const btn = document.getElementById(`inv-ch-${c}`);
      if (!btn) return;
      const isActive = c === ch;
      const color = c === 'WHATSAPP' ? 'green' : c === 'EMAIL' ? 'blue' : 'amber';
      btn.style.borderColor = isActive ? `var(--${color}-text)` : 'var(--border)';
      btn.style.background  = isActive ? `var(--${color}-bg)`   : 'var(--bg)';
      btn.style.color       = isActive ? `var(--${color}-text)` : 'var(--text-2)';
    });
  }

  // ── Step 4 — Preview & Send ────────────────────────────────
function _renderStep4(body) {
    const invType  = _form.invoice_type;
    const dueDate  = _form.due_date     || '—';
    const vat      = _form.vat_rate     || '0';
    const channel  = _form.delivery_channel;
    const name     = _form.bill_to_name    || '—';
    const phone    = _form.bill_to_phone   || '—';
    const email    = _form.bill_to_email   || '—';
    const company  = _form.bill_to_company || '';
    const note     = _form.bm_note         || '';

    let subtotal = 0;
    let lineItemsHtml = '';

    if (_mode === 'LINKED' && _selectedJob) {
      subtotal = parseFloat(_selectedJob.estimated_cost || 0);
      const items = _selectedJob.line_items || [];
      lineItemsHtml = items.length
        ? items.map((li, i) => `
          <tr style="border-bottom:1px solid var(--border);">
            <td style="padding:10px 8px;font-size:13px;color:var(--text-3);">${i+1}</td>
            <td style="padding:10px 8px;">
              <div style="font-size:13px;font-weight:600;color:var(--text);">${_esc(li.label || li.service_name || '—')}</div>
              <div style="font-size:11px;color:var(--text-3);">${li.paper_size || ''} · ${li.is_color ? 'Colour' : 'B&W'}</div>
            </td>
            <td style="padding:10px 8px;font-size:13px;color:var(--text-2);text-align:center;">${li.sets || li.quantity || 1}</td>
            <td style="padding:10px 8px;font-size:13px;font-family:'JetBrains Mono',monospace;text-align:right;">${_fmt(li.unit_price || 0)}</td>
            <td style="padding:10px 8px;font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;text-align:right;">${_fmt(li.line_total || 0)}</td>
          </tr>`).join('')
        : `<tr><td colspan="5" style="padding:16px;text-align:center;color:var(--text-3);font-size:13px;">No line items</td></tr>`;
    } else {
      subtotal = _cart.reduce((s, i) => s + i.line_total, 0);
      lineItemsHtml = _cart.map((item, i) => `
        <tr style="border-bottom:1px solid var(--border);">
          <td style="padding:10px 8px;font-size:13px;color:var(--text-3);">${i+1}</td>
          <td style="padding:10px 8px;">
            <div style="font-size:13px;font-weight:600;color:var(--text);">${_esc(item.serviceName)}</div>
            <div style="font-size:11px;color:var(--text-3);">${item.paper_size} · ${item.is_color ? 'Colour' : 'B&W'}</div>
          </td>
          <td style="padding:10px 8px;font-size:13px;color:var(--text-2);text-align:center;">${item.pages > 1 ? `${item.pages}pp × ${item.sets}` : item.sets}</td>
          <td style="padding:10px 8px;font-size:13px;font-family:'JetBrains Mono',monospace;text-align:right;">${_fmt(item.unit_price)}</td>
          <td style="padding:10px 8px;font-size:13px;font-weight:700;font-family:'JetBrains Mono',monospace;text-align:right;">${_fmt(item.line_total)}</td>
        </tr>`).join('');
    }

    const vatAmt = subtotal * (parseFloat(vat) / 100);
    const total  = subtotal + vatAmt;
    const channelLabel = { WHATSAPP: 'WhatsApp', EMAIL: 'Email', BOTH: 'WhatsApp + Email' };
    const typeColor = invType === 'PROFORMA' ? 'var(--blue-text)' : 'var(--green-text)';
    const typeBg    = invType === 'PROFORMA' ? 'var(--blue-bg)'   : 'var(--green-bg)';

    body.innerHTML = `
      <!-- Invoice header -->
      <div style="display:flex;justify-content:space-between;align-items:flex-start;
        margin-bottom:20px;padding-bottom:16px;border-bottom:2px solid var(--border);">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;
            color:var(--text);margin-bottom:2px;">Farhat Printing Press</div>
          <div style="font-size:12px;color:var(--text-3);">Professional Printing Services</div>
        </div>
        <div style="text-align:right;">
          <div style="display:inline-flex;align-items:center;padding:4px 12px;
            border-radius:20px;font-size:11px;font-weight:700;
            background:${typeBg};color:${typeColor};border:1px solid ${typeColor};
            margin-bottom:6px;">
            ${invType === 'PROFORMA' ? 'PROFORMA INVOICE' : 'TAX INVOICE'}
          </div>
          <div style="font-size:12px;color:var(--text-3);">Preview</div>
        </div>
      </div>

      <!-- Bill To + Meta -->
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;margin-bottom:20px;">
        <div style="padding:14px;background:var(--bg);border:1px solid var(--border);
          border-radius:var(--radius-sm);">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Bill To</div>
          <div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:3px;">
            ${_esc(name)}
          </div>
          ${company ? `<div style="font-size:12px;color:var(--text-2);margin-bottom:2px;">${_esc(company)}</div>` : ''}
          ${phone !== '—' ? `<div style="font-size:12px;color:var(--text-3);">${_esc(phone)}</div>` : ''}
          ${email !== '—' ? `<div style="font-size:12px;color:var(--text-3);">${_esc(email)}</div>` : ''}
        </div>
        <div style="padding:14px;background:var(--bg);border:1px solid var(--border);
          border-radius:var(--radius-sm);">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Invoice Details</div>
          <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <span style="font-size:12px;color:var(--text-3);">Due Date</span>
            <span style="font-size:12px;font-weight:600;color:var(--text);">${dueDate}</span>
          </div>
          <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <span style="font-size:12px;color:var(--text-3);">Delivery</span>
            <span style="font-size:12px;font-weight:600;color:var(--text);">${channelLabel[channel]}</span>
          </div>
          <div style="display:flex;justify-content:space-between;">
            <span style="font-size:12px;color:var(--text-3);">VAT Rate</span>
            <span style="font-size:12px;font-weight:600;color:var(--text);">${vat}%</span>
          </div>
        </div>
      </div>

      <!-- Line items -->
      <div style="border:1px solid var(--border);border-radius:var(--radius-sm);
        overflow:hidden;margin-bottom:16px;">
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:var(--bg);">
              <th style="padding:10px 8px;font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;text-align:left;width:32px;">#</th>
              <th style="padding:10px 8px;font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;text-align:left;">Service</th>
              <th style="padding:10px 8px;font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;text-align:center;">Qty</th>
              <th style="padding:10px 8px;font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;text-align:right;">Unit Price</th>
              <th style="padding:10px 8px;font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;text-align:right;">Total</th>
            </tr>
          </thead>
          <tbody>${lineItemsHtml}</tbody>
        </table>
      </div>

      <!-- Totals -->
      <div style="display:flex;justify-content:flex-end;margin-bottom:16px;">
        <div style="width:240px;">
          <div style="display:flex;justify-content:space-between;padding:6px 0;
            font-size:13px;border-bottom:1px solid var(--border);">
            <span style="color:var(--text-3);">Subtotal</span>
            <span style="font-family:'JetBrains Mono',monospace;">${_fmt(subtotal)}</span>
          </div>
          ${parseFloat(vat) > 0 ? `
          <div style="display:flex;justify-content:space-between;padding:6px 0;
            font-size:13px;border-bottom:1px solid var(--border);">
            <span style="color:var(--text-3);">VAT (${vat}%)</span>
            <span style="font-family:'JetBrains Mono',monospace;">${_fmt(vatAmt)}</span>
          </div>` : ''}
          <div style="display:flex;justify-content:space-between;padding:10px 0 0;
            font-size:15px;font-weight:800;">
            <span>Total</span>
            <span style="font-family:'JetBrains Mono',monospace;color:${typeColor};">${_fmt(total)}</span>
          </div>
        </div>
      </div>

      ${note ? `
      <!-- Note -->
      <div style="padding:12px 14px;background:var(--bg);border:1px solid var(--border);
        border-left:3px solid ${typeColor};border-radius:var(--radius-sm);
        font-size:13px;color:var(--text-2);line-height:1.5;">
        <div style="font-size:10px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Message</div>
        ${_esc(note)}
      </div>` : ''}`;
  }
  // ══════════════════════════════════════════════════════════
  // NAVIGATION
  // ══════════════════════════════════════════════════════════

function next() {
    if (!_validateStep(_step)) return;
    _saveStep(_step);
    if (_step < 4) _renderStep(_step + 1);
    else _submit();
  }

  function back() {
    if (_step > 1) _renderStep(_step - 1);
  }

  function _saveStep(step) {
    if (step === 2) {
      _form.invoice_type = document.getElementById('inv-type-val')?.value    || 'PROFORMA';
      _form.due_date     = document.getElementById('inv-due-date')?.value    || '';
      _form.vat_rate     = document.getElementById('inv-vat')?.value         || '0';
      _form.bm_note      = document.getElementById('inv-bm-note')?.value     || '';
    }
    if (step === 3) {
      _form.bill_to_name     = document.getElementById('inv-bill-name')?.value    || '';
      _form.bill_to_phone    = document.getElementById('inv-bill-phone')?.value   || '';
      _form.bill_to_email    = document.getElementById('inv-bill-email')?.value   || '';
      _form.bill_to_company  = document.getElementById('inv-bill-company')?.value || '';
      _form.delivery_channel = document.getElementById('inv-channel-val')?.value  || 'WHATSAPP';
    }
  }

  function _validateStep(step) {
    if (step === 1) {
      if (_mode === 'LINKED' && !_selectedJob) {
        _toast('Please select a job.', 'error'); return false;
      }
      if (_mode === 'STANDALONE' && !_cart.length) {
        _toast('Add at least one service.', 'error'); return false;
      }
    }
    if (step === 3) {
      const name    = document.getElementById('inv-bill-name')?.value.trim();
      const channel = document.getElementById('inv-channel-val')?.value;
      const phone   = document.getElementById('inv-bill-phone')?.value.trim();
      const email   = document.getElementById('inv-bill-email')?.value.trim();
      if (!name) { _toast('Customer name is required.', 'error'); return false; }
      if (['WHATSAPP','BOTH'].includes(channel) && !phone) {
        _toast('Phone number required for WhatsApp.', 'error'); return false;
      }
      if (['EMAIL','BOTH'].includes(channel) && !email) {
        _toast('Email required for email delivery.', 'error'); return false;
      }
    }
    return true;
  }

  // ══════════════════════════════════════════════════════════
  // SUBMIT
  // ══════════════════════════════════════════════════════════

  async function _submit() {
    const btn = document.getElementById('invoice-next-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Generating…'; }

    const body = {
      invoice_type     : _form.invoice_type,
      due_date         : _form.due_date     || null,
      vat_rate         : parseFloat(_form.vat_rate || 0),
      bm_note          : _form.bm_note      || '',
      bill_to_name     : _form.bill_to_name,
      bill_to_phone    : _form.bill_to_phone,
      bill_to_email    : _form.bill_to_email,
      bill_to_company  : _form.bill_to_company,
      delivery_channel : _form.delivery_channel,
    };

    if (_mode === 'LINKED' && _selectedJob) {
      body.job_id = _selectedJob.id;
    } else {
      body.line_items = _cart.map(item => ({
        service   : item.serviceId,
        pages     : item.pages,
        sets      : item.sets,
        is_color  : item.is_color,
        paper_size: item.paper_size,
        sides     : item.sides,
      }));
    }

    try {
      const res = await Auth.fetch('/api/v1/finance/invoices/create/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        console.error('Invoice create error:', JSON.stringify(err));
        _toast(err.detail || JSON.stringify(err) || 'Failed to create invoice.', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Generate & Send'; }
        return;
      }

      const invoice = await res.json();
      _toast(`${invoice.invoice_number} generated & sent.`, 'success');
      close();

    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Generate & Send'; }
    }
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    open,
    close,
    next,
    back,
    _setMode,
    _setInvType,
    _setChannel,
    _selectJob,
    _filterJobs,
    _selectChip,
    _filterChips,
    _triggerPrice,
    _addToCart,
    _removeFromCart,
  };

})();