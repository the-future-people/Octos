/**
 * Octos ? Branch Manager Dashboard
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

  // -- State --------------------------------------------------
  let branchId      = null;
  let services      = [];
  let customers     = [];
  let jobsLoaded    = false;
  let inboxLoaded   = false;
  let svcLoaded     = false;
  let currentPeriod = 'day';

  // -- Boot ---------------------------------------------------
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

  // -- Context ------------------------------------------------
  async function loadContext() {
    try {
      const res = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const user = await res.json();

      const fullName = user.full_name || user.email || '?';
      const initials = fullName.split(' ').slice(0, 2)
        .map(w => w[0]?.toUpperCase() || '').join('');

      _set('db-user-name',     fullName);
      _set('db-user-initials', initials);
      if (user.employment_status === 'SHADOW') {
        document.querySelectorAll('.hero-btn, .btn-dark, #late-job-btn').forEach(el => {
          el.style.display = 'none';
        });
      }

   if (user.branch_detail) {
        const b = user.branch_detail;
        branchId = b.id;
        State.branchId = branchId;    // ? add this
        _set('db-branch-name', b.name || '?');
        _set('db-branch-name-left', b.name || '?');
        _set('db-branch-pill', b.name || '?');
        if (b.region_name)      _set('meta-region', b.region_name);
        if (b.belt_name)        _set('meta-belt',   b.belt_name);
        if (b.load_percentage != null) _set('meta-load', b.load_percentage + '%');
      }else if (user.branch && typeof user.branch === 'number') {
        branchId = user.branch;
        State.branchId = branchId;    // ? add this
        if (br.ok) {
          const b = await br.json();
          _set('db-branch-name', b.name || '?');
          _set('db-branch-name-left', b.name || '?');
          _set('db-branch-pill', b.name || '?');
          if (b.region_name)      _set('meta-region', b.region_name);
          if (b.belt_name)        _set('meta-belt',   b.belt_name);
          if (b.load_percentage != null) _set('meta-load', b.load_percentage + '%');
        }
      }
    } catch { /* silent */ }
    _checkHandoverBanners();
  }

