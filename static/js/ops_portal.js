'use strict';

// ── Ops Portal ────────────────────────────────────────────────────────────────
const Ops = (() => {

  let _user          = null;
  let _allOrders     = [];
  let _branches      = [];
  let _activeOrderId = null;
  let _activePane    = 'branches';
  let _expandedBranch = null;
  let _pollTimer     = null;

  // ── Init ───────────────────────────────────────────────────────────────────
  async function init() {
    try {
      const res  = await Auth.fetch('/api/v1/accounts/me/');
      const data = await res.json();
      _user = data;
      _hydrateTopbar(data);
      await Promise.all([loadBranches(), _loadOrders()]);
      OpsNotif.startPolling();
    } catch (err) {
      console.error('Ops.init failed:', err);
      _toast('Failed to initialise portal.', 'error');
    }
  }

  function _hydrateTopbar(user) {
    const name     = user.full_name || `${user.first_name} ${user.last_name}`;
    const initials = `${(user.first_name||'?')[0]}${(user.last_name||'?')[0]}`.toUpperCase();
    const role     = user.role_detail?.name || user.role_name || 'Operations';
    _set('ops-user-name',     name);
    _set('ops-user-initials', initials);
    _set('ops-profile-name',  name);
    _set('ops-user-sub',      role);
    _set('strip-officer',     name);
    _set('strip-date', new Date().toLocaleDateString('en-GB', {
      weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
    }));
  }

  // ── Branches ───────────────────────────────────────────────────────────────
  async function loadBranches() {
    try {
      const res = await Auth.fetch('/api/v1/procurement/branches/');
      _branches = await res.json();
      _renderBranches();
    } catch (err) {
      console.error('loadBranches failed:', err);
      document.getElementById('branches-list').innerHTML =
        '<div style="padding:24px;color:var(--red-text);font-size:13px;">Could not load branches.</div>';
    }
  }

  function _renderBranches() {
    const el  = document.getElementById('branches-list');
    if (!el) return;

    const needingStock = _branches.filter(b => b.low_stock_count > 0).length;
    _set('strip-low', needingStock);
    _setBadge('sidebar-low-count', needingStock);

    if (!_branches.length) {
      el.innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">🏢</div>
        <div class="empty-state-title">No branches found</div>
        <div class="empty-state-sub">No active branches are registered.</div>
      </div>`;
      return;
    }

    el.innerHTML = _branches.map(b => _branchCard(b)).join('');
  }

  function _branchCard(b) {
    const hasActive    = !!b.active_order_id;
    const canPrepare   = b.can_prepare;
    const lowCount     = b.low_stock_count;
    const healthColor  = lowCount === 0 ? 'var(--green-text)' : lowCount <= 3 ? 'var(--amber-text)' : 'var(--red-text)';
    const healthBg     = lowCount === 0 ? 'var(--green-bg)'   : lowCount <= 3 ? 'var(--amber-bg)'   : 'var(--red-bg)';
    const healthBorder = lowCount === 0 ? 'var(--green-border)' : lowCount <= 3 ? 'var(--amber-border)' : 'var(--red-border)';
    const healthLabel  = lowCount === 0 ? 'Fully stocked' : `${lowCount} item${lowCount !== 1 ? 's' : ''} low`;

    const weekLabel = b.latest_week
      ? `Week ${b.latest_week}, ${b.latest_year}`
      : 'No locked report';

    let actionBtn = '';
    if (hasActive) {
      const statusLabel = _statusLabel(b.active_order_status);
      actionBtn = `
        <button onclick="Ops.openManifestForBranch(${b.branch_id})"
          style="padding:7px 14px;background:var(--amber-bg);color:var(--amber-text);
            border:1px solid var(--amber-border);border-radius:var(--radius-sm);
            font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;
            white-space:nowrap;">
          View Order · ${statusLabel}
        </button>`;
    } else if (canPrepare) {
      actionBtn = `
        <button onclick="Ops.prepareDeliverables(${b.branch_id}, this)"
          style="padding:7px 14px;background:var(--text);color:#fff;
            border:none;border-radius:var(--radius-sm);
            font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;
            white-space:nowrap;">
          Prepare Deliverables
        </button>`;
    } else {
      actionBtn = `
        <span style="font-size:12px;color:var(--text-3);font-style:italic;">
          No locked report available
        </span>`;
    }

    // Low stock items list (collapsed by default)
    const lowItems = b.low_stock_items || [];
    const itemsHtml = lowItems.length ? `
      <div style="padding:12px 20px 16px;border-top:1px solid var(--border);
        display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:6px;">
        ${lowItems.map(item => `
          <div style="display:flex;align-items:center;gap:6px;font-size:12px;color:var(--text-2);">
            <span style="width:6px;height:6px;border-radius:50%;background:var(--red-text);flex-shrink:0;"></span>
            ${_esc(item)}
          </div>`).join('')}
      </div>` : '';

    return `
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
        margin-bottom:8px;overflow:hidden;">
        <!-- Branch header row -->
        <div style="display:flex;align-items:center;gap:16px;padding:14px 20px;cursor:pointer;"
          onclick="Ops._toggleBranchExpand(${b.branch_id}, this)">
          <div style="flex:1;min-width:0;">
            <div style="display:flex;align-items:center;gap:10px;">
              <span style="font-size:14px;font-weight:700;color:var(--text);">${_esc(b.branch_name)}</span>
              <span style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-3);">${_esc(b.branch_code)}</span>
              ${b.region_name ? `<span style="font-size:11px;color:var(--text-3);">${_esc(b.region_name)}</span>` : ''}
            </div>
            <div style="font-size:12px;color:var(--text-3);margin-top:3px;">Latest locked: ${weekLabel}</div>
          </div>
          <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;
            background:${healthBg};color:${healthColor};border:1px solid ${healthBorder};
            white-space:nowrap;">
            ${healthLabel}
          </span>
          ${actionBtn}
          <svg class="branch-chevron" xmlns="http://www.w3.org/2000/svg" width="14" height="14"
            viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
            style="color:var(--text-3);flex-shrink:0;transition:transform 0.2s;">
            <polyline points="6 9 12 15 18 9"/>
          </svg>
        </div>
        <!-- Expandable low stock items -->
        <div class="branch-expand" id="branch-expand-${b.branch_id}" style="display:none;">
          ${itemsHtml || `<div style="padding:12px 20px 16px;font-size:13px;color:var(--green-text);">
            ✓ All stock levels are healthy for this branch.
          </div>`}
        </div>
      </div>`;
  }

  function _toggleBranchExpand(branchId, rowEl) {
    const expandEl = document.getElementById(`branch-expand-${branchId}`);
    const chevron  = rowEl.querySelector('.branch-chevron');
    if (!expandEl) return;
    const isOpen = expandEl.style.display !== 'none';
    expandEl.style.display = isOpen ? 'none' : 'block';
    if (chevron) chevron.style.transform = isOpen ? '' : 'rotate(180deg)';
  }

  async function prepareDeliverables(branchId, btn) {
    if (btn) { btn.disabled = true; btn.textContent = 'Preparing…'; }
    try {
      const res  = await Auth.fetch(`/api/v1/procurement/branches/${branchId}/prepare/`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) {
        _toast(data.detail || 'Failed to prepare deliverables.', 'error');
        return;
      }
      _toast(`Order ${data.order_number} generated. Review it in New Orders.`, 'success');
      await Promise.all([loadBranches(), _loadOrders()]);
      switchPane('new-orders');
    } catch (err) {
      console.error('prepareDeliverables failed:', err);
      _toast('Unexpected error.', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Prepare Deliverables'; }
    }
  }

  async function openManifestForBranch(branchId) {
    try {
      const res   = await Auth.fetch(`/api/v1/procurement/branches/${branchId}/active-order/`);
      const order = await res.json();
      if (!order) { _toast('No active order found for this branch.', 'error'); return; }
      _openManifest(order);
    } catch (err) {
      console.error('openManifestForBranch failed:', err);
      _toast('Could not load order.', 'error');
    }
  }

  // ── Orders ─────────────────────────────────────────────────────────────────
  async function _loadOrders() {
    try {
      const res  = await Auth.fetch('/api/v1/procurement/orders/');
      _allOrders = await res.json();
      _renderOrders();
    } catch (err) {
      console.error('_loadOrders failed:', err);
    }
  }

  function _renderOrders() {
    const newOrders = _allOrders.filter(o =>
      ['DRAFT', 'CONFIRMED'].includes(o.status)
    );
    const transit   = _allOrders.filter(o => o.status === 'IN_TRANSIT');
    const delivered = _allOrders.filter(o => o.status === 'DELIVERED');
    const history   = _allOrders.filter(o => ['CLOSED', 'CANCELLED'].includes(o.status));

    // Combine transit + delivered for in-transit pane
    const inTransitAll = [...delivered, ...transit];

    _set('strip-transit', inTransitAll.length);
    _setBadge('sidebar-new-count',     newOrders.length);
    _setBadge('sidebar-transit-count', inTransitAll.length);
    _set('new-orders-pill', `${newOrders.length} order${newOrders.length !== 1 ? 's' : ''}`);
    _set('transit-pill',    `${inTransitAll.length} order${inTransitAll.length !== 1 ? 's' : ''}`);

    _renderOrderList('new-orders-list', newOrders, _newOrderCard);
    _renderOrderList('transit-list',    inTransitAll, _transitCard);
    _renderOrderList('history-list',    history,    _historyCard);
  }

  function _renderOrderList(containerId, orders, cardFn) {
    const el = document.getElementById(containerId);
    if (!el) return;
    if (!orders.length) {
      el.innerHTML = `<div class="empty-state">
        <div class="empty-state-icon">📋</div>
        <div class="empty-state-title">Nothing here</div>
        <div class="empty-state-sub">Orders will appear when ready.</div>
      </div>`;
      return;
    }
    el.innerHTML = orders.map(o => cardFn(o)).join('');
  }

  function _newOrderCard(o) {
    const isDraft     = o.status === 'DRAFT';
    const isConfirmed = o.status === 'CONFIRMED';
    return `
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
        padding:16px 20px;margin-bottom:10px;display:flex;align-items:center;gap:16px;">
        <div style="flex:1;min-width:0;">
          <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;
            color:var(--text);margin-bottom:3px;">${_esc(o.order_number)}</div>
          <div style="display:flex;gap:10px;margin-top:4px;flex-wrap:wrap;">
            <span class="status-badge ${o.status.toLowerCase().replace('_','-')}">${_statusLabel(o.status)}</span>
          </div>
          <div style="font-size:12px;color:var(--text-3);margin-top:4px;display:flex;gap:12px;">
            <span>🏢 ${_esc(o.branch_name)}</span>
            <span>📅 Week ${o.week_number}, ${o.year}</span>
            <span>📦 ${o.line_item_count || '—'} items</span>
          </div>
        </div>
        <div style="display:flex;gap:8px;align-items:center;flex-shrink:0;">
          <button onclick="Ops.openManifest(${o.id})"
            style="padding:7px 14px;background:var(--bg);color:var(--text-2);
              border:1px solid var(--border);border-radius:var(--radius-sm);
              font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;">
            View Manifest
          </button>
          ${isDraft ? `
            <button onclick="Ops.confirmOrder(${o.id}, this)"
              style="padding:7px 14px;background:var(--blue-bg);color:var(--blue-text);
                border:1px solid var(--blue-border);border-radius:var(--radius-sm);
                font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;">
              Confirm Order
            </button>` : ''}
          ${isConfirmed ? `
            <button onclick="Ops.openDispatchModal(${o.id})"
              style="padding:7px 14px;background:var(--text);color:#fff;
                border:none;border-radius:var(--radius-sm);
                font-size:12px;font-weight:600;cursor:pointer;font-family:inherit;">
              Dispatch →
            </button>` : ''}
        </div>
      </div>`;
  }

  function _transitCard(o) {
    const isDelivered = o.status === 'DELIVERED';
    return `
      <div style="background:var(--panel);border:1px solid ${isDelivered ? 'var(--amber-border)' : 'var(--border)'};
        border-radius:var(--radius);padding:16px 20px;margin-bottom:10px;
        display:flex;align-items:center;gap:16px;">
        <div style="flex:1;min-width:0;">
          <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;
            color:var(--text);margin-bottom:3px;">${_esc(o.order_number)}</div>
          <div style="display:flex;gap:10px;margin-top:4px;">
            <span class="status-badge ${o.status.toLowerCase().replace('_','-')}">${_statusLabel(o.status)}</span>
          </div>
          <div style="font-size:12px;color:var(--text-3);margin-top:4px;display:flex;gap:12px;">
            <span>🏢 ${_esc(o.branch_name)}</span>
            <span>📦 ${o.line_item_count || '—'} items</span>
            ${o.dispatched_at ? `<span>🚚 Dispatched ${_fmtDate(o.dispatched_at)}</span>` : ''}
          </div>
        </div>
        <div style="display:flex;gap:8px;flex-shrink:0;">
          ${o.status === 'IN_TRANSIT' ? `
            <button onclick="Ops.openDeliveryModal(${o.id})"
              style="padding:7px 14px;background:var(--text);color:#fff;border:none;
                border-radius:var(--radius-sm);font-size:12px;font-weight:600;
                cursor:pointer;font-family:inherit;">
              Record Delivery
            </button>` : ''}
          ${isDelivered ? `
            <span style="font-size:12px;color:var(--amber-text);font-weight:600;
              padding:7px 14px;background:var(--amber-bg);border:1px solid var(--amber-border);
              border-radius:var(--radius-sm);">
              ⏳ Awaiting BM acceptance
            </span>` : ''}
        </div>
      </div>`;
  }

  function _historyCard(o) {
    return `
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
        padding:14px 20px;margin-bottom:8px;display:flex;align-items:center;gap:16px;">
        <div style="flex:1;">
          <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;
            color:var(--text);">${_esc(o.order_number)}</div>
          <div style="font-size:12px;color:var(--text-3);margin-top:4px;display:flex;gap:12px;">
            <span>🏢 ${_esc(o.branch_name)}</span>
            <span>📅 Week ${o.week_number}, ${o.year}</span>
          </div>
        </div>
        <span class="status-badge ${o.status.toLowerCase()}">${_statusLabel(o.status)}</span>
      </div>`;
  }

  // ── Confirm order ──────────────────────────────────────────────────────────
  async function confirmOrder(orderId, btn) {
    if (btn) { btn.disabled = true; btn.textContent = 'Confirming…'; }
    try {
      const res  = await Auth.fetch(`/api/v1/procurement/orders/${orderId}/confirm/`, {
        method: 'POST',
      });
      const data = await res.json();
      if (!res.ok) { _toast(data.detail || 'Failed to confirm order.', 'error'); return; }
      _toast('Order confirmed. Ready to dispatch.', 'success');
      await _loadOrders();
    } catch (err) {
      _toast('Unexpected error.', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Confirm Order'; }
    }
  }

  // ── Manifest modal ─────────────────────────────────────────────────────────
  async function openManifest(orderId) {
    _activeOrderId = orderId;
    try {
      const res   = await Auth.fetch(`/api/v1/procurement/orders/${orderId}/`);
      const order = await res.json();
      _openManifest(order);
    } catch (err) {
      _toast('Could not load order details.', 'error');
    }
  }

  function _openManifest(order) {
    _activeOrderId = order.id;
    _set('manifest-order-number', order.order_number);
    _set('manifest-subtitle',     `${order.branch_name} · Week ${order.week_number}, ${order.year}`);
    _set('manifest-branch',       order.branch_name);
    _set('manifest-report',       `Week ${order.week_number}, ${order.year}`);

    const statusBadgeEl = document.getElementById('manifest-status-badge');
    if (statusBadgeEl) {
      statusBadgeEl.innerHTML = `<span class="status-badge ${order.status.toLowerCase().replace('_','-')}">${_statusLabel(order.status)}</span>`;
    }

    const tbody = document.getElementById('manifest-tbody');
    if (tbody) {
      tbody.innerHTML = (order.line_items || []).map(li => {
        const packDesc = li.pack_description || `${li.requested_qty} ${li.unit_label}`;
        const stockQty = `${parseFloat(li.requested_qty).toFixed(0)} ${li.unit_label}`;
        return `
          <tr>
            <td style="padding:11px 20px;border-bottom:1px solid var(--border);
              font-size:13px;font-weight:600;color:var(--text);">${_esc(li.consumable_name)}</td>
            <td style="padding:11px 16px;border-bottom:1px solid var(--border);
              font-size:12px;color:var(--text-3);">${_esc(li.consumable_category || '—')}</td>
            <td style="padding:11px 16px;border-bottom:1px solid var(--border);
              text-align:right;font-family:'JetBrains Mono',monospace;font-size:13px;
              font-weight:700;color:var(--text);">${_esc(packDesc)}</td>
            <td style="padding:11px 16px;border-bottom:1px solid var(--border);
              text-align:right;font-size:12px;color:var(--text-3);">${_esc(stockQty)}</td>
            <td style="padding:11px 20px;border-bottom:1px solid var(--border);
              font-size:11px;color:var(--text-3);max-width:220px;">${_esc((li.notes||'').split('|')[0])}</td>
          </tr>`;
      }).join('');
    }

    _set('manifest-item-count', `${(order.line_items||[]).length} items`);

    // Inject action buttons based on status
    const footer = document.getElementById('manifest-footer');
    if (footer) {
      let actionBtns = '';
      if (order.status === 'DRAFT') {
        actionBtns = `
          <button class="btn btn-primary" onclick="Ops.confirmOrder(${order.id}, this);Ops.closeManifestModal();">
            Confirm Order
          </button>`;
      } else if (order.status === 'CONFIRMED') {
        actionBtns = `
          <button class="btn btn-primary" onclick="Ops.closeManifestModal();Ops.openDispatchModal(${order.id});">
            Dispatch →
          </button>`;
      }
      footer.innerHTML = `
        <button class="btn btn-secondary" onclick="Ops.closeManifestModal()">Close</button>
        ${actionBtns}`;
    }

    document.getElementById('manifest-modal').classList.add('open');
  }

  function closeManifestModal() {
    document.getElementById('manifest-modal').classList.remove('open');
  }

  // ── Dispatch modal ─────────────────────────────────────────────────────────
  function openDispatchModal(orderId) {
    _activeOrderId = orderId;
    const order = _allOrders.find(o => o.id === orderId);
    if (order) {
      _set('dispatch-order-number', order.order_number);
      _set('dispatch-branch-name',  `${order.branch_name} · Week ${order.week_number}, ${order.year}`);
    }
    document.getElementById('dispatch-notes').value = '';
    document.getElementById('dispatch-modal').classList.add('open');
  }

  function closeDispatchModal() {
    document.getElementById('dispatch-modal').classList.remove('open');
  }

  async function confirmDispatch() {
    const notes = document.getElementById('dispatch-notes')?.value || '';
    const btn   = document.getElementById('btn-confirm-dispatch');
    btn.disabled = true; btn.textContent = 'Dispatching…';

    try {
      const res  = await Auth.fetch(`/api/v1/procurement/orders/${_activeOrderId}/dispatch/`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ ops_notes: notes }),
      });
      const data = await res.json();
      if (!res.ok) { _toast(data.detail || 'Dispatch failed.', 'error'); return; }
      _toast(`Order ${data.order_number} dispatched. BM has been notified.`, 'success');
      closeDispatchModal();
      await _loadOrders();
      switchPane('in-transit');
      _startDeliveryPolling();
    } catch (err) {
      _toast('Unexpected error.', 'error');
    } finally {
      btn.disabled = false; btn.textContent = 'Dispatch Now';
    }
  }

  // ── Delivery record modal ──────────────────────────────────────────────────
  async function openDeliveryModal(orderId) {
    _activeOrderId = orderId;
    try {
      const res   = await Auth.fetch(`/api/v1/procurement/orders/${orderId}/`);
      const order = await res.json();
      const tbody = document.getElementById('delivery-checklist-body');
      tbody.innerHTML = (order.line_items || []).map(li => {
        const expected = li.pack_description || `${li.requested_qty} ${li.unit_label}`;
        return `
          <tr>
            <td style="padding:10px 16px;border-bottom:1px solid var(--border);font-size:13px;font-weight:600;">
              ${_esc(li.consumable_name)}</td>
            <td style="padding:10px 16px;border-bottom:1px solid var(--border);
              text-align:right;font-size:12px;color:var(--text-3);">${_esc(expected)}</td>
            <td style="padding:10px 16px;border-bottom:1px solid var(--border);text-align:right;">
              <input type="number" class="qty-input" id="delivered-${li.id}"
                min="0" step="0.01" value="${parseFloat(li.requested_qty).toFixed(2)}"
                oninput="Ops._highlightDiscrepancy(this, ${parseFloat(li.requested_qty)})">
            </td>
          </tr>`;
      }).join('');
      document.getElementById('delivery-modal').classList.add('open');
    } catch (err) {
      _toast('Could not load order details.', 'error');
    }
  }

  function closeDeliveryModal() {
    document.getElementById('delivery-modal').classList.remove('open');
  }

  async function confirmDelivery() {
    const inputs = document.querySelectorAll('#delivery-checklist-body input[id^="delivered-"]');
    const delivered_quantities = {};
    for (const input of inputs) {
      const lineId = input.id.replace('delivered-', '');
      const qty    = parseFloat(input.value);
      if (isNaN(qty) || qty < 0) {
        _toast('All quantities must be valid non-negative numbers.', 'error');
        return;
      }
      delivered_quantities[lineId] = qty;
    }

    const btn = document.getElementById('btn-confirm-delivery');
    btn.disabled = true; btn.textContent = 'Recording…';

    try {
      const res  = await Auth.fetch(`/api/v1/procurement/orders/${_activeOrderId}/deliver/`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ delivered_quantities }),
      });
      const data = await res.json();
      if (!res.ok) { _toast(data.detail || 'Failed to record delivery.', 'error'); return; }
      _toast('Delivery recorded. Awaiting BM acceptance.', 'success');
      closeDeliveryModal();
      await _loadOrders();
    } catch (err) {
      _toast('Unexpected error.', 'error');
    } finally {
      btn.disabled = false; btn.textContent = 'Record Delivery';
    }
  }

  function _highlightDiscrepancy(input, expected) {
    const val = parseFloat(input.value);
    input.classList.toggle('discrepancy', !isNaN(val) && val !== expected);
  }

  // ── Delivery polling (5s when orders in transit) ───────────────────────────
  function _startDeliveryPolling() {
    _stopDeliveryPolling();
    _pollTimer = setInterval(async () => {
      await _loadOrders();
      const stillActive = _allOrders.some(o =>
        ['IN_TRANSIT', 'DELIVERED'].includes(o.status)
      );
      if (!stillActive) _stopDeliveryPolling();
    }, 5000);
  }

  function _stopDeliveryPolling() {
    if (_pollTimer) { clearInterval(_pollTimer); _pollTimer = null; }
  }

  // ── Pane switching ─────────────────────────────────────────────────────────
  function switchPane(pane) {
    _activePane = pane;
    ['branches', 'new-orders', 'in-transit', 'history'].forEach(p => {
      const paneEl = document.getElementById(`pane-${p}`);
      const itemEl = document.querySelector(`.sidebar-item[data-pane="${p}"]`);
      if (paneEl) paneEl.classList.toggle('active', p === pane);
      if (itemEl) itemEl.classList.toggle('active', p === pane);
    });
  }

  // ── Helpers ────────────────────────────────────────────────────────────────
  function _statusLabel(status) {
    const map = {
      DRAFT:     'Draft',
      CONFIRMED: 'Confirmed',
      IN_TRANSIT:'In Transit',
      DELIVERED: 'Delivered',
      CLOSED:    'Closed',
      CANCELLED: 'Cancelled',
    };
    return map[status] || status;
  }

  function _fmtDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('en-GB', {
      day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit',
    });
  }

  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function _setBadge(id, count) {
    const el = document.getElementById(id);
    if (!el) return;
    el.textContent   = count;
    el.style.display = count > 0 ? 'flex' : 'none';
  }

  function _esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el       = document.createElement('div');
    el.className   = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 4000);
  }

  return {
    init,
    loadBranches,
    prepareDeliverables,
    openManifestForBranch,
    openManifest,
    closeManifestModal,
    confirmOrder,
    openDispatchModal,
    closeDispatchModal,
    confirmDispatch,
    openDeliveryModal,
    closeDeliveryModal,
    confirmDelivery,
    switchPane,
    _toggleBranchExpand,
    _highlightDiscrepancy,
  };

})();

// ── Notifications ─────────────────────────────────────────────────────────────
const OpsNotif = (() => {
  let open = false;
  function toggle() { open ? close() : _open(); }
  function _open() {
    open = true;
    const dd = document.getElementById('ops-notif-dropdown');
    if (dd) dd.style.display = 'block';
    _load();
  }
  function close() {
    open = false;
    const dd = document.getElementById('ops-notif-dropdown');
    if (dd) dd.style.display = 'none';
  }
  async function _load() {
    const list = document.getElementById('ops-notif-list');
    if (!list) return;
    try {
      const res  = await Auth.fetch('/api/v1/notifications/');
      const data = await res.json();
      if (!data.length) {
        list.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-3);font-size:13px;">All caught up ✓</div>';
        return;
      }
      list.innerHTML = data.map(n => `
        <div style="padding:12px 16px;border-bottom:1px solid var(--border);
          background:${n.is_read ? 'var(--panel)' : 'var(--bg)'};cursor:pointer;"
          onclick="OpsNotif._markRead(${n.id}, this)">
          <div style="font-size:12.5px;color:var(--text);margin-bottom:3px;">${n.message}</div>
          <div style="font-size:11px;color:var(--text-3);">${n.time_ago || ''}</div>
        </div>`).join('');
    } catch {}
  }
  async function _markRead(id, el) {
    await Auth.fetch(`/api/v1/notifications/${id}/read/`, { method: 'POST' }).catch(() => {});
    if (el) el.style.background = 'var(--panel)';
    await _loadCount();
  }
  async function markAllRead() {
    await Auth.fetch('/api/v1/notifications/read-all/', { method: 'POST' }).catch(() => {});
    const badge = document.getElementById('ops-notif-badge');
    if (badge) badge.style.display = 'none';
  }
  async function _loadCount() {
    try {
      const res   = await Auth.fetch('/api/v1/notifications/unread-count/');
      const data  = await res.json();
      const count = data.count || 0;
      const badge = document.getElementById('ops-notif-badge');
      if (badge) {
        badge.textContent   = count > 99 ? '99+' : count;
        badge.style.display = count > 0 ? 'flex' : 'none';
      }
    } catch {}
  }
  function startPolling() { _loadCount(); setInterval(_loadCount, 30000); }
  document.addEventListener('click', e => {
    if (open &&
        !document.getElementById('ops-notif-btn')?.contains(e.target) &&
        !document.getElementById('ops-notif-dropdown')?.contains(e.target)) close();
  });
  return { toggle, close, markAllRead, startPolling, _markRead };
})();

// ── Profile dropdown ──────────────────────────────────────────────────────────
const OpsProfile = (() => {
  let open = false;
  function toggle() { open ? close() : _open(); }
  function _open() {
    open = true;
    const dd    = document.getElementById('ops-profile-dropdown');
    const arrow = document.getElementById('ops-profile-arrow');
    if (dd)    dd.style.display      = 'block';
    if (arrow) arrow.style.transform = 'rotate(180deg)';
  }
  function close() {
    open = false;
    const dd    = document.getElementById('ops-profile-dropdown');
    const arrow = document.getElementById('ops-profile-arrow');
    if (dd)    dd.style.display      = 'none';
    if (arrow) arrow.style.transform = 'rotate(0deg)';
  }
  document.addEventListener('click', e => {
    if (open &&
        !document.getElementById('ops-profile-btn')?.contains(e.target) &&
        !document.getElementById('ops-profile-dropdown')?.contains(e.target)) close();
  });
  return { toggle, close };
})();

// ── Boot ──────────────────────────────────────────────────────────────────────
async function _boot() {
  await Auth.guard(['OPERATIONS_MANAGER', 'SUPER_ADMIN']);
  Ops.init();
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', _boot);
} else {
  _boot();
}