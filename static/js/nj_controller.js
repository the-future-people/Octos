/**
 * NJ — New Job Modal Controller
 *
 * INSTANT  → POS-style cart: select service → configure → add to cart → repeat → submit
 * PRODUCTION / DESIGN → single-service form (unchanged behaviour)
 *
 * Depends on: Auth, State (branchId, services, customers)
 */

'use strict';

const NJ = (() => {

  // ── Internal state ─────────────────────────────────────────
  let currentType    = 'INSTANT';
  let currentService = null;
  let priceTimer     = null;

  // POS cart — only used for INSTANT
  // Each entry: { service, serviceId, serviceName, quantity, pages, sets,
  //               is_color, paper_size, sides, file_source, specs,
  //               unit_price, line_total, label }
  let cart = [];

  // ── Toast ──────────────────────────────────────────────────
  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className   = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ── Helpers ────────────────────────────────────────────────
  function _esc(s) {
    return String(s ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _fmt(n) {
    return `GHS ${parseFloat(n || 0).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
  }

  function _getModal() {
    return document.querySelector('#new-job-modal .modal');
  }

  // ── Toggle pill ────────────────────────────────────────────
  function _positionPill() {
    const toggle = document.getElementById('nj-type-toggle');
    const active = toggle?.querySelector('.nj-toggle-btn.active');
    const pill   = document.getElementById('nj-toggle-pill');
    if (!active || !pill) return;
    pill.style.left  = active.offsetLeft + 'px';
    pill.style.width = active.offsetWidth + 'px';
  }

  // ── Theme ──────────────────────────────────────────────────
  function _applyTheme(type) {
    const toggle = document.getElementById('nj-type-toggle');
    const modal  = _getModal();
    const slug   = type.toLowerCase();
    toggle?.classList.remove('type-instant', 'type-production', 'type-design');
    toggle?.classList.add(`type-${slug}`);
    if (modal) {
      modal.classList.remove('type-instant', 'type-production', 'type-design');
      modal.classList.add(`type-${slug}`);
    }
  }

  // ══════════════════════════════════════════════════════════
  // TYPE SWITCHING
  // ══════════════════════════════════════════════════════════

  function setType(type) {
    currentType    = type;
    currentService = null;
    cart           = [];

    document.querySelectorAll('.nj-toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.type === type);
    });

    _positionPill();
    _applyTheme(type);

    if (type === 'INSTANT') {
      _showInstantUI();
    } else {
      _showFormUI(type);
    }
  }

  // ══════════════════════════════════════════════════════════
  // INSTANT — POS CART UI
  // ══════════════════════════════════════════════════════════

  function _showInstantUI() {
    const body = document.getElementById('nj-modal-body');
    if (!body) return;

    const services = State.services.filter(s => s.category === 'INSTANT');

    body.innerHTML = `
      <div class="nj-pos-layout">

        <!-- Left: service picker + configurator -->
        <div class="nj-pos-left">

          <!-- Customer + channel row -->
          <div class="form-row-2" style="margin-bottom:14px;">
            <div class="form-group">
              <label class="form-label">Customer</label>
              <select id="nj-customer" class="form-input">
                <option value="">Walk-in / Unknown</option>
                ${State.customers.map(c =>
                  `<option value="${c.id}">${_esc(c.full_name || c.name || c.email || 'Customer ' + c.id)}</option>`
                ).join('')}
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Intake Channel</label>
              <select id="nj-channel" class="form-input">
                <option value="WALK_IN">Walk-in</option>
                <option value="WHATSAPP">WhatsApp</option>
                <option value="EMAIL">Email</option>
                <option value="PHONE">Phone</option>
              </select>
            </div>
          </div>

          <!-- Service grid -->
          <div class="form-group" style="margin-bottom:12px;">
            <label class="form-label">Select Service</label>
            <div class="nj-service-grid" id="nj-service-grid">
              ${services.map(s => `
                <button class="nj-service-chip" data-id="${s.id}" onclick="NJ._selectServiceChip(${s.id})">
                  ${_esc(s.name)}
                </button>`).join('')}
            </div>
          </div>

          <!-- Configurator — shown after service selected -->
          <div id="nj-configurator" style="display:none;">
            <div class="nj-configurator-head" id="nj-configurator-title">Configure</div>

            <!-- Core params -->
            <div class="form-row-2">
              <div class="form-group">
                <label class="form-label">Paper Size</label>
                <select id="nj-paper-size" class="form-input" onchange="NJ._triggerLinePrice()">
                  <option value="A4">A4</option>
                  <option value="A3">A3</option>
                  <option value="A5">A5</option>
                  <option value="A2">A2</option>
                  <option value="NA">N/A</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">Colour Mode</label>
                <select id="nj-color-mode" class="form-input" onchange="NJ._triggerLinePrice()">
                  <option value="BW">Black &amp; White</option>
                  <option value="COLOR">Colour</option>
                </select>
              </div>
            </div>

            <div class="form-row-2">
              <div class="form-group">
                <label class="form-label">Pages</label>
                <input type="number" id="nj-pages" class="form-input"
                  value="1" min="1" oninput="NJ._triggerLinePrice()">
              </div>
              <div class="form-group">
                <label class="form-label">Sets / Copies</label>
                <input type="number" id="nj-sets" class="form-input"
                  value="1" min="1" oninput="NJ._triggerLinePrice()">
              </div>
            </div>

            <div class="form-row-2">
              <div class="form-group">
                <label class="form-label">Sides</label>
                <select id="nj-sides" class="form-input" onchange="NJ._triggerLinePrice()">
                  <option value="SINGLE">Single-sided</option>
                  <option value="DOUBLE">Double-sided</option>
                </select>
              </div>
              <div class="form-group">
                <label class="form-label">File Source</label>
                <select id="nj-file-source" class="form-input">
                  <option value="HARDCOPY">Walk-in Hardcopy</option>
                  <option value="WHATSAPP">WhatsApp</option>
                  <option value="EMAIL">Email</option>
                  <option value="USB">USB</option>
                  <option value="TYPING">Typing Request</option>
                  <option value="NA">N/A</option>
                </select>
              </div>
            </div>

            <!-- Dynamic spec fields from spec_template -->
            <div id="nj-spec-fields"></div>

            <!-- Line price preview -->
            <div class="nj-line-price-box" id="nj-line-price-box" style="display:none;">
              <span style="font-size:12px;color:var(--green-text);font-weight:600;">LINE TOTAL</span>
              <span id="nj-line-price" style="font-family:'JetBrains Mono',monospace;font-size:16px;font-weight:700;color:var(--green-text);">—</span>
            </div>

            <button class="nj-add-btn" onclick="NJ._addToCart()">
              <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              Add to Cart
            </button>
          </div>

        </div>

        <!-- Right: cart -->
        <div class="nj-pos-right">
          <div class="nj-cart-head">
            <span style="font-size:12px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Cart</span>
            <span class="nj-cart-count" id="nj-cart-count">0 items</span>
          </div>

          <div class="nj-cart-list" id="nj-cart-list">
            <div class="nj-cart-empty">
              <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>
              <div>No items yet</div>
              <div style="font-size:11px;margin-top:2px;">Select a service to begin</div>
            </div>
          </div>

          <div class="nj-cart-total" id="nj-cart-total" style="display:none;">
            <span>Total</span>
            <span id="nj-total-amount" style="font-family:'JetBrains Mono',monospace;font-weight:700;">GHS 0.00</span>
          </div>
        </div>

      </div>`;
  }

  // ── Service chip selection ─────────────────────────────────
  function _selectServiceChip(serviceId) {
    currentService = State.services.find(s => s.id === serviceId) || null;
    if (!currentService) return;

    // Highlight selected chip
    document.querySelectorAll('.nj-service-chip').forEach(btn => {
      btn.classList.toggle('active', parseInt(btn.dataset.id) === serviceId);
    });

    // Show configurator
    const cfg = document.getElementById('nj-configurator');
    if (cfg) cfg.style.display = 'block';

    const title = document.getElementById('nj-configurator-title');
    if (title) title.textContent = currentService.name;

    // Render spec template fields
    _renderSpecFields();
    _triggerLinePrice();
  }

  // ── Line price calculation (per item being configured) ─────
  function _triggerLinePrice() {
    clearTimeout(priceTimer);
    priceTimer = setTimeout(_calcLinePrice, 300);
  }

  async function _calcLinePrice() {
    if (!currentService || !State.branchId) {
      document.getElementById('nj-line-price-box').style.display = 'none';
      return;
    }

    const pages    = parseInt(document.getElementById('nj-pages')?.value  || 1);
    const sets     = parseInt(document.getElementById('nj-sets')?.value   || 1);
    const is_color = document.getElementById('nj-color-mode')?.value === 'COLOR';
    const quantity = pages * sets || 1;

    try {
      const params = new URLSearchParams({
        service  : currentService.id,
        branch   : State.branchId,
        quantity,
        pages,
        is_color : is_color ? 'true' : 'false',
      });
      const res  = await Auth.fetch(`/api/v1/jobs/price/calculate/?${params}`);
      if (!res.ok) return;
      const data  = await res.json();
      const total = data.total || 0;

      const box = document.getElementById('nj-line-price-box');
      const el  = document.getElementById('nj-line-price');
      if (box && el) {
        el.textContent  = _fmt(total);
        box.style.display = 'flex';
      }
    } catch { /* silent */ }
  }

  // ── Add current configuration to cart ─────────────────────
  async function _addToCart() {
    if (!currentService) { _toast('Select a service first.', 'error'); return; }

    const pages      = parseInt(document.getElementById('nj-pages')?.value      || 1);
    const sets       = parseInt(document.getElementById('nj-sets')?.value       || 1);
    const is_color   = document.getElementById('nj-color-mode')?.value === 'COLOR';
    const paper_size = document.getElementById('nj-paper-size')?.value  || 'A4';
    const sides      = document.getElementById('nj-sides')?.value       || 'SINGLE';
    const file_src   = document.getElementById('nj-file-source')?.value || 'NA';
    const specs      = _collectSpecs();
    const quantity   = pages * sets || 1;

    // Get price
    let unit_price = 0;
    let line_total = 0;
    try {
      const params = new URLSearchParams({
        service  : currentService.id,
        branch   : State.branchId,
        quantity,
        pages,
        is_color : is_color ? 'true' : 'false',
      });
      const res = await Auth.fetch(`/api/v1/jobs/price/calculate/?${params}`);
      if (res.ok) {
        const data = await res.json();
        unit_price = parseFloat(data.base_price || 0);
        line_total = parseFloat(data.total      || 0);
      }
    } catch { /* silent — add with 0 price */ }

    cart.push({
      serviceId   : currentService.id,
      serviceName : currentService.name,
      pages,
      sets,
      quantity,
      is_color,
      paper_size,
      sides,
      file_source : file_src,
      specifications: specs,
      unit_price,
      line_total,
    });

    _renderCart();
    _resetConfigurator();
    _toast(`${currentService.name} added.`, 'success');
  }

  // ── Reset configurator after adding ───────────────────────
  function _resetConfigurator() {
    currentService = null;
    document.querySelectorAll('.nj-service-chip').forEach(b => b.classList.remove('active'));
    const cfg = document.getElementById('nj-configurator');
    if (cfg) cfg.style.display = 'none';
    const box = document.getElementById('nj-line-price-box');
    if (box) box.style.display = 'none';
    const specs = document.getElementById('nj-spec-fields');
    if (specs) specs.innerHTML = '';
  }

  // ── Render cart ────────────────────────────────────────────
  function _renderCart() {
    const list      = document.getElementById('nj-cart-list');
    const countEl   = document.getElementById('nj-cart-count');
    const totalBox  = document.getElementById('nj-cart-total');
    const totalEl   = document.getElementById('nj-total-amount');
    if (!list) return;

    const total = cart.reduce((sum, item) => sum + item.line_total, 0);

    if (countEl)  countEl.textContent = `${cart.length} item${cart.length !== 1 ? 's' : ''}`;
    if (totalEl)  totalEl.textContent = _fmt(total);
    if (totalBox) totalBox.style.display = cart.length ? 'flex' : 'none';

    if (!cart.length) {
      list.innerHTML = `
        <div class="nj-cart-empty">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="9" cy="21" r="1"/><circle cx="20" cy="21" r="1"/><path d="M1 1h4l2.68 13.39a2 2 0 0 0 2 1.61h9.72a2 2 0 0 0 2-1.61L23 6H6"/></svg>
          <div>No items yet</div>
          <div style="font-size:11px;margin-top:2px;">Select a service to begin</div>
        </div>`;
      return;
    }

    list.innerHTML = cart.map((item, i) => {
      const qty_label = item.pages > 1
        ? `${item.pages}pp × ${item.sets} sets`
        : `× ${item.quantity}`;
      const color_label = item.is_color ? 'Colour' : 'B&W';

      return `
        <div class="nj-cart-item">
          <div class="nj-cart-item-info">
            <div class="nj-cart-item-name">${_esc(item.serviceName)}</div>
            <div class="nj-cart-item-meta">${_esc(item.paper_size)} · ${color_label} · ${qty_label}</div>
          </div>
          <div class="nj-cart-item-right">
            <span class="nj-cart-item-price">${_fmt(item.line_total)}</span>
            <button class="nj-cart-remove" onclick="NJ._removeFromCart(${i})" title="Remove">×</button>
          </div>
        </div>`;
    }).join('');
  }

  // ── Remove from cart ───────────────────────────────────────
  function _removeFromCart(index) {
    cart.splice(index, 1);
    _renderCart();
  }

  // ══════════════════════════════════════════════════════════
  // PRODUCTION / DESIGN — FORM UI (unchanged behaviour)
  // ══════════════════════════════════════════════════════════

  function _showFormUI(type) {
    const body = document.getElementById('nj-modal-body');
    if (!body) return;

    const services = State.services.filter(s => s.category === type);

    body.innerHTML = `
      <div class="form-row-2">
        <div class="form-group">
          <label class="form-label">Service</label>
          <select id="nj-service" class="form-input" onchange="NJ.onServiceChange()">
            <option value="">Select service…</option>
            ${services.map(s => `<option value="${s.id}">${_esc(s.name)}</option>`).join('')}
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Priority</label>
          <select id="nj-priority" class="form-input">
            <option value="NORMAL">Normal</option>
            <option value="HIGH">High</option>
            <option value="URGENT">Urgent</option>
          </select>
        </div>
      </div>

      <div class="form-row-2">
        <div class="form-group">
          <label class="form-label">Customer <span style="color:var(--text-3);font-weight:400;">(optional)</span></label>
          <select id="nj-customer" class="form-input">
            <option value="">Walk-in / Unknown</option>
            ${State.customers.map(c =>
              `<option value="${c.id}">${_esc(c.full_name || c.name || c.email || 'Customer ' + c.id)}</option>`
            ).join('')}
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Intake Channel</label>
          <select id="nj-channel" class="form-input">
            <option value="WALK_IN">Walk-in</option>
            <option value="WHATSAPP">WhatsApp</option>
            <option value="EMAIL">Email</option>
            <option value="PHONE">Phone</option>
          </select>
        </div>
      </div>

      <!-- Dynamic spec fields -->
      <div id="nj-spec-fields"></div>

      <div class="form-row-2">
        <div class="form-group">
          <label class="form-label">Deposit</label>
          <select id="nj-deposit" class="form-input">
            <option value="100">100% — Full Payment</option>
            <option value="70">70% — Deposit</option>
          </select>
        </div>
        <div class="form-group">
          <label class="form-label">Deadline <span style="color:var(--text-3);font-weight:400;">(optional)</span></label>
          <input type="datetime-local" id="nj-deadline" class="form-input">
        </div>
      </div>

      <div class="form-group">
        <label class="form-label">Notes <span style="color:var(--text-3);font-weight:400;">(optional)</span></label>
        <textarea id="nj-notes" class="form-input" rows="2" placeholder="Any special instructions…"></textarea>
      </div>

      <div class="nj-price-box" id="nj-price-box" style="display:none;">
        <span style="font-size:12px;color:var(--green-text);font-weight:600;">ESTIMATED COST</span>
        <span id="nj-price" style="font-family:'JetBrains Mono',monospace;font-size:18px;font-weight:700;color:var(--green-text);">—</span>
      </div>`;

    // Auto-select if only one service
    if (services.length === 1) {
      const sel = document.getElementById('nj-service');
      if (sel) { sel.value = services[0].id; onServiceChange(); }
    }
  }

  // ── On service selection (Production/Design) ───────────────
  function onServiceChange() {
    const sel       = document.getElementById('nj-service');
    if (!sel) return;
    const serviceId = parseInt(sel.value);
    currentService  = State.services.find(s => s.id === serviceId) || null;
    _renderSpecFields();
    _triggerPriceCalc();
  }

  // ── Spec fields (shared between Instant configurator and P/D form) ──
  function _renderSpecFields() {
    const container = document.getElementById('nj-spec-fields');
    if (!container) return;
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
        const nextFull = !next || next.type === 'text' || next.type === 'textarea';
        if (next && !nextFull) {
          html += `<div class="spec-field-row">${_renderField(field)}${_renderField(next)}</div>`;
          i += 2;
        } else {
          html += `<div class="spec-field-row">${_renderField(field)}</div>`;
          i++;
        }
      }
    }

    container.innerHTML = html;
    container.querySelectorAll('input, select').forEach(el => {
      el.addEventListener('change', currentType === 'INSTANT' ? _triggerLinePrice : _triggerPriceCalc);
      el.addEventListener('input',  currentType === 'INSTANT' ? _triggerLinePrice : _triggerPriceCalc);
    });
  }

  function _renderField(f) {
    const required = f.required ? 'required' : '';
    const reqMark  = f.required ? '' : ' <span style="color:var(--text-3);font-weight:400;">(optional)</span>';
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
      const unit = f.unit ? `<span style="font-size:12px;color:var(--text-3);margin-left:6px;">${_esc(f.unit)}</span>` : '';
      input = `<div style="display:flex;align-items:center;">
        <input type="number" id="spec-${f.key}" data-spec-key="${f.key}"
          class="form-input" ${min} ${max} ${def} ${required} style="flex:1;">
        ${unit}
      </div>`;

    } else if (f.type === 'checkbox') {
      const checked = f.default ? 'checked' : '';
      input = `<div style="display:flex;align-items:center;gap:8px;margin-top:8px;">
        <input type="checkbox" id="spec-${f.key}" data-spec-key="${f.key}" ${checked}
          style="width:16px;height:16px;cursor:pointer;">
        <span style="font-size:13px;color:var(--text-2);">${_esc(f.label)}</span>
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

  function _collectSpecs() {
    const specs = {};
    document.querySelectorAll('#nj-spec-fields [data-spec-key]').forEach(el => {
      specs[el.dataset.specKey] = el.type === 'checkbox' ? el.checked : el.value;
    });
    return specs;
  }

  // ── Price calc for Production/Design ──────────────────────
  function _triggerPriceCalc() {
    clearTimeout(priceTimer);
    priceTimer = setTimeout(_calcPrice, 350);
  }

  async function _calcPrice() {
    if (!currentService || !State.branchId) { _hidePriceBox(); return; }

    const specs    = _collectSpecs();
    const quantity = parseInt(specs.quantity || 1);
    const pages    = parseInt(specs.pages    || 1);
    const is_color = specs.color === 'Color' || specs.is_color === true ? 'true' : 'false';

    try {
      const params = new URLSearchParams({
        service: currentService.id,
        branch : State.branchId,
        quantity, pages, is_color,
      });
      const res  = await Auth.fetch(`/api/v1/jobs/price/calculate/?${params}`);
      if (!res.ok) { _hidePriceBox(); return; }
      const data  = await res.json();
      const total = data.total;

      if (total != null) {
        const box = document.getElementById('nj-price-box');
        const el  = document.getElementById('nj-price');
        if (box && el) {
          el.textContent    = _fmt(total);
          box.style.display = 'flex';
        }
      } else {
        _hidePriceBox();
      }
    } catch { _hidePriceBox(); }
  }

  function _hidePriceBox() {
    const box = document.getElementById('nj-price-box');
    if (box) box.style.display = 'none';
  }

  // ══════════════════════════════════════════════════════════
  // CREATE JOB
  // ══════════════════════════════════════════════════════════

  async function createJob() {
    const btn = document.getElementById('nj-submit-btn');

    // ── INSTANT — submit cart ─────────────────────────────────
    if (currentType === 'INSTANT') {
      if (!cart.length) {
        _toast('Add at least one service to the cart.', 'error');
        return;
      }

      const channel  = document.getElementById('nj-channel')?.value  || 'WALK_IN';
      const customer = document.getElementById('nj-customer')?.value || '';

      if (btn) { btn.disabled = true; btn.textContent = 'Creating…'; }

      try {
        const body = {
          job_type           : 'INSTANT',
          intake_channel     : channel,
          deposit_percentage : 100,
          line_items         : cart.map((item, i) => ({
            service        : item.serviceId,
            quantity       : item.quantity,
            pages          : item.pages,
            sets           : item.sets,
            is_color       : item.is_color,
            paper_size     : item.paper_size,
            sides          : item.sides,
            file_source    : item.file_source,
            specifications : item.specifications,
            position       : i,
          })),
        };
        if (customer) body.customer = parseInt(customer);

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
        const total = _fmt(cart.reduce((s, i) => s + i.line_total, 0));
        _toast(`${job.job_number} created — ${cart.length} service${cart.length > 1 ? 's' : ''}, ${total}`, 'success');
        closeNewJobModal();
        reset();
        _onJobCreated();

      } catch { _toast('Network error. Please try again.', 'error'); }
      finally  { if (btn) { btn.disabled = false; btn.innerHTML = _submitBtnHTML(); } }
      return;
    }

    // ── PRODUCTION / DESIGN — submit single service ───────────
    if (!currentService) {
      _toast('Please select a service.', 'error');
      return;
    }

    const specs    = _collectSpecs();
    const deadline = document.getElementById('nj-deadline')?.value       || '';
    const notes    = document.getElementById('nj-notes')?.value.trim()   || '';
    const deposit  = parseInt(document.getElementById('nj-deposit')?.value || 100);
    const channel  = document.getElementById('nj-channel')?.value        || 'WALK_IN';
    const customer = document.getElementById('nj-customer')?.value       || '';
    const priority = document.getElementById('nj-priority')?.value       || 'NORMAL';
    const quantity = parseInt(specs.quantity || 1);
    const pages    = parseInt(specs.pages    || 1);
    const is_color = specs.color === 'Color' || specs.is_color === true;

    if (btn) { btn.disabled = true; btn.textContent = 'Creating…'; }

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
      _onJobCreated();

    } catch { _toast('Network error. Please try again.', 'error'); }
    finally  { if (btn) { btn.disabled = false; btn.innerHTML = _submitBtnHTML(); } }
  }

  function _submitBtnHTML() {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg> Create Job`;
  }

  function _onJobCreated() {
    if (typeof Dashboard !== 'undefined') {
      Dashboard.onJobCreated();
    } else if (typeof loadJobs === 'function') {
      State.page = 1;
      loadJobs();
    }
  }

  // ══════════════════════════════════════════════════════════
  // RESET + OPEN + PUBLIC API
  // ══════════════════════════════════════════════════════════

  function reset() {
    currentService = null;
    currentType    = 'INSTANT';
    cart           = [];
  }

  function populateCustomers() {
    // Customers are now injected directly into the modal body HTML
    // This is a no-op kept for compatibility
  }

  function open() {
    reset();
    document.getElementById('new-job-modal')?.classList.add('open');
    // Render INSTANT ui by default
    document.querySelectorAll('.nj-toggle-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.type === 'INSTANT');
    });
    _applyTheme('INSTANT');
    _positionPill();
    _showInstantUI();
    requestAnimationFrame(_positionPill);
  }

  return {
    setType,
    onServiceChange,
    createJob,
    reset,
    open,
    populateCustomers,
    _triggerPriceCalc,
    _triggerLinePrice,
    _selectServiceChip,
    _addToCart,
    _removeFromCart,
  };

})();