// -- Handover / Shadow banners ------------------------------
  async function _checkHandoverBanners() {
    try {
      const res  = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const user = await res.json();

      // -- Shadow banner ? incoming employee ------------------
      if (user.employment_status === 'SHADOW') {
        const paRes = await Auth.fetch('/api/v1/accounts/pending-activation/me/');
        if (paRes.ok) {
          const pa       = await paRes.json();
          const daysLeft = pa.days_until_start;
          const dateStr  = new Date(pa.start_date).toLocaleDateString('en-GB', {
            day: 'numeric', month: 'short', year: 'numeric',
          });
          _injectBanner({
            id      : 'shadow-banner',
            color   : '#1a3599',
            bg      : '#eef3ff',
            border  : '#b0c4f8',
            icon    : '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
            message : `You go live in <strong>${daysLeft} day${daysLeft !== 1 ? 's' : ''}</strong> ? Assumption date: ${dateStr}`,
            sub     : 'You currently have read-only shadow access. Full access activates on your start date.',
          });
        }
        return; // shadow users don't see outgoing handover banner
      }

      // -- Outgoing BM banner ? being replaced ----------------
      const dispRes = await Auth.fetch('/api/v1/accounts/pending-activation/displacing-me/');
      if (dispRes.ok) {
        const pa       = await dispRes.json();
        const daysLeft = pa.days_until_start;
        const dateStr  = new Date(pa.start_date).toLocaleDateString('en-GB', {
          day: 'numeric', month: 'short', year: 'numeric',
        });
        const urgency  = daysLeft <= 3 ? '#b91c1c' : daysLeft <= 7 ? '#7a5c00' : '#1a6640';
        const urgencyBg = daysLeft <= 3 ? '#fff0f0' : daysLeft <= 7 ? '#fffbec' : '#edfaf4';
        const urgencyBorder = daysLeft <= 3 ? '#fca5a5' : daysLeft <= 7 ? '#f0d878' : '#a8dfc0';
        _injectBanner({
          id      : 'handover-banner',
          color   : urgency,
          bg      : urgencyBg,
          border  : urgencyBorder,
          icon    : '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
          message : `Handover in <strong>${daysLeft} day${daysLeft !== 1 ? 's' : ''}</strong> ? ${pa.incoming_name} assumes on ${dateStr}`,
          sub     : 'Ensure open jobs are resolved, sheets are closed, and floats are reconciled before handover.',
        });
      }
    } catch { /* silent ? banners are non-critical */ }
  }

  function _injectBanner({ id, color, bg, border, icon, message, sub }) {
    // Remove existing banner of same id
    document.getElementById(id)?.remove();

    const banner = document.createElement('div');
    banner.id    = id;
    banner.style.cssText = `
      display:flex;align-items:flex-start;gap:12px;
      padding:12px 18px;margin-bottom:12px;
      background:${bg};border:1px solid ${border};
      border-radius:var(--radius-sm);
      animation:fadeIn 0.3s ease;`;

    banner.innerHTML = `
      <div style="flex-shrink:0;width:32px;height:32px;border-radius:8px;
        background:${bg};border:1px solid ${border};
        display:flex;align-items:center;justify-content:center;">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
          viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2">
          ${icon}
        </svg>
      </div>
      <div style="flex:1;">
        <div style="font-size:13px;font-weight:600;color:${color};margin-bottom:3px;">
          ${message}
        </div>
        <div style="font-size:11px;color:${color};opacity:0.8;line-height:1.5;">
          ${sub}
        </div>
      </div>
      <button onclick="document.getElementById('${id}').remove()"
        style="flex-shrink:0;background:none;border:none;cursor:pointer;
          color:${color};opacity:0.5;font-size:16px;padding:0;line-height:1;">?</button>`;

    // Inject at top of main content area, below the meta strip
    const main = document.getElementById('db-main') || document.querySelector('.db-main') || document.body;
    main.insertBefore(banner, main.firstChild);
  }

  // -- Stats --------------------------------------------------
 async function loadStats() {
    try {
      const sheetRes = await Auth.fetch('/api/v1/finance/sheets/today/');
      const sheet    = sheetRes.ok ? await sheetRes.json() : null;

      const param = sheet?.id ? `daily_sheet=${sheet.id}` : 'period=day';
      const res   = await Auth.fetch(`/api/v1/jobs/stats/?${param}`);
      if (!res.ok) return;
      const stats = await res.json();

      _setStats(
        stats.total       || 0,
        stats.in_progress || 0,
        stats.complete    || 0,
        stats.pending     || 0,
        stats.routed      || 0,
      );
    } catch { /* silent */ }
  }

  function _setStats(total, inProgress, complete, pending, routed) {
    _set('stat-total-jobs',      total);
    _set('stat-in-progress',     inProgress);
    _set('stat-complete',        complete);
    _set('stat-pending-payment', pending);
    _set('stat-routed',          routed);
  }

  // -- Recent jobs --------------------------------------------
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
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--text-3);font-size:13px;">Today's sheet is closed ? jobs archived in the day sheet PDF.</td></tr>`;
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
            <div class="td-job-title">${_esc(j.title || '?')}</div>
            <div class="td-job-ref">${_esc(j.job_number || '#' + j.id)}</div>
          </td>
          <td>${_typeBadge(j.job_type)}</td>
          <td>${_statusBadge(j.status)}</td>
          <td style="font-family:'JetBrains Mono',monospace;font-size:12.5px;">
            ${j.estimated_cost != null ? 'GHS ' + Number(j.estimated_cost).toFixed(2) : '?'}
          </td>
          <td style="font-size:12px;color:var(--text-3);">${_formatDate(j.created_at)}</td>
          <td>
            ${j.is_routed
              ? `<span style="font-size:12px;color:var(--purple-text);">? Routed</span>`
              : `<span style="font-size:12px;color:var(--text-3);">Local</span>`}
          </td>
        </tr>`).join('');

    } catch {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--text-3);">Could not load jobs.</td></tr>`;
    }
  }

  // -- Metrics ------------------------------------------------
  function setPeriod(period) {
    currentPeriod = period;
    document.querySelectorAll('.period-tab').forEach(t => {
      t.classList.toggle('active', t.dataset.period === period);
    });
    _renderMetrics(period);  // async ? fire and forget
  }

  async function _renderMetrics(period) {
    const grid = document.getElementById('metrics-grid');
    if (!grid) return;

    grid.innerHTML = `<div class="loading-cell" style="grid-column:1/-1;padding:40px !important;">
      <span class="spin"></span> Loading metrics?</div>`;

    try {
      // Fetch today's sheet for day-scoped data
      const sheetRes = await Auth.fetch('/api/v1/finance/sheets/today/');
      const sheet    = sheetRes.ok ? await sheetRes.json() : null;

      // Fetch job stats ? scope by period
      const paramMap = { day: `daily_sheet=${sheet?.id}`, week: 'period=week', month: 'period=month' };
      const statsRes = await Auth.fetch(`/api/v1/jobs/stats/?${paramMap[period] || paramMap.day}`);
      const stats    = statsRes.ok ? await statsRes.json() : {};

      const total      = stats.total      || 0;
      const complete   = stats.complete   || 0;
      const pending    = stats.pending    || 0;
      const inProgress = stats.in_progress || 0;
      const registered = stats.registered || 0;
      const revenue    = parseFloat(stats.revenue || 0);

      // -- Rates --------------------------------------------
      const completionRate   = total > 0 ? Math.round(complete / total * 100)   : 0;
      const registrationRate = total > 0 ? Math.round(registered / total * 100) : 0;
      const queueClearance   = total > 0 ? Math.round((total - pending - inProgress) / total * 100) : 0;

      // Collection rate: revenue vs estimated (use sheet totals for day, stats revenue for others)
      const sheetRevenue = sheet
        ? parseFloat(sheet.total_cash||0) + parseFloat(sheet.total_momo||0) + parseFloat(sheet.total_pos||0)
        : revenue;
      const collectionRate = period === 'day' && sheet
        ? (sheetRevenue > 0 && complete > 0 ? Math.min(100, Math.round((complete / Math.max(total,1)) * 100)) : 0)
        : (total > 0 ? Math.round(complete / total * 100) : 0);

      // -- Absolute stats -----------------------------------
      const avgJobValue = complete > 0 ? (revenue / complete) : 0;
      const displayRevenue = period === 'day' ? sheetRevenue : revenue;

      // -- Render -------------------------------------------
      const periodLabel = { day: 'today', week: 'this week', month: 'this month' }[period] || 'today';

      const rings = [
        { name: 'Completion Rate',   value: completionRate,   color: '#22c98a', sub: `${complete} of ${total} jobs done ${periodLabel}` },
        { name: 'Registration Rate', value: registrationRate, color: '#3355cc', sub: `${registered} of ${total} jobs linked to a customer` },
        { name: 'Queue Clearance',   value: queueClearance,   color: '#9b59b6', sub: `${pending + inProgress} job${pending+inProgress!==1?'s':''} still outstanding` },
        { name: 'Collection Rate',   value: collectionRate,   color: '#e8a820', sub: `Based on completed vs total jobs` },
      ];

      const ringHtml = rings.map(m => {
        const circumference = 2 * Math.PI * 30;
        const offset = circumference * (1 - m.value / 100);
        const textColor = m.value >= 70 ? m.color : m.value >= 40 ? '#d97706' : '#dc2626';
        return `
          <div style="background:var(--panel);border:1px solid var(--border);
            border-radius:var(--radius);padding:20px 16px;display:flex;
            flex-direction:column;align-items:center;gap:10px;text-align:center;">
            <div style="position:relative;width:80px;height:80px;">
              <svg viewBox="0 0 72 72" width="80" height="80" style="transform:rotate(-90deg);">
                <circle cx="36" cy="36" r="30" fill="none"
                  stroke="var(--border)" stroke-width="5"/>
                <circle cx="36" cy="36" r="30" fill="none"
                  stroke="${m.color}" stroke-width="5"
                  stroke-dasharray="${circumference}"
                  stroke-dashoffset="${offset}"
                  stroke-linecap="round"
                  style="transition:stroke-dashoffset 0.6s ease;"/>
              </svg>
              <div style="position:absolute;inset:0;display:flex;align-items:center;
                justify-content:center;font-family:'JetBrains Mono',monospace;
                font-size:15px;font-weight:800;color:${textColor};">
                ${m.value}%
              </div>
            </div>
            <div style="font-size:12px;font-weight:700;color:var(--text);">${m.name}</div>
            <div style="font-size:11px;color:var(--text-3);line-height:1.4;">${m.sub}</div>
          </div>`;
      }).join('');

      // Stat cards for absolute values
      const statHtml = `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:20px 16px;display:flex;
          flex-direction:column;justify-content:center;gap:6px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;">Revenue ${periodLabel}</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:22px;
            font-weight:800;color:#22c98a;">
            ${_fmt(displayRevenue)}
          </div>
          <div style="font-size:11px;color:var(--text-3);">
            Cash ? MoMo ? POS combined
          </div>
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:20px 16px;display:flex;
          flex-direction:column;justify-content:center;gap:6px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;">Avg Job Value</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:22px;
            font-weight:800;color:#3355cc;">
            ${avgJobValue > 0 ? _fmt(avgJobValue) : '?'}
          </div>
          <div style="font-size:11px;color:var(--text-3);">
            Per completed job ${periodLabel}
          </div>
        </div>`;

      grid.innerHTML = `
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));
          gap:12px;width:100%;">
          ${ringHtml}
          ${statHtml}
        </div>`;

    } catch {
      grid.innerHTML = `<div class="loading-cell" style="grid-column:1/-1;color:var(--red-text);">
        Could not load metrics.</div>`;
    }
  }

  function _getMetricData(period) {
    // Placeholder ? will be replaced with real API data
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

  // -- Pane switching -----------------------------------------
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
    if (paneId === 'catalogue'   && !svcLoaded)   Catalogue.loadServicesTab();
    if (paneId === 'performance')                 Performance.loadPerformancePane();
    if (paneId === 'finance') {
      const pane = document.getElementById('pane-finance');
      if (pane) pane.dataset.loaded = '';  // always bust cache on navigation
      _loadFinancePane();
    }
    if (paneId === 'reports')                     Reports.loadReportsPane();
    if (paneId === 'inventory')                   Inventory.loadInventoryPane();
    if (paneId === 'customers')                   Customers.loadCustomersPane();
  }

  // -- Jobs pane ----------------------------------------------
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
          <div class="stat-card blue"><div class="stat-num" id="jobs-stat-total">?</div><div class="stat-lbl">Total Jobs</div></div>
          <div class="stat-card amber"><div class="stat-num" id="jobs-stat-in-progress">?</div><div class="stat-lbl">In Progress</div></div>
          <div class="stat-card green"><div class="stat-num" id="jobs-stat-complete">?</div><div class="stat-lbl">Complete</div></div>
          <div class="stat-card purple"><div class="stat-num" id="jobs-stat-revenue">?</div><div class="stat-lbl">Revenue (GHS)</div></div>
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
            <input type="text" id="jobs-search" class="inp-sm" placeholder="Search jobs?" style="width:180px;">
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
              <tr><td colspan="6" class="loading-cell"><span class="spin"></span> Loading jobs?</td></tr>
            </tbody>
          </table>
          <div class="jobs-pagination" id="jobs-pagination" style="display:none;">
            <span class="jobs-page-info" id="jobs-page-info"></span>
            <div class="jobs-page-btns">
              <button class="jobs-page-btn" id="jobs-btn-prev" onclick="Jobs.prevPage()">? Prev</button>
              <button class="jobs-page-btn" id="jobs-btn-next" onclick="Jobs.nextPage()">Next ?</button>
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
          <div class="loading-cell"><span class="spin"></span> Loading?</div>
        </div>`;
      _loadInvoicesContent();
    }

    if (tab === 'receipts') {
      content.innerHTML = `
        <div class="section-head">
          <span class="section-title">Receipts</span>
          <span style="font-size:12px;color:var(--text-3);">Read-only ? Completed jobs</span>
        </div>
        <div id="receipts-content">
          <div class="loading-cell"><span class="spin"></span> Loading?</div>
        </div>`;
      _loadReceiptsContent();
    }
  }

let _invoicesPeriod = '';
  let _invoicesPage   = 1;

  async function _loadInvoicesContent() {
    const container = document.getElementById('invoices-content');
    if (!container) return;

    _invoicesPeriod = '';
    _invoicesPage   = 1;

    container.innerHTML = `
      <!-- Period tabs -->
      <div class="reports-tabs" id="invoices-period-tabs" style="margin-bottom:16px;">
        <button class="reports-tab active" data-period=""
          onclick="Dashboard.setInvoicesPeriod('')">All</button>
        <button class="reports-tab" data-period="day"
          onclick="Dashboard.setInvoicesPeriod('day')">Today</button>
        <button class="reports-tab" data-period="week"
          onclick="Dashboard.setInvoicesPeriod('week')">This Week</button>
        <button class="reports-tab" data-period="month"
          onclick="Dashboard.setInvoicesPeriod('month')">This Month</button>
      </div>

      <!-- Table -->
      <div id="invoices-table-wrap">
        <div class="loading-cell"><span class="spin"></span> Loading?</div>
      </div>

      <!-- Pagination -->
      <div id="invoices-pagination" style="display:none;align-items:center;
        justify-content:space-between;padding:12px 4px;margin-top:8px;">
        <button id="invoices-prev-btn" onclick="Dashboard._invoicesPageChange(-1)"
          style="padding:6px 14px;font-size:12px;font-weight:600;
            border:1px solid var(--border);border-radius:var(--radius-sm);
            background:var(--panel);color:var(--text-2);cursor:pointer;
            font-family:'DM Sans',sans-serif;">? Prev</button>
        <span id="invoices-page-info"
          style="font-size:12px;color:var(--text-3);font-family:'JetBrains Mono',monospace;">
        </span>
        <button id="invoices-next-btn" onclick="Dashboard._invoicesPageChange(1)"
          style="padding:6px 14px;font-size:12px;font-weight:600;
            border:1px solid var(--border);border-radius:var(--radius-sm);
            background:var(--panel);color:var(--text-2);cursor:pointer;
            font-family:'DM Sans',sans-serif;">Next ?</button>
      </div>`;

    await _fetchInvoices();
  }

  async function _fetchInvoices() {
    const wrap = document.getElementById('invoices-table-wrap');
    if (!wrap) return;
    wrap.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading?</div>';

    try {
      const periodParam = _invoicesPeriod ? `&period=${_invoicesPeriod}` : '';
      const res      = await Auth.fetch(
        `/api/v1/finance/invoices/?page=${_invoicesPage}&page_size=10${periodParam}`
      );
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const invoices = data.results || [];
      const count    = data.count   || 0;
      const totalPages = Math.ceil(count / 10);

      // Pagination controls
      const pagination = document.getElementById('invoices-pagination');
      const pageInfo   = document.getElementById('invoices-page-info');
      const prevBtn    = document.getElementById('invoices-prev-btn');
      const nextBtn    = document.getElementById('invoices-next-btn');

      if (pagination) pagination.style.display = totalPages > 1 ? 'flex' : 'none';
      if (pageInfo) {
        const from = count === 0 ? 0 : (_invoicesPage - 1) * 10 + 1;
        const to   = Math.min(_invoicesPage * 10, count);
        pageInfo.textContent = `${from}?${to} of ${count}`;
      }
      if (prevBtn) prevBtn.disabled = _invoicesPage <= 1;
      if (nextBtn) nextBtn.disabled = _invoicesPage >= totalPages;

      if (!invoices.length) {
        wrap.innerHTML = `<div style="text-align:center;padding:48px;
          color:var(--text-3);font-size:13px;">No invoices for this period.</div>`;
        return;
      }

      wrap.innerHTML = `
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
                    <div style="font-weight:600;font-size:13px;">${_esc(inv.bill_to_name || '?')}</div>
                    ${inv.bill_to_company ? `<div style="font-size:11px;color:var(--text-3);">${_esc(inv.bill_to_company)}</div>` : ''}
                  </td>
                  <td style="font-family:'JetBrains Mono',monospace;font-weight:600;">
                    ${_fmt(inv.total)}</td>
                  <td><span class="badge ${_invoiceStatusBadge(inv.status)}">${inv.status}</span></td>
                  <td style="font-size:12px;color:var(--text-3);">
                    ${inv.issue_date ? new Date(inv.issue_date).toLocaleDateString('en-GH') : '?'}</td>
                  <td>
                    <button onclick="Dashboard.downloadInvoicePDF(${inv.id}, '${_esc(inv.invoice_number)}')"
                      style="padding:5px 12px;font-size:12px;font-weight:600;
                        background:var(--bg);border:1px solid var(--border);
                        border-radius:var(--radius-sm);cursor:pointer;
                        font-family:'DM Sans',sans-serif;color:var(--text-2);">? PDF</button>
                  </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      wrap.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">
        Could not load invoices.</div>`;
    }
  }

  async function setInvoicesPeriod(period) {
    _invoicesPeriod = period;
    _invoicesPage   = 1;
    document.querySelectorAll('#invoices-period-tabs .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.period === period);
    });
    await _fetchInvoices();
  }

  async function _invoicesPageChange(delta) {
    _invoicesPage += delta;
    await _fetchInvoices();
  }

 // -- Receipts tab -------------------------------------------
  let _receiptsPeriod  = 'day';
  let _activeReceiptId = null;

 async function _loadReceiptsContent() {
    const container = document.getElementById('receipts-content');
    if (!container) return;

    _receiptsPeriod  = 'day';
    _receiptsPage    = 1;
    _activeReceiptId = null;

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

        <!-- Left ? receipt list -->
        <div style="width:300px;flex-shrink:0;border-right:1px solid var(--border);
          display:flex;flex-direction:column;background:var(--panel);">
          <div id="receipts-list-panel" style="flex:1;overflow-y:auto;">
            <div style="padding:20px;text-align:center;color:var(--text-3);">
              <span class="spin"></span>
            </div>
          </div>
          <!-- Pagination -->
          <div id="receipts-pagination" style="display:none;flex-shrink:0;
            padding:10px 12px;border-top:1px solid var(--border);
            background:var(--bg);display:flex;align-items:center;
            justify-content:space-between;gap:8px;">
            <button id="receipts-prev-btn" onclick="Dashboard._receiptsPageChange(-1)"
              style="padding:5px 12px;font-size:12px;font-weight:600;
                border:1px solid var(--border);border-radius:var(--radius-sm);
                background:var(--panel);color:var(--text-2);cursor:pointer;
                font-family:'DM Sans',sans-serif;">? Prev</button>
            <span id="receipts-page-info"
              style="font-size:11px;color:var(--text-3);font-family:'JetBrains Mono',monospace;">
            </span>
            <button id="receipts-next-btn" onclick="Dashboard._receiptsPageChange(1)"
              style="padding:5px 12px;font-size:12px;font-weight:600;
                border:1px solid var(--border);border-radius:var(--radius-sm);
                background:var(--panel);color:var(--text-2);cursor:pointer;
                font-family:'DM Sans',sans-serif;">Next ?</button>
          </div>
        </div>

        <!-- Right ? receipt detail -->
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
        `/api/v1/finance/receipts/?period=${_receiptsPeriod}&page=${_receiptsPage}&page_size=10`
      );
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const receipts = data.results || [];
      const count    = data.count || 0;
      const totalPages = Math.ceil(count / 10);

      // Update pagination controls
      const pagination  = document.getElementById('receipts-pagination');
      const pageInfo    = document.getElementById('receipts-page-info');
      const prevBtn     = document.getElementById('receipts-prev-btn');
      const nextBtn     = document.getElementById('receipts-next-btn');

      if (pagination) {
        pagination.style.display = totalPages > 1 ? 'flex' : 'none';
      }
      if (pageInfo) {
        const from = count === 0 ? 0 : (_receiptsPage - 1) * 10 + 1;
        const to   = Math.min(_receiptsPage * 10, count);
        pageInfo.textContent = `${from}?${to} of ${count}`;
      }
      if (prevBtn) prevBtn.disabled = _receiptsPage <= 1;
      if (nextBtn) nextBtn.disabled = _receiptsPage >= totalPages;

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
          : '?';
        const date    = r.created_at
          ? new Date(r.created_at).toLocaleDateString('en-GB', {
              day: 'numeric', month: 'short'
            })
          : '?';
        const isActive = r.id === _activeReceiptId;

        return `
          <div onclick="Dashboard.openReceipt(${r.id})"
            id="receipt-row-${r.id}"
            style="padding:14px 16px;border-bottom:1px solid var(--border);
              cursor:pointer;background:${isActive ? 'var(--bg)' : 'var(--panel)'};
              transition:background 0.12s;border-left:3px solid ${isActive ? 'var(--text)' : 'transparent'};"
            onmouseover="this.style.background='var(--bg)'"
            onmouseout="this.style.background='${isActive ? 'var(--bg)' : 'var(--panel)'}'">
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
            <div style="font-size:12px;color:var(--text-2);font-weight:500;
              margin-bottom:5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">
              ${_esc(r.customer_name || 'Walk-in')}
            </div>
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <span style="font-size:10px;font-weight:700;padding:2px 7px;
                border-radius:4px;border:1px solid ${mc.border};
                background:${mc.bg};color:${mc.text};">
                ${r.payment_method || '?'}
              </span>
              <span style="font-size:11px;color:var(--text-3);
                font-family:'JetBrains Mono',monospace;">
                ${date} ? ${time}
              </span>
            </div>
          </div>`;
      }).join('');

      // Auto-open first receipt on page 1 if none active
      if (receipts.length && !_activeReceiptId && _receiptsPage === 1) {
        openReceipt(receipts[0].id);
      }

    } catch {
      listPanel.innerHTML = `<div style="padding:24px;text-align:center;
        color:var(--red-text);font-size:13px;">Could not load receipts.</div>`;
    }
  }

  let _receiptsPage = 1;

  async function _receiptsPageChange(delta) {
    _receiptsPage    += delta;
    _activeReceiptId  = null;
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
    await _fetchReceipts();
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
            ${_esc(li.service_name || li.service || '?')}
          </div>
          ${li.pages && li.sets ? `
            <div style="font-size:11px;color:var(--text-3);margin-top:1px;">
              ${li.pages} pg ? ${li.sets} set${li.sets !== 1 ? 's' : ''}
              ${li.is_color ? ' ? Colour' : ' ? B&W'}
            </div>` : ''}
        </div>
        <div style="font-size:12px;color:var(--text-3);text-align:right;">
          ${li.unit_price != null ? _fmt(li.unit_price) : '?'}
        </div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:13px;
          font-weight:600;color:var(--text);text-align:right;min-width:80px;">
          ${li.line_total != null ? _fmt(li.line_total) : '?'}
        </div>
      </div>`).join('');

    const issuedAt = r.created_at
      ? new Date(r.created_at).toLocaleString('en-GH', {
          day: 'numeric', month: 'short', year: 'numeric',
          hour: '2-digit', minute: '2-digit'
        })
      : '?';

    container.innerHTML = `
      <div style="flex:1;overflow-y:auto;padding:24px;min-height:0;" id="receipt-printable">

        <!-- ? Header -->
        <div style="display:flex;align-items:flex-start;
          justify-content:space-between;margin-bottom:20px;
          padding-bottom:16px;border-bottom:1px solid var(--border);">
          <div>
            <div style="font-family:'Syne',sans-serif;font-size:18px;
              font-weight:800;color:var(--text);letter-spacing:-0.3px;">
              ${_esc(r.receipt_number || '?')}
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

        <!-- ? Job summary -->
        <div style="margin-bottom:20px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">
            Job
          </div>
          <div style="font-size:14px;font-weight:700;color:var(--text);
            margin-bottom:3px;">
            ${_esc(r.job_title || r.job?.title || '?')}
          </div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:11px;
            color:var(--text-3);">
            ${_esc(r.job_number || r.job?.job_number || '?')}
          </div>
        </div>

        <!-- ? Line items -->
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

        <!-- ? Payment settlement -->
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

        <!-- ? Payment method -->
        <div style="margin-bottom:20px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.8px;margin-bottom:8px;">
            Payment Method
          </div>
          <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
            <span style="padding:5px 14px;border-radius:20px;font-size:12px;
              font-weight:700;background:${mc.bg};color:${mc.text};
              border:1px solid ${mc.border};">
              ${r.payment_method || '?'}
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

        <!-- ? People -->
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
            ['Cashier',   r.cashier_name  || r.cashier?.full_name || '?'],
            ['Attendant', r.intake_by_name || '?'],
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

      <!-- ? Actions -->
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
    _receiptsPage    = 1;
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

// -- Performance pane ---------------------------------------
  let _performanceTab = 'metrics';

  async function _loadFinancePane() {
    const pane = document.getElementById('pane-finance');
    if (!pane) return;
    pane.dataset.loaded = '1';
    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Day Sheet</span>
      </div>
      <div id="daysheet-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;
    await _renderTodaySheet(document.getElementById('daysheet-content'));
  }

  async function _loadDaySheetTab(tab) {
    const content = document.getElementById('daysheet-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading?</div>';
    if (tab === 'today')   await _renderTodaySheet(content);
    if (tab === 'archive') await _renderSheetsArchive(content);
  }

  async function _renderTodaySheet(container) {
    try {
      const todayRes = await Auth.fetch('/api/v1/finance/sheets/today/summary/');
      if (!todayRes.ok) throw new Error();
      const summary  = await todayRes.json();
      const sheet    = { id: summary.meta.sheet_id, date: summary.meta.date, status: summary.meta.status, sheet_number: summary.meta.sheet_number, opened_at: summary.meta.opened_at, notes: summary.meta.notes, total_jobs_created: summary.jobs.total, total_refunds: 0, total_petty_cash_out: summary.revenue.petty_cash_out, total_credit_issued: summary.revenue.credit_issued, total_credit_settled: summary.revenue.credit_settled };
      const rev      = summary.revenue;
      const liveCash  = parseFloat(rev.cash  || 0);
      const liveMomo  = parseFloat(rev.momo  || 0);
      const livePos   = parseFloat(rev.pos   || 0);
      const liveTotal = liveCash + liveMomo + livePos;

      container.innerHTML = `
        <!-- Status strip -->
        <div style="display:flex;align-items:center;justify-content:space-between;
          margin-bottom:16px;">
          <div style="display:flex;align-items:center;gap:8px;">
            <span style="font-family:'JetBrains Mono',monospace;font-size:12px;
              font-weight:700;color:var(--text-3);">
              ${sheet.sheet_number || ''}
            </span>
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
        <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:16px;">
          <div class="stat-card" style="background:var(--panel);border:2px solid var(--text);">
            <div class="stat-num">${_fmt(liveTotal)}</div>
            <div class="stat-lbl" style="font-weight:700;">Total Today</div>
          </div>
          <div class="stat-card green">
            <div class="stat-num">${_fmt(liveCash)}</div>
            <div class="stat-lbl">Cash</div>
          </div>
          <div class="stat-card amber">
            <div class="stat-num">${_fmt(liveMomo)}</div>
            <div class="stat-lbl">MoMo</div>
          </div>
          <div class="stat-card blue">
            <div class="stat-num">${_fmt(livePos)}</div>
            <div class="stat-lbl">POS</div>
          </div>
          <div class="stat-card purple">
            <div class="stat-num">${_fmt(parseFloat(rev.net_cash_in_till || 0))}</div>
            <div class="stat-lbl">Net Cash In Till</div>
          </div>
        </div>

        <!-- Registration rate strip -->
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:14px 20px;margin-bottom:10px;
          display:grid;grid-template-columns:1fr 1fr 1fr;gap:0;">
          <div style="padding-right:20px;border-right:1px solid var(--border);">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
              Registered Jobs</div>
            <div style="font-size:18px;font-weight:700;color:var(--text);"
              id="sheet-registered-jobs">?</div>
            <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
              linked to a customer</div>
          </div>
          <div style="padding:0 20px;border-right:1px solid var(--border);">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
              Walk-in Jobs</div>
            <div style="font-size:18px;font-weight:700;color:var(--green-text);"
              id="sheet-walkin-jobs">?</div>
            <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
              no customer linked</div>
          </div>
          <div style="padding-left:20px;">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
              Registration Rate</div>
            <div style="font-size:18px;font-weight:700;"
              id="sheet-reg-rate">?</div>
            <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
              of jobs have a customer</div>
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

    // -- Populate computed fields ------------------------------
    // Total revenue
    const totalRevenue = liveTotal;

    // Job stats from stats endpoint
    try {
      const statsRes = await Auth.fetch(`/api/v1/jobs/stats/?daily_sheet=${sheet.id}`);
      if (statsRes.ok) {
        const stats = await statsRes.json();
        const total     = stats.total || 0;
        const registered = stats.registered || 0;
        const walkin     = stats.walkin     || total - registered;
        const rate       = total > 0 ? Math.round(registered / total * 100) : 0;
        const rateColor  = rate >= 60 ? 'var(--green-text)'
          : rate >= 30 ? 'var(--amber-text)' : 'var(--red-text)';

        _set('sheet-registered-jobs', registered);
        _set('sheet-walkin-jobs',     walkin);

        const rateEl = document.getElementById('sheet-reg-rate');
        if (rateEl) {
          rateEl.textContent = `${rate}%`;
          rateEl.style.color = rateColor;
        }

        // Outstanding jobs alert
        const outstanding = (stats.pending || 0) + (stats.in_progress || 0);
        if (outstanding > 0 && sheet.status === 'OPEN') {
          const existingAlert = document.getElementById('sheet-outstanding-alert');
          if (!existingAlert) {
            const alertDiv = document.createElement('div');
            alertDiv.id = 'sheet-outstanding-alert';
            alertDiv.style.cssText = `margin-top:10px;padding:10px 16px;
              background:var(--amber-bg);border:1px solid var(--amber-border);
              border-radius:var(--radius-sm);font-size:13px;
              color:var(--amber-text);font-weight:600;
              display:flex;align-items:center;gap:8px;`;
            alertDiv.innerHTML = `
              <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
                viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
              </svg>
              ${outstanding} job${outstanding !== 1 ? 's' : ''} still outstanding
              (${stats.pending || 0} pending payment ? ${stats.in_progress || 0} in progress)`;
            container.appendChild(alertDiv);
          }
        }

        // ── Analytics strip — uses summary.pace (already fetched) ──
        if (sheet.status === 'OPEN' && summary.pace?.jobs_per_hour != null) {
          const p             = summary.pace;
          const paceColor     = p.pace_change_pct == null ? 'var(--text-3)'
            : p.pace_change_pct >= 0 ? 'var(--green-text)' : 'var(--red-text)';
          const paceArrow     = p.pace_change_pct == null ? ''
            : p.pace_change_pct >= 0 ? '↑' : '↓';
          const paceVsYday    = p.pace_change_pct == null ? ''
            : `<span style="font-size:11px;font-weight:700;color:${paceColor};margin-left:6px;">
                ${paceArrow} ${Math.abs(p.pace_change_pct)}% vs yesterday
               </span>`;
          const avgToday      = p.avg_job_value_today != null
            ? `GHS ${parseFloat(p.avg_job_value_today).toFixed(2)}` : '—';
          const avg7d         = p.avg_job_value_7d != null
            ? `GHS ${parseFloat(p.avg_job_value_7d).toFixed(2)}` : '—';
          const avgColor      = (p.avg_job_value_today != null && p.avg_job_value_7d != null)
            ? (p.avg_job_value_today >= p.avg_job_value_7d ? 'var(--green-text)' : 'var(--red-text)')
            : 'var(--text)';

          const strip = document.createElement('div');
          strip.id    = 'sheet-pace-strip';
          strip.style.cssText = `margin-top:10px;padding:12px 16px;
            background:var(--panel);border:1px solid var(--border);
            border-radius:var(--radius-sm);
            display:grid;grid-template-columns:1fr 1fr 1fr;gap:0;`;
          strip.innerHTML = `
            <div style="padding-right:16px;border-right:1px solid var(--border);">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                Branch Pace
              </div>
              <div style="display:flex;align-items:baseline;gap:4px;">
                <span style="font-family:'JetBrains Mono',monospace;font-weight:800;
                  color:var(--text);font-size:18px;">${p.jobs_per_hour}</span>
                <span style="font-size:11px;color:var(--text-3);">jobs/hr</span>
                ${paceVsYday}
              </div>
              ${p.projected_eod != null ? `
              <div style="font-size:11px;color:var(--text-3);margin-top:3px;">
                Projected EOD: <strong style="color:var(--text);">${p.projected_eod} jobs</strong>
              </div>` : ''}
            </div>
            <div style="padding:0 16px;border-right:1px solid var(--border);">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                Avg Job Value Today
              </div>
              <div style="font-family:'JetBrains Mono',monospace;font-weight:800;
                font-size:18px;color:${avgColor};">${avgToday}</div>
              <div style="font-size:11px;color:var(--text-3);margin-top:3px;">
                7-day avg: <strong style="color:var(--text);">${avg7d}</strong>
              </div>
            </div>
            <div style="padding-left:16px;">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">
                Hours Open
              </div>
              <div style="font-family:'JetBrains Mono',monospace;font-weight:800;
                font-size:18px;color:var(--text);">${p.hours_open}h</div>
              <div style="font-size:11px;color:var(--text-3);margin-top:3px;">
                ${p.yesterday_per_hour != null
                  ? `Yesterday: <strong style="color:var(--text);">${p.yesterday_per_hour} jobs/hr</strong>`
                  : 'No comparison data'}
              </div>
            </div>`;
          container.appendChild(strip);
        }
      }
    } catch { /* silent */ }

    // ── Consumables snapshot — uses summary.inventory (already fetched) ──
    if (sheet.status === 'OPEN') {
      const invItems = (summary.inventory || []).filter(i => i.category !== 'Machinery');
      if (invItems.length) {
        const lowItems  = invItems.filter(i => i.is_low);
        const invDiv    = document.createElement('div');
        invDiv.style.cssText = 'margin-top:16px;';
        invDiv.innerHTML = `
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;
            display:flex;align-items:center;gap:8px;">
            Current Stock Levels
            ${lowItems.length ? `<span style="padding:2px 8px;border-radius:20px;
              background:var(--red-bg);color:var(--red-text);font-size:9px;font-weight:700;">
              ${lowItems.length} low</span>` : ''}
          </div>
          <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">
            ${invItems.map(item => {
              const qty      = parseFloat(item.closing);
              const consumed = parseFloat(item.consumed || 0);
              const rpt      = parseFloat(item.reorder_point || 0);
              const isCrit   = qty === 0;
              const isLow    = item.is_low;
              const isPct    = (item.unit || '').includes('%');
              const unit     = item.unit || 'units';
              const fmtQty   = n => isPct
                ? `${parseFloat(n).toFixed(1)}%`
                : parseFloat(n).toLocaleString('en-GH', { maximumFractionDigits: 1 });
              const statusColor = isCrit ? '#dc2626' : isLow ? '#d97706' : '#16a34a';
              const total    = qty + consumed;
              const fillPct  = isPct ? Math.min(100, qty) : (total > 0 ? Math.min(100, (qty / total) * 100) : 0);

              // Tooltip — human readable consumption
              const consumedLabel = consumed > 0
                ? `${fmtQty(consumed)} ${unit} consumed today`
                : 'No consumption recorded today';
              const tooltip = `${item.consumable} · ${consumedLabel} · Closing: ${fmtQty(qty)} ${unit}`;

              return `
                <div title="${_esc(tooltip)}"
                  style="position:relative;overflow:hidden;padding:9px 12px;
                    background:var(--panel);
                    border:1px solid ${isCrit ? '#fca5a5' : isLow ? '#fcd34d' : 'var(--border)'};
                    border-radius:var(--radius-sm);
                    display:flex;align-items:center;justify-content:space-between;gap:8px;
                    cursor:default;">
                  <div style="position:absolute;top:0;right:0;width:4px;height:100%;
                    background:#e5e7eb;border-radius:0 var(--radius-sm) var(--radius-sm) 0;">
                    <div style="position:absolute;bottom:0;left:0;width:100%;
                      height:${fillPct.toFixed(1)}%;background:${statusColor};
                      border-radius:0 0 var(--radius-sm) var(--radius-sm);
                      transition:height 0.3s ease;"></div>
                  </div>
                  <span style="font-size:11px;font-weight:600;
                    color:${isCrit ? '#dc2626' : isLow ? '#d97706' : 'var(--text)'};
                    overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
                    flex:1;min-width:0;"
                    >${_esc(item.consumable)}</span>
                  <div style="display:flex;align-items:center;gap:5px;flex-shrink:0;padding-right:8px;">
                    ${consumed > 0 ? `
                      <span style="font-family:'JetBrains Mono',monospace;font-size:10px;
                        font-weight:600;color:#dc2626;">-${fmtQty(consumed)}</span>
                      <span style="color:var(--border);font-size:10px;">·</span>` : ''}
                    <span style="font-family:'JetBrains Mono',monospace;font-size:12px;
                      font-weight:700;color:${isCrit ? '#dc2626' : isLow ? '#d97706' : 'var(--text)'};">
                      ${fmtQty(qty)}
                    </span>
                  </div>
                </div>`;
            }).join('')}
          </div>`;
        container.appendChild(invDiv);
      }
    }
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
                        <div class="loading-cell"><span class="spin"></span> Loading?</div>
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
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading?</div>';

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
                  : '?';
                return `
                  <tr style="border-bottom:1px solid var(--border);">
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-3);">${time}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:11px;">${_esc(j.job_number || '#' + j.id)}</td>
                    <td style="padding:8px 12px;">${_statusBadge(j.status)}</td>
                    <td style="padding:8px 12px;font-size:12px;">
                      ${j.payment_method
                        ? `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;padding:2px 7px;border-radius:4px;background:var(--border);color:var(--text-2);font-weight:700;">${j.payment_method}</span>`
                        : '<span style="color:var(--text-3);">?</span>'}
                    </td>
                    <td style="padding:8px 12px;font-size:12px;color:var(--text-2);">${_esc(j.intake_by_name || '?')}</td>
                    <td style="padding:8px 12px;font-size:12px;color:var(--text-2);">${_esc(j.confirmed_by_name || '?')}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:12px;">${j.estimated_cost != null ? _fmt(j.estimated_cost) : '?'}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:12px;">${j.cash_tendered != null ? _fmt(j.cash_tendered) : '?'}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:12px;">${j.change_given != null ? _fmt(j.change_given) : '?'}</td>
                    <td style="padding:8px 12px;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;">${j.amount_paid != null ? _fmt(j.amount_paid) : '?'}</td>
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
                ${sheet ? _fmt(sheet.total_cash) : '?'}
              </div>
            </div>
            <div>
              <span style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;">MoMo</span>
              <div style="font-size:14px;font-weight:700;color:var(--text);
                font-family:'JetBrains Mono',monospace;">
                ${sheet ? _fmt(sheet.total_momo) : '?'}
              </div>
            </div>
            <div>
              <span style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;">POS</span>
              <div style="font-size:14px;font-weight:700;color:var(--text);
                font-family:'JetBrains Mono',monospace;">
                ${sheet ? _fmt(sheet.total_pos) : '?'}
              </div>
            </div>
            <div style="padding-left:16px;border-left:1px solid var(--border);">
              <span style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;letter-spacing:0.5px;">Total</span>
              <div style="font-size:16px;font-weight:800;color:var(--text);
                font-family:'Outfit',sans-serif;">
                ${sheet
                  ? _fmt(parseFloat(sheet.total_cash||0) + parseFloat(sheet.total_momo||0) + parseFloat(sheet.total_pos||0))
                  : '?'}
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

// -- EOD / Close Sheet -----------------------------------------
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
    if (!inputs.length) return true; // no cashiers ? no float needed
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

    // -- Header ----------------------------------------------------
    const dateStr = new Date(meta.date).toLocaleDateString('en-GH', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric'
    });
    document.getElementById('eod-subtitle').textContent = `${meta.sheet_number || ''} ? ${dateStr} ? ${meta.branch}`;
    document.getElementById('eod-ack-branch').textContent = meta.branch;

    // Set BM name in acknowledgement
    const user = Auth.getUser();
    const bmName = user?.full_name || user?.first_name || 'Branch Manager';
    const bmEl = document.getElementById('eod-ack-bm-name');
    if (bmEl) bmEl.textContent = bmName;

    // -- 1. Revenue ------------------------------------------------
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

    // -- 2. Jobs Grid ----------------------------------------------
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

    // -- 3. Cashier Sign-Off ---------------------------------------
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
               border:1px solid var(--green-border);">? Signed off</span>`
          : `<span style="display:inline-flex;align-items:center;gap:4px;padding:3px 10px;
               border-radius:20px;font-size:11px;font-weight:700;
               background:var(--red-bg);color:var(--red-text);
               border:1px solid var(--red-border);">? Not signed off</span>`;

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
        ? `<span style="font-size:11px;font-weight:700;color:var(--green-text);">? All signed off</span>`
        : `<span style="font-size:11px;font-weight:700;color:var(--red-text);">? Sign-off pending</span>`;
    }

    // -- 4. Pending Payments ---------------------------------------
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
        : '<div class="eod-empty-note">No pending payments. ?</div>';

    const untouchedSubtitle = document.getElementById('eod-untouched-subtitle');
    const untouchedNote     = document.getElementById('eod-untouched-note');
    untouchedSubtitle.style.display = jobs.untouched_list?.length ? 'block' : 'none';
    untouchedNote.style.display     = jobs.untouched_list?.length ? 'block' : 'none';
    document.getElementById('eod-untouched-list').innerHTML =
      jobs.untouched_list?.length ? _jobMiniTable(jobs.untouched_list) : '';

    // -- 5. Petty Cash ---------------------------------------------
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
                <td>${_esc(p.reason || p.purpose || '?')}</td>
                <td>${_esc(p.recorded_by_name || '?')}</td>
                <td style="font-size:11px;color:var(--text-3);">
                  ${p.created_at ? new Date(p.created_at).toLocaleTimeString('en-GH',{hour:'2-digit',minute:'2-digit'}) : '?'}
                </td>
                <td class="mono">${fmt(p.amount)}</td>
              </tr>`).join('')}
          </tbody>
        </table>`;
    } else {
      pettyList.innerHTML = '<div class="eod-empty-note">No petty cash disbursements today. ?</div>';
    }

    // -- 6. Credit Sales -------------------------------------------
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
      creditList.innerHTML = '<div class="eod-empty-note">No credit sales today. ?</div>';
    }

    // -- 7. Inventory Consumption ------------------------------
    const invSection = document.getElementById('eod-inventory-section');
    const invList    = document.getElementById('eod-inventory-list');
    if (invSection && invList) {
      const items = d.inventory_consumption || [];
      if (items.length) {
        invSection.style.display = 'block';
        invList.innerHTML = `
          <table class="eod-table">
            <thead>
              <tr>
                <th>Consumable</th>
                <th style="text-align:right;">Consumed</th>
                <th style="text-align:right;">Closing</th>
                <th style="text-align:center;">Status</th>
              </tr>
            </thead>
            <tbody>
              ${items.map(item => {
                const isToner  = item.unit === '%';
                const closing  = parseFloat(item.closing);
                const isLow    = item.is_low;
                const pctColor = isToner
                  ? (closing >= 30 ? 'var(--green-text)' : closing >= 15 ? 'var(--amber-text)' : 'var(--red-text)')
                  : (isLow ? 'var(--red-text)' : 'var(--text-2)');
                const badge = isLow
                  ? `<span style="background:#fee2e2;color:var(--red-text);padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;">LOW</span>`
                  : `<span style="background:#dcfce7;color:var(--green-text);padding:2px 6px;border-radius:4px;font-size:10px;font-weight:700;">OK</span>`;
                return `
                  <tr>
                    <td>${_esc(item.consumable)}</td>
                    <td class="mono" style="text-align:right;">${item.consumed} ${item.unit}</td>
                    <td class="mono" style="text-align:right;color:${pctColor};font-weight:600;">${item.closing} ${item.unit}</td>
                    <td style="text-align:center;">${badge}</td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>`;
      } else {
        invSection.style.display = 'block';
        invList.innerHTML = '<div class="eod-empty-note">No inventory movements recorded today.</div>';
      }
    }

    // -- 8. Tomorrow's Float ---------------------------------------
    const floatContainer = document.getElementById('eod-cashier-floats');
    if (floatContainer) {
      // Use cashier_activity if available, else branch_cashiers
      const cashiers = (d.cashier_activity?.length)
        ? d.cashier_activity
        : (d.branch_cashiers || []);

      if (cashiers.length) {
        // Check if tomorrow is Sunday ? skip to Monday
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
            ${isSunday ? '(Monday ? skipping Sunday)' : ''}
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

    // -- Hide loading, show content --------------------------------
    document.getElementById('eod-loading').style.display = 'none';
    document.getElementById('eod-content').style.display = 'block';

    // -- Show footer -----------------------------------------------
    document.getElementById('eod-footer').style.display = 'flex';

    // -- Update integrity status in footer -------------------------
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
        ? `? Blocked: ${issues.join(' ? ')}`
        : '? Ready to close';
      footerStatus.style.color = issues.length ? 'var(--red-text)' : 'var(--green-text)';
    }
  }

  function _checkItem(type, text, sub) {
    const icons = { ok: '?', warn: '?', alert: '?' };
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
              <td>${j.title || '?'}</td>
              <td>${j.intake_by_name}</td>
              <td>${j.created_at ? new Date(j.created_at).toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' }) : '?'}</td>
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
    btn.innerHTML = '<span style="opacity:0.6">Closing?</span>';

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

  // -- Inbox pane ---------------------------------------------
// -- Inbox pane ---------------------------------------------
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
            <div style="font-size:11px;color:var(--text-3);margin-top:1px;">${_esc(convo.channel || '')} ? ${convo.contact_value || ''}</div>
          </div>
        </div>
        <div id="inbox-messages" style="flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:10px;">
          ${msgs.length ? msgs.map(m => _renderMessage(m)).join('') : '<div style="text-align:center;color:var(--text-3);font-size:13px;padding:32px 0;">No messages yet.</div>'}
        </div>
        <div style="padding:12px 14px;border-top:1px solid var(--border);display:flex;gap:8px;">
          <input id="inbox-reply-input" type="text" placeholder="Type a reply?"
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
  // -- Services pane ------------------------------------------
  async function _loadServicesAndCustomers() {
    try {
      const [svcRes, custRes] = await Promise.all([
        Auth.fetch('/api/v1/jobs/services/'),
        Auth.fetch('/api/v1/customers/?page_size=200'),
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
        // If paginated, fetch remaining pages
        if (data.count && data.next) {
          let next = data.next;
          while (next) {
            const pageRes = await Auth.fetch(next);
            if (!pageRes.ok) break;
            const pageData = await pageRes.json();
            customers = customers.concat(pageData.results || []);
            next = pageData.next;
          }
        }
        if (typeof State !== 'undefined') State.customers = customers;
      }

    } catch { /* silent */ }
  }

 
  // -- Outsource modal ----------------------------------------
  async function openOutsourceModal() {
    document.getElementById('outsource-modal').classList.add('open');

    // Load pending jobs into select
    try {
      const res  = await Auth.fetch('/api/v1/jobs/?status=PENDING_PAYMENT&page_size=50');
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);
      const sel  = document.getElementById('outsource-job-select');
      if (sel) {
        sel.innerHTML = '<option value="">Select job?</option>' +
          jobs.map(j => `<option value="${j.id}">${_esc(j.job_number)} ? ${_esc(j.title)}</option>`).join('');
      }
    } catch { /* silent */ }

    // Load branches into select
    try {
      const res     = await Auth.fetch('/api/v1/organization/branches/');
      const data    = await res.json();
      const branches = Array.isArray(data) ? data : (data.results || []);
      const sel     = document.getElementById('outsource-branch-select');
      if (sel) {
        sel.innerHTML = '<option value="">Select branch?</option>' +
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

  // -- NJ controller integration ------------------------------
  // Called by NJ after job creation to refresh dashboard
  function onJobCreated() {
    jobsLoaded = false;
    Promise.all([loadStats(), loadRecentJobs()]);
  }

  // -- Helpers ------------------------------------------------
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
    return str.length > len ? str.slice(0, len) + '?' : str;
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
    if (!iso) return '?';
    return new Date(iso).toLocaleDateString('en-GB', {
      day: 'numeric', month: 'short', year: 'numeric',
    });
  }

  function _timeAgo(iso) {
    if (!iso) return '?';
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
    return `<span class="badge ${map[status] || 'badge-draft'}">${labels[status] || status || '?'}</span>`;
  }

  function _typeBadge(type) {
    const map = {
      INSTANT    : 'badge-instant',
      PRODUCTION : 'badge-production',
      DESIGN     : 'badge-design',
    };
    return `<span class="badge ${map[type] || 'badge-draft'}">${_esc(type || '?')}</span>`;
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

// -- Reports pane ---------------------------------------------
// ── Sheet PDF download ─────────────────────────────────────
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

    const user     = Auth.getUser();
    const hasPinSet = user?.download_pin_set;

    _set('pin-modal-subtitle', `Sheet · ${sheetDate}`);

    if (!hasPinSet) {
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
    const btn        = document.getElementById('pin-submit-btn');
    const isSetState = document.getElementById('pin-set-state').style.display !== 'none';
    btn.disabled     = true;
    btn.textContent  = 'Checking…';
    if (isSetState) { await _handleSetPin(btn); } else { await _handleVerifyPin(btn); }
  }

  async function _handleSetPin(btn) {
    const pin        = document.getElementById('pin-set-input')?.value.trim();
    const confirmPin = document.getElementById('pin-confirm-input')?.value.trim();
    const errorEl    = document.getElementById('pin-set-error');
    errorEl.style.display = 'none';

    if (!pin || pin.length !== 4 || !/^\d{4}$/.test(pin)) {
      errorEl.textContent   = 'PIN must be exactly 4 digits.';
      errorEl.style.display = 'block';
      btn.disabled = false; btn.textContent = 'Confirm';
      return;
    }
    if (pin !== confirmPin) {
      errorEl.textContent   = 'PINs do not match.';
      errorEl.style.display = 'block';
      btn.disabled = false; btn.textContent = 'Confirm';
      return;
    }
    try {
      const res = await Auth.fetch('/api/v1/accounts/pin/set/', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin, confirm_pin: confirmPin }),
      });
      if (res.ok) {
        const userRes = await Auth.fetch('/api/v1/accounts/me/');
        if (userRes?.ok) Auth.setUser(await userRes.json());
        _toast('Download PIN set successfully.', 'success');
        closePinModal();
        setTimeout(() => initiateSheetDownload(_pinSheetId, _pinSheetDate), 300);
      } else {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent   = err.detail || 'Could not set PIN.';
        errorEl.style.display = 'block';
        btn.disabled = false; btn.textContent = 'Confirm';
      }
    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
      btn.disabled = false; btn.textContent = 'Confirm';
    }
  }

  async function _handleVerifyPin(btn) {
    const pin        = document.getElementById('pin-verify-input')?.value.trim();
    const errorEl    = document.getElementById('pin-verify-error');
    const attemptsEl = document.getElementById('pin-attempts');
    errorEl.style.display = 'none';

    if (!pin || pin.length !== 4) {
      errorEl.textContent   = 'Please enter your 4-digit PIN.';
      errorEl.style.display = 'block';
      btn.disabled = false; btn.textContent = 'Confirm';
      return;
    }
    try {
      const res = await Auth.fetch('/api/v1/accounts/pin/verify/', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pin, sheet_id: _pinSheetId }),
      });
      if (res.ok) {
        closePinModal();
        _toast('PIN verified. Downloading…', 'success');
        await downloadSheetPDF(_pinSheetId, _pinSheetDate);
      } else {
        _pinAttempts++;
        const remaining = MAX_ATTEMPTS - _pinAttempts;
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
          if (attemptsEl) attemptsEl.textContent = '';
          btn.disabled = true; btn.textContent = 'Locked';
        } else {
          errorEl.textContent   = 'Incorrect PIN.';
          errorEl.style.display = 'block';
          if (attemptsEl) attemptsEl.textContent = `${remaining} attempt${remaining !== 1 ? 's' : ''} remaining`;
          btn.disabled = false; btn.textContent = 'Confirm';
        }
      }
    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
      btn.disabled = false; btn.textContent = 'Confirm';
    }
  }

  function closePinModal() {
    document.getElementById('pin-modal').classList.remove('open');
    ['pin-verify-input','pin-set-input','pin-confirm-input'].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.value = '';
    });
    for (let i = 0; i < 4; i++) {
      const d  = document.getElementById(`pin-dot-${i}`);
      const ds = document.getElementById(`pin-set-dot-${i}`);
      if (d)  d.style.background  = 'var(--border)';
      if (ds) ds.style.background = 'var(--border)';
    }
    _pinAttempts = 0;
  }

  // ── Invoice status badge ───────────────────────────────────
  function _invoiceStatusBadge(status) {
    return { 'DRAFT':'badge-draft','SENT':'badge-progress','VIEWED':'badge-pending','PAID':'badge-done' }[status] || 'badge-draft';
  }

  async function downloadInvoicePDF(id, invoiceNumber) {
    try {
      const res = await Auth.fetch(`/api/v1/finance/invoices/${id}/pdf/`);
      if (!res.ok) { _toast('Could not download PDF.', 'error'); return; }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = `${invoiceNumber}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch { _toast('Download failed.', 'error'); }
  }

  function openCreateInvoice() {
    _toast('Invoice creation coming soon.', 'info');
  }

  // ── Late Job ───────────────────────────────────────────────
  function openLateJobModal() {
    document.getElementById('late-job-reason').value     = '';
    document.getElementById('late-job-svc-search').value = '';
    document.getElementById('late-job-svc-id').value     = '';
    document.getElementById('late-job-pages').value      = '1';
    document.getElementById('late-job-sets').value       = '1';
    document.getElementById('late-job-color').value      = 'false';
    document.getElementById('late-job-error').style.display    = 'none';
    document.getElementById('late-job-svc-dropdown').style.display = 'none';
    document.getElementById('late-job-overlay').classList.add('open');
  }

  function closeLateJobModal() {
    document.getElementById('late-job-overlay').classList.remove('open');
  }

  function _lateJobFilterServices() {
    const query    = document.getElementById('late-job-svc-search').value.toLowerCase();
    const dropdown = document.getElementById('late-job-svc-dropdown');
    const filtered = services.filter(s => s.name.toLowerCase().includes(query));
    if (!filtered.length) { dropdown.style.display = 'none'; return; }
    dropdown.innerHTML = filtered.map(s => `
      <div onclick="Dashboard._lateJobSelectService(${s.id}, '${_esc(s.name)}')"
        style="padding:9px 12px;font-size:13px;cursor:pointer;border-bottom:1px solid var(--border);"
        onmouseover="this.style.background='var(--bg)'" onmouseout="this.style.background=''">
        <div style="font-weight:600;color:var(--text);">${_esc(s.name)}</div>
        <div style="font-size:11px;color:var(--text-3);">${s.category}</div>
      </div>`).join('');
    dropdown.style.display = 'block';
  }

  function _lateJobSelectService(id, name) {
    document.getElementById('late-job-svc-id').value    = id;
    document.getElementById('late-job-svc-search').value = name;
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

    btn.disabled = true; btn.textContent = 'Recording…';
    try {
      const res = await Auth.fetch('/api/v1/jobs/late/', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          post_closing_reason: reason,
          line_items: [{ service: parseInt(svcId), pages, sets, is_color: isColor }],
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
      btn.disabled = false; btn.textContent = 'Record Late Job';
    }
  }

  function _checkLateJobButton() {
    const btn = document.getElementById('late-job-btn');
    if (!btn) return;
    const now  = new Date();
    const isPastClosing = now.getHours() > 19 || (now.getHours() === 19 && now.getMinutes() >= 30);
    btn.style.display = isPastClosing ? 'inline-flex' : 'none';
  }

  // ── Closing warning ────────────────────────────────────────
  let _closingWarnShown = false;

  function _checkClosingWarning() {
    const now   = new Date();
    const hours = now.getHours();
    const mins  = now.getMinutes();
    const isWarningTime = hours === 19 && mins >= 0 && mins < 30;
    if (!isWarningTime || _closingWarnShown) return;
    const openModals = document.querySelectorAll('.modal-overlay.open, .eod-overlay.open');
    if (openModals.length > 0) return;
    _closingWarnShown = true;
    _showClosingModal();
  }

  function _showClosingModal() {
    const existing = document.getElementById('closing-warn-overlay');
    if (existing) existing.remove();
    const overlay = document.createElement('div');
    overlay.id    = 'closing-warn-overlay';
    overlay.style.cssText = `position:fixed;inset:0;z-index:9998;background:rgba(0,0,0,0.85);display:flex;align-items:center;justify-content:center;font-family:'DM Sans',sans-serif;animation:fadeIn 0.3s ease;`;
    overlay.innerHTML = `
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);width:100%;max-width:480px;padding:32px;text-align:center;box-shadow:0 24px 64px rgba(0,0,0,0.4);">
        <div style="width:64px;height:64px;border-radius:50%;background:var(--amber-bg);border:2px solid var(--amber-border);display:flex;align-items:center;justify-content:center;margin:0 auto 20px;">
          <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="var(--amber-text)" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        </div>
        <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;color:var(--text);margin-bottom:8px;">30 Minutes to Closing</div>
        <div style="font-size:14px;color:var(--text-3);margin-bottom:8px;">Branch closes at <strong style="color:var(--text);">7:30 PM</strong> today.</div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:28px;">Ensure all jobs are processed and the cashier is prepared for end-of-day sign-off.</div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">Auto-dismissing in <span id="closing-warn-countdown" style="font-weight:700;color:var(--amber-text);">15</span>s</div>
        <button onclick="document.getElementById('closing-warn-overlay').remove()" style="padding:10px 28px;background:var(--text);color:#fff;border:none;border-radius:var(--radius-sm);font-size:14px;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;">Dismiss</button>
      </div>`;
    document.body.appendChild(overlay);
    let count = 15;
    const timer = setInterval(() => {
      count--;
      const el = document.getElementById('closing-warn-countdown');
      if (el) el.textContent = count;
      if (count <= 0) { clearInterval(timer); overlay.remove(); }
    }, 1000);
  }
  
// ── Public API ─────────────────────────────────────────────
  // ── Public API ─────────────────────────────────────────────
  return {
    init,
    switchPane,
    setPeriod,
    switchJobsTab,
    switchPerformanceTab : Performance.switchPerformanceTab,
    printReceipt,
    openReceipt,
    setReceiptsPeriod,
    _receiptsPageChange,
    printReceiptDetail,
    sendReceiptWhatsApp,
    loadInboxTab,
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
    initiateSheetDownload,
    closePinModal,
    _onPinInput,
    _submitPin,
    toggleSheetRow,
    _validateFloatInput,
    downloadInvoicePDF,
    setInvoicesPeriod,
    _invoicesPageChange,
    openCreateInvoice,
    openLateJobModal,
    closeLateJobModal,
    submitLateJob,
    _lateJobFilterServices,
    _lateJobSelectService,
    _checkLateJobButton,
    _showClosingModal,
    // Catalogue delegates
    openAddServiceModal  : Catalogue.openAddServiceModal,
    closeAddServiceModal : Catalogue.closeAddServiceModal,
    submitAddService     : Catalogue.submitAddService,
    _svcAutoCode         : Catalogue._svcAutoCode,
    _svcPreviewImage     : Catalogue._svcPreviewImage,
    _svcToggleConsumable : Catalogue._svcToggleConsumable,
    // Inventory delegates
    switchInventoryTab     : Inventory.switchInventoryTab,
    openReceiveStock       : Inventory.openReceiveStock,
    closeReceiveStock      : Inventory.closeReceiveStock,
    submitReceiveStock     : Inventory.submitReceiveStock,
    _recvSelectConsumable  : Inventory._recvSelectConsumable,
    _recvFilterConsumables : Inventory._recvFilterConsumables,
    _recvShowDropdown      : Inventory._recvShowDropdown,
    _openEquipmentModal    : Inventory._openEquipmentModal,
    _openAddEquipment      : Inventory._openAddEquipment,
    _saveEquipment         : Inventory._saveEquipment,
    _openAddMaintenanceLog : Inventory._openAddMaintenanceLog,
    _saveMaintenanceLog    : Inventory._saveMaintenanceLog,
    _printEquipmentQR      : Inventory._printEquipmentQR,
    // Customers delegates
    switchCustomersTab     : Customers.switchCustomersTab,
    openCustomerDetail     : Customers.openCustomerDetail,
    openAddCustomerModal   : Customers.openAddCustomerModal,
    onSearchInput          : Customers.onSearchInput,
    changePage             : Customers.changePage,
    closeCustomerProfile   : Customers.closeCustomerProfile,
    _saveCustomerNotes     : Customers.saveCustomerNotes,
    _editCustomer          : Customers.editCustomer,
    _saveCustomerEdit      : Customers.saveCustomerEdit,
    _editPhoneNormalise    : Customers.editPhoneNormalise,
    _toggleEditHistory     : Customers.toggleEditHistory,
    _nominateCredit        : Customers.nominateCredit,
    _editTitleChange       : Customers.editTitleChange,
    _renderEditCustomerForm: () => {},
    _loadEditHistory       : () => {},
    // Reports delegates
    setReportsPeriod         : Reports.setReportsPeriod,
    switchReportsTab         : Reports.switchReportsTab,
    weeklyPrepare            : Reports.weeklyPrepare,
    weeklySubmit             : Reports.weeklySubmit,
    weeklyDownloadPDF        : Reports.weeklyDownloadPDF,
    _renderMonthlyClose      : Reports.renderMonthlyClose,
    _submitMonthlyClose      : Reports.submitMonthlyClose,
    _downloadMonthlyPDF      : Reports.downloadMonthlyPDF,
    setServicesPeriod        : Reports.setServicesPeriod,
    _toggleDailySheet        : Reports.toggleDailySheet,
    _loadDailySheetInventory : Reports.loadDailySheetInventory,
    _toggleCurrentWeek       : () => {},
    _toggleHistoryWeek       : Reports.toggleHistoryWeek,
    _renderWeeklyReportDetail: Reports.renderWeeklyReportDetail,
    _renderWeeklyInventory   : Reports.renderWeeklyInventory,
    _renderMonthlyCloseDetail: Reports.renderMonthlyCloseDetail,
    _historyDrill            : Reports.historyDrill,
    _historyNav              : Reports.historyNav,
  };

})();

document.addEventListener('DOMContentLoaded', Dashboard.init);


// -------------------------------------------------------------
// State ? shared with NJ controller
// -------------------------------------------------------------
const State = {
  branchId  : null,
  services  : [],
  customers : [],
  page      : 1,
};
