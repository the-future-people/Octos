/**
 * Octos — Branch Manager / Jobs
 * Dual-mode: runs standalone (/portal/jobs/) or embedded in dashboard pane.
 *
 * Standalone:  DOMContentLoaded → Jobs.init({ embedded: false })
 * Dashboard:   Dashboard calls  → Jobs.init({ embedded: true })
 *
 * API endpoints:
 *   GET  /api/v1/jobs/                 — list (branch-scoped, filters)
 *   GET  /api/v1/jobs/<id>/            — detail + status_logs + allowed_transitions
 *   POST /api/v1/jobs/create/          — create job
 *   POST /api/v1/jobs/<id>/transition/ — { to_status, notes }
 *   GET  /api/v1/jobs/services/        — active services
 *   GET  /api/v1/jobs/price/calculate/ — ?service=&branch=&quantity=&pages=&is_color=
 *   GET  /api/v1/customers/            — customer list
 *   GET  /api/v1/accounts/me/          — user/branch context
 */

'use strict';

// ─────────────────────────────────────────────────────────────────────────────
// State — shared with NJ controller via window.JobsState
// ─────────────────────────────────────────────────────────────────────────────
const JobsState = {
  jobs        : [],
  page        : 1,
  pageSize    : 25,
  totalCount  : 0,
  status      : 'all',
  jobType     : '',
  searchQuery : '',
  services    : [],
  customers   : [],
  branchId    : null,
  embedded    : false,
  pendingTransition: { jobId: null, toStatus: null },
};

// Expose for nj_controller.js
window.JobsState = JobsState;

// ─────────────────────────────────────────────────────────────────────────────
// Constants
// ─────────────────────────────────────────────────────────────────────────────
const STATUS_LABELS = {
  DRAFT              : 'Draft',
  PENDING_PAYMENT    : 'Pending Payment',
  PAID               : 'Paid',
  CONFIRMED          : 'Confirmed',
  IN_PROGRESS        : 'In Progress',
  READY              : 'Ready',
  OUT_FOR_DELIVERY   : 'Out for Delivery',
  COMPLETE           : 'Complete',
  CANCELLED          : 'Cancelled',
  VOIDED             : 'Voided',
  HALTED             : 'Halted',
  SAMPLE_SENT        : 'Sample Sent',
  REVISION_REQUESTED : 'Revision Requested',
  DESIGN_APPROVED    : 'Design Approved',
};

const STATUS_BADGE = {
  DRAFT              : 'badge-draft',
  PENDING_PAYMENT    : 'badge-pending',
  PAID               : 'badge-ready',
  CONFIRMED          : 'badge-pending',
  IN_PROGRESS        : 'badge-progress',
  READY              : 'badge-ready',
  OUT_FOR_DELIVERY   : 'badge-ready',
  COMPLETE           : 'badge-done',
  CANCELLED          : 'badge-cancelled',
  VOIDED             : 'badge-cancelled',
  HALTED             : 'badge-halted',
  SAMPLE_SENT        : 'badge-pending',
  REVISION_REQUESTED : 'badge-halted',
  DESIGN_APPROVED    : 'badge-ready',
};

