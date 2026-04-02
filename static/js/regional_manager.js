/**
 * Octos — Regional Manager Portal
 *
 * Panes: Overview (branch health grid), Monthly Close, Branch Detail
 * Data source: /api/v1/organization/regional/dashboard/
 */

'use strict';

const RM = (() => {

  // ── State ──────────────────────────────────────────────────
  let _data          = null;   // last dashboard response
  let _alertsOnly    = false;
  let _closeLoaded   = false;
  let _refreshTimer  = null;

  // ── Boot ───────────────────────────────────────────────────
  async function init() {
    await Auth.guard(['REGIONAL_MANAGER', 'BELT_MANAGER', 'SUPER_ADMIN']);

    _set('rm-meta-date', new Date().toLocaleDateString('en-GB', {
      weekday: 'short', day: 'numeric', month: 'short', year: 'numeric',
    }));

    await _loadContext();
    await _loadDashboard();

    // Auto-refresh every 5 minutes
    _refreshTimer = setInterval(_loadDashboard, 5 * 60 * 1000);

    RMNotifications.startPolling();
  }

  // ── Context ────────────────────────────────────────────────
  async function _loadContext() {
    try {
      const res  = await Auth.fetch('/api/v1/accounts/me/');
      if (!res?.ok) return;
      const user = await res.json();

      const fullName = user.full_name || user.email || '—';
      const initials = fullName.split(' ').slice(0, 2)
        .map(w => w[0]?.toUpperCase() || '').join('');

      _set('rm-user-name',     fullName);
      _set('rm-user-initials', initials);

      if (user.region_detail) {
        const r = user.region_detail;
        _set('rm-region-name', r.name || '—');
        _set('rm-meta-region', r.name || '—');
        _set('rm-meta-belt',   r.belt_name || '—');
      }
    } catch { /* silent */ }
  }

  // ── Dashboard load ─────────────────────────────────────────
  async function _loadDashboard() {
    try {
      const res = await Auth.fetch('/api/v1/organization/regional/dashboard/');
      if (!res?.ok) {
        _toast('Could not load dashboard data.', 'error');
        return;
      }
      _data = await res.json();
      _renderDashboard(_data);
      _updateRefreshLabel();
    } catch {
      _toast('Network error refreshing dashboard.', 'error');
    }
  }

  function refresh() {
    const btn = document.getElementById('rm-refresh-btn');
    if (btn) btn.style.opacity = '0.4';
    _loadDashboard().finally(() => {
      if (btn) btn.style.opacity = '1';
    });
  }

  function _updateRefreshLabel() {
    const el = document.getElementById('rm-refresh-label');
    if (el) {
      const now = new Date().toLocaleTimeString('en-GH', {
        hour: '2-digit', minute: '2-digit',
      });
      el.textContent = `Updated ${now}`;
    }
  }

  // ── Render dashboard ───────────────────────────────────────
  function _renderDashboard(data) {
    _renderSummaryStrip(data.summary);
    _renderInfoStrip(data);
    _renderSidebarBranches(data.branches);
    _renderBranchGrid(data.branches);
  }

  // ── Summary strip ──────────────────────────────────────────
  function _renderSummaryStrip(s) {
    _set('sum-total',    s.total_jobs);
    _set('sum-complete', s.total_complete);
    _set('sum-pending',  s.total_pending);
    _set('sum-alerts',   s.total_alerts);
    _set('sum-rate',     s.completion_rate + '% completion rate');

    // Alerts card — accent red only if there are alerts
    const alertCard = document.getElementById('sum-alerts-card');
    if (alertCard) {
      alertCard.classList.toggle('rm-summary-red-active', s.total_alerts > 0);
    }
  }

  // ── Info strip ─────────────────────────────────────────────
  function _renderInfoStrip(data) {
    _set('rm-meta-branches', data.summary.branch_count + ' active');
    _set('rm-meta-alerts',
      data.summary.total_alerts > 0
        ? data.summary.total_alerts + ' need attention'
        : 'All clear ✓'
    );

    // Sidebar alert badge
    const badge = document.getElementById('sidebar-alert-count');
    if (badge) {
      badge.textContent   = data.summary.total_alerts;
      badge.style.display = data.summary.total_alerts > 0 ? 'flex' : 'none';
    }
  }

  // ── Sidebar branch list ────────────────────────────────────
  function _renderSidebarBranches(branches) {
    const el = document.getElementById('sidebar-branch-list');
    if (!el) return;

    el.innerHTML = branches.map(b => {
      const hasAlerts = b.alerts.length > 0;
      return `
        <div class="sidebar-item" data-pane="branch-detail"
          onclick="RM.openBranchDetail(${b.id})"
          style="position:relative;">
          <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="2"
            style="flex-shrink:0;opacity:0.5;">
            <path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>
            <polyline points="9 22 9 12 15 12 15 22"/>
          </svg>
          <span class="sidebar-label" style="font-size:12px;">${_esc(b.name)}</span>
          ${hasAlerts
            ? `<span style="width:6px;height:6px;border-radius:50%;background:var(--red-text);
                flex-shrink:0;margin-left:auto;"></span>`
            : ''}
        </div>`;
    }).join('');
  }

  // ── Branch grid ────────────────────────────────────────────
  function _renderBranchGrid(branches) {
    const grid = document.getElementById('rm-branch-grid');
    if (!grid) return;

    const visible = _alertsOnly
      ? branches.filter(b => b.alerts.length > 0)
      : branches;

    // Update filter label
    const filterLabel = document.getElementById('rm-filter-label');
    if (filterLabel) {
      filterLabel.textContent = _alertsOnly ? 'Show all branches' : 'Show alerts only';
    }

    if (!visible.length) {
      grid.innerHTML = `
        <div style="grid-column:1/-1;text-align:center;padding:48px;color:var(--text-3);">
          <div style="font-size:32px;margin-bottom:12px;">✓</div>
          <div style="font-size:14px;font-weight:600;color:var(--text-2);">All clear</div>
          <div style="font-size:13px;margin-top:4px;">No branches with alerts right now.</div>
        </div>`;
      return;
    }

    grid.innerHTML = visible.map(b => _renderBranchCard(b)).join('');
  }

  function _renderBranchCard(b) {
    const sheetOpen   = b.sheet_status === 'OPEN';
    const sheetClosed = b.sheet_status === 'CLOSED';
    const noSheet     = !b.sheet_status;
    const hasAlerts   = b.alerts.length > 0;

    const sheetPill = noSheet
      ? `<span class="rm-pill rm-pill-muted">No sheet</span>`
      : sheetOpen
        ? `<span class="rm-pill rm-pill-green">Sheet open</span>`
        : `<span class="rm-pill rm-pill-muted">Sheet closed</span>`;

    const hqBadge = b.is_hq
      ? `<span class="rm-pill rm-pill-purple" style="margin-left:4px;">HQ</span>`
      : b.is_regional_hq
        ? `<span class="rm-pill rm-pill-blue" style="margin-left:4px;">Regional HQ</span>`
        : '';

    // Sparkline — 7-day trend
    const sparkline = _sparkline(b.trend);

    // Alerts
    const alertsHtml = b.alerts.map(a => `
      <div class="rm-alert-row rm-alert-${a.level}">
        <span class="rm-alert-dot"></span>
        <span class="rm-alert-msg">${_esc(a.message)}</span>
      </div>`).join('');

    return `
      <div class="rm-branch-card ${hasAlerts ? 'rm-branch-card-alert' : ''}"
        onclick="RM.openBranchDetail(${b.id})" style="cursor:pointer;">

        <div class="rm-card-head">
          <div>
            <div class="rm-card-name">${_esc(b.name)} ${hqBadge}</div>
            <div class="rm-card-code">${_esc(b.code)}</div>
          </div>
          <div style="display:flex;flex-direction:column;align-items:flex-end;gap:4px;">
            ${sheetPill}
            ${b.staff_on_shift > 0
              ? `<span style="font-size:10px;color:var(--text-3);">${b.staff_on_shift} staff active</span>`
              : `<span style="font-size:10px;color:var(--text-3);">No staff clocked in</span>`}
          </div>
        </div>

        <div class="rm-card-stats">
          <div class="rm-card-stat">
            <div class="rm-card-stat-val">${b.jobs.total}</div>
            <div class="rm-card-stat-label">Jobs</div>
          </div>
          <div class="rm-card-stat">
            <div class="rm-card-stat-val" style="color:#3B6D11;">${b.jobs.complete}</div>
            <div class="rm-card-stat-label">Done</div>
          </div>
          <div class="rm-card-stat">
            <div class="rm-card-stat-val" style="color:#854F0B;">${b.jobs.pending}</div>
            <div class="rm-card-stat-label">Pending</div>
          </div>
          <div class="rm-card-stat">
            <div class="rm-card-stat-val">${b.jobs.rate}%</div>
            <div class="rm-card-stat-label">Rate</div>
          </div>
        </div>

        <!-- 7-day sparkline -->
        <div class="rm-sparkline-wrap">
          ${sparkline}
          <span class="rm-sparkline-label">7 days</span>
        </div>

        <!-- Alerts -->
        ${alertsHtml
          ? `<div class="rm-alerts-block">${alertsHtml}</div>`
          : ''}

      </div>`;
  }

  // ── Sparkline SVG ──────────────────────────────────────────
  function _sparkline(trend) {
    const counts = trend.map(d => d.count);
    const max    = Math.max(...counts, 1);
    const w      = 120;
    const h      = 28;
    const step   = w / (counts.length - 1);

    const points = counts.map((c, i) => {
      const x = Math.round(i * step);
      const y = Math.round(h - (c / max) * h);
      return `${x},${y}`;
    }).join(' ');

    return `
      <svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"
        xmlns="http://www.w3.org/2000/svg" style="overflow:visible;">
        <polyline
          points="${points}"
          fill="none"
          stroke="#378ADD"
          stroke-width="1.5"
          stroke-linejoin="round"
          stroke-linecap="round"/>
        ${counts.map((c, i) => {
          const x = Math.round(i * step);
          const y = Math.round(h - (c / max) * h);
          const isToday = trend[i]?.is_today ?? (i === counts.length - 1);
          return isToday
            ? `<circle cx="${x}" cy="${y}" r="3" fill="#378ADD"/>`
            : '';
        }).join('')}
      </svg>`;
  }

  // ── Branch detail pane ─────────────────────────────────────
  async function openBranchDetail(branchId) {
    switchPane('branch-detail', 'Branch Detail');

    const body = document.getElementById('rm-branch-detail-body');
    if (!body) return;

    // Find branch in cached data first
    const branch = _data?.branches?.find(b => b.id === branchId);
    if (branch) {
      body.innerHTML = _renderBranchDetailHTML(branch);
      return;
    }

    body.innerHTML = `<div class="loading-cell"><span class="spin"></span> Loading…</div>`;
    body.innerHTML = `<div style="padding:32px;color:var(--text-3);">Branch not found.</div>`;
  }

  function _renderBranchDetailHTML(b) {
    const trendRows = b.trend.map(d => `
      <div style="display:flex;align-items:center;gap:10px;padding:5px 0;
        border-bottom:0.5px solid var(--border);">
        <span style="font-size:12px;color:var(--text-3);width:80px;flex-shrink:0;">
          ${d.day} ${d.date.slice(5)}
        </span>
        <div style="flex:1;height:6px;background:var(--bg);border-radius:3px;overflow:hidden;">
          <div style="height:100%;background:#378ADD;border-radius:3px;
            width:${b.trend.reduce((m,x) => Math.max(m,x.count),1) > 0
              ? Math.round(d.count / b.trend.reduce((m,x) => Math.max(m,x.count),1) * 100)
              : 0}%;"></div>
        </div>
        <span style="font-size:12px;font-weight:600;color:var(--text);width:24px;text-align:right;">
          ${d.count}
        </span>
      </div>`).join('');

    const alertsHtml = b.alerts.length
      ? b.alerts.map(a => `
          <div class="rm-alert-row rm-alert-${a.level}" style="margin-bottom:6px;">
            <span class="rm-alert-dot"></span>
            <span class="rm-alert-msg">${_esc(a.message)}</span>
          </div>`).join('')
      : `<div style="font-size:13px;color:var(--text-3);">No active alerts.</div>`;

    return `
      <div class="section-head">
        <span class="section-title">${_esc(b.name)}</span>
        <span class="section-link" onclick="RM.switchPane('overview','Overview')" style="cursor:pointer;">
          ← Back to overview
        </span>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:20px;">

        <!-- Stats -->
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:16px 18px;">
          <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;margin-bottom:12px;">Today's jobs</div>
          <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
            ${[
              ['Total',   b.jobs.total,    ''],
              ['Done',    b.jobs.complete, '#3B6D11'],
              ['Pending', b.jobs.pending,  '#854F0B'],
              ['Rate',    b.jobs.rate+'%', ''],
            ].map(([label, val, color]) => `
              <div style="text-align:center;">
                <div style="font-size:22px;font-weight:600;color:${color||'var(--text)'};">${val}</div>
                <div style="font-size:10px;color:var(--text-3);margin-top:2px;">${label}</div>
              </div>`).join('')}
          </div>
          <div style="margin-top:12px;padding-top:12px;border-top:1px solid var(--border);
            font-size:12px;color:var(--text-3);">
            ${b.staff_on_shift} staff clocked in ·
            Sheet: <strong style="color:var(--text);">${b.sheet_status || 'None'}</strong>
          </div>
        </div>

        <!-- Alerts -->
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:16px 18px;">
          <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.5px;margin-bottom:12px;">Active alerts</div>
          ${alertsHtml}
        </div>

      </div>

      <!-- 7-day trend -->
      <div style="background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);padding:16px 18px;">
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;
          letter-spacing:0.5px;margin-bottom:12px;">7-day job trend</div>
        ${trendRows}
      </div>`;
  }

  // ── Monthly close pane ─────────────────────────────────────
 async function _loadMonthlyClosePane() {
    _closeLoaded = true;
    const el = document.getElementById('rm-close-list');
    if (!el) return;
    if (!_data) await _loadDashboard();

    // Ensure dashboard data is loaded — needed for branch ID filtering
    if (!_data) await _loadDashboard();

    try {
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/pending/');
      if (!res?.ok) throw new Error();
      const data = await res.json();
      const list = Array.isArray(data) ? data : (data.results || []);

      // Filter to branches in this region only
      const regionBranchCodes = new Set((_data?.branches || []).map(b => b.code));
      const regional = regionBranchCodes.size > 0
        ? list.filter(c => regionBranchCodes.has(c.branch_code))
        : list;

      // Update sidebar badge
      const badge = document.getElementById('sidebar-badge-close');
      if (badge) {
        badge.textContent   = regional.length;
        badge.style.display = regional.length > 0 ? 'flex' : 'none';
      }

      if (!regional.length) {
        el.innerHTML = `
          <div style="text-align:center;padding:48px;color:var(--text-3);">
            <div style="font-size:32px;margin-bottom:12px;">✓</div>
            <div style="font-size:14px;font-weight:600;color:var(--text-2);">All caught up</div>
            <div style="font-size:13px;margin-top:4px;">No monthly closes pending endorsement.</div>
          </div>`;
        return;
      }

      el.innerHTML = regional.map(c => `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);padding:16px 20px;margin-bottom:10px;
          display:flex;align-items:center;justify-content:space-between;gap:16px;
          cursor:pointer;transition:border-color 0.15s;"
          onclick="RM.openCloseReview(${c.id})"
          onmouseover="this.style.borderColor='var(--border-dark)'"
          onmouseout="this.style.borderColor='var(--border)'">
          <div>
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">
              ${_esc(c.branch_name || c.branch || 'Branch')} — ${_esc(c.month_name || '—')} ${c.year || ''}
            </div>
            <div style="font-size:12px;color:var(--text-3);">
              Submitted by ${_esc(c.submitted_by || '—')} ·
              ${c.submitted_at ? _timeAgo(c.submitted_at) : '—'} ·
              GHS ${parseFloat(c.total_collected || 0).toLocaleString('en-GH', {minimumFractionDigits:2})} collected ·
              ${c.total_jobs || 0} jobs
            </div>
          </div>
          <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;">
            <span style="font-size:11px;color:var(--text-3);">Click to review →</span>
          </div>
        </div>`).join('');

    } catch (e) {
      console.error('Monthly close pane error:', e);
      el.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">
        Could not load monthly closes.</div>`;
    }
  }
  
async function endorseClose(closeId) {
    // Compile all section notes
    const sections = ['revenue','jobs','weekly','services','staff','bmnotes','overall'];
    const notes = sections
      .map(s => {
        const val = document.getElementById(`note-${s}`)?.value?.trim();
        if (!val) return null;
        const label = {
          revenue:'Revenue', jobs:'Jobs', weekly:'Weekly Breakdown',
          services:'Top Services', staff:'Staff Performance',
          bmnotes:'BM Notes', overall:'Overall'
        }[s];
        return `[${label}] ${val}`;
      })
      .filter(Boolean)
      .join('\n\n');
 
    const btn = document.querySelector('#close-review-overlay button[onclick*="endorseClose"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Endorsing…'; }
 
    try {
      const res = await Auth.fetch(`/api/v1/finance/monthly-close/${closeId}/endorse/`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ belt_notes: notes }),
      });
      if (res?.ok) {
        document.getElementById('close-review-overlay')?.remove();
        _toast('Monthly close endorsed and filed.', 'success');
        _closeLoaded = false;
        _loadMonthlyClosePane();
      } else {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Could not endorse.', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Endorse & File'; }
      }
    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Endorse & File'; }
    }
  }
 

