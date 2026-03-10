/**
 * Octos — Branch Manager Jobs
 * Handles: job list, filters, pagination, detail panel,
 *          new job modal with price calculation, status transitions
 */

'use strict';

// ─────────────────────────────────────────
// State
// ─────────────────────────────────────────
const State = {
  jobs:        [],
  filtered:    [],
  page:        1,
  pageSize:    20,
  totalCount:  0,
  status:      'all',
  jobType:     '',
  searchQuery: '',
  activeJobId: null,
  services:    [],
  customers:   [],
  priceTimer:  null,
};

const STATUS_TRANSITIONS = {
  PENDING:     ['IN_PROGRESS', 'CANCELLED'],
  IN_PROGRESS: ['READY', 'CANCELLED'],
  READY:       ['COMPLETED', 'IN_PROGRESS'],
  COMPLETED:   [],
  CANCELLED:   [],
};

const STATUS_LABELS = {
  PENDING:     'Pending',
  IN_PROGRESS: 'In Progress',
  READY:       'Ready for Pickup',
  COMPLETED:   'Completed',
  CANCELLED:   'Cancelled',
};

// ─────────────────────────────────────────
// Bootstrap
// ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  Auth.guard();
  loadJobs();
  loadServices();
  loadCustomers();
  bindFilters();
  bindNewJobModal();
  bindTransitionModal();
  bindModalClose();
});

// ─────────────────────────────────────────
// Load Jobs
// ─────────────────────────────────────────
async function loadJobs() {
  setTableLoading();

  const params = new URLSearchParams();
  params.set('page', State.page);
  params.set('page_size', State.pageSize);
  if (State.status   && State.status !== 'all') params.set('status', State.status);
  if (State.jobType)   params.set('job_type', State.jobType);
  if (State.searchQuery) params.set('search', State.searchQuery);

  try {
    const res  = await Auth.fetch(`/api/v1/jobs/?${params}`);
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();

    if (Array.isArray(data)) {
      State.jobs       = data;
      State.totalCount = data.length;
    } else {
      State.jobs       = data.results || [];
      State.totalCount = data.count   || 0;
    }

    renderJobs();
    renderPagination();
    computeStats();
  } catch {
    document.getElementById('jobs-tbody').innerHTML = `
      <tr><td colspan="8" style="text-align:center;padding:40px;color:var(--text-muted);">
        Could not load jobs. <a href="#" onclick="loadJobs()" style="color:var(--yellow);">Retry</a>
      </td></tr>`;
  }
}

// ─────────────────────────────────────────
// Render Jobs Table
// ─────────────────────────────────────────
function renderJobs() {
  const tbody = document.getElementById('jobs-tbody');

  if (!State.jobs.length) {
    tbody.innerHTML = `
      <tr><td colspan="8" style="text-align:center;padding:60px;">
        <div class="empty-state" style="padding:0;">
          <div class="empty-icon" style="margin:0 auto 12px;">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </div>
          <h4>No jobs found</h4>
          <p>Try adjusting filters or create a new job.</p>
        </div>
      </td></tr>`;
    return;
  }

  tbody.innerHTML = State.jobs.map(j => `
    <tr style="cursor:pointer;" onclick="openJobDetail(${j.id})">
      <td class="td-primary" style="font-family:var(--font-mono);font-size:12.5px;">${escHtml(j.reference || '#' + j.id)}</td>
      <td>${escHtml(j.customer_name || j.customer || '—')}</td>
      <td><span class="badge badge-grey">${escHtml(j.job_type || '—')}</span></td>
      <td style="color:var(--text-secondary);">${escHtml(j.service_name || j.service || '—')}</td>
      <td>${statusBadge(j.status)}</td>
      <td style="font-family:var(--font-mono);color:var(--yellow);">${j.final_price != null ? Number(j.final_price).toFixed(2) : '—'}</td>
      <td style="color:var(--text-muted);font-size:12.5px;">${formatDate(j.created_at)}</td>
      <td onclick="event.stopPropagation()">
        <button class="btn btn-ghost btn-sm btn-icon" title="View details" onclick="openJobDetail(${j.id})">
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
        </button>
      </td>
    </tr>`).join('');
}

