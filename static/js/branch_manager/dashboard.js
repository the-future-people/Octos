/**
 * Octos — Branch Manager Dashboard
 * dashboard.js
 *
 * Handles:
 *  - Boot, user context, stats, meta strip
 *  - Sidebar pane switching with breadcrumb update
 *  - Collapsible sidebar state
 *  - Metrics rings (Day / Week / Month)
 *  - Recent jobs table
 *  - Jobs pane (fetched partial)
 *  - Inbox pane (lazy)
 *  - Services pane (lazy)
 *  - New Job modal (delegates to NJ controller)
 *  - Outsource Job modal
 *  - Notifications polling
 */

'use strict';

const Dashboard = (() => {

  // ── State ──────────────────────────────────────────────────
  let branchId      = null;
  let services      = [];
  let customers     = [];
  let jobsLoaded    = false;
  let inboxLoaded   = false;
  let svcLoaded     = false;
  let currentPeriod = 'day';

  // ── Boot ───────────────────────────────────────────────────
 async function init() {
    await Auth.guard(['BRANCH_MANAGER', 'BELT_MANAGER', 'REGIONAL_MANAGER', 'HQ_FACTORY_MANAGER', 'HQ_HR_MANAGER', 'REGIONAL_HR_COORDINATOR', 'SUPER_ADMIN']);
    _setDate();
    await Promise.all([
      loadContext(),
      loadStats(),
      loadRecentJobs(),
      _loadServicesAndCustomers(),
    ]);
    _renderMetrics(currentPeriod);
      Notifications.startPolling();
      WeekGreeter.init();
      _checkLateJobButton();
      setInterval(_checkLateJobButton, 60000);
      setInterval(_checkClosingWarning, 60000);
    _checkClosingWarning(); // check on load too
    }

  // ── Context ────────────────────────────────────────────────
  async function loadContext() {
    try {
      const res = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const user = await res.json();

      const fullName = user.full_name || user.email || '—';
      const initials = fullName.split(' ').slice(0, 2)
        .map(w => w[0]?.toUpperCase() || '').join('');

      _set('db-user-name',     fullName);
      _set('db-user-initials', initials);

   if (user.branch_detail) {
        const b = user.branch_detail;
        branchId = b.id;
        State.branchId = branchId;    // ← add this
        _set('db-branch-name', b.name || '—');
        _set('db-branch-name-left', b.name || '—');
        _set('db-branch-pill', b.name || '—');
        if (b.region_name)      _set('meta-region', b.region_name);
        if (b.belt_name)        _set('meta-belt',   b.belt_name);
        if (b.load_percentage != null) _set('meta-load', b.load_percentage + '%');
      }else if (user.branch && typeof user.branch === 'number') {
        branchId = user.branch;
        State.branchId = branchId;    // ← add this
        if (br.ok) {
          const b = await br.json();
          _set('db-branch-name', b.name || '—');
          _set('db-branch-name-left', b.name || '—');
          _set('db-branch-pill', b.name || '—');
          if (b.region_name)      _set('meta-region', b.region_name);
          if (b.belt_name)        _set('meta-belt',   b.belt_name);
          if (b.load_percentage != null) _set('meta-load', b.load_percentage + '%');
        }
      }
    } catch { /* silent */ }
  }

  // ── Stats ──────────────────────────────────────────────────
 async function loadStats() {
    try {
      // Scope everything to today's open sheet
      const sheetRes = await Auth.fetch('/api/v1/finance/sheets/today/');
      if (!sheetRes.ok) {
        _setStats(0, 0, 0, 0, 0);
        return;
      }
      const sheet = await sheetRes.json();

      if (sheet.status !== 'OPEN') {
        _setStats(0, 0, 0, 0, 0);
        _set('meta-load', '0%');
        return;
      }

      const res  = await Auth.fetch(`/api/v1/jobs/stats/?daily_sheet=${sheet.id}`);
      if (!res.ok) throw new Error();
      const data = await res.json();

      _setStats(data.total, data.in_progress, data.complete, data.pending, data.routed);

      // Sidebar badge — today's total only
      const jobsBadge = document.getElementById('sidebar-badge-jobs');
      if (jobsBadge) {
        jobsBadge.textContent   = data.total;
        jobsBadge.style.display = data.total > 0 ? 'flex' : 'none';
      }

      // Branch load
      const load = data.total > 0
        ? Math.round((data.in_progress / data.total) * 100) + '%'
        : '0%';
      _set('meta-load', load);

    } catch { /* silent */ }

    // Unread messages — not sheet-scoped, always live
    try {
      const res    = await Auth.fetch('/api/v1/communications/');
      if (!res.ok) throw new Error();
      const data   = await res.json();
      const convos = Array.isArray(data) ? data : (data.results || []);
      const unread = convos.reduce((sum, c) => sum + (c.unread_count || 0), 0);

      _set('stat-unread', unread);

      const inboxBadge = document.getElementById('sidebar-badge-inbox');
      if (inboxBadge) {
        inboxBadge.textContent   = unread;
        inboxBadge.style.display = unread > 0 ? 'flex' : 'none';
      }
    } catch { /* silent */ }
  }

  function _setStats(total, inProgress, complete, pending, routed) {
    _set('stat-total-jobs',      total);
    _set('stat-in-progress',     inProgress);
    _set('stat-complete',        complete);
    _set('stat-pending-payment', pending);
    _set('stat-routed',          routed);
  }

  // ── Recent jobs ────────────────────────────────────────────
async function loadRecentJobs() {
    const tbody = document.getElementById('recent-jobs-tbody');
    if (!tbody) return;

    try {
      // First get today's open sheet
      const sheetRes = await Auth.fetch('/api/v1/finance/sheets/today/');
      if (!sheetRes.ok) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--text-3);font-size:13px;">No open sheet today.</td></tr>`;
        return;
      }
      const sheet = await sheetRes.json();

      if (sheet.status !== 'OPEN') {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--text-3);font-size:13px;">Today's sheet is closed — jobs archived in the day sheet PDF.</td></tr>`;
        return;
      }

      // Fetch jobs scoped to this sheet
      const res  = await Auth.fetch(`/api/v1/jobs/?daily_sheet=${sheet.id}&page_size=10`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--text-3);font-size:13px;">No jobs recorded yet today.</td></tr>`;
        return;
      }

      tbody.innerHTML = jobs.map(j => `
        <tr onclick="Dashboard.switchPane('jobs','Jobs')">
          <td>
            <div class="td-job-title">${_esc(j.title || '—')}</div>
            <div class="td-job-ref">${_esc(j.job_number || '#' + j.id)}</div>
          </td>
          <td>${_typeBadge(j.job_type)}</td>
          <td>${_statusBadge(j.status)}</td>
          <td style="font-family:'JetBrains Mono',monospace;font-size:12.5px;">
            ${j.estimated_cost != null ? 'GHS ' + Number(j.estimated_cost).toFixed(2) : '—'}
          </td>
          <td style="font-size:12px;color:var(--text-3);">${_formatDate(j.created_at)}</td>
          <td>
            ${j.is_routed
              ? `<span style="font-size:12px;color:var(--purple-text);">→ Routed</span>`
              : `<span style="font-size:12px;color:var(--text-3);">Local</span>`}
          </td>
        </tr>`).join('');

    } catch {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--text-3);">Could not load jobs.</td></tr>`;
    }
  }

  // ── Metrics ────────────────────────────────────────────────
  function setPeriod(period) {
    currentPeriod = period;
    document.querySelectorAll('.period-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.period === period);
    });
    _renderMetrics(period);
  }

  function _renderMetrics(period) {
    const grid = document.getElementById('metrics-grid');
    if (!grid) return;

    // For now render with placeholder data
    // These will be wired to real API when analytics endpoint is ready
    const metrics = _getMetricData(period);

    grid.innerHTML = metrics.map(m => `
      <div class="metric-card">
        <div class="metric-ring">
          <svg viewBox="0 0 72 72" width="72" height="72">
            <circle class="metric-ring-bg" cx="36" cy="36" r="30"/>
            <circle class="metric-ring-fill"
              cx="36" cy="36" r="30"
              stroke="${m.color}"
              stroke-dasharray="${2 * Math.PI * 30}"
              stroke-dashoffset="${2 * Math.PI * 30 * (1 - m.value / 100)}"
            />
          </svg>
          <div class="metric-ring-label">${m.value}%</div>
        </div>
        <div class="metric-name">${m.name}</div>
        <div class="metric-sub">${m.sub}</div>
      </div>
    `).join('');
  }

  function _getMetricData(period) {
    // Placeholder — will be replaced with real API data
    const map = {
      day:   [
        { name: 'Completion Rate',   value: 0,  color: '#22c98a', sub: 'Jobs completed today' },
        { name: 'Collection Rate',   value: 0,  color: '#3355cc', sub: 'Revenue collected' },
        { name: 'Growth',            value: 0,  color: '#e8c84a', sub: 'vs yesterday' },
        { name: 'Queue Clearance',   value: 0,  color: '#7733cc', sub: 'Pending cleared' },
      ],
      week:  [
        { name: 'Completion Rate',   value: 0,  color: '#22c98a', sub: 'Jobs completed this week' },
        { name: 'Collection Rate',   value: 0,  color: '#3355cc', sub: 'Revenue collected' },
        { name: 'Growth',            value: 0,  color: '#e8c84a', sub: 'vs last week' },
        { name: 'Queue Clearance',   value: 0,  color: '#7733cc', sub: 'Pending cleared' },
      ],
      month: [
        { name: 'Completion Rate',   value: 0,  color: '#22c98a', sub: 'Jobs completed this month' },
        { name: 'Collection Rate',   value: 0,  color: '#3355cc', sub: 'Revenue collected' },
        { name: 'Growth',            value: 0,  color: '#e8c84a', sub: 'vs last month' },
        { name: 'Queue Clearance',   value: 0,  color: '#7733cc', sub: 'Pending cleared' },
      ],
    };
    return map[period] || map.day;
  }

  // ── Pane switching ─────────────────────────────────────────
  function switchPane(paneId, label) {
    // Update sidebar active state
    document.querySelectorAll('.sidebar-item').forEach(item => {
      item.classList.toggle('active', item.dataset.pane === paneId);
    });

    // Update pane visibility
    document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
    const target = document.getElementById(`pane-${paneId}`);
    if (target) target.classList.add('active');

    // Update breadcrumb
    _set('breadcrumb-current', label);

    // Lazy load pane content
   if (paneId === 'jobs'        && !jobsLoaded)  _loadJobsPane();
    if (paneId === 'inbox'       && !inboxLoaded) loadInboxTab();
    if (paneId === 'catalogue'   && !svcLoaded)   loadServicesTab();
    if (paneId === 'performance')                 _loadPerformancePane();
    if (paneId === 'finance') {
      const pane = document.getElementById('pane-finance');
      if (pane) pane.dataset.loaded = '';
      _loadFinancePane();
    }
    if (paneId === 'reports')                     _loadReportsPane();
    if (paneId === 'inventory')                   _loadInventoryPane();
    if (paneId === 'customers')                   _loadCustomersPane();
  }

  // ── Jobs pane ──────────────────────────────────────────────
  let _jobsTab = 'today';

  function _loadJobsPane() {
    jobsLoaded = true;
    const pane = document.getElementById('pane-jobs');
    if (!pane) return;

    // Inject tab bar above the existing jobs content
    const tabBar = document.createElement('div');
    tabBar.id = 'jobs-tab-bar';
    tabBar.className = 'reports-tabs';
    tabBar.style.marginBottom = '0';
    tabBar.innerHTML = `
      <button class="reports-tab active" data-tab="today"
        onclick="Dashboard.switchJobsTab('today')">Today's Jobs</button>
      <button class="reports-tab" data-tab="invoices"
        onclick="Dashboard.switchJobsTab('invoices')">Invoices</button>
      <button class="reports-tab" data-tab="receipts"
        onclick="Dashboard.switchJobsTab('receipts')">Receipts</button>`;

    // Wrap existing pane content in a tab content div
    const existing = pane.innerHTML;
    pane.innerHTML = '';
    pane.appendChild(tabBar);

    const tabContent = document.createElement('div');
    tabContent.id = 'jobs-tab-content';
    tabContent.innerHTML = existing;
    pane.appendChild(tabContent);

    Jobs.init({ embedded: true });
    _jobsTab = 'today';
  }

  function switchJobsTab(tab) {
    _jobsTab = tab;
    document.querySelectorAll('#jobs-tab-bar .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    const content = document.getElementById('jobs-tab-content');
    if (!content) return;

    if (tab === 'today') {
      // Re-init jobs pane content
      content.innerHTML = `
        <div class="jobs-pane-head">
          <div class="jobs-pane-title">Jobs</div>
          <div class="jobs-pane-actions">
            <button class="hero-btn hero-btn-primary" style="padding:8px 16px;" onclick="NJ.open()">
              <div class="hero-btn-icon" style="width:24px;height:24px;">
                <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
              </div>
              <div class="hero-btn-label">
                <span class="hero-btn-title" style="font-size:13px;">New Job</span>
              </div>
            </button>
          </div>
        </div>
        <div class="jobs-stat-strip">
          <div class="stat-card blue"><div class="stat-num" id="jobs-stat-total">—</div><div class="stat-lbl">Total Jobs</div></div>
          <div class="stat-card amber"><div class="stat-num" id="jobs-stat-in-progress">—</div><div class="stat-lbl">In Progress</div></div>
          <div class="stat-card green"><div class="stat-num" id="jobs-stat-complete">—</div><div class="stat-lbl">Complete</div></div>
          <div class="stat-card purple"><div class="stat-num" id="jobs-stat-revenue">—</div><div class="stat-lbl">Revenue (GHS)</div></div>
        </div>
        <div class="jobs-toolbar">
          <div class="filter-tabs" id="jobs-filter-tabs">
            <button class="filter-tab active" data-status="all">All Today</button>
            <button class="filter-tab" data-status="DRAFT">Draft</button>
            <button class="filter-tab" data-status="PENDING_PAYMENT">Pending Payment</button>
            <button class="filter-tab" data-status="IN_PROGRESS">In Progress</button>
            <button class="filter-tab" data-status="READY">Ready</button>
            <button class="filter-tab" data-status="HALTED">Halted</button>
            <button class="filter-tab" data-status="COMPLETE">Complete</button>
            <button class="filter-tab" data-status="CANCELLED">Cancelled</button>
          </div>
          <div class="toolbar-right">
            <input type="text" id="jobs-search" class="inp-sm" placeholder="Search jobs…" style="width:180px;">
            <select id="jobs-type" class="sel-sm">
              <option value="">All Types</option>
              <option value="INSTANT">Instant</option>
              <option value="PRODUCTION">Production</option>
              <option value="DESIGN">Design</option>
            </select>
          </div>
        </div>
        <div class="jobs-table-wrap">
          <table class="p-table">
            <thead>
              <tr>
                <th>Job</th><th>Customer</th><th>Type</th>
                <th>Status</th><th>Price</th><th>Date</th>
              </tr>
            </thead>
            <tbody id="jobs-tbody">
              <tr><td colspan="6" class="loading-cell"><span class="spin"></span> Loading jobs…</td></tr>
            </tbody>
          </table>
          <div class="jobs-pagination" id="jobs-pagination" style="display:none;">
            <span class="jobs-page-info" id="jobs-page-info"></span>
            <div class="jobs-page-btns">
              <button class="jobs-page-btn" id="jobs-btn-prev" onclick="Jobs.prevPage()">← Prev</button>
              <button class="jobs-page-btn" id="jobs-btn-next" onclick="Jobs.nextPage()">Next →</button>
            </div>
          </div>
        </div>`;
      Jobs.init({ embedded: true });
    }

    if (tab === 'invoices') {
      content.innerHTML = `
        <div class="section-head">
          <span class="section-title">Invoices</span>
          <button class="btn-dark" style="padding:6px 14px;font-size:12px;"
            onclick="Invoice.open()">+ New Invoice</button>
        </div>
        <div id="invoices-content">
          <div class="loading-cell"><span class="spin"></span> Loading…</div>
        </div>`;
      _loadInvoicesContent();
    }

    if (tab === 'receipts') {
      content.innerHTML = `
        <div class="section-head">
          <span class="section-title">Receipts</span>
          <span style="font-size:12px;color:var(--text-3);">Read-only · Completed jobs</span>
        </div>
        <div id="receipts-content">
          <div class="loading-cell"><span class="spin"></span> Loading…</div>
        </div>`;
      _loadReceiptsContent();
    }
  }

  async function _loadInvoicesContent() {
    const container = document.getElementById('invoices-content');
    if (!container) return;

    try {
      const res      = await Auth.fetch('/api/v1/finance/invoices/');
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const invoices = Array.isArray(data) ? data : (data.results || []);

      if (!invoices.length) {
        container.innerHTML = `<div style="text-align:center;padding:48px;
          color:var(--text-3);font-size:13px;">No invoices yet.</div>`;
        return;
      }

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table class="p-table">
            <thead>
              <tr>
                <th>Invoice No</th><th>Type</th><th>Bill To</th>
                <th>Amount</th><th>Status</th><th>Date</th><th></th>
              </tr>
            </thead>
            <tbody>
              ${invoices.map(inv => `
                <tr>
                  <td style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;">
                    ${_esc(inv.invoice_number)}</td>
                  <td><span class="badge ${inv.invoice_type === 'PROFORMA' ? 'badge-production' : 'badge-instant'}">
                    ${inv.invoice_type}</span></td>
                  <td>
                    <div style="font-weight:600;font-size:13px;">${_esc(inv.bill_to_name || '—')}</div>
                    ${inv.bill_to_company ? `<div style="font-size:11px;color:var(--text-3);">${_esc(inv.bill_to_company)}</div>` : ''}
                  </td>
                  <td style="font-family:'JetBrains Mono',monospace;font-weight:600;">
                    ${_fmt(inv.total)}</td>
                  <td><span class="badge ${_invoiceStatusBadge(inv.status)}">${inv.status}</span></td>
                  <td style="font-size:12px;color:var(--text-3);">
                    ${inv.issue_date ? new Date(inv.issue_date).toLocaleDateString('en-GH') : '—'}</td>
                  <td>
                    <button onclick="Dashboard.downloadInvoicePDF(${inv.id}, '${_esc(inv.invoice_number)}')"
                      style="padding:5px 12px;font-size:12px;font-weight:600;
                        background:var(--bg);border:1px solid var(--border);
                        border-radius:var(--radius-sm);cursor:pointer;
                        font-family:'DM Sans',sans-serif;color:var(--text-2);">↓ PDF</button>
                  </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      container.innerHTML = `<div class="loading-cell">Could not load invoices.</div>`;
    }
  }

 // ── Receipts tab ───────────────────────────────────────────
  let _receiptsPeriod  = 'day';
  let _activeReceiptId = null;

  async function _loadReceiptsContent() {
    const container = document.getElementById('receipts-content');
    if (!container) return;

    container.innerHTML = `
      <!-- Period selector -->
      <div style="display:flex;align-items:center;justify-content:space-between;
        margin-bottom:16px;">
        <div style="font-size:13px;font-weight:600;color:var(--text-2);">
          Branch Receipts
        </div>
        <div class="reports-tabs" id="receipts-period-tabs" style="margin-bottom:0;">
          <button class="reports-tab active" data-period="day"
            onclick="Dashboard.setReceiptsPeriod('day')">Today</button>
          <button class="reports-tab" data-period="week"
            onclick="Dashboard.setReceiptsPeriod('week')">This Week</button>
          <button class="reports-tab" data-period="month"
            onclick="Dashboard.setReceiptsPeriod('month')">This Month</button>
        </div>
      </div>

      <!-- Two-panel layout -->
      <div style="display:flex;gap:0;border:1px solid var(--border);
        border-radius:var(--radius);overflow:hidden;min-height:520px;">

        <!-- Left — receipt list -->
        <div id="receipts-list-panel"
          style="width:300px;flex-shrink:0;border-right:1px solid var(--border);
            overflow-y:auto;background:var(--panel);">
          <div style="padding:20px;text-align:center;color:var(--text-3);">
            <span class="spin"></span>
          </div>
        </div>

        <!-- Right — receipt detail -->
        <div id="receipts-detail-panel"
          style="flex:1;display:flex;flex-direction:column;background:var(--bg);
            overflow:hidden;position:relative;">
          <div style="flex:1;display:flex;align-items:center;justify-content:center;
            flex-direction:column;gap:12px;color:var(--text-3);padding:40px;">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"
              viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.5" style="opacity:0.3;">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
            <div style="font-size:13px;">Select a receipt to view details</div>
          </div>
        </div>

      </div>`;

    await _fetchReceipts();
  }

  async function _fetchReceipts() {
    const listPanel = document.getElementById('receipts-list-panel');
    if (!listPanel) return;

    listPanel.innerHTML = `<div style="padding:20px;text-align:center;
      color:var(--text-3);"><span class="spin"></span></div>`;

    try {
      const res      = await Auth.fetch(
        `/api/v1/finance/receipts/?period=${_receiptsPeriod}&page_size=100`
      );
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const receipts = Array.isArray(data) ? data : (data.results || []);

      if (!receipts.length) {
        listPanel.innerHTML = `
          <div style="padding:32px 16px;text-align:center;
            color:var(--text-3);font-size:13px;">
            No receipts for this period.
          </div>`;
        return;
      }

      const methodColor = {
        CASH  : { bg: 'var(--cash-bg)',  text: 'var(--cash-text)',  border: 'var(--cash-border)' },
        MOMO  : { bg: 'var(--momo-bg)',  text: 'var(--momo-text)',  border: 'var(--momo-border)' },
        POS   : { bg: 'var(--pos-bg)',   text: 'var(--pos-text)',   border: 'var(--pos-border)'  },
        CREDIT: { bg: 'var(--bg)',       text: 'var(--text-3)',     border: 'var(--border)'      },
      };

      listPanel.innerHTML = receipts.map(r => {
        const mc      = methodColor[r.payment_method] || methodColor.CREDIT;
        const time    = r.created_at
          ? new Date(r.created_at).toLocaleTimeString('en-GH', {
              hour: '2-digit', minute: '2-digit'
            })
          : '—';
        const date    = r.created_at
          ? new Date(r.created_at).toLocaleDateString('en-GB', {
              day: 'numeric', month: 'short'
            })
          : '—';
        const isActive = r.id === _activeReceiptId;

        return `
          <div onclick="Dashboard.openReceipt(${r.id})"
            id="receipt-row-${r.id}"
            style="padding:14px 16px;border-bottom:1px solid var(--border);
              cursor:pointer;background:${isActive ? 'var(--bg)' : 'var(--panel)'};
              transition:background 0.12s;border-left:3px solid ${isActive ? 'var(--text)' : 'transparent'};"
            onmouseover="this.style.background='var(--bg)'"
            onmouseout="this.style.background='${isActive ? 'var(--bg)' : 'var(--panel)'}'">

            <!-- Row top: receipt number + amount -->
            <div style="display:flex;align-items:center;
              justify-content:space-between;margin-bottom:4px;">
              <span style="font-family:'JetBrains Mono',monospace;font-size:11px;
                font-weight:700;color:var(--text);">
                ${_esc(r.receipt_number || '#' + r.id)}
              </span>
              <span style="font-family:'JetBrains Mono',monospace;font-size:13px;
                font-weight:700;color:var(--text);">
                ${_fmt(r.amount_paid)}
              </span>
            </div>

            <!-- Row mid: customer -->
            <div style="font-size:12px;color:var(--text-2);font-weight:500;
              margin-bottom:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
              ${_esc(r.customer_name || 'Walk-in')}
            </div>

            <!-- Row bottom: method badge + time -->
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <span style="font-size:10px;font-weight:700;padding:2px 7px;
                border-radius:4px;border:1px solid ${mc.border};
                background:${mc.bg};color:${mc.text};">
                ${r.payment_method || '—'}
              </span>
              <span style="font-size:11px;color:var(--text-3);
                font-family:'JetBrains Mono',monospace;">
                ${date} · ${time}
              </span>
            </div>

          </div>`;
      }).join('');

      // Auto-open first receipt
      if (receipts.length && !_activeReceiptId) {
        openReceipt(receipts[0].id);
      }

    } catch {
      listPanel.innerHTML = `<div style="padding:24px;text-align:center;
        color:var(--red-text);font-size:13px;">Could not load receipts.</div>`;
    }
  }

  async function openReceipt(receiptId) {
    _activeReceiptId = receiptId;

    // Highlight active row
    document.querySelectorAll('[id^="receipt-row-"]').forEach(el => {
      const isActive = el.id === `receipt-row-${receiptId}`;
      el.style.background  = isActive ? 'var(--bg)'   : 'var(--panel)';
      el.style.borderLeft  = isActive ? '3px solid var(--text)' : '3px solid transparent';
    });

    const detail = document.getElementById('receipts-detail-panel');
    if (!detail) return;
    detail.innerHTML = `<div style="flex:1;display:flex;align-items:center;
      justify-content:center;padding:40px;">
      <span class="spin"></span></div>`;

    try {
      const res = await Auth.fetch(`/api/v1/finance/receipts/${receiptId}/`);
      if (!res.ok) throw new Error();
      const r = await res.json();
      _renderReceiptDetail(detail, r);
    } catch {
      detail.innerHTML = `<div style="flex:1;display:flex;align-items:center;
        justify-content:center;color:var(--red-text);font-size:13px;padding:40px;">
        Could not load receipt.</div>`;
    }
  }

  function _renderReceiptDetail(container, r) {
    const methodColor = {
      CASH  : { bg: 'var(--cash-bg)',  text: 'var(--cash-text)',  border: 'var(--cash-border)',  strong: 'var(--cash-strong)'  },
      MOMO  : { bg: 'var(--momo-bg)',  text: 'var(--momo-text)',  border: 'var(--momo-border)',  strong: 'var(--momo-strong)'  },
      POS   : { bg: 'var(--pos-bg)',   text: 'var(--pos-text)',   border: 'var(--pos-border)',   strong: 'var(--pos-strong)'   },
      CREDIT: { bg: 'var(--bg)',       text: 'var(--text-3)',     border: 'var(--border)',       strong: 'var(--text-3)'       },
    };
    const mc = methodColor[r.payment_method] || methodColor.CREDIT;

    const lineItems = (r.line_items || []).map(li => `
      <div style="display:grid;grid-template-columns:1fr auto auto;
        gap:12px;align-items:center;padding:9px 0;
        border-bottom:1px solid var(--border);">
        <div>
          <div style="font-size:13px;font-weight:500;color:var(--text);">
            ${_esc(li.service_name || li.service || '—')}
          </div>
          ${li.pages && li.sets ? `
            <div style="font-size:11px;color:var(--text-3);margin-top:1px;">
              ${li.pages} pg × ${li.sets} set${li.sets !== 1 ? 's' : ''}
              ${li.is_color ? ' · Colour' : ' · B&W'}
            </div>` : ''}
        </div>
        <div style="font-size:12px;color:var(--text-3);text-align:right;">
          ${li.unit_price != null ? _fmt(li.unit_price) : '—'}
        </div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
          font-weight:600;color:var(--text);text-align:right;min-width:80px;">
          ${li.line_total != null ? _fmt(li.line_total) : '—'}
        </div>
      </div>`).join('');

    const issuedAt = r.created_at
      ? new Date(r.created_at).toLocaleString('en-GH', {
          day: 'numeric', month: 'short', year: 'numeric',
          hour: '2-digit', minute: '2-digit'
        })
      : '—';

    container.innerHTML = `
      <div style="flex:1;overflow-y:auto;padding:24px;min-height:0;" id="receipt-printable">

        <!-- ① Header -->
        <div style="display:flex;align-items:flex-start;
          justify-content:space-between;margin-bottom:20px;
          padding-bottom:16px;border-bottom:1px solid var(--border);">
          <div>
            <div style="font-family:'Syne',sans-serif;font-size:18px;
              font-weight:800;color:var(--text);letter-spacing:-0.3px;">
              ${_esc(r.receipt_number || '—')}
            </div>
            <div style="font-size:12px;color:var(--text-3);margin-top:3px;">
              ${issuedAt}
            </div>
          </div>
          <span style="padding:4px 12px;border-radius:20px;font-size:11px;
            font-weight:700;background:var(--green-bg);color:var(--green-text);
            border:1px solid var(--green-border);">
            PAID
          </span>
        </div>

        <!-- ② Job summary -->
        <div style="margin-bottom:20px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">
            Job
          </div>
          <div style="font-size:14px;font-weight:700;color:var(--text);
            margin-bottom:3px;">
            ${_esc(r.job_title || r.job?.title || '—')}
          </div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:11px;
            color:var(--text-3);">
            ${_esc(r.job_number || r.job?.job_number || '—')}
          </div>
        </div>

        <!-- ③ Line items -->
        ${lineItems ? `
        <div style="margin-bottom:20px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">
            Services
          </div>
          <div style="background:var(--panel);border:1px solid var(--border);
            border-radius:var(--radius-sm);padding:0 14px;">
            <div style="display:grid;grid-template-columns:1fr auto auto;
              gap:12px;padding:7px 0;border-bottom:1px solid var(--border);">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;">Service</div>
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;text-align:right;">Unit</div>
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;text-align:right;
                min-width:80px;">Total</div>
            </div>
            ${lineItems}
            <div style="display:flex;justify-content:space-between;
              padding:10px 0;margin-top:2px;">
              <span style="font-size:12px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.3px;">Subtotal</span>
              <span style="font-family:'JetBrains Mono',monospace;font-size:13px;
                font-weight:700;color:var(--text);">
                ${_fmt(r.subtotal || r.amount_paid)}
              </span>
            </div>
          </div>
        </div>` : ''}

        <!-- ④ Payment settlement -->
        <div style="margin-bottom:20px;background:${mc.bg};
          border:1px solid ${mc.border};border-radius:var(--radius-sm);
          padding:14px 16px;">
          <div style="font-size:10px;font-weight:700;color:${mc.text};
            text-transform:uppercase;letter-spacing:0.8px;margin-bottom:12px;">
            Payment Settlement
          </div>
          ${[
            ['Amount Due',    _fmt(r.subtotal || r.amount_paid), false],
            ['Amount Paid',   _fmt(r.amount_paid),               true ],
            r.cash_tendered != null && parseFloat(r.cash_tendered) > 0
              ? ['Cash Tendered', _fmt(r.cash_tendered), false] : null,
            r.change_given != null && parseFloat(r.change_given) > 0
              ? ['Change Given', _fmt(r.change_given), false] : null,
            r.balance_due != null && parseFloat(r.balance_due) > 0
              ? ['Balance Due', _fmt(r.balance_due), false] : null,
          ].filter(Boolean).map(([label, val, strong]) => `
            <div style="display:flex;justify-content:space-between;
              align-items:center;padding:5px 0;
              ${strong ? 'border-top:1px solid ' + mc.border + ';margin-top:4px;padding-top:9px;' : ''}">
              <span style="font-size:12px;font-weight:${strong ? '700' : '500'};
                color:${mc.text};">${label}</span>
              <span style="font-family:'JetBrains Mono',monospace;
                font-size:${strong ? '16px' : '13px'};
                font-weight:${strong ? '800' : '600'};
                color:${strong ? mc.strong : mc.text};">${val}</span>
            </div>`).join('')}
        </div>

        <!-- ⑤ Payment method -->
        <div style="margin-bottom:20px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">
            Payment Method
          </div>
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <span style="padding:5px 14px;border-radius:20px;font-size:12px;
              font-weight:700;background:${mc.bg};color:${mc.text};
              border:1px solid ${mc.border};">
              ${r.payment_method || '—'}
            </span>
            ${r.momo_reference ? `
              <span style="font-size:12px;color:var(--text-3);">
                Ref: <span style="font-family:'JetBrains Mono',monospace;
                  font-weight:600;color:var(--text);">${_esc(r.momo_reference)}</span>
              </span>` : ''}
            ${r.pos_approval_code ? `
              <span style="font-size:12px;color:var(--text-3);">
                Approval: <span style="font-family:'JetBrains Mono',monospace;
                  font-weight:600;color:var(--text);">${_esc(r.pos_approval_code)}</span>
              </span>` : ''}
          </div>
        </div>

        <!-- ⑥ People -->
        <div style="margin-bottom:24px;background:var(--panel);
          border:1px solid var(--border);border-radius:var(--radius-sm);
          padding:14px 16px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.8px;margin-bottom:12px;">
            People
          </div>
          ${[
            ['Customer',  r.customer_name || 'Walk-in'],
            r.customer_phone ? ['Phone', r.customer_phone] : null,
            ['Cashier',   r.cashier_name  || r.cashier?.full_name || '—'],
            ['Attendant', r.intake_by_name || '—'],
          ].filter(Boolean).map(([label, val]) => `
            <div style="display:flex;justify-content:space-between;
              padding:5px 0;border-bottom:1px solid var(--border);">
              <span style="font-size:12px;color:var(--text-3);">${label}</span>
              <span style="font-size:13px;font-weight:500;color:var(--text);">
                ${_esc(val)}
              </span>
            </div>`).join('')}
        </div>

      </div>

      <!-- ⑦ Actions -->
      <div style="padding:16px 24px;border-top:1px solid var(--border);
        background:var(--panel);display:flex;gap:10px;flex-shrink:0;">
        <button onclick="Dashboard.printReceiptDetail()"
          style="flex:1;padding:10px;background:var(--text);color:#fff;
            border:none;border-radius:var(--radius-sm);font-size:13px;
            font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;
            display:flex;align-items:center;justify-content:center;gap:8px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
            viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="6 9 6 2 18 2 18 9"/>
            <path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/>
            <rect x="6" y="14" width="12" height="8"/>
          </svg>
          Print Receipt
        </button>
        ${r.customer_phone ? `
        <button onclick="Dashboard.sendReceiptWhatsApp(${r.id})"
          style="flex:1;padding:10px;background:#25D366;color:#fff;
            border:none;border-radius:var(--radius-sm);font-size:13px;
            font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;
            display:flex;align-items:center;justify-content:center;gap:8px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
            viewBox="0 0 24 24" fill="currentColor">
            <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z"/>
          </svg>
          Send WhatsApp
        </button>` : ''}
      </div>`;
  }

  function setReceiptsPeriod(period) {
    _receiptsPeriod  = period;
    _activeReceiptId = null;
    document.querySelectorAll('#receipts-period-tabs .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.period === period);
    });
    // Reset detail panel
    const detail = document.getElementById('receipts-detail-panel');
    if (detail) detail.innerHTML = `
      <div style="flex:1;display:flex;align-items:center;justify-content:center;
        flex-direction:column;gap:12px;color:var(--text-3);padding:40px;">
        <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"
          viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="1.5" style="opacity:0.3;">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <div style="font-size:13px;">Select a receipt to view details</div>
      </div>`;
    _fetchReceipts();
  }

  async function printReceiptDetail() {
    if (!_activeReceiptId) return;
    try {
      const res  = await Auth.fetch(`/api/v1/finance/receipts/${_activeReceiptId}/thermal/`);
      if (!res.ok) { _toast('Could not load receipt for printing.', 'error'); return; }
      const data = await res.json();
      const win  = window.open('', '_blank', 'width=300,height=600');
      if (win) {
win.document.write(`<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <title>Receipt</title>
  <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }

    body {
      font-family: 'Courier New', Courier, monospace;
      font-size: 12px;
      color: #000;
      background: #fff;
      display: flex;
      justify-content: center;
      padding: 16px;
    }

    pre {
      white-space: pre-wrap;
      word-break: break-word;
      width: 80mm;
      font-size: 11px;
    }

    @media print {
      @page { margin: 8mm; }
      body { padding: 0; }
    }
  </style>
</head>
<body>
  <pre>${data.text}</pre>
</body>
</html>`);
        win.document.close();
        win.focus();
        setTimeout(() => { win.print(); win.close(); }, 300);
      }
    } catch {
      _toast('Print error.', 'error');
    }
  }

  async function sendReceiptWhatsApp(receiptId) {
    try {
      const res = await Auth.fetch(
        `/api/v1/finance/receipts/${receiptId}/send-whatsapp/`,
        { method: 'POST' }
      );
      if (res.ok) _toast('Receipt sent via WhatsApp.', 'success');
      else _toast('WhatsApp delivery failed.', 'error');
    } catch {
      _toast('Network error.', 'error');
    }
  }

  function printReceipt(id) {
    openReceipt(id);
  }

// ── Performance pane ───────────────────────────────────────
  let _performanceTab = 'metrics';

  function _loadPerformancePane() {
    const pane = document.getElementById('pane-performance');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Performance</span>
      </div>
      <div class="reports-tabs" id="performance-tab-bar">
        <button class="reports-tab active" data-tab="metrics"
          onclick="Dashboard.switchPerformanceTab('metrics')">Branch Metrics</button>
        <button class="reports-tab" data-tab="services"
          onclick="Dashboard.switchPerformanceTab('services')">Service Performance</button>
      </div>
      <div id="performance-tab-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    switchPerformanceTab('metrics');
  }

function switchPerformanceTab(tab) {
    _performanceTab = tab;
    document.querySelectorAll('#performance-tab-bar .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    const content = document.getElementById('performance-tab-content');
    if (!content) return;

    if (tab === 'metrics') {
      content.innerHTML = `
        <div class="section-head" style="margin-top:16px;">
          <span></span>
          <div class="period-tabs">
            <button class="period-tab active" data-period="day"   onclick="Dashboard.setPeriod('day')">Day</button>
            <button class="period-tab"         data-period="week"  onclick="Dashboard.setPeriod('week')">Week</button>
            <button class="period-tab"         data-period="month" onclick="Dashboard.setPeriod('month')">Month</button>
          </div>
        </div>
        <div class="metrics-section">
          <div class="metrics-grid" id="metrics-grid">
            <div class="loading-cell" style="grid-column:1/-1;padding:40px !important;">
              <span class="spin"></span> Loading metrics…
            </div>
          </div>
        </div>`;
      _renderMetrics(currentPeriod);
    }

    if (tab === 'services') {
      content.innerHTML = `
        <div id="services-report-content" style="margin-top:16px;">
          <div class="loading-cell"><span class="spin"></span> Loading…</div>
        </div>`;
      _renderServicesReport(content);
    }
  }



  // ── Finance pane ───────────────────────────────────────────
 async function _loadFinancePane() {
    const pane = document.getElementById('pane-finance');
    if (!pane || pane.dataset.loaded) return;
    pane.dataset.loaded = '1';

    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Day Sheet</span>
      </div>
      <div class="reports-tabs" id="daysheet-tabs">
        <button class="reports-tab active" data-tab="today"
          onclick="Dashboard.switchDaySheetTab('today')">Today's Sheet</button>
        <button class="reports-tab" data-tab="archive"
          onclick="Dashboard.switchDaySheetTab('archive')">Archive</button>
      </div>
      <div id="daysheet-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    await _loadDaySheetTab('today');
  }

  async function switchDaySheetTab(tab) {
    document.querySelectorAll('#daysheet-tabs .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    await _loadDaySheetTab(tab);
  }

  async function _loadDaySheetTab(tab) {
    const content = document.getElementById('daysheet-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';
    if (tab === 'today')   await _renderTodaySheet(content);
    if (tab === 'archive') await _renderSheetsArchive(content);
  }

  async function _renderTodaySheet(container) {
    try {
      const res = await Auth.fetch('/api/v1/finance/sheets/today/');
      if (!res.ok) throw new Error();
      const sheet = await res.json();

      container.innerHTML = `
        <!-- Status strip -->
        <div style="display:flex;align-items:center;justify-content:space-between;
          margin-bottom:16px;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-size:13px;font-weight:600;color:var(--text-2);">
              ${sheet.date}
            </span>
            <span class="badge badge-${sheet.status === 'OPEN' ? 'progress' : 'done'}">
              ${sheet.status}
            </span>
          </div>
          ${sheet.status === 'OPEN' ? `
            <button class="btn-dark" onclick="Dashboard.closeSheet(${sheet.id})">
              Close Day Sheet
            </button>` : `
            <button onclick="Dashboard.downloadSheetPDF(${sheet.id}, '${sheet.date}')"
              style="display:inline-flex;align-items:center;gap:6px;padding:7px 16px;
                     background:var(--text);color:#fff;border-radius:var(--radius-sm);
                     font-size:13px;font-weight:700;border:none;cursor:pointer;">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="2">
                <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/>
                <polyline points="7 10 12 15 17 10"/>
                <line x1="12" y1="15" x2="12" y2="3"/>
              </svg>
              Download PDF
            </button>`}
        </div>

        <!-- Revenue cards -->
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">
          <div class="stat-card green">
            <div class="stat-num">${_fmt(sheet.total_cash)}</div>
            <div class="stat-lbl">Cash</div>
          </div>
          <div class="stat-card amber">
            <div class="stat-num">${_fmt(sheet.total_momo)}</div>
            <div class="stat-lbl">MoMo</div>
          </div>
          <div class="stat-card blue">
            <div class="stat-num">${_fmt(sheet.total_pos)}</div>
            <div class="stat-lbl">POS</div>
          </div>
          <div class="stat-card purple">
            <div class="stat-num">${_fmt(sheet.net_cash_in_till)}</div>
            <div class="stat-lbl">Net Cash In Till</div>
          </div>
        </div>

        <!-- Sheet details -->
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:16px 20px;
          display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin-bottom:16px;">
          <div>
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Total Jobs</div>
            <div style="font-size:18px;font-weight:700;color:var(--text);">
              ${sheet.total_jobs_created}
            </div>
          </div>
          <div>
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Refunds</div>
            <div style="font-size:18px;font-weight:700;color:var(--text);">
              ${_fmt(sheet.total_refunds)}
            </div>
          </div>
          <div>
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Petty Cash Out</div>
            <div style="font-size:18px;font-weight:700;color:var(--text);">
              ${_fmt(sheet.total_petty_cash_out)}
            </div>
          </div>
          <div>
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Credit Issued</div>
            <div style="font-size:18px;font-weight:700;color:var(--text);">
              ${_fmt(sheet.total_credit_issued)}
            </div>
          </div>
        </div>

        ${sheet.notes ? `
          <div style="padding:12px 16px;background:var(--bg);border:1px solid var(--border);
            border-radius:var(--radius-sm);font-size:13px;color:var(--text-2);">
            ${_esc(sheet.notes)}
          </div>` : ''}`;

    } catch {
      container.innerHTML = '<div class="loading-cell">Could not load today\'s sheet.</div>';
    }
  }

  async function _renderSheetsArchive(container) {
    try {
      const res    = await Auth.fetch('/api/v1/finance/sheets/?page_size=50');
      if (!res.ok) throw new Error();
      const data   = await res.json();
      const sheets = Array.isArray(data) ? data : (data.results || []);

      if (!sheets.length) {
        container.innerHTML = '<div class="loading-cell">No sheets found.</div>';
        return;
      }

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table class="p-table" id="sheets-archive-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Status</th>
                <th>Jobs</th>
                <th>Cash</th>
                <th>MoMo</th>
                <th>POS</th>
                <th>Total</th>
                <th></th>
              </tr>
            </thead>
            <tbody id="sheets-archive-tbody">
              ${sheets.map(s => {
                const total = parseFloat(s.total_cash||0)
                  + parseFloat(s.total_momo||0)
                  + parseFloat(s.total_pos||0);
                return `
                  <tr id="sheet-row-${s.id}" onclick="Dashboard.toggleSheetRow(${s.id}, '${s.date}')"
                    style="cursor:pointer;transition:background 0.12s;"
                    onmouseover="this.style.background='var(--bg)'"
                    onmouseout="this.style.background=''">
                    <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">
                      ${s.date}
                    </td>
                    <td>
                      <span class="badge badge-${s.status==='OPEN'?'progress':'done'}">
                        ${s.status}
                      </span>
                    </td>
                    <td>${s.total_jobs_created || 0}</td>
                    <td>${_fmt(s.total_cash)}</td>
                    <td>${_fmt(s.total_momo)}</td>
                    <td>${_fmt(s.total_pos)}</td>
                    <td style="font-weight:700;">${_fmt(total)}</td>
                    <td>
                      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"
                        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                        id="sheet-chevron-${s.id}" style="color:var(--text-3);transition:transform 0.2s;">
                        <polyline points="6 9 12 15 18 9"/>
                      </svg>
                    </td>
                  </tr>
                  <tr id="sheet-detail-${s.id}" style="display:none;">
                    <td colspan="8" class="sheet-detail-td" style="background:var(--bg);border-bottom:1px solid var(--border);">
                      <div id="sheet-detail-content-${s.id}"
                        style="padding:16px 0;border-top:1px solid var(--border);margin-left:-1px;">
                        <div class="loading-cell"><span class="spin"></span> Loading…</div>
                      </div>
                    </td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load archive.</div>';
    }
  }

  let _openSheetRow = null;

  async function toggleSheetRow(sheetId, sheetDate) {
    const detailRow     = document.getElementById(`sheet-detail-${sheetId}`);
    const chevron       = document.getElementById(`sheet-chevron-${sheetId}`);
    const contentEl     = document.getElementById(`sheet-detail-content-${sheetId}`);
    const isOpen        = detailRow.style.display !== 'none';

    // Close any open row
    if (_openSheetRow && _openSheetRow !== sheetId) {
      const prevDetail  = document.getElementById(`sheet-detail-${_openSheetRow}`);
      const prevChevron = document.getElementById(`sheet-chevron-${_openSheetRow}`);
      if (prevDetail)  prevDetail.style.display  = 'none';
      if (prevChevron) prevChevron.style.transform = 'rotate(0deg)';
    }

    if (isOpen) {
      detailRow.style.display   = 'none';
      chevron.style.transform   = 'rotate(0deg)';
      _openSheetRow             = null;
    } else {
      detailRow.style.display   = 'table-row';
      chevron.style.transform   = 'rotate(180deg)';
      _openSheetRow             = sheetId;
      await _loadSheetDetail(sheetId, sheetDate, contentEl);
    }
  }

  async function _loadSheetDetail(sheetId, sheetDate, container) {
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    try {
      const res  = await Auth.fetch(`/api/v1/jobs/?daily_sheet=${sheetId}&page_size=200`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      // Get sheet totals
      const sheetRes = await Auth.fetch(`/api/v1/finance/sheets/${sheetId}/`);
      const sheet    = sheetRes.ok ? await sheetRes.json() : null;

      if (!jobs.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:24px;color:var(--text-3);font-size:13px;">
            No jobs recorded for this day.
          </div>`;
        return;
      }

      container.innerHTML = `
        <!-- Jobs table -->
        <div style="overflow-x:auto;padding:0 20px;margin-bottom:16px;margin-left:-18px;margin-right:-14px;">
          <table style="min-width:900px;width:100%;border-collapse:collapse;font-size:13px;">
            <thead>
              <tr style="border-bottom:1px solid var(--border);">
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Time</th>
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Job Ref</th>
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Status</th>
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Channel</th>
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Attendant</th>
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Cashier</th>
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Due</th>
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Given</th>
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Change</th>
                <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;white-space:nowrap;">Total</th>
              </tr>
            </thead>
            <tbody>
              ${jobs.map(j => {
                const time = j.created_at
                  ? new Date(j.created_at).toLocaleTimeString('en-GH', {
                      hour:'2-digit', minute:'2-digit'
                    })
                  : '—';
                return `
                  <tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-3);">${time}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:11px;">${_esc(j.job_number || '#' + j.id)}</td>
                    <td style="padding:8px 12px;">${_statusBadge(j.status)}</td>
                    <td style="padding:8px 12px;font-size:12px;">
                      ${j.payment_method
                        ? `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;padding:2px 7px;border-radius:4px;background:var(--border);color:var(--text-2);font-weight:700;">${j.payment_method}</span>`
                        : '<span style="color:var(--text-3);">—</span>'}
                    </td>
                    <td style="padding:8px 12px;font-size:12px;color:var(--text-2);">${_esc(j.intake_by_name || '—')}</td>
                    <td style="padding:8px 12px;font-size:12px;color:var(--text-2);">${_esc(j.confirmed_by_name || '—')}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:12px;">${j.estimated_cost != null ? _fmt(j.estimated_cost) : '—'}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:12px;">${j.cash_tendered != null ? _fmt(j.cash_tendered) : '—'}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:12px;">${j.change_given != null ? _fmt(j.change_given) : '—'}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;">${j.amount_paid != null ? _fmt(j.amount_paid) : '—'}</td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>

        <!-- Day summary strip -->
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:14px 20px;margin:0 20px;
          display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;">
          <div style="display:flex;align-items:center;gap:24px;flex-wrap:wrap;">
            <div>
              <span style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;">Cash</span>
              <div style="font-size:14px;font-weight:700;color:var(--text);
                font-family:'JetBrains Mono',monospace;">
                ${sheet ? _fmt(sheet.total_cash) : '—'}
              </div>
            </div>
            <div>
              <span style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;">MoMo</span>
              <div style="font-size:14px;font-weight:700;color:var(--text);
                font-family:'JetBrains Mono',monospace;">
                ${sheet ? _fmt(sheet.total_momo) : '—'}
              </div>
            </div>
            <div>
              <span style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;">POS</span>
              <div style="font-size:14px;font-weight:700;color:var(--text);
                font-family:'JetBrains Mono',monospace;">
                ${sheet ? _fmt(sheet.total_pos) : '—'}
              </div>
            </div>
            <div style="padding-left:16px;border-left:1px solid var(--border);">
              <span style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;">Total</span>
              <div style="font-size:16px;font-weight:800;color:var(--text);
                font-family:'Outfit',sans-serif;">
                ${sheet
                  ? _fmt(parseFloat(sheet.total_cash||0) + parseFloat(sheet.total_momo||0) + parseFloat(sheet.total_pos||0))
                  : '—'}
              </div>
            </div>
          </div>

          <!-- Download PDF button -->
          ${sheet && sheet.status !== 'OPEN' ? `
            <button onclick="Dashboard.initiateSheetDownload(${sheetId}, '${sheetDate}')"
              style="display:inline-flex;align-items:center;gap:7px;padding:8px 16px;
                     background:var(--ink, #0f0f0f);color:#fff;border:none;
                     border-radius:var(--radius-sm);font-size:12px;font-weight:700;
                     cursor:pointer;font-family:'Outfit',sans-serif;
                     transition:opacity 0.15s;"
              onmouseover="this.style.opacity='0.85'"
              onmouseout="this.style.opacity='1'">
              <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="2">
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
              </svg>
              Download PDF
            </button>` : ''}
        </div>`;

    } catch {
      container.innerHTML = `
        <div class="loading-cell" style="color:var(--red-text);">
          Could not load sheet details.
        </div>`;
    }
  }

// ── EOD / Close Sheet ─────────────────────────────────────────
  let _eodSheetId = null;
  let _eodData    = null;

  async function closeSheet(sheetId) {
    _eodSheetId = sheetId;
    _eodData    = null;

    // Reset modal state
    document.getElementById('eod-loading').style.display  = 'flex';
    document.getElementById('eod-content').style.display  = 'none';
    document.getElementById('eod-footer').style.display   = 'none';
    document.getElementById('eod-ack-checkbox').checked   = false;
    document.getElementById('eod-confirm-btn').disabled   = true;
    document.getElementById('eod-notes').value            = '';

    document.getElementById('eod-overlay').classList.add('open');

    try {
      const res = await Auth.fetch(`/api/v1/finance/sheets/${sheetId}/eod-summary/`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Could not load EOD summary.', 'error');
        closeEOD();
        return;
      }
      _eodData = await res.json();
      _renderEOD(_eodData);
    } catch {
      _toast('Network error loading EOD summary.', 'error');
      closeEOD();
    }
  }

  function closeEOD() {
    document.getElementById('eod-overlay').classList.remove('open');
    _eodSheetId = null;
    _eodData    = null;
  }

  function toggleEODConfirm() {
    const allSignedOff = !document.getElementById('eod-cashier-blocker') ||
      document.getElementById('eod-cashier-blocker').style.display === 'none';
    _updateEODIntegrity(allSignedOff);
  }

  function _validateFloatInput(input) {
    const val = parseFloat(input.value);
    const valid = val >= 20 && val <= 100 && val % 5 === 0;
    input.style.borderColor = valid ? 'var(--border)' : 'var(--red-border)';
    input.style.background  = valid ? 'var(--panel)'  : 'var(--red-bg)';
    toggleEODConfirm();
  }

  function _validateAllFloats() {
    const inputs = document.querySelectorAll('[id^="float-input-"]');
    if (!inputs.length) return true; // no cashiers — no float needed
    for (const input of inputs) {
      const val = parseFloat(input.value || 0);
      if (!val || val < 20 || val > 100 || val % 5 !== 0) return false;
    }
    return true;
  }

  function _getFloatData() {
    const inputs  = document.querySelectorAll('[id^="float-input-"]');
    const floats  = [];
    inputs.forEach(input => {
      const cashierId = input.id.replace('float-input-', '');
      floats.push({
        cashier_id    : parseInt(cashierId),
        opening_float : parseFloat(input.value),
      });
    });
    return floats;
  }

  function _fmt(n) {
    return `GHS ${parseFloat(n || 0).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
  }

  function _renderEOD(d) {
    const meta = d.meta;
    const rev  = d.revenue;
    const jobs = d.jobs;
    const fmt  = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH', {minimumFractionDigits:2})}`;

    // ── Header ────────────────────────────────────────────────────
    const dateStr = new Date(meta.date).toLocaleDateString('en-GH', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
    });
    document.getElementById('eod-subtitle').textContent = `${dateStr} · ${meta.branch}`;
    document.getElementById('eod-ack-branch').textContent = meta.branch;

    // Set BM name in acknowledgement
    const user = Auth.getUser();
    const bmName = user?.full_name || user?.first_name || 'Branch Manager';
    const bmEl = document.getElementById('eod-ack-bm-name');
    if (bmEl) bmEl.textContent = bmName;

    // ── 1. Revenue ────────────────────────────────────────────────
    // Use live totals for open sheet
    const liveCash  = parseFloat(rev.cash  || 0);
    const liveMomo  = parseFloat(rev.momo  || 0);
    const livePos   = parseFloat(rev.pos   || 0);
    const liveTotal = liveCash + liveMomo + livePos;

    document.getElementById('eod-cash').textContent          = fmt(liveCash);
    document.getElementById('eod-momo').textContent          = fmt(liveMomo);
    document.getElementById('eod-pos').textContent           = fmt(livePos);
    document.getElementById('eod-total').textContent         = fmt(liveTotal);
    document.getElementById('eod-credit-issued').textContent  = fmt(rev.credit_issued);
    document.getElementById('eod-credit-settled').textContent = fmt(rev.credit_settled || 0);
    document.getElementById('eod-petty-cash-out').textContent = fmt(rev.petty_cash_out);
    document.getElementById('eod-net-cash').textContent       = fmt(rev.net_cash_in_till);

    // ── 2. Jobs Grid ──────────────────────────────────────────────
    const jobsGrid = document.getElementById('eod-jobs-grid');
    if (jobsGrid) {
      const jobCards = [
        { label: 'Total Jobs',   value: jobs.total,         color: 'blue' },
        { label: 'Completed',    value: jobs.completed,     color: 'green' },
        { label: 'Pending',      value: jobs.pending_payment, color: 'amber' },
        { label: 'Cancelled',    value: jobs.cancelled,     color: 'red' },
      ];
      jobsGrid.innerHTML = jobCards.map(c => `
        <div style="padding:14px 16px;background:var(--${c.color}-bg);
          border:1px solid var(--${c.color}-border);border-radius:var(--radius-sm);
          text-align:center;">
          <div style="font-family:'JetBrains Mono',monospace;font-size:24px;
            font-weight:800;color:var(--${c.color}-text);">${c.value}</div>
          <div style="font-size:11px;font-weight:600;color:var(--${c.color}-text);
            margin-top:4px;opacity:0.8;">${c.label}</div>
        </div>
      `).join('');
    }

    // ── 3. Cashier Sign-Off ───────────────────────────────────────
    const cashierEl      = document.getElementById('eod-cashier-activity');
    const floatWarn      = document.getElementById('eod-float-warning');
    const cashierBlocker = document.getElementById('eod-cashier-blocker');
    const signoffStatus  = document.getElementById('eod-cashier-signoff-status');

    floatWarn.style.display = d.float_opened ? 'none' : 'block';

    let allSignedOff = true;

    if (d.cashier_activity && d.cashier_activity.length) {
      cashierEl.innerHTML = d.cashier_activity.map(c => {
        if (!c.is_signed_off) allSignedOff = false;

        const variance      = parseFloat(c.variance || 0);
        const varDisplay    = variance >= 0 ? `+${fmt(variance)}` : fmt(variance);
        const varColor      = variance >= 0 ? 'var(--green-text)' : 'var(--red-text)';
        const signoffBadge  = c.is_signed_off
          ? `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;
               border-radius:20px;font-size:11px;font-weight:700;
               background:var(--green-bg);color:var(--green-text);
               border:1px solid var(--green-border);">✓ Signed off</span>`
          : `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;
               border-radius:20px;font-size:11px;font-weight:700;
               background:var(--red-bg);color:var(--red-text);
               border:1px solid var(--red-border);">⚠ Not signed off</span>`;

        const methods = ['CASH','MOMO','POS'].map(m => {
          const info = c.method_breakdown?.[m];
          if (!info) return '';
          return `<div style="padding:8px 12px;border-radius:var(--radius-sm);
            border:1px solid var(--border);background:var(--panel);min-width:90px;">
            <div style="font-size:9px;font-weight:700;text-transform:uppercase;
              letter-spacing:0.4px;color:var(--text-3);margin-bottom:3px;">${m}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
              font-weight:700;color:var(--text);">${fmt(info.total)}</div>
            <div style="font-size:10px;color:var(--text-3);">${info.count} txn</div>
          </div>`;
        }).join('');

        return `
          <div style="border:1px solid var(--border);border-radius:var(--radius);
            margin-bottom:12px;overflow:hidden;
            ${!c.is_signed_off ? 'border-color:var(--red-border);' : ''}">

            <!-- Cashier header -->
            <div style="display:flex;align-items:center;justify-content:space-between;
              padding:12px 16px;background:var(--bg);border-bottom:1px solid var(--border);">
              <div>
                <div style="font-size:14px;font-weight:700;color:var(--text);">
                  ${_esc(c.cashier_name)}
                </div>
                <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
                  ${c.transaction_count} transactions
                </div>
              </div>
              <div style="display:flex;align-items:center;gap:10px;">
                ${signoffBadge}
                <div style="font-family:'JetBrains Mono',monospace;font-size:16px;
                  font-weight:800;color:var(--green-text);">${fmt(c.total_collected)}</div>
              </div>
            </div>

            <!-- Float + Variance row -->
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;
              gap:0;border-bottom:1px solid var(--border);">
              ${[
                ['Opening Float', fmt(c.opening_float), 'var(--text)'],
                ['Expected Cash', fmt(c.expected_cash), 'var(--text)'],
                ['Closing Count', fmt(c.closing_cash),  'var(--text)'],
                ['Variance',      varDisplay,            varColor],
              ].map(([label, val, color]) => `
                <div style="padding:10px 14px;border-right:1px solid var(--border);">
                  <div style="font-size:10px;font-weight:700;text-transform:uppercase;
                    letter-spacing:0.4px;color:var(--text-3);margin-bottom:3px;">${label}</div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                    font-weight:700;color:${color};">${val}</div>
                </div>
              `).join('')}
            </div>

            <!-- Method breakdown -->
            <div style="padding:12px 16px;display:flex;gap:10px;flex-wrap:wrap;">
              ${methods || '<span style="font-size:12px;color:var(--text-3);">No transactions recorded.</span>'}
            </div>
          </div>`;
      }).join('');
    } else {
      cashierEl.innerHTML = `<div class="eod-empty-note">No cashier activity today.</div>`;
      allSignedOff = true; // no cashier = no block
    }

    // Show/hide cashier blocker
    cashierBlocker.style.display = allSignedOff ? 'none' : 'block';
    if (signoffStatus) {
      signoffStatus.innerHTML = allSignedOff
        ? `<span style="font-size:11px;font-weight:700;color:var(--green-text);">✓ All signed off</span>`
        : `<span style="font-size:11px;font-weight:700;color:var(--red-text);">⚠ Sign-off pending</span>`;
    }

    // ── 4. Pending Payments ───────────────────────────────────────
    const pendingBadge = document.getElementById('eod-pending-badge');
    if (jobs.pending_payment > 0) {
      pendingBadge.textContent     = jobs.pending_payment;
      pendingBadge.style.display   = 'inline-flex';
    } else {
      pendingBadge.style.display   = 'none';
    }

    document.getElementById('eod-pending-note').style.display =
      jobs.pending_list?.length ? 'block' : 'none';

    document.getElementById('eod-pending-list').innerHTML =
      jobs.pending_list?.length
        ? _jobMiniTable(jobs.pending_list)
        : '<div class="eod-empty-note">No pending payments. ✓</div>';

    const untouchedSubtitle = document.getElementById('eod-untouched-subtitle');
    const untouchedNote     = document.getElementById('eod-untouched-note');
    untouchedSubtitle.style.display = jobs.untouched_list?.length ? 'block' : 'none';
    untouchedNote.style.display     = jobs.untouched_list?.length ? 'block' : 'none';
    document.getElementById('eod-untouched-list').innerHTML =
      jobs.untouched_list?.length ? _jobMiniTable(jobs.untouched_list) : '';

    // ── 5. Petty Cash ─────────────────────────────────────────────
    const pettyList = document.getElementById('eod-petty-list');
    if (d.petty_cash?.length) {
      pettyList.innerHTML = `
        <table class="eod-table">
          <thead>
            <tr><th>Item / Purpose</th><th>Recorded By</th><th>Time</th><th>Amount</th></tr>
          </thead>
          <tbody>
            ${d.petty_cash.map(p => `
              <tr>
                <td>${_esc(p.reason || p.purpose || '—')}</td>
                <td>${_esc(p.recorded_by_name || '—')}</td>
                <td style="font-size:11px;color:var(--text-3);">
                  ${p.created_at ? new Date(p.created_at).toLocaleTimeString('en-GH',{hour:'2-digit',minute:'2-digit'}) : '—'}
                </td>
                <td class="mono">${fmt(p.amount)}</td>
              </tr>`).join('')}
          </tbody>
        </table>`;
    } else {
      pettyList.innerHTML = '<div class="eod-empty-note">No petty cash disbursements today. ✓</div>';
    }

    // ── 6. Credit Sales ───────────────────────────────────────────
    const creditList = document.getElementById('eod-credit-list');
    if (d.credit_sales?.length) {
      creditList.innerHTML = `
        <table class="eod-table">
          <thead>
            <tr><th>Job</th><th>Customer</th><th>Amount</th></tr>
          </thead>
          <tbody>
            ${d.credit_sales.map(c => `
              <tr>
                <td>${_esc(c.title)}</td>
                <td>${_esc(c.customer_name)}</td>
                <td class="mono">${fmt(c.estimated_cost)}</td>
              </tr>`).join('')}
          </tbody>
        </table>`;
    } else {
      creditList.innerHTML = '<div class="eod-empty-note">No credit sales today. ✓</div>';
    }

    // ── 8. Tomorrow's Float ───────────────────────────────────────
    const floatContainer = document.getElementById('eod-cashier-floats');
    if (floatContainer) {
      // Use cashier_activity if available, else branch_cashiers
      const cashiers = (d.cashier_activity?.length)
        ? d.cashier_activity
        : (d.branch_cashiers || []);

      if (cashiers.length) {
        // Check if tomorrow is Sunday — skip to Monday
        const tomorrow = new Date();
        tomorrow.setDate(tomorrow.getDate() + 1);
        const isSunday = tomorrow.getDay() === 0;
        const floatDate = isSunday
          ? (() => { const m = new Date(tomorrow); m.setDate(m.getDate()+1); return m; })()
          : tomorrow;
        const floatDateStr = floatDate.toLocaleDateString('en-GH',{weekday:'long',month:'short',day:'numeric'});

        floatContainer.innerHTML = `
          <div style="font-size:11px;color:var(--text-3);margin-bottom:10px;">
            Float for <strong>${floatDateStr}</strong>
            ${isSunday ? '(Monday — skipping Sunday)' : ''}
          </div>
          ${cashiers.map(c => `
            <div style="display:flex;align-items:center;justify-content:space-between;
              padding:12px 14px;background:var(--bg);border:1px solid var(--border);
              border-radius:var(--radius-sm);margin-bottom:8px;">
              <div>
                <div style="font-size:13px;font-weight:700;color:var(--text);">
                  ${_esc(c.cashier_name)}
                </div>
                <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
                  Opening float for tomorrow
                </div>
              </div>
              <div style="display:flex;align-items:center;gap:8px;">
                <span style="font-size:12px;color:var(--text-3);font-weight:600;">GHS</span>
                <input type="number"
                  id="float-input-${c.cashier_id}"
                  min="20" max="100" step="5" value="50"
                  onchange="Dashboard._validateFloatInput(this)"
                  oninput="Dashboard._validateFloatInput(this)"
                  style="width:90px;padding:8px 10px;border:1.5px solid var(--border);
                    border-radius:var(--radius-sm);background:var(--panel);
                    color:var(--text);font-size:15px;font-weight:700;
                    font-family:'JetBrains Mono',monospace;text-align:right;outline:none;">
              </div>
            </div>`).join('')}`;
      } else {
        floatContainer.innerHTML = `
          <div class="eod-info-note amber">
            No cashiers found for this branch. Float staging skipped.
          </div>`;
      }
    }

    // ── Hide loading, show content ────────────────────────────────
    document.getElementById('eod-loading').style.display = 'none';
    document.getElementById('eod-content').style.display = 'block';

    // ── Show footer ───────────────────────────────────────────────
    document.getElementById('eod-footer').style.display = 'flex';

    // ── Update integrity status in footer ─────────────────────────
    _updateEODIntegrity(allSignedOff);
  }

  function _updateEODIntegrity(allSignedOff) {
    const floatsValid    = _validateAllFloats();
    const ackChecked     = document.getElementById('eod-ack-checkbox')?.checked;
    const confirmBtn     = document.getElementById('eod-confirm-btn');
    const footerStatus   = document.getElementById('eod-footer-status');
    const cashierBlocker = document.getElementById('eod-cashier-blocker');
    const floatBlocker   = document.getElementById('eod-float-blocker');

    cashierBlocker.style.display = allSignedOff  ? 'none' : 'block';
    floatBlocker.style.display   = floatsValid   ? 'none' : 'block';

    const canClose = allSignedOff && floatsValid && ackChecked;
    confirmBtn.disabled = !canClose;

    if (footerStatus) {
      const issues = [];
      if (!allSignedOff) issues.push('cashier sign-off pending');
      if (!floatsValid)  issues.push('tomorrow\'s float not set');
      if (!ackChecked)   issues.push('acknowledgement required');
      footerStatus.textContent = issues.length
        ? `⚠ Blocked: ${issues.join(' · ')}`
        : '✓ Ready to close';
      footerStatus.style.color = issues.length ? 'var(--red-text)' : 'var(--green-text)';
    }
  }

  function _checkItem(type, text, sub) {
    const icons = { ok: '✓', warn: '⚠', alert: '✕' };
    return `
      <div class="eod-check-item ${type}">
        <span class="eod-check-icon">${icons[type]}</span>
        <div>
          <div class="eod-check-text">${text}</div>
          ${sub ? `<div class="eod-check-sub">${sub}</div>` : ''}
        </div>
      </div>`;
  }

  function _jobMiniTable(list) {
    return `
      <table class="eod-table">
        <thead>
          <tr>
            <th>Job Ref</th>
            <th>Title</th>
            <th>Attendant</th>
            <th>Created</th>
            <th style="text-align:right;">Amount</th>
          </tr>
        </thead>
        <tbody>
          ${list.map(j => `
            <tr>
              <td class="mono">${j.job_number}</td>
              <td>${j.title || '—'}</td>
              <td>${j.intake_by_name}</td>
              <td>${j.created_at ? new Date(j.created_at).toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' }) : '—'}</td>
              <td class="mono" style="text-align:right;">${_fmt(j.estimated_cost)}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  }

  async function confirmCloseSheet() {
    if (!_eodSheetId) return;

    const notes  = document.getElementById('eod-notes')?.value.trim() || '';
    const btn    = document.getElementById('eod-confirm-btn');
    btn.disabled = true;
    btn.innerHTML = '<span style="opacity:0.6">Closing…</span>';

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/sheets/${_eodSheetId}/close/`,
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ notes, floats: _getFloatData() }),
        }
      );
      if (res.ok) {
        _toast('Day sheet closed successfully.', 'success');
        closeEOD();
        document.getElementById('pane-finance').dataset.loaded = '';
        _loadFinancePane();
      } else {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Could not close sheet.', 'error');
        btn.disabled = false;
        btn.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg> Confirm &amp; Close Sheet';
      }
    } catch {
      _toast('Network error.', 'error');
      btn.disabled = false;
    }
  }

  // ── Inbox pane ─────────────────────────────────────────────
// ── Inbox pane ─────────────────────────────────────────────
  let _inboxChannel  = 'WHATSAPP';
  let _inboxConvos   = [];
  let _activeConvoId = null;

  async function loadInboxTab() {
    inboxLoaded = true;
    const pane = document.getElementById('pane-inbox');
    if (!pane) return;

    // Render shell
    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Inbox</span>
      </div>
      <div class="reports-tabs" id="inbox-channel-tabs">
        <button class="reports-tab active" data-channel="WHATSAPP" onclick="Dashboard.switchInboxChannel('WHATSAPP')">
          WhatsApp <span class="inbox-badge" id="inbox-badge-WHATSAPP" style="display:none;"></span>
        </button>
        <button class="reports-tab" data-channel="EMAIL" onclick="Dashboard.switchInboxChannel('EMAIL')">
          Email <span class="inbox-badge" id="inbox-badge-EMAIL" style="display:none;"></span>
        </button>
        <button class="reports-tab" data-channel="PHONE" onclick="Dashboard.switchInboxChannel('PHONE')">
          Phone <span class="inbox-badge" id="inbox-badge-PHONE" style="display:none;"></span>
        </button>
      </div>
      <div id="inbox-body" style="display:flex;gap:0;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;min-height:480px;">
        <div id="inbox-list" style="width:320px;flex-shrink:0;border-right:1px solid var(--border);overflow-y:auto;"></div>
        <div id="inbox-thread" style="flex:1;display:flex;flex-direction:column;">
          <div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--text-3);font-size:13px;">
            Select a conversation
          </div>
        </div>
      </div>`;

    await _fetchAndRenderInbox();
  }

  async function _fetchAndRenderInbox() {
    const listEl = document.getElementById('inbox-list');
    if (!listEl) return;
    listEl.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-3);font-size:13px;"><span class="spin"></span></div>';

    try {
      const res = await Auth.fetch('/api/v1/communications/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      _inboxConvos = Array.isArray(data) ? data : (data.results || []);

      // Update badges
      ['WHATSAPP', 'EMAIL', 'PHONE'].forEach(ch => {
        const unread = _inboxConvos
          .filter(c => (c.channel || '').toUpperCase() === ch)
          .reduce((sum, c) => sum + (c.unread_count || 0), 0);
        const badge = document.getElementById(`inbox-badge-${ch}`);
        if (badge) {
          badge.textContent   = unread;
          badge.style.display = unread > 0 ? 'inline-flex' : 'none';
        }
      });

      _renderInboxList();
    } catch {
      listEl.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-3);">Could not load inbox.</div>';
    }
  }

  function _renderInboxList() {
    const listEl = document.getElementById('inbox-list');
    if (!listEl) return;

    const filtered = _inboxConvos.filter(
      c => (c.channel || '').toUpperCase() === _inboxChannel
    );

    if (!filtered.length) {
      listEl.innerHTML = `<div style="padding:32px 16px;text-align:center;color:var(--text-3);font-size:13px;">No ${_inboxChannel.toLowerCase()} conversations.</div>`;
      return;
    }

    const AV_COLORS = ['#22c98a','#e8294a','#4a90e8','#9b59b6','#e8c84a'];
    const _avColor  = name => {
      let h = 0;
      for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
      return AV_COLORS[Math.abs(h) % AV_COLORS.length];
    };

    listEl.innerHTML = filtered.map(c => {
      const name      = c.display_name || c.customer_name || 'Unknown';
      const ini       = _initials(name);
      const avColor   = _avColor(name);
      const time      = _timeAgo(c.last_message_at || c.updated_at || c.created_at);
      const preview   = _esc(_truncate(c.last_message_preview || c.last_message || 'No messages yet', 55));
      const hasUnread = (c.unread_count || 0) > 0;
      const isActive  = c.id === _activeConvoId;

      return `
        <div onclick="Dashboard.openConvo(${c.id})"
          style="
            display:flex;align-items:center;gap:10px;padding:12px 14px;
            border-bottom:1px solid var(--border);cursor:pointer;
            background:${isActive ? 'var(--bg)' : 'var(--panel)'};
            transition:background 0.12s;
          "
          onmouseover="this.style.background='var(--bg)'"
          onmouseout="this.style.background='${isActive ? 'var(--bg)' : 'var(--panel)'}'">
          <div style="
            width:36px;height:36px;border-radius:50%;flex-shrink:0;
            background:${avColor};color:${avColor === '#e8c84a' ? '#111' : '#fff'};
            display:flex;align-items:center;justify-content:center;
            font-family:'Syne',sans-serif;font-size:12px;font-weight:700;
          ">${ini}</div>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:2px;">
              <span style="font-size:13px;font-weight:${hasUnread ? '700' : '500'};color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px;">
                ${_esc(name)}
              </span>
              <span style="font-size:10.5px;color:var(--text-3);font-family:'JetBrains Mono',monospace;flex-shrink:0;margin-left:6px;">${time}</span>
            </div>
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <span style="font-size:12px;color:var(--text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:200px;">${preview}</span>
              ${hasUnread ? `<span style="width:6px;height:6px;border-radius:50%;background:var(--red-text);flex-shrink:0;margin-left:6px;"></span>` : ''}
            </div>
          </div>
        </div>`;
    }).join('');
  }

  async function switchInboxChannel(channel) {
    _inboxChannel  = channel;
    _activeConvoId = null;

    document.querySelectorAll('#inbox-channel-tabs .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.channel === channel);
    });

    _renderInboxList();

    // Reset thread
    const thread = document.getElementById('inbox-thread');
    if (thread) thread.innerHTML = `
      <div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--text-3);font-size:13px;">
        Select a conversation
      </div>`;
  }

  async function openConvo(convoId) {
    _activeConvoId = convoId;
    _renderInboxList(); // re-render to highlight active

    const thread = document.getElementById('inbox-thread');
    if (!thread) return;
    thread.innerHTML = '<div style="flex:1;display:flex;align-items:center;justify-content:center;"><span class="spin"></span></div>';

    try {
      const res = await Auth.fetch(`/api/v1/communications/${convoId}/`);
      if (!res.ok) throw new Error();
      const convo = await res.json();
      const msgs  = convo.messages || [];
      const name  = convo.display_name || convo.customer_name || 'Unknown';

      thread.innerHTML = `
        <div style="padding:14px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">
          <div>
            <div style="font-size:14px;font-weight:700;color:var(--text);">${_esc(name)}</div>
            <div style="font-size:11px;color:var(--text-3);margin-top:1px;">${_esc(convo.channel || '')} · ${convo.contact_value || ''}</div>
          </div>
        </div>
        <div id="inbox-messages" style="flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;">
          ${msgs.length ? msgs.map(m => _renderMessage(m)).join('') : '<div style="text-align:center;color:var(--text-3);font-size:13px;padding:32px 0;">No messages yet.</div>'}
        </div>
        <div style="padding:12px 14px;border-top:1px solid var(--border);display:flex;gap:8px;">
          <input id="inbox-reply-input" type="text" placeholder="Type a reply…"
            style="flex:1;padding:8px 12px;border:1px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;outline:none;"
            onkeydown="if(event.key==='Enter') Dashboard.sendReply(${convoId})"/>
          <button onclick="Dashboard.sendReply(${convoId})"
            style="padding:8px 16px;background:var(--text);color:#fff;border:none;border-radius:var(--radius-sm);font-size:13px;font-weight:700;cursor:pointer;">
            Send
          </button>
        </div>`;

      // Scroll to bottom
      const msgsEl = document.getElementById('inbox-messages');
      if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;

    } catch {
      thread.innerHTML = '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--text-3);font-size:13px;">Could not load conversation.</div>';
    }
  }

  function _renderMessage(m) {
    const isOutbound = m.direction === 'OUTBOUND' || m.is_outbound;
    const time = m.created_at
      ? new Date(m.created_at).toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' })
      : '';
    return `
      <div style="display:flex;flex-direction:column;align-items:${isOutbound ? 'flex-end' : 'flex-start'};">
        <div style="
          max-width:70%;padding:9px 13px;border-radius:${isOutbound ? '14px 14px 4px 14px' : '14px 14px 14px 4px'};
          background:${isOutbound ? 'var(--text)' : 'var(--bg)'};
          color:${isOutbound ? '#fff' : 'var(--text)'};
          border:${isOutbound ? 'none' : '1px solid var(--border)'};
          font-size:13px;line-height:1.5;
        ">${_esc(m.body || m.content || '')}</div>
        <span style="font-size:10px;color:var(--text-3);margin-top:3px;">${time}</span>
      </div>`;
  }

  async function sendReply(convoId) {
    const input = document.getElementById('inbox-reply-input');
    const body  = input?.value.trim();
    if (!body) return;

    input.value    = '';
    input.disabled = true;

    try {
      const res = await Auth.fetch(`/api/v1/communications/${convoId}/reply/`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ body }),
      });
      if (res.ok) {
        await openConvo(convoId); // refresh thread
      } else {
        _toast('Could not send reply.', 'error');
        input.disabled = false;
      }
    } catch {
      _toast('Network error.', 'error');
      input.disabled = false;
    }
  }
  // ── Services pane ──────────────────────────────────────────
  async function _loadServicesAndCustomers() {
    try {
      const [svcRes, custRes] = await Promise.all([
        Auth.fetch('/api/v1/jobs/services/'),
        Auth.fetch('/api/v1/customers/'),
      ]);

      if (svcRes.ok) {
        const data = await svcRes.json();
        services = Array.isArray(data) ? data : (data.results || []);
        _set('meta-services', services.length);
        _set('meta-services-count', `${services.length} services`);

        // Pass to NJ controller
        if (typeof State !== 'undefined') State.services = services;
      }

      if (custRes.ok) {
        const data = await custRes.json();
        customers = Array.isArray(data) ? data : (data.results || []);
        if (typeof State !== 'undefined') State.customers = customers;
      }

    } catch { /* silent */ }
  }

  async function loadServicesTab() {
    if (svcLoaded) return;
    svcLoaded = true;

    const grid = document.getElementById('services-grid');
    if (!grid) return;

    if (!services.length) {
      grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-3);">No services available.</div>`;
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
               </div>`
          }
          <div class="service-card-body">
            <div class="service-card-name">${_esc(s.name)}</div>
            <div class="service-card-price">${s.base_price != null ? 'GHS ' + Number(s.base_price).toFixed(2) : '—'}</div>
            <div class="service-card-desc">${_esc(s.description || '')}</div>
          </div>
        </div>`).join('');
  }

  // ── Outsource modal ────────────────────────────────────────
  async function openOutsourceModal() {
    document.getElementById('outsource-modal').classList.add('open');

    // Load pending jobs into select
    try {
      const res  = await Auth.fetch('/api/v1/jobs/?status=PENDING_PAYMENT&page_size=50');
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);
      const sel  = document.getElementById('outsource-job-select');
      if (sel) {
        sel.innerHTML = '<option value="">Select job…</option>' +
          jobs.map(j => `<option value="${j.id}">${_esc(j.job_number)} — ${_esc(j.title)}</option>`).join('');
      }
    } catch { /* silent */ }

    // Load branches into select
    try {
      const res     = await Auth.fetch('/api/v1/organization/branches/');
      const data    = await res.json();
      const branches = Array.isArray(data) ? data : (data.results || []);
      const sel     = document.getElementById('outsource-branch-select');
      if (sel) {
        sel.innerHTML = '<option value="">Select branch…</option>' +
          branches.map(b => `<option value="${b.id}">${_esc(b.name)}</option>`).join('');
      }
    } catch { /* silent */ }
  }

  async function confirmOutsource() {
    const jobId    = document.getElementById('outsource-job-select')?.value;
    const branchId = document.getElementById('outsource-branch-select')?.value;
    const reason   = document.getElementById('outsource-reason')?.value.trim();

    if (!jobId)    { _toast('Please select a job.', 'error');    return; }
    if (!branchId) { _toast('Please select a branch.', 'error'); return; }

    try {
      const res = await Auth.fetch(`/api/v1/jobs/${jobId}/route/confirm/`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ branch_id: parseInt(branchId), notes: reason }),
      });

      if (res.ok) {
        _toast('Job outsourced successfully.', 'success');
        document.getElementById('outsource-modal').classList.remove('open');
        jobsLoaded = false;
        await Promise.all([loadStats(), loadRecentJobs()]);
      } else {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Could not outsource job.', 'error');
      }
    } catch {
      _toast('Network error.', 'error');
    }
  }

  // ── NJ controller integration ──────────────────────────────
  // Called by NJ after job creation to refresh dashboard
  function onJobCreated() {
    jobsLoaded = false;
    Promise.all([loadStats(), loadRecentJobs()]);
  }

  // ── Helpers ────────────────────────────────────────────────
  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function _esc(str) {
    return String(str ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _truncate(str, len) {
    return str.length > len ? str.slice(0, len) + '…' : str;
  }

  function _initials(name) {
    return String(name).split(' ').slice(0, 2)
      .map(w => w[0]?.toUpperCase() || '').join('') || '?';
  }

  function _setDate() {
    const now = new Date();
    _set('meta-date', now.toLocaleDateString('en-GB', {
      day: 'numeric', month: 'short', year: 'numeric',
    }));
  }

  function _formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('en-GB', {
      day: 'numeric', month: 'short', year: 'numeric',
    });
  }

  function _timeAgo(iso) {
    if (!iso) return '—';
    const diff = Date.now() - new Date(iso).getTime();
    if (diff < 60000)    return 'just now';
    if (diff < 3600000)  return `${Math.floor(diff / 60000)}m`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h`;
    return _formatDate(iso);
  }

  function _fmt(val) {
    const n = parseFloat(val || 0);
    return `GHS ${n.toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
  }

  function _statusBadge(status) {
    const map = {
      DRAFT           : 'badge-draft',
      PENDING_PAYMENT : 'badge-pending',
      PAID            : 'badge-pending',
      IN_PROGRESS     : 'badge-progress',
      CONFIRMED       : 'badge-progress',
      READY           : 'badge-ready',
      COMPLETE        : 'badge-done',
      CANCELLED       : 'badge-cancelled',
      HALTED          : 'badge-halted',
    };
    const labels = {
      DRAFT           : 'Draft',
      PENDING_PAYMENT : 'Pending Payment',
      PAID            : 'Paid',
      IN_PROGRESS     : 'In Progress',
      CONFIRMED       : 'Confirmed',
      READY           : 'Ready',
      COMPLETE        : 'Complete',
      CANCELLED       : 'Cancelled',
      HALTED          : 'Halted',
    };
    return `<span class="badge ${map[status] || 'badge-draft'}">${labels[status] || status || '—'}</span>`;
  }

  function _typeBadge(type) {
    const map = {
      INSTANT    : 'badge-instant',
      PRODUCTION : 'badge-production',
      DESIGN     : 'badge-design',
    };
    return `<span class="badge ${map[type] || 'badge-draft'}">${_esc(type || '—')}</span>`;
  }

  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el     = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

// ── Inventory pane ────────────────────────────────────────────────────
  let _inventoryTab = 'consumables';

  async function _loadInventoryPane() {
    const pane = document.getElementById('pane-inventory');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head" style="margin-bottom:0;">
        <span class="section-title">Inventory</span>
      </div>
      <div style="display:flex;gap:0;border-bottom:2px solid var(--border);margin-bottom:20px;">
        ${[['consumables','Consumables'],['equipment','Equipment'],['movements','Movements'],['waste','Waste Incidents']].map(([t,l]) => `
          <button class="reports-tab ${_inventoryTab===t?'active':''}" data-tab="${t}"
            onclick="Dashboard.switchInventoryTab('${t}')"
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

  // ── Equipment tab ─────────────────────────────────────────
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
          <button onclick="Dashboard._openAddEquipment()"
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
                <th style="padding:10px 14px;font-size:11px;font-weight:700;
                  color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">
                  Asset</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;
                  color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">
                  Equipment</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;
                  color:var(--text-3);text-align:center;text-transform:uppercase;letter-spacing:0.5px;">
                  Qty</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;
                  color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">
                  Condition</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;
                  color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">
                  Last Serviced</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;
                  color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">
                  Next Due</th>
                <th style="padding:10px 14px;font-size:11px;font-weight:700;
                  color:var(--text-3);text-align:left;text-transform:uppercase;letter-spacing:0.5px;">
                  Location</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(eq => `
                <tr onclick="Dashboard._openEquipmentModal(${eq.id})"
                  style="border-bottom:1px solid var(--border);cursor:pointer;transition:background 0.1s;"
                  onmouseover="this.style.background='var(--bg)'"
                  onmouseout="this.style.background=''">
                  <td style="padding:12px 14px;font-size:12px;font-weight:700;
                    color:var(--text-3);font-family:'JetBrains Mono',monospace;">
                    ${eq.asset_code}</td>
                  <td style="padding:12px 14px;">
                    <div style="font-size:13px;font-weight:600;color:var(--text);">
                      ${eq.name}</div>
                    ${eq.manufacturer ? `<div style="font-size:11px;color:var(--text-3);">
                      ${eq.manufacturer}</div>` : ''}
                  </td>
                  <td style="padding:12px 14px;text-align:center;font-size:13px;
                    color:var(--text);">${eq.quantity}</td>
                  <td style="padding:12px 14px;">${conditionBadge(eq.service_status)}</td>
                  <td style="padding:12px 14px;font-size:12px;color:var(--text-2);">
                    ${eq.last_serviced || '—'}</td>
                  <td style="padding:12px 14px;font-size:12px;color:var(--text-2);">
                    ${eq.next_service_due || '—'}</td>
                  <td style="padding:12px 14px;font-size:12px;color:var(--text-2);">
                    ${eq.location || '—'}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`}`;

    } catch {
      container.innerHTML = '<div class="loading-cell">Failed to load equipment.</div>';
    }
  }

  // ── Equipment modal ───────────────────────────────────────
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

      // Create modal overlay
      const overlay = document.createElement('div');
      overlay.id = 'equipment-modal-overlay';
      overlay.style.cssText = `position:fixed;inset:0;background:rgba(0,0,0,0.5);
        z-index:1000;display:flex;align-items:center;justify-content:center;padding:24px;`;
      overlay.onclick = e => { if (e.target === overlay) overlay.remove(); };

      overlay.innerHTML = `
        <div style="background:var(--panel);border-radius:var(--radius);
          width:100%;max-width:720px;max-height:85vh;display:flex;flex-direction:column;
          overflow:hidden;border:1px solid var(--border);">

          <!-- Header -->
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
              <button onclick="Dashboard._printEquipmentQR(${eq.id}, '${eq.asset_code}')"
                style="padding:7px 14px;font-size:12px;font-weight:600;
                  border:1px solid var(--border);border-radius:var(--radius-sm);
                  background:var(--bg);color:var(--text);cursor:pointer;font-family:inherit;">
                🏷 Print QR
              </button>
              <button onclick="Dashboard._openAddMaintenanceLog(${eq.id})"
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

          <!-- Scrollable body -->
          <div style="overflow-y:auto;flex:1;padding:24px;">

            <!-- Details grid -->
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
                    text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">
                    ${label}</div>
                  <div style="font-size:13px;color:var(--text);font-weight:500;">
                    ${value}</div>
                </div>`).join('')}
            </div>

            ${eq.notes ? `
            <div style="padding:12px 14px;background:var(--bg);border-radius:var(--radius-sm);
              border:1px solid var(--border);margin-bottom:24px;">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Notes</div>
              <div style="font-size:13px;color:var(--text-2);">${eq.notes}</div>
            </div>` : ''}

            <!-- Maintenance history -->
            <div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:12px;">
              Maintenance History
              <span style="font-size:11px;font-weight:400;color:var(--text-3);margin-left:6px;">
                ${logs.length} record${logs.length !== 1 ? 's' : ''}</span>
            </div>

            ${!logs.length ? `
              <div style="padding:20px;text-align:center;color:var(--text-3);font-size:13px;
                background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border);">
                No maintenance records yet. Log the first service above.
              </div>` : logs.map(log => `
              <div style="padding:14px;background:var(--bg);border-radius:var(--radius-sm);
                border:1px solid var(--border);margin-bottom:8px;">
                <div style="display:flex;justify-content:space-between;align-items:flex-start;
                  margin-bottom:8px;">
                  <div>
                    <span style="font-size:12px;font-weight:700;color:var(--text);">
                      ${logTypeLabel(log.log_type)}</span>
                    <span style="font-size:11px;color:var(--text-3);margin-left:8px;">
                      ${log.service_date}</span>
                  </div>
                  ${conditionBadge(log.condition_after)}
                </div>
                <div style="font-size:13px;color:var(--text-2);margin-bottom:6px;">
                  ${log.description}</div>
                <div style="display:flex;gap:16px;flex-wrap:wrap;">
                  <span style="font-size:11px;color:var(--text-3);">
                    By: <strong>${log.performed_by}</strong></span>
                  ${log.cost ? `<span style="font-size:11px;color:var(--text-3);">
                    Cost: <strong>GHS ${log.cost}</strong></span>` : ''}
                  ${log.next_due ? `<span style="font-size:11px;color:var(--text-3);">
                    Next due: <strong>${log.next_due}</strong></span>` : ''}
                  <span style="font-size:11px;color:var(--text-3);">
                    Logged by: ${log.logged_by_name}</span>
                </div>
                ${log.parts_replaced ? `<div style="font-size:11px;color:var(--text-3);
                  margin-top:4px;">Parts replaced: ${log.parts_replaced}</div>` : ''}
              </div>`).join('')}

          </div>
        </div>`;

      document.body.appendChild(overlay);

    } catch {
      _toast('Failed to load equipment details.', 'error');
    }
  }

  // ── Add maintenance log modal ─────────────────────────────
  async function _openAddMaintenanceLog(equipmentId) {
    // Remove existing if open
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
            onclick="Dashboard._saveMaintenanceLog(${equipmentId})"
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
      // Reopen the equipment modal to show the new log
      await _openEquipmentModal(equipmentId);

    } catch {
      errEl.textContent   = 'Network error. Please try again.';
      errEl.style.display = 'block';
    } finally {
      btn.disabled = false; btn.textContent = 'Save Log';
    }
  }

  // ── Print QR code ─────────────────────────────────────────
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

  // ── Add equipment modal ───────────────────────────────────
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
              <input type="text" id="ae-location" class="form-input"
                placeholder="e.g. Front Desk">
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

          <button id="ae-save-btn" onclick="Dashboard._saveEquipment()"
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
    const btn    = document.getElementById('ae-save-btn');
    const errEl  = document.getElementById('ae-error');
    const name   = document.getElementById('ae-name')?.value.trim();

    errEl.style.display = 'none';
    if (!name) { errEl.textContent = 'Equipment name is required.'; errEl.style.display = 'block'; return; }

    btn.disabled = true; btn.textContent = 'Saving…';

    try {
      const purchasePrice = document.getElementById('ae-purchase-price')?.value;
      const res = await Auth.fetch('/api/v1/inventory/equipment/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({
          name            : name,
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
          <button onclick="Dashboard.openReceiveStock()"
            style="padding:8px 18px;background:var(--text);color:#fff;border:none;
                   border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                   cursor:pointer;font-family:'DM Sans',sans-serif;">
            + Receive Stock
          </button>
        </div>
        ${alertHtml}
        ${_renderInventoryCards(items.filter(i => i.category !== 'Machinery'), 'live')}`;

    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load stock levels.</div>';
    }
  }

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
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Date</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Item</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Type</th>
                <th style="text-align:right;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Qty</th>
                <th style="text-align:right;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Balance</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Notes</th>
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
                    <td style="padding:10px 16px;font-size:13px;color:var(--text);font-weight:500;">
                      ${_esc(m.consumable_name || '—')}
                    </td>
                    <td style="padding:10px 16px;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;
                        background:${typeBg[m.movement_type]||'var(--bg)'};
                        color:${typeColor[m.movement_type]||'var(--text-3)'};">
                        ${m.movement_type}
                      </span>
                    </td>
                    <td style="padding:10px 16px;text-align:right;
                      font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;
                      color:${isOut ? 'var(--red-text)' : 'var(--green-text)'};">
                      ${isOut ? '-' : '+'}${parseFloat(m.quantity).toFixed(2)}
                    </td>
                    <td style="padding:10px 16px;text-align:right;
                      font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-3);">
                      ${parseFloat(m.balance_after).toFixed(2)}
                    </td>
                    <td style="padding:10px 16px;font-size:12px;color:var(--text-3);
                      max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
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
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Date</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Item</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Reason</th>
                <th style="text-align:right;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Qty</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Reported By</th>
                <th style="text-align:left;padding:9px 16px;font-size:10.5px;font-weight:700;
                  text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);
                  border-bottom:2px solid var(--border);">Job</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(w => {
                const date = new Date(w.created_at).toLocaleDateString('en-GB',
                  { day: 'numeric', month: 'short', year: 'numeric' });
                return `
                  <tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:10px 16px;font-size:12px;color:var(--text-3);">${date}</td>
                    <td style="padding:10px 16px;font-size:13px;color:var(--text);font-weight:500;">
                      ${_esc(w.consumable_name || '—')}
                    </td>
                    <td style="padding:10px 16px;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:11px;font-weight:700;
                        background:${reasonBg[w.reason]||'var(--bg)'};
                        color:${reasonColor[w.reason]||'var(--text-3)'};">
                        ${w.reason}
                      </span>
                    </td>
                    <td style="padding:10px 16px;text-align:right;
                      font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:600;
                      color:var(--red-text);">
                      -${parseFloat(w.quantity).toFixed(2)}
                    </td>
                    <td style="padding:10px 16px;font-size:12px;color:var(--text-2);">
                      ${_esc(w.reported_by_name || '—')}
                    </td>
                    <td style="padding:10px 16px;font-size:12px;color:var(--text-3);
                      font-family:'JetBrains Mono',monospace;">
                      ${_esc(w.job_number || '—')}
                    </td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load waste incidents.</div>';
    }
  }

  async function openReceiveStock() {
    // Reset form
    document.getElementById('recv-consumable').value          = '';
    document.getElementById('recv-consumable-search').value   = '';
    document.getElementById('recv-consumable-dropdown').style.display = 'none';
    document.getElementById('recv-quantity').value     = '';
    document.getElementById('recv-notes').value        = '';
    document.getElementById('recv-error').style.display = 'none';
    document.getElementById('recv-submit-btn').disabled = false;
    document.getElementById('recv-submit-btn').textContent = 'Confirm Receipt';

    document.getElementById('recv-overlay').classList.add('open');

    // Load consumables if not already loaded
    if (!_consumables.length) {
      await _loadConsumables();
    }

    // Populate consumable dropdown
    const sel = document.getElementById('recv-consumable');
    sel.innerHTML = '<option value="">Select consumable…</option>';
    _consumables.forEach(c => {
      const opt       = document.createElement('option');
      opt.value       = c.consumable;
      opt.textContent = `${c.name} (${c.quantity} ${c.unit_label} in stock)`;
      sel.appendChild(opt);
    });
  }

  function _recvShowDropdown() {
    _recvFilterConsumables();
  }

  function _recvFilterConsumables() {
    const query    = document.getElementById('recv-consumable-search').value.toLowerCase();
    const dropdown = document.getElementById('recv-consumable-dropdown');
    const filtered = _consumables.filter(c =>
      c.name.toLowerCase().includes(query)
    );

    if (!filtered.length) {
      dropdown.style.display = 'none';
      return;
    }

    dropdown.innerHTML = filtered.map(c => `
      <div onclick="Dashboard._recvSelectConsumable(${c.consumable}, '${_esc(c.name)}', '${c.quantity} ${c.unit_label}')"
        style="padding:9px 12px;font-size:13px;cursor:pointer;
               border-bottom:1px solid var(--border);
               transition:background 0.1s;"
        onmouseover="this.style.background='var(--bg)'"
        onmouseout="this.style.background=''">
        <div style="font-weight:600;color:var(--text);">${_esc(c.name)}</div>
        <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
          ${c.quantity} ${c.unit_label} in stock
        </div>
      </div>
    `).join('');

    dropdown.style.display = 'block';
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
          notes         : notes,
        }),
      });

      const data = await res.json();

      if (!res.ok) {
        const msg = Object.values(data).flat().join(' ');
        err.textContent    = msg || 'Failed to receive stock.';
        err.style.display  = 'block';
        return;
      }

      closeReceiveStock();
      _toast(`Stock received successfully.`, 'success');

      // Reload inventory tab to reflect new balance
      switchInventoryTab(document.querySelector('.inv-tab.active')?.dataset.tab || 'consumables');

    } catch {
      err.textContent   = 'Network error. Please try again.';
      err.style.display = 'block';
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Confirm Receipt';
    }
  }