// ─────────────────────────────────────────────────────────────────────────────
// Jobs public API
// ─────────────────────────────────────────────────────────────────────────────
const Jobs = {

  /**
   * Initialise the jobs interface.
   * @param {object} opts
   * @param {boolean} opts.embedded  - true when running inside dashboard pane
   */
  init({ embedded = false } = {}) {
    JobsState.embedded = embedded;
    JobsState.page        = 1;
    JobsState.status      = 'all';
    JobsState.jobType     = '';
    JobsState.searchQuery = '';

if (!embedded) {
      // Standalone page only
      Auth.guard();
      _setDate();
      _loadContext();
      JobsNotifications.startPolling();
    }

    _loadJobs();
    _loadServices();
    _loadCustomers();
    _bindFilters();
    WeekGreeter.init();
  },

  // ── Detail modal ─────────────────────────────────────────────────────────
  async openDetail(jobId) {
    const overlay = document.getElementById('job-detail-modal');
    const body    = document.getElementById('detail-body');
    if (!overlay || !body) return;

    overlay.classList.add('open');
    body.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-3);"><span class="spin"></span> Loading…</div>`;

    try {
      const res = await Auth.fetch(`/api/v1/jobs/${jobId}/`);
      if (!res.ok) throw new Error('Not found');
      const job = await res.json();

      _set('detail-title', job.title || 'Job Detail');
      _set('detail-ref',   job.job_number || `#${job.id}`);

      const price    = job.amount_paid ?? job.final_cost ?? job.estimated_cost;
      const priceStr = price
        ? `GHS ${parseFloat(price).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
        : '—';

      const logs = (job.status_logs || []).map(log => {
        const isGood = ['COMPLETE','PAID','DESIGN_APPROVED','CONFIRMED','READY'].includes(log.to_status);
        const isBad  = ['CANCELLED','REVISION_REQUESTED','HALTED','VOIDED'].includes(log.to_status);
        const dotCls = isGood ? 'green' : (isBad ? 'red' : '');
        const from   = STATUS_LABELS[log.from_status] || log.from_status || '—';
        const to     = STATUS_LABELS[log.to_status]   || log.to_status   || '—';
        const when   = log.transitioned_at
          ? new Date(log.transitioned_at).toLocaleString('en-GB', {
              day: 'numeric', month: 'short', year: 'numeric',
              hour: '2-digit', minute: '2-digit',
            })
          : '';
        const notesHtml = log.notes
          ? `<div class="tl-notes">${_esc(log.notes)}</div>`
          : '';

        return `
          <div class="timeline-item">
            <div class="tl-dot ${dotCls}">
              <svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24"
                fill="none" stroke="currentColor" stroke-width="3">
                <polyline points="20 6 9 17 4 12"/>
              </svg>
            </div>
            <div class="tl-body">
              <div class="tl-status">${from} → ${to}</div>
              <div class="tl-meta">${_esc(log.actor_name || '—')} · ${when}</div>
              ${notesHtml}
            </div>
          </div>`;
      }).join('') || '<div style="color:var(--text-3);font-size:13px;">No status history yet.</div>';

      const transitions    = job.allowed_transitions || [];
      const transitionHtml = transitions.length
        ? `<div class="transition-btns">${transitions.map(s =>
            `<button class="transition-btn"
              onclick="Jobs.openTransitionModal(${job.id}, '${s}', '${_esc(job.job_number || '#' + job.id)}')">
              ${STATUS_LABELS[s] || s}
            </button>`
          ).join('')}</div>`
        : `<span style="font-size:13px;color:var(--text-3);">No transitions available.</span>`;

      body.innerHTML = `
        <div class="detail-section">
          <div class="detail-section-title">Job Information</div>
          <div class="detail-grid">
            <div class="detail-field">
              <span class="detail-label">Status</span>
              <span class="detail-val">
                <span class="badge ${STATUS_BADGE[job.status] || 'badge-draft'}">
                  ${STATUS_LABELS[job.status] || job.status}
                </span>
              </span>
            </div>
            <div class="detail-field">
              <span class="detail-label">Type</span>
              <span class="detail-val">${_typeTag(job.job_type)}</span>
            </div>
            <div class="detail-field">
              <span class="detail-label">Customer</span>
              <span class="detail-val">${_esc(job.customer_name || '—')}</span>
            </div>
            <div class="detail-field">
              <span class="detail-label">Intake By</span>
              <span class="detail-val">${_esc(job.intake_by_name || '—')}</span>
            </div>
            <div class="detail-field">
              <span class="detail-label">Price</span>
              <span class="detail-val" style="font-family:'JetBrains Mono',monospace;">${priceStr}</span>
            </div>
            <div class="detail-field">
              <span class="detail-label">Channel</span>
              <span class="detail-val">${_esc(job.intake_channel || '—')}</span>
            </div>
            <div class="detail-field">
              <span class="detail-label">Created</span>
              <span class="detail-val">${job.created_at
                ? new Date(job.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                : '—'}</span>
            </div>
            <div class="detail-field">
              <span class="detail-label">Deadline</span>
              <span class="detail-val">${job.deadline
                ? new Date(job.deadline).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
                : '—'}</span>
            </div>
          </div>
          ${job.notes ? `
            <div style="margin-top:14px;">
              <div class="detail-label" style="margin-bottom:4px;">Notes</div>
              <div style="font-size:13px;color:var(--text-2);line-height:1.5;padding:10px 12px;
                background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border);">
                ${_esc(job.notes)}
              </div>
            </div>` : ''}
        </div>

        <div class="detail-section">
          <div class="detail-section-title">Move Status</div>
          ${transitionHtml}
        </div>

        <div class="detail-section">
          <div class="detail-section-title">Status History</div>
          <div class="timeline">${logs}</div>
        </div>`;

    } catch (e) {
      body.innerHTML = `<div style="text-align:center;padding:40px;color:var(--red-text);font-size:13px;">
        Failed to load job detail.</div>`;
    }
  },

  // ── Transition modal ──────────────────────────────────────────────────────
  openTransitionModal(jobId, toStatus, jobRef) {
    JobsState.pendingTransition = { jobId, toStatus };

    _set('transition-job-ref', jobRef);
    const notesEl = document.getElementById('transition-notes');
    if (notesEl) notesEl.value = '';

    const btn = document.getElementById('transition-submit-btn');
    if (btn) btn.disabled = false;

    const btns  = document.getElementById('transition-btns');
    const label = STATUS_LABELS[toStatus] || toStatus;
    if (btns) {
      btns.innerHTML = `
        <button class="transition-btn" style="background:var(--text);color:#fff;border-color:var(--text);">
          ${label}
        </button>`;
    }

    document.getElementById('job-detail-modal')?.classList.remove('open');
    document.getElementById('transition-modal')?.classList.add('open');
  },

  async confirmTransition() {
    const { jobId, toStatus } = JobsState.pendingTransition;
    if (!jobId || !toStatus) return;

    const notes = document.getElementById('transition-notes')?.value.trim() || '';
    const btn   = document.getElementById('transition-submit-btn');

    if (btn) { btn.disabled = true; btn.textContent = 'Updating…'; }

    try {
      const res = await Auth.fetch(`/api/v1/jobs/${jobId}/transition/`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ to_status: toStatus, notes }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Transition failed.', 'error');
        return;
      }

      _toast(`Status updated to ${STATUS_LABELS[toStatus] || toStatus}.`, 'success');
      closeTransitionModal();
      JobsState.pendingTransition = { jobId: null, toStatus: null };
      _loadJobs();

    } catch {
      _toast('Network error.', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Confirm Transition'; }
    }
  },

  // ── Pagination ────────────────────────────────────────────────────────────
  prevPage() {
    if (JobsState.page > 1) { JobsState.page--; _loadJobs(); }
  },

  nextPage() {
    const totalPages = Math.ceil(JobsState.totalCount / JobsState.pageSize);
    if (JobsState.page < totalPages) { JobsState.page++; _loadJobs(); }
  },

  // Expose for dashboard reload after job creation
  reload() { _loadJobs(); },
};

// Expose globally
window.Jobs = Jobs;

// ─────────────────────────────────────────────────────────────────────────────
// Context (standalone only — dashboard already has context)
// ─────────────────────────────────────────────────────────────────────────────
async function _loadContext() {
  try {
    const res  = await Auth.fetch('/api/v1/accounts/me/');
    if (!res.ok) return;
    const user = await res.json();

    const fullName = user.full_name || user.email || '—';
    const initials = fullName.split(' ').slice(0, 2)
      .map(w => w[0]?.toUpperCase() || '').join('');

    _set('jobs-user-name',     fullName);
    _set('jobs-user-initials', initials);

    const branch = user.branch;
    if (branch && typeof branch === 'object') {
      JobsState.branchId = branch.id;
      _set('jobs-branch-name', branch.name || 'Jobs');
      _set('jobs-branch-pill', branch.name || '—');
    } else if (branch && typeof branch === 'number') {
      JobsState.branchId = branch;
      const br = await Auth.fetch(`/api/v1/organization/branches/${branch}/`);
      if (br.ok) {
        const b = await br.json();
        _set('jobs-branch-name', b.name || 'Jobs');
        _set('jobs-branch-pill', b.name || '—');
      }
    }
  } catch (e) {
    console.warn('Jobs _loadContext failed:', e);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Jobs list
// ─────────────────────────────────────────────────────────────────────────────
async function _loadJobs() {
  _setTableLoading();

  const params = new URLSearchParams();
  params.set('page',      JobsState.page);
  params.set('page_size', JobsState.pageSize);
  if (JobsState.status && JobsState.status !== 'all') params.set('status',   JobsState.status);
  if (JobsState.jobType)                              params.set('job_type', JobsState.jobType);
  if (JobsState.searchQuery)                          params.set('search',   JobsState.searchQuery);

  try {
    const sheetRes = await Auth.fetch('/api/v1/finance/sheets/today/');

    if (!sheetRes.ok) {
      _setSheetClosed('No open sheet today.');
      return;
    }

    const sheet = await sheetRes.json();

    if (sheet.status !== 'OPEN') {
      _setSheetClosed('Today\'s sheet is closed — view history in Reports.');
      return;
    }

    params.set('daily_sheet', sheet.id);

    const res  = await Auth.fetch(`/api/v1/jobs/?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    JobsState.jobs       = data.results || data;
    JobsState.totalCount = data.count   || JobsState.jobs.length;

    _renderTable();
    _renderStats(sheet.id);
    _renderPagination();
  } catch (err) {
    console.error('_loadJobs failed:', err);
    _setTableError();
  }
}

function _renderTable() {
  const tbody = document.getElementById('jobs-tbody');
  if (!tbody) return;

  if (!JobsState.jobs.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="empty-cell">
          <div class="empty-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"
              fill="none" stroke="currentColor" stroke-width="2">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
              <polyline points="14 2 14 8 20 8"/>
            </svg>
          </div>
          <div class="empty-text">No jobs found</div>
        </td>
      </tr>`;
    return;
  }

  tbody.innerHTML = JobsState.jobs.map(j => {
    const badgeCls = STATUS_BADGE[j.status]  || 'badge-draft';
    const label    = STATUS_LABELS[j.status] || j.status;
    const price    = j.amount_paid ?? j.estimated_cost;
    const priceStr = price
      ? `GHS ${parseFloat(price).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
      : '—';
    const date     = j.created_at
      ? new Date(j.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })
      : '—';

    return `
      <tr onclick="Jobs.openDetail(${j.id})">
        <td>
          <div class="td-job-title">${_esc(j.title || '—')}</div>
          <div class="td-job-ref">${_esc(j.job_number || '#' + j.id)}</div>
        </td>
        <td style="font-size:13px;color:var(--text-2);">${_esc(j.customer_name || '—')}</td>
        <td>${_typeTag(j.job_type)}</td>
        <td><span class="badge ${badgeCls}">${label}</span></td>
        <td style="font-family:'JetBrains Mono',monospace;font-size:12.5px;">${priceStr}</td>
        <td style="font-size:12px;color:var(--text-3);">${date}</td>
      </tr>`;
  }).join('');
}

