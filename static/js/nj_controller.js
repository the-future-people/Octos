/**
 * NJ — New Job Modal Controller
 *
 * Handles:
 *  - 3-way type toggle (INSTANT / PRODUCTION / DESIGN) with color theming
 *  - Service dropdown filtered by job type
 *  - Dynamic spec fields rendered from service.spec_template
 *  - Live price calculation
 *  - Deposit due preview
 *  - Job creation (title auto-set to service name)
 *
 * Depends on: Auth, State (branchId, services, customers)
 */

const NJ = (() => {

  // ── Internal state ─────────────────────────────────────────
  let currentType    = 'INSTANT';
  let currentService = null;
  let priceTimer     = null;

  // ── Toast — works on dashboard and jobs page ───────────────
  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ── Helpers ────────────────────────────────────────────────
  function _esc(s) {
    return String(s ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _getModal() {
    return document.querySelector('#new-job-modal .modal');
  }

  // ── Toggle pill positioning ────────────────────────────────
  function _positionPill() {
    const toggle = document.getElementById('nj-type-toggle');
    const active = toggle.querySelector('.nj-toggle-btn.active');
    const pill   = document.getElementById('nj-toggle-pill');
    if (!active || !pill) return;
    pill.style.left  = active.offsetLeft + 'px';
    pill.style.width = active.offsetWidth + 'px';
  }

  // ── Apply type color theme to toggle + modal ───────────────
  function _applyTheme(type) {
    const toggle = document.getElementById('nj-type-toggle');
    const modal  = _getModal();
    const slug   = type.toLowerCase();

    toggle.classList.remove('type-instant', 'type-production', 'type-design');
    toggle.classList.add(`type-${slug}`);

    if (modal) {
      modal.classList.remove('type-instant', 'type-production', 'type-design');
      modal.classList.add(`type-${slug}`);
    }
  }

  // ── Set job type ───────────────────────────────────────────
  function setType(type) {
    currentType    = type;
    currentService = null;

    document.querySelectorAll('.nj-toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.type === type);
    });

    _positionPill();
    _applyTheme(type);
    _populateServices();

    // Hide fields that don't apply to INSTANT jobs
    const isInstant = type === 'INSTANT';
    ['nj-priority-row', 'nj-deposit-deadline-row', 'nj-notes-row'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.style.display = isInstant ? 'none' : '';
    });

    document.getElementById('nj-spec-fields').innerHTML = '';
    _hidePriceBox();
  }

  // ── Populate services filtered by type ────────────────────
  function _populateServices() {
    const sel      = document.getElementById('nj-service');
    const filtered = State.services.filter(s => s.category === currentType);

    sel.innerHTML = '<option value="">Select service…</option>' +
      filtered.map(s =>
        `<option value="${s.id}">${_esc(s.name)}</option>`
      ).join('');

    // Auto-select if only one service for this type
    if (filtered.length === 1) {
      sel.value = filtered[0].id;
      onServiceChange();
    }
  }

  // ── On service selection ───────────────────────────────────
  function onServiceChange() {
    const sel       = document.getElementById('nj-service');
    const serviceId = parseInt(sel.value);
    currentService  = State.services.find(s => s.id === serviceId) || null;

    _renderSpecFields();
    _triggerPriceCalc();
  }

  // ── Render dynamic spec fields from spec_template ─────────
  function _renderSpecFields() {
    const container = document.getElementById('nj-spec-fields');
    if (!currentService || !currentService.spec_template?.length) {
      container.innerHTML = '';
      return;
    }

    const template = currentService.spec_template;
    let html = '';
    let i = 0;

    while (i < template.length) {
      const field = template[i];
      const isFullWidth = field.type === 'text' || field.type === 'textarea';

      if (isFullWidth) {
        html += `<div class="spec-field-row full">${_renderField(field)}</div>`;
        i++;
      } else {
        const next = template[i + 1];
        const nextIsFullWidth = !next || next.type === 'text' || next.type === 'textarea';
        if (next && !nextIsFullWidth) {
          html += `<div class="spec-field-row">${_renderField(field)}${_renderField(next)}</div>`;
          i += 2;
        } else {
          html += `<div class="spec-field-row">${_renderField(field)}</div>`;
          i++;
        }
      }
    }

    container.innerHTML = html;

    // Bind change events to re-trigger price calculation
    container.querySelectorAll('input, select').forEach(el => {
      el.addEventListener('change', _triggerPriceCalc);
      el.addEventListener('input',  _triggerPriceCalc);
    });
  }

  function _renderField(f) {
    const required = f.required ? 'required' : '';
    const reqMark  = f.required ? '' : ' <span style="color:#ccc;font-weight:400;">(optional)</span>';

    let input = '';

    if (f.type === 'select') {
      const opts = (f.options || []).map(o =>
        `<option value="${_esc(o)}" ${f.default === o ? 'selected' : ''}>${_esc(o)}</option>`
      ).join('');
      input = `<select id="spec-${f.key}" data-spec-key="${f.key}" class="form-input" ${required}>${opts}</select>`;

    } else if (f.type === 'number') {
      const min  = f.min  != null ? `min="${f.min}"`  : '';
      const max  = f.max  != null ? `max="${f.max}"`  : '';
      const def  = f.default != null ? `value="${f.default}"` : '';
      const unit = f.unit ? `<span style="font-size:12px;color:#aaa;margin-left:6px;">${_esc(f.unit)}</span>` : '';
      input = `<div style="display:flex;align-items:center;">
        <input type="number" id="spec-${f.key}" data-spec-key="${f.key}"
          class="form-input" ${min} ${max} ${def} ${required}
          style="flex:1;" onchange="NJ._triggerPriceCalc()">
        ${unit}
      </div>`;

    } else if (f.type === 'checkbox') {
      const checked = f.default ? 'checked' : '';
      input = `<div style="display:flex;align-items:center;gap:8px;margin-top:8px;">
        <input type="checkbox" id="spec-${f.key}" data-spec-key="${f.key}" ${checked}
          style="width:16px;height:16px;cursor:pointer;" onchange="NJ._triggerPriceCalc()">
        <span style="font-size:13px;color:#444;">${_esc(f.label)}</span>
      </div>`;
      return `<div class="form-group">${input}</div>`;

    } else if (f.type === 'textarea') {
      const def = f.default ? `placeholder="${_esc(f.default)}"` : '';
      input = `<textarea id="spec-${f.key}" data-spec-key="${f.key}"
        class="form-input" rows="2" ${required} ${def}
        style="resize:vertical;min-height:60px;"></textarea>`;

    } else {
      const def = f.default ? `placeholder="${_esc(f.default)}"` : '';
      input = `<input type="text" id="spec-${f.key}" data-spec-key="${f.key}"
        class="form-input" ${required} ${def}>`;
    }

    return `
      <div class="form-group">
        <label class="form-label" for="spec-${f.key}">${_esc(f.label).toUpperCase()}${reqMark}</label>
        ${input}
      </div>`;
  }

  // ── Collect spec values from rendered fields ───────────────
  function _collectSpecs() {
    const specs = {};
    document.querySelectorAll('#nj-spec-fields [data-spec-key]').forEach(el => {
      const key = el.dataset.specKey;
      if (el.type === 'checkbox') {
        specs[key] = el.checked;
      } else {
        specs[key] = el.value;
      }
    });
    return specs;
  }

  // ── Price calculation ──────────────────────────────────────
  function _triggerPriceCalc() {
    clearTimeout(priceTimer);
    priceTimer = setTimeout(_calcPrice, 350);
  }

  async function _calcPrice() {
    if (!currentService || !State.branchId) { _hidePriceBox(); return; }

    const specs    = _collectSpecs();
    const quantity = specs.quantity || 1;
    const pages    = specs.pages    || 1;
    const is_color = specs.color === 'Color' || specs.is_color === true ? 'true' : 'false';

    try {
      const params = new URLSearchParams({
        service  : currentService.id,
        branch   : State.branchId,
        quantity,
        pages,
        is_color,
      });
      const res  = await Auth.fetch(`/api/v1/jobs/price/calculate/?${params}`);
      if (!res.ok) { _hidePriceBox(); return; }
      const data = await res.json();
      const total = data.total || data.estimated_price || data.price;

      if (total != null) {
        const depositEl  = document.getElementById('nj-deposit');
        const depositPct = depositEl ? (parseInt(depositEl.value) || 100) : 100;
        const depositAmt = (parseFloat(total) * depositPct / 100);

        const priceEl = document.getElementById('nj-price');
        if (priceEl) {
          priceEl.textContent =
            `GHS ${parseFloat(total).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
        }

        const dueEl = document.getElementById('nj-deposit-due');
        if (dueEl) {
          dueEl.textContent =
            `GHS ${depositAmt.toLocaleString('en-GH', { minimumFractionDigits: 2 })} due`;
        }

        const box = document.getElementById('nj-price-box');
        if (box) box.classList.add('show');

      } else {
        _hidePriceBox();
      }
    } catch (e) {
      _hidePriceBox();
    }
  }

  function _hidePriceBox() {
    const box = document.getElementById('nj-price-box');
    if (box) box.classList.remove('show');
  }

  // ── Create job ─────────────────────────────────────────────
  async function createJob() {
    if (!currentService) {
      _toast('Please select a service.', 'error');
      return;
    }

    const specs    = _collectSpecs();
    const deadlineEl = document.getElementById('nj-deadline');
    const notesEl    = document.getElementById('nj-notes');
    const depositEl  = document.getElementById('nj-deposit');
    const channelEl  = document.getElementById('nj-channel');
    const customerEl = document.getElementById('nj-customer');
    const priorityEl = document.getElementById('nj-priority');

    const deadline = deadlineEl ? deadlineEl.value       : '';
    const notes    = notesEl    ? notesEl.value.trim()   : '';
    const deposit  = depositEl  ? parseInt(depositEl.value) : 100;
    const channel  = channelEl  ? channelEl.value        : 'WALK_IN';
    const customer = customerEl ? customerEl.value       : '';
    const priority = priorityEl ? priorityEl.value       : 'NORMAL';

    const quantity = parseInt(specs.quantity || specs.qty || 1);
    const pages    = parseInt(specs.pages    || 1);
    const is_color = specs.color === 'Color' || specs.is_color === true;

    const btn = document.getElementById('nj-submit-btn');
    if (btn) {
      btn.disabled    = true;
      btn.textContent = 'Creating…';
    }

    try {
      const body = {
        job_type           : currentType,
        service            : currentService.id,
        priority,
        intake_channel     : channel,
        deposit_percentage : deposit,
        specifications     : specs,
        quantity,
        pages,
        is_color,
        notes,
      };
      if (customer) body.customer = parseInt(customer);
      if (deadline) body.deadline = deadline;

      const res = await Auth.fetch('/api/v1/jobs/create/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || Object.values(err)[0] || 'Failed to create job.', 'error');
        return;
      }

      const job = await res.json();
      _toast(`${job.job_number || 'Job'} created — sent to cashier queue.`, 'success');
      closeNewJobModal();
      reset();

      // Refresh parent page
      if (typeof Dashboard !== 'undefined') {
        Dashboard.onJobCreated();
      } else if (typeof loadJobs === 'function') {
        State.page = 1;
        loadJobs();
      }

    } catch (e) {
      _toast('Network error. Please try again.', 'error');
    } finally {
      if (btn) {
        btn.disabled  = false;
        btn.innerHTML = `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Create Job`;
      }
    }
  }

  // ── Reset ──────────────────────────────────────────────────
  function reset() {
    currentService = null;
    currentType    = 'INSTANT';

    const fields = {
      'nj-service'  : '',
      'nj-priority' : 'NORMAL',
      'nj-channel'  : 'WALK_IN',
      'nj-customer' : '',
      'nj-deposit'  : '100',
      'nj-deadline' : '',
      'nj-notes'    : '',
    };

    Object.entries(fields).forEach(([id, val]) => {
      const el = document.getElementById(id);
      if (el) el.value = val;
    });

    const specFields = document.getElementById('nj-spec-fields');
    if (specFields) specFields.innerHTML = '';

    _hidePriceBox();

    document.querySelectorAll('.nj-toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.type === 'INSTANT');
    });
  }

  // ── Populate customers into dropdown ──────────────────────
  function populateCustomers() {
    const sel = document.getElementById('nj-customer');
    if (!sel) return;
    sel.innerHTML = '<option value="">Walk-in / Unknown</option>' +
      State.customers.map(c =>
        `<option value="${c.id}">${_esc(c.full_name || c.name || c.email || 'Customer ' + c.id)}</option>`
      ).join('');
  }

  // ── Open modal ─────────────────────────────────────────────
  function open() {
    reset();
    setType('INSTANT');
    populateCustomers();
    document.getElementById('new-job-modal').classList.add('open');
    requestAnimationFrame(_positionPill);
  }

  // ── Bind deposit change to update price preview ────────────
  document.addEventListener('DOMContentLoaded', () => {
    const depositSel = document.getElementById('nj-deposit');
    if (depositSel) {
      depositSel.addEventListener('change', _triggerPriceCalc);
    }
  });

  // ── Public API ─────────────────────────────────────────────
  return {
    setType,
    onServiceChange,
    createJob,
    reset,
    open,
    populateCustomers,
    _triggerPriceCalc,
  };

})();