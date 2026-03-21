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
    if (paneId === 'jobs'    && !jobsLoaded)  _loadJobsPane();
    if (paneId === 'inbox'   && !inboxLoaded) loadInboxTab();
    if (paneId === 'services'&& !svcLoaded)   loadServicesTab();
    if (paneId === 'finance') {
      const pane = document.getElementById('pane-finance');
      if (pane) pane.dataset.loaded = '';
      _loadFinancePane();
    }
    if (paneId === 'reports')                 _loadReportsPane();
  }

  // ── Jobs pane ──────────────────────────────────────────────
      function _loadJobsPane() {
        jobsLoaded = true;
        Jobs.init({ embedded: true });
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
    const checked = document.getElementById('eod-ack-checkbox').checked;
    document.getElementById('eod-confirm-btn').disabled = !checked;
  }

  function _fmt(n) {
    return `GHS ${parseFloat(n || 0).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
  }

  function _renderEOD(d) {
    const meta = d.meta;
    const rev  = d.revenue;
    const jobs = d.jobs;

    // Subtitle
    const dateStr = new Date(meta.date).toLocaleDateString('en-GH', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
    });
    document.getElementById('eod-subtitle').textContent =
      `${dateStr} · ${meta.branch}`;
    document.getElementById('eod-ack-branch').textContent = meta.branch;

    // ── Revenue ──────────────────────────────────────────────────
    document.getElementById('eod-cash').textContent        = _fmt(rev.cash);
    document.getElementById('eod-momo').textContent        = _fmt(rev.momo);
    document.getElementById('eod-pos').textContent         = _fmt(rev.pos);
    document.getElementById('eod-total').textContent       = _fmt(rev.total);
    document.getElementById('eod-credit-issued').textContent  = _fmt(rev.credit_issued);
    document.getElementById('eod-petty-cash-out').textContent = _fmt(rev.petty_cash_out);
    document.getElementById('eod-net-cash').textContent    = _fmt(rev.net_cash_in_till);

    // ── Jobs checklist ───────────────────────────────────────────
    const cl = document.getElementById('eod-jobs-checklist');
    cl.innerHTML = [
      _checkItem('ok',
        `${jobs.total} jobs created · ${jobs.completed} completed`,
        jobs.cancelled ? `${jobs.cancelled} cancelled` : null),
      _checkItem('ok',
        `${jobs.local} local jobs · ${jobs.routed_out} routed out`,
        jobs.routed_in ? `${jobs.routed_in} routed in from other branches` : null),
      jobs.pending_payment > 0
        ? _checkItem('warn',
            `${jobs.pending_payment} pending payment — will carry forward`,
            `${jobs.pending_untouched} never touched by cashier`)
        : _checkItem('ok', 'All jobs paid — no carry-forwards', null),
      d.float_opened
        ? _checkItem('ok', 'Cashier float opened today', null)
        : _checkItem('warn', 'No cashier float was opened today', null),
    ].join('');

    // ── Pending payments list ─────────────────────────────────────
    const pendingBadge = document.getElementById('eod-pending-badge');
    pendingBadge.textContent = jobs.pending_payment;
    pendingBadge.style.display = jobs.pending_payment ? 'inline-flex' : 'none';

    const pendingNote = document.getElementById('eod-pending-note');
    pendingNote.style.display = jobs.pending_list.length ? 'block' : 'none';

    document.getElementById('eod-pending-list').innerHTML =
      jobs.pending_list.length
        ? _jobMiniTable(jobs.pending_list)
        : '<div class="eod-empty-note">No pending payments.</div>';

    const untouchedSubtitle = document.getElementById('eod-untouched-subtitle');
    const untouchedNote     = document.getElementById('eod-untouched-note');
    untouchedSubtitle.style.display = jobs.untouched_list.length ? 'block' : 'none';
    untouchedNote.style.display     = jobs.untouched_list.length ? 'block' : 'none';
    document.getElementById('eod-untouched-list').innerHTML =
      jobs.untouched_list.length ? _jobMiniTable(jobs.untouched_list) : '';

    // ── Cashier activity ─────────────────────────────────────────
    const cashierEl = document.getElementById('eod-cashier-activity');
    const floatWarn = document.getElementById('eod-float-warning');
    floatWarn.style.display = d.float_opened ? 'none' : 'block';

    if (d.cashier_activity.length) {
      cashierEl.innerHTML = d.cashier_activity.map(c => {
        const methods = ['CASH', 'MOMO', 'POS'].map(m => {
          const info = c.method_breakdown[m];
          if (!info) return '';
          return `
            <div class="eod-method-pill ${m.toLowerCase()}">
              <span class="eod-method-pill-label">${m}</span>
              <span class="eod-method-pill-val">${_fmt(info.total)}</span>
            </div>`;
        }).join('');

        const activeFrom = c.active_from
          ? new Date(c.active_from).toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' })
          : '—';
        const activeTo = c.active_to
          ? new Date(c.active_to).toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' })
          : '—';

        const variance    = parseFloat(c.variance || 0);
        const varClass    = variance === 0 ? 'variance-ok' : 'variance-warn';
        const varDisplay  = variance >= 0 ? `+${_fmt(variance)}` : _fmt(variance);
        const signoffHtml = c.is_signed_off
          ? `<span class="eod-signoff-badge ok">✓ Signed off</span>`
          : `<span class="eod-signoff-badge pending">⚠ Not signed off</span>`;

        return `
          <div class="eod-cashier-card">
            <div class="eod-cashier-head">
              <div>
                <div class="eod-cashier-name">${c.cashier_name}</div>
                <div class="eod-cashier-meta">Active ${activeFrom} → ${activeTo} · ${c.transaction_count} transactions</div>
              </div>
              <div style="display:flex;align-items:center;gap:10px;">
                ${signoffHtml}
                <div class="eod-cashier-total">${_fmt(c.total_collected)}</div>
              </div>
            </div>
            <div class="eod-cashier-body">
              <div class="eod-cashier-methods">${methods}</div>
              <div class="eod-cashier-float-row">
                <div class="eod-float-item">
                  <span class="eod-float-label">Opening Float</span>
                  <span class="eod-float-val">${_fmt(c.opening_float)}</span>
                </div>
                <div class="eod-float-item">
                  <span class="eod-float-label">Expected Cash</span>
                  <span class="eod-float-val">${_fmt(c.expected_cash)}</span>
                </div>
                <div class="eod-float-item">
                  <span class="eod-float-label">Closing Cash</span>
                  <span class="eod-float-val">${_fmt(c.closing_cash)}</span>
                </div>
                <div class="eod-float-item">
                  <span class="eod-float-label">Variance</span>
                  <span class="eod-float-val ${varClass}">${varDisplay}</span>
                </div>
                ${c.variance_notes ? `
                <div class="eod-float-item" style="flex:1;">
                  <span class="eod-float-label">Variance Notes</span>
                  <span class="eod-float-val" style="font-family:inherit;font-size:12px;">${c.variance_notes}</span>
                </div>` : ''}
              </div>
            </div>
          </div>`;
      }).join('');
    } else {
      cashierEl.innerHTML = '<div class="eod-empty-note">No cashier activity recorded today.</div>';
    }

    // ── Petty cash ────────────────────────────────────────────────
    const pettyEl = document.getElementById('eod-petty-list');
    if (d.petty_cash.length) {
      pettyEl.innerHTML = `
        <table class="eod-table">
          <thead>
            <tr>
              <th>Reason</th>
              <th>Recorded By</th>
              <th>Time</th>
              <th style="text-align:right;">Amount</th>
            </tr>
          </thead>
          <tbody>
            ${d.petty_cash.map(p => `
              <tr>
                <td>${p.reason || '—'}</td>
                <td>${p.recorded_by_name}</td>
                <td>${p.created_at ? new Date(p.created_at).toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' }) : '—'}</td>
                <td class="mono" style="text-align:right;">${_fmt(p.amount)}</td>
              </tr>`).join('')}
          </tbody>
        </table>`;
    } else {
      pettyEl.innerHTML = '<div class="eod-empty-note">No petty cash disbursements today.</div>';
    }

    // ── Credit sales ──────────────────────────────────────────────
    const creditEl = document.getElementById('eod-credit-list');
    if (d.credit_sales.length) {
      creditEl.innerHTML = `
        <table class="eod-table">
          <thead>
            <tr>
              <th>Job Ref</th>
              <th>Title</th>
              <th>Customer</th>
              <th style="text-align:right;">Amount</th>
            </tr>
          </thead>
          <tbody>
            ${d.credit_sales.map(c => `
              <tr>
                <td class="mono">${c.job_number}</td>
                <td>${c.title || '—'}</td>
                <td>${c.customer_name}</td>
                <td class="mono" style="text-align:right;">${_fmt(c.estimated_cost)}</td>
              </tr>`).join('')}
          </tbody>
        </table>`;
    } else {
      creditEl.innerHTML = '<div class="eod-empty-note">No credit sales today.</div>';
    }

    // ── Show content ──────────────────────────────────────────────
    document.getElementById('eod-loading').style.display = 'none';
    document.getElementById('eod-content').style.display = 'block';
    document.getElementById('eod-footer').style.display  = 'flex';
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
          body: JSON.stringify({ notes }),
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
        <div class="service-card-name">${_esc(s.name)}</div>
        <div class="service-card-price">${s.base_price != null ? 'GHS ' + Number(s.base_price).toFixed(2) : '—'}</div>
        <div class="service-card-desc">${_esc(s.description || '')}</div>
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
// ── Reports pane ─────────────────────────────────────────────
async function _loadReportsPane() {
    const pane = document.getElementById('pane-reports');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Reports & Filing</span>
      </div>

      <div class="reports-tabs">
        <button class="reports-tab active" data-tab="history"
          onclick="Dashboard.switchReportsTab('history')">Jobs Archive</button>
        <button class="reports-tab" data-tab="filing"
          onclick="Dashboard.switchReportsTab('filing')">Weekly Filing</button>
        <button class="reports-tab" data-tab="services"
          onclick="Dashboard.switchReportsTab('services')">Service Performance</button>
      </div>

      <div id="reports-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    await _loadReportsTab('history');
  }
  async function setReportsPeriod(period) {
    const activeTab = document.querySelector('.reports-tab.active')?.dataset.tab || 'history';
    await _loadReportsTab(activeTab);
  }

  async function switchReportsTab(tab) {
    document.querySelectorAll('.reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    await _loadReportsTab(tab);
  }

  async function _loadReportsTab(tab) {
    const content = document.getElementById('reports-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    if (tab === 'history')  await _renderHistoryReport(content);
    if (tab === 'filing')   await _renderWeeklyFiling(content);
    if (tab === 'services') await _renderServicesReport(content);
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

 async function _renderWeeklyFiling(container) {
    if (!container) return;

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
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
      </div>`;

    await _loadWeeklyReport();
  }

  async function _loadWeeklyReport() {
    const content = document.getElementById('weekly-content');
    if (!content) return;

    try {
      // Check if a report exists for current week
      const res  = await Auth.fetch('/api/v1/finance/weekly/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const reports = data.results || data;

      // Get current ISO week
      const now    = new Date();
      const jan4   = new Date(now.getFullYear(), 0, 4);
      const weekN  = Math.ceil(((now - jan4) / 86400000 + jan4.getDay() + 1) / 7);

      const current = reports.find(r =>
        r.week_number === weekN && r.year === now.getFullYear()
      );

      if (current) {
        _renderWeeklyReportDetail(content, current);
      } else {
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

  function _renderWeeklyReportDetail(container, report) {
    const fmt     = n => `GHS ${Number(n).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
    const isLocked = report.status === 'LOCKED';
    const isDraft  = report.status === 'DRAFT';

    const statusColor = {
      DRAFT     : 'var(--amber-text)',
      SUBMITTED : 'var(--green-text)',
      LOCKED    : 'var(--green-text)',
    }[report.status] || 'var(--text-3)';

    const statusBg = {
      DRAFT     : 'var(--amber-bg)',
      SUBMITTED : 'var(--green-bg)',
      LOCKED    : 'var(--green-bg)',
    }[report.status] || 'var(--bg)';

    // ── Sheet status grid ─────────────────────────────────────────────────
    const days    = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const sheets  = report.daily_sheets || [];

    const sheetGrid = days.map((day, i) => {
      const sheet = sheets.find(s => new Date(s.date).getDay() === (i + 1));
      if (!sheet) {
        return `
          <div style="flex:1;padding:10px 8px;background:var(--bg);border:1px solid var(--border);
            border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;margin-bottom:4px;">${day}</div>
            <div style="font-size:10px;color:var(--text-3);">No sheet</div>
          </div>`;
      }
      const isClosed = sheet.status !== 'OPEN';
      const dotColor = isClosed ? 'var(--green-text)' : 'var(--amber-text)';
      const dotBg    = isClosed ? 'var(--green-bg)'   : 'var(--amber-bg)';
      return `
        <div style="flex:1;padding:10px 8px;background:${dotBg};
          border:1px solid ${isClosed ? 'var(--green-border)' : 'var(--amber-border)'};
          border-radius:var(--radius-sm);text-align:center;">
          <div style="font-size:10px;font-weight:700;color:${dotColor};
            text-transform:uppercase;margin-bottom:4px;">${day}</div>
          <div style="font-size:10px;color:${dotColor};font-weight:600;">
            ${isClosed ? '✓ Closed' : '● Open'}
          </div>
          <div style="font-size:9px;color:${dotColor};margin-top:2px;
            font-family:'JetBrains Mono',monospace;">
            ${fmt(parseFloat(sheet.total_cash||0) + parseFloat(sheet.total_momo||0) + parseFloat(sheet.total_pos||0))}
          </div>
        </div>`;
    }).join('');

    container.innerHTML = `
      <!-- Status header -->
      <div style="display:flex;align-items:center;justify-content:space-between;
        background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);
        padding:16px 20px;margin-bottom:16px;">
        <div>
          <div style="font-size:13px;font-weight:600;color:var(--text);">
            Week ${report.week_number}, ${report.year}
          </div>
          <div style="font-size:12px;color:var(--text-3);margin-top:2px;">
            ${new Date(report.date_from).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}
            –
            ${new Date(report.date_to).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })}
          </div>
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;
            background:${statusBg};color:${statusColor};">${report.status}</span>
          ${isDraft ? `
            <button onclick="Dashboard.weeklyPrepare()"
              style="padding:6px 14px;background:none;border:1.5px solid var(--border);
                     border-radius:var(--radius-sm);font-size:12px;font-weight:600;
                     cursor:pointer;color:var(--text-2);font-family:'DM Sans',sans-serif;">
              Refresh
            </button>` : ''}
          ${isLocked && report.pdf_path ? `
            <button onclick="Dashboard.weeklyDownloadPDF(${report.id})"
              style="padding:6px 14px;background:var(--text);color:#fff;border:none;
                     border-radius:var(--radius-sm);font-size:12px;font-weight:600;
                     cursor:pointer;font-family:'DM Sans',sans-serif;">
              Download PDF
            </button>` : ''}
        </div>
      </div>

      <!-- Sheet status grid -->
      <div style="margin-bottom:16px;">
        <div style="font-size:10.5px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.8px;margin-bottom:10px;">Daily Sheets</div>
        <div style="display:flex;gap:8px;">${sheetGrid}</div>
      </div>

      <!-- Revenue summary -->
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:10px;margin-bottom:16px;">
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:14px 16px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Total Collected</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:16px;
            font-weight:700;color:var(--text);">${fmt(parseFloat(report.total_cash||0) + parseFloat(report.total_momo||0) + parseFloat(report.total_pos||0))}</div>
        </div>
        <div style="background:var(--cash-bg);border:1px solid var(--cash-border);
          border-radius:var(--radius);padding:14px 16px;">
          <div style="font-size:10px;font-weight:700;color:var(--cash-text);
            text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Cash</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:16px;
            font-weight:700;color:var(--cash-strong);">${fmt(parseFloat(report.total_cash||0))}</div>
        </div>
        <div style="background:var(--momo-bg);border:1px solid var(--momo-border);
          border-radius:var(--radius);padding:14px 16px;">
          <div style="font-size:10px;font-weight:700;color:var(--momo-text);
            text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">MoMo</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:16px;
            font-weight:700;color:var(--momo-strong);">${fmt(parseFloat(report.total_momo||0))}</div>
        </div>
        <div style="background:var(--pos-bg);border:1px solid var(--pos-border);
          border-radius:var(--radius);padding:14px 16px;">
          <div style="font-size:10px;font-weight:700;color:var(--pos-text);
            text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">POS</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:16px;
            font-weight:700;color:var(--pos-strong);">${fmt(parseFloat(report.total_pos||0))}</div>
        </div>
      </div>

      <!-- Jobs summary -->
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:16px;">
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:14px 16px;text-align:center;">
          <div style="font-family:'Outfit',sans-serif;font-size:22px;font-weight:700;
            color:var(--text);">${fmt(parseFloat(report.total_jobs_created||0))}</div>
          <div style="font-size:11px;color:var(--text-3);margin-top:2px;">Jobs Created</div>
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:14px 16px;text-align:center;">
          <div style="font-family:'Outfit',sans-serif;font-size:22px;font-weight:700;
            color:var(--green-text);">${report.total_jobs_complete}</div>
          <div style="font-size:11px;color:var(--text-3);margin-top:2px;">Completed</div>
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:14px 16px;text-align:center;">
          <div style="font-family:'Outfit',sans-serif;font-size:22px;font-weight:700;
            color:var(--red-text);">${report.total_jobs_cancelled}</div>
          <div style="font-size:11px;color:var(--text-3);margin-top:2px;">Cancelled</div>
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:14px 16px;text-align:center;">
          <div style="font-family:'Outfit',sans-serif;font-size:22px;font-weight:700;
            color:var(--amber-text);">${report.carry_forward_count}</div>
          <div style="font-size:11px;color:var(--text-3);margin-top:2px;">Carry Forward</div>
        </div>
      </div>

      <!-- Inventory placeholder -->
      <div style="background:#fffbec;border:1px solid var(--momo-border);
        border-radius:var(--radius);padding:14px 16px;margin-bottom:16px;
        display:flex;align-items:center;gap:10px;">
        <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
          fill="none" stroke="var(--momo-text)" stroke-width="2">
          <circle cx="12" cy="12" r="10"/>
          <line x1="12" y1="8" x2="12" y2="12"/>
          <line x1="12" y1="16" x2="12.01" y2="16"/>
        </svg>
        <span style="font-size:12.5px;color:var(--momo-text);">
          Inventory section will appear here once the inventory module is active.
        </span>
      </div>

      <!-- BM Notes -->
      <div style="margin-bottom:16px;">
        <div style="font-size:10.5px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">Branch Manager Notes</div>
        ${isLocked
          ? `<div style="background:var(--panel);border:1px solid var(--border);
               border-radius:var(--radius);padding:14px 16px;font-size:13px;
               color:var(--text-2);min-height:60px;">${report.bm_notes || '—'}</div>`
          : `<textarea id="weekly-notes" rows="3"
               placeholder="Add weekly observations, incidents, or notes…"
               style="width:100%;padding:10px 14px;border:1.5px solid var(--border);
                      border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                      font-size:13px;resize:vertical;box-sizing:border-box;
                      font-family:'DM Sans',sans-serif;">${report.bm_notes || ''}</textarea>`
        }
      </div>

      <!-- Submit button -->
      ${isDraft ? `
        <div style="display:flex;justify-content:flex-end;gap:10px;">
          <button onclick="Dashboard.weeklySubmit(${report.id})"
            id="weekly-submit-btn"
            style="padding:10px 24px;background:var(--text);color:#fff;border:none;
                   border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                   cursor:pointer;font-family:'DM Sans',sans-serif;
                   ${!report.all_sheets_closed ? 'opacity:0.4;cursor:not-allowed;' : ''}">
            ${report.all_sheets_closed ? 'Submit & Lock Filing' : 'Close all sheets to submit'}
          </button>
        </div>
        ${!report.all_sheets_closed ? `
          <div style="text-align:right;font-size:12px;color:var(--text-3);margin-top:6px;">
            All daily sheets must be closed before the weekly filing can be submitted.
          </div>` : ''}
      ` : ''}

      ${isLocked ? `
        <div style="background:var(--green-bg);border:1px solid var(--green-border);
          border-radius:var(--radius);padding:14px 16px;display:flex;
          align-items:center;gap:10px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24"
            fill="none" stroke="var(--green-text)" stroke-width="2">
            <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
            <polyline points="22 4 12 14.01 9 11.01"/>
          </svg>
          <span style="font-size:13px;font-weight:600;color:var(--green-text);">
            Filed by ${report.submitted_by_name || '—'} on
            ${report.submitted_at
              ? new Date(report.submitted_at).toLocaleDateString('en-GB',
                  { day: 'numeric', month: 'short', year: 'numeric' })
              : '—'}
          </span>
        </div>
      ` : ''}`;
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
    if (!container) container = document.getElementById('reports-content');
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
            <div onclick="Dashboard._historyDrill(${JSON.stringify(item).replace(/"/g,'&quot;')})"
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
            <div onclick="Dashboard._historyDrill(${JSON.stringify(item).replace(/"/g,'&quot;')})"
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

  function _historyDrill(item) {
    if (typeof item === 'string') {
      try { item = JSON.parse(item.replace(/&quot;/g, '"')); } catch { return; }
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

    _fetchAndRenderHistory(document.getElementById('reports-content'));
  }

  function _historyNav(level, year, month, week) {
    _historyLevel = level;
    _historyYear  = year;
    _historyMonth = month;
    _historyWeek  = week;
    _fetchAndRenderHistory(document.getElementById('reports-content'));
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
  // ── Public API ─────────────────────────────────────────────
return {
    init,
    switchPane,
    setPeriod,
    setReportsPeriod,
    switchReportsTab,
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
    setServicesPeriod,
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