async function _renderStats(sheetId) {
  try {
    const res  = await Auth.fetch(`/api/v1/jobs/stats/?daily_sheet=${sheetId}`);
    if (!res.ok) return;
    const data = await res.json();

    _set('jobs-stat-total',       data.total);
    _set('jobs-stat-in-progress', data.in_progress);
    _set('jobs-stat-complete',    data.complete);
    _set('jobs-stat-revenue',     parseFloat(data.revenue) > 0
      ? parseFloat(data.revenue).toLocaleString('en-GH', { minimumFractionDigits: 2 })
      : '0');
  } catch { /* silent */ }
}

function _renderPagination() {
  const pag     = document.getElementById('jobs-pagination');
  const info    = document.getElementById('jobs-page-info');
  const btnPrev = document.getElementById('jobs-btn-prev');
  const btnNext = document.getElementById('jobs-btn-next');

  if (JobsState.totalCount <= JobsState.pageSize) {
    if (pag) pag.style.display = 'none';
    return;
  }

  const totalPages = Math.ceil(JobsState.totalCount / JobsState.pageSize);
  const start      = (JobsState.page - 1) * JobsState.pageSize + 1;
  const end        = Math.min(JobsState.page * JobsState.pageSize, JobsState.totalCount);

  if (pag)     pag.style.display  = 'flex';
  if (info)    info.textContent   = `Showing ${start}–${end} of ${JobsState.totalCount} jobs`;
  if (btnPrev) btnPrev.disabled   = JobsState.page <= 1;
  if (btnNext) btnNext.disabled   = JobsState.page >= totalPages;
}

