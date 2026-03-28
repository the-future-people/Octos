/**
 * Octos — Attendant Portal
 *
 * Panes: Overview, My Jobs, Branch Jobs, Drafts, Inbox, Services
 * No financial data — attendant creates jobs, cashier handles payment
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
    await Promise.all([
      _loadContext(),
      _loadServicesAndCustomers(),
    ]);
    await _loadSheet();
    await Promise.all([
      _loadStats(),
      _loadRecentJobs(),
      _loadDraftCount(),
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

// ── Stats ──────────────────────────────────────────────────
  async function _loadStats() {
    if (!_sheetId) return;
    try {
      const res  = await Auth.fetch(
        `/api/v1/jobs/?daily_sheet=${_sheetId}&intake_by=me&page_size=200`
      );
      if (!res.ok) return;
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      const total     = jobs.length;
      const pending   = jobs.filter(j => j.status === 'PENDING_PAYMENT').length;
      const confirmed = jobs.filter(j =>
        j.status === 'COMPLETE' || j.status === 'PAID' || j.status === 'CONFIRMED'
      ).length;
      const value     = jobs.reduce(
        (sum, j) => sum + parseFloat(j.total_cost || 0), 0
      );
      const rate      = total > 0 ? Math.round((confirmed / total) * 100) : null;

      // Strip cards
      _set('strip-recorded',  total);
      _set('strip-value',     'GHS ' + value.toLocaleString('en-GH', {
        minimumFractionDigits: 2, maximumFractionDigits: 2
      }));
      _set('strip-confirmed', confirmed);
      _set('strip-rate',      rate !== null ? rate + '%' : '—');
      _set('strip-rate-sub',  rate !== null
        ? `${confirmed} of ${total} job${total !== 1 ? 's' : ''}`
        : 'no jobs yet'
      );

      // Overview stat cards
      _set('stat-my-total',    total);
      _set('stat-my-pending',  pending);
      _set('stat-my-complete', confirmed);

      const badge = document.getElementById('sidebar-badge-myjobs');
      if (badge) {
        badge.textContent   = total;
        badge.style.display = total > 0 ? 'flex' : 'none';
      }
    } catch { /* silent */ }
  }

  async function _loadDraftCount() {
    try {
      const res  = await Auth.fetch('/api/v1/jobs/drafts/');
      if (!res.ok) return;
      const data   = await res.json();
      const drafts = Array.isArray(data) ? data : (data.results || []);

      _set('stat-my-drafts', drafts.length);

      const badge = document.getElementById('sidebar-badge-drafts');
      if (badge) {
        badge.textContent   = drafts.length;
        badge.style.display = drafts.length > 0 ? 'flex' : 'none';
      }
    } catch { /* silent */ }
  }

  // ── Recent jobs (overview) ─────────────────────────────────
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

    // If expanding, auto-navigate to Today's Jobs
    if (_myJobsExpanded) {
      switchPane('my-jobs-today', "Today's Jobs");
    }
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
              <th>Job</th>
              <th>Type</th>
              <th>Status</th>
              <th>Customer</th>
              <th>Created</th>
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

  // ── Branch Jobs pane (status only — no cost/customer) ──────
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
              <th>Job Ref</th>
              <th>Title</th>
              <th>Type</th>
              <th>Status</th>
              <th>Created</th>
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
      <div class="section-head">
        <span class="section-title">Saved Drafts</span>
      </div>
      <div id="drafts-list">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

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
              fill="none" stroke="currentColor" stroke-width="1.5" style="margin-bottom:12px;opacity:0.4;">
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
              GHS ${parseFloat(d.estimated_cost || 0).toLocaleString('en-GH', { minimumFractionDigits: 2 })} ·
              Expires ${_timeAgo(d.expires_at)}
            </div>
          </div>
          <div style="display:flex;gap:8px;">
            <button onclick="Attendant.resumeDraft(${d.id})"
              style="padding:7px 16px;background:var(--text);color:#fff;border:none;
                     border-radius:var(--radius-sm);font-size:12px;font-weight:700;
                     cursor:pointer;font-family:inherit;">
              Resume
            </button>
            <button onclick="Attendant.discardDraft(${d.id})"
              style="padding:7px 12px;background:none;border:1px solid var(--border);
                     border-radius:var(--radius-sm);font-size:12px;color:var(--text-3);
                     cursor:pointer;font-family:inherit;">
              Discard
            </button>
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

      // Restore cart in NJ controller
      NJ.open();
      NJ.setType('INSTANT');

      // Wait for UI to render then populate cart
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
      <div class="section-head">
        <span class="section-title">Inbox</span>
      </div>
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
        _set('meta-services', _services.length);
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
                <th>Job</th>
                <th>Type</th>
                <th>Status</th>
                <th>Recorded By</th>
                <th>Date</th>
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
                  <td style="font-size:12px;color:var(--text-3);">
                    ${_esc(j.intake_by_name || '—')}
                  </td>
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

  function _esc(str) {
    return String(str ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  return { toggle, close, markRead, markAllRead, loadCount, startPolling };
})();