'use strict';

// ── Delivery Acceptance Module ────────────────────────────────────────────────
// Polls for incoming deliveries and shows the full-screen acceptance modal.

const DeliveryAcceptance = (() => {

  let _order      = null;
  let _pollTimer  = null;
  const POLL_MS   = 5000;

  // ── Start polling ──────────────────────────────────────────────────────────
  function startPolling() {
    _poll();
    _pollTimer = setInterval(_poll, POLL_MS);
  }

  async function _poll() {
    try {
      const res = await Auth.fetch('/api/v1/procurement/pending-delivery/');
      if (!res || !res.ok) return;
      const data = await res.json();
      if (data && data.id) {
        _showModal(data);
      } else {
        _hideModal();
      }
    } catch { /* silent */ }
  }

  // ── Modal display ──────────────────────────────────────────────────────────
  function _showModal(order) {
    // Don't re-render if already showing the same order
    if (_order && _order.id === order.id) return;
    _order = order;

    // Populate header
    const refEl = document.getElementById('da-order-ref');
    if (refEl) refEl.textContent = `${order.order_number} · Week ${order.week_number}, ${order.year}`;

    // Populate line items
    const tbody = document.getElementById('da-items-tbody');
    if (tbody) {
      tbody.innerHTML = (order.line_items || []).map(li => {
        const deliveredQty = li.delivered_qty != null
          ? `${parseFloat(li.delivered_qty).toFixed(0)} ${li.unit_label}`
          : (li.pack_description || `${parseFloat(li.requested_qty).toFixed(0)} ${li.unit_label}`);

        const defaultAccept = li.delivered_qty != null
          ? parseFloat(li.delivered_qty)
          : parseFloat(li.requested_qty);

        return `
          <tr>
            <td style="padding:12px 20px;border-bottom:1px solid var(--border);
              font-size:13px;font-weight:600;color:var(--text);">${_esc(li.consumable_name)}</td>
            <td style="padding:12px 16px;border-bottom:1px solid var(--border);
              text-align:right;font-size:13px;color:var(--text-2);
              font-family:'JetBrains Mono',monospace;">${_esc(deliveredQty)}</td>
            <td style="padding:12px 20px;border-bottom:1px solid var(--border);text-align:right;">
              <input type="number" id="da-accept-${li.id}"
                value="${defaultAccept.toFixed(2)}"
                min="0" step="0.01"
                style="width:90px;padding:6px 10px;border:1.5px solid var(--border);
                  border-radius:var(--radius-sm);font-size:13px;text-align:right;
                  font-family:'JetBrains Mono',monospace;font-weight:600;
                  background:var(--panel);color:var(--text);outline:none;"
                oninput="DeliveryAcceptance._flagDiscrepancy(this, ${defaultAccept})">
            </td>
          </tr>`;
      }).join('');
    }

    // Clear notes
    const notesEl = document.getElementById('da-bm-notes');
    if (notesEl) notesEl.value = '';

    // Show overlay
    const overlay = document.getElementById('delivery-acceptance-overlay');
    if (overlay) overlay.style.display = 'flex';
  }

  function _hideModal() {
    if (!_order) return;
    _order = null;
    const overlay = document.getElementById('delivery-acceptance-overlay');
    if (overlay) overlay.style.display = 'none';
  }

  // ── Accept ─────────────────────────────────────────────────────────────────
  async function confirmAccept() {
    if (!_order) return;

    const btn = document.getElementById('da-accept-btn');
    btn.disabled = true;
    btn.textContent = 'Accepting…';

    const accepted_quantities = {};
    for (const li of (_order.line_items || [])) {
      const input = document.getElementById(`da-accept-${li.id}`);
      const qty   = parseFloat(input?.value || '0');
      if (isNaN(qty) || qty < 0) {
        _toast('All quantities must be valid non-negative numbers.');
        btn.disabled = false;
        btn.textContent = '✓ Accept Delivery';
        return;
      }
      accepted_quantities[li.id] = qty;
    }

    const bm_notes = document.getElementById('da-bm-notes')?.value || '';

    try {
      const res = await Auth.fetch(
        `/api/v1/procurement/orders/${_order.id}/accept/`, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ accepted_quantities, bm_notes }),
        }
      );
      const data = await res.json();

      if (!res.ok) {
        _toast(data.detail || 'Acceptance failed.');
        btn.disabled = false;
        btn.textContent = '✓ Accept Delivery';
        return;
      }

      // Hide delivery modal, show success animation
      const overlay = document.getElementById('delivery-acceptance-overlay');
      if (overlay) overlay.style.display = 'none';

      const successOverlay = document.getElementById('delivery-success-overlay');
      const successMsg     = document.getElementById('da-success-msg');
      if (successMsg) successMsg.textContent =
        `${_order.line_items?.length || 0} items added to your branch inventory.`;
      if (successOverlay) successOverlay.style.display = 'flex';

      // Auto-dismiss after 3 seconds
      setTimeout(() => {
        if (successOverlay) successOverlay.style.display = 'none';
        _order = null;
        // Refresh dashboard inventory if visible
        if (typeof Dashboard !== 'undefined' && Dashboard._loadInventory) {
          Dashboard._loadInventory();
        }
      }, 3000);

    } catch (err) {
      console.error('confirmAccept failed:', err);
      _toast('Unexpected error. Please try again.');
      btn.disabled = false;
      btn.textContent = '✓ Accept Delivery';
    }
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function _flagDiscrepancy(input, expected) {
    const val = parseFloat(input.value);
    const hasDiscrepancy = !isNaN(val) && val !== expected;
    input.style.borderColor = hasDiscrepancy ? 'var(--red-text)' : 'var(--border)';
    input.style.background  = hasDiscrepancy ? 'var(--red-bg)'   : 'var(--panel)';
  }

  function _esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _toast(msg) {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className   = 'toast error';
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  return {
    startPolling,
    confirmAccept,
    _flagDiscrepancy,
  };

})();

// Boot — start polling after dashboard initialises
document.addEventListener('DOMContentLoaded', () => {
  // Small delay to let dashboard auth complete first
  setTimeout(() => DeliveryAcceptance.startPolling(), 2000);
});