function _setTableLoading() {
  const el = document.getElementById('jobs-tbody');
  if (el) el.innerHTML =
    `<tr><td colspan="6" class="loading-cell"><span class="spin"></span> Loading jobs…</td></tr>`;
}

function _setTableError() {
  const el = document.getElementById('jobs-tbody');
  if (el) el.innerHTML =
    `<tr><td colspan="6" class="loading-cell" style="color:var(--red-text);">
      Failed to load jobs. Try refreshing.</td></tr>`;
  const pag = document.getElementById('jobs-pagination');
  if (pag) pag.style.display = 'none';
}

function _setSheetClosed(message) {
  _set('jobs-stat-total',       '—');
  _set('jobs-stat-in-progress', '—');
  _set('jobs-stat-complete',    '—');
  _set('jobs-stat-revenue',     '—');

  const pag = document.getElementById('jobs-pagination');
  if (pag) pag.style.display = 'none';

  const tbody = document.getElementById('jobs-tbody');
  if (tbody) tbody.innerHTML = `
    <tr>
      <td colspan="6" class="empty-cell">
        <div class="empty-icon">
          <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24"
            fill="none" stroke="currentColor" stroke-width="2">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
            <polyline points="14 2 14 8 20 8"/>
          </svg>
        </div>
        <div class="empty-text">${message}</div>
      </td>
    </tr>`;
}