async function rejectClose(closeId) {
    // Compile notes as the rejection reason
    const sections = ['revenue','jobs','weekly','services','staff','bmnotes','overall'];
    const notes = sections
      .map(s => {
        const val = document.getElementById(`note-${s}`)?.value?.trim();
        if (!val) return null;
        const label = {
          revenue:'Revenue', jobs:'Jobs', weekly:'Weekly Breakdown',
          services:'Top Services', staff:'Staff Performance',
          bmnotes:'BM Notes', overall:'Overall'
        }[s];
        return `[${label}] ${val}`;
      })
      .filter(Boolean)
      .join('\n\n');
 
    if (!notes) {
      _toast('Please add at least one objection note before rejecting.', 'error');
      return;
    }
 
    const btn = document.querySelector('#close-review-overlay button[onclick*="rejectClose"]');
    if (btn) { btn.disabled = true; btn.textContent = 'Rejecting…'; }
 
    try {
      const res = await Auth.fetch(`/api/v1/finance/monthly-close/${closeId}/reject/`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ reason: notes }),
      });
      if (res?.ok) {
        document.getElementById('close-review-overlay')?.remove();
        _toast('Monthly close rejected. BM has been notified.', 'info');
        _closeLoaded = false;
        _loadMonthlyClosePane();
      } else {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Could not reject.', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Reject'; }
      }
    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Reject'; }
    }
  }

  // ── Pane switching ─────────────────────────────────────────
  function switchPane(paneId, label) {
    document.querySelectorAll('.sidebar-item').forEach(item => {
      item.classList.toggle('active', item.dataset.pane === paneId);
    });
    document.querySelectorAll('.pane').forEach(p => p.classList.remove('active'));
    const target = document.getElementById(`pane-${paneId}`);
    if (target) target.classList.add('active');
    _set('breadcrumb-current', label);

    if (paneId === 'monthly-close' && !_closeLoaded) _loadMonthlyClosePane();
  }

  // ── Alerts-only filter toggle ──────────────────────────────
  function toggleAlertsOnly() {
    _alertsOnly = !_alertsOnly;
    if (_data) _renderBranchGrid(_data.branches);
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

  function _timeAgo(iso) {
    if (!iso) return '—';
    const diff = Date.now() - new Date(iso).getTime();
    if (diff < 60000)    return 'just now';
    if (diff < 3600000)  return `${Math.floor(diff/60000)}m ago`;
    if (diff < 86400000) return `${Math.floor(diff/3600000)}h ago`;
    return new Date(iso).toLocaleDateString('en-GB', { day:'numeric', month:'short' });
  }

  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className   = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

    async function openCloseReview(closeId) {
    // Fetch full detail
    const overlay = document.createElement('div');
    overlay.id    = 'close-review-overlay';
    overlay.style.cssText = `
      position:fixed;inset:0;z-index:9000;
      background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);
      display:flex;align-items:flex-start;justify-content:center;
      padding:20px;overflow-y:auto;font-family:'DM Sans',sans-serif;`;
 
    overlay.innerHTML = `
      <div style="background:var(--panel);border:1px solid var(--border);
        border-radius:var(--radius);width:100%;max-width:780px;
        box-shadow:0 24px 64px rgba(0,0,0,0.2);margin:auto;">
        <div style="padding:24px 28px;border-bottom:1px solid var(--border);
          display:flex;align-items:center;justify-content:space-between;">
          <div>
            <div style="font-family:'Syne',sans-serif;font-size:20px;
              font-weight:800;color:var(--text);">Monthly Close Review</div>
            <div style="font-size:12px;color:var(--text-3);margin-top:3px;"
              id="review-subtitle">Loading…</div>
          </div>
          <button onclick="document.getElementById('close-review-overlay').remove()"
            style="width:32px;height:32px;border-radius:50%;border:1px solid var(--border);
              background:var(--bg);display:flex;align-items:center;justify-content:center;
              cursor:pointer;font-size:18px;color:var(--text-2);">×</button>
        </div>
        <div id="review-body" style="padding:28px;">
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <span class="spin"></span> Loading document…
          </div>
        </div>
      </div>`;
 
    document.body.appendChild(overlay);
 
    try {
      const res  = await Auth.fetch(`/api/v1/finance/monthly-close/${closeId}/`);
      if (!res?.ok) throw new Error();
      const c    = await res.json();
      const snap = c.summary_snapshot || {};
 
      document.getElementById('review-subtitle').textContent =
        `${c.branch} — ${c.month_name} ${c.year} · Submitted by ${c.submitted_by} · ${c.submitted_at ? _timeAgo(c.submitted_at) : '—'}`;
 
      const fmt  = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH', {minimumFractionDigits:2})}`;
      const rev  = snap.revenue || {};
      const jobs = snap.jobs    || {};
 
      const sectionHtml = (id, title, content) => `
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);margin-bottom:16px;overflow:hidden;">
          <div style="padding:14px 18px;background:var(--bg);
            border-bottom:1px solid var(--border);
            display:flex;align-items:center;justify-content:space-between;">
            <span style="font-size:12px;font-weight:700;color:var(--text);
              text-transform:uppercase;letter-spacing:0.5px;">${title}</span>
          </div>
          <div style="padding:16px 18px;">${content}</div>
          <div style="padding:0 18px 16px;">
            <div style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">
              Add Note / Raise Objection
            </div>
            <textarea id="note-${id}" rows="2"
              placeholder="Optional — flag a concern or ask a question about this section…"
              style="width:100%;padding:9px 12px;border:1px solid var(--border);
                border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
                font-size:12px;resize:vertical;box-sizing:border-box;
                font-family:'DM Sans',sans-serif;"></textarea>
          </div>
        </div>`;
 
      const row = (label, val, mono=false) => `
        <div style="display:flex;justify-content:space-between;padding:7px 0;
          border-bottom:1px solid var(--border);">
          <span style="font-size:13px;color:var(--text-3);">${label}</span>
          <span style="font-size:13px;font-weight:600;color:var(--text);
            ${mono ? "font-family:'JetBrains Mono',monospace;" : ''}">${val}</span>
        </div>`;
 
      // ── Section 1: Revenue ────────────────────────────────
      const revenueContent = `
        ${row('Total Collected', fmt(rev.total_collected), true)}
        ${row('Cash', `${fmt(rev.total_cash)} (${rev.cash_pct||0}%)`)}
        ${row('Mobile Money', `${fmt(rev.total_momo)} (${rev.momo_pct||0}%)`)}
        ${row('POS', `${fmt(rev.total_pos)} (${rev.pos_pct||0}%)`)}
        ${row('Credit Issued', fmt(rev.total_credit_issued))}
        ${row('Credit Settled', fmt(rev.total_credit_settled))}
        ${row('Petty Cash Out', fmt(rev.total_petty_cash_out))}`;
 
      // ── Section 2: Jobs ───────────────────────────────────
      const jobsContent = `
        ${row('Total Jobs', jobs.total || 0)}
        ${row('Completed', jobs.complete || 0)}
        ${row('Cancelled', jobs.cancelled || 0)}
        ${row('Completion Rate', `${jobs.completion_rate || 0}%`)}
        ${row('Pending (carry forward)', jobs.pending || 0)}`;
 
      // ── Section 3: Weekly Breakdown ───────────────────────
      const weeks = snap.weekly_breakdown || [];
      const weeklyContent = weeks.length ? weeks.map(w => `
        <div style="padding:10px 0;border-bottom:1px solid var(--border);">
          <div style="display:flex;justify-content:space-between;margin-bottom:4px;">
            <span style="font-size:13px;font-weight:600;color:var(--text);">
              Week ${w.week_number}
              <span style="font-size:11px;color:var(--text-3);font-weight:400;">
                (${w.date_from} – ${w.date_to})
              </span>
            </span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:13px;
              font-weight:700;color:var(--text);">${fmt(w.total)}</span>
          </div>
          <div style="display:flex;gap:16px;">
            <span style="font-size:11px;color:var(--cash-text);">Cash: ${fmt(w.cash)}</span>
            <span style="font-size:11px;color:var(--momo-text);">MoMo: ${fmt(w.momo)}</span>
            <span style="font-size:11px;color:var(--pos-text);">POS: ${fmt(w.pos)}</span>
            <span style="font-size:11px;color:var(--text-3);">${w.jobs} jobs</span>
            <span style="font-size:11px;font-weight:700;
              color:${w.status==='LOCKED'?'var(--green-text)':'var(--amber-text)'};">
              ${w.status}
            </span>
          </div>
        </div>`).join('') : '<div style="color:var(--text-3);font-size:13px;">No weekly data.</div>';
 
      // ── Section 4: Top Services ───────────────────────────
      const services = snap.top_services || [];
      const servicesContent = services.length ? `
        <table style="width:100%;border-collapse:collapse;">
          ${services.map((s,i) => `
            <tr style="border-bottom:1px solid var(--border);">
              <td style="padding:7px 0;font-size:13px;color:var(--text-3);">${i+1}.</td>
              <td style="padding:7px 8px;font-size:13px;color:var(--text);">${_esc(s.service)}</td>
              <td style="padding:7px 0;font-size:12px;color:var(--text-3);text-align:right;">
                ${s.job_count} jobs
              </td>
              <td style="padding:7px 0;font-family:'JetBrains Mono',monospace;
                font-size:13px;font-weight:700;color:var(--text);text-align:right;
                padding-left:16px;">${fmt(s.revenue)}</td>
            </tr>`).join('')}
        </table>` : '<div style="color:var(--text-3);font-size:13px;">No service data.</div>';
 
      // ── Section 5: Staff Performance ──────────────────────
      const staff = snap.staff_performance || [];
      const staffContent = staff.length ? `
        <table style="width:100%;border-collapse:collapse;">
          <thead>
            <tr style="background:var(--bg);">
              <th style="padding:8px;text-align:left;font-size:10.5px;font-weight:700;
                color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;
                border-bottom:2px solid var(--border);">Staff Member</th>
              <th style="padding:8px;text-align:right;font-size:10.5px;font-weight:700;
                color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;
                border-bottom:2px solid var(--border);">Jobs</th>
              <th style="padding:8px;text-align:right;font-size:10.5px;font-weight:700;
                color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;
                border-bottom:2px solid var(--border);">Revenue</th>
            </tr>
          </thead>
          <tbody>
            ${staff.map(s => {
              const name = s.name ||
                `${s.intake_by__first_name||''} ${s.intake_by__last_name||''}`.trim() || '—';
              return `
                <tr style="border-bottom:1px solid var(--border);">
                  <td style="padding:10px 8px;font-size:13px;color:var(--text);">${_esc(name)}</td>
                  <td style="padding:10px 8px;font-size:13px;color:var(--text-2);
                    text-align:right;">${s.jobs_recorded}</td>
                  <td style="padding:10px 8px;font-family:'JetBrains Mono',monospace;
                    font-size:13px;font-weight:700;color:var(--text);
                    text-align:right;">${fmt(s.revenue)}</td>
                </tr>`;
            }).join('')}
          </tbody>
        </table>` : '<div style="color:var(--text-3);font-size:13px;">No staff data.</div>';
 
      // ── Section 6: BM Notes ───────────────────────────────
      const bmNotesContent = `
        <div style="font-size:13px;color:var(--text-2);line-height:1.6;
          min-height:40px;white-space:pre-wrap;">
          ${_esc(c.bm_notes || '—')}
        </div>`;
 
      // ── Assemble body ─────────────────────────────────────
      document.getElementById('review-body').innerHTML = `
 
        ${sectionHtml('revenue',  'Revenue Summary',    revenueContent)}
        ${sectionHtml('jobs',     'Jobs Summary',       jobsContent)}
        ${sectionHtml('weekly',   'Weekly Breakdown',   weeklyContent)}
        ${sectionHtml('services', 'Top Services',       servicesContent)}
        ${sectionHtml('staff',    'Staff Performance',  staffContent)}
        ${sectionHtml('bmnotes',  'Branch Manager Notes', bmNotesContent)}
 
        <!-- Overall RM notes -->
        <div style="margin-bottom:20px;">
          <div style="font-size:12px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">
            Overall RM Notes (Optional)
          </div>
          <textarea id="note-overall" rows="3"
            placeholder="Add overall comments or observations before endorsing or rejecting…"
            style="width:100%;padding:10px 14px;border:1px solid var(--border);
              border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
              font-size:13px;resize:vertical;box-sizing:border-box;
              font-family:'DM Sans',sans-serif;"></textarea>
        </div>
 
        <!-- Action buttons -->
        <div style="display:flex;gap:10px;justify-content:flex-end;
          padding-top:16px;border-top:1px solid var(--border);">
          <button onclick="document.getElementById('close-review-overlay').remove()"
            style="padding:10px 24px;background:none;border:1px solid var(--border);
              border-radius:var(--radius-sm);font-size:13px;font-weight:600;
              cursor:pointer;color:var(--text-2);font-family:inherit;">
            Cancel
          </button>
          <button onclick="RM.rejectClose(${closeId})"
            style="padding:10px 24px;background:none;border:1px solid var(--red-border);
              border-radius:var(--radius-sm);font-size:13px;font-weight:700;
              cursor:pointer;color:var(--red-text);font-family:inherit;">
            Reject
          </button>
          <button onclick="RM.endorseClose(${closeId})"
            style="padding:10px 28px;background:var(--text);color:#fff;border:none;
              border-radius:var(--radius-sm);font-size:13px;font-weight:700;
              cursor:pointer;font-family:inherit;">
            Endorse & File
          </button>
        </div>`;
 
    } catch {
      document.getElementById('review-body').innerHTML = `
        <div style="text-align:center;padding:60px;color:var(--red-text);font-size:13px;">
          Could not load monthly close document.
        </div>`;
    }
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    init,
    refresh,
    switchPane,
    toggleAlertsOnly,
    openBranchDetail,
    endorseClose,
    rejectClose,
    openCloseReview,
  };

})();

