/**
 * Octos — Branch Manager / Jobs
 * Matches jobs.html v2 (dashboard-aligned design)
 *
 * API endpoints:
 *   GET  /api/v1/jobs/                — list (branch-scoped, filters)
 *   GET  /api/v1/jobs/<id>/           — detail + status_logs + allowed_transitions
 *   POST /api/v1/jobs/create/         — create job
 *   POST /api/v1/jobs/<id>/transition/ — { to_status, notes }
 *   GET  /api/v1/jobs/services/       — active services
 *   GET  /api/v1/jobs/price/calculate/ — ?service=&branch=&quantity=&pages=&is_color=
 *   GET  /api/v1/customers/           — customer list
 *   GET  /api/v1/organization/me/     — branch/user context
 */

'use strict';

// ─────────────────────────────────────────────────────────────
// State
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
  // for transition modal
  pendingTransition : { jobId: null, toStatus: null },
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
  HALTED             : 'Halted',
  SAMPLE_SENT        : 'Sample Sent',
  REVISION_REQUESTED : 'Revision Requested',
  DESIGN_APPROVED    : 'Design Approved',
};

const STATUS_BADGE = {
  DRAFT              : 'badge-grey',
  PENDING_PAYMENT    : 'badge-yellow',
  PAID               : 'badge-green',
  CONFIRMED          : 'badge-yellow',
  IN_PROGRESS        : 'badge-blue',
  READY              : 'badge-green',
  OUT_FOR_DELIVERY   : 'badge-green',
  COMPLETE           : 'badge-green',
  CANCELLED          : 'badge-grey',
  HALTED             : 'badge-red',
  SAMPLE_SENT        : 'badge-yellow',
  REVISION_REQUESTED : 'badge-red',
  DESIGN_APPROVED    : 'badge-green',
};

// ─────────────────────────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  Auth.guard();
  loadContext();
  loadJobs();
  loadServices();
  loadCustomers();
  bindFilters();
  Notifications.init({
    badgeEl   : document.getElementById('jobs-notif-badge'),
    dropdownEl: document.getElementById('notif-dropdown'),
    listEl    : document.getElementById('notif-list'),
  });

  // Meta date
  document.getElementById('meta-date').textContent =
    new Date().toLocaleDateString('en-GB', { day:'numeric', month:'short', year:'numeric' });
});

// ─────────────────────────────────────────────────────────────
// Context (branch / user info)
// ─────────────────────────────────────────────────────────────
async function loadContext() {
  try {
    const res  = await Auth.fetch('/api/v1/organization/me/');
    if (!res.ok) return;
    const data = await res.json();

    const user   = data.user   || {};
    const branch = data.branch || {};

    document.getElementById('jobs-branch-name').textContent = branch.name || 'Branch Manager';
    document.getElementById('jobs-user-name').textContent   = user.full_name || user.email || '—';
    const initials = (user.full_name || '').split(' ').map(w => w[0]).join('').slice(0,2).toUpperCase() || 'KA';
    document.getElementById('jobs-user-initials').textContent = initials;

    document.getElementById('meta-branch').textContent = branch.name || '—';
    document.getElementById('meta-region').textContent = branch.region || '—';

    State.branchId = branch.id || null;
  } catch (e) {
    console.warn('loadContext failed:', e);
  }
}

// ─────────────────────────────────────────────────────────────
// Jobs List
// ─────────────────────────────────────────────────────────────
async function loadJobs() {
  setTableLoading();

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

    renderTable();
    renderStats();
    renderPagination();
  } catch (err) {
    console.error('loadJobs failed:', err);
    setTableError();
  }
}

