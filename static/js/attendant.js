/**
 * Octos — Attendant Portal
 *
 * Panes: Overview, My Jobs, Branch Jobs, Drafts, Inbox, Services
 */

'use strict';

const Attendant = (() => {

  // ── State ──────────────────────────────────────────────────
  let _sheetId       = null;
  let _services      = [];
  let _customers     = [];
  let _myJobsLoaded  = false;
  let _branchLoaded  = false;
  let _draftsLoaded  = false;
  let _inboxLoaded   = false;
  let _svcLoaded     = false;
  let _inboxChannel  = 'WHATSAPP';
  let _inboxConvos   = [];
  let _activeConvoId = null;

  // ── Boot ───────────────────────────────────────────────────
  async function init() {
    await Auth.guard(['ATTENDANT', 'BRANCH_MANAGER', 'SUPER_ADMIN']);
    _set('at-meta-date', new Date().toLocaleDateString('en-GB', {
      weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
    }));
    await Promise.all([
      _loadContext(),
      _loadServicesAndCustomers(),
    ]);
    await _loadSheet();
    await Promise.all([
      _loadStats(),
      _loadRecentJobs(),
      _loadDraftCount(),
      _loadShift(),
    ]);
    AtNotifications.startPolling();
    WeekGreeter.init();
  }

  // ── Context ────────────────────────────────────────────────
  async function _loadContext() {
    try {
      const res  = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const user = await res.json();

      const fullName = user.full_name || user.email || '—';
      const initials = fullName.split(' ').slice(0, 2)
        .map(w => w[0]?.toUpperCase() || '').join('');

      _set('at-user-name',     fullName);
      _set('at-user-initials', initials);

      if (user.branch_detail) {
        const b = user.branch_detail;
        State.branchId = b.id;
        _set('at-branch-name',      b.name || '—');
        _set('at-branch-name-left', b.name || '—');
        _set('at-meta-branch',      b.name || '—');
      }
    } catch { /* silent */ }
  }

  // ── Sheet ──────────────────────────────────────────────────
  async function _loadSheet() {
    try {
      const res = await Auth.fetch('/api/v1/finance/sheets/today/');
      if (!res.ok) return;
      const sheet = await res.json();
      if (sheet.status === 'OPEN') _sheetId = sheet.id;
    } catch { /* silent */ }
  }

  // ── Shift ──────────────────────────────────────────────────
// ── Shift ──────────────────────────────────────────────────
  async function _loadShift() {
    try {
      const res  = await Auth.fetch('/api/v1/finance/cashier/shift-status/');
      if (!res.ok) return;
      const data = await res.json();

      if (!data.has_shift) {
        _set('at-meta-shift-end', 'No shift');
        return;
      }

      const end = data.overtime_until || data.shift_end;
      if (!end) return;

      // shift_end may be "HH:MM:SS" or full ISO datetime
      let endTime;
      if (String(end).includes('T')) {
        endTime = new Date(end);
      } else {
        const today = new Date().toISOString().slice(0, 10);
        endTime     = new Date(`${today}T${end}`);
      }

      const now    = new Date();
      const diffMs = endTime - now;

      const timeStr = endTime.toLocaleTimeString('en-GH', {
        hour: '2-digit', minute: '2-digit', hour12: true,
      });

      let remainingHtml = '';
      if (diffMs > 0) {
        const totalMins = Math.floor(diffMs / 60000);
        const hrs       = Math.floor(totalMins / 60);
        const mins      = totalMins % 60;
        const label     = hrs > 0 ? `${hrs}h ${mins}m left` : `${mins}m left`;
        const pillClass = diffMs < 3600000 ? 'at-shift-pill at-shift-pill-warn' : 'at-shift-pill';
        remainingHtml   = ` <span class="${pillClass}">${label}</span>`;
      }

      const label = data.is_overtime ? `${timeStr} (OT)` : timeStr;
      const el    = document.getElementById('at-meta-shift-end');
      if (el) el.innerHTML = _esc(label) + remainingHtml;

    } catch { /* silent */ }
  }

  // ── Stats — single server call ─────────────────────────────
  async function _loadStats() {
    if (!_sheetId) return;
    try {
      const res  = await Auth.fetch(`/api/v1/jobs/stats/?daily_sheet=${_sheetId}`);
      if (!res.ok) return;
      const data = await res.json();
      const p    = data.personal || {};

      _renderStatsStrip(p);
      _renderProgressBar(p);
      _renderInsightsPanel(p);
      _renderStreakWidget(p);
      _renderSheetNumber(p);

      // Sidebar my-jobs badge
      const badge = document.getElementById('sidebar-badge-myjobs');
      if (badge) {
        const total             = p.my_total || 0;
        badge.textContent       = total;
        badge.style.display     = total > 0 ? 'flex' : 'none';
      }

    } catch { /* silent */ }
  }

  // ── Render: stats strip ────────────────────────────────────
  function _renderStatsStrip(p) {
    _set('stat-my-total',     p.my_total     ?? '—');
    _set('stat-my-confirmed', p.my_confirmed ?? '—');
    _set('stat-per-hour',     p.jobs_per_hour != null ? p.jobs_per_hour : '—');

    // My value — GHS formatted
    const valEl = document.getElementById('stat-my-value');
    if (valEl) {
      valEl.textContent = p.my_value != null
        ? 'GHS ' + Number(p.my_value).toLocaleString('en-GH', {
            minimumFractionDigits: 2, maximumFractionDigits: 2,
          })
        : 'GHS —';
    }

    // Completion rate + delta
    _set('stat-my-rate', p.my_rate != null ? p.my_rate + '%' : '—');
    const deltaEl = document.getElementById('stat-rate-delta');
    if (deltaEl) {
      if (p.yesterday_rate != null && p.my_rate != null) {
        const diff = p.my_rate - p.yesterday_rate;
        if (diff > 0) {
          deltaEl.textContent  = `↑ vs ${p.yesterday_rate}% yesterday`;
          deltaEl.className    = 'at-stat-delta at-delta-up';
        } else if (diff < 0) {
          deltaEl.textContent  = `↓ vs ${p.yesterday_rate}% yesterday`;
          deltaEl.className    = 'at-stat-delta at-delta-down';
        } else {
          deltaEl.textContent  = `= ${p.yesterday_rate}% yesterday`;
          deltaEl.className    = 'at-stat-delta';
        }
      } else {
        deltaEl.textContent = 'no data yet';
        deltaEl.className   = 'at-stat-delta';
      }
    }

    // Confirmed sub label
    const subEl = document.getElementById('stat-confirmed-sub');
    if (subEl && p.my_total > 0) {
      const pending = p.my_total - (p.my_confirmed || 0);
      subEl.textContent = pending > 0
        ? `${pending} pending cashier`
        : 'all cleared ✓';
    }
  }

  // ── Render: progress bar ───────────────────────────────────
  function _renderProgressBar(p) {
    const wrap = document.getElementById('at-progress-wrap');
    if (!wrap) return;

    const total   = p.my_total    || 0;
    const target  = p.daily_target || 10;
    const pct     = Math.min(Math.round((total / target) * 100), 100);
    const done    = total >= target;

    _set('at-progress-title', `Daily target — ${target} jobs`);
    _set('at-progress-meta',  `${total} of ${target} done`);

    const fill = document.getElementById('at-progress-fill');
    if (fill) {
      fill.style.width      = pct + '%';
      fill.style.background = done ? 'var(--green, #1D9E75)' : '';
    }

    const footEl = document.getElementById('at-progress-foot-label');
    if (footEl) {
      if (done) {
        footEl.textContent = '🎯 Target reached!';
      } else {
        const rem = target - total;
        footEl.textContent = `${rem} more to hit target`;
      }
    }

    // Personal best pill
    const pbEl = document.getElementById('at-pb-badge');
    if (pbEl && p.personal_best) {
      pbEl.textContent    = `Personal best: ${p.personal_best} jobs — ${p.personal_best_date || ''}`;
      pbEl.style.display  = 'inline-block';
    }
  }

  // ── Render: insights panel ─────────────────────────────────
  function _renderInsightsPanel(p) {
    // Top service
    const topEl = document.getElementById('insight-top-service-val');
    if (topEl) {
      topEl.textContent = p.top_service
        ? `${p.top_service} — ${p.top_service_count} job${p.top_service_count !== 1 ? 's' : ''}`
        : 'No data yet this week';
    }

    // Week daily counts
    const weekEl = document.getElementById('insight-week-counts');
    if (weekEl && p.week_daily_counts && p.week_daily_counts.length) {
      weekEl.textContent = p.week_daily_counts
        .filter(d => !d.is_future)
        .map(d => `${d.day} ${d.count}`)
        .join(' · ') || 'No jobs this week yet';
    }
  }

  // ── Render: streak widget ──────────────────────────────────
  function _renderStreakWidget(p) {
    const wrap = document.getElementById('sidebar-streak');
    if (!wrap) return;

    const streak     = p.streak     || 0;
    const streakDays = p.streak_days || [];

    // Only show if they've worked at least one day this week
    const hasActivity = streakDays.some(d => d.state !== 'future' && d.state !== 'empty');
    if (!hasActivity) return;

    wrap.style.display = 'block';
    _set('streak-count', streak > 0 ? `${streak}-day streak` : 'Keep going!');

    const daysEl = document.getElementById('streak-days');
    if (daysEl) {
      daysEl.innerHTML = streakDays.map(d => {
        let cls = 'streak-day';
        if (d.state === 'hit')    cls += ' streak-hit';
        if (d.state === 'miss')   cls += ' streak-miss';
        if (d.state === 'empty')  cls += ' streak-empty';
        if (d.state === 'future') cls += ' streak-future';
        if (d.is_today)           cls += ' streak-today';
        return `<div class="${cls}" title="${d.label}">${_esc(d.label)}</div>`;
      }).join('');
    }
  }

  // ── Render: sheet number ───────────────────────────────────
  function _renderSheetNumber(p) {
    const el = document.getElementById('at-meta-sheet');
    if (!el) return;
    el.textContent = p.sheet_number ? `#${p.sheet_number}` : (_sheetId ? `#${_sheetId}` : '—');
  }

  async function _loadDraftCount() {
    try {
      const res  = await Auth.fetch('/api/v1/jobs/drafts/');
      if (!res.ok) return;
      const data   = await res.json();
      const drafts = Array.isArray(data) ? data : (data.results || []);

      const badge = document.getElementById('sidebar-badge-drafts');
      if (badge) {
        badge.textContent   = drafts.length;
        badge.style.display = drafts.length > 0 ? 'flex' : 'none';
      }
    } catch { /* silent */ }
  }

  // ── Recent jobs (overview table) ───────────────────────────
  async function _loadRecentJobs() {
    const tbody = document.getElementById('recent-jobs-tbody');
    if (!tbody || !_sheetId) return;

    try {
      const res  = await Auth.fetch(
        `/api/v1/jobs/?daily_sheet=${_sheetId}&intake_by=me&page_size=8`
      );
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;padding:32px;
          color:var(--text-3);font-size:13px;">No jobs yet today. Create your first one!</td></tr>`;
        return;
      }

      tbody.innerHTML = jobs.map(j => `
        <tr onclick="Attendant.openDetail(${j.id})" style="cursor:pointer;">
          <td>
            <div class="td-job-title">${_esc(j.title || '—')}</div>
            <div class="td-job-ref">${_esc(j.job_number || '#' + j.id)}</div>
          </td>
          <td>${_typeBadge(j.job_type)}</td>
          <td>${_statusBadge(j.status)}</td>
          <td style="font-size:12px;color:var(--text-3);">${_timeAgo(j.created_at)}</td>
        </tr>`).join('');
    } catch {
      tbody.innerHTML = `<tr><td colspan="4" class="loading-cell">Could not load jobs.</td></tr>`;
    }
  }

  // ── Pane switching ─────────────────────────────────────────
  let _myJobsExpanded = false;

  function toggleMyJobs() {
    _myJobsExpanded = !_myJobsExpanded;
    const subnav = document.getElementById('myjobs-subnav');
    if (subnav) subnav.style.display = _myJobsExpanded ? 'block' : 'none';
    if (_myJobsExpanded) switchPane('my-jobs-today', "Today's Jobs");
  }

  function switchPane(paneId, label) {
    document.querySelectorAll('.sidebar-item').forEach(item => {
      item.classList.toggle('active', item.dataset.pane === paneId);
    });
    document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
    const target = document.getElementById(`pane-${paneId}`);
    if (target) target.classList.add('active');
    _set('breadcrumb-current', label);

    if (paneId === 'my-jobs-today' && !_myJobsLoaded)  _loadMyJobsPane();
    if (paneId === 'branch-jobs'   && !_branchLoaded)  _loadBranchJobsPane();
    if (paneId === 'drafts'        && !_draftsLoaded)  _loadDraftsPane();
    if (paneId === 'inbox'         && !_inboxLoaded)   _loadInboxPane();
    if (paneId === 'services'      && !_svcLoaded)     _loadServicesPane();
    if (paneId === 'search') {
      setTimeout(() => document.getElementById('search-input')?.focus(), 50);
    }
  }

  // ── My Jobs pane ───────────────────────────────────────────
  async function _loadMyJobsPane() {
    _myJobsLoaded = true;
    const pane = document.getElementById('pane-my-jobs-today');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">My Jobs Today</span>
      </div>
      <div style="background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);overflow:hidden;">
        <table class="p-table">
          <thead>
            <tr>
              <th>Job</th><th>Type</th><th>Status</th><th>Customer</th><th>Created</th>
            </tr>
          </thead>
          <tbody id="my-jobs-tbody">
            <tr><td colspan="5" class="loading-cell"><span class="spin"></span> Loading…</td></tr>
          </tbody>
        </table>
      </div>`;

    await _renderMyJobs();
  }

  async function _renderMyJobs() {
    const tbody = document.getElementById('my-jobs-tbody');
    if (!tbody || !_sheetId) return;

    try {
      const res  = await Auth.fetch(
        `/api/v1/jobs/?daily_sheet=${_sheetId}&intake_by=me&page_size=100`
      );
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:32px;
          color:var(--text-3);">No jobs yet today.</td></tr>`;
        return;
      }

      tbody.innerHTML = jobs.map(j => `
        <tr onclick="Attendant.openDetail(${j.id})" style="cursor:pointer;">
          <td>
            <div class="td-job-title">${_esc(j.title || '—')}</div>
            <div class="td-job-ref">${_esc(j.job_number || '#' + j.id)}</div>
          </td>
          <td>${_typeBadge(j.job_type)}</td>
          <td>${_statusBadge(j.status)}</td>
          <td style="font-size:13px;color:var(--text-2);">${_esc(j.customer_name || 'Walk-in')}</td>
          <td style="font-size:12px;color:var(--text-3);">${_timeAgo(j.created_at)}</td>
        </tr>`).join('');
    } catch {
      tbody.innerHTML = `<tr><td colspan="5" class="loading-cell"
        style="color:var(--red-text);">Could not load jobs.</td></tr>`;
    }
  }

  // ── Branch Jobs pane ───────────────────────────────────────
  async function _loadBranchJobsPane() {
    _branchLoaded = true;
    const pane = document.getElementById('pane-branch-jobs');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Branch Jobs Today</span>
        <span style="font-size:12px;color:var(--text-3);">Status view only</span>
      </div>
      <div style="background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);overflow:hidden;">
        <table class="p-table">
          <thead>
            <tr>
              <th>Job Ref</th><th>Title</th><th>Type</th><th>Status</th><th>Created</th>
            </tr>
          </thead>
          <tbody id="branch-jobs-tbody">
            <tr><td colspan="5" class="loading-cell"><span class="spin"></span> Loading…</td></tr>
          </tbody>
        </table>
      </div>`;

    if (!_sheetId) {
      document.getElementById('branch-jobs-tbody').innerHTML =
        `<tr><td colspan="5" style="text-align:center;padding:32px;color:var(--text-3);">
          No open sheet today.</td></tr>`;
      return;
    }

    try {
      const res  = await Auth.fetch(
        `/api/v1/jobs/?daily_sheet=${_sheetId}&page_size=100`
      );
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);
      const tbody = document.getElementById('branch-jobs-tbody');

      if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center;padding:32px;
          color:var(--text-3);">No jobs today.</td></tr>`;
        return;
      }

      tbody.innerHTML = jobs.map(j => `
        <tr>
          <td style="font-family:'JetBrains Mono',monospace;font-size:11px;color:var(--text-3);">
            ${_esc(j.job_number || '#' + j.id)}
          </td>
          <td style="font-size:13px;color:var(--text-2);">${_esc(j.title || '—')}</td>
          <td>${_typeBadge(j.job_type)}</td>
          <td>${_statusBadge(j.status)}</td>
          <td style="font-size:12px;color:var(--text-3);">${_timeAgo(j.created_at)}</td>
        </tr>`).join('');
    } catch {
      document.getElementById('branch-jobs-tbody').innerHTML =
        `<tr><td colspan="5" class="loading-cell" style="color:var(--red-text);">
          Could not load jobs.</td></tr>`;
    }
  }

  // ── Drafts pane ────────────────────────────────────────────
  async function _loadDraftsPane() {
    _draftsLoaded = true;
    const pane = document.getElementById('pane-drafts');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head"><span class="section-title">Saved Drafts</span></div>
      <div id="drafts-list"><div class="loading-cell"><span class="spin"></span> Loading…</div></div>`;

    try {
      const res    = await Auth.fetch('/api/v1/jobs/drafts/');
      if (!res.ok) throw new Error();
      const data   = await res.json();
      const drafts = Array.isArray(data) ? data : (data.results || []);
      const el     = document.getElementById('drafts-list');

      if (!drafts.length) {
        el.innerHTML = `
          <div style="text-align:center;padding:48px;color:var(--text-3);">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" stroke-width="1.5"
              style="margin-bottom:12px;opacity:0.4;">
              <path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>
            </svg>
            <div style="font-size:13px;">No saved drafts.</div>
          </div>`;
        return;
      }

      el.innerHTML = drafts.map(d => `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:16px 20px;margin-bottom:10px;
          display:flex;align-items:center;justify-content:space-between;">
          <div>
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">
              ${_esc(d.title || 'Untitled Draft')}
            </div>
            <div style="font-size:12px;color:var(--text-3);">
              ${_esc(d.job_number)} ·
              ${d.line_items?.length || 0} item${d.line_items?.length !== 1 ? 's' : ''} ·
              Expires ${_timeAgo(d.expires_at)}
            </div>
          </div>
          <div style="display:flex;gap:8px;">
            <button onclick="Attendant.resumeDraft(${d.id})"
              style="padding:7px 16px;background:var(--text);color:#fff;border:none;
                     border-radius:var(--radius-sm);font-size:12px;font-weight:700;
                     cursor:pointer;font-family:inherit;">Resume</button>
            <button onclick="Attendant.discardDraft(${d.id})"
              style="padding:7px 12px;background:none;border:1px solid var(--border);
                     border-radius:var(--radius-sm);font-size:12px;color:var(--text-3);
                     cursor:pointer;font-family:inherit;">Discard</button>
          </div>
        </div>`).join('');
    } catch {
      document.getElementById('drafts-list').innerHTML =
        `<div class="loading-cell" style="color:var(--red-text);">Could not load drafts.</div>`;
    }
  }

  async function resumeDraft(draftId) {
    try {
      const res   = await Auth.fetch('/api/v1/jobs/drafts/');
      if (!res.ok) return;
      const data  = await res.json();
      const draft = (Array.isArray(data) ? data : (data.results || []))
        .find(d => d.id === draftId);
      if (!draft) return;

      NJ.open();
      NJ.setType('INSTANT');

      setTimeout(() => {
        if (draft.line_items?.length) {
          draft.line_items.forEach(item => {
            const svc = _services.find(s => s.id === item.service);
            if (!svc) return;
            NJ._selectServiceChip(svc.id);
            setTimeout(() => {
              const pagesEl = document.getElementById('nj-pages');
              const setsEl  = document.getElementById('nj-sets');
              if (pagesEl) pagesEl.value = item.pages || 1;
              if (setsEl)  setsEl.value  = item.sets  || 1;
              NJ._addToCart();
            }, 200);
          });
        }
        _toast(`Resuming draft: ${draft.title}`, 'info');
      }, 300);
    } catch {
      _toast('Could not resume draft.', 'error');
    }
  }

  async function discardDraft(draftId) {
    try {
      const res = await Auth.fetch(`/api/v1/jobs/drafts/${draftId}/discard/`, {
        method: 'POST',
      });
      if (res.ok) {
        _toast('Draft discarded.', 'info');
        _draftsLoaded = false;
        _loadDraftsPane();
        _loadDraftCount();
      }
    } catch {
      _toast('Could not discard draft.', 'error');
    }
  }

  // ── Inbox pane ─────────────────────────────────────────────
  async function _loadInboxPane() {
    _inboxLoaded = true;
    const pane = document.getElementById('pane-inbox');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head"><span class="section-title">Inbox</span></div>
      <div class="reports-tabs" id="inbox-channel-tabs">
        <button class="reports-tab active" data-channel="WHATSAPP"
          onclick="Attendant.switchInboxChannel('WHATSAPP')">
          WhatsApp <span class="inbox-badge" id="inbox-badge-WHATSAPP" style="display:none;"></span>
        </button>
        <button class="reports-tab" data-channel="EMAIL"
          onclick="Attendant.switchInboxChannel('EMAIL')">
          Email <span class="inbox-badge" id="inbox-badge-EMAIL" style="display:none;"></span>
        </button>
        <button class="reports-tab" data-channel="PHONE"
          onclick="Attendant.switchInboxChannel('PHONE')">
          Phone <span class="inbox-badge" id="inbox-badge-PHONE" style="display:none;"></span>
        </button>
      </div>
      <div id="inbox-body" style="display:flex;gap:0;border:1px solid var(--border);
        border-radius:var(--radius);overflow:hidden;min-height:480px;">
        <div id="inbox-list" style="width:320px;flex-shrink:0;border-right:1px solid var(--border);overflow-y:auto;"></div>
        <div id="inbox-thread" style="flex:1;display:flex;flex-direction:column;">
          <div style="flex:1;display:flex;align-items:center;justify-content:center;
            color:var(--text-3);font-size:13px;">Select a conversation</div>
        </div>
      </div>`;

    await _fetchInbox();
  }

  async function _fetchInbox() {
    const listEl = document.getElementById('inbox-list');
    if (!listEl) return;
    listEl.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-3);"><span class="spin"></span></div>';

    try {
      const res = await Auth.fetch('/api/v1/communications/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      _inboxConvos = Array.isArray(data) ? data : (data.results || []);

      ['WHATSAPP','EMAIL','PHONE'].forEach(ch => {
        const unread = _inboxConvos
          .filter(c => (c.channel||'').toUpperCase() === ch)
          .reduce((sum, c) => sum + (c.unread_count||0), 0);
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
      c => (c.channel||'').toUpperCase() === _inboxChannel
    );

    if (!filtered.length) {
      listEl.innerHTML = `<div style="padding:32px;text-align:center;color:var(--text-3);font-size:13px;">
        No ${_inboxChannel.toLowerCase()} conversations.</div>`;
      return;
    }

    const AV_COLORS = ['#22c98a','#e8294a','#4a90e8','#9b59b6','#e8c84a'];
    const avColor = name => {
      let h = 0;
      for (let i = 0; i < name.length; i++) h = name.charCodeAt(i) + ((h << 5) - h);
      return AV_COLORS[Math.abs(h) % AV_COLORS.length];
    };

    listEl.innerHTML = filtered.map(c => {
      const name      = c.display_name || c.customer_name || 'Unknown';
      const ini       = _initials(name);
      const color     = avColor(name);
      const time      = _timeAgo(c.last_message_at || c.updated_at || c.created_at);
      const preview   = _esc(_truncate(c.last_message_preview || 'No messages yet', 55));
      const hasUnread = (c.unread_count||0) > 0;
      const isActive  = c.id === _activeConvoId;

      return `
        <div onclick="Attendant.openConvo(${c.id})"
          style="display:flex;align-items:center;gap:10px;padding:12px 14px;
                 border-bottom:1px solid var(--border);cursor:pointer;
                 background:${isActive ? 'var(--bg)' : 'var(--panel)'};transition:background 0.12s;"
          onmouseover="this.style.background='var(--bg)'"
          onmouseout="this.style.background='${isActive ? 'var(--bg)' : 'var(--panel)'}'">
          <div style="width:36px;height:36px;border-radius:50%;flex-shrink:0;
            background:${color};color:${color==='#e8c84a'?'#111':'#fff'};
            display:flex;align-items:center;justify-content:center;
            font-family:'Syne',sans-serif;font-size:12px;font-weight:700;">${ini}</div>
          <div style="flex:1;min-width:0;">
            <div style="display:flex;justify-content:space-between;margin-bottom:2px;">
              <span style="font-size:13px;font-weight:${hasUnread?'700':'500'};color:var(--text);
                white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:160px;">
                ${_esc(name)}
              </span>
              <span style="font-size:10.5px;color:var(--text-3);font-family:'JetBrains Mono',monospace;
                flex-shrink:0;margin-left:6px;">${time}</span>
            </div>
            <div style="display:flex;align-items:center;justify-content:space-between;">
              <span style="font-size:12px;color:var(--text-3);white-space:nowrap;overflow:hidden;
                text-overflow:ellipsis;max-width:200px;">${preview}</span>
              ${hasUnread ? `<span style="width:6px;height:6px;border-radius:50%;
                background:var(--red-text);flex-shrink:0;margin-left:6px;"></span>` : ''}
            </div>
          </div>
        </div>`;
    }).join('');
  }

  function switchInboxChannel(channel) {
    _inboxChannel  = channel;
    _activeConvoId = null;
    document.querySelectorAll('#inbox-channel-tabs .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.channel === channel);
    });
    _renderInboxList();
    const thread = document.getElementById('inbox-thread');
    if (thread) thread.innerHTML = `<div style="flex:1;display:flex;align-items:center;
      justify-content:center;color:var(--text-3);font-size:13px;">Select a conversation</div>`;
  }

  async function openConvo(convoId) {
    _activeConvoId = convoId;
    _renderInboxList();
    const thread = document.getElementById('inbox-thread');
    if (!thread) return;
    thread.innerHTML = '<div style="flex:1;display:flex;align-items:center;justify-content:center;"><span class="spin"></span></div>';

    try {
      const res   = await Auth.fetch(`/api/v1/communications/${convoId}/`);
      if (!res.ok) throw new Error();
      const convo = await res.json();
      const msgs  = convo.messages || [];
      const name  = convo.display_name || convo.customer_name || 'Unknown';

      thread.innerHTML = `
        <div style="padding:14px 16px;border-bottom:1px solid var(--border);flex-shrink:0;">
          <div style="font-size:14px;font-weight:700;color:var(--text);">${_esc(name)}</div>
          <div style="font-size:11px;color:var(--text-3);margin-top:1px;">
            ${_esc(convo.channel||'')} · ${convo.contact_value||''}
          </div>
        </div>
        <div id="inbox-messages" style="flex:1;overflow-y:auto;padding:16px;
          display:flex;flex-direction:column;gap:10px;">
          ${msgs.length
            ? msgs.map(m => _renderMessage(m)).join('')
            : '<div style="text-align:center;color:var(--text-3);font-size:13px;padding:32px 0;">No messages yet.</div>'}
        </div>
        <div style="padding:12px 14px;border-top:1px solid var(--border);display:flex;gap:8px;flex-shrink:0;">
          <input id="inbox-reply-input" type="text" placeholder="Type a reply…"
            style="flex:1;padding:8px 12px;border:1px solid var(--border);
                   border-radius:var(--radius-sm);background:var(--bg);
                   color:var(--text);font-size:13px;outline:none;"
            onkeydown="if(event.key==='Enter') Attendant.sendReply(${convoId})"/>
          <button onclick="Attendant.sendReply(${convoId})"
            style="padding:8px 16px;background:var(--text);color:#fff;border:none;
                   border-radius:var(--radius-sm);font-size:13px;font-weight:700;cursor:pointer;">
            Send
          </button>
        </div>`;

      const msgsEl = document.getElementById('inbox-messages');
      if (msgsEl) msgsEl.scrollTop = msgsEl.scrollHeight;
    } catch {
      thread.innerHTML = '<div style="flex:1;display:flex;align-items:center;justify-content:center;color:var(--text-3);">Could not load conversation.</div>';
    }
  }

  function _renderMessage(m) {
    const isOut = m.direction === 'OUTBOUND' || m.is_outbound;
    const time  = m.created_at
      ? new Date(m.created_at).toLocaleTimeString('en-GH', { hour:'2-digit', minute:'2-digit' })
      : '';
    return `
      <div style="display:flex;flex-direction:column;align-items:${isOut?'flex-end':'flex-start'};">
        <div style="max-width:70%;padding:9px 13px;
          border-radius:${isOut?'14px 14px 4px 14px':'14px 14px 14px 4px'};
          background:${isOut?'var(--text)':'var(--bg)'};
          color:${isOut?'#fff':'var(--text)'};
          border:${isOut?'none':'1px solid var(--border)'};
          font-size:13px;line-height:1.5;">
          ${_esc(m.body||m.content||'')}
        </div>
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
      if (res.ok) await openConvo(convoId);
      else { _toast('Could not send reply.', 'error'); input.disabled = false; }
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
        _services = Array.isArray(data) ? data : (data.results || []);
        if (typeof State !== 'undefined') State.services = _services;
      }
      if (custRes.ok) {
        const data = await custRes.json();
        _customers = Array.isArray(data) ? data : (data.results || []);
        if (typeof State !== 'undefined') State.customers = _customers;
      }
    } catch { /* silent */ }
  }

  async function _loadServicesPane() {
    _svcLoaded = true;
    const grid = document.getElementById('services-grid');
    if (!grid) return;
    _set('meta-services-count', `${_services.length} services`);

    if (!_services.length) {
      grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:var(--text-3);">
        No services available.</div>`;
      return;
    }

    grid.innerHTML = _services.map(s => `
      <div class="service-card">
        <div class="service-card-name">${_esc(s.name)}</div>
        <div class="service-card-price">${s.base_price != null ? 'GHS ' + Number(s.base_price).toFixed(2) : '—'}</div>
        <div class="service-card-desc">${_esc(s.description || '')}</div>
      </div>`).join('');
  }

  // ── Job detail modal ───────────────────────────────────────
  async function openDetail(jobId) {
    const overlay = document.getElementById('job-detail-modal');
    const body    = document.getElementById('detail-body');
    overlay.classList.add('open');
    body.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-3);">
      <span class="spin"></span> Loading…</div>`;

    try {
      const res = await Auth.fetch(`/api/v1/jobs/${jobId}/`);
      if (!res.ok) throw new Error();
      const job = await res.json();

      _set('detail-title', job.title || 'Job Detail');
      _set('detail-ref',   job.job_number || `#${job.id}`);

      const logs = (job.status_logs || []).map(log => {
        const from = _statusLabel(log.from_status);
        const to   = _statusLabel(log.to_status);
        const when = log.transitioned_at
          ? new Date(log.transitioned_at).toLocaleString('en-GB', {
              day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'
            })
          : '';
        return `
          <div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);">
            <div style="font-size:13px;font-weight:600;color:var(--text);flex:1;">
              ${from} → ${to}
            </div>
            <div style="font-size:11px;color:var(--text-3);">${when}</div>
          </div>`;
      }).join('') || '<div style="color:var(--text-3);font-size:13px;">No history yet.</div>';

      body.innerHTML = `
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px;">
          <div>
            <div style="font-size:10.5px;font-weight:700;color:var(--text-3);text-transform:uppercase;
              letter-spacing:0.3px;margin-bottom:4px;">Status</div>
            ${_statusBadge(job.status)}
          </div>
          <div>
            <div style="font-size:10.5px;font-weight:700;color:var(--text-3);text-transform:uppercase;
              letter-spacing:0.3px;margin-bottom:4px;">Type</div>
            ${_typeBadge(job.job_type)}
          </div>
          <div>
            <div style="font-size:10.5px;font-weight:700;color:var(--text-3);text-transform:uppercase;
              letter-spacing:0.3px;margin-bottom:4px;">Customer</div>
            <div style="font-size:13.5px;color:var(--text-2);">${_esc(job.customer_name || 'Walk-in')}</div>
          </div>
          <div>
            <div style="font-size:10.5px;font-weight:700;color:var(--text-3);text-transform:uppercase;
              letter-spacing:0.3px;margin-bottom:4px;">Channel</div>
            <div style="font-size:13.5px;color:var(--text-2);">${_esc(job.intake_channel || '—')}</div>
          </div>
          <div>
            <div style="font-size:10.5px;font-weight:700;color:var(--text-3);text-transform:uppercase;
              letter-spacing:0.3px;margin-bottom:4px;">Created</div>
            <div style="font-size:13px;color:var(--text-3);">
              ${job.created_at ? new Date(job.created_at).toLocaleString('en-GB',{
                day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : '—'}
            </div>
          </div>
        </div>

        ${job.notes ? `
        <div style="padding:12px;background:var(--bg);border:1px solid var(--border);
          border-radius:var(--radius-sm);margin-bottom:20px;font-size:13px;color:var(--text-2);">
          ${_esc(job.notes)}
        </div>` : ''}

        <div style="font-size:10.5px;font-weight:700;color:var(--text-3);text-transform:uppercase;
          letter-spacing:0.3px;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid var(--border);">
          Status History
        </div>
        ${logs}`;

    } catch {
      body.innerHTML = `<div style="text-align:center;padding:40px;color:var(--red-text);">
        Failed to load job detail.</div>`;
    }
  }

  // ── NJ callback ────────────────────────────────────────────
  function onJobCreated() {
    _myJobsLoaded = false;
    _branchLoaded = false;
    Promise.all([_loadStats(), _loadRecentJobs(), _loadDraftCount()]);
  }

  // ── Job Search ─────────────────────────────────────────────
  let _searchTimer = null;

  function onSearchInput(query) {
    clearTimeout(_searchTimer);
    const results = document.getElementById('search-results');

    if (!query.trim()) {
      results.innerHTML = `
        <div style="text-align:center;padding:48px;color:var(--text-3);">
          <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="1.5"
            style="margin-bottom:12px;opacity:0.3;">
            <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
          </svg>
          <div style="font-size:13px;">Type to search jobs from the last 7 days</div>
        </div>`;
      return;
    }

    results.innerHTML = `<div class="loading-cell"><span class="spin"></span> Searching…</div>`;
    _searchTimer = setTimeout(() => _runSearch(query.trim()), 350);
  }

  async function _runSearch(query) {
    const results = document.getElementById('search-results');
    try {
      const res  = await Auth.fetch(
        `/api/v1/jobs/?period=week&search=${encodeURIComponent(query)}&page_size=50`
      );
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      if (!jobs.length) {
        results.innerHTML = `
          <div style="text-align:center;padding:48px;color:var(--text-3);">
            <div style="font-size:24px;margin-bottom:8px;">🔍</div>
            <div style="font-size:13px;font-weight:600;color:var(--text-2);">
              No jobs found for "${_esc(query)}"
            </div>
            <div style="font-size:12px;margin-top:4px;">
              Try a different job number, title or customer name
            </div>
          </div>`;
        return;
      }

      results.innerHTML = `
        <div style="font-size:12px;color:var(--text-3);margin-bottom:12px;">
          ${jobs.length} result${jobs.length !== 1 ? 's' : ''} for
          "<strong style="color:var(--text-2);">${_esc(query)}</strong>"
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table class="p-table">
            <thead>
              <tr>
                <th>Job</th><th>Type</th><th>Status</th><th>Recorded By</th><th>Date</th>
              </tr>
            </thead>
            <tbody>
              ${jobs.map(j => `
                <tr onclick="Attendant.openDetail(${j.id})" style="cursor:pointer;">
                  <td>
                    <div class="td-job-title">${_esc(j.title || '—')}</div>
                    <div class="td-job-ref">${_esc(j.job_number || '#' + j.id)}</div>
                  </td>
                  <td>${_typeBadge(j.job_type)}</td>
                  <td>${_statusBadge(j.status)}</td>
                  <td style="font-size:12px;color:var(--text-3);">${_esc(j.intake_by_name || '—')}</td>
                  <td style="font-size:12px;color:var(--text-3);">
                    ${j.created_at ? new Date(j.created_at).toLocaleDateString('en-GB', {
                      day:'numeric', month:'short', year:'numeric'
                    }) : '—'}
                  </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      results.innerHTML = `
        <div class="loading-cell" style="color:var(--red-text);">
          Search failed. Please try again.
        </div>`;
    }
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
    return String(str).length > len ? String(str).slice(0, len) + '…' : String(str);
  }

  function _initials(name) {
    return String(name).split(' ').slice(0,2)
      .map(w => w[0]?.toUpperCase() || '').join('') || '?';
  }

  function _timeAgo(iso) {
    if (!iso) return '—';
    const diff = Date.now() - new Date(iso).getTime();
    if (diff < 60000)    return 'just now';
    if (diff < 3600000)  return `${Math.floor(diff/60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff/3600000)}h ago`;
    return new Date(iso).toLocaleDateString('en-GB', { day:'numeric', month:'short' });
  }

  function _statusLabel(s) {
    const map = {
      DRAFT:'Draft', PENDING_PAYMENT:'Pending Payment', PAID:'Paid',
      CONFIRMED:'Confirmed', IN_PROGRESS:'In Progress', READY:'Ready',
      COMPLETE:'Complete', CANCELLED:'Cancelled', HALTED:'Halted',
    };
    return map[s] || s || '—';
  }

  function _statusBadge(status) {
    const cls = {
      DRAFT:'badge-draft', PENDING_PAYMENT:'badge-pending', PAID:'badge-pending',
      IN_PROGRESS:'badge-progress', CONFIRMED:'badge-progress', READY:'badge-ready',
      COMPLETE:'badge-done', CANCELLED:'badge-cancelled', HALTED:'badge-halted',
    };
    return `<span class="badge ${cls[status]||'badge-draft'}">${_statusLabel(status)}</span>`;
  }

  function _typeBadge(type) {
    const map = { INSTANT:'badge-instant', PRODUCTION:'badge-production', DESIGN:'badge-design' };
    return `<span class="badge ${map[type]||'badge-draft'}">${_esc(type||'—')}</span>`;
  }

  function _toast(msg, type='info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className   = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ── Register Customer ──────────────────────────────────────
  function openRegisterCustomer() {
    CustomerReg.open(_onRegisterSuccess);
  }

  function _onRegisterSuccess(customer) {
    // Add to local state so NJ search finds them immediately
    _customers.push(customer);
    if (typeof State !== 'undefined') State.customers = _customers;
    // Show congratulatory flash
    _showRegistrationFlash(customer);
  }

  function _showRegistrationFlash(customer) {
    const typeLabel = {
      INDIVIDUAL : 'Individual',
      BUSINESS   : 'Business',
      INSTITUTION: 'Institution',
    }[customer.customer_type] || 'Customer';

    const name = customer.display_name || customer.full_name
      || `${customer.first_name || ''} ${customer.last_name || ''}`.trim()
      || 'New Customer';

    const overlay = document.createElement('div');
    overlay.id = 'reg-flash-overlay';
    overlay.style.cssText = `
      position:fixed;inset:0;z-index:3000;
      background:rgba(0,0,0,0.75);
      display:flex;align-items:center;justify-content:center;
      font-family:'DM Sans',sans-serif;
      animation:fadeIn 0.25s ease;`;

    overlay.innerHTML = `
      <div style="
        background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);width:100%;max-width:420px;
        padding:40px 32px;text-align:center;
        box-shadow:0 24px 64px rgba(0,0,0,0.4);
        animation:slideUp 0.3s ease;">

        <!-- Flag icon -->
        <div style="font-size:48px;margin-bottom:16px;line-height:1;">🎉</div>

        <!-- Headline -->
        <div style="font-family:'Syne',sans-serif;font-size:22px;font-weight:800;
          color:var(--text);letter-spacing:-0.3px;margin-bottom:8px;">
          Customer Registered!
        </div>

        <!-- Name + type -->
        <div style="font-size:16px;font-weight:700;color:var(--text);
          margin-bottom:6px;">${_esc(name)}</div>
        <div style="display:inline-block;padding:3px 12px;border-radius:20px;
          font-size:12px;font-weight:700;background:var(--green-bg);
          color:var(--green-text);border:1px solid var(--green-border);
          margin-bottom:20px;">${_esc(typeLabel)}</div>

        <!-- Subtext -->
        <div style="font-size:13px;color:var(--text-3);margin-bottom:28px;
          line-height:1.5;">
          Added to the system. They'll be searchable from their next visit.
        </div>

        <!-- Countdown bar -->
        <div style="height:3px;background:var(--border);border-radius:2px;
          overflow:hidden;margin-bottom:16px;">
          <div id="reg-flash-bar"
            style="height:100%;width:100%;background:var(--green-text);
              border-radius:2px;transition:width linear;">
          </div>
        </div>

        <!-- Dismiss -->
        <button onclick="document.getElementById('reg-flash-overlay').remove()"
          style="padding:9px 24px;background:none;border:1px solid var(--border);
            border-radius:var(--radius-sm);font-size:13px;font-weight:600;
            cursor:pointer;color:var(--text-2);font-family:'DM Sans',sans-serif;">
          Dismiss
        </button>
      </div>`;

    document.body.appendChild(overlay);

    // Animate countdown bar and auto-dismiss after 4 seconds
    const bar      = document.getElementById('reg-flash-bar');
    const duration = 4000;
    const start    = performance.now();

    function tick(now) {
      const elapsed = now - start;
      const pct     = Math.max(0, 100 - (elapsed / duration * 100));
      if (bar) bar.style.width = pct + '%';
      if (elapsed < duration) {
        requestAnimationFrame(tick);
      } else {
        overlay.remove();
      }
    }
    requestAnimationFrame(tick);
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    init,
    switchPane,
    toggleMyJobs,
    openDetail,
    openConvo,
    sendReply,
    switchInboxChannel,
    resumeDraft,
    discardDraft,
    onJobCreated,
    onSearchInput,
    openRegisterCustomer,
  };
})();