// ── Reports pane ─────────────────────────────────────────────
async function _loadReportsPane() {
    const pane = document.getElementById('pane-reports');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Reports & Filing</span>
      </div>

      <div class="reports-tabs">
        <button class="reports-tab active" data-tab="daily"
          onclick="Dashboard.switchReportsTab('daily')">Daily</button>
        <button class="reports-tab" data-tab="filing"
          onclick="Dashboard.switchReportsTab('filing')">Weekly</button>
        <button class="reports-tab" data-tab="monthly"
          onclick="Dashboard.switchReportsTab('monthly')">Monthly</button>
        <button class="reports-tab" data-tab="yearly"
          onclick="Dashboard.switchReportsTab('yearly')">Yearly</button>
        <button class="reports-tab" data-tab="ledger"
          onclick="Dashboard.switchReportsTab('ledger')">Job Ledger</button>
      </div>

      <div id="reports-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    await _loadReportsTab('daily');
  }



  async function setReportsPeriod(period) {
    const activeTab = document.querySelector('.reports-tab.active')?.dataset.tab || 'history';
    await _loadReportsTab(activeTab);
  }

async function switchReportsTab(tab) {
    document.querySelectorAll('#pane-reports .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    await _loadReportsTab(tab);
  }

async function _loadReportsTab(tab) {
    const content = document.getElementById('reports-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    if (tab === 'daily')   await _renderDailySheets(content);
    if (tab === 'filing')  await _renderWeeklyFiling(content);
    if (tab === 'monthly') await _renderMonthlyClose(content);
    if (tab === 'yearly')  await _renderYearlySummary(content);
    if (tab === 'ledger')  _renderHistoryReport(content);
  }


  // ── Sheets Archive ────────────────────────────────────────────
  async function _renderSheetsReport(container) {
    try {
      const res = await Auth.fetch(`/api/v1/finance/sheets/?period=${_reportsPeriod}`);
      if (!res.ok) throw new Error();
      const data  = await res.json();
      const sheets = data.results || data;

      if (!sheets.length) {
        container.innerHTML = '<div class="loading-cell">No sheets found for this period.</div>';
        return;
      }

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
          <table class="p-table">
            <thead>
              <tr>
                <th>Date</th>
                <th>Status</th>
                <th>Jobs</th>
                <th>Cash</th>
                <th>MoMo</th>
                <th>POS</th>
                <th>Total</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${sheets.map(s => `
                <tr>
                  <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${s.date}</td>
                  <td><span class="badge badge-${s.status === 'OPEN' ? 'progress' : 'done'}">${s.status}</span></td>
                  <td>${s.total_jobs_created || 0}</td>
                  <td>${fmt(s.total_cash)}</td>
                  <td>${fmt(s.total_momo)}</td>
                  <td>${fmt(s.total_pos)}</td>
                  <td style="font-weight:700;">${fmt((parseFloat(s.total_cash||0)+parseFloat(s.total_momo||0)+parseFloat(s.total_pos||0)))}</td>
                  <td>
                    ${s.status !== 'OPEN' ? `
                        <button onclick="Dashboard.downloadSheetPDF(${s.id}, '${s.date}')"
                        style="font-size:12px;color:var(--text-2);background:none;border:none;cursor:pointer;font-weight:600;padding:0;">
                        PDF ↓
                      </button>` : '—'}
                  </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load sheets.</div>';
    }
  }

  // ── Jobs History ──────────────────────────────────────────────
  async function _renderJobsReport(container) {
    try {
      const res = await Auth.fetch(`/api/v1/jobs/?period=${_reportsPeriod}&page_size=50`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = data.results || data;

      const total     = jobs.length;
      const completed = jobs.filter(j => j.status === 'COMPLETE').length;
      const cancelled = jobs.filter(j => j.status === 'CANCELLED').length;
      const drafts    = jobs.filter(j => j.status === 'DRAFT').length;
      const pct       = total ? Math.round(completed / total * 100) : 0;

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

      container.innerHTML = `
        <div class="stat-grid" style="margin-bottom:20px;">
          <div class="stat-card blue"><div class="stat-num">${total}</div><div class="stat-lbl">Total Jobs</div></div>
          <div class="stat-card green"><div class="stat-num">${completed}</div><div class="stat-lbl">Completed</div></div>
          <div class="stat-card red"><div class="stat-num">${cancelled}</div><div class="stat-lbl">Cancelled</div></div>
          <div class="stat-card amber"><div class="stat-num">${pct}%</div><div class="stat-lbl">Completion Rate</div></div>
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
          <table class="p-table">
            <thead>
              <tr>
                <th>Ref</th>
                <th>Title</th>
                <th>Type</th>
                <th>Status</th>
                <th>Attendant</th>
                <th>Amount</th>
                <th>Date</th>
              </tr>
            </thead>
            <tbody>
              ${jobs.map(j => `
                <tr>
                  <td style="font-family:'JetBrains Mono',monospace;font-size:11px;">${j.job_number||'—'}</td>
                  <td style="max-width:180px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${j.title||'—'}</td>
                  <td><span class="type-pill ${j.job_type||''}">${j.job_type||'—'}</span></td>
                  <td><span class="badge badge-${_jobStatusBadge(j.status)}">${j.status}</span></td>
                  <td>${j.intake_by_name||'—'}</td>
                  <td>${fmt(j.estimated_cost)}</td>
                  <td style="font-size:11px;color:var(--text-3);">${j.created_at ? new Date(j.created_at).toLocaleDateString('en-GH') : '—'}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load jobs.</div>';
    }
  }

  function _jobStatusBadge(status) {
    const map = {
      COMPLETE: 'done', PENDING_PAYMENT: 'pending', IN_PROGRESS: 'progress',
      CANCELLED: 'cancelled', DRAFT: 'draft', PAID: 'progress',
    };
    return map[status] || 'pending';
  }

  // ── Service Performance ───────────────────────────────────────
 // ── Service Performance ──────────────────────────────────────────────────
  let _servicesPeriod = 'month';

  async function _renderServicesReport(container) {
    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
        <div style="font-size:10.5px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.8px;">Service Performance</div>
        <div style="display:flex;gap:4px;">
          ${['day','week','month','year'].map(p => `
            <button onclick="Dashboard.setServicesPeriod('${p}')"
              class="reports-tab ${_servicesPeriod === p ? 'active' : ''}"
              data-period="${p}"
              style="padding:5px 12px;font-size:12px;">
              ${p.charAt(0).toUpperCase() + p.slice(1)}
            </button>`).join('')}
        </div>
      </div>
      <div id="services-report-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    await _fetchServicesReport();
  }

  async function _fetchServicesReport() {
    const content = document.getElementById('services-report-content');
    if (!content) return;

    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    try {
      const res = await Auth.fetch(`/api/v1/jobs/reports/services/?period=${_servicesPeriod}`);
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const services = data.services || [];

      if (!services.length) {
        content.innerHTML = '<div class="loading-cell">No service data for this period.</div>';
        return;
      }

      const fmt    = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
      const maxRev = Math.max(...services.map(s => parseFloat(s.revenue||0)));

      content.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:20px;margin-bottom:16px;">
          <div style="font-size:12px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;margin-bottom:16px;">
            Revenue by Service
          </div>
          ${services.slice(0,10).map(s => {
            const pct = maxRev ? (parseFloat(s.revenue||0) / maxRev * 100) : 0;
            return `
              <div style="margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;
                  align-items:center;margin-bottom:4px;">
                  <span style="font-size:12px;font-weight:500;color:var(--text);">${s.service}</span>
                  <span style="font-size:12px;font-family:'JetBrains Mono',monospace;
                    color:var(--text-2);">${fmt(s.revenue)}</span>
                </div>
                <div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden;">
                  <div style="height:100%;width:${pct}%;background:var(--text);
                    border-radius:3px;transition:width 0.4s ease;"></div>
                </div>
              </div>`;
          }).join('')}
        </div>

        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table class="p-table">
            <thead>
              <tr>
                <th>Service</th>
                <th>Jobs</th>
                <th>Revenue</th>
                <th>% of Total</th>
              </tr>
            </thead>
            <tbody>
              ${services.map(s => `
                <tr>
                  <td>${s.service}</td>
                  <td>${s.job_count}</td>
                  <td style="font-family:'JetBrains Mono',monospace;font-weight:600;">
                    ${fmt(s.revenue)}</td>
                  <td>
                    <div style="display:flex;align-items:center;gap:8px;">
                      <div style="width:60px;height:4px;background:var(--border);border-radius:2px;">
                        <div style="height:100%;width:${s.percentage}%;
                          background:var(--green-text);border-radius:2px;"></div>
                      </div>
                      <span style="font-size:12px;color:var(--text-2);">${s.percentage}%</span>
                    </div>
                  </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      content.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load service data.</div>';
    }
  }

  async function setServicesPeriod(period) {
    _servicesPeriod = period;
    document.querySelectorAll('#pane-reports .reports-tab[data-period]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.period === period);
    });
    await _fetchServicesReport();
  }

 async function _renderMonthlyClose(container) {
    if (!container) return;

    const now   = new Date();
    const month = now.getMonth() + 1;
    const year  = now.getFullYear();

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;
        margin-bottom:20px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;
            color:var(--text);letter-spacing:-0.3px;">Monthly Close</div>
          <div style="font-size:12.5px;color:var(--text-3);margin-top:3px;">
            End-of-month operations closure and Finance review
          </div>
        </div>
      </div>
      <div id="monthly-current-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>
      <div id="monthly-history" style="margin-top:24px;"></div>`;

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/monthly-close/?month=${month}&year=${year}`
      );
      const content = document.getElementById('monthly-current-content');
      if (!content) return;

      if (!res.ok) {
        const monthName = ['January','February','March','April','May','June',
          'July','August','September','October','November','December'][month - 1];
        content.innerHTML = `
          <div style="background:var(--panel);border:1px solid var(--border);
            border-radius:var(--radius);padding:24px 20px;text-align:center;
            color:var(--text-3);">
            <div style="font-size:14px;font-weight:600;color:var(--text);
              margin-bottom:6px;">${monthName} ${year}</div>
            <div style="font-size:13px;">
              No monthly close record yet. Submit at month end when all
              integrity gates are met.
            </div>
          </div>`;
        return;
      }

      const data = await res.json();
      _renderMonthlyCloseDetail(content, data);
    } catch {
      const content = document.getElementById('monthly-current-content');
      if (content) content.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:24px 20px;text-align:center;
          color:var(--text-3);font-size:13px;">
          Monthly close not yet initiated for this month.
        </div>`;
    }

    await _loadMonthlyHistory();
  }

  async function _loadMonthlyHistory() {
    const container = document.getElementById('monthly-history');
    if (!container) return;

    const monthNames = ['January','February','March','April','May','June',
      'July','August','September','October','November','December'];

    try {
      // Fetch all closes for this branch — we use the weekly list endpoint trick
      // by fetching each previous month close
      const now   = new Date();
      const year  = now.getFullYear();
      const currentMonth = now.getMonth() + 1;

      // Fetch closes for all previous months this year
      const fetches = [];
      for (let m = 1; m < currentMonth; m++) {
        fetches.push(
          Auth.fetch(`/api/v1/finance/monthly-close/?month=${m}&year=${year}`)
            .then(r => r.ok ? r.json() : null)
            .catch(() => null)
        );
      }

      const results = await Promise.all(fetches);
      const closes  = results
        .filter(r => r && r.status && r.status !== 'OPEN')
        .sort((a, b) => b.month - a.month);

      if (!closes.length) return;

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

      const statusConfig = {
        SUBMITTED          : { bg: 'var(--amber-bg)',  text: 'var(--amber-text)',  label: 'Awaiting Finance' },
        FINANCE_REVIEWING  : { bg: '#dbeafe',           text: '#1e40af',            label: 'Finance Reviewing' },
        NEEDS_CLARIFICATION: { bg: 'var(--amber-bg)',  text: 'var(--amber-text)',  label: 'Needs Clarification' },
        RESUBMITTED        : { bg: 'var(--amber-bg)',  text: 'var(--amber-text)',  label: 'Resubmitted' },
        FINANCE_CLEARED    : { bg: 'var(--green-bg)',  text: 'var(--green-text)',  label: 'Finance Cleared' },
        ENDORSED           : { bg: 'var(--green-bg)',  text: 'var(--green-text)',  label: 'Endorsed ✓' },
        LOCKED             : { bg: 'var(--green-bg)',  text: 'var(--green-text)',  label: 'Locked ✓' },
        REJECTED           : { bg: 'var(--red-bg)',    text: 'var(--red-text)',    label: 'Rejected' },
      };

      container.innerHTML = `
        <div style="font-size:10px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">
          Previous Monthly Closes
        </div>
        ${closes.map(c => {
          const snap    = c.summary_snapshot || {};
          const revenue = snap.revenue || {};
          const jobs    = snap.jobs    || {};
          const sc      = statusConfig[c.status] || { bg:'var(--bg)', text:'var(--text-3)', label: c.status };
          const canDownload = ['ENDORSED','LOCKED'].includes(c.status);

          return `
            <div style="border:1px solid var(--border);border-radius:var(--radius);
              overflow:hidden;margin-bottom:10px;">

              <!-- Header -->
              <div style="padding:16px 20px;background:var(--panel);
                border-bottom:1px solid var(--border);">
                <div style="display:flex;align-items:center;
                  justify-content:space-between;margin-bottom:10px;">
                  <div>
                    <div style="font-size:15px;font-weight:700;color:var(--text);">
                      ${monthNames[(c.month||1)-1]} ${c.year}
                    </div>
                    <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
                      Submitted by ${c.submitted_by || '—'}
                      ${c.submitted_at ? ' · ' + new Date(c.submitted_at)
                        .toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : ''}
                    </div>
                  </div>
                  <div style="display:flex;align-items:center;gap:8px;">
                    <span style="padding:4px 12px;border-radius:20px;font-size:11px;
                      font-weight:700;background:${sc.bg};color:${sc.text};">
                      ${sc.label}
                    </span>
                    ${canDownload ? `
                      <button onclick="Dashboard._downloadMonthlyPDF(${c.id})"
                        style="display:inline-flex;align-items:center;gap:5px;
                          padding:6px 14px;background:var(--text);color:#fff;
                          border:none;border-radius:var(--radius-sm);font-size:12px;
                          font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;">
                        <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11"
                          viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                          <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                          <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                        </svg>
                        PDF
                      </button>` : ''}
                  </div>
                </div>

                <!-- Revenue + jobs strip -->
                ${snap.revenue ? `
                  <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
                    ${[
                      ['Total Collected', fmt(revenue.total_collected || 0), 'var(--text)'],
                      ['Cash',            fmt(revenue.total_cash      || 0), 'var(--cash-strong)'],
                      ['MoMo',            fmt(revenue.total_momo      || 0), 'var(--momo-strong)'],
                      ['Jobs',            jobs.total || 0,                   'var(--text)'],
                    ].map(([label, val, color]) => `
                      <div style="padding:8px 12px;background:var(--bg);
                        border:1px solid var(--border);border-radius:var(--radius-sm);">
                        <div style="font-size:10px;font-weight:700;color:var(--text-3);
                          text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">
                          ${label}</div>
                        <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                          font-weight:700;color:${color};">${val}</div>
                      </div>`).join('')}
                  </div>` : ''}
              </div>

              <!-- Audit trail -->
              <div style="padding:12px 20px;background:var(--bg);">
                <div style="font-size:10px;font-weight:700;color:var(--text-3);
                  text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
                  Audit Trail
                </div>
                <div style="display:flex;flex-direction:column;gap:6px;">
                  ${[
                    ['Submitted',       c.submitted_by,        c.submitted_at,        '#3355cc'],
                    ['Finance Cleared', c.finance_reviewer,    c.finance_cleared_at,  '#22c98a'],
                    ['Endorsed',        c.endorsed_by,         c.endorsed_at,         '#9b59b6'],
                    ['Locked',          c.locked_at ? 'System' : null, c.locked_at,  '#666'],
                  ].filter(([,actor]) => actor).map(([label, actor, ts, color]) => `
                    <div style="display:flex;align-items:center;gap:10px;">
                      <div style="width:6px;height:6px;border-radius:50%;
                        background:${color};flex-shrink:0;"></div>
                      <span style="font-size:12px;font-weight:600;color:var(--text);
                        min-width:120px;">${label}</span>
                      <span style="font-size:12px;color:var(--text-2);">${actor || '—'}</span>
                      ${ts ? `<span style="font-size:11px;color:var(--text-3);margin-left:auto;">
                        ${new Date(ts).toLocaleDateString('en-GB',
                          {day:'numeric',month:'short',year:'numeric'})}</span>` : ''}
                    </div>`).join('')}
                </div>
                ${c.rejection_reason ? `
                  <div style="margin-top:10px;padding:8px 12px;
                    background:var(--red-bg);border:1px solid var(--red-border);
                    border-radius:var(--radius-sm);font-size:12px;color:var(--red-text);">
                    <strong>Rejection reason:</strong> ${c.rejection_reason}
                  </div>` : ''}
              </div>

            </div>`;
        }).join('')}`;

    } catch { /* silent */ }
  }

  async function _submitMonthlyClose(month, year) {
    const btn   = document.getElementById('monthly-submit-btn');
    const notes = document.getElementById('monthly-bm-notes')?.value.trim() || '';

    if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }

    try {
      const res = await Auth.fetch('/api/v1/finance/monthly-close/submit/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ month, year, bm_notes: notes }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = Array.isArray(err.detail) ? err.detail.join(' ') : (err.detail || 'Submission failed.');
        _toast(msg, 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Submit for Endorsement'; }
        return;
      }

      _toast('Monthly close submitted. Awaiting Belt Manager endorsement.', 'success');
      const content = document.getElementById('reports-content');
      if (content) await _renderMonthlyClose(content);

    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Submit for Endorsement'; }
    }
  }

  async function _downloadMonthlyPDF(id) {
    try {
      const res = await Auth.fetch(`/api/v1/finance/monthly-close/${id}/pdf/`);
      if (!res.ok) { _toast('Could not generate PDF.', 'error'); return; }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = `monthly_close_${id}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      _toast('Download failed.', 'error');
    }
  }

async function _renderYearlySummary(container) {
    if (!container) return;

    const year = new Date().getFullYear();
    const monthNames = ['January','February','March','April','May','June',
      'July','August','September','October','November','December'];

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;
        margin-bottom:20px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;
            color:var(--text);letter-spacing:-0.3px;">${year} Annual Overview</div>
          <div style="font-size:12.5px;color:var(--text-3);margin-top:3px;">
            Month-by-month summary for the current year
          </div>
        </div>
      </div>
      <div id="yearly-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    try {
      const res = await Auth.fetch(
        `/api/v1/jobs/history/?level=month&year=${year}`
      );
      if (!res.ok) throw new Error();
      const data = await res.json();

      const content = document.getElementById('yearly-content');
      if (!content) return;

      const fmt     = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
      const kpis    = data.kpis || {};
      const items   = data.items || [];

      // ── KPI strip ─────────────────────────────────────────
      const kpiHtml = `
        <div style="display:grid;grid-template-columns:repeat(4,1fr);
          gap:10px;margin-bottom:24px;">
          ${[
            { label:'Total Jobs',   value: kpis.total?.value   || 0, fmt: v => v,       color:'#3355cc' },
            { label:'Revenue',      value: kpis.revenue?.value || 0, fmt: v => fmt(v),  color:'#22c98a' },
            { label:'Pending',      value: kpis.pending?.value || 0, fmt: v => v,       color:'#e8a820' },
            { label:'Completion',   value: kpis.rate?.value    || 0, fmt: v => v + '%', color:'#9b59b6' },
          ].map(k => {
            const change = kpis[Object.keys(kpis).find(key =>
              kpis[key].value === k.value
            )]?.change;
            return `
              <div style="background:var(--panel);border:1px solid var(--border);
                border-top:3px solid ${k.color};border-radius:var(--radius);
                padding:14px 16px;">
                <div style="font-size:10px;font-weight:700;color:var(--text-3);
                  text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">
                  ${k.label}</div>
                <div style="font-size:20px;font-weight:800;color:${k.color};
                  font-family:'Outfit',sans-serif;">${k.fmt(k.value)}</div>
              </div>`;
          }).join('')}
        </div>`;

      // ── Monthly breakdown table ────────────────────────────
      const maxRevenue = Math.max(...items.map(i => i.revenue || 0), 1);

      const tableHtml = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;margin-bottom:20px;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);">
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;
                  border-bottom:2px solid var(--border);">Month</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;
                  border-bottom:2px solid var(--border);">Jobs</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;
                  border-bottom:2px solid var(--border);">Revenue</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;
                  border-bottom:2px solid var(--border);">Rate</th>
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;
                  border-bottom:2px solid var(--border);">Trend</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;
                  border-bottom:2px solid var(--border);">Close</th>
              </tr>
            </thead>
            <tbody>
              ${monthNames.map((name, i) => {
                const m      = i + 1;
                const item   = items.find(it => it.month === m);
                const now    = new Date();
                const isPast = m < now.getMonth() + 1;
                const isCurr = m === now.getMonth() + 1;
                const isFuture = m > now.getMonth() + 1;

                if (isFuture) {
                  return `
                    <tr style="border-bottom:1px solid var(--border);opacity:0.3;">
                      <td style="padding:12px 16px;font-size:13px;font-weight:600;
                        color:var(--text-3);">${name}</td>
                      <td colspan="5" style="padding:12px 16px;font-size:12px;
                        color:var(--text-3);text-align:center;">—</td>
                    </tr>`;
                }

                const total   = item?.total   || 0;
                const revenue = item?.revenue  || 0;
                const rate    = item?.rate     || 0;
                const barPct  = maxRevenue > 0 ? (revenue / maxRevenue * 100) : 0;

                return `
                  <tr style="border-bottom:1px solid var(--border);
                    ${isCurr ? 'background:var(--bg);' : ''}
                    transition:background 0.12s;"
                    onmouseover="this.style.background='var(--bg)'"
                    onmouseout="this.style.background='${isCurr ? 'var(--bg)' : ''}'">
                    <td style="padding:12px 16px;">
                      <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-size:13px;font-weight:700;color:var(--text);">
                          ${name}</span>
                        ${isCurr ? `<span style="padding:2px 8px;border-radius:20px;
                          font-size:10px;font-weight:700;background:var(--amber-bg);
                          color:var(--amber-text);">Current</span>` : ''}
                      </div>
                    </td>
                    <td style="padding:12px 16px;text-align:right;font-size:13px;
                      font-weight:600;color:var(--text);">${total}</td>
                    <td style="padding:12px 16px;text-align:right;
                      font-family:'JetBrains Mono',monospace;font-size:13px;
                      font-weight:700;color:var(--text);">${fmt(revenue)}</td>
                    <td style="padding:12px 16px;text-align:right;font-size:13px;
                      font-weight:600;color:${rate >= 95 ? 'var(--green-text)' :
                        rate >= 80 ? 'var(--amber-text)' : 'var(--red-text)'};">
                      ${rate}%</td>
                    <td style="padding:12px 16px;">
                      <div style="height:6px;background:var(--border);
                        border-radius:3px;width:120px;overflow:hidden;">
                        <div style="height:100%;width:${barPct.toFixed(1)}%;
                          background:var(--text);border-radius:3px;
                          transition:width 0.4s ease;"></div>
                      </div>
                    </td>
                    <td style="padding:12px 16px;text-align:center;">
                      ${isPast || isCurr ? `
                        <button onclick="Dashboard.switchReportsTab('monthly')"
                          style="padding:4px 12px;background:none;
                            border:1px solid var(--border);border-radius:var(--radius-sm);
                            font-size:11px;font-weight:600;cursor:pointer;
                            color:var(--text-2);font-family:'DM Sans',sans-serif;">
                          View
                        </button>` : '—'}
                    </td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;

      content.innerHTML = kpiHtml + tableHtml;

    } catch {
      const content = document.getElementById('yearly-content');
      if (content) content.innerHTML = `
        <div class="loading-cell" style="color:var(--red-text);">
          Could not load yearly summary.</div>`;
    }
  }

async function _renderDailySheets(container) {
    if (!container) return;

    const now   = new Date();
    const month = now.getMonth() + 1;
    const year  = now.getFullYear();

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;
        margin-bottom:20px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;
            color:var(--text);letter-spacing:-0.3px;">Daily Sheets</div>
          <div style="font-size:12.5px;color:var(--text-3);margin-top:3px;">
            Closed sheets for ${now.toLocaleDateString('en-GB',{month:'long',year:'numeric'})}
             — read-only records
          </div>
        </div>
      </div>
      <div id="daily-sheets-list">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/sheets/?period=month&page_size=31`
      );
      if (!res.ok) throw new Error();
      const data   = await res.json();
      const sheets = (Array.isArray(data) ? data : (data.results || []))
        .filter(s => s.status !== 'OPEN')
        .sort((a, b) => new Date(b.date) - new Date(a.date));

      const list = document.getElementById('daily-sheets-list');
      if (!list) return;

      if (!sheets.length) {
        list.innerHTML = `
          <div style="text-align:center;padding:48px;color:var(--text-3);">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"
              viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.5" style="opacity:0.3;display:block;margin:0 auto 12px;">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">
              No closed sheets this month</div>
            <div style="font-size:13px;">Sheets appear here once closed by the Branch Manager.</div>
          </div>`;
        return;
      }

      list.innerHTML = sheets.map(s => {
        const total    = parseFloat(s.total_cash||0) + parseFloat(s.total_momo||0) + parseFloat(s.total_pos||0);
        const fmt      = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
        const dateObj  = new Date(s.date);
        const dayName  = dateObj.toLocaleDateString('en-GB',{weekday:'long'});
        const dateStr  = dateObj.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
        const isAuto   = s.status === 'AUTO_CLOSED';

        return `
          <div style="border:1px solid var(--border);border-radius:var(--radius);
            overflow:hidden;margin-bottom:10px;">

            <!-- Sheet header — always visible, click to expand -->
            <div onclick="Dashboard._toggleDailySheet(${s.id})"
              style="display:flex;align-items:center;justify-content:space-between;
                padding:14px 20px;background:var(--panel);cursor:pointer;
                transition:background 0.12s;"
              onmouseover="this.style.background='var(--bg)'"
              onmouseout="this.style.background='var(--panel)'">

              <div style="display:flex;align-items:center;gap:14px;">
                <!-- Date block -->
                <div style="text-align:center;min-width:44px;">
                  <div style="font-size:11px;font-weight:700;color:var(--text-3);
                    text-transform:uppercase;">${dateObj.toLocaleDateString('en-GB',{month:'short'})}</div>
                  <div style="font-size:22px;font-weight:800;color:var(--text);
                    font-family:'Syne',sans-serif;line-height:1;">${dateObj.getDate()}</div>
                  <div style="font-size:10px;color:var(--text-3);">${dateObj.toLocaleDateString('en-GB',{weekday:'short'})}</div>
                </div>

                <!-- Divider -->
                <div style="width:1px;height:40px;background:var(--border);"></div>

                <!-- Stats -->
                <div>
                  <div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:3px;">
                    ${dayName} · ${dateStr}
                  </div>
                  <div style="display:flex;align-items:center;gap:16px;">
                    <span style="font-size:12px;color:var(--text-3);">
                      ${s.total_jobs_created || 0} jobs
                    </span>
                    <span style="font-family:'JetBrains Mono',monospace;font-size:13px;
                      font-weight:700;color:var(--text);">${fmt(total)}</span>
                  </div>
                </div>
              </div>

              <div style="display:flex;align-items:center;gap:10px;">
                ${isAuto ? `
                  <span style="padding:3px 10px;border-radius:20px;font-size:10px;
                    font-weight:700;background:var(--amber-bg);color:var(--amber-text);">
                    Auto-closed
                  </span>` : `
                  <span style="padding:3px 10px;border-radius:20px;font-size:10px;
                    font-weight:700;background:var(--green-bg);color:var(--green-text);">
                    Closed
                  </span>`}
                <svg id="daily-chevron-${s.id}" xmlns="http://www.w3.org/2000/svg"
                  width="14" height="14" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" stroke-width="2"
                  style="color:var(--text-3);transition:transform 0.2s;">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </div>
            </div>

            <!-- Expandable detail -->
            <div id="daily-detail-${s.id}" style="display:none;">
              <div style="padding:16px 20px;border-top:1px solid var(--border);
                background:var(--bg);">

                <!-- Revenue strip -->
                <div style="display:grid;grid-template-columns:repeat(4,1fr);
                  gap:8px;margin-bottom:14px;">
                  ${[
                    ['Cash',           s.total_cash,          'cash'],
                    ['MoMo',           s.total_momo,          'momo'],
                    ['POS',            s.total_pos,           'pos'],
                    ['Net Cash in Till', s.net_cash_in_till,  'green'],
                  ].map(([label, val, theme]) => `
                    <div style="padding:10px 12px;
                      background:var(--${theme}-bg, var(--bg));
                      border:1px solid var(--${theme}-border, var(--border));
                      border-radius:var(--radius-sm);">
                      <div style="font-size:10px;font-weight:700;
                        color:var(--${theme}-text, var(--text-3));
                        text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">
                        ${label}</div>
                      <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                        font-weight:700;color:var(--${theme}-strong, var(--text));">
                        ${fmt(val)}</div>
                    </div>`).join('')}
                </div>

                <!-- Secondary metrics -->
                <div style="display:grid;grid-template-columns:repeat(4,1fr);
                  gap:8px;margin-bottom:14px;">
                  ${[
                    ['Jobs Created',   s.total_jobs_created || 0, false],
                    ['Petty Cash Out', s.total_petty_cash_out,    true],
                    ['Credit Issued',  s.total_credit_issued,     true],
                    ['Credit Settled', s.total_credit_settled,    true],
                  ].map(([label, val, isMoney]) => `
                    <div style="padding:10px 12px;background:var(--panel);
                      border:1px solid var(--border);border-radius:var(--radius-sm);">
                      <div style="font-size:10px;font-weight:700;color:var(--text-3);
                        text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">
                        ${label}</div>
                      <div style="font-size:15px;font-weight:700;color:var(--text);">
                        ${isMoney ? fmt(val) : val}</div>
                    </div>`).join('')}
                </div>

                <!-- Actions -->
                <div style="display:flex;justify-content:flex-end;gap:8px;">
                  ${s.status !== 'OPEN' ? `
                    <button onclick="Dashboard.initiateSheetDownload(${s.id}, '${s.date}')"
                      style="display:inline-flex;align-items:center;gap:6px;
                        padding:7px 16px;background:var(--text);color:#fff;border:none;
                        border-radius:var(--radius-sm);font-size:12px;font-weight:700;
                        cursor:pointer;font-family:'DM Sans',sans-serif;">
                      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12"
                        viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                        <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                      </svg>
                      Download PDF
                    </button>` : ''}
                </div>

              </div>
            </div>

          </div>`;
      }).join('');

    } catch {
      const list = document.getElementById('daily-sheets-list');
      if (list) list.innerHTML = `
        <div class="loading-cell" style="color:var(--red-text);">
          Could not load daily sheets.</div>`;
    }
  }

  let _openDailySheet = null;

  function _toggleDailySheet(sheetId) {
    const detail  = document.getElementById(`daily-detail-${sheetId}`);
    const chevron = document.getElementById(`daily-chevron-${sheetId}`);
    const isOpen  = detail.style.display !== 'none';

    // Close any open sheet
    if (_openDailySheet && _openDailySheet !== sheetId) {
      const prev         = document.getElementById(`daily-detail-${_openDailySheet}`);
      const prevChevron  = document.getElementById(`daily-chevron-${_openDailySheet}`);
      if (prev)        prev.style.display        = 'none';
      if (prevChevron) prevChevron.style.transform = 'rotate(0deg)';
    }

    if (isOpen) {
      detail.style.display    = 'none';
      chevron.style.transform = 'rotate(0deg)';
      _openDailySheet         = null;
    } else {
      detail.style.display    = 'block';
      chevron.style.transform = 'rotate(180deg)';
      _openDailySheet         = sheetId;
    }
  }


async function _renderWeeklyFiling(container) {
    if (!container) return;

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;
        margin-bottom:20px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;
            color:var(--text);letter-spacing:-0.3px;">Weekly Filing</div>
          <div style="font-size:12.5px;color:var(--text-3);margin-top:3px;">
            Monday – Saturday consolidated operations report
          </div>
        </div>
        <button id="weekly-prepare-btn" onclick="Dashboard.weeklyPrepare()"
          style="padding:8px 18px;background:var(--text);color:#fff;border:none;
                 border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                 cursor:pointer;font-family:'DM Sans',sans-serif;">
          Prepare This Week
        </button>
      </div>
      <div id="weekly-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>
      <div id="weekly-history" style="margin-top:24px;"></div>`;

    await _loadWeeklyReport();
    await _loadWeeklyHistory();
  }

 async function _loadWeeklyHistory() {
    const container = document.getElementById('weekly-history');
    if (!container) return;

    try {
      const res  = await Auth.fetch('/api/v1/finance/weekly/');
      if (!res.ok) throw new Error();
      const data    = await res.json();
      const reports = (Array.isArray(data) ? data : (data.results || []))
        .filter(r => r.status === 'LOCKED')
        .sort((a, b) => {
          if (b.year !== a.year) return b.year - a.year;
          return b.week_number - a.week_number;
        });

      if (!reports.length) return;

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

      container.innerHTML = `
        <div style="font-size:10px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">
          Previous Filed Weeks
        </div>
        ${reports.map(r => {
          const total      = parseFloat(r.total_cash||0) + parseFloat(r.total_momo||0) + parseFloat(r.total_pos||0);
          const dateFrom   = new Date(r.date_from).toLocaleDateString('en-GB',{day:'numeric',month:'short'});
          const dateTo     = new Date(r.date_to).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
          const submittedAt = r.submitted_at
            ? new Date(r.submitted_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})
            : '—';

          return `
            <div style="border:1px solid var(--border);border-radius:var(--radius);
              overflow:hidden;margin-bottom:8px;">

              <!-- Header — clickable to expand -->
              <div onclick="Dashboard._toggleHistoryWeek(${r.id})"
                style="display:flex;align-items:center;justify-content:space-between;
                  padding:14px 20px;background:var(--panel);cursor:pointer;
                  transition:background 0.12s;"
                onmouseover="this.style.background='var(--bg)'"
                onmouseout="this.style.background='var(--panel)'">
                <div>
                  <div style="font-size:14px;font-weight:700;color:var(--text);
                    margin-bottom:3px;">
                    Week ${r.week_number}, ${r.year}
                    <span style="font-size:12px;font-weight:400;color:var(--text-3);
                      margin-left:8px;">${dateFrom} – ${dateTo}</span>
                  </div>
                  <div style="font-size:11px;color:var(--text-3);">
                    Filed by ${r.submitted_by_name || '—'} · ${submittedAt}
                  </div>
                </div>
                <div style="display:flex;align-items:center;gap:10px;">
                  <span style="padding:3px 10px;border-radius:20px;font-size:10px;
                    font-weight:700;background:var(--green-bg);color:var(--green-text);">
                    ✓ Locked
                  </span>
                  <button onclick="event.stopPropagation();Dashboard.weeklyDownloadPDF(${r.id})"
                    style="display:inline-flex;align-items:center;gap:5px;
                      padding:6px 14px;background:var(--text);color:#fff;border:none;
                      border-radius:var(--radius-sm);font-size:12px;font-weight:600;
                      cursor:pointer;font-family:'DM Sans',sans-serif;">
                    <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11"
                      viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                      <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>
                      <path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                    </svg>
                    PDF
                  </button>
                  <svg id="history-week-chevron-${r.id}"
                    xmlns="http://www.w3.org/2000/svg" width="14" height="14"
                    viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                    style="color:var(--text-3);transition:transform 0.2s;">
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </div>
              </div>

              <!-- Revenue strip — always visible -->
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;
                gap:0;border-top:1px solid var(--border);">
                ${[
                  ['Total',  fmt(total),           'var(--text)',       'var(--panel)'],
                  ['Cash',   fmt(r.total_cash),    'var(--cash-strong)','var(--cash-bg)'],
                  ['MoMo',   fmt(r.total_momo),    'var(--momo-strong)','var(--momo-bg)'],
                  ['Jobs',   r.total_jobs_created || 0, 'var(--text)', 'var(--panel)'],
                ].map(([label, val, color, bg]) => `
                  <div style="padding:10px 16px;background:${bg};
                    border-right:1px solid var(--border);">
                    <div style="font-size:10px;font-weight:700;color:var(--text-3);
                      text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">
                      ${label}</div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                      font-weight:700;color:${color};">${val}</div>
                  </div>`).join('')}
              </div>

              <!-- Expandable full detail — lazy loaded -->
              <div id="history-week-detail-${r.id}" style="display:none;">
                <div style="padding:16px 20px;border-top:1px solid var(--border);
                  background:var(--bg);">
                  <div class="loading-cell"><span class="spin"></span> Loading…</div>
                </div>
              </div>

            </div>`;
        }).join('')}`;

    } catch { /* silent */ }
  }

  let _openHistoryWeek = null;

  async function _toggleHistoryWeek(reportId) {
    const detail  = document.getElementById(`history-week-detail-${reportId}`);
    const chevron = document.getElementById(`history-week-chevron-${reportId}`);
    if (!detail) return;

    const isOpen = detail.style.display !== 'none';

    // Close any open
    if (_openHistoryWeek && _openHistoryWeek !== reportId) {
      const prev        = document.getElementById(`history-week-detail-${_openHistoryWeek}`);
      const prevChevron = document.getElementById(`history-week-chevron-${_openHistoryWeek}`);
      if (prev)        prev.style.display        = 'none';
      if (prevChevron) prevChevron.style.transform = 'rotate(0deg)';
    }

    if (isOpen) {
      detail.style.display    = 'none';
      chevron.style.transform = 'rotate(0deg)';
      _openHistoryWeek        = null;
      return;
    }

    // Open and lazy-load detail
    detail.style.display    = 'block';
    chevron.style.transform = 'rotate(180deg)';
    _openHistoryWeek        = reportId;

    const inner = detail.querySelector('div');

    try {
      const res    = await Auth.fetch(`/api/v1/finance/weekly/${reportId}/`);
      if (!res.ok) throw new Error();
      const report = await res.json();

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

      // Sheet grid
      const days   = ['Mon','Tue','Wed','Thu','Fri','Sat'];
      const sheets = report.daily_sheets || [];
      const sheetGrid = days.map((day, i) => {
        const sheet = sheets.find(s => new Date(s.date).getDay() === (i + 1));
        if (!sheet) return `
          <div style="flex:1;padding:8px 6px;background:var(--bg);
            border:1px solid var(--border);border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:9px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;margin-bottom:3px;">${day}</div>
            <div style="font-size:9px;color:var(--text-3);">No sheet</div>
          </div>`;
        const isClosed = sheet.status !== 'OPEN';
        const dotColor = isClosed ? 'var(--green-text)' : 'var(--amber-text)';
        const dotBg    = isClosed ? 'var(--green-bg)'   : 'var(--amber-bg)';
        const tot      = parseFloat(sheet.total_cash||0) + parseFloat(sheet.total_momo||0) + parseFloat(sheet.total_pos||0);
        return `
          <div style="flex:1;padding:8px 6px;background:${dotBg};
            border:1px solid ${isClosed ? 'var(--green-border)' : 'var(--amber-border)'};
            border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:9px;font-weight:700;color:${dotColor};
              text-transform:uppercase;margin-bottom:3px;">${day}</div>
            <div style="font-size:9px;color:${dotColor};font-weight:600;">
              ${isClosed ? '✓' : '●'}</div>
            <div style="font-size:8px;color:${dotColor};margin-top:2px;
              font-family:'JetBrains Mono',monospace;">
              ${fmt(tot)}</div>
          </div>`;
      }).join('');

      inner.innerHTML = `
        <!-- Sheet grid -->
        <div style="margin-bottom:14px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">
            Daily Sheets</div>
          <div style="display:flex;gap:6px;">${sheetGrid}</div>
        </div>

        <!-- Jobs summary -->
        <div style="display:grid;grid-template-columns:repeat(4,1fr);
          gap:8px;margin-bottom:14px;">
          ${[
            ['Jobs Created',  report.total_jobs_created  || 0, 'var(--text)'],
            ['Completed',     report.total_jobs_complete  || 0, 'var(--green-text)'],
            ['Cancelled',     report.total_jobs_cancelled || 0, 'var(--red-text)'],
            ['Carry Forward', report.carry_forward_count  || 0, 'var(--amber-text)'],
          ].map(([label, val, color]) => `
            <div style="padding:10px 12px;background:var(--panel);
              border:1px solid var(--border);border-radius:var(--radius-sm);
              text-align:center;">
              <div style="font-size:18px;font-weight:700;color:${color};">${val}</div>
              <div style="font-size:10px;color:var(--text-3);margin-top:2px;">${label}</div>
            </div>`).join('')}
        </div>

        <!-- Inventory -->
        <div style="margin-bottom:14px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">
            Inventory Snapshot</div>
          ${_renderInventorySnapshot(report.inventory_snapshot)}
        </div>

      <!-- BM Notes -->
      <div style="margin-bottom:16px;">

        <!-- BM Notes -->
        <div style="padding:10px 14px;background:var(--panel);
          border:1px solid var(--border);border-radius:var(--radius-sm);">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
            Branch Manager Notes</div>
          <div style="font-size:13px;color:var(--text-2);">
            ${report.bm_notes || '—'}</div>
        </div>`;

    } catch {
      inner.innerHTML = `<div style="color:var(--red-text);font-size:13px;">
        Could not load week detail.</div>`;
    }
  }


 async function _loadWeeklyReport() {
    const content = document.getElementById('weekly-content');
    if (!content) return;

    try {
      const res  = await Auth.fetch('/api/v1/finance/weekly/');
      if (!res.ok) throw new Error();
      const data    = await res.json();
      const reports = Array.isArray(data) ? data : (data.results || []);

      const now   = new Date();
      const year  = now.getFullYear();
      const month = now.getMonth() + 1;

      // Find report whose date range covers today
      const today = now.toISOString().split('T')[0];
      const current = reports.find(r =>
        r.date_from <= today && r.date_to >= today
      );

      if (current) {
        // Fetch full detail so inventory_snapshot is available
        const detailRes = await Auth.fetch(`/api/v1/finance/weekly/${current.id}/`);
        if (!detailRes.ok) throw new Error();
        const fullReport = await detailRes.json();

        // Hide prepare button if locked
        const prepareBtn = document.getElementById('weekly-prepare-btn');
        if (prepareBtn) prepareBtn.style.display = fullReport.status === 'LOCKED' ? 'none' : '';

        _renderWeeklyReportDetail(content, fullReport);
      } else {
        // No report covering today — show empty state with prepare button
        const prepareBtn = document.getElementById('weekly-prepare-btn');
        if (prepareBtn) prepareBtn.style.display = '';
        _renderWeeklyEmpty(content);
      }

    } catch {
      content.innerHTML = `
        <div style="text-align:center;padding:60px;color:var(--text-3);font-size:13px;">
          Could not load weekly filing.
        </div>`;
    }
  }

  function _renderWeeklyEmpty(container) {
    const now      = new Date();
    const monday   = new Date(now);
    monday.setDate(now.getDate() - now.getDay() + 1);
    const saturday = new Date(monday);
    saturday.setDate(monday.getDate() + 5);

    const fmt = d => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });

    container.innerHTML = `
      <div style="background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);padding:32px;text-align:center;">
        <div style="width:48px;height:48px;border-radius:12px;background:var(--bg);
          border:1px solid var(--border);display:flex;align-items:center;
          justify-content:center;margin:0 auto 16px;color:var(--text-3);">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
        </div>
        <div style="font-family:'Syne',sans-serif;font-size:15px;font-weight:700;
          color:var(--text);margin-bottom:6px;">No filing for this week</div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          ${fmt(monday)} – ${fmt(saturday)}
        </div>
        <button onclick="Dashboard.weeklyPrepare()"
          style="padding:8px 20px;background:var(--text);color:#fff;border:none;
                 border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                 cursor:pointer;font-family:'DM Sans',sans-serif;">
          Prepare Filing
        </button>
      </div>`;
  }

function _renderInventorySnapshot(snapshot) {
    if (!snapshot || !snapshot.items || !snapshot.items.length) {
      return `
        <div style="padding:24px;text-align:center;color:var(--text-3);font-size:13px;">
          No inventory data for this period.
        </div>`;
    }

    const items = snapshot.items.filter(i => i.category !== 'Machinery');
    const lowStockFiltered = (snapshot.low_stock || []).filter(name => {
      const item = items.find(i => i.consumable === name);
      return item && item.category !== 'Machinery';
    });

    const alertHtml = lowStockFiltered.length ? `
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
          Low stock: ${lowStockFiltered.join(', ')}
        </span>
      </div>` : '';

    return alertHtml + _renderInventoryCards(items, 'snapshot');
  }

function _renderInventoryCards(items, mode = 'snapshot') {
    if (!items || !items.length) {
      return `
        <div style="padding:24px;text-align:center;color:var(--text-3);font-size:13px;">
          No inventory data available.
        </div>`;
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
        const statusLabel = isCritical ? 'Critical'  : isLow ? 'Low'  : 'OK';

        // Toner progress bar
        const barPct = reorderPoint > 0
          ? Math.min(100, (closing / 100) * 100)  // toner is %, so closing IS the pct
          : Math.min(100, (closing / (reorderPoint * 3 || 1)) * 100);
        const barColor = isCritical ? '#dc2626' : isLow ? '#d97706' : '#3355cc';

        // Last received info
        const lastReceivedHtml = received > 0
          ? `<div style="font-size:10px;color:#16a34a;margin-top:2px;font-weight:600;">
               +${fmtQty(received)} ${unit} received
             </div>`
          : lastReceived
            ? `<div style="font-size:10px;color:#9ca3af;margin-top:2px;">
                 Last: ${new Date(lastReceived).toLocaleDateString('en-GB',
                   { day:'numeric', month:'short' })}
               </div>`
            : '';

        return `
          <tr style="border-bottom:1px solid #f3f4f6;
            background:${idx % 2 === 0 ? '#fff' : '#fafafa'};">

            <!-- Item name -->
            <td style="padding:9px 14px;">
              <div style="font-size:12px;font-weight:600;color:#111;">${name}</div>
              ${lastReceivedHtml}
            </td>

            <!-- Unit -->
            <td style="padding:9px 14px;font-size:11px;color:#9ca3af;
              text-align:center;">${unit}</td>

            <!-- In stock — with toner progress bar -->
            <td style="padding:9px 14px;text-align:right;">
              <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                font-weight:700;color:${statusColor};">${fmtQty(closing)}</div>
              ${isToner ? `
                <div style="margin-top:4px;height:3px;background:#e5e7eb;
                  border-radius:2px;overflow:hidden;width:80px;margin-left:auto;">
                  <div style="height:100%;width:${barPct.toFixed(1)}%;
                    background:${barColor};border-radius:2px;"></div>
                </div>` : ''}
            </td>

            <!-- Reorder at -->
            <td style="padding:9px 14px;text-align:right;font-size:12px;
              color:#6b7280;font-family:'JetBrains Mono',monospace;">
              ${reorderPoint > 0 ? fmtQty(reorderPoint) : '—'}
            </td>

            <!-- Consumed -->
            <td style="padding:9px 14px;text-align:right;font-size:12px;
              font-family:'JetBrains Mono',monospace;
              color:${consumed > 0 ? '#dc2626' : '#9ca3af'};">
              ${consumed > 0 ? '-' + fmtQty(consumed) : '—'}
            </td>

            <!-- Status -->
            <td style="padding:9px 14px;text-align:center;">
              <span style="padding:2px 8px;border-radius:20px;font-size:10px;
                font-weight:700;background:${statusBg};color:${statusColor};">
                ${statusLabel}
              </span>
            </td>

          </tr>`;
      }).join('');

      return `
        <div style="margin-bottom:16px;border:1px solid #e5e7eb;
          border-radius:8px;overflow:hidden;">

          <!-- Category header -->
          <div style="display:flex;align-items:center;gap:8px;
            padding:8px 14px;
            background:${cfg.bg};
            border-bottom:2px solid ${cfg.strip};">
            <span style="color:${cfg.header};">${cfg.icon}</span>
            <span style="font-size:11px;font-weight:800;color:${cfg.header};
              text-transform:uppercase;letter-spacing:0.6px;">${cat}</span>
            <span style="font-size:10px;color:${cfg.header};opacity:0.5;margin-left:2px;">
              · ${catItems.length} item${catItems.length !== 1 ? 's' : ''}
            </span>
            ${lowCount > 0 ? `
              <span style="margin-left:auto;padding:1px 8px;border-radius:20px;
                font-size:9px;font-weight:700;background:#fee2e2;color:#dc2626;">
                ${lowCount} need${lowCount === 1 ? 's' : ''} attention
              </span>` : `
              <span style="margin-left:auto;padding:1px 8px;border-radius:20px;
                font-size:9px;font-weight:700;background:#dcfce7;color:#16a34a;">
                All good
              </span>`}
          </div>

          <!-- Table -->
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:#f9fafb;border-bottom:1px solid #e5e7eb;">
                <th style="padding:7px 14px;text-align:left;font-size:10px;
                  font-weight:700;color:#9ca3af;text-transform:uppercase;
                  letter-spacing:0.5px;">Item</th>
                <th style="padding:7px 14px;text-align:center;font-size:10px;
                  font-weight:700;color:#9ca3af;text-transform:uppercase;
                  letter-spacing:0.5px;">Unit</th>
                <th style="padding:7px 14px;text-align:right;font-size:10px;
                  font-weight:700;color:#9ca3af;text-transform:uppercase;
                  letter-spacing:0.5px;">In Stock</th>
                <th style="padding:7px 14px;text-align:right;font-size:10px;
                  font-weight:700;color:#9ca3af;text-transform:uppercase;
                  letter-spacing:0.5px;">Reorder At</th>
                <th style="padding:7px 14px;text-align:right;font-size:10px;
                  font-weight:700;color:#9ca3af;text-transform:uppercase;
                  letter-spacing:0.5px;">Consumed</th>
                <th style="padding:7px 14px;text-align:center;font-size:10px;
                  font-weight:700;color:#9ca3af;text-transform:uppercase;
                  letter-spacing:0.5px;">Status</th>
              </tr>
            </thead>
            <tbody>${rows}</tbody>
          </table>

        </div>`;
    }).join('');
  }

  function _toggleCurrentWeek() {
    const detail  = document.getElementById('current-week-detail');
    const chevron = document.getElementById('current-week-chevron');
    if (!detail) return;
    const isOpen = detail.style.display !== 'none';
    detail.style.display    = isOpen ? 'none' : 'block';
    chevron.style.transform = isOpen ? 'rotate(0deg)' : 'rotate(180deg)';
  }

  async function weeklyPrepare() {
    const btn = document.getElementById('weekly-prepare-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Preparing…'; }

    try {
      const res = await Auth.fetch('/api/v1/finance/weekly/prepare/', { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Could not prepare weekly report.', 'error');
        return;
      }
      const report = await res.json();
      const content = document.getElementById('weekly-content');
      if (content) _renderWeeklyReportDetail(content, report);
      _toast('Weekly filing prepared.', 'success');
    } catch {
      _toast('Network error.', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Prepare This Week'; }
    }
  }

  async function weeklySubmit(reportId) {
    const btn = document.getElementById('weekly-submit-btn');
    if (btn && btn.style.opacity === '0.4') return;
    if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }

    // Save notes first
    const notes = document.getElementById('weekly-notes')?.value.trim() || '';
    if (notes) {
      await Auth.fetch(`/api/v1/finance/weekly/${reportId}/notes/`, {
        method  : 'PATCH',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify({ bm_notes: notes }),
      }).catch(() => {});
    }

    try {
      const res = await Auth.fetch(`/api/v1/finance/weekly/${reportId}/submit/`, {
        method: 'POST',
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Submission failed.', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Submit & Lock Filing'; }
        return;
      }
      const report = await res.json();
      const content = document.getElementById('weekly-content');
      if (content) _renderWeeklyReportDetail(content, report);
      _toast('Weekly filing submitted and locked.', 'success');
    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Submit & Lock Filing'; }
    }
  }

  async function weeklyDownloadPDF(reportId) {
    try {
      const res = await Auth.fetch(`/api/v1/finance/weekly/${reportId}/pdf/`);
      if (!res.ok) { _toast('Could not generate PDF.', 'error'); return; }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = `weekly_report_${reportId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      _toast('Download failed.', 'error');
    }
  }

  // ── Jobs Archive (drill-down history) ─────────────────────
  let _historyLevel  = 'year';
  let _historyYear   = null;
  let _historyMonth  = null;
  let _historyWeek   = null;
  let _historyCharts = {};

  async function _renderHistoryReport(container) {
    _historyLevel = 'year';
    _historyYear  = null;
    _historyMonth = null;
    _historyWeek  = null;
    await _fetchAndRenderHistory(container);
  }

  async function _fetchAndRenderHistory(container) {
    if (!container) container = document.getElementById('performance-tab-content') || document.getElementById('reports-content');
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    // Destroy existing charts
    Object.values(_historyCharts).forEach(c => { try { c.destroy(); } catch {} });
    _historyCharts = {};

    // Build query params
    const params = new URLSearchParams({ level: _historyLevel });
    if (_historyYear)  params.set('year',  _historyYear);
    if (_historyMonth) params.set('month', _historyMonth);
    if (_historyWeek !== null) params.set('week', _historyWeek);

    try {
      const res  = await Auth.fetch(`/api/v1/jobs/history/?${params}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      _renderHistoryData(container, data);
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load history.</div>';
    }
  }

 function _renderHistoryData(container, data) {
    const fmt  = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
    const kpis = data.kpis || {};

    // ── Breadcrumb ────────────────────────────────────────────
    const crumbs = [{ label: 'All Years', level: 'year', year: null, month: null, week: null }];
    if (_historyYear)  crumbs.push({ label: String(_historyYear), level: 'month', year: _historyYear, month: null, week: null });
    if (_historyMonth) {
      const mn = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][_historyMonth-1];
      crumbs.push({ label: mn, level: 'week', year: _historyYear, month: _historyMonth, week: null });
    }
    if (_historyWeek !== null) crumbs.push({ label: `Week ${_historyWeek}`, level: 'day', year: _historyYear, month: _historyMonth, week: _historyWeek });

    const breadcrumbHtml = crumbs.map((c, i) => {
      const isLast = i === crumbs.length - 1;
      return isLast
        ? `<span style="font-size:13px;font-weight:700;color:var(--text);">${c.label}</span>`
        : `<span onclick="Dashboard._historyNav('${c.level}',${c.year},${c.month},${c.week})"
             style="font-size:13px;color:var(--text-3);cursor:pointer;transition:color 0.15s;"
             onmouseover="this.style.color='var(--text)'"
             onmouseout="this.style.color='var(--text-3)'">${c.label}</span>
           <span style="color:var(--border-dark);margin:0 6px;">›</span>`;
    }).join('');

    // ── Drill-down items ──────────────────────────────────────
    let itemsHtml = '';

    if (data.level === 'year' || data.level === 'month') {
      const heading = data.level === 'year' ? 'Years' : 'Months';
      itemsHtml = `
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
          letter-spacing:0.5px;margin-bottom:12px;">${heading}</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;margin-bottom:24px;">
          ${(data.items||[]).map((item, i) => {
            const colors = ['#1a1a2e','#6b47d9','#1a3a2e','#2e1a1a','#1a2e3a','#3a2e1a'];
            const bg = colors[i % colors.length];
            return `
            <div onclick="Dashboard._historyDrill(this)"
              data-item="${JSON.stringify(item).replace(/"/g,'&quot;')}"
              style="border:1px solid var(--border);border-radius:8px;overflow:hidden;
                     cursor:pointer;transition:all 0.15s;display:flex;height:64px;
                     box-shadow:0 1px 4px rgba(0,0,0,0.05);"
              onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 4px 12px rgba(0,0,0,0.1)'"
              onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='0 1px 4px rgba(0,0,0,0.05)'">

              <!-- Left — year -->
              <div style="
                background:${bg};
                background-image:repeating-linear-gradient(45deg,rgba(255,255,255,0.04) 0px,rgba(255,255,255,0.04) 1px,transparent 1px,transparent 7px);
                width:80px;flex-shrink:0;
                display:flex;align-items:center;justify-content:center;">
                <div style="font-family:'Outfit',sans-serif;font-size:18px;font-weight:800;
                  color:#fff;letter-spacing:-0.01em;">
                  ${item.label}
                </div>
              </div>

              <!-- Right — stats -->
              <div style="background:var(--panel);flex:1;padding:0 14px;
                display:flex;align-items:center;gap:20px;">
                <div>
                  <div style="font-size:13px;font-weight:700;color:var(--text);">${item.total} jobs</div>
                  <div style="font-size:11px;color:var(--text-3);font-family:'JetBrains Mono',monospace;">${fmt(item.revenue)}</div>
                </div>
                <div style="flex:1;">
                  <div style="height:3px;background:var(--border);border-radius:2px;">
                    <div style="height:100%;width:${item.rate}%;background:var(--green-text);border-radius:2px;"></div>
                  </div>
                  <div style="font-size:10px;color:var(--text-3);margin-top:3px;font-family:'JetBrains Mono',monospace;">${item.rate}% complete</div>
                </div>
              </div>

            </div>`;
          }).join('')}
        </div>`;

    } else if (data.level === 'week') {
      itemsHtml = `
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
          letter-spacing:0.5px;margin-bottom:12px;">Weeks</div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
          overflow:hidden;margin-bottom:24px;">
          ${(data.items||[]).map(item => `
            <div onclick="Dashboard._historyDrill(this)"
              data-item="${JSON.stringify(item).replace(/"/g,'&quot;')}"
              style="display:flex;align-items:center;justify-content:space-between;
                     padding:14px 20px;border-bottom:1px solid var(--border);cursor:pointer;
                     transition:background 0.12s;"
              onmouseover="this.style.background='var(--bg)'"
              onmouseout="this.style.background=''">
              <div>
                <div style="font-size:14px;font-weight:700;color:var(--text);">${item.label}</div>
                <div style="font-size:11px;color:var(--text-3);margin-top:2px;font-family:'JetBrains Mono',monospace;">
                  ${item.start} → ${item.end}
                </div>
              </div>
              <div style="display:flex;align-items:center;gap:24px;">
                <div style="text-align:right;">
                  <div style="font-size:13px;font-weight:600;color:var(--text);">${item.total} jobs</div>
                  <div style="font-size:12px;color:var(--text-3);">${fmt(item.revenue)}</div>
                </div>
                <div style="font-size:12px;color:var(--green-text);font-weight:600;min-width:40px;text-align:right;">
                  ${item.rate}%
                </div>
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24"
                  fill="none" stroke="currentColor" stroke-width="2" style="color:var(--text-3);">
                  <polyline points="9 18 15 12 9 6"/>
                </svg>
              </div>
            </div>`).join('')}
        </div>`;

    } else if (data.level === 'day') {
      itemsHtml = `
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
          letter-spacing:0.5px;margin-bottom:12px;">Days</div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
          overflow:hidden;margin-bottom:24px;">
          <table class="p-table">
            <thead>
              <tr>
                <th>Day</th>
                <th>Jobs</th>
                <th>Complete</th>
                <th>Pending</th>
                <th>Revenue</th>
                <th>Sheet</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${(data.items||[]).map(item => `
                <tr>
                  <td style="font-weight:600;color:var(--text);">${item.label}</td>
                  <td>${item.total}</td>
                  <td style="color:var(--green-text);font-weight:600;">${item.complete}</td>
                  <td style="color:var(--amber-text);">${item.pending}</td>
                  <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${fmt(item.revenue)}</td>
                  <td>
                    ${item.sheet_status
                      ? `<span class="badge badge-${item.sheet_status==='OPEN'?'progress':'done'}">${item.sheet_status}</span>`
                      : '<span style="color:var(--text-3);font-size:12px;">No sheet</span>'}
                  </td>
                  <td>
                    ${item.sheet_id && item.sheet_status !== 'OPEN'
                      ? `<button onclick="Dashboard.downloadSheetPDF(${item.sheet_id},'${item.date}')"
                           style="font-size:12px;color:var(--text-2);background:none;border:none;
                                  cursor:pointer;font-weight:600;padding:0;">PDF ↓</button>`
                      : '—'}
                  </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    }

    // ── KPI cards (compact with % change) ─────────────────────