function renderTable() {
  const tbody = document.getElementById('jobs-tbody');

  if (!State.jobs.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="7" class="empty-cell">
          <div class="empty-icon">
            <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </div>
          <div class="empty-text">No jobs found</div>
        </td>
      </tr>`;
    return;
  }

  tbody.innerHTML = State.jobs.map(j => {
    const badgeCls = STATUS_BADGE[j.status] || 'badge-grey';
    const label    = STATUS_LABELS[j.status] || j.status;
    const typeHtml = typeTag(j.job_type);
    const price    = j.estimated_cost ? `GHS ${parseFloat(j.estimated_cost).toLocaleString('en-GH', {minimumFractionDigits:2})}` : '—';
    const date     = j.created_at ? new Date(j.created_at).toLocaleDateString('en-GB', {day:'numeric',month:'short',year:'numeric'}) : '—';
    const customer = escHtml(j.customer_name || '—');

    return `
      <tr onclick="Jobs.openDetail(${j.id})">
        <td>
          <div class="td-job-title">${escHtml(j.title || '—')}</div>
          <div class="td-job-ref">${escHtml(j.job_number || '#' + j.id)}</div>
        </td>
        <td>${customer}</td>
        <td>${typeHtml}</td>
        <td><span class="badge ${badgeCls}">${label}</span></td>
        <td style="font-family:monospace;font-size:12.5px;">${price}</td>
        <td style="font-size:12px;color:#bbb;">${date}</td>
      </tr>`;
  }).join('');
}

function renderStats() {
  const total      = State.totalCount;
  const inProgress = State.jobs.filter(j => j.status === 'IN_PROGRESS').length;
  const complete   = State.jobs.filter(j => j.status === 'COMPLETE').length;
  const revenue    = State.jobs
    .filter(j => ['PAID','COMPLETE'].includes(j.status))
    .reduce((sum, j) => sum + parseFloat(j.final_cost || j.estimated_cost || 0), 0);

  document.getElementById('stat-total').textContent       = total;
  document.getElementById('stat-in-progress').textContent = inProgress;
  document.getElementById('stat-complete').textContent    = complete;
  document.getElementById('stat-revenue').textContent     =
    revenue > 0 ? revenue.toLocaleString('en-GH', {minimumFractionDigits:2}) : '0';
}

function renderPagination() {
  const pag     = document.getElementById('pagination');
  const info    = document.getElementById('page-info');
  const btnPrev = document.getElementById('btn-prev');
  const btnNext = document.getElementById('btn-next');

  if (State.totalCount <= State.pageSize) {
    pag.style.display = 'none';
    return;
  }

  const totalPages = Math.ceil(State.totalCount / State.pageSize);
  const start      = (State.page - 1) * State.pageSize + 1;
  const end        = Math.min(State.page * State.pageSize, State.totalCount);

  pag.style.display     = 'flex';
  info.textContent      = `Showing ${start}–${end} of ${State.totalCount} jobs`;
  btnPrev.disabled      = State.page <= 1;
  btnNext.disabled      = State.page >= totalPages;
}

function setTableLoading() {
  document.getElementById('jobs-tbody').innerHTML =
    `<tr><td colspan="7" class="loading-cell"><span class="spin"></span> Loading jobs…</td></tr>`;
}

function setTableError() {
  document.getElementById('jobs-tbody').innerHTML =
    `<tr><td colspan="7" class="loading-cell" style="color:#e8294a;">Failed to load jobs. Try refreshing.</td></tr>`;
}

// ─────────────────────────────────────────────────────────────
// Filters
// ─────────────────────────────────────────────────────────────
function bindFilters() {
  document.getElementById('filter-tabs').addEventListener('click', e => {
    const btn = e.target.closest('.filter-tab');
    if (!btn) return;
    document.querySelectorAll('.filter-tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    State.status = btn.dataset.status;
    State.page   = 1;
    loadJobs();
  });

  let searchTimer;
  document.getElementById('jobs-search').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      State.searchQuery = e.target.value.trim();
      State.page        = 1;
      loadJobs();
    }, 350);
  });

  document.getElementById('jobs-type').addEventListener('change', e => {
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
// Jobs Object (detail + transitions + pagination)
// ─────────────────────────────────────────────────────────────
const Jobs = {

  async openDetail(jobId) {
    const overlay = document.getElementById('job-detail-modal');
    const body    = document.getElementById('detail-body');
    overlay.classList.add('open');
    body.innerHTML = `<div style="text-align:center;padding:40px;color:#ccc;"><span class="spin"></span> Loading…</div>`;

    try {
      const res = await Auth.fetch(`/api/v1/jobs/${jobId}/`);
      if (!res.ok) throw new Error('Not found');
      const job = await res.json();

      document.getElementById('detail-title').textContent = job.title || 'Job Detail';
      document.getElementById('detail-ref').textContent   = job.job_number || `#${job.id}`;

      const price = job.final_cost ?? job.estimated_cost;
      const priceStr = price ? `GHS ${parseFloat(price).toLocaleString('en-GH', {minimumFractionDigits:2})}` : '—';

      const logs = (job.status_logs || []).map(log => {
        const isGood = ['COMPLETE','PAID','DESIGN_APPROVED','CONFIRMED','READY'].includes(log.to_status);
        const isBad  = ['CANCELLED','REVISION_REQUESTED','HALTED'].includes(log.to_status);
        const dotCls = isGood ? 'green' : (isBad ? 'red' : '');
        const from   = STATUS_LABELS[log.from_status] || log.from_status || '—';
        const to     = STATUS_LABELS[log.to_status]   || log.to_status   || '—';
        const when   = log.transitioned_at ? new Date(log.transitioned_at).toLocaleString('en-GB', {day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'}) : '';
        const notesHtml = log.notes ? `<div class="tl-notes">${escHtml(log.notes)}</div>` : '';
        return `
          <div class="timeline-item">
            <div class="tl-dot ${dotCls}">
              <svg xmlns="http://www.w3.org/2000/svg" width="8" height="8" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
            </div>
            <div class="tl-body">
              <div class="tl-status">${from} → ${to}</div>
              <div class="tl-meta">${escHtml(log.actor_name || '—')} · ${when}</div>
              ${notesHtml}
            </div>
          </div>`;
      }).join('') || '<div style="color:#ccc;font-size:13px;">No status history yet.</div>';

      const transitions = job.allowed_transitions || [];
      const transitionHtml = transitions.length
        ? `<div class="transition-btns">${transitions.map(s =>
            `<button class="transition-btn" onclick="Jobs.openTransitionModal(${job.id}, '${s}', '${escHtml(job.job_number || '#' + job.id)}')">${STATUS_LABELS[s] || s}</button>`
          ).join('')}</div>`
        : `<span style="font-size:13px;color:#ccc;">No transitions available.</span>`;

      body.innerHTML = `
        <div class="detail-section">
          <div class="detail-section-title">Job Information</div>
          <div class="detail-grid">
            <div class="detail-field"><span class="detail-label">Status</span><span class="detail-val"><span class="badge ${STATUS_BADGE[job.status] || 'badge-grey'}">${STATUS_LABELS[job.status] || job.status}</span></span></div>
            <div class="detail-field"><span class="detail-label">Type</span><span class="detail-val">${typeTag(job.job_type)}</span></div>
            <div class="detail-field"><span class="detail-label">Customer</span><span class="detail-val">${escHtml(job.customer_name || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Assigned To</span><span class="detail-val">${escHtml(job.assigned_to_name || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Est. Cost</span><span class="detail-val" style="font-family:monospace;">${priceStr}</span></div>
            <div class="detail-field"><span class="detail-label">Channel</span><span class="detail-val">${escHtml(job.intake_channel || '—')}</span></div>
            <div class="detail-field"><span class="detail-label">Created</span><span class="detail-val">${job.created_at ? new Date(job.created_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : '—'}</span></div>
            <div class="detail-field"><span class="detail-label">Deadline</span><span class="detail-val">${job.deadline ? new Date(job.deadline).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : '—'}</span></div>
          </div>
          ${job.description ? `<div style="margin-top:12px;"><div class="detail-label" style="margin-bottom:4px;">Description</div><div style="font-size:13px;color:#555;line-height:1.5;">${escHtml(job.description)}</div></div>` : ''}
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
      body.innerHTML = `<div style="text-align:center;padding:40px;color:#e8294a;font-size:13px;">Failed to load job detail.</div>`;
    }
  },

  openTransitionModal(jobId, toStatus, jobRef) {
    State.pendingTransition = { jobId, toStatus };

    document.getElementById('transition-job-ref').textContent = jobRef;
    document.getElementById('transition-notes').value = '';
    document.getElementById('transition-submit-btn').disabled = false;

    const btns  = document.getElementById('transition-btns');
    const label = STATUS_LABELS[toStatus] || toStatus;
    btns.innerHTML = `<button class="transition-btn" style="background:#111;color:#fff;border-color:#111;">${label}</button>`;

    document.getElementById('job-detail-modal').classList.remove('open');
    document.getElementById('transition-modal').classList.add('open');
  },

  async confirmTransition() {
    const { jobId, toStatus } = State.pendingTransition;
    if (!jobId || !toStatus) return;

    const notes = document.getElementById('transition-notes').value.trim();
    const btn   = document.getElementById('transition-submit-btn');
    btn.disabled    = true;
    btn.textContent = 'Updating…';

    try {
      const res = await Auth.fetch(`/api/v1/jobs/${jobId}/transition/`, {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ to_status: toStatus, notes }),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        showToast(err.detail || 'Transition failed.', 'error');
        return;
      }

      showToast(`Status updated to ${STATUS_LABELS[toStatus] || toStatus}.`, 'success');
      closeTransitionModal();
      State.pendingTransition = { jobId: null, toStatus: null };
      loadJobs();
    } catch (e) {
      showToast('Network error.', 'error');
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Confirm Transition';
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
  _badge: null, _dropdown: null, _list: null,

  init({ badgeEl, dropdownEl, listEl }) {
    this._badge    = badgeEl;
    this._dropdown = dropdownEl;
    this._list     = listEl;
    this.poll();
    setInterval(() => this.poll(), 30000);

    document.addEventListener('click', e => {
      if (!dropdownEl.contains(e.target) && e.target.id !== 'jobs-notif-btn' && !e.target.closest('#jobs-notif-btn')) {
        this.close();
      }
    });
  },

  async poll() {
    try {
      const res  = await Auth.fetch('/api/v1/notifications/unread-count/');
      if (!res.ok) return;
      const data = await res.json();
      const cnt  = data.count || 0;
      if (this._badge) {
        this._badge.textContent   = cnt;
        this._badge.style.display = cnt > 0 ? 'flex' : 'none';
      }
    } catch (e) { /* silent */ }
  },

  async toggle() {
    const isOpen = this._dropdown.classList.contains('open');
    if (isOpen) { this.close(); return; }
    this._dropdown.classList.add('open');
    await this.load();
  },

  async load() {
    this._list.innerHTML = '<div class="notif-empty">Loading…</div>';
    try {
      const res  = await Auth.fetch('/api/v1/notifications/?page_size=20');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const items = data.results || data;
      if (!items.length) {
        this._list.innerHTML = '<div class="notif-empty">No notifications</div>';
        return;
      }
      this._list.innerHTML = items.map(n => `
        <div class="notif-item ${n.is_read ? 'read' : 'unread'}" onclick="Notifications.markRead(${n.id}, this)">
          <div class="notif-dot"></div>
          <div style="flex:1;">
            <div class="notif-text">${escHtml(n.message || n.title || '')}</div>
            <div class="notif-time">${n.created_at ? new Date(n.created_at).toLocaleString('en-GB',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : ''}</div>
          </div>
        </div>`).join('');
    } catch (e) {
      this._list.innerHTML = '<div class="notif-empty">Failed to load</div>';
    }
  },

  async markRead(id, el) {
    try {
      await Auth.fetch(`/api/v1/notifications/${id}/read/`, { method: 'POST' });
      el.classList.remove('unread');
      el.classList.add('read');
      this.poll();
    } catch (e) { /* silent */ }
  },

  async markAllRead() {
    try {
      await Auth.fetch('/api/v1/notifications/mark-all-read/', { method: 'POST' });
      document.querySelectorAll('.notif-item.unread').forEach(el => {
        el.classList.remove('unread');
        el.classList.add('read');
      });
      this.poll();
    } catch (e) { /* silent */ }
  },

  close() { this._dropdown.classList.remove('open'); },
};

// ─────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────
function typeTag(type) {
  if (!type) return '—';
  const cls = { INSTANT: 'type-instant', PRODUCTION: 'type-production', DESIGN: 'type-design' }[type] || '';
  return `<span class="type-badge ${cls}">${type}</span>`;
}

function escHtml(str) {
  return String(str ?? '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function closeNewJobModal()     { document.getElementById('new-job-modal').classList.remove('open'); }
function closeTransitionModal() { document.getElementById('transition-modal').classList.remove('open'); }

function showToast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  const toast     = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.textContent = msg;
  container.appendChild(toast);
  setTimeout(() => toast.remove(), 3500);
}