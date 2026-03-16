/**
 * Octos — Branch Manager / Jobs
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

// ─────────────────────────────────────────────────────────────
// State — shared with NJ controller
// ─────────────────────────────────────────────────────────────
const State = {
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
  pendingTransition: { jobId: null, toStatus: null },
};

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

// ─────────────────────────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  Auth.guard();
  _setDate();
  loadContext();
  loadJobs();
  loadServices();
  loadCustomers();
  bindFilters();
  Notifications.startPolling();
});

// ─────────────────────────────────────────────────────────────
// Context
// ─────────────────────────────────────────────────────────────
async function loadContext() {
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
      State.branchId = branch.id;
      _set('jobs-branch-name', branch.name || 'Jobs');
      _set('jobs-branch-pill', branch.name || '—');
    } else if (branch && typeof branch === 'number') {
      State.branchId = branch;
      const br = await Auth.fetch(`/api/v1/organization/branches/${branch}/`);
      if (br.ok) {
        const b = await br.json();
        _set('jobs-branch-name', b.name || 'Jobs');
        _set('jobs-branch-pill', b.name || '—');
      }
    }
  } catch (e) {
    console.warn('loadContext failed:', e);
  }
}

// ─────────────────────────────────────────────────────────────
// Jobs list
// ─────────────────────────────────────────────────────────────
async function loadJobs() {
  _setTableLoading();

  const params = new URLSearchParams();
  params.set('page',      State.page);
  params.set('page_size', State.pageSize);
  if (State.status && State.status !== 'all') params.set('status',   State.status);
  if (State.jobType)                          params.set('job_type', State.jobType);
  if (State.searchQuery)                      params.set('search',   State.searchQuery);

  try {
    const res  = await Auth.fetch(`/api/v1/jobs/?${params}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();

    State.jobs       = data.results || data;
    State.totalCount = data.count   || State.jobs.length;

    _renderTable();
    _renderStats();
    _renderPagination();
  } catch (err) {
    console.error('loadJobs failed:', err);
    _setTableError();
  }
}

function _renderTable() {
  const tbody = document.getElementById('jobs-tbody');

  if (!State.jobs.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="empty-cell">
          <div class="empty-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </div>
          <div class="empty-text">No jobs found</div>
        </td>
      </tr>`;
    return;
  }

  tbody.innerHTML = State.jobs.map(j => {
    const badgeCls = STATUS_BADGE[j.status]  || 'badge-draft';
    const label    = STATUS_LABELS[j.status] || j.status;
    const price    = j.estimated_cost
      ? `GHS ${parseFloat(j.estimated_cost).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`
      : '—';
    const date     = j.created_at
      ? new Date(j.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' })
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
        <td style="font-family:'JetBrains Mono',monospace;font-size:12.5px;">${price}</td>
        <td style="font-size:12px;color:var(--text-3);">${date}</td>
      </tr>`;
  }).join('');
}

function _renderStats() {
  const total      = State.totalCount;
  const inProgress = State.jobs.filter(j => j.status === 'IN_PROGRESS').length;
  const complete   = State.jobs.filter(j => j.status === 'COMPLETE').length;
  const revenue    = State.jobs
    .filter(j => ['PAID', 'COMPLETE'].includes(j.status))
    .reduce((sum, j) => sum + parseFloat(j.final_cost || j.estimated_cost || 0), 0);

  _set('stat-total',       total);
  _set('stat-in-progress', inProgress);
  _set('stat-complete',    complete);
  _set('stat-revenue',     revenue > 0
    ? revenue.toLocaleString('en-GH', { minimumFractionDigits: 2 })
    : '0');
}

function _renderPagination() {
  const pag     = document.getElementById('pagination');
  const info    = document.getElementById('page-info');
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');

  if (State.totalCount <= State.pageSize) {
    if (pag) pag.style.display = 'none';
    return;
  }

  const totalPages = Math.ceil(State.totalCount / State.pageSize);
  const start      = (State.page - 1) * State.pageSize + 1;
  const end        = Math.min(State.page * State.pageSize, State.totalCount);

  if (pag)     pag.style.display  = 'flex';
  if (info)    info.textContent   = `Showing ${start}–${end} of ${State.totalCount} jobs`;
  if (btnPrev) btnPrev.disabled   = State.page <= 1;
  if (btnNext) btnNext.disabled   = State.page >= totalPages;
}

function _setTableLoading() {
  const el = document.getElementById('jobs-tbody');
  if (el) el.innerHTML =
    `<tr><td colspan="6" class="loading-cell"><span class="spin"></span> Loading jobs…</td></tr>`;
}

function _setTableError() {
  const el = document.getElementById('jobs-tbody');
  if (el) el.innerHTML =
    `<tr><td colspan="6" class="loading-cell" style="color:var(--red-text);">Failed to load jobs. Try refreshing.</td></tr>`;
}

// ─────────────────────────────────────────────────────────────
// Filters
// ─────────────────────────────────────────────────────────────
function bindFilters() {
  document.getElementById('filter-tabs')?.addEventListener('click', e => {
    const btn = e.target.closest('.filter-tab');
    if (!btn) return;
    document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    State.status = btn.dataset.status;
    State.page   = 1;
    loadJobs();
  });

  let searchTimer;
  document.getElementById('jobs-search')?.addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      State.searchQuery = e.target.value.trim();
      State.page        = 1;
      loadJobs();
    }, 350);
  });

  document.getElementById('jobs-type')?.addEventListener('change', e => {
    State.jobType = e.target.value;
    State.page    = 1;
    loadJobs();
  });
}

// ─────────────────────────────────────────────────────────────
// Services & Customers
// ─────────────────────────────────────────────────────────────
async function loadServices() {
  try {
    const res  = await Auth.fetch('/api/v1/jobs/services/');
    if (!res.ok) return;
    const data = await res.json();
    State.services = data.results || data;
  } catch (e) {
    console.warn('loadServices failed:', e);
  }
}

async function loadCustomers() {
  try {
    const res  = await Auth.fetch('/api/v1/customers/');
    if (!res.ok) return;
    const data = await res.json();
    State.customers = data.results || data;
  } catch (e) {
    console.warn('loadCustomers failed:', e);
  }
}

// ─────────────────────────────────────────────────────────────
// Jobs object — detail, transitions, pagination
// ─────────────────────────────────────────────────────────────
const Jobs = {

  async openDetail(jobId) {
    const overlay = document.getElementById('job-detail-modal');
    const body    = document.getElementById('detail-body');
    overlay.classList.add('open');
    body.innerHTML = `<div style="text-align:center;padding:40px;color:var(--text-3);"><span class="spin"></span> Loading…</div>`;

    try {
      const res = await Auth.fetch(`/api/v1/jobs/${jobId}/`);
      if (!res.ok) throw new Error('Not found');
      const job = await res.json();

      _set('detail-title', job.title || 'Job Detail');
      _set('detail-ref',   job.job_number || `#${job.id}`);

      const price    = job.final_cost ?? job.estimated_cost;
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
              <svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
            <div class="tl-body">
              <div class="tl-status">${from} → ${to}</div>
              <div class="tl-meta">${_esc(log.actor_name || '—')} · ${when}</div>
              ${notesHtml}
            </div>
          </div>`;
      }).join('') || '<div style="color:var(--text-3);font-size:13px;">No status history yet.</div>';

      const transitions   = job.allowed_transitions || [];
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
              <span class="detail-label">Est. Cost</span>
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
              <div style="font-size:13px;color:var(--text-2);line-height:1.5;padding:10px 12px;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border);">
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
      body.innerHTML = `<div style="text-align:center;padding:40px;color:var(--red-text);font-size:13px;">Failed to load job detail.</div>`;
    }
  },

  openTransitionModal(jobId, toStatus, jobRef) {
    State.pendingTransition = { jobId, toStatus };

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

    document.getElementById('job-detail-modal').classList.remove('open');
    document.getElementById('transition-modal').classList.add('open');
  },

  async confirmTransition() {
    const { jobId, toStatus } = State.pendingTransition;
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
      State.pendingTransition = { jobId: null, toStatus: null };
      loadJobs();

    } catch (e) {
      _toast('Network error.', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Confirm Transition'; }
    }
  },

  prevPage() {
    if (State.page > 1) { State.page--; loadJobs(); }
  },

  nextPage() {
    const totalPages = Math.ceil(State.totalCount / State.pageSize);
    if (State.page < totalPages) { State.page++; loadJobs(); }
  },
};

// ─────────────────────────────────────────────────────────────
// Notifications
// ─────────────────────────────────────────────────────────────
const Notifications = {

  async startPolling() {
    await this._loadCount();
    setInterval(() => this._loadCount(), 30000);
  },

  async _loadCount() {
    try {
      const res  = await Auth.fetch('/api/v1/notifications/unread-count/');
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
      const res  = await Auth.fetch('/api/v1/notifications/?page_size=20');
      if (!res.ok) throw new Error();
      const data  = await res.json();
      const items = data.results || data;

      if (!items.length) {
        list.innerHTML = '<div class="notif-empty">You\'re all caught up ✓</div>';
        return;
      }

      list.innerHTML = items.map(n => `
        <div class="notif-item ${n.is_read ? 'read' : 'unread'}"
          onclick="Notifications.markRead(${n.id}, this)">
          <div class="notif-dot"></div>
          <div style="flex:1;">
            <div class="notif-msg">${_esc(n.message || '')}</div>
            <div class="notif-time">${n.created_at
              ? new Date(n.created_at).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
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

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────
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
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
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

// Global aliases expected by NJ controller and HTML onclick handlers
function closeNewJobModal()     { document.getElementById('new-job-modal').classList.remove('open'); }
function closeTransitionModal() { document.getElementById('transition-modal').classList.remove('open'); }