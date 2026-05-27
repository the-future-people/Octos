/**
 * Octos — Branch Manager Service Catalogue
 * static/js/branch_manager/catalogue.js
 *
 * Responsibilities:
 *  - Render the service catalogue grid (pane-catalogue)
 *  - Add Service modal: form, consumable mappings, image upload, submit
 *
 * Dependencies:
 *  - auth.js (Auth.fetch)
 *  - dashboard.js (State.services, Dashboard._esc, Dashboard._toast)
 *
 * Loaded before dashboard.js.
 * dashboard.js calls: Catalogue.loadServicesTab(), Catalogue.openAddServiceModal()
 * Template inline handlers use: Catalogue.* prefix
 */

'use strict';

const Catalogue = (() => {

  // ── Private state ──────────────────────────────────────────
  let _consumables = [];
  let _loaded      = false;

  // ── Service catalogue grid ─────────────────────────────────

  async function loadServicesTab() {
    if (_loaded) return;
    _loaded = true;

    const grid = document.getElementById('services-grid');
    if (!grid) return;

    const services = (typeof State !== 'undefined') ? State.services : [];

    if (!services.length) {
      grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;
        color:var(--text-3);">No services available.</div>`;
      return;
    }

    grid.innerHTML = services.map(s => `
      <div class="service-card">
        ${s.image
          ? `<div class="service-card-img">
               <img src="${s.image}" alt="${_esc(s.name)}"
                 style="width:100%;height:100%;object-fit:cover;border-radius:var(--radius-sm);">
             </div>`
          : `<div class="service-card-img service-card-img--placeholder">
               <svg width="28" height="28" viewBox="0 0 24 24" fill="none"
                 stroke="currentColor" stroke-width="1.5" opacity="0.3">
                 <rect x="3" y="3" width="18" height="18" rx="2"/>
                 <circle cx="8.5" cy="8.5" r="1.5"/>
                 <polyline points="21 15 16 10 5 21"/>
               </svg>
             </div>`}
        <div class="service-card-body">
          <div class="service-card-name">${_esc(s.name)}</div>
          <div class="service-card-price">${s.base_price != null ? 'GHS ' + Number(s.base_price).toFixed(2) : '—'}</div>
          <div class="service-card-desc">${_esc(s.description || '')}</div>
        </div>
      </div>`).join('');
  }

  // Reset loaded flag so catalogue re-renders after a new service is added
  function resetLoaded() {
    _loaded = false;
  }

  // ── Add Service modal ──────────────────────────────────────

  async function openAddServiceModal() {
    document.getElementById('svc-name').value        = '';
    document.getElementById('svc-code').value        = '';
    document.getElementById('svc-price').value       = '';
    document.getElementById('svc-description').value = '';
    document.getElementById('svc-image').value       = '';
    document.getElementById('svc-image-preview').style.display = 'none';
    document.getElementById('svc-error').style.display         = 'none';
    document.getElementById('svc-category').value   = 'INSTANT';
    document.getElementById('svc-unit').value       = 'PER_PIECE';
    document.getElementById('svc-sides').value      = 'SINGLE';

    document.getElementById('add-service-overlay').classList.add('open');

    if (!_consumables.length) {
      await _loadConsumables();
    } else {
      _renderConsumables();
    }
  }

  function closeAddServiceModal() {
    document.getElementById('add-service-overlay').classList.remove('open');
  }

  async function _loadConsumables() {
    try {
      const res  = await Auth.fetch('/api/v1/inventory/stock/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      _consumables = Array.isArray(data) ? data : (data.results || []);
      _renderConsumables();
    } catch {
      document.getElementById('svc-consumables-list').innerHTML =
        '<div class="eod-empty-note">Could not load consumables.</div>';
    }
  }

  function _renderConsumables() {
    const container = document.getElementById('svc-consumables-list');
    if (!_consumables.length) {
      container.innerHTML = '<div class="eod-empty-note">No consumables found.</div>';
      return;
    }

    const mappable = _consumables.filter(c =>
      !c.name.toLowerCase().includes('toner')
    );

    if (!mappable.length) {
      container.innerHTML = '<div class="eod-empty-note">No consumables found.</div>';
      return;
    }

    container.innerHTML = mappable.map((c, i) => `
      <div style="display:grid;grid-template-columns:auto 1fr auto auto auto;
        align-items:center;gap:10px;padding:8px 0;
        border-bottom:1px solid var(--border);">
        <input type="checkbox" id="svc-con-check-${i}"
          onchange="Catalogue._svcToggleConsumable(${i})"
          style="width:15px;height:15px;cursor:pointer;">
        <label for="svc-con-check-${i}"
          style="font-size:12px;font-weight:500;color:var(--text);cursor:pointer;">
          ${_esc(c.name)}
          <span style="font-size:11px;color:var(--text-3);margin-left:4px;">
            ${_esc(c.unit_label || '')}
          </span>
        </label>
        <input type="number" id="svc-con-qty-${i}"
          value="1.0" min="0.0001" step="0.0001"
          placeholder="qty/unit" disabled
          style="width:80px;padding:5px 8px;font-size:12px;
            font-family:'JetBrains Mono',monospace;
            background:var(--input-bg);border:1px solid var(--border);
            border-radius:var(--radius-sm);color:var(--text);opacity:0.4;">
        <label style="display:flex;align-items:center;gap:4px;
          font-size:11px;color:var(--text-3);opacity:0.4;" id="svc-con-color-label-${i}">
          <input type="checkbox" id="svc-con-color-${i}" checked disabled
            style="width:12px;height:12px;">
          Color
        </label>
        <label style="display:flex;align-items:center;gap:4px;
          font-size:11px;color:var(--text-3);opacity:0.4;" id="svc-con-bw-label-${i}">
          <input type="checkbox" id="svc-con-bw-${i}" checked disabled
            style="width:12px;height:12px;">
          B&amp;W
        </label>
      </div>`).join('');
  }

  function _svcToggleConsumable(i) {
    const checked  = document.getElementById(`svc-con-check-${i}`).checked;
    const qty      = document.getElementById(`svc-con-qty-${i}`);
    const colorLbl = document.getElementById(`svc-con-color-label-${i}`);
    const bwLbl    = document.getElementById(`svc-con-bw-label-${i}`);
    const colorChk = document.getElementById(`svc-con-color-${i}`);
    const bwChk    = document.getElementById(`svc-con-bw-${i}`);

    qty.disabled      = !checked;
    colorChk.disabled = !checked;
    bwChk.disabled    = !checked;
    qty.style.opacity      = checked ? '1' : '0.4';
    colorLbl.style.opacity = checked ? '1' : '0.4';
    bwLbl.style.opacity    = checked ? '1' : '0.4';
  }

  function _svcAutoCode() {
    const name = document.getElementById('svc-name').value;
    const code = name.trim().toUpperCase()
      .replace(/[^A-Z0-9\s]/g, '')
      .replace(/\s+/g, '-')
      .substring(0, 20);
    document.getElementById('svc-code').value = code;
  }

  function _svcPreviewImage() {
    const file    = document.getElementById('svc-image').files[0];
    const preview = document.getElementById('svc-image-preview');
    if (file) {
      preview.src           = URL.createObjectURL(file);
      preview.style.display = 'block';
    } else {
      preview.style.display = 'none';
    }
  }

  async function submitAddService() {
    const btn = document.getElementById('svc-submit-btn');
    const err = document.getElementById('svc-error');
    err.style.display = 'none';

    const name      = document.getElementById('svc-name').value.trim();
    const code      = document.getElementById('svc-code').value.trim().toUpperCase();
    const category  = document.getElementById('svc-category').value;
    const unit      = document.getElementById('svc-unit').value;
    const price     = document.getElementById('svc-price').value.trim();
    const desc      = document.getElementById('svc-description').value.trim();
    const imageFile = document.getElementById('svc-image').files[0];
    const sides     = document.getElementById('svc-sides').value;

    if (!name)  { _showSvcError('Service name is required.'); return; }
    if (!code)  { _showSvcError('Service code is required.'); return; }
    if (!price || isNaN(parseFloat(price)) || parseFloat(price) < 0) {
      _showSvcError('A valid base price is required.'); return;
    }

    // Build consumable mappings
    const mappable = _consumables.filter(c =>
      !c.name.toLowerCase().includes('toner')
    );
    const mappings = [];
    mappable.forEach((c, i) => {
      if (!document.getElementById(`svc-con-check-${i}`)?.checked) return;
      const qty   = parseFloat(document.getElementById(`svc-con-qty-${i}`).value);
      const color = document.getElementById(`svc-con-color-${i}`).checked;
      const bw    = document.getElementById(`svc-con-bw-${i}`).checked;
      if (qty > 0) {
        mappings.push({
          consumable_id    : c.consumable,
          quantity_per_unit: qty,
          applies_to_color : color,
          applies_to_bw    : bw,
        });
      }
    });

    const fd = new FormData();
    fd.append('name',        name);
    fd.append('code',        code);
    fd.append('category',    category);
    fd.append('unit',        unit);
    fd.append('base_price',  price);
    fd.append('description', desc);
    fd.append('sides',       sides);
    if (imageFile) fd.append('image', imageFile);
    if (mappings.length) fd.append('consumable_mappings', JSON.stringify(mappings));

    btn.disabled    = true;
    btn.textContent = 'Saving…';

    try {
      const res  = await Auth.fetch('/api/v1/jobs/services/create/', {
        method: 'POST',
        body  : fd,
      });
      const data = await res.json();

      if (!res.ok) {
        const msg = Object.values(data).flat().join(' ');
        _showSvcError(msg || 'Failed to save service.');
        return;
      }

      // Update shared State
      if (typeof State !== 'undefined') {
        State.services.push(data);
      }

      // Update meta strip counts
      const count = State?.services?.length || 0;
      const metaSvc = document.getElementById('meta-services');
      if (metaSvc) metaSvc.textContent = count;
      const metaCount = document.getElementById('meta-services-count');
      if (metaCount) metaCount.textContent = `${count} services`;

      // Force re-render on next catalogue open
      resetLoaded();
      loadServicesTab();

      closeAddServiceModal();
      if (typeof Dashboard !== 'undefined') {
        Dashboard._toast(`Service "${data.name}" added successfully.`, 'success');
      }

    } catch {
      _showSvcError('Network error. Please try again.');
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Save Service';
    }
  }

  function _showSvcError(msg) {
    const err = document.getElementById('svc-error');
    err.textContent   = msg;
    err.style.display = 'block';
  }

  // ── Private helpers ────────────────────────────────────────
  function _esc(str) {
    return String(str ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    loadServicesTab,
    resetLoaded,
    openAddServiceModal,
    closeAddServiceModal,
    submitAddService,
    _svcAutoCode,
    _svcPreviewImage,
    _svcToggleConsumable,
  };

})();