// ─────────────────────────────────────────────────────────────────────────────
// Services & Customers (for NJ modal)
// ─────────────────────────────────────────────────────────────────────────────
async function _loadServices() {
  try {
    const res  = await Auth.fetch('/api/v1/jobs/services/');
    if (!res.ok) return;
    const data = await res.json();
    JobsState.services = data.results || data;
  } catch (e) {
    console.warn('_loadServices failed:', e);
  }
}

async function _loadCustomers() {
  try {
    const res  = await Auth.fetch('/api/v1/customers/');
    if (!res.ok) return;
    const data = await res.json();
    JobsState.customers = data.results || data;
  } catch (e) {
    console.warn('_loadCustomers failed:', e);
  }
}

// ─────────────────────────────────────────────────────────────────────────────
// Filters
// ─────────────────────────────────────────────────────────────────────────────
function _bindFilters() {
  document.getElementById('jobs-filter-tabs')?.addEventListener('click', e => {
    const btn = e.target.closest('.filter-tab');
    if (!btn) return;
    document.querySelectorAll('#jobs-filter-tabs .filter-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    JobsState.status = btn.dataset.status;
    JobsState.page   = 1;
    _loadJobs();
  });

  let searchTimer;
  document.getElementById('jobs-search')?.addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      JobsState.searchQuery = e.target.value.trim();
      JobsState.page        = 1;
      _loadJobs();
    }, 350);
  });

  document.getElementById('jobs-type')?.addEventListener('change', e => {
    JobsState.jobType = e.target.value;
    JobsState.page    = 1;
    _loadJobs();
  });
}