document.addEventListener('DOMContentLoaded', RM.init);

// ── Notifications ──────────────────────────────────────────
const RMNotifications = (() => {
  let open = false;

  function _esc(str) {
    return String(str ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  async function load() {
    const list = document.getElementById('rm-notif-list');
    if (!list) return;
    try {
      const res  = await Auth.fetch('/api/v1/notifications/');
      if (!res?.ok) throw new Error();
      const data = await res.json();
      if (!data.length) {
        list.innerHTML = '<div class="notif-empty">You\'re all caught up ✓</div>';
        return;
      }
      list.innerHTML = data.map(n => `
        <div class="notif-item ${n.is_read ? 'read' : 'unread'}"
          onclick="RMNotifications.markRead(${n.id}, this)">
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
      if (!res?.ok) return;
      const data  = await res.json();
      const count = data.count || 0;
      const badge = document.getElementById('rm-notif-badge');
      if (badge) {
        badge.textContent   = count > 99 ? '99+' : count;
        badge.style.display = count > 0 ? 'flex' : 'none';
      }
    } catch { /* silent */ }
  }

  function toggle() { open ? close() : _open(); }

  function _open() {
    open = true;
    document.getElementById('rm-notif-dropdown')?.classList.add('open');
    load();
  }

  function close() {
    open = false;
    document.getElementById('rm-notif-dropdown')?.classList.remove('open');
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