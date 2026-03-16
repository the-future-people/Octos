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
    Auth.guard();
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

   if (user.branch && typeof user.branch === 'object') {
        const b = user.branch;
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
      const res  = await Auth.fetch('/api/v1/jobs/?page_size=200');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      const total      = data.count || jobs.length;
      const inProgress = jobs.filter(j => j.status === 'IN_PROGRESS').length;
      const complete   = jobs.filter(j => j.status === 'COMPLETE').length;
      const pending    = jobs.filter(j => j.status === 'PENDING_PAYMENT').length;
      const routed     = jobs.filter(j => j.is_routed).length;

      _set('stat-total-jobs',      total);
      _set('stat-in-progress',     inProgress);
      _set('stat-complete',        complete);
      _set('stat-pending-payment', pending);
      _set('stat-routed',          routed);

      // Sidebar badge
      const jobsBadge = document.getElementById('sidebar-badge-jobs');
      if (jobsBadge && total > 0) {
        jobsBadge.textContent = total;
        jobsBadge.style.display = 'flex';
      }

      // Branch load
      const load = total > 0 ? Math.round((inProgress / total) * 100) + '%' : '0%';
      _set('meta-load', load);

    } catch { /* silent */ }

    // Unread messages
    try {
      const res  = await Auth.fetch('/api/v1/communications/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const convos = Array.isArray(data) ? data : (data.results || []);
      const unread = convos.reduce((sum, c) => sum + (c.unread_count || 0), 0);

      _set('stat-unread', unread);

      const inboxBadge = document.getElementById('sidebar-badge-inbox');
      if (inboxBadge && unread > 0) {
        inboxBadge.textContent = unread;
        inboxBadge.style.display = 'flex';
      }
    } catch { /* silent */ }
  }

  // ── Recent jobs ────────────────────────────────────────────
  async function loadRecentJobs() {
    const tbody = document.getElementById('recent-jobs-tbody');
    if (!tbody) return;

    try {
      const res  = await Auth.fetch('/api/v1/jobs/?page_size=10');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:var(--text-3);font-size:13px;">No jobs yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = jobs.map(j => `
        <tr onclick="window.location='/portal/jobs/'">
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
    if (paneId === 'finance')                 _loadFinancePane();
  }

  // ── Jobs pane ──────────────────────────────────────────────
  async function _loadJobsPane() {
    jobsLoaded = true;
    const pane = document.getElementById('pane-jobs');
    if (!pane) return;

    pane.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading jobs…</div>';

    try {
      const res = await fetch('/portal/jobs-tab/');
      if (!res.ok) throw new Error();
      const html = await res.text();
      pane.innerHTML = html;
      pane.querySelectorAll('script').forEach(old => {
        const s = document.createElement('script');
        s.textContent = old.textContent;
        old.replaceWith(s);
      });
    } catch {
      pane.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load jobs.</div>';
    }
  }

  // ── Finance pane ───────────────────────────────────────────
  async function _loadFinancePane() {
    const pane = document.getElementById('pane-finance');
    if (!pane || pane.dataset.loaded) return;
    pane.dataset.loaded = '1';

    try {
      const res = await Auth.fetch('/api/v1/finance/sheets/today/');
      if (!res.ok) throw new Error();
      const sheet = await res.json();

      pane.innerHTML = `
        <div class="section-head">
          <span class="section-title">Today's Sales Sheet</span>
          <span class="section-link" style="color:${sheet.status === 'OPEN' ? 'var(--green-text)' : 'var(--text-3)'};">
            ${sheet.status}
          </span>
        </div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:24px;">
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
        <div class="section-head">
          <span class="section-title">Sheet Details</span>
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:20px;display:grid;grid-template-columns:1fr 1fr;gap:16px;">
          <div><span style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Total Jobs</span><div style="font-size:20px;font-weight:700;margin-top:4px;">${sheet.total_jobs_created}</div></div>
          <div><span style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Refunds</span><div style="font-size:20px;font-weight:700;margin-top:4px;">${_fmt(sheet.total_refunds)}</div></div>
          <div><span style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Petty Cash Out</span><div style="font-size:20px;font-weight:700;margin-top:4px;">${_fmt(sheet.total_petty_cash_out)}</div></div>
          <div><span style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Credit Issued</span><div style="font-size:20px;font-weight:700;margin-top:4px;">${_fmt(sheet.total_credit_issued)}</div></div>
        </div>
        <div style="margin-top:20px;display:flex;gap:10px;">
        ${sheet.status === 'OPEN' ? `
          <button class="btn-dark" onclick="Dashboard.closeSheet(${sheet.id})">Close Day Sheet</button>
        ` : `
          <a href="/api/v1/finance/sheets/${sheet.id}/pdf/" 
             target="_blank"
             style="display:inline-flex;align-items:center;gap:6px;padding:8px 18px;
                    background:var(--text);color:#fff;border-radius:var(--radius-sm);
                    font-size:13px;font-weight:700;text-decoration:none;">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
            Download Sheet PDF
          </a>
        `}
      </div>
        ${sheet.notes ? `<div style="margin-top:16px;padding:14px 16px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);font-size:13px;color:var(--text-2);">${_esc(sheet.notes)}</div>` : ''}
      `;
    } catch {
      pane.innerHTML = '<div class="loading-cell">Could not load today\'s sheet.</div>';
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
  async function loadInboxTab() {
    if (inboxLoaded) return;
    inboxLoaded = true;

    const list = document.getElementById('inbox-tab-list');
    if (!list) return;

    try {
      const res  = await Auth.fetch('/api/v1/communications/');
      if (!res.ok) throw new Error();
      const data   = await res.json();
      const convos = Array.isArray(data) ? data : (data.results || []);

      if (!convos.length) {
        list.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-3);font-size:13px;">No conversations yet.</div>`;
        return;
      }

const AV_COLORS = ['#22c98a','#e8294a','#4a90e8','#9b59b6','#e8c84a'];
      const _avColor  = name => {
        let h = 0;
        for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
        return AV_COLORS[Math.abs(h) % AV_COLORS.length];
      };

      list.innerHTML = convos.slice(0, 12).map(c => {
        const name     = c.display_name || c.customer_name || 'Unknown';
        const ini      = _initials(name);
        const avColor  = _avColor(name);
        const time     = _timeAgo(c.last_message_at || c.updated_at || c.created_at);
        const preview  = _esc(_truncate(c.last_message_preview || c.last_message || 'No messages yet', 60));
        const hasUnread = (c.unread_count || 0) > 0;
        const channel  = c.channel || '';

        const channelBadge = channel ? `
          <span style="
            display:inline-flex;align-items:center;padding:2px 8px;border-radius:20px;
            font-size:10px;font-weight:700;letter-spacing:0.3px;margin-left:6px;
            background:var(--bg);border:1px solid var(--border);color:var(--text-3);
          ">${channel.replace('_', ' ')}</span>` : '';

        return `
          <div onclick="window.location='/portal/inbox/'" style="
            display:flex;align-items:center;gap:12px;
            padding:12px 20px;border-bottom:1px solid var(--border);
            cursor:pointer;transition:background 0.12s;
          " onmouseover="this.style.background='var(--bg)'" onmouseout="this.style.background=''">
            <div style="
              width:38px;height:38px;border-radius:50%;flex-shrink:0;
              background:${avColor};color:${avColor === '#e8c84a' ? '#111' : '#fff'};
              display:flex;align-items:center;justify-content:center;
              font-family:'Syne',sans-serif;font-size:13px;font-weight:700;
            ">${ini}</div>
            <div style="flex:1;min-width:0;">
              <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:3px;">
                <div style="display:flex;align-items:center;">
                  <span style="font-size:13.5px;font-weight:${hasUnread ? '700' : '500'};color:var(--text);">
                    ${_esc(name)}
                  </span>
                  ${channelBadge}
                </div>
                <span style="font-size:11px;color:var(--text-3);font-family:'JetBrains Mono',monospace;flex-shrink:0;">${time}</span>
              </div>
              <div style="display:flex;align-items:center;justify-content:space-between;">
                <span style="font-size:12.5px;color:var(--text-3);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:380px;">${preview}</span>
                ${hasUnread ? `<span style="width:7px;height:7px;border-radius:50%;background:var(--red-text);flex-shrink:0;margin-left:8px;"></span>` : ''}
              </div>
            </div>
          </div>`;
      }).join('');

    } catch {
      list.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-3);">Could not load inbox.</div>`;
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

  // ── Public API ─────────────────────────────────────────────
  return {
    init,
    switchPane,
    setPeriod,
    loadInboxTab,
    loadServicesTab,
    openOutsourceModal,
    confirmOutsource,
    closeSheet,
    onJobCreated,
    closeEOD,
    toggleEODConfirm,
    confirmCloseSheet,
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