'use strict';

const Inventory = (() => {

  // ── Private state ──────────────────────────────────────────
  let _inventoryTab = 'consumables';

  // ── Helpers ────────────────────────────────────────────────
  function _esc(str) {
    return String(str ?? '')
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
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ── Inventory pane ─────────────────────────────────────────
  async function loadInventoryPane() {
    const pane = document.getElementById('pane-inventory');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head" style="margin-bottom:0;">
        <span class="section-title">Inventory</span>
      </div>
      <div style="display:flex;gap:0;border-bottom:2px solid var(--border);margin-bottom:20px;">
        ${[['consumables','Consumables'],['equipment','Equipment'],['movements','Movements'],['waste','Waste Incidents']].map(([t,l]) => `
          <button class="reports-tab ${_inventoryTab===t?'active':''}" data-tab="${t}"
            onclick="Inventory.switchInventoryTab('${t}')"
            style="padding:10px 18px;font-size:13px;">${l}</button>`).join('')}
      </div>
      <div id="inventory-content">
        <div class="loading-cell"><span class="spin"></span> Loading...</div>
      </div>`;

    await _loadInventoryTab(_inventoryTab);
  }

  async function switchInventoryTab(tab) {
    _inventoryTab = tab;
    document.querySelectorAll('#pane-inventory .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    await _loadInventoryTab(tab);
  }

  async function _loadInventoryTab(tab) {
    const content = document.getElementById('inventory-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading...</div>';
    if (tab === 'consumables') await _renderStockLevels(content);
    if (tab === 'equipment')   await _renderEquipment(content);
    if (tab === 'movements')   await _renderStockMovements(content);
    if (tab === 'waste')       await _renderWasteIncidents(content);
  }

  // ── Consumables tab ────────────────────────────────────────
  async function _renderStockLevels(container) {
    try {
      const res  = await Auth.fetch('/api/v1/inventory/stock/');
      if (!res.ok) throw new Error();
      const data  = await res.json();
      const items = data.results || data;

      if (!items.length) {
        container.innerHTML = '<div class="loading-cell">No stock data available.</div>';
        return;
      }

      const lowItems = items.filter(i =>
        parseFloat(i.quantity) <= parseFloat(i.reorder_point) &&
        i.category !== 'Machinery'
      );

      const alertHtml = lowItems.length ? `
        <div style="padding:10px 14px;background:#fee2e2;
          border:1px solid #fca5a5;border-radius:8px;margin-bottom:16px;
          display:flex;align-items:center;gap:8px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
            viewBox="0 0 24 24" fill="none" stroke="#991b1b" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <line x1="12" y1="8" x2="12" y2="12"/>
            <line x1="12" y1="16" x2="12.01" y2="16"/>
          </svg>
          <span style="font-size:11px;font-weight:700;color:#991b1b;">
            Low stock: ${lowItems.map(i => i.name).join(', ')}
          </span>
        </div>` : '';

      container.innerHTML = `
        <div style="display:flex;justify-content:flex-end;margin-bottom:16px;">
          <button onclick="Inventory.openReceiveStock()"
            style="padding:8px 18px;background:var(--text);color:#fff;border:none;
                   border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                   cursor:pointer;font-family:'DM Sans',sans-serif;">
            + Receive Stock
          </button>
        </div>
        ${alertHtml}
        ${renderInventoryCards(items.filter(i => i.category !== 'Machinery'), 'live')}`;

    } catch(e) {
      console.error('_renderStockLevels threw:', e);
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load stock levels.</div>';
    }
  }

  // ── Equipment tab ──────────────────────────────────────────
  async function _renderEquipment(container) {
    try {
      const res  = await Auth.fetch('/api/v1/inventory/equipment/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const items = Array.isArray(data) ? data : (data.results || []);

      const conditionBadge = c => {
        const map = {
          GOOD          : ['#dcfce7','#166534','Good'],
          FAIR          : ['#fef9c3','#854d0e','Fair'],
          NEEDS_SERVICE : ['#ffedd5','#9a3412','Needs Service'],
          OUT_OF_SERVICE: ['#fee2e2','#991b1b','Out of Service'],
          OVERDUE       : ['#fee2e2','#991b1b','Overdue'],
        };
        const [bg, color, label] = map[c] || ['#f3f4f6','#374151', c];
        return `<span style="padding:2px 10px;border-radius:20px;font-size:11px;
          font-weight:700;background:${bg};color:${color};">${label}</span>`;
      };

      container.innerHTML = `
        <div style="display:flex;justify-content:flex-end;margin-bottom:16px;">
          <button onclick="Inventory._openAddEquipment()"
            style="padding:8px 16px;background:var(--text);color:#fff;border:none;
              border-radius:var(--radius-sm);font-size:13px;font-weight:600;
              cursor:pointer;font-family:inherit;">
            + Add Equipment
          </button>
        </div>
        ${!items.length ? `
          <div class="loading-cell">No equipment recorded for this branch.</div>` : `
        <div style="border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);border-bottom:1px solid var(--border);">
                <th style="padding:10px 14px;font-size:11px;font-weight:700;color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">Asset</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">Equipment</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;color:var(--text-3);text-align:center;text-transform:uppercase;letter-spacing:0.5px;">Qty</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">Condition</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">Last Serviced</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">Next Due</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">Location</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(eq => `
                <tr onclick="Inventory._openEquipmentModal(${eq.id})"
                  style="border-bottom:1px solid var(--border);cursor:pointer;transition:background 0.1s;"
                  onmouseover="this.style.background='var(--bg)'"
                  onmouseout="this.style.background=''">
                  <td style="padding:12px 14px;font-size:12px;font-weight:700;color:var(--text-3);font-family:'JetBrains Mono',monospace;">${eq.asset_code}</td>
                  <td style="padding:12px 14px;">
                    <div style="font-size:13px;font-weight:600;color:var(--text);">${eq.name}</div>
                    ${eq.manufacturer ? `<div style="font-size:11px;color:var(--text-3);">${eq.manufacturer}</div>` : ''}
                  </td>
                  <td style="padding:12px 14px;text-align:center;font-size:13px;color:var(--text);">${eq.quantity}</td>
                  <td style="padding:12px 14px;">${conditionBadge(eq.service_status)}</td>
                  <td style="padding:12px 14px;font-size:12px;color:var(--text-2);">${eq.last_serviced || '—'}</td>
                  <td style="padding:12px 14px;font-size:12px;color:var(--text-2);">${eq.next_service_due || '—'}</td>
                  <td style="padding:12px 14px;font-size:12px;color:var(--text-2);">${eq.location || '—'}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`}`;

    } catch {
      container.innerHTML = '<div class="loading-cell">Failed to load equipment.</div>';
    }
  }

  // ── Equipment modal ────────────────────────────────────────
  async function _openEquipmentModal(id) {
    try {
      const [eqRes, logsRes] = await Promise.all([
        Auth.fetch(`/api/v1/inventory/equipment/${id}/`),
        Auth.fetch(`/api/v1/inventory/equipment/${id}/maintenance/`),
      ]);
      if (!eqRes.ok) return;
      const eq   = await eqRes.json();
      const logs = logsRes.ok ? await logsRes.json() : [];

      const conditionBadge = c => {
        const map = {
          GOOD          : ['#dcfce7','#166534','Good'],
          FAIR          : ['#fef9c3','#854d0e','Fair'],
          NEEDS_SERVICE : ['#ffedd5','#9a3412','Needs Service'],
          OUT_OF_SERVICE: ['#fee2e2','#991b1b','Out of Service'],
        };
        const [bg, color, label] = map[c] || ['#f3f4f6','#374151', c];
        return `<span style="padding:3px 12px;border-radius:20px;font-size:12px;
          font-weight:700;background:${bg};color:${color};">${label}</span>`;
      };

      const logTypeLabel = t => ({
        ROUTINE:'Routine', REPAIR:'Repair', REPLACEMENT:'Replacement',
        INSPECTION:'Inspection', OTHER:'Other'
      }[t] || t);

      const overlay = document.createElement('div');
      overlay.id = 'equipment-modal-overlay';
      overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.5);
        z-index:1000;display:flex;align-items:center;justify-content:center;padding:24px;`;
      overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };

      overlay.innerHTML = `
        <div style="background:var(--panel);border-radius:var(--radius);
          width:100%;max-width:720px;max-height:85vh;display:flex;flex-direction:column;
          overflow:hidden;border:1px solid var(--border);">
          <div style="padding:20px 24px;border-bottom:1px solid var(--border);
            display:flex;align-items:flex-start;justify-content:space-between;flex-shrink:0;">
            <div>
              <div style="font-size:11px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;
                font-family:'JetBrains Mono',monospace;">${eq.asset_code}</div>
              <div style="font-size:18px;font-weight:700;color:var(--text);">${eq.name}</div>
              <div style="margin-top:6px;">${conditionBadge(eq.condition)}</div>
            </div>
            <div style="display:flex;gap:8px;align-items:center;">
              <button onclick="Inventory._printEquipmentQR(${eq.id}, '${eq.asset_code}')"
                style="padding:7px 14px;font-size:12px;font-weight:600;
                  border:1px solid var(--border);border-radius:var(--radius-sm);
                  background:var(--bg);color:var(--text);cursor:pointer;font-family:inherit;">
                🏷 Print QR
              </button>
              <button onclick="Inventory._openAddMaintenanceLog(${eq.id})"
                style="padding:7px 14px;font-size:12px;font-weight:600;
                  border:none;border-radius:var(--radius-sm);
                  background:var(--text);color:#fff;cursor:pointer;font-family:inherit;">
                + Log Service
              </button>
              <button onclick="document.getElementById('equipment-modal-overlay').remove()"
                style="padding:7px 12px;font-size:16px;border:none;background:none;
                  cursor:pointer;color:var(--text-3);">×</button>
            </div>
          </div>
          <div style="overflow-y:auto;flex:1;padding:24px;">
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:24px;">
              ${[
                ['Quantity',     eq.quantity],
                ['Manufacturer', eq.manufacturer || '—'],
                ['Model Number', eq.model_number || '—'],
                ['Serial No.',   eq.serial_number || '—'],
                ['Location',     eq.location || '—'],
                ['Purchase Date',eq.purchase_date || '—'],
                ['Purchase Price', eq.purchase_price ? `GHS ${eq.purchase_price}` : '—'],
                ['Warranty Expiry', eq.warranty_expiry || '—'],
                ['Last Serviced', eq.last_serviced || '—'],
                ['Next Service Due', eq.next_service_due || '—'],
              ].map(([label, value]) => `
                <div style="padding:10px 14px;background:var(--bg);
                  border-radius:var(--radius-sm);border:1px solid var(--border);">
                  <div style="font-size:10px;font-weight:700;color:var(--text-3);
                    text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">${label}</div>
                  <div style="font-size:13px;color:var(--text);font-weight:500;">${value}</div>
                </div>`).join('')}
            </div>
            ${eq.notes ? `
            <div style="padding:12px 14px;background:var(--bg);border-radius:var(--radius-sm);
              border:1px solid var(--border);margin-bottom:24px;">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Notes</div>
              <div style="font-size:13px;color:var(--text-2);">${eq.notes}</div>
            </div>` : ''}
            <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:12px;">
              Maintenance History
              <span style="font-size:11px;font-weight:400;color:var(--text-3);margin-left:6px;">
                ${logs.length} record${logs.length !== 1 ? 's' : ''}</span>
            </div>
            ${!logs.length ? `
              <div style="padding:20px;text-align:center;color:var(--text-3);font-size:13px;
                background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border);">
                No maintenance records yet.
              </div>` : logs.map(log => `
              <div style="padding:14px;background:var(--bg);border-radius:var(--radius-sm);
                border:1px solid var(--border);margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;margin-bottom:8px;">
                  <div>
                    <span style="font-size:12px;font-weight:700;color:var(--text);">${logTypeLabel(log.log_type)}</span>
                    <span style="font-size:11px;color:var(--text-3);margin-left:8px;">${log.service_date}</span>
                  </div>
                  ${conditionBadge(log.condition_after)}
                </div>
                <div style="font-size:13px;color:var(--text-2);margin-bottom:6px;">${log.description}</div>
                <div style="display:flex;gap:16px;flex-wrap:wrap;">
                  <span style="font-size:11px;color:var(--text-3);">By: <strong>${log.performed_by}</strong></span>
                  ${log.cost ? `<span style="font-size:11px;color:var(--text-3);">Cost: <strong>GHS ${log.cost}</strong></span>` : ''}
                  ${log.next_due ? `<span style="font-size:11px;color:var(--text-3);">Next due: <strong>${log.next_due}</strong></span>` : ''}
                  <span style="font-size:11px;color:var(--text-3);">Logged by: ${log.logged_by_name}</span>
                </div>
                ${log.parts_replaced ? `<div style="font-size:11px;color:var(--text-3);margin-top:4px;">Parts replaced: ${log.parts_replaced}</div>` : ''}
              </div>`).join('')}
          </div>
        </div>`;

      document.body.appendChild(overlay);

    } catch {
      _toast('Failed to load equipment details.', 'error');
    }
  }

  // ── Add maintenance log ────────────────────────────────────
  async function _openAddMaintenanceLog(equipmentId) {
    document.getElementById('maintenance-log-modal')?.remove();

    const modal = document.createElement('div');
    modal.id = 'maintenance-log-modal';
    modal.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.6);
      z-index:1100;display:flex;align-items:center;justify-content:center;padding:24px;`;
    modal.onclick = e => { if (e.target === modal) modal.remove(); };

    modal.innerHTML = `
      <div style="background:var(--panel);border-radius:var(--radius);width:100%;max-width:520px;
        border:1px solid var(--border);overflow:hidden;">
        <div style="padding:18px 24px;border-bottom:1px solid var(--border);
          display:flex;justify-content:space-between;align-items:center;">
          <div style="font-size:16px;font-weight:700;color:var(--text);">Log Service</div>
          <button onclick="document.getElementById('maintenance-log-modal').remove()"
            style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-3);">×</button>
        </div>
        <div style="padding:24px;display:flex;flex-direction:column;gap:14px;">
          <div class="form-row-2">
            <div class="form-group">
              <label class="form-label">Type</label>
              <select id="ml-type" class="form-input">
                <option value="ROUTINE">Routine Maintenance</option>
                <option value="REPAIR">Repair</option>
                <option value="REPLACEMENT">Part Replacement</option>
                <option value="INSPECTION">Inspection</option>
                <option value="OTHER">Other</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Service Date</label>
              <input type="date" id="ml-date" class="form-input"
                value="${new Date().toISOString().split('T')[0]}">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Description</label>
            <textarea id="ml-description" class="form-input" rows="3"
              placeholder="What was done? Be specific…"></textarea>
          </div>
          <div class="form-row-2">
            <div class="form-group">
              <label class="form-label">Performed By</label>
              <input type="text" id="ml-performed-by" class="form-input"
                placeholder="Technician or company name">
            </div>
            <div class="form-group">
              <label class="form-label">Cost (GHS)</label>
              <input type="number" id="ml-cost" class="form-input"
                placeholder="0.00" step="0.01" min="0">
            </div>
          </div>
          <div class="form-row-2">
            <div class="form-group">
              <label class="form-label">Condition After</label>
              <select id="ml-condition" class="form-input">
                <option value="GOOD">Good</option>
                <option value="FAIR">Fair</option>
                <option value="NEEDS_SERVICE">Needs Service</option>
                <option value="OUT_OF_SERVICE">Out of Service</option>
              </select>
            </div>
            <div class="form-group">
              <label class="form-label">Next Due</label>
              <input type="date" id="ml-next-due" class="form-input">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Parts Replaced <span style="color:var(--text-3);font-weight:400;">(optional)</span></label>
            <input type="text" id="ml-parts" class="form-input"
              placeholder="e.g. Drum unit, fuser kit">
          </div>
          <div id="ml-error" style="display:none;font-size:12px;color:var(--red-text);"></div>
          <button id="ml-save-btn"
            onclick="Inventory._saveMaintenanceLog(${equipmentId})"
            style="padding:10px;background:var(--text);color:#fff;border:none;
              border-radius:var(--radius-sm);font-size:13px;font-weight:700;
              cursor:pointer;font-family:inherit;">
            Save Log
          </button>
        </div>
      </div>`;

    document.body.appendChild(modal);
    document.getElementById('ml-performed-by')?.focus();
  }

  async function _saveMaintenanceLog(equipmentId) {
    const btn         = document.getElementById('ml-save-btn');
    const errEl       = document.getElementById('ml-error');
    const description = document.getElementById('ml-description')?.value.trim();
    const performedBy = document.getElementById('ml-performed-by')?.value.trim();
    const serviceDate = document.getElementById('ml-date')?.value;

    errEl.style.display = 'none';
    if (!description) { errEl.textContent = 'Description is required.'; errEl.style.display = 'block'; return; }
    if (!performedBy) { errEl.textContent = 'Performed by is required.'; errEl.style.display = 'block'; return; }
    if (!serviceDate) { errEl.textContent = 'Service date is required.'; errEl.style.display = 'block'; return; }

    btn.disabled = true; btn.textContent = 'Saving…';

    try {
      const cost    = document.getElementById('ml-cost')?.value;
      const nextDue = document.getElementById('ml-next-due')?.value;

      const res = await Auth.fetch(`/api/v1/inventory/equipment/${equipmentId}/maintenance/`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({
          log_type        : document.getElementById('ml-type')?.value,
          service_date    : serviceDate,
          description,
          performed_by    : performedBy,
          cost            : cost ? parseFloat(cost) : null,
          next_due        : nextDue || null,
          condition_after : document.getElementById('ml-condition')?.value,
          parts_replaced  : document.getElementById('ml-parts')?.value.trim() || '',
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errEl.textContent   = err.detail || 'Failed to save log.';
        errEl.style.display = 'block';
        return;
      }

      document.getElementById('maintenance-log-modal')?.remove();
      document.getElementById('equipment-modal-overlay')?.remove();
      _toast('Maintenance log saved.', 'success');
      await _openEquipmentModal(equipmentId);

    } catch {
      errEl.textContent   = 'Network error. Please try again.';
      errEl.style.display = 'block';
    } finally {
      btn.disabled = false; btn.textContent = 'Save Log';
    }
  }

  // ── Print QR ───────────────────────────────────────────────
  function _printEquipmentQR(id, assetCode) {
    const win = window.open('', '_blank', 'width=300,height=400');
    if (!win) return;
    win.document.write(`<!DOCTYPE html>
<html><head><title>Asset Tag — ${assetCode}</title>
<style>
  body { font-family: monospace; text-align: center; padding: 20px; }
  img  { width: 200px; height: 200px; display: block; margin: 0 auto 12px; }
  h2   { font-size: 18px; margin: 0 0 4px; }
  p    { font-size: 12px; color: #555; margin: 0; }
  @media print { @page { margin: 8mm; } }
</style></head>
<body>
  <img src="/api/v1/inventory/equipment/${id}/qr/" alt="QR Code"
    onload="window.print()" onerror="this.alt='QR unavailable'">
  <h2>${assetCode}</h2>
  <p>Farhat Printing Press</p>
  <p>Westland Branch</p>
</body></html>`);
    win.document.close();
  }

  // ── Add equipment modal ────────────────────────────────────
  function _openAddEquipment() {
    document.getElementById('add-equipment-modal')?.remove();

    const modal = document.createElement('div');
    modal.id = 'add-equipment-modal';
    modal.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.5);
      z-index:1000;display:flex;align-items:center;justify-content:center;padding:24px;`;
    modal.onclick = e => { if (e.target === modal) modal.remove(); };

    modal.innerHTML = `
      <div style="background:var(--panel);border-radius:var(--radius);width:100%;max-width:520px;
        border:1px solid var(--border);overflow:hidden;">
        <div style="padding:18px 24px;border-bottom:1px solid var(--border);
          display:flex;justify-content:space-between;align-items:center;">
          <div style="font-size:16px;font-weight:700;color:var(--text);">Add Equipment</div>
          <button onclick="document.getElementById('add-equipment-modal').remove()"
            style="background:none;border:none;font-size:20px;cursor:pointer;color:var(--text-3);">×</button>
        </div>
        <div style="padding:24px;display:flex;flex-direction:column;gap:14px;
          max-height:70vh;overflow-y:auto;">
          <div class="form-group">
            <label class="form-label">Equipment Name</label>
            <input type="text" id="ae-name" class="form-input"
              placeholder="e.g. Canon iR-ADV 5531i Printer">
          </div>
          <div class="form-row-2">
            <div class="form-group">
              <label class="form-label">Quantity</label>
              <input type="number" id="ae-quantity" class="form-input" value="1" min="1">
            </div>
            <div class="form-group">
              <label class="form-label">Condition</label>
              <select id="ae-condition" class="form-input">
                <option value="GOOD">Good</option>
                <option value="FAIR">Fair</option>
                <option value="NEEDS_SERVICE">Needs Service</option>
                <option value="OUT_OF_SERVICE">Out of Service</option>
              </select>
            </div>
          </div>
          <div class="form-row-2">
            <div class="form-group">
              <label class="form-label">Manufacturer</label>
              <input type="text" id="ae-manufacturer" class="form-input" placeholder="e.g. Canon">
            </div>
            <div class="form-group">
              <label class="form-label">Model Number</label>
              <input type="text" id="ae-model" class="form-input" placeholder="e.g. iR-ADV 5531i">
            </div>
          </div>
          <div class="form-row-2">
            <div class="form-group">
              <label class="form-label">Serial Number</label>
              <input type="text" id="ae-serial" class="form-input" placeholder="Optional">
            </div>
            <div class="form-group">
              <label class="form-label">Location</label>
              <input type="text" id="ae-location" class="form-input" placeholder="e.g. Front Desk">
            </div>
          </div>
          <div class="form-row-2">
            <div class="form-group">
              <label class="form-label">Purchase Date</label>
              <input type="date" id="ae-purchase-date" class="form-input">
            </div>
            <div class="form-group">
              <label class="form-label">Purchase Price (GHS)</label>
              <input type="number" id="ae-purchase-price" class="form-input"
                placeholder="0.00" step="0.01" min="0">
            </div>
          </div>
          <div class="form-row-2">
            <div class="form-group">
              <label class="form-label">Warranty Expiry</label>
              <input type="date" id="ae-warranty" class="form-input">
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">Notes</label>
            <textarea id="ae-notes" class="form-input" rows="2"
              placeholder="Any additional notes…"></textarea>
          </div>
          <div id="ae-error" style="display:none;font-size:12px;color:var(--red-text);"></div>
          <button id="ae-save-btn" onclick="Inventory._saveEquipment()"
            style="padding:10px;background:var(--text);color:#fff;border:none;
              border-radius:var(--radius-sm);font-size:13px;font-weight:700;
              cursor:pointer;font-family:inherit;">
            Add Equipment
          </button>
        </div>
      </div>`;

    document.body.appendChild(modal);
    document.getElementById('ae-name')?.focus();
  }

  async function _saveEquipment() {
    const btn   = document.getElementById('ae-save-btn');
    const errEl = document.getElementById('ae-error');
    const name  = document.getElementById('ae-name')?.value.trim();

    errEl.style.display = 'none';
    if (!name) { errEl.textContent = 'Equipment name is required.'; errEl.style.display = 'block'; return; }

    btn.disabled = true; btn.textContent = 'Saving…';

    try {
      const purchasePrice = document.getElementById('ae-purchase-price')?.value;
      const res = await Auth.fetch('/api/v1/inventory/equipment/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({
          name,
          quantity        : parseInt(document.getElementById('ae-quantity')?.value || 1),
          condition       : document.getElementById('ae-condition')?.value,
          manufacturer    : document.getElementById('ae-manufacturer')?.value.trim() || '',
          model_number    : document.getElementById('ae-model')?.value.trim() || '',
          serial_number   : document.getElementById('ae-serial')?.value.trim() || '',
          location        : document.getElementById('ae-location')?.value.trim() || '',
          purchase_date   : document.getElementById('ae-purchase-date')?.value || null,
          purchase_price  : purchasePrice ? parseFloat(purchasePrice) : null,
          warranty_expiry : document.getElementById('ae-warranty')?.value || null,
          notes           : document.getElementById('ae-notes')?.value.trim() || '',
        }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errEl.textContent   = err.detail || 'Failed to add equipment.';
        errEl.style.display = 'block';
        return;
      }

      document.getElementById('add-equipment-modal')?.remove();
      _toast('Equipment added successfully.', 'success');
      await switchInventoryTab('equipment');

    } catch {
      errEl.textContent   = 'Network error. Please try again.';
      errEl.style.display = 'block';
    } finally {
      btn.disabled = false; btn.textContent = 'Add Equipment';
    }
  }

  // ── Movements tab ──────────────────────────────────────────
  async function _renderStockMovements(container) {
    try {
      const res  = await Auth.fetch('/api/v1/inventory/movements/?page_size=50');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const items = data.results || data;

      if (!items.length) {
        container.innerHTML = '<div class="loading-cell">No movements recorded yet.</div>';
        return;
      }

      const typeColor = {
        OPENING    : 'var(--green-text)',
        IN         : 'var(--green-text)',
        OUT        : 'var(--text-3)',
        WASTE      : 'var(--red-text)',
        CORRECTION : 'var(--amber-text)',
      };
      const typeBg = {
        OPENING    : 'var(--green-bg)',
        IN         : 'var(--green-bg)',
        OUT        : 'var(--bg)',
        WASTE      : 'var(--red-bg)',
        CORRECTION : 'var(--amber-bg)',
      };

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);">
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Date</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Item</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Type</th>
                <th style="text-align:right;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Qty</th>
                <th style="text-align:right;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Balance</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Notes</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(m => {
                const date = new Date(m.created_at).toLocaleDateString('en-GB',
                  { day: 'numeric', month: 'short', year: 'numeric' });
                const isOut = ['OUT','WASTE'].includes(m.movement_type);
                return `
                  <tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:10px 16px;font-size:12px;color:var(--text-3);">${date}</td>
                    <td style="padding:10px 16px;font-size:13px;color:var(--text);font-weight:500;">${_esc(m.consumable_name || '—')}</td>
                    <td style="padding:10px 16px;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;
                        background:${typeBg[m.movement_type]||'var(--bg)'};
                        color:${typeColor[m.movement_type]||'var(--text-3)'};">
                        ${m.movement_type}
                      </span>
                    </td>
                    <td style="padding:10px 16px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;
                      color:${isOut ? 'var(--red-text)' : 'var(--green-text)'};">
                      ${isOut ? '-' : '+'}${parseFloat(m.quantity).toFixed(2)}
                    </td>
                    <td style="padding:10px 16px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-3);">
                      ${parseFloat(m.balance_after).toFixed(2)}
                    </td>
                    <td style="padding:10px 16px;font-size:12px;color:var(--text-3);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                      ${_esc(m.notes || '—')}
                    </td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load movements.</div>';
    }
  }

  // ── Waste incidents tab ────────────────────────────────────
  async function _renderWasteIncidents(container) {
    try {
      const res  = await Auth.fetch('/api/v1/inventory/waste/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const items = data.results || data;

      if (!items.length) {
        container.innerHTML = '<div class="loading-cell">No waste incidents recorded.</div>';
        return;
      }

      const reasonColor = {
        JAM      : 'var(--amber-text)',
        MISPRINT : 'var(--red-text)',
        DAMAGE   : 'var(--red-text)',
        OTHER    : 'var(--text-3)',
      };
      const reasonBg = {
        JAM      : 'var(--amber-bg)',
        MISPRINT : 'var(--red-bg)',
        DAMAGE   : 'var(--red-bg)',
        OTHER    : 'var(--bg)',
      };

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);">
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Date</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Item</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Reason</th>
                <th style="text-align:right;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Qty</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Reported By</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);border-bottom:2px solid var(--border);">Job</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(w => {
                const date = new Date(w.created_at).toLocaleDateString('en-GB',
                  { day: 'numeric', month: 'short', year: 'numeric' });
                return `
                  <tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:10px 16px;font-size:12px;color:var(--text-3);">${date}</td>
                    <td style="padding:10px 16px;font-size:13px;color:var(--text);font-weight:500;">${_esc(w.consumable_name || '—')}</td>
                    <td style="padding:10px 16px;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;
                        background:${reasonBg[w.reason]||'var(--bg)'};
                        color:${reasonColor[w.reason]||'var(--text-3)'};">
                        ${w.reason}
                      </span>
                    </td>
                    <td style="padding:10px 16px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;color:var(--red-text);">
                      -${parseFloat(w.quantity).toFixed(2)}
                    </td>
                    <td style="padding:10px 16px;font-size:12px;color:var(--text-2);">${_esc(w.reported_by_name || '—')}</td>
                    <td style="padding:10px 16px;font-size:12px;color:var(--text-3);font-family:'JetBrains Mono',monospace;">${_esc(w.job_number || '—')}</td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load waste incidents.</div>';
    }
  }

  // ── Receive Stock modal ────────────────────────────────────
  async function openReceiveStock() {
    document.getElementById('recv-consumable').value                       = '';
    document.getElementById('recv-consumable-search').value                = '';
    document.getElementById('recv-consumable-dropdown').style.display      = 'none';
    document.getElementById('recv-quantity').value                         = '';
    document.getElementById('recv-notes').value                            = '';
    document.getElementById('recv-error').style.display                    = 'none';
    document.getElementById('recv-submit-btn').disabled                    = false;
    document.getElementById('recv-submit-btn').textContent                 = 'Confirm Receipt';
    document.getElementById('recv-overlay').classList.add('open');

    const sel = document.getElementById('recv-consumable');
    sel.innerHTML = '<option value="">Loading…</option>';
    try {
      const res   = await Auth.fetch('/api/v1/inventory/stock/');
      const data  = res.ok ? await res.json() : [];
      const items = Array.isArray(data) ? data : (data.results || []);
      sel.innerHTML = '<option value="">Select consumable…</option>';
      items.forEach(c => {
        const opt       = document.createElement('option');
        opt.value       = c.consumable;
        opt.textContent = `${c.name} (${c.quantity} ${c.unit_label} in stock)`;
        sel.appendChild(opt);
      });
    } catch {
      sel.innerHTML = '<option value="">Could not load consumables</option>';
    }
  }

  function _recvShowDropdown() {
    /* typeahead disabled — select fallback works fine */
  }

  function _recvFilterConsumables() {
    /* typeahead disabled — select fallback works fine */
  }

  function _recvSelectConsumable(id, name, stock) {
    document.getElementById('recv-consumable').value        = id;
    document.getElementById('recv-consumable-search').value = name;
    document.getElementById('recv-consumable-dropdown').style.display = 'none';
  }

  function closeReceiveStock() {
    document.getElementById('recv-overlay').classList.remove('open');
  }

  async function submitReceiveStock() {
    const btn          = document.getElementById('recv-submit-btn');
    const err          = document.getElementById('recv-error');
    const consumableId = document.getElementById('recv-consumable').value;
    const quantity     = document.getElementById('recv-quantity').value.trim();
    const notes        = document.getElementById('recv-notes').value.trim();

    err.style.display = 'none';

    if (!consumableId) { err.textContent = 'Please select a consumable.'; err.style.display = 'block'; return; }
    if (!quantity || isNaN(parseFloat(quantity)) || parseFloat(quantity) <= 0) {
      err.textContent = 'Please enter a valid quantity.'; err.style.display = 'block'; return;
    }

    btn.disabled    = true;
    btn.textContent = 'Saving…';

    try {
      const res = await Auth.fetch('/api/v1/inventory/stock/receive/', {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify({
          consumable_id : parseInt(consumableId),
          quantity      : parseFloat(quantity),
          notes,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        const msg = Object.values(data).flat().join(' ');
        err.textContent   = msg || 'Failed to receive stock.';
        err.style.display = 'block';
        return;
      }

      closeReceiveStock();
      _toast('Stock received successfully.', 'success');
      await switchInventoryTab(document.querySelector('#pane-inventory .reports-tab.active')?.dataset.tab || 'consumables');

    } catch {
      err.textContent   = 'Network error. Please try again.';
      err.style.display = 'block';
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Confirm Receipt';
    }
  }

  // ── Shared rendering helpers (used by reports/finance too) ─
  function renderInventorySnapshot(snapshot) {
    if (!snapshot || !snapshot.items || !snapshot.items.length) {
      return `<div style="padding:24px;text-align:center;color:var(--text-3);font-size:13px;">No inventory data for this period.</div>`;
    }

    const items = snapshot.items.filter(i => i.category !== 'Machinery');
    const lowStockFiltered = (snapshot.low_stock || []).filter(name => {
      const item = items.find(i => i.consumable === name);
      return item && item.category !== 'Machinery';
    });

    const alertHtml = lowStockFiltered.length ? `
      <div style="padding:10px 14px;background:#fee2e2;border:1px solid #fca5a5;border-radius:8px;margin-bottom:16px;display:flex;align-items:center;gap:8px;">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#991b1b" stroke-width="2">
          <circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span style="font-size:11px;font-weight:700;color:#991b1b;">Low stock: ${lowStockFiltered.join(', ')}</span>
      </div>` : '';

    return alertHtml + renderInventoryCards(items, 'snapshot');
  }

  function renderInventoryCards(items, mode = 'snapshot') {
    if (!items || !items.length) {
      return `<div style="padding:24px;text-align:center;color:var(--text-3);font-size:13px;">No inventory data available.</div>`;
    }

    const filtered = items.filter(i => i.category !== 'Machinery');

    const categoryConfig = {
      'Paper'      : { bg: '#fdf8f0', strip: '#e8a820', header: '#8a6a2e', icon: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>` },
      'Toner'      : { bg: '#f0f4fd', strip: '#3355cc', header: '#2e4a8a', icon: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 7V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v2"/></svg>` },
      'Binding'    : { bg: '#f5f0fd', strip: '#9b59b6', header: '#5a2e8a', icon: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg>` },
      'Lamination' : { bg: '#f0fdf4', strip: '#22c98a', header: '#1a6b3a', icon: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18"/><path d="M3 15h18"/></svg>` },
      'Envelopes'  : { bg: '#fffbeb', strip: '#f59e0b', header: '#8a6a00', icon: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/></svg>` },
      'Photography': { bg: '#fdf0f5', strip: '#e8294a', header: '#8a1a4a', icon: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>` },
    };
    const defaultConfig = { bg: '#f8f8f8', strip: '#888', header: '#444', icon: `<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/></svg>` };

    const groups = {};
    filtered.forEach(item => {
      const cat = item.category || 'Other';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(item);
    });

    return Object.entries(groups).map(([cat, catItems]) => {
      const cfg      = categoryConfig[cat] || defaultConfig;
      const isToner  = cat === 'Toner';
      const lowCount = catItems.filter(i => i.is_low).length;

      const rows = catItems.map((item, idx) => {
        const name         = mode === 'snapshot' ? item.consumable : item.name;
        const unit         = item.unit || item.unit_label || '';
        const isPercent    = unit === '%';
        const isLow        = item.is_low;
        const isCritical   = isLow && (mode === 'snapshot'
          ? parseFloat(item.closing  || 0) === 0
          : parseFloat(item.quantity || 0) === 0);

        const closing      = mode === 'snapshot'
          ? parseFloat(item.closing  || 0)
          : parseFloat(item.quantity || 0);
        const received     = mode === 'snapshot' ? parseFloat(item.received || 0) : 0;
        const consumed     = mode === 'snapshot' ? parseFloat(item.consumed || 0) : 0;
        const reorderPoint = parseFloat(item.reorder_point || 0);
        const lastReceived = item.last_received || null;

        const fmtQty = n => isPercent
          ? `${parseFloat(n).toFixed(1)}%`
          : parseFloat(n).toLocaleString('en-GH', { minimumFractionDigits: 0 });

        const statusColor = isCritical ? '#dc2626' : isLow ? '#d97706' : '#16a34a';
        const statusBg    = isCritical ? '#fee2e2' : isLow ? '#fef3c7' : '#dcfce7';
        const statusLabel = isCritical ? 'Critical' : isLow ? 'Low' : 'OK';

        const barPct = reorderPoint > 0
          ? Math.min(100, (closing / 100) * 100)
          : Math.min(100, (closing / (reorderPoint * 3 || 1)) * 100);
        const barColor = isCritical ? '#dc2626' : isLow ? '#d97706' : '#3355cc';

        const lastReceivedHtml = received > 0
          ? `<div style="font-size:10px;color:#16a34a;margin-top:2px;font-weight:600;">+${fmtQty(received)} ${unit} received</div>`
          : lastReceived
            ? `<div style="font-size:10px;color:#9ca3af;margin-top:2px;">Last: ${new Date(lastReceived).toLocaleDateString('en-GB',{day:'numeric',month:'short'})}</div>`
            : '';

        return `
          <tr style="border-bottom:1px solid #f3f4f6;background:${idx % 2 === 0 ? '#fff' : '#fafafa'};">
            <td style="padding:9px 14px;">
              <div style="font-size:12px;font-weight:600;color:#111;">${name}</div>
              ${lastReceivedHtml}
            </td>
            <td style="padding:9px 14px;font-size:11px;color:#9ca3af;text-align:center;">${unit}</td>
            <td style="padding:9px 14px;text-align:right;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:${statusColor};">${fmtQty(closing)}</div>
              ${isToner ? `<div style="margin-top:4px;height:3px;background:#e5e7eb;border-radius:2px;overflow:hidden;width:80px;margin-left:auto;"><div style="height:100%;width:${barPct.toFixed(1)}%;background:${barColor};border-radius:2px;"></div></div>` : ''}
            </td>
            <td style="padding:9px 14px;text-align:right;font-size:12px;color:#6b7280;font-family:'JetBrains Mono',monospace;">${reorderPoint > 0 ? fmtQty(reorderPoint) : '—'}</td>
            ${mode === 'snapshot' ? `<td style="padding:9px 14px;text-align:right;font-size:12px;font-family:'JetBrains Mono',monospace;color:${consumed > 0 ? '#dc2626' : '#9ca3af'};">${consumed > 0 ? '-' + fmtQty(consumed) : '—'}</td>` : ''}            <td style="padding:9px 14px;text-align:center;">
              <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;background:${statusBg};color:${statusColor};">${statusLabel}</span>
            </td>
          </tr>`;
      }).join('');

      return `
        <div style="margin-bottom:16px;border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;">
          <div style="display:flex;align-items:center;gap:8px;padding:8px 14px;background:${cfg.bg};border-bottom:2px solid ${cfg.strip};">
            <span style="color:${cfg.header};">${cfg.icon}</span>
            <span style="font-size:11px;font-weight:800;color:${cfg.header};text-transform:uppercase;letter-spacing:0.6px;">${cat}</span>
            <span style="font-size:10px;color:${cfg.header};opacity:0.5;margin-left:2px;">· ${catItems.length} item${catItems.length !== 1 ? 's' : ''}</span>
            ${lowCount > 0
              ? `<span style="margin-left:auto;padding:1px 8px;border-radius:20px;font-size:9px;font-weight:700;background:#fee2e2;color:#dc2626;">${lowCount} need${lowCount === 1 ? 's' : ''} attention</span>`
              : `<span style="margin-left:auto;padding:1px 8px;border-radius:20px;font-size:9px;font-weight:700;background:#dcfce7;color:#16a34a;">All good</span>`}
          </div>
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:#f9fafb;border-bottom:1px solid #e5e7eb;">
                <th style="padding:7px 14px;text-align:left;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">Item</th>
                <th style="padding:7px 14px;text-align:center;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">Unit</th>
                <th style="padding:7px 14px;text-align:right;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">In Stock</th>
                <th style="padding:7px 14px;text-align:right;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">Reorder At</th>
                ${mode === 'snapshot' ? `<th style="padding:7px 14px;text-align:right;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">Consumed</th>` : ''}                <th style="padding:7px 14px;text-align:center;font-size:10px;font-weight:700;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;">Status</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>
        </div>`;
    }).join('');
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    loadInventoryPane,
    switchInventoryTab,
    openReceiveStock,
    closeReceiveStock,
    submitReceiveStock,
    _recvSelectConsumable,
    _recvFilterConsumables,
    _recvShowDropdown,
    _openEquipmentModal,
    _openAddEquipment,
    _saveEquipment,
    _openAddMaintenanceLog,
    _saveMaintenanceLog,
    _printEquipmentQR,
    renderInventorySnapshot,
    renderInventoryCards,
  };

})();