// ─────────────────────────────────────────────────────────────────────────────
// Notifications (standalone page only)
// ─────────────────────────────────────────────────────────────────────────────
const JobsNotifications = {

  async startPolling() {
    await this._loadCount();
    setInterval(() => this._loadCount(), 30000);
  },

  async _loadCount() {
    try {
      const res   = await Auth.fetch('/api/v1/notifications/unread-count/');
      if (!res.ok) return;
      const data  = await res.json();
      const count = data.count || 0;
      const badge = document.getElementById('jobs-notif-badge');
      if (badge) {
        badge.textContent   = count > 99 ? '99+' : count;
        badge.style.display = count > 0 ? 'flex' : 'none';
      }
    } catch { /* silent */ }
  },

  async toggle() {
    const dd = document.getElementById('notif-dropdown');
    if (!dd) return;
    const isOpen = dd.classList.contains('open');
    if (isOpen) { this.close(); return; }
    dd.classList.add('open');
    await this._load();
  },

  async _load() {
    const list = document.getElementById('notif-list');
    if (!list) return;
    list.innerHTML = '<div class="notif-empty">Loading…</div>';

    try {
      const res   = await Auth.fetch('/api/v1/notifications/?page_size=20');
      if (!res.ok) throw new Error();
      const data  = await res.json();
      const items = data.results || data;

      if (!items.length) {
        list.innerHTML = '<div class="notif-empty">You\'re all caught up ✓</div>';
        return;
      }

      list.innerHTML = items.map(n => `
        <div class="notif-item ${n.is_read ? 'read' : 'unread'}"
          onclick="JobsNotifications.markRead(${n.id}, this)">
          <div class="notif-dot"></div>
          <div style="flex:1;">
            <div class="notif-msg">${_esc(n.message || '')}</div>
            <div class="notif-time">${n.created_at
              ? new Date(n.created_at).toLocaleString('en-GB', {
                  day: 'numeric', month: 'short',
                  hour: '2-digit', minute: '2-digit',
                })
              : ''}</div>
          </div>
        </div>`).join('');

    } catch {
      list.innerHTML = '<div class="notif-empty">Failed to load.</div>';
    }
  },

  async markRead(id, el) {
    try {
      await Auth.fetch(`/api/v1/notifications/${id}/read/`, { method: 'POST' });
      el?.classList.remove('unread');
      el?.classList.add('read');
      await this._loadCount();
    } catch { /* silent */ }
  },

  async markAllRead() {
    try {
      await Auth.fetch('/api/v1/notifications/read-all/', { method: 'POST' });
      document.querySelectorAll('.notif-item.unread').forEach(el => {
        el.classList.remove('unread');
        el.classList.add('read');
      });
      await this._loadCount();
    } catch { /* silent */ }
  },

  close() {
    document.getElementById('notif-dropdown')?.classList.remove('open');
  },
};

window.JobsNotifications = JobsNotifications;

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
function _typeTag(type) {
  if (!type) return '—';
  const cls = {
    INSTANT    : 'type-instant',
    PRODUCTION : 'type-production',
    DESIGN     : 'type-design',
  }[type] || '';
  return `<span class="type-badge ${cls}">${type}</span>`;
}

function _esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

function _set(id, val) {
  const el = document.getElementById(id);
  if (el) el.textContent = val;
}

function _setDate() {
  const now = new Date();
  _set('meta-date', now.toLocaleDateString('en-GB', {
    weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
  }));
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

// ─────────────────────────────────────────────────────────────────────────────
// Global aliases for HTML onclick handlers and NJ controller
// ─────────────────────────────────────────────────────────────────────────────
function closeNewJobModal() {
  if (typeof NJ !== 'undefined') NJ.tryAutoSaveDraft();
  document.getElementById('new-job-modal')?.classList.remove('open');
}
function closeDetailModal()     { document.getElementById('job-detail-modal')?.classList.remove('open'); }
function closeTransitionModal() { document.getElementById('transition-modal')?.classList.remove('open'); }

window.closeNewJobModal    = closeNewJobModal;
window.closeDetailModal    = closeDetailModal;
window.closeTransitionModal = closeTransitionModal;

// ─────────────────────────────────────────────────────────────────────────────
// Standalone boot — only runs when loaded by jobs.html directly
// ─────────────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  // If we're on the standalone jobs page (not embedded in dashboard)
  if (document.getElementById('jobs-standalone-root')) {
    Jobs.init({ embedded: false });
  }
});