const kpiCards = [
      { key:'total',   label:'Total Jobs', value: kpis.total?.value   || 0, fmt: v => v,       border:'#3355cc', text:'#3355cc' },
      { key:'revenue', label:'Revenue',    value: kpis.revenue?.value || 0, fmt: v => fmt(v),  border:'#22c98a', text:'#22c98a' },
      { key:'pending', label:'Pending',    value: kpis.pending?.value || 0, fmt: v => v,       border:'#e8a820', text:'#e8a820' },
      { key:'rate',    label:'Completion', value: kpis.rate?.value    || 0, fmt: v => v + '%', border:'#9b59b6', text:'#9b59b6' },
    ];

    const kpiHtml = `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:20px;">
        ${kpiCards.map(k => {
          const change = kpis[k.key]?.change;
          const isPos  = change?.startsWith('+');
          const isNeg  = change?.startsWith('-');
          return `
            <div style="background:var(--panel);border:1px solid var(--border);
              border-top:3px solid ${k.border};
              border-radius:8px;padding:10px 12px;">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                ${k.label}
              </div>
              <div style="font-size:17px;font-weight:800;color:${k.text};
                font-family:'Outfit',sans-serif;letter-spacing:-0.01em;margin-bottom:3px;">
                ${k.fmt(k.value)}
              </div>
              ${change ? `
                <div style="font-size:9px;font-weight:700;font-family:'JetBrains Mono',monospace;
                  color:${isPos ? '#22c98a' : isNeg ? '#e8294a' : 'var(--text-3)'};">
                  ${isPos ? '↑' : isNeg ? '↓' : ''} ${change} vs prev
                </div>` : `
                <div style="font-size:9px;color:var(--text-3);">no prev data</div>`}
            </div>`;
        }).join('')}
      </div>`;

    // ── Charts ────────────────────────────────────────────────
    const chartsHtml = `
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
        padding:20px;margin-bottom:16px;">
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
          letter-spacing:0.5px;margin-bottom:16px;">📈 Trend</div>
        <canvas id="history-trend-chart" height="70"></canvas>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:20px;">
          <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;margin-bottom:16px;">📊 Distribution</div>
          <canvas id="history-bar-chart" height="140"></canvas>
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:20px;">
          <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;margin-bottom:16px;">🔥 Activity Heatmap</div>
          <div id="history-heatmap"></div>
        </div>
      </div>`;

    // ── Assemble in new order ─────────────────────────────────
    container.innerHTML = `
      <div style="display:flex;align-items:center;gap:4px;margin-bottom:20px;flex-wrap:wrap;">
        ${breadcrumbHtml}
      </div>
      ${itemsHtml}
      ${kpiHtml}
      ${chartsHtml}`;

    _drawHistoryCharts(data);
  }

  function _drawHistoryCharts(data) {
    // Load Chart.js if not already loaded
    if (typeof Chart === 'undefined') {
      const script   = document.createElement('script');
      script.src     = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
      script.onload  = () => _drawHistoryCharts(data);
      document.head.appendChild(script);
      return;
    }

    const textColor   = getComputedStyle(document.documentElement)
      .getPropertyValue('--text-3').trim() || '#999';
    const borderColor = getComputedStyle(document.documentElement)
      .getPropertyValue('--border').trim() || '#eee';

    // Trend chart
    const trendCtx = document.getElementById('history-trend-chart');
    if (trendCtx && data.trend) {
      _historyCharts.trend = new Chart(trendCtx, {
        type: 'line',
        data: {
          labels  : data.trend.labels,
          datasets: [
            {
              label          : 'Jobs',
              data           : data.trend.jobs,
              borderColor    : '#3355cc',
              backgroundColor: 'rgba(51,85,204,0.08)',
              tension        : 0.4,
              fill           : true,
              yAxisID        : 'y',
            },
            {
              label          : 'Revenue (GHS)',
              data           : data.trend.revenue,
              borderColor    : '#22c98a',
              backgroundColor: 'rgba(34,201,138,0.08)',
              tension        : 0.4,
              fill           : true,
              yAxisID        : 'y1',
            },
          ],
        },
        options: {
          responsive : true,
          interaction: { mode: 'index', intersect: false },
          plugins    : { legend: { labels: { color: textColor, font: { size: 11 } } } },
          scales     : {
            x : { ticks: { color: textColor, font: { size: 10 } }, grid: { color: borderColor } },
            y : { ticks: { color: textColor, font: { size: 10 } }, grid: { color: borderColor }, position: 'left' },
            y1: { ticks: { color: textColor, font: { size: 10 } }, grid: { display: false }, position: 'right' },
          },
        },
      });
    }

    // Bar chart
    const barCtx = document.getElementById('history-bar-chart');
    if (barCtx && data.bar) {
      _historyCharts.bar = new Chart(barCtx, {
        type: 'bar',
        data: {
          labels  : data.bar.labels,
          datasets: [{
            label          : 'Jobs',
            data           : data.bar.data,
            backgroundColor: 'rgba(51,85,204,0.7)',
            borderRadius   : 4,
          }],
        },
        options: {
          responsive: true,
          plugins   : { legend: { display: false } },
          scales    : {
            x: { ticks: { color: textColor, font: { size: 10 } }, grid: { display: false } },
            y: { ticks: { color: textColor, font: { size: 10 } }, grid: { color: borderColor } },
          },
        },
      });
    }

    // Heatmap
    _drawHeatmap(data);
  }

  function _drawHeatmap(data) {
    const el = document.getElementById('history-heatmap');
    if (!el || !data.heatmap) return;

    // Flatten heatmap to get max value for color scaling
    let items = [];
    if (data.level === 'day') {
      // Array of {date, hours:[{hour,count}]}
      data.heatmap.forEach(day => {
        day.hours.forEach(h => items.push(h.count));
      });
    } else {
      // Array of {week, count}
      items = data.heatmap.map(w => (typeof w === 'object' && w.count !== undefined) ? w.count : 0);
    }
    const max = Math.max(...items, 1);

    const cellSize = 14;
    const gap      = 2;

    if (data.level === 'day') {
      // Hour × Day grid
      const days  = data.heatmap;
      const hours = Array.from({length:12}, (_,i) => i + 8);
      let html = `
        <div style="overflow-x:auto;">
          <table style="border-collapse:separate;border-spacing:${gap}px;font-size:9px;color:var(--text-3);">
            <thead>
              <tr>
                <td></td>
                ${days.map(d => `<td style="text-align:center;padding-bottom:4px;">
                  ${new Date(d.date).toLocaleDateString('en-GB',{weekday:'short'})}</td>`).join('')}
              </tr>
            </thead>
            <tbody>
              ${hours.map(h => `
                <tr>
                  <td style="padding-right:6px;text-align:right;">${h}h</td>
                  ${days.map(d => {
                    const hdata = d.hours.find(x => x.hour === h);
                    const count = hdata?.count || 0;
                    const alpha = count ? 0.15 + (count / max) * 0.85 : 0.05;
                    return `<td title="${count} jobs" style="width:${cellSize}px;height:${cellSize}px;
                      border-radius:2px;background:rgba(51,85,204,${alpha.toFixed(2)});cursor:default;"></td>`;
                  }).join('')}
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
      el.innerHTML = html;
    } else {
      // Week grid — 52 weeks × 1 row or monthly grid
      const weeks = data.heatmap;
      let html = '<div style="display:flex;flex-wrap:wrap;gap:2px;">';
      weeks.forEach(w => {
        const count = Array.isArray(w) ? w.reduce((s,d) => s + d.count, 0) : (w.count || 0);
        const alpha = count ? 0.15 + (count / max) * 0.85 : 0.05;
        html += `<div title="${count} jobs" style="width:${cellSize}px;height:${cellSize}px;
          border-radius:2px;background:rgba(51,85,204,${alpha.toFixed(2)});"></div>`;
      });
      html += '</div>';
      el.innerHTML = html;
    }
  }

  function _historyDrill(elOrItem) {
    let item = elOrItem;
    if (elOrItem instanceof HTMLElement) {
      try { item = JSON.parse(elOrItem.dataset.item.replace(/&quot;/g, '"')); } catch { return; }
    } else if (typeof elOrItem === 'string') {
      try { item = JSON.parse(elOrItem.replace(/&quot;/g, '"')); } catch { return; }
    }
    _historyYear  = item.year  || _historyYear;
    _historyMonth = item.month || null;
    _historyWeek  = item.week  !== undefined ? item.week : null;

    if (_historyMonth && _historyWeek !== null) {
      _historyLevel = 'day';
    } else if (_historyMonth) {
      _historyLevel = 'week';
    } else if (_historyYear) {
      _historyLevel = 'month';
    }

    const container = document.getElementById('performance-tab-content') || document.getElementById('reports-content');
    _fetchAndRenderHistory(container);
  }

  function _historyNav(level, year, month, week) {
    _historyLevel = level;
    _historyYear  = year;
    _historyMonth = month;
    _historyWeek  = week;
    const container = document.getElementById('performance-tab-content') || document.getElementById('reports-content');
    _fetchAndRenderHistory(container);
  }
  async function downloadSheetPDF(sheetId, sheetDate) {
    try {
      const res = await Auth.fetch(`/api/v1/finance/sheets/${sheetId}/pdf/`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Could not download PDF.', 'error');
        return;
      }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = `sheet_NTB_${sheetDate}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      _toast('Network error downloading PDF.', 'error');
    }
  }
  // ── PIN Modal ──────────────────────────────────────────────
  let _pinSheetId   = null;
  let _pinSheetDate = null;
  let _pinAttempts  = 0;
  const MAX_ATTEMPTS = 3;

  async function initiateSheetDownload(sheetId, sheetDate) {
    _pinSheetId   = sheetId;
    _pinSheetDate = sheetDate;
    _pinAttempts  = 0;

    // Check if PIN is set
    const user = Auth.getUser();
    const hasPinSet = user?.download_pin_set;

    _set('pin-modal-subtitle', `Sheet · ${sheetDate}`);

    if (!hasPinSet) {
      // Need to re-fetch to get latest pin status
      const res = await Auth.fetch('/api/v1/accounts/me/');
      if (res?.ok) {
        const fresh = await res.json();
        Auth.setUser(fresh);
        if (!fresh.download_pin_set) {
          _showPinState('set');
          document.getElementById('pin-modal-title').textContent = 'Set Download PIN';
          document.getElementById('pin-modal').classList.add('open');
          setTimeout(() => document.getElementById('pin-set-input')?.focus(), 100);
          return;
        }
      }
    }

    _showPinState('verify');
    document.getElementById('pin-modal-title').textContent = 'Enter PIN';
    document.getElementById('pin-modal').classList.add('open');
    setTimeout(() => document.getElementById('pin-verify-input')?.focus(), 100);
  }

  function _showPinState(state) {
    document.getElementById('pin-set-state').style.display    = state === 'set'    ? 'block' : 'none';
    document.getElementById('pin-verify-state').style.display = state === 'verify' ? 'block' : 'none';
  }

  function _onPinInput(type) {
    if (type === 'verify') {
      const val = document.getElementById('pin-verify-input').value;
      for (let i = 0; i < 4; i++) {
        const dot = document.getElementById(`pin-dot-${i}`);
        if (dot) dot.style.background = i < val.length ? 'var(--text)' : 'var(--border)';
      }
    } else if (type === 'set') {
      const val = document.getElementById('pin-set-input').value;
      for (let i = 0; i < 4; i++) {
        const dot = document.getElementById(`pin-set-dot-${i}`);
        if (dot) dot.style.background = i < val.length ? 'var(--text)' : 'var(--border)';
      }
    }
  }

  async function _submitPin() {
    const btn = document.getElementById('pin-submit-btn');
    const isSetState = document.getElementById('pin-set-state').style.display !== 'none';

    btn.disabled = true;
    btn.textContent = 'Checking…';

    if (isSetState) {
      await _handleSetPin(btn);
    } else {
      await _handleVerifyPin(btn);
    }
  }

  async function _handleSetPin(btn) {
    const pin        = document.getElementById('pin-set-input')?.value.trim();
    const confirmPin = document.getElementById('pin-confirm-input')?.value.trim();
    const errorEl    = document.getElementById('pin-set-error');

    errorEl.style.display = 'none';

    if (!pin || pin.length !== 4 || !/^\d{4}$/.test(pin)) {
      errorEl.textContent    = 'PIN must be exactly 4 digits.';
      errorEl.style.display  = 'block';
      btn.disabled = false;
      btn.textContent = 'Confirm';
      return;
    }

    if (pin !== confirmPin) {
      errorEl.textContent    = 'PINs do not match.';
      errorEl.style.display  = 'block';
      btn.disabled = false;
      btn.textContent = 'Confirm';
      return;
    }

    try {
      const res = await Auth.fetch('/api/v1/accounts/pin/set/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ pin, confirm_pin: confirmPin }),
      });

      if (res.ok) {
        // Update cached user
        const userRes = await Auth.fetch('/api/v1/accounts/me/');
        if (userRes?.ok) Auth.setUser(await userRes.json());

        _toast('Download PIN set successfully.', 'success');
        closePinModal();

        // Now proceed to verify
        setTimeout(() => initiateSheetDownload(_pinSheetId, _pinSheetDate), 300);
      } else {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent   = err.detail || 'Could not set PIN.';
        errorEl.style.display = 'block';
        btn.disabled    = false;
        btn.textContent = 'Confirm';
      }
    } catch {
      const errorEl = document.getElementById('pin-set-error');
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
      btn.disabled    = false;
      btn.textContent = 'Confirm';
    }
  }

  async function _handleVerifyPin(btn) {
    const pin     = document.getElementById('pin-verify-input')?.value.trim();
    const errorEl = document.getElementById('pin-verify-error');
    const attemptsEl = document.getElementById('pin-attempts');

    errorEl.style.display = 'none';

    if (!pin || pin.length !== 4) {
      errorEl.textContent   = 'Please enter your 4-digit PIN.';
      errorEl.style.display = 'block';
      btn.disabled    = false;
      btn.textContent = 'Confirm';
      return;
    }

    try {
      const res = await Auth.fetch('/api/v1/accounts/pin/verify/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ pin, sheet_id: _pinSheetId }),
      });

      if (res.ok) {
        closePinModal();
        _toast('PIN verified. Downloading…', 'success');
        await downloadSheetPDF(_pinSheetId, _pinSheetDate);
      } else {
        _pinAttempts++;
        const remaining = MAX_ATTEMPTS - _pinAttempts;

        // Shake animation
        const input = document.getElementById('pin-verify-input');
        if (input) {
          input.style.borderColor = 'var(--red-text)';
          input.value = '';
          for (let i = 0; i < 4; i++) {
            const dot = document.getElementById(`pin-dot-${i}`);
            if (dot) dot.style.background = 'var(--border)';
          }
          setTimeout(() => { input.style.borderColor = 'var(--border)'; }, 600);
          setTimeout(() => input.focus(), 100);
        }

        if (_pinAttempts >= MAX_ATTEMPTS) {
          errorEl.textContent   = 'Too many incorrect attempts. Please try again later.';
          errorEl.style.display = 'block';
          attemptsEl.textContent = '';
          btn.disabled = true;
          btn.textContent = 'Locked';
        } else {
          errorEl.textContent   = 'Incorrect PIN.';
          errorEl.style.display = 'block';
          attemptsEl.textContent = `${remaining} attempt${remaining !== 1 ? 's' : ''} remaining`;
          btn.disabled    = false;
          btn.textContent = 'Confirm';
        }
      }
    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
      btn.disabled    = false;
      btn.textContent = 'Confirm';
    }
  }

  function closePinModal() {
    document.getElementById('pin-modal').classList.remove('open');
    const pinVerifyInput = document.getElementById('pin-verify-input');
    const pinSetInput    = document.getElementById('pin-set-input');
    const pinConfirmInput = document.getElementById('pin-confirm-input');
    if (pinVerifyInput)  pinVerifyInput.value  = '';
    if (pinSetInput)     pinSetInput.value     = '';
    if (pinConfirmInput) pinConfirmInput.value = '';
    for (let i = 0; i < 4; i++) {
      const dot    = document.getElementById(`pin-dot-${i}`);
      const setDot = document.getElementById(`pin-set-dot-${i}`);
      if (dot)    dot.style.background    = 'var(--border)';
      if (setDot) setDot.style.background = 'var(--border)';
    }
    _pinAttempts = 0;
  }

  // ── Add Service Modal ─────────────────────────────────────────────────
  let _consumables = [];

  async function openAddServiceModal() {
    // Reset form
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

    // Load consumables if not already loaded
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

    const mappableConsumables = _consumables.filter(c =>
      !c.name.toLowerCase().includes('toner')
    );

    if (!mappableConsumables.length) {
      container.innerHTML = '<div class="eod-empty-note">No consumables found.</div>';
      return;
    }

    container.innerHTML = mappableConsumables.map((c, i) => `
      <div style="display:grid;grid-template-columns:auto 1fr auto auto auto;
        align-items:center;gap:10px;padding:8px 0;
        border-bottom:1px solid var(--border);">

        <input type="checkbox" id="svc-con-check-${i}"
          onchange="Dashboard._svcToggleConsumable(${i})"
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
            border-radius:var(--radius-sm);color:var(--text);
            opacity:0.4;">

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

      </div>
    `).join('');
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

    const name     = document.getElementById('svc-name').value.trim();
    const code     = document.getElementById('svc-code').value.trim().toUpperCase();
    const category = document.getElementById('svc-category').value;
    const unit     = document.getElementById('svc-unit').value;
    const price    = document.getElementById('svc-price').value.trim();
    const desc     = document.getElementById('svc-description').value.trim();
    const imageFile = document.getElementById('svc-image').files[0];

    // Validate
    if (!name)  { _showSvcError('Service name is required.'); return; }
    if (!code)  { _showSvcError('Service code is required.'); return; }
    if (!price || isNaN(parseFloat(price)) || parseFloat(price) < 0) {
      _showSvcError('A valid base price is required.'); return;
    }

    // Build consumable mappings
    const mappings = [];
    const mappableConsumables = _consumables.filter(c =>
      !c.name.toLowerCase().includes('toner')
    );
    mappableConsumables.forEach((c, i) => {
      const checked = document.getElementById(`svc-con-check-${i}`)?.checked;
      if (!checked) return;
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

    // Build FormData (multipart for image upload)
    const sides = document.getElementById('svc-sides').value;

    const fd = new FormData();
    fd.append('name',        name);
    fd.append('code',        code);
    fd.append('category',    category);
    fd.append('unit',        unit);
    fd.append('base_price',  price);
    fd.append('description', desc);
    fd.append('sides',       sides);
    if (imageFile) fd.append('image', imageFile);
    if (mappings.length) {
      fd.append('consumable_mappings', JSON.stringify(mappings));
    }

    btn.disabled       = true;
    btn.textContent    = 'Saving…';

    try {
      const res = await Auth.fetch('/api/v1/jobs/services/create/', {
        method : 'POST',
        body   : fd,
      });

      const data = await res.json();

      if (!res.ok) {
        console.error('Service create error:', JSON.stringify(data));
        const msg = Object.values(data).flat().join(' ');
        _showSvcError(msg || 'Failed to save service.');
        return;
      }

      // Success — add to local services array and re-render grid
      services.push(data);
      if (typeof State !== 'undefined') State.services = services;
      _set('meta-services', services.length);
      _set('meta-services-count', `${services.length} services`);
      svcLoaded = false; // force re-render
      loadServicesTab();

      closeAddServiceModal();
      _toast(`Service "${data.name}" added successfully.`, 'success');

    } catch {
      _showSvcError('Network error. Please try again.');
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Save Service';
    }
  }

  function _showSvcError(msg) {
    const err = document.getElementById('svc-error');
    err.textContent    = msg;
    err.style.display  = 'block';
  }

  // ── Invoices pane ─────────────────────────────────────────
  let _invoicesLoaded = false;

  async function _loadInvoicesPane() {
    _invoicesLoaded = true;
    const container = document.getElementById('invoices-content');
    if (!container) return;

    try {
      const res  = await Auth.fetch('/api/v1/finance/invoices/');
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const invoices = Array.isArray(data) ? data : (data.results || []);

      if (!invoices.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:48px;color:var(--text-3);font-size:13px;">
            No invoices yet. Create one to get started.
          </div>`;
        return;
      }

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH', {minimumFractionDigits:2})}`;

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table class="p-table">
            <thead>
              <tr>
                <th>Invoice No</th>
                <th>Type</th>
                <th>Bill To</th>
                <th>Amount</th>
                <th>Status</th>
                <th>Date</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              ${invoices.map(inv => `
                <tr>
                  <td>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;">
                      ${_esc(inv.invoice_number)}
                    </div>
                  </td>
                  <td>
                    <span class="badge ${inv.invoice_type === 'PROFORMA' ? 'badge-production' : 'badge-instant'}">
                      ${inv.invoice_type}
                    </span>
                  </td>
                  <td>
                    <div style="font-weight:600;font-size:13px;">${_esc(inv.bill_to_name || '—')}</div>
                    ${inv.bill_to_company ? `<div style="font-size:11px;color:var(--text-3);">${_esc(inv.bill_to_company)}</div>` : ''}
                  </td>
                  <td style="font-family:'JetBrains Mono',monospace;font-weight:600;">
                    ${fmt(inv.total)}
                  </td>
                  <td>
                    <span class="badge ${_invoiceStatusBadge(inv.status)}">
                      ${inv.status}
                    </span>
                  </td>
                  <td style="font-size:12px;color:var(--text-3);">
                    ${inv.issue_date ? new Date(inv.issue_date).toLocaleDateString('en-GH') : '—'}
                  </td>
                  <td>
                    <button onclick="Dashboard.downloadInvoicePDF(${inv.id}, '${_esc(inv.invoice_number)}')"
                      style="padding:5px 12px;font-size:12px;font-weight:600;
                        background:var(--bg);border:1px solid var(--border);
                        border-radius:var(--radius-sm);cursor:pointer;
                        font-family:'DM Sans',sans-serif;color:var(--text-2);
                        transition:all 0.15s;"
                      onmouseover="this.style.borderColor='var(--border-dark)'"
                      onmouseout="this.style.borderColor='var(--border)'">
                      ↓ PDF
                    </button>
                  </td>
                </tr>
              `).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      container.innerHTML = `<div class="loading-cell">Could not load invoices.</div>`;
    }
  }

  function _invoiceStatusBadge(status) {
    return {
      'DRAFT'  : 'badge-draft',
      'SENT'   : 'badge-progress',
      'VIEWED' : 'badge-pending',
      'PAID'   : 'badge-done',
    }[status] || 'badge-draft';
  }

  async function downloadInvoicePDF(id, invoiceNumber) {
    try {
      const res = await Auth.fetch(`/api/v1/finance/invoices/${id}/pdf/`);
      if (!res.ok) { _toast('Could not download PDF.', 'error'); return; }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href     = url;
      a.download = `${invoiceNumber}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      _toast('Download failed.', 'error');
    }
  }

  function openCreateInvoice() {
    _toast('Invoice creation coming soon.', 'info');
  }

  // ── Late Job ──────────────────────────────────────────────────
  function openLateJobModal() {
    document.getElementById('late-job-reason').value    = '';
    document.getElementById('late-job-svc-search').value= '';
    document.getElementById('late-job-svc-id').value   = '';
    document.getElementById('late-job-pages').value     = '1';
    document.getElementById('late-job-sets').value      = '1';
    document.getElementById('late-job-color').value     = 'false';
    document.getElementById('late-job-error').style.display = 'none';
    document.getElementById('late-job-svc-dropdown').style.display = 'none';
    document.getElementById('late-job-overlay').classList.add('open');
  }

  function closeLateJobModal() {
    document.getElementById('late-job-overlay').classList.remove('open');
  }

  function _lateJobFilterServices() {
    const query    = document.getElementById('late-job-svc-search').value.toLowerCase();
    const dropdown = document.getElementById('late-job-svc-dropdown');
    const filtered = services.filter(s =>
      s.name.toLowerCase().includes(query)
    );
    if (!filtered.length) { dropdown.style.display = 'none'; return; }
    dropdown.innerHTML = filtered.map(s => `
      <div onclick="Dashboard._lateJobSelectService(${s.id}, '${_esc(s.name)}')"
        style="padding:9px 12px;font-size:13px;cursor:pointer;
               border-bottom:1px solid var(--border);"
        onmouseover="this.style.background='var(--bg)'"
        onmouseout="this.style.background=''">
        <div style="font-weight:600;color:var(--text);">${_esc(s.name)}</div>
        <div style="font-size:11px;color:var(--text-3);">${s.category}</div>
      </div>
    `).join('');
    dropdown.style.display = 'block';
  }

  function _lateJobSelectService(id, name) {
    document.getElementById('late-job-svc-id').value    = id;
    document.getElementById('late-job-svc-search').value= name;
    document.getElementById('late-job-svc-dropdown').style.display = 'none';
  }

  async function submitLateJob() {
    const btn    = document.getElementById('late-job-submit-btn');
    const err    = document.getElementById('late-job-error');
    err.style.display = 'none';

    const reason  = document.getElementById('late-job-reason').value.trim();
    const svcId   = document.getElementById('late-job-svc-id').value;
    const pages   = parseInt(document.getElementById('late-job-pages').value) || 1;
    const sets    = parseInt(document.getElementById('late-job-sets').value)  || 1;
    const isColor = document.getElementById('late-job-color').value === 'true';

    if (!reason) { err.textContent = 'Reason is required.'; err.style.display = 'block'; return; }
    if (!svcId)  { err.textContent = 'Please select a service.'; err.style.display = 'block'; return; }

    btn.disabled    = true;
    btn.textContent = 'Recording…';

    try {
      const res = await Auth.fetch('/api/v1/jobs/late/', {
        method  : 'POST',
        headers : { 'Content-Type': 'application/json' },
        body    : JSON.stringify({
          post_closing_reason : reason,
          line_items          : [{
            service  : parseInt(svcId),
            pages,
            sets,
            is_color : isColor,
          }],
        }),
      });

      const data = await res.json();
      if (!res.ok) {
        err.textContent   = data.detail || Object.values(data).flat().join(' ');
        err.style.display = 'block';
        return;
      }

      closeLateJobModal();
      _toast(`Late job ${data.job_number} recorded and sent to cashier.`, 'success');

    } catch {
      err.textContent   = 'Network error. Please try again.';
      err.style.display = 'block';
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Record Late Job';
    }
  }

  function _checkLateJobButton() {
    const btn = document.getElementById('late-job-btn');
    if (!btn) return;
    const now     = new Date();
    const hours   = now.getHours();
    const minutes = now.getMinutes();
    // Show after 19:30
    const isPastClosing = hours > 19 || (hours === 19 && minutes >= 30);
    btn.style.display = isPastClosing ? 'inline-flex' : 'none';
  }

  // ── Closing time warning ───────────────────────────────────
  let _closingWarnShown = false;

  function _checkClosingWarning() {
    const now     = new Date();
    const hours   = now.getHours();
    const minutes = now.getMinutes();

    // Show at 19:00 (30 mins before 19:30 closing)
    const isWarningTime = hours === 19 && minutes >= 0 && minutes < 30;
    if (!isWarningTime || _closingWarnShown) return;

    // Don't interrupt if a modal is open
    const openModals = document.querySelectorAll(
      '.modal-overlay.open, .eod-overlay.open'
    );
    if (openModals.length > 0) return;

    _closingWarnShown = true;
    _showClosingModal();
  }

  function _showClosingModal() {
    const existing = document.getElementById('closing-warn-overlay');
    if (existing) existing.remove();

    const overlay = document.createElement('div');
    overlay.id    = 'closing-warn-overlay';
    overlay.style.cssText = `
      position:fixed;inset:0;z-index:9998;
      background:rgba(0,0,0,0.85);
      display:flex;align-items:center;justify-content:center;
      font-family:'DM Sans',sans-serif;
      animation:fadeIn 0.3s ease;`;

    overlay.innerHTML = `
      <div style="
        background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);width:100%;max-width:480px;
        padding:32px;text-align:center;
        box-shadow:0 24px 64px rgba(0,0,0,0.4);">

        <!-- Icon -->
        <div style="width:64px;height:64px;border-radius:50%;
          background:var(--amber-bg);border:2px solid var(--amber-border);
          display:flex;align-items:center;justify-content:center;
          margin:0 auto 20px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28"
            viewBox="0 0 24 24" fill="none"
            stroke="var(--amber-text)" stroke-width="2">
            <circle cx="12" cy="12" r="10"/>
            <polyline points="12 6 12 12 16 14"/>
          </svg>
        </div>

        <!-- Title -->
        <div style="font-family:'Syne',sans-serif;font-size:22px;
          font-weight:800;color:var(--text);margin-bottom:8px;">
          30 Minutes to Closing
        </div>
        <div style="font-size:14px;color:var(--text-3);margin-bottom:8px;">
          Branch closes at <strong style="color:var(--text);">7:30 PM</strong> today.
        </div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:28px;">
          Ensure all jobs are processed and the cashier is prepared for end-of-day sign-off.
        </div>

        <!-- Countdown -->
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">
          Auto-dismissing in <span id="closing-warn-countdown"
            style="font-weight:700;color:var(--amber-text);">15</span>s
        </div>

        <!-- Dismiss button -->
        <button onclick="document.getElementById('closing-warn-overlay').remove()"
          style="padding:10px 28px;background:var(--text);color:#fff;border:none;
            border-radius:var(--radius-sm);font-size:14px;font-weight:700;
            cursor:pointer;font-family:'DM Sans',sans-serif;">
          Dismiss
        </button>
      </div>`;

    document.body.appendChild(overlay);

    // Auto-dismiss after 15 seconds
    let count = 15;
    const timer = setInterval(() => {
      count--;
      const el = document.getElementById('closing-warn-countdown');
      if (el) el.textContent = count;
      if (count <= 0) {
        clearInterval(timer);
        overlay.remove();
      }
    }, 1000);
  }
// ── Customers pane ────────────────────────────────────────
  let _customersTab = 'all';

  async function _loadCustomersPane() {
    const pane = document.getElementById('pane-customers');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Customers</span>
        <button onclick="Dashboard.openAddCustomerModal()"
          style="padding:7px 16px;background:var(--text);color:#fff;border:none;
            border-radius:var(--radius-sm);font-size:13px;font-weight:700;
            cursor:pointer;font-family:'DM Sans',sans-serif;">
          + Add Customer
        </button>
      </div>

      <div class="reports-tabs" id="customers-tab-bar">
        <button class="reports-tab active" data-tab="all"
          onclick="Dashboard.switchCustomersTab('all')">All</button>
        <button class="reports-tab" data-tab="individuals"
          onclick="Dashboard.switchCustomersTab('individuals')">Individuals</button>
        <button class="reports-tab" data-tab="businesses"
          onclick="Dashboard.switchCustomersTab('businesses')">Businesses</button>
        <button class="reports-tab" data-tab="institutions"
          onclick="Dashboard.switchCustomersTab('institutions')">Institutions</button>
        <button class="reports-tab" data-tab="credit"
          onclick="Dashboard.switchCustomersTab('credit')">Credit Accounts</button>
      </div>

      <div id="customers-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    await _loadCustomersTab('all');
  }

  async function switchCustomersTab(tab) {
    _customersTab = tab;
    document.querySelectorAll('#customers-tab-bar .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    await _loadCustomersTab(tab);
  }

  async function _loadCustomersTab(tab) {
    const content = document.getElementById('customers-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    if (tab === 'all')          await _renderCustomerList(content, {});
    if (tab === 'individuals')  await _renderCustomerList(content, { customer_type: 'INDIVIDUAL' });
    if (tab === 'businesses')   await _renderCustomerList(content, { customer_type: 'BUSINESS' });
    if (tab === 'institutions') await _renderCustomerList(content, { customer_type: 'INSTITUTION' });
    if (tab === 'credit')       await _renderCreditCustomers(content);
  }

  async function _renderCustomerList(container, filters = {}) {
    try {
      const params = new URLSearchParams(filters);
      const res    = await Auth.fetch(`/api/v1/customers/?${params}`);
      if (!res.ok) throw new Error();
      const data      = await res.json();
      const customers = Array.isArray(data) ? data : (data.results || []);

      if (!customers.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"
              viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.5" style="opacity:0.3;display:block;margin:0 auto 12px;">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
              <circle cx="9" cy="7" r="4"/>
            </svg>
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">
              No customers found</div>
            <div style="font-size:13px;">Add your first customer to get started.</div>
          </div>`;
        return;
      }

      const typeConfig = {
        INDIVIDUAL : { label: 'Individual',   bg: '#f0f4fd', color: '#2e4a8a' },
        BUSINESS   : { label: 'Business',     bg: '#f0fdf4', color: '#1a6b3a' },
        INSTITUTION: { label: 'Institution',  bg: '#f5f0fd', color: '#5a2e8a' },
      };

      const tierConfig = {
        REGULAR  : { label: 'Regular',   bg: 'var(--bg)',       color: 'var(--text-3)' },
        PREFERRED: { label: 'Preferred', bg: '#fef3c7',         color: '#d97706'       },
        VIP      : { label: 'VIP',       bg: '#fdf0f5',         color: '#8a1a4a'       },
      };

      const subtypeLabel = {
        SCHOOL: 'School', CHURCH: 'Church', NGO: 'NGO',
        GOVT: 'Government', OTHER: 'Institution',
      };

      container.innerHTML = `
        <!-- Search bar -->
        <div style="margin-bottom:16px;">
          <input type="text" id="customers-search"
            placeholder="Search by name or phone…"
            oninput="Dashboard._filterCustomerRows(this.value)"
            style="width:100%;max-width:320px;padding:8px 14px;
              border:1.5px solid var(--border);border-radius:var(--radius-sm);
              background:var(--bg);color:var(--text);font-size:13px;
              font-family:'DM Sans',sans-serif;outline:none;box-sizing:border-box;">
        </div>

        <!-- Summary strip -->
        <div style="display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap;">
          ${[
            ['Total', customers.length, 'var(--text)', 'var(--panel)'],
            ['Individuals',  customers.filter(c => c.customer_type === 'INDIVIDUAL').length,  '#2e4a8a', '#f0f4fd'],
            ['Businesses',   customers.filter(c => c.customer_type === 'BUSINESS').length,    '#1a6b3a', '#f0fdf4'],
            ['Institutions', customers.filter(c => c.customer_type === 'INSTITUTION').length, '#5a2e8a', '#f5f0fd'],
          ].map(([label, count, color, bg]) => `
            <div style="padding:10px 16px;background:${bg};border:1px solid #e5e7eb;
              border-radius:8px;text-align:center;min-width:90px;">
              <div style="font-size:20px;font-weight:800;color:${color};">${count}</div>
              <div style="font-size:10px;color:#9ca3af;text-transform:uppercase;
                letter-spacing:0.4px;margin-top:2px;">${label}</div>
            </div>`).join('')}
        </div>

        <!-- Table -->
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;" id="customers-table">
            <thead>
              <tr style="background:var(--bg);border-bottom:2px solid var(--border);">
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Customer</th>
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Phone</th>
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Type</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Visits</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Tier</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Score</th>
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Since</th>
                <th style="padding:10px 16px;"></th>
              </tr>
            </thead>
            <tbody id="customers-tbody">
              ${customers.map((c, idx) => {
                const tc  = typeConfig[c.customer_type]  || typeConfig.INDIVIDUAL;
                const trc = tierConfig[c.tier]           || tierConfig.REGULAR;
                const isIndividual = c.customer_type === 'INDIVIDUAL';
                const name = isIndividual
                  ? (c.full_name || c.display_name || '—')
                  : (c.display_name || '—');
                const sub = isIndividual
                  ? ''
                  : (c.full_name ? `Rep: ${c.full_name}` : '');
                const sinceDate = c.created_at
                  ? new Date(c.created_at).toLocaleDateString('en-GB',
                      { day: 'numeric', month: 'short', year: 'numeric' })
                  : '—';
                const scoreColor = c.confidence_score >= 70
                  ? '#16a34a' : c.confidence_score >= 40 ? '#d97706' : '#dc2626';
                const typeLabel = c.institution_subtype
                  ? subtypeLabel[c.institution_subtype] || tc.label
                  : tc.label;

                return `
                  <tr data-search="${(name + ' ' + (c.phone||'')).toLowerCase()}"
                    style="border-bottom:1px solid var(--border);
                      background:${idx % 2 === 0 ? '#fff' : '#fafafa'};
                      cursor:pointer;transition:background 0.12s;"
                    onmouseover="this.style.background='var(--bg)'"
                    onmouseout="this.style.background='${idx % 2 === 0 ? '#fff' : '#fafafa'}'"
                    onclick="Dashboard.openCustomerDetail(${c.id})">

                    <!-- Name -->
                    <td style="padding:11px 16px;">
                      <div style="font-size:13px;font-weight:700;color:var(--text);">
                        ${_esc(name)}</div>
                      ${sub ? `
                        <div style="font-size:11px;color:var(--text-3);margin-top:1px;">
                          ${_esc(sub)}
                        </div>` : ''}
                    </td>

                    <!-- Phone -->
                    <td style="padding:11px 16px;font-family:'JetBrains Mono',monospace;
                      font-size:12px;color:var(--text-2);">${_esc(c.phone || '—')}</td>

                    <!-- Type -->
                    <td style="padding:11px 16px;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:10px;
                        font-weight:700;background:${tc.bg};color:${tc.color};">
                        ${typeLabel}
                      </span>
                    </td>

                    <!-- Visits -->
                    <td style="padding:11px 16px;text-align:center;font-size:13px;
                      font-weight:600;color:var(--text);">${c.visit_count || 0}</td>

                    <!-- Tier -->
                    <td style="padding:11px 16px;text-align:center;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:10px;
                        font-weight:700;background:${trc.bg};color:${trc.color};">
                        ${trc.label}
                      </span>
                    </td>

                    <!-- Score -->
                    <td style="padding:11px 16px;text-align:center;">
                      <span style="font-family:'JetBrains Mono',monospace;font-size:13px;
                        font-weight:700;color:${scoreColor};">${c.confidence_score}</span>
                    </td>

                    <!-- Since -->
                    <td style="padding:11px 16px;font-size:12px;color:var(--text-3);">
                      ${sinceDate}</td>

                    <!-- Action -->
                    <td style="padding:11px 16px;text-align:right;">
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
                        viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="2" style="color:var(--text-3);">
                        <polyline points="9 18 15 12 9 6"/>
                      </svg>
                    </td>

                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;

    } catch {
      container.innerHTML = `
        <div class="loading-cell" style="color:var(--red-text);">
          Could not load customers.</div>`;
    }
  }

  async function _renderCreditCustomers(container) {
    try {
      const res  = await Auth.fetch('/api/v1/customers/credit/');
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const accounts = Array.isArray(data) ? data : (data.results || []);

      if (!accounts.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">
              No credit accounts</div>
            <div style="font-size:13px;">
              Nominate a customer for credit from their profile.</div>
          </div>`;
        return;
      }

      const statusConfig = {
        ACTIVE   : { bg: '#dcfce7', color: '#16a34a', label: 'Active'    },
        PENDING  : { bg: '#fef3c7', color: '#d97706', label: 'Pending'   },
        SUSPENDED: { bg: '#fee2e2', color: '#dc2626', label: 'Suspended' },
        CLOSED   : { bg: '#f3f4f6', color: '#6b7280', label: 'Closed'    },
      };

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',
        { minimumFractionDigits: 2 })}`;

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);border-bottom:2px solid var(--border);">
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Customer</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Limit</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Balance</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Available</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Usage</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;
                  color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Status</th>
              </tr>
            </thead>
            <tbody>
              ${accounts.map((a, idx) => {
                const sc      = statusConfig[a.status] || statusConfig.PENDING;
                const usagePct = a.utilisation_pct || 0;
                const usageColor = usagePct >= 90 ? '#dc2626'
                  : usagePct >= 70 ? '#d97706' : '#16a34a';

                return `
                  <tr style="border-bottom:1px solid var(--border);
                    background:${idx % 2 === 0 ? '#fff' : '#fafafa'};">
                    <td style="padding:11px 16px;">

                      <!-- Line 1: Primary name + account type badge -->
                      <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">
                        <span style="font-size:13px;font-weight:700;color:var(--text);">
                          ${_esc(a.customer_name || '—')}
                        </span>
                        <span style="font-size:9px;font-weight:700;padding:1px 7px;
                          border-radius:20px;
                          background:${a.account_type === 'BUSINESS' ? '#f0fdf4' : '#f0f4fd'};
                          color:${a.account_type === 'BUSINESS' ? '#1a6b3a' : '#2e4a8a'};">
                          ${a.account_type === 'BUSINESS' ? 'Business' : 'Individual'}
                        </span>
                      </div>

                      <!-- Line 2: Rep (business) or company affiliation (individual) + phone -->
                      <div style="font-size:11px;color:var(--text-3);margin-bottom:2px;">
                        ${a.account_type === 'BUSINESS'
                          ? (a.contact_person ? `Rep: ${_esc(a.contact_person)} · ` : '')
                          : (a.customer_company ? `${_esc(a.customer_company)} · ` : '')}
                        <span style="font-family:'JetBrains Mono',monospace;">
                          ${_esc(a.customer_phone || '—')}
                        </span>
                      </div>

                      <!-- Line 3: Address if available -->
                      ${a.customer_address ? `
                        <div style="font-size:11px;color:var(--text-3);">
                          ${_esc(a.customer_address)}
                        </div>` : ''}

                    </td>
                    <td style="padding:11px 16px;text-align:right;
                      font-family:'JetBrains Mono',monospace;font-size:12px;
                      font-weight:600;color:var(--text);">${fmt(a.credit_limit)}</td>
                    <td style="padding:11px 16px;text-align:right;
                      font-family:'JetBrains Mono',monospace;font-size:12px;
                      font-weight:700;color:#dc2626;">${fmt(a.current_balance)}</td>
                    <td style="padding:11px 16px;text-align:right;
                      font-family:'JetBrains Mono',monospace;font-size:12px;
                      color:#16a34a;font-weight:600;">${fmt(a.available_credit)}</td>
                    <td style="padding:11px 16px;text-align:center;">
                      <div style="display:flex;align-items:center;gap:6px;
                        justify-content:center;">
                        <div style="width:60px;height:4px;background:#f3f4f6;
                          border-radius:2px;overflow:hidden;">
                          <div style="height:100%;width:${Math.min(100,usagePct).toFixed(1)}%;
                            background:${usageColor};border-radius:2px;"></div>
                        </div>
                        <span style="font-size:11px;font-weight:600;
                          color:${usageColor};">${usagePct.toFixed(0)}%</span>
                      </div>
                    </td>
                    <td style="padding:11px 16px;text-align:center;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:10px;
                        font-weight:700;background:${sc.bg};color:${sc.color};">
                        ${sc.label}
                      </span>
                    </td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;

    } catch {
      container.innerHTML = `
        <div class="loading-cell" style="color:var(--red-text);">
          Could not load credit accounts.</div>`;
    }
  }

  function _filterCustomerRows(query) {
    const q    = query.toLowerCase();
    const rows = document.querySelectorAll('#customers-tbody tr');
    rows.forEach(row => {
      const search = row.dataset.search || '';
      row.style.display = search.includes(q) ? '' : 'none';
    });
  }

async function openCustomerDetail(customerId) {
    const overlay = document.getElementById('customer-profile-overlay');
    const content = document.getElementById('customer-profile-content');
    if (!overlay || !content) return;

    overlay.style.display = 'block';

    content.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;
        min-height:100vh;color:var(--text-3);">
        <span class="spin"></span>
      </div>`;

    try {
      const [profileRes, jobsRes, creditRes] = await Promise.all([
        Auth.fetch(`/api/v1/customers/${customerId}/`),
        Auth.fetch(`/api/v1/jobs/?customer=${customerId}&page_size=100`),
        Auth.fetch(`/api/v1/customers/credit/`),
      ]);

      const customer  = profileRes.ok ? await profileRes.json() : null;
      if (!customer) throw new Error();

      const jobsData   = jobsRes.ok   ? await jobsRes.json()   : { results: [] };
      const creditData = creditRes.ok ? await creditRes.json() : { results: [] };

      // Filter jobs that are actually linked to this customer
      const jobs   = (jobsData.results || []).filter(j => j.customer === customerId);

      // Filter credit account for this customer
      const credit = (creditData.results || []).find(c => c.customer === customerId) || null;

      _renderCustomerProfile(content, customer, jobs, credit);

    } catch {
      content.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;
          min-height:100vh;flex-direction:column;gap:12px;color:var(--red-text);">
          <div>Could not load customer profile.</div>
          <button onclick="Dashboard.closeCustomerProfile()"
            style="padding:8px 20px;background:var(--text);color:#fff;border:none;
              border-radius:var(--radius-sm);cursor:pointer;font-family:inherit;">
            Close
          </button>
        </div>`;
    }
  }

  function _renderCustomerProfile(container, c, jobs, credit) {
    const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
    const isIndividual = c.customer_type === 'INDIVIDUAL';

    const primaryName = isIndividual
      ? (c.full_name || '—')
      : (c.company_name || '—');
    const secondaryName = isIndividual
      ? (c.company_name || '')
      : (c.full_name ? `Rep: ${c.full_name}` : '');

    const typeConfig = {
      INDIVIDUAL : { label: 'Individual',  bg: '#f0f4fd', color: '#2e4a8a' },
      BUSINESS   : { label: 'Business',    bg: '#f0fdf4', color: '#1a6b3a' },
      INSTITUTION: { label: 'Institution', bg: '#f5f0fd', color: '#5a2e8a' },
    };
    const tc  = typeConfig[c.customer_type] || typeConfig.INDIVIDUAL;

    const tierConfig = {
      REGULAR  : { label: 'Regular',   color: '#6b7280' },
      PREFERRED: { label: 'Preferred', color: '#d97706' },
      VIP      : { label: 'VIP',       color: '#8a1a4a' },
    };
    const trc = tierConfig[c.tier] || tierConfig.REGULAR;

    const sinceDate = c.created_at
      ? new Date(c.created_at).toLocaleDateString('en-GB',
          { day: 'numeric', month: 'long', year: 'numeric' })
      : '—';

    const initials = primaryName.split(' ').slice(0,2)
      .map(w => w[0]?.toUpperCase() || '').join('');

    const scoreColor = c.confidence_score >= 70 ? '#16a34a'
      : c.confidence_score >= 40 ? '#d97706' : '#dc2626';

    const totalSpent = jobs.reduce((s, j) => s + parseFloat(j.amount_paid||0), 0);
    const scoreToCredit = Math.max(0, 50 - c.confidence_score);

    // ── Timeline HTML ─────────────────────────────────────
    const timelineHtml = !jobs.length ? `
      <div style="text-align:center;padding:48px 24px;
        background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);">
        <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28"
          viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="1.5" style="opacity:0.3;display:block;margin:0 auto 12px;
          color:var(--text-3);">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:6px;">
          No Job History Available for ${_esc(primaryName)}
        </div>
        <div style="font-size:13px;color:var(--text-3);">
          Jobs linked to this customer will appear here once created.
        </div>
      </div>` : `
      <div style="position:relative;">
        ${jobs.map((j, idx) => {
          const dt       = new Date(j.created_at);
          const dateStr  = dt.toLocaleDateString('en-GB',
            { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
          const timeStr  = dt.toLocaleTimeString('en-GH',
            { hour: '2-digit', minute: '2-digit' });
          const services = (j.line_items || [])
            .map(li => li.service_name).join(', ') || '—';
          const isLast   = idx === jobs.length - 1;

          const statusColor = {
            COMPLETE       : '#16a34a', CANCELLED: '#dc2626',
            IN_PROGRESS    : '#d97706', PENDING_PAYMENT: '#d97706',
          }[j.status] || '#6b7280';

          const statusBg = {
            COMPLETE       : '#dcfce7', CANCELLED: '#fee2e2',
            IN_PROGRESS    : '#fef3c7', PENDING_PAYMENT: '#fef3c7',
          }[j.status] || '#f3f4f6';

          const methodColor = {
            CASH: '#8a6a2e', MOMO: '#1a6b3a', POS: '#2e4a8a', CREDIT: '#8a1a4a',
          }[j.payment_method] || '#6b7280';

          const methodBg = {
            CASH: '#fdf8f0', MOMO: '#f0fdf4', POS: '#f0f4fd', CREDIT: '#fdf0f5',
          }[j.payment_method] || '#f3f4f6';

          return `
            <div style="display:flex;gap:16px;margin-bottom:${isLast ? '0' : '0'};">

              <!-- Timeline spine -->
              <div style="display:flex;flex-direction:column;align-items:center;
                flex-shrink:0;width:32px;">
                <!-- Node dot -->
                <div style="width:12px;height:12px;border-radius:50%;
                  background:${statusColor};border:2px solid #fff;
                  box-shadow:0 0 0 2px ${statusColor};
                  flex-shrink:0;margin-top:16px;"></div>
                <!-- Line -->
                ${!isLast ? `
                  <div style="width:2px;flex:1;background:#e5e7eb;
                    margin-top:4px;min-height:24px;"></div>` : ''}
              </div>

              <!-- Job card -->
              <div style="flex:1;background:var(--panel);border:1px solid var(--border);
                border-radius:var(--radius);overflow:hidden;margin-bottom:12px;">

                <!-- Job header — dark strip -->
                <div style="padding:10px 16px;background:var(--text);
                  display:flex;align-items:center;justify-content:space-between;">
                  <div style="font-family:'JetBrains Mono',monospace;font-size:12px;
                    font-weight:700;color:#fff;letter-spacing:0.3px;">
                    ${_esc(j.job_number || '—')}
                  </div>
                  <div style="display:flex;align-items:center;gap:6px;">
                    <span style="padding:2px 8px;border-radius:20px;font-size:10px;
                      font-weight:700;background:rgba(255,255,255,0.15);color:#fff;">
                      ${j.job_type || '—'}
                    </span>
                    <span style="padding:2px 8px;border-radius:20px;font-size:10px;
                      font-weight:700;background:${statusBg};color:${statusColor};">
                      ${j.status.replace(/_/g,' ')}
                    </span>
                  </div>
                </div>

                <!-- Job body -->
                <div style="padding:12px 16px;">

                  <!-- Service name -->
                  <div style="font-size:13px;font-weight:600;color:var(--text);
                    margin-bottom:10px;">${_esc(services)}</div>

                  <!-- Meta grid -->
                  <div style="display:grid;grid-template-columns:repeat(3,1fr);
                    gap:8px;margin-bottom:10px;">

                    <div>
                      <div style="font-size:9px;font-weight:700;color:var(--text-3);
                        text-transform:uppercase;letter-spacing:0.4px;margin-bottom:2px;">
                        Date & Time</div>
                      <div style="font-size:11px;color:var(--text-2);">${dateStr}</div>
                      <div style="font-size:10px;color:var(--text-3);">${timeStr}</div>
                    </div>

                    <div>
                      <div style="font-size:9px;font-weight:700;color:var(--text-3);
                        text-transform:uppercase;letter-spacing:0.4px;margin-bottom:2px;">
                        Attendant</div>
                      <div style="font-size:11px;color:var(--text-2);">
                        ${_esc(j.intake_by_name || '—')}</div>
                    </div>

                    <div>
                      <div style="font-size:9px;font-weight:700;color:var(--text-3);
                        text-transform:uppercase;letter-spacing:0.4px;margin-bottom:2px;">
                        Amount</div>
                      <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
                        font-weight:800;color:var(--text);">${fmt(j.amount_paid)}</div>
                    </div>

                  </div>

                  <!-- Bottom row: payment method + production duration -->
                  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    ${j.payment_method ? `
                      <span style="padding:2px 8px;border-radius:20px;font-size:10px;
                        font-weight:700;background:${methodBg};color:${methodColor};">
                        ${j.payment_method}
                      </span>` : ''}
                    ${j.job_type === 'PRODUCTION' && j.deadline ? `
                      <span style="padding:2px 8px;border-radius:20px;font-size:10px;
                        font-weight:700;background:#f0f4fd;color:#2e4a8a;">
                        Due: ${new Date(j.deadline).toLocaleDateString('en-GB',
                          { day: 'numeric', month: 'short' })}
                      </span>` : ''}
                    ${j.is_routed ? `
                      <span style="padding:2px 8px;border-radius:20px;font-size:10px;
                        font-weight:700;background:#f5f0fd;color:#5a2e8a;">
                        → Routed
                      </span>` : ''}
                  </div>

                </div>
              </div>
            </div>`;
        }).join('')}
      </div>`;

    // ── Full modal HTML ───────────────────────────────────
    container.innerHTML = `
      <!-- Topbar -->
      <div style="display:flex;align-items:center;justify-content:space-between;
        padding:14px 28px;border-bottom:1px solid var(--border);
        background:var(--panel);position:sticky;top:0;z-index:10;">
        <div style="display:flex;align-items:center;gap:12px;">
          <button onclick="Dashboard.closeCustomerProfile()"
            style="display:flex;align-items:center;gap:6px;padding:7px 14px;
              background:none;border:1px solid var(--border);
              border-radius:var(--radius-sm);font-size:13px;font-weight:600;
              cursor:pointer;color:var(--text-2);font-family:inherit;"
            onmouseover="this.style.borderColor='var(--border-dark)'"
            onmouseout="this.style.borderColor='var(--border)'">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="19" y1="12" x2="5" y2="12"/>
              <polyline points="12 19 5 12 12 5"/>
            </svg>
            Back
          </button>
          <span style="font-size:13px;color:var(--text-3);">Customer Profile</span>
        </div>
        <div style="display:flex;gap:8px;">
          <button onclick="Dashboard._editCustomer(${c.id})"
            style="padding:7px 16px;background:none;border:1px solid var(--border);
              border-radius:var(--radius-sm);font-size:13px;font-weight:600;
              cursor:pointer;color:var(--text-2);font-family:inherit;">
            Edit Profile
          </button>
          ${!credit && c.confidence_score >= 50 ? `
          <button onclick="Dashboard._nominateCredit(${c.id})"
            style="padding:7px 16px;background:#16a34a;color:#fff;border:none;
              border-radius:var(--radius-sm);font-size:13px;font-weight:700;
              cursor:pointer;font-family:inherit;">
            Nominate for Credit
          </button>` : ''}
        </div>
      </div>

      <!-- Scrollable body — single column -->
      <div style="max-height:calc(100vh - 120px);overflow-y:auto;">
      <div style="max-width:800px;margin:0 auto;padding:32px 28px;">

        <!-- ── Profile header ──────────────────────────── -->
        <div style="display:flex;align-items:flex-start;gap:24px;margin-bottom:32px;">

          <!-- Avatar with score ring -->
          <div style="position:relative;flex-shrink:0;">
            <svg width="80" height="80" viewBox="0 0 80 80">
              <circle cx="40" cy="40" r="34" fill="none"
                stroke="#f3f4f6" stroke-width="4"/>
              <circle cx="40" cy="40" r="34" fill="none"
                stroke="${scoreColor}" stroke-width="4"
                stroke-dasharray="${2 * Math.PI * 34}"
                stroke-dashoffset="${2 * Math.PI * 34 * (1 - c.confidence_score / 100)}"
                stroke-linecap="round"
                transform="rotate(-90 40 40)"/>
            </svg>
            <div style="position:absolute;inset:0;display:flex;
              align-items:center;justify-content:center;">
              <div style="width:60px;height:60px;border-radius:50%;
                background:var(--text);display:flex;align-items:center;
                justify-content:center;font-family:'Syne',sans-serif;
                font-size:20px;font-weight:800;color:#fff;">
                ${initials}
              </div>
            </div>
          </div>

          <!-- Name + badges + meta -->
          <div style="flex:1;">
            <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;
              color:var(--text);letter-spacing:-0.4px;margin-bottom:4px;">
              ${_esc(primaryName)}
            </div>
            ${secondaryName ? `
              <div style="font-size:13px;color:var(--text-3);margin-bottom:8px;">
                ${_esc(secondaryName)}
              </div>` : ''}
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;
              margin-bottom:12px;">
              <span style="padding:3px 10px;border-radius:20px;font-size:11px;
                font-weight:700;background:${tc.bg};color:${tc.color};">
                ${tc.label}
              </span>
              <span style="padding:3px 10px;border-radius:20px;font-size:11px;
                font-weight:700;background:var(--bg);color:${trc.color};
                border:1px solid var(--border);">
                ${trc.label}
              </span>
              ${c.is_priority ? `
                <span style="padding:3px 10px;border-radius:20px;font-size:11px;
                  font-weight:700;background:#fef3c7;color:#d97706;">
                  ⭐ Priority
                </span>` : ''}
              ${credit ? `
                <span style="padding:3px 10px;border-radius:20px;font-size:11px;
                  font-weight:700;background:#fdf0f5;color:#8a1a4a;">
                  💳 Credit Account
                </span>` : ''}
            </div>
            <!-- Quick stats -->
            <div style="display:flex;gap:20px;flex-wrap:wrap;">
              ${[
                ['Customer since', sinceDate],
                ['Total visits',   c.visit_count || 0],
                ['Jobs on record', jobs.length],
                ['Lifetime spend', fmt(totalSpent)],
              ].map(([label, val]) => `
                <div>
                  <div style="font-size:10px;color:var(--text-3);margin-bottom:1px;">
                    ${label}</div>
                  <div style="font-size:13px;font-weight:700;color:var(--text);">
                    ${val}</div>
                </div>`).join('')}
            </div>
          </div>
        </div>

        <!-- ── Info sections ───────────────────────────── -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;
          margin-bottom:24px;">

          <!-- Contact -->
          <div style="background:var(--panel);border:1px solid var(--border);
            border-radius:var(--radius);padding:16px 18px;">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">
              Contact Details
            </div>
            ${[
              ['Phone',   c.phone   || '—'],
              ['Email',   c.email   || '—'],
              ['Address', c.address || '—'],
            ].map(([label, val]) => `
              <div style="display:flex;justify-content:space-between;
                padding:6px 0;border-bottom:1px solid var(--border);">
                <span style="font-size:12px;color:var(--text-3);">${label}</span>
                <span style="font-size:12px;font-weight:500;
                  color:${val === '—' ? 'var(--text-3)' : 'var(--text)'};">
                  ${_esc(val)}</span>
              </div>`).join('')}
          </div>

          <!-- Credit or eligibility -->
          <div style="background:var(--panel);border:1px solid var(--border);
            border-radius:var(--radius);padding:16px 18px;">
            ${credit ? `
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">
                Credit Account
              </div>
              ${[
                ['Limit',     fmt(credit.credit_limit)],
                ['Balance',   fmt(credit.current_balance)],
                ['Available', fmt(credit.available_credit)],
                ['Terms',     `${credit.payment_terms} days`],
                ['Status',    credit.status],
              ].map(([label, val]) => `
                <div style="display:flex;justify-content:space-between;
                  padding:6px 0;border-bottom:1px solid var(--border);">
                  <span style="font-size:12px;color:var(--text-3);">${label}</span>
                  <span style="font-size:12px;font-weight:600;
                    color:${label==='Balance' ? '#dc2626'
                      : label==='Available' ? '#16a34a' : 'var(--text)'};">
                    ${_esc(String(val))}</span>
                </div>`).join('')}
              <!-- Usage bar -->
              <div style="margin-top:10px;">
                <div style="height:4px;background:#f3f4f6;border-radius:2px;
                  overflow:hidden;">
                  <div style="height:100%;
                    width:${Math.min(100,credit.utilisation_pct).toFixed(1)}%;
                    background:${credit.utilisation_pct>=90?'#dc2626'
                      :credit.utilisation_pct>=70?'#d97706':'#16a34a'};
                    border-radius:2px;"></div>
                </div>
                <div style="font-size:10px;color:var(--text-3);margin-top:3px;
                  text-align:right;">${credit.utilisation_pct.toFixed(0)}% utilised</div>
              </div>` : `
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">
                Credit Eligibility
              </div>
              <div style="margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;
                  margin-bottom:6px;">
                  <span style="font-size:12px;color:var(--text-2);">
                    Confidence Score</span>
                  <span style="font-size:13px;font-weight:700;color:${scoreColor};">
                    ${c.confidence_score} / 100</span>
                </div>
                <div style="height:6px;background:#f3f4f6;border-radius:3px;
                  overflow:hidden;">
                  <div style="height:100%;width:${c.confidence_score}%;
                    background:${scoreColor};border-radius:3px;"></div>
                </div>
              </div>
              <div style="font-size:12px;color:var(--text-3);">
                ${c.confidence_score >= 50
                  ? '✓ Eligible — use Nominate for Credit button above'
                  : `Needs <strong style="color:var(--text);">${scoreToCredit} more points</strong> to reach credit threshold`}
              </div>`}
          </div>

        </div>

        <!-- ── BM Notes ─────────────────────────────────── -->
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:16px 18px;margin-bottom:24px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;">
            Branch Manager Notes
          </div>
          <textarea id="customer-notes-${c.id}" rows="3"
            placeholder="Add notes about this customer…"
            onblur="Dashboard._saveCustomerNotes(${c.id})"
            style="width:100%;padding:10px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;resize:vertical;box-sizing:border-box;
              font-family:'DM Sans',sans-serif;outline:none;">
${_esc(c.notes || '')}</textarea>
          <div style="font-size:10px;color:var(--text-3);margin-top:4px;">
            Auto-saves when you click away
          </div>
        </div>

        <!-- ── Job History timeline ────────────────────── -->
        <div style="margin-bottom:32px;">
          <div style="font-family:'Syne',sans-serif;font-size:17px;font-weight:800;
            color:var(--text);letter-spacing:-0.2px;margin-bottom:16px;
            display:flex;align-items:center;gap:10px;">
            Job History
            <span style="font-size:12px;font-weight:400;color:var(--text-3);
              font-family:'DM Sans',sans-serif;">
              ${jobs.length} job${jobs.length !== 1 ? 's' : ''} on record
            </span>
          </div>
          ${timelineHtml}
        </div>

      </div>
      </div>`;
  }

  function closeCustomerProfile() {
    const overlay = document.getElementById('customer-profile-overlay');
    if (overlay) overlay.style.display = 'none';
  }

  async function _saveCustomerNotes(customerId) {
    const textarea = document.getElementById(`customer-notes-${customerId}`);
    if (!textarea) return;
    const notes = textarea.value.trim();
    try {
      await Auth.fetch(`/api/v1/customers/${customerId}/`, {
        method : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ notes }),
      });
    } catch { /* silent */ }
  }

  // ── Customer Inline Edit ──────────────────────────────────────
// Replaces _editCustomer stub. Opens edit view inside the profile overlay.

  async function _editCustomer(customerId) {
    const content = document.getElementById('customer-profile-content');
    if (!content) return;

    // Show spinner while we fetch fresh data
    content.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;
        min-height:100vh;color:var(--text-3);">
        <span class="spin"></span>
      </div>`;

    try {
      const res = await Auth.fetch(`/api/v1/customers/${customerId}/`);
      if (!res.ok) throw new Error();
      const c = await res.json();
      _renderEditCustomerForm(content, c);
    } catch {
      _toast('Could not load customer for editing.', 'error');
      // Fall back to re-opening the profile view
      openCustomerDetail(customerId);
    }
  }

  function _renderEditCustomerForm(container, c) {
    const isIndividual  = c.customer_type === 'INDIVIDUAL';
    const isBusiness    = c.customer_type === 'BUSINESS';
    const isInstitution = c.customer_type === 'INSTITUTION';

    const primaryName = isIndividual
      ? (c.full_name || '—')
      : (c.company_name || '—');

    // Fields allowed per type
    const showCompany    = isBusiness || isInstitution;
    const showSubtype    = isInstitution;

    const subtypeOptions = [
      ['SCHOOL', 'School'],
      ['CHURCH', 'Church / Religious'],
      ['NGO',    'NGO / Non-profit'],
      ['GOVT',   'Government / Public'],
      ['OTHER',  'Other Institution'],
    ];

    container.innerHTML = `
      <!-- Topbar -->
      <div style="display:flex;align-items:center;justify-content:space-between;
        padding:14px 28px;border-bottom:1px solid var(--border);
        background:var(--panel);position:sticky;top:0;z-index:10;">
        <div style="display:flex;align-items:center;gap:12px;">
          <button onclick="Dashboard.openCustomerDetail(${c.id})"
            style="display:flex;align-items:center;gap:6px;padding:7px 14px;
              background:none;border:1px solid var(--border);
              border-radius:var(--radius-sm);font-size:13px;font-weight:600;
              cursor:pointer;color:var(--text-2);font-family:inherit;"
            onmouseover="this.style.borderColor='var(--border-dark)'"
            onmouseout="this.style.borderColor='var(--border)'">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13"
              viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="19" y1="12" x2="5" y2="12"/>
              <polyline points="12 19 5 12 12 5"/>
            </svg>
            Cancel
          </button>
          <span style="font-size:13px;color:var(--text-3);">
            Editing: <strong style="color:var(--text);">${_esc(primaryName)}</strong>
          </span>
        </div>
        <button id="edit-cust-save-btn"
          onclick="Dashboard._saveCustomerEdit(${c.id})"
          style="padding:8px 20px;background:var(--text);color:#fff;border:none;
            border-radius:var(--radius-sm);font-size:13px;font-weight:700;
            cursor:pointer;font-family:'DM Sans',sans-serif;">
          Save Changes
        </button>
      </div>

      <!-- Edit form body -->
      <div style="max-height:calc(100vh - 64px);overflow-y:auto;">
      <div style="max-width:680px;margin:0 auto;padding:36px 28px;">

        <!-- Section label -->
        <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;
          color:var(--text);letter-spacing:-0.3px;margin-bottom:6px;">Edit Profile</div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:28px;">
          Locked fields (tier, score, customer type, visit count) cannot be edited here.
          All changes are logged in the audit trail.
        </div>

        <!-- Error banner -->
        <div id="edit-cust-error" style="display:none;font-size:13px;
          color:var(--red-text);padding:10px 14px;background:var(--red-bg);
          border:1px solid var(--red-border);border-radius:var(--radius-sm);
          margin-bottom:20px;"></div>

        <!-- ── Editable fields ───────────────────────── -->
        <div style="display:flex;flex-direction:column;gap:18px;">

          ${showCompany ? `
          <!-- Company / Institution name -->
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;display:block;
              margin-bottom:7px;">
              ${isBusiness ? 'Company Name' : 'Institution Name'} *
            </label>
            <input type="text" id="edit-company"
              value="${_esc(c.company_name || '')}"
              style="width:100%;padding:10px 13px;border:1.5px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                box-sizing:border-box;">
          </div>` : ''}

          ${showSubtype ? `
          <!-- Institution subtype -->
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;display:block;
              margin-bottom:7px;">Institution Type</label>
            <select id="edit-subtype"
              style="width:100%;padding:10px 13px;border:1.5px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:13px;font-family:'DM Sans',sans-serif;outline:none;">
              <option value="">Select type…</option>
              ${subtypeOptions.map(([val, label]) =>
                `<option value="${val}" ${c.institution_subtype === val ? 'selected' : ''}>${label}</option>`
              ).join('')}
            </select>
          </div>` : ''}

          <!-- Name row -->
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;display:block;
                margin-bottom:7px;">
                ${isIndividual ? 'First Name' : 'Rep First Name'} *
              </label>
              <input type="text" id="edit-first-name"
                value="${_esc(c.first_name || '')}"
                style="width:100%;padding:10px 13px;border:1.5px solid var(--border);
                  border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                  font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                  box-sizing:border-box;">
            </div>
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;display:block;
                margin-bottom:7px;">
                ${isIndividual ? 'Last Name' : 'Rep Last Name'} *
              </label>
              <input type="text" id="edit-last-name"
                value="${_esc(c.last_name || '')}"
                style="width:100%;padding:10px 13px;border:1.5px solid var(--border);
                  border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                  font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                  box-sizing:border-box;">
            </div>
          </div>

          <!-- Phone -->
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;display:block;
              margin-bottom:7px;">Phone Number *</label>
            <input type="tel" id="edit-phone"
              value="${_esc(c.phone || '')}"
              onblur="Dashboard._editPhoneNormalise(this)"
              style="width:100%;padding:10px 13px;border:1.5px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                box-sizing:border-box;">
            <div id="edit-phone-feedback"
              style="font-size:11px;margin-top:5px;"></div>
          </div>

          <!-- Email -->
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;display:block;
              margin-bottom:7px;">
              Email <span style="font-weight:400;">(optional)</span>
            </label>
            <input type="email" id="edit-email"
              value="${_esc(c.email || '')}"
              style="width:100%;padding:10px 13px;border:1.5px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                box-sizing:border-box;">
          </div>

          <!-- Address -->
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;display:block;
              margin-bottom:7px;">
              Address ${!isIndividual
                ? '*'
                : '<span style="font-weight:400;">(optional)</span>'}
            </label>
            <textarea id="edit-address" rows="3"
              style="width:100%;padding:10px 13px;border:1.5px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                resize:vertical;box-sizing:border-box;">${_esc(c.address || '')}</textarea>
          </div>

          <!-- ── Locked fields — read-only display ───── -->
          <div style="padding:16px 18px;background:var(--bg);
            border:1px solid var(--border);border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">
              Read-only Fields
            </div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
              ${[
                ['Customer Type',     c.customer_type],
                ['Tier',              c.tier || 'REGULAR'],
                ['Confidence Score',  c.confidence_score + ' / 100'],
                ['Total Visits',      c.visit_count || 0],
              ].map(([label, val]) => `
                <div>
                  <div style="font-size:10px;font-weight:700;color:var(--text-3);
                    text-transform:uppercase;letter-spacing:0.4px;margin-bottom:3px;">
                    ${label}</div>
                  <div style="font-size:13px;color:var(--text-3);font-weight:500;">
                    ${_esc(String(val))}</div>
                </div>`).join('')}
            </div>
          </div>

        </div>

        <!-- ── Edit History ──────────────────────────── -->
        <div style="margin-top:36px;">
          <div style="display:flex;align-items:center;justify-content:space-between;
            margin-bottom:12px;">
            <div style="font-family:'Syne',sans-serif;font-size:17px;font-weight:800;
              color:var(--text);letter-spacing:-0.2px;">Edit History</div>
            <button onclick="Dashboard._toggleEditHistory(${c.id})"
              id="edit-history-toggle-btn"
              style="padding:5px 14px;background:none;border:1px solid var(--border);
                border-radius:var(--radius-sm);font-size:12px;font-weight:600;
                cursor:pointer;color:var(--text-2);font-family:inherit;">
              Load History
            </button>
          </div>
          <div id="edit-history-content" style="display:none;"></div>
        </div>

      </div>
      </div>`;
  }

  function _editPhoneNormalise(input) {
    const norm = _normalisePhone(input.value);
    input.value = norm;
    const fb = document.getElementById('edit-phone-feedback');
    if (fb && norm && norm !== document.getElementById('edit-phone')?.dataset.original) {
      fb.textContent = 'Number normalised to: ' + norm;
      fb.style.color = 'var(--text-3)';
    }
  }

  async function _saveCustomerEdit(customerId) {
    const btn   = document.getElementById('edit-cust-save-btn');
    const errEl = document.getElementById('edit-cust-error');
    errEl.style.display = 'none';

    const firstName = document.getElementById('edit-first-name')?.value.trim();
    const lastName  = document.getElementById('edit-last-name')?.value.trim();
    const rawPhone  = document.getElementById('edit-phone')?.value.trim();
    const phone     = _normalisePhone(rawPhone);
    const email     = document.getElementById('edit-email')?.value.trim();
    const address   = document.getElementById('edit-address')?.value.trim();
    const company   = document.getElementById('edit-company')?.value.trim();
    const subtype   = document.getElementById('edit-subtype')?.value;

    // ── Validation ──────────────────────────────────────
    const showErr = msg => {
      errEl.textContent   = msg;
      errEl.style.display = 'block';
      errEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    if (!firstName) return showErr('First name is required.');
    if (!lastName)  return showErr('Last name is required.');
    if (!phone)     return showErr('Phone number is required.');

    btn.disabled    = true;
    btn.textContent = 'Saving…';

    // Build payload — only send fields that exist in the form
    const payload = { first_name: firstName, last_name: lastName, phone };
    if (email   !== undefined) payload.email   = email;
    if (address !== undefined) payload.address = address;
    if (company !== undefined && document.getElementById('edit-company'))
      payload.company_name = company;
    if (subtype !== undefined && document.getElementById('edit-subtype'))
      payload.institution_subtype = subtype;

    try {
      const res  = await Auth.fetch(`/api/v1/customers/${customerId}/edit/`, {
        method : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify(payload),
      });
      const data = await res.json();

      if (!res.ok) {
        const msg = typeof data.detail === 'string'
          ? data.detail
          : Object.values(data).flat().join(' ');
        btn.disabled    = false;
        btn.textContent = 'Save Changes';
        return showErr(msg || 'Save failed. Please try again.');
      }

      _toast('Profile updated successfully.', 'success');
      // Refresh the full profile view
      openCustomerDetail(customerId);

    } catch {
      btn.disabled    = false;
      btn.textContent = 'Save Changes';
      showErr('Network error. Please try again.');
    }
  }

  async function _toggleEditHistory(customerId) {
    const content = document.getElementById('edit-history-content');
    const btn     = document.getElementById('edit-history-toggle-btn');
    if (!content) return;

    const isVisible = content.style.display !== 'none';
    if (isVisible) {
      content.style.display = 'none';
      btn.textContent = 'Load History';
      return;
    }

    content.style.display = 'block';
    btn.textContent = 'Hide History';
    content.innerHTML = '<div style="padding:16px 0;color:var(--text-3);font-size:13px;"><span class="spin"></span> Loading…</div>';

    await _loadEditHistory(customerId, content);
  }

  async function _loadEditHistory(customerId, container) {
    try {
      const res  = await Auth.fetch(`/api/v1/customers/${customerId}/edit-log/`);
      if (!res.ok) throw new Error();
      const logs = await res.json();

      if (!logs.length) {
        container.innerHTML = `
          <div style="padding:20px;text-align:center;color:var(--text-3);font-size:13px;
            background:var(--panel);border:1px solid var(--border);
            border-radius:var(--radius-sm);">
            No edits recorded yet.
          </div>`;
        return;
      }

      const fieldLabel = field => ({
        first_name          : 'First Name',
        last_name           : 'Last Name',
        phone               : 'Phone',
        email               : 'Email',
        address             : 'Address',
        company_name        : 'Company / Institution Name',
        institution_subtype : 'Institution Type',
      }[field] || field);

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          ${logs.map((log, idx) => {
            const dt = new Date(log.changed_at);
            const dateStr = dt.toLocaleDateString('en-GB',
              { day: 'numeric', month: 'short', year: 'numeric' });
            const timeStr = dt.toLocaleTimeString('en-GH',
              { hour: '2-digit', minute: '2-digit' });
            const isLast = idx === logs.length - 1;

            return `
              <div style="display:flex;align-items:flex-start;gap:14px;
                padding:14px 18px;
                ${!isLast ? 'border-bottom:1px solid var(--border);' : ''}">

                <!-- Field pill -->
                <div style="flex-shrink:0;margin-top:2px;">
                  <span style="padding:3px 9px;border-radius:20px;font-size:10px;
                    font-weight:700;background:var(--bg);color:var(--text-2);
                    border:1px solid var(--border);">
                    ${_esc(fieldLabel(log.field_name))}
                  </span>
                </div>

                <!-- Change -->
                <div style="flex:1;min-width:0;">
                  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;
                    margin-bottom:5px;">
                    <span style="font-size:13px;color:var(--red-text);font-weight:500;
                      max-width:200px;overflow:hidden;text-overflow:ellipsis;
                      white-space:nowrap;"
                      title="${_esc(log.old_value || '(empty)')}">
                      ${_esc(log.old_value || '(empty)')}
                    </span>
                    <span style="color:var(--text-3);font-size:12px;">→</span>
                    <span style="font-size:13px;color:var(--green-text);font-weight:600;
                      max-width:200px;overflow:hidden;text-overflow:ellipsis;
                      white-space:nowrap;"
                      title="${_esc(log.new_value || '(empty)')}">
                      ${_esc(log.new_value || '(empty)')}
                    </span>
                  </div>
                  <div style="font-size:11px;color:var(--text-3);">
                    By <strong style="color:var(--text-2);">
                      ${_esc(log.changed_by_name || '—')}
                    </strong>
                    · ${dateStr} at ${timeStr}
                  </div>
                </div>

              </div>`;
          }).join('')}
        </div>`;

    } catch {
      container.innerHTML = `
        <div style="padding:16px;color:var(--red-text);font-size:13px;
          background:var(--red-bg);border:1px solid var(--red-border);
          border-radius:var(--radius-sm);">
          Could not load edit history.
        </div>`;
    }
  }

  function _nominateCredit(customerId) {
    _toast('Credit nomination coming soon.', 'info');
  }

// ── Add Customer Modal — delegates to CustomerReg ─────────────────────────
  function openAddCustomerModal() {
    CustomerReg.open(async function(data) {
      _toast(`${data.display_name || data.full_name || 'Customer'} registered successfully.`, 'success');
      await _loadCustomersTab(_customersTab);
      if (data.id) setTimeout(() => openCustomerDetail(data.id), 300);
    });
  }

  function _buildCustForm(type) {
    const isIndividual  = type === 'INDIVIDUAL';
    const isBusiness    = type === 'BUSINESS';
    const isInstitution = type === 'INSTITUTION';

    return `
      <div style="display:flex;flex-direction:column;gap:14px;">

        ${isInstitution ? `
        <!-- Institution subtype -->
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Institution Type *
          </label>
          <select id="cust-subtype" style="width:100%;padding:9px 12px;
            border:1.5px solid var(--border);border-radius:var(--radius-sm);
            background:var(--bg);color:var(--text);font-size:13px;
            font-family:'DM Sans',sans-serif;outline:none;">
            <option value="">Select type…</option>
            <option value="SCHOOL">School</option>
            <option value="CHURCH">Church / Religious</option>
            <option value="NGO">NGO / Non-profit</option>
            <option value="GOVT">Government / Public</option>
            <option value="OTHER">Other Institution</option>
          </select>
        </div>` : ''}

        ${!isIndividual ? `
        <!-- Company / Institution name -->
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            ${isBusiness ? 'Company Name' : 'Institution Name'} *
          </label>
          <input type="text" id="cust-company" placeholder="${isBusiness ? 'e.g. Suma Court Hotel' : 'e.g. Accra High School'}"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              box-sizing:border-box;">
        </div>` : ''}

        <!-- Name row -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
              ${isIndividual ? 'First Name *' : 'Rep First Name *'}
            </label>
            <input type="text" id="cust-first-name"
              placeholder="${isIndividual ? 'e.g. Kwame' : 'e.g. Ama'}"
              style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                box-sizing:border-box;">
          </div>
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
              ${isIndividual ? 'Last Name *' : 'Rep Last Name *'}
            </label>
            <input type="text" id="cust-last-name"
              placeholder="${isIndividual ? 'e.g. Mensah' : 'e.g. Owusu'}"
              style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
                box-sizing:border-box;">
          </div>
        </div>

        <!-- Phone -->
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Phone Number *
          </label>
          <input type="tel" id="cust-phone" placeholder="e.g. 0244123456"
            onblur="Dashboard._checkCustPhoneDuplicate()"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              box-sizing:border-box;">
          <div id="cust-phone-feedback" style="font-size:11px;margin-top:4px;"></div>
        </div>

        <!-- Email -->
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Email <span style="font-weight:400;color:var(--text-3);">(optional)</span>
          </label>
          <input type="email" id="cust-email" placeholder="e.g. info@sumacourt.com"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              box-sizing:border-box;">
        </div>

        <!-- Address -->
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Address ${!isIndividual ? '*' : '<span style="font-weight:400;color:var(--text-3);">(optional)</span>'}
          </label>
          <textarea id="cust-address" rows="2"
            placeholder="Physical address…"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              resize:none;box-sizing:border-box;"></textarea>
        </div>

        <!-- BM Notes -->
        <div>
          <label style="font-size:11px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:6px;">
            Notes <span style="font-weight:400;color:var(--text-3);">(optional)</span>
          </label>
          <textarea id="cust-notes" rows="2"
            placeholder="Any notes about this customer…"
            style="width:100%;padding:9px 12px;border:1.5px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;font-family:'DM Sans',sans-serif;outline:none;
              resize:none;box-sizing:border-box;"></textarea>
        </div>

      </div>`;
  }

  function _setCustType(type) {
    _addCustType = type;

    // Update button styles
    const typeColors = {
      INDIVIDUAL : { bg: '#f0f4fd', color: '#2e4a8a', border: '#2e4a8a' },
      BUSINESS   : { bg: '#f0fdf4', color: '#1a6b3a', border: '#1a6b3a' },
      INSTITUTION: { bg: '#f5f0fd', color: '#5a2e8a', border: '#5a2e8a' },
    };
    ['INDIVIDUAL','BUSINESS','INSTITUTION'].forEach(t => {
      const btn = document.getElementById(`cust-type-${t}`);
      if (!btn) return;
      if (t === type) {
        const c = typeColors[t];
        btn.style.background = c.bg;
        btn.style.color      = c.color;
        btn.style.border     = `2px solid ${c.border}`;
      } else {
        btn.style.background = 'var(--bg)';
        btn.style.color      = 'var(--text-3)';
        btn.style.border     = '2px solid var(--border)';
      }
    });

    // Rebuild form
    const body = document.getElementById('add-cust-form-body');
    if (body) {
      body.innerHTML = _buildCustForm(type);
      setTimeout(() => document.getElementById('cust-first-name')?.focus(), 50);
    }
  }

  async function _checkCustPhoneDuplicate() {
    const raw   = document.getElementById('cust-phone')?.value.trim();
    const phone = _normalisePhone(raw);
    if (raw !== phone) {
      const phoneInput = document.getElementById('cust-phone');
      if (phoneInput) phoneInput.value = phone;
    }
    const feedback = document.getElementById('cust-phone-feedback');
    const input    = document.getElementById('cust-phone');
    if (!feedback || !phone) return;

    feedback.textContent = '';
    feedback.style.color = '';

    // Check against employee roster first
    try {
      const branchId  = State.branchId;
      const empRes    = await Auth.fetch(`/api/v1/accounts/users/?branch=${branchId}`);
      if (empRes.ok) {
        const empData = await empRes.json();
        const empList = Array.isArray(empData) ? empData : (empData.results || []);
        const match   = empList.find(u => u.phone && u.phone === phone);
        if (match) {
          feedback.textContent = `⚠ This number belongs to a branch employee (${match.full_name}). Cannot register.`;
          feedback.style.color = 'var(--red-text)';
          input.style.borderColor = 'var(--red-border)';
          return;
        }
      }
    } catch { /* silent */ }

    // Check against existing customers
    try {
      const res = await Auth.fetch(`/api/v1/customers/lookup/?phone=${encodeURIComponent(phone)}`);
      if (res.status === 200) {
        const existing = await res.json();
        const name     = existing.display_name || existing.full_name || 'Unknown';
        feedback.innerHTML = `⚠ A customer with this number already exists: <strong>${_esc(name)}</strong>. Cannot register a duplicate.`;
        feedback.style.color = 'var(--red-text)';
        input.style.borderColor = 'var(--red-border)';
        return;
      }
    } catch { /* silent */ }

    // Clean
    feedback.textContent    = '✓ Phone number is available';
    feedback.style.color    = 'var(--green-text)';
    input.style.borderColor = 'var(--green-border, #16a34a)';
  }

  async function _submitAddCustomer() {
    const btn    = document.getElementById('add-cust-submit-btn');
    const errEl  = document.getElementById('add-cust-error');
    errEl.style.display = 'none';

    const type      = _addCustType;
    const firstName = document.getElementById('cust-first-name')?.value.trim();
    const lastName  = document.getElementById('cust-last-name')?.value.trim();
    const phone     = _normalisePhone(document.getElementById('cust-phone')?.value.trim());
    const email     = document.getElementById('cust-email')?.value.trim();
    const address   = document.getElementById('cust-address')?.value.trim();
    const notes     = document.getElementById('cust-notes')?.value.trim();
    const company   = document.getElementById('cust-company')?.value.trim() || '';
    const subtype   = document.getElementById('cust-subtype')?.value || '';

    // ── Validation ──────────────────────────────────────────
    const showErr = msg => {
      errEl.textContent   = msg;
      errEl.style.display = 'block';
      errEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };

    if (!firstName) return showErr('First name is required.');
    if (!lastName)  return showErr('Last name is required.');
    if (!phone)     return showErr('Phone number is required.');

    if (type !== 'INDIVIDUAL' && !company) {
      return showErr(`${type === 'BUSINESS' ? 'Company' : 'Institution'} name is required.`);
    }
    if (type === 'INSTITUTION' && !subtype) {
      return showErr('Please select the institution type.');
    }
    if (type !== 'INDIVIDUAL' && !address) {
      return showErr('Address is required for businesses and institutions.');
    }

    // ── Duplicate checks ────────────────────────────────────
    btn.disabled    = true;
    btn.textContent = 'Checking…';

    // Employee phone check
    try {
      const branchId = State.branchId;
      const empRes   = await Auth.fetch(`/api/v1/accounts/users/?branch=${branchId}`);
      if (empRes.ok) {
        const empData = await empRes.json();
        const empList = Array.isArray(empData) ? empData : (empData.results || []);
        const match   = empList.find(u => u.phone && u.phone === phone);
        if (match) {
          btn.disabled    = false;
          btn.textContent = 'Register Customer';
          return showErr(`This phone number belongs to a branch employee (${match.full_name}). Registration blocked.`);
        }
      }
    } catch { /* silent */ }

    // Customer phone duplicate check
    try {
      const res = await Auth.fetch(`/api/v1/customers/lookup/?phone=${encodeURIComponent(phone)}`);
      if (res.status === 200) {
        const existing = await res.json();
        const name     = existing.display_name || existing.full_name || 'this number';
        btn.disabled    = false;
        btn.textContent = 'Register Customer';
        return showErr(`A customer with this number already exists: ${name}. Cannot create a duplicate.`);
      }
    } catch { /* silent */ }

    // Company name duplicate check
    if (company) {
      try {
        const res  = await Auth.fetch(`/api/v1/customers/?company_name=${encodeURIComponent(company)}`);
        if (res.ok) {
          const data = await res.json();
          const list = Array.isArray(data) ? data : (data.results || []);
          if (list.length > 0) {
            btn.disabled    = false;
            btn.textContent = 'Register Customer';
            return showErr(`A customer named "${company}" already exists. Cannot create a duplicate.`);
          }
        }
      } catch { /* silent */ }
    }

    // ── Submit ──────────────────────────────────────────────
    btn.textContent = 'Registering…';

    const payload = {
      customer_type       : type,
      first_name          : firstName,
      last_name           : lastName,
      phone,
      email               : email || '',
      address             : address || '',
      company_name        : company || '',
      institution_subtype : subtype || '',
      notes               : notes || '',
    };

    try {
      const res  = await Auth.fetch('/api/v1/customers/create/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify(payload),
      });
      const data = await res.json();

      if (!res.ok) {
        const msg = Object.values(data).flat().join(' ');
        btn.disabled    = false;
        btn.textContent = 'Register Customer';
        return showErr(msg || 'Registration failed. Please try again.');
      }

      // Success
      _closeAddCustomer();
      _toast(`${data.display_name || firstName + ' ' + lastName} registered successfully.`, 'success');

      // Refresh customer list
      await _loadCustomersTab(_customersTab);

      // Look up the new customer by phone to get full profile with id
      if (phone) {
        try {
          const lookupRes = await Auth.fetch(`/api/v1/customers/lookup/?phone=${encodeURIComponent(_normalisePhone(phone))}`);
          if (lookupRes.ok) {
            const newCust = await lookupRes.json();
            if (newCust.id) setTimeout(() => openCustomerDetail(newCust.id), 300);
          }
        } catch { /* silent */ }
      }

    } catch {
      btn.disabled    = false;
      btn.textContent = 'Register Customer';
      showErr('Network error. Please try again.');
    }
  }

  function _closeAddCustomer() {
    document.getElementById('add-customer-overlay')?.remove();
  }
  function _normalisePhone(raw) {
    // Strip all spaces, dashes, parentheses
    let p = String(raw || '').replace(/[\s\-().]/g, '');
    // Convert +233XXXXXXXXX → 0XXXXXXXXX
    if (p.startsWith('+233')) p = '0' + p.slice(4);
    // Convert 233XXXXXXXXX → 0XXXXXXXXX
    if (p.startsWith('233') && p.length >= 12) p = '0' + p.slice(3);
    return p;
  }

  // ── Public API ─────────────────────────────────────────────
return {
    init,
    switchPane,
    setPeriod,
    setReportsPeriod,
    switchReportsTab,
    switchJobsTab,
    switchPerformanceTab,
    printReceipt,
    openReceipt,
    setReceiptsPeriod,
    printReceiptDetail,
    sendReceiptWhatsApp,
    loadInboxTab,
    loadServicesTab,
    openOutsourceModal,
    confirmOutsource,
    closeSheet,
    downloadSheetPDF,
    onJobCreated,
    closeEOD,
    toggleEODConfirm,
    confirmCloseSheet,
    switchInboxChannel,
    openConvo,
    sendReply,
    _historyDrill,
    _historyNav,
    switchDaySheetTab,
    initiateSheetDownload,
    closePinModal,
    _onPinInput,
    _submitPin,
    toggleSheetRow,
    weeklyPrepare,
    weeklySubmit,
    weeklyDownloadPDF,
    _renderMonthlyClose,
    _submitMonthlyClose,
    _downloadMonthlyPDF,
    setServicesPeriod,
    switchInventoryTab,
    _openEquipmentModal,
    _openAddEquipment,
    _openAddMaintenanceLog,
    _saveMaintenanceLog,
    _saveEquipment,
    _printEquipmentQR,
    openReceiveStock,
    _validateFloatInput,
    openAddServiceModal,
    closeAddServiceModal,
    submitAddService,
    _svcAutoCode,
    _svcPreviewImage,
    _svcToggleConsumable,
    closeReceiveStock,
    submitReceiveStock,
    _recvFilterConsumables,
    _recvShowDropdown,
    _recvSelectConsumable,
    downloadInvoicePDF,
    openCreateInvoice,
    openLateJobModal,
    closeLateJobModal,
    submitLateJob,
    _lateJobFilterServices,
    _lateJobSelectService,
    _checkLateJobButton,
    _showClosingModal,
    switchPerformanceTab,
    _toggleDailySheet,
    _toggleCurrentWeek,
    _toggleHistoryWeek,
    switchCustomersTab,
    openCustomerDetail,
    openAddCustomerModal,
    _filterCustomerRows,
    closeCustomerProfile,
    _saveCustomerNotes,
    _editCustomer,
    _renderEditCustomerForm,
    _saveCustomerEdit,
    _editPhoneNormalise,
    _toggleEditHistory,
    _loadEditHistory,
    _nominateCredit,
  };

})();

document.addEventListener('DOMContentLoaded', Dashboard.init);


// ─────────────────────────────────────────────────────────────
// State — shared with NJ controller
// ─────────────────────────────────────────────────────────────
const State = {
  branchId  : null,
  services  : [],
  customers : [],
  page      : 1,
};


// ─────────────────────────────────────────────────────────────
// Notifications
// ─────────────────────────────────────────────────────────────
const Notifications = (() => {

  let open = false;

  async function load() {
    const list = document.getElementById('notif-list');
    if (!list) return;

    try {
      const res  = await Auth.fetch('/api/v1/notifications/');
      if (!res.ok) throw new Error();
      const data = await res.json();

      if (!data.length) {
        list.innerHTML = '<div class="notif-empty">You\'re all caught up ✓</div>';
        return;
      }

      list.innerHTML = data.map(n => `
        <div class="notif-item ${n.is_read ? 'read' : 'unread'}"
          onclick="Notifications.markRead(${n.id}, this, '${n.link || ''}')">
          <span class="notif-dot"></span>
          <span class="notif-msg">${_esc(n.message)}</span>
          <span class="notif-time">${n.time_ago || ''}</span>
        </div>`).join('');

    } catch {
      list.innerHTML = '<div class="notif-empty">Could not load notifications.</div>';
    }
  }

  async function loadCount() {
    try {
      const res  = await Auth.fetch('/api/v1/notifications/unread-count/');
      if (!res.ok) return;
      const data  = await res.json();
      const count = data.count || 0;
      const badge = document.getElementById('db-notif-badge');
      if (badge) {
        badge.textContent   = count > 99 ? '99+' : count;
        badge.style.display = count > 0 ? 'flex' : 'none';
      }
    } catch { /* silent */ }
  }

  function toggle() { open ? close() : _open(); }

  function _open() {
    open = true;
    document.getElementById('notif-dropdown')?.classList.add('open');
    load();
  }

  function close() {
    open = false;
    document.getElementById('notif-dropdown')?.classList.remove('open');
  }

  async function markRead(id, el, link) {
    try {
      await Auth.fetch(`/api/v1/notifications/${id}/read/`, { method: 'POST' });
      el?.classList.remove('unread');
      el?.classList.add('read');
      await loadCount();
    } catch { /* silent */ }
    if (link) { close(); window.location = link; }
  }

  async function markAllRead() {
    try {
      await Auth.fetch('/api/v1/notifications/read-all/', { method: 'POST' });
      document.querySelectorAll('.notif-item.unread').forEach(el => {
        el.classList.remove('unread');
        el.classList.add('read');
      });
      await loadCount();
    } catch { /* silent */ }
  }

  function startPolling(intervalMs = 30000) {
    loadCount();
    setInterval(loadCount, intervalMs);
  }

  function _esc(str) {
    return String(str ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  return { toggle, close, markRead, markAllRead, loadCount, startPolling };

})();