// ─────────────────────────────────────────
// Compute & Display Stats
// ─────────────────────────────────────────
function computeStats() {
  const jobs = State.jobs;

  document.getElementById('stat-total').textContent      = State.totalCount;
  document.getElementById('stat-inprogress').textContent = jobs.filter(j => j.status === 'IN_PROGRESS').length;
  document.getElementById('stat-done').textContent       = jobs.filter(j => j.status === 'COMPLETED').length;

  const revenue = jobs
    .filter(j => j.status === 'COMPLETED')
    .reduce((sum, j) => sum + (parseFloat(j.final_price) || 0), 0);

  document.getElementById('stat-revenue').textContent = revenue >= 1000
    ? (revenue / 1000).toFixed(1) + 'k'
    : revenue.toFixed(0);
}

// ─────────────────────────────────────────
// Pagination
// ─────────────────────────────────────────
function renderPagination() {
  const total = State.totalCount;
  const from  = (State.page - 1) * State.pageSize + 1;
  const to    = Math.min(State.page * State.pageSize, total);

  document.getElementById('pagination-info').textContent =
    total ? `Showing ${from}–${to} of ${total} jobs` : 'No jobs';

  const prevBtn = document.getElementById('btn-prev');
  const nextBtn = document.getElementById('btn-next');
  prevBtn.disabled = State.page <= 1;
  nextBtn.disabled = to >= total;
}

// ─────────────────────────────────────────
// Job Detail Panel
// ─────────────────────────────────────────
async function openJobDetail(id) {
  State.activeJobId = id;
  const overlay = document.getElementById('job-detail-overlay');
  overlay.classList.add('open');

  // Clear and show loading
  document.getElementById('detail-ref').textContent      = 'Loading…';
  document.getElementById('detail-status-badge').innerHTML = '';
  document.getElementById('detail-timeline').innerHTML   = '<div style="font-size:13px;color:var(--text-muted);">Loading…</div>';
  document.getElementById('detail-actions').innerHTML    = '';

  try {
    const res = await Auth.fetch(`/api/v1/jobs/${id}/`);
    if (!res.ok) throw new Error('Failed');
    const job = await res.json();
    populateJobDetail(job);
  } catch {
    document.getElementById('detail-ref').textContent = 'Could not load job';
  }
}

function closeJobDetail(event) {
  if (event && event.target !== document.getElementById('job-detail-overlay')) return;
  document.getElementById('job-detail-overlay').classList.remove('open');
  State.activeJobId = null;
}

function populateJobDetail(job) {
  document.getElementById('detail-ref').textContent      = job.reference || `#${job.id}`;
  document.getElementById('detail-status-badge').innerHTML = statusBadge(job.status);
  document.getElementById('detail-customer').textContent = job.customer_name || job.customer || '—';
  document.getElementById('detail-service').textContent  = job.service_name  || job.service  || '—';
  document.getElementById('detail-type').textContent     = job.job_type || '—';
  document.getElementById('detail-qty').textContent      = job.quantity  != null ? job.quantity : '—';
  document.getElementById('detail-price').textContent    = job.final_price != null ? `GHS ${Number(job.final_price).toFixed(2)}` : '—';
  document.getElementById('detail-branch').textContent   = job.branch_name || job.branch || '—';
  document.getElementById('detail-created').textContent  = formatDateFull(job.created_at);

  const notesSection = document.getElementById('detail-notes-section');
  const notesEl      = document.getElementById('detail-notes');
  if (job.notes) {
    notesSection.style.display = 'block';
    notesEl.textContent        = job.notes;
  } else {
    notesSection.style.display = 'none';
  }

  // Timeline
  const timeline = document.getElementById('detail-timeline');
  const logs     = job.status_logs || [];
  if (logs.length) {
    timeline.innerHTML = logs.map((log, i) => `
      <div class="timeline-item">
        <div class="timeline-dot ${i === 0 ? 'active' : 'done'}"></div>
        <div class="timeline-content">
          <div class="timeline-label">${STATUS_LABELS[log.status] || log.status}</div>
          <div class="timeline-meta">${formatDateFull(log.created_at)}${log.note ? ' · ' + escHtml(log.note) : ''}</div>
        </div>
      </div>`).join('');
  } else {
    timeline.innerHTML = `<div style="font-size:13px;color:var(--text-muted);">No status history.</div>`;
  }

  // Actions
  const actionsEl   = document.getElementById('detail-actions');
  const transitions = STATUS_TRANSITIONS[job.status] || [];

  if (transitions.length) {
    actionsEl.innerHTML = `
      <button class="btn btn-yellow" onclick="openTransitionModal(${job.id}, '${job.status}')">
        <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        Update Status
      </button>`;
  } else {
    actionsEl.innerHTML = `<p style="font-size:13px;color:var(--text-muted);">No further actions available.</p>`;
  }
}