document.addEventListener('DOMContentLoaded', Attendant.init);

// ── State — shared with NJ controller ─────────────────────
const State = {
  branchId  : null,
  services  : [],
  customers : [],
  page      : 1,
};

// ── Notifications ──────────────────────────────────────────
const AtNotifications = (() => {
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
          onclick="AtNotifications.markRead(${n.id}, this)">
          <span class="notif-dot"></span>
          <span class="notif-msg">${_esc(n.message)}</span>
          <span class="notif-time">${n.time_ago || ''}</span>
        </div>`).join('');
    } catch {
      list.innerHTML = '<div class="notif-empty">Could not load notifications.</div>';
    }
  }

  function _esc(str) {
    return String(str ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  async function loadCount() {
    try {
      const res   = await Auth.fetch('/api/v1/notifications/unread-count/');
      if (!res.ok) return;
      const data  = await res.json();
      const count = data.count || 0;
      const badge = document.getElementById('at-notif-badge');
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

  async function markRead(id, el) {
    try {
      await Auth.fetch(`/api/v1/notifications/${id}/read/`, { method: 'POST' });
      el?.classList.remove('unread');
      el?.classList.add('read');
      await loadCount();
    } catch { /* silent */ }
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

  function startPolling(ms = 30000) {
    loadCount();
    setInterval(loadCount, ms);
  }

  return { toggle, close, markRead, markAllRead, loadCount, startPolling };
})();