// ─────────────────────────────────────────
// Status Transitions
// ─────────────────────────────────────────
function openTransitionModal(jobId, currentStatus) {
  const transitions = STATUS_TRANSITIONS[currentStatus] || [];
  if (!transitions.length) return;

  const select = document.getElementById('transition-status');
  select.innerHTML = transitions
    .map(s => `<option value="${s}">${STATUS_LABELS[s] || s}</option>`)
    .join('');

  document.getElementById('transition-note').value = '';

  // Store job id for confirm
  document.getElementById('btn-confirm-transition').dataset.jobId = jobId;

  openModal('transition-modal');
}

function bindTransitionModal() {
  document.getElementById('btn-confirm-transition').addEventListener('click', async () => {
    const jobId  = document.getElementById('btn-confirm-transition').dataset.jobId;
    const status = document.getElementById('transition-status').value;
    const note   = document.getElementById('transition-note').value.trim();

    if (!jobId || !status) return;

    const btn = document.getElementById('btn-confirm-transition');
    btn.disabled = true;
    btn.innerHTML = `<div class="spinner spinner-sm"></div> Updating…`;

    try {
      const res = await Auth.fetch(`/api/v1/jobs/${jobId}/transition/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ status, note }),
      });
      if (!res.ok) throw new Error('Failed');
      closeModal('transition-modal');
      closeJobDetail();
      toast(`Status updated to ${STATUS_LABELS[status]}`, 'success');
      loadJobs();
    } catch {
      toast('Could not update status', 'error');
    } finally {
      btn.disabled = false;
      btn.textContent = 'Update Status';
    }
  });
}

// ─────────────────────────────────────────
// New Job Modal
// ─────────────────────────────────────────
function bindNewJobModal() {
  document.getElementById('btn-new-job').addEventListener('click', () => {
    resetNewJobForm();
    openModal('new-job-modal');
  });
  document.getElementById('btn-create-job').addEventListener('click', createJob);
  document.getElementById('nj-qty').addEventListener('input', () => {
    clearTimeout(State.priceTimer);
    State.priceTimer = setTimeout(calculatePrice, 350);
  });
}

function resetNewJobForm() {
  ['nj-customer', 'nj-service', 'nj-notes'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.value = '';
  });
  document.getElementById('nj-type').value      = 'INSTANT';
  document.getElementById('nj-qty').value       = '1';
  document.getElementById('price-preview').style.display = 'none';
}

async function loadServices() {
  try {
    const res = await Auth.fetch('/api/v1/jobs/services/');
    if (!res.ok) return;
    const data = await res.json();
    State.services = Array.isArray(data) ? data : (data.results || []);

    const select = document.getElementById('nj-service');
    if (select) {
      select.innerHTML = '<option value="">Select service…</option>' +
        State.services.map(s => `<option value="${s.id}">${escHtml(s.name)}</option>`).join('');
    }
  } catch { /* silent */ }
}

async function loadCustomers() {
  try {
    const res = await Auth.fetch('/api/v1/customers/');
    if (!res.ok) return;
    const data = await res.json();
    State.customers = Array.isArray(data) ? data : (data.results || []);

    const select = document.getElementById('nj-customer');
    if (select) {
      select.innerHTML = '<option value="">Select customer…</option>' +
        State.customers.map(c => `<option value="${c.id}">${escHtml(c.name || c.company_name || c.email)}</option>`).join('');
    }
  } catch { /* silent */ }
}

async function calculatePrice() {
  const serviceId = document.getElementById('nj-service').value;
  const qty       = parseInt(document.getElementById('nj-qty').value) || 1;
  const preview   = document.getElementById('price-preview');

  if (!serviceId) { preview.style.display = 'none'; return; }

  try {
    const res = await Auth.fetch('/api/v1/jobs/price/calculate/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ service: serviceId, quantity: qty }),
    });
    if (!res.ok) throw new Error('Failed');
    const data = await res.json();

    document.getElementById('price-amount').textContent = `GHS ${Number(data.total || data.price || 0).toFixed(2)}`;
    document.getElementById('price-breakdown').textContent = data.breakdown || '';
    preview.style.display = 'block';
  } catch {
    preview.style.display = 'none';
  }
}

async function createJob() {
  const customer = document.getElementById('nj-customer').value;
  const service  = document.getElementById('nj-service').value;
  const jobType  = document.getElementById('nj-type').value;
  const qty      = document.getElementById('nj-qty').value;
  const notes    = document.getElementById('nj-notes').value.trim();

  if (!customer || !service) {
    toast('Customer and Service are required', 'error');
    return;
  }

  const btn = document.getElementById('btn-create-job');
  btn.disabled = true;
  btn.innerHTML = `<div class="spinner spinner-sm"></div> Creating…`;

  try {
    const res = await Auth.fetch('/api/v1/jobs/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        customer,
        service,
        job_type: jobType,
        quantity: qty,
        notes: notes || undefined,
      }),
    });
    if (!res.ok) throw new Error('Failed');
    closeModal('new-job-modal');
    toast('Job created successfully', 'success');
    State.page = 1;
    loadJobs();
  } catch {
    toast('Could not create job', 'error');
  } finally {
    btn.disabled = false;
    btn.innerHTML = `
      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
      Create Job`;
  }
}

// ─────────────────────────────────────────
// Filters
// ─────────────────────────────────────────
function bindFilters() {
  // Status tabs
  document.getElementById('status-filters').addEventListener('click', e => {
    const tab = e.target.closest('.filter-tab');
    if (!tab) return;
    document.querySelectorAll('#status-filters .filter-tab').forEach(t => t.classList.remove('active'));
    tab.classList.add('active');
    State.status = tab.dataset.status;
    State.page   = 1;
    loadJobs();
  });

  // Type filter
  document.getElementById('jobs-type-filter').addEventListener('change', e => {
    State.jobType = e.target.value;
    State.page    = 1;
    loadJobs();
  });

  // Search
  let searchTimer;
  document.getElementById('jobs-search').addEventListener('input', e => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      State.searchQuery = e.target.value.trim();
      State.page        = 1;
      loadJobs();
    }, 350);
  });

  // Pagination
  document.getElementById('btn-prev').addEventListener('click', () => {
    if (State.page > 1) { State.page--; loadJobs(); }
  });
  document.getElementById('btn-next').addEventListener('click', () => {
    const maxPage = Math.ceil(State.totalCount / State.pageSize);
    if (State.page < maxPage) { State.page++; loadJobs(); }
  });
}

// ─────────────────────────────────────────
// Modal Helpers
// ─────────────────────────────────────────
function openModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('open');
}

function closeModal(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('open');
}

function bindModalClose() {
  document.querySelectorAll('.modal-overlay').forEach(overlay => {
    overlay.addEventListener('click', e => {
      if (e.target === overlay) overlay.classList.remove('open');
    });
  });
}

// ─────────────────────────────────────────
// Toast
// ─────────────────────────────────────────
function toast(msg, type = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${type}`;
  const icons = {
    success: `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>`,
    error:   `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
    info:    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>`,
  };
  el.innerHTML = (icons[type] || icons.info) + `<span>${escHtml(msg)}</span>`;
  container.appendChild(el);
  setTimeout(() => el.remove(), 3500);
}

// ─────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────
function setTableLoading() {
  document.getElementById('jobs-tbody').innerHTML = `
    <tr class="loading-row">
      <td colspan="8">
        <div class="spinner" style="margin:0 auto 10px;"></div>
        Loading jobs…
      </td>
    </tr>`;
}

function statusBadge(status) {
  const map = {
    PENDING:     'badge-yellow',
    IN_PROGRESS: 'badge-red',
    READY:       'badge-green',
    COMPLETED:   'badge-green',
    CANCELLED:   'badge-grey',
  };
  const cls  = map[status] || 'badge-grey';
  const label = STATUS_LABELS[status] || status || '—';
  return `<span class="badge ${cls}">${escHtml(label)}</span>`;
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function formatDate(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
}

function formatDateFull(iso) {
  if (!iso) return '—';
  return new Date(iso).toLocaleString('en-GB', {
    day: 'numeric', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  });
}