/**
 * Octos — Branch Manager Dashboard
 * Handles: boot, stats, meta, recent jobs,
 *          jobs tab, inbox tab, services tab,
 *          new job modal with price calculation
 */

'use strict';

const Dashboard = (() => {

  // ─────────────────────────────────────────
  // State
  // ─────────────────────────────────────────
  let services    = [];
  let jobsLoaded  = false;
  let inboxLoaded = false;
  let svcLoaded   = false;
  let priceTimer  = null;

  const STATUS_LABELS = {
    PENDING:     'Pending',
    IN_PROGRESS: 'In Progress',
    READY:       'Ready',
    COMPLETED:   'Completed',
    CANCELLED:   'Cancelled',
  };

  // ─────────────────────────────────────────
  // Boot
  // ─────────────────────────────────────────
  async function init() {
    Auth.guard();
    setDate();
    await Promise.all([
      loadUser(),
      loadStats(),
      loadRecentJobs(),
      loadServices(),
    ]);
  }

  // ─────────────────────────────────────────
  // User
  // ─────────────────────────────────────────
  async function loadUser() {
    try {
      const res  = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const user = await res.json();

      const fullName = user.full_name || user.email || '—';
      const initials = fullName.split(' ').slice(0, 2)
        .map(w => w[0]?.toUpperCase() || '').join('');

      set('db-user-name',     fullName);
      set('db-user-initials', initials);

      // Branch - may be bare ID, object, or null
      if (user.branch && typeof user.branch === 'object') {
        set('db-branch-name', user.branch.name);
        if (user.branch.region_name) set('meta-region', user.branch.region_name);
      } else if (user.branch && typeof user.branch === 'number') {
        const br = await Auth.fetch('/api/v1/organization/branches/' + user.branch + '/');
        if (br.ok) {
          const branch = await br.json();
          set('db-branch-name', branch.name);
          if (branch.region_name)    set('meta-region', branch.region_name);
          if (branch.belt_name)      set('meta-belt',   branch.belt_name);
          if (branch.load_percentage != null) set('meta-load', branch.load_percentage + '%');
        }
      }
    } catch { /* silent */ }
  }

  // ─────────────────────────────────────────
  // Stats
  // ─────────────────────────────────────────
  async function loadStats() {
    try {
      const res  = await Auth.fetch('/api/v1/jobs/?page_size=200');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      const total      = data.count || jobs.length;
      const inProgress = jobs.filter(j => j.status === 'IN_PROGRESS').length;
      const complete   = jobs.filter(j => j.status === 'COMPLETED').length;
      const pending    = jobs.filter(j => j.status === 'PENDING').length;
      const routed     = jobs.filter(j => j.routed_to).length;

      set('stat-total-jobs',     total);
      set('stat-in-progress',    inProgress);
      set('stat-complete',       complete);
      set('stat-pending-payment',pending);
      set('stat-routed',         routed);

      // Tab badge
      const jobsBadge = document.getElementById('tab-count-jobs');
      if (jobsBadge && total > 0) {
        jobsBadge.textContent = total;
        jobsBadge.classList.add('show');
      }

      // Branch load (in-progress / total)
      const load = total > 0 ? Math.round((inProgress / total) * 100) + '%' : '0%';
      set('meta-load', load);

    } catch { /* silent */ }

    // Unread messages
    try {
      const res  = await Auth.fetch('/api/v1/communications/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const convos  = Array.isArray(data) ? data : (data.results || []);
      const unread  = convos.reduce((sum, c) => sum + (c.unread_count || 0), 0);

      set('stat-unread', unread);

      const inboxBadge = document.getElementById('tab-count-inbox');
      if (inboxBadge && unread > 0) {
        inboxBadge.textContent = unread;
        inboxBadge.classList.add('show');
      }

      // Notif badge
      if (unread > 0) {
        const badge = document.getElementById('db-notif-badge');
        if (badge) {
          badge.textContent = unread;
          badge.style.display = 'flex';
        }
      }

    } catch { /* silent */ }
  }

  // ─────────────────────────────────────────
  // Recent Jobs (Overview tab)
  // ─────────────────────────────────────────
  async function loadRecentJobs() {
    const tbody = document.getElementById('recent-jobs-tbody');
    if (!tbody) return;

    try {
      const res  = await Auth.fetch('/api/v1/jobs/?page_size=10');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const jobs = Array.isArray(data) ? data : (data.results || []);

      if (!jobs.length) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:#ccc;font-size:13px;">No jobs yet.</td></tr>`;
        return;
      }

      tbody.innerHTML = jobs.map(j => `
        <tr onclick="window.location='/portal/jobs/'">
          <td class="td-bold" style="font-family:monospace;font-size:12.5px;">${esc(j.reference || '#' + j.id)}</td>
          <td>${esc(j.title || j.service_name || '—')}</td>
          <td>${typeBadge(j.job_type)}</td>
          <td>${statusBadge(j.status)}</td>
          <td style="font-family:monospace;">${j.final_price != null ? 'GHS ' + Number(j.final_price).toFixed(2) : '—'}</td>
          <td>${j.routed_to ? `<span style="font-size:12px;color:#888;">→ ${esc(j.routed_to_name || j.routed_to)}</span>` : '<span style="color:#ccc;font-size:12px;">Local</span>'}</td>
        </tr>`).join('');

    } catch {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:#ccc;font-size:13px;">Could not load jobs.</td></tr>`;
    }
  }

  // ─────────────────────────────────────────
  // Jobs Tab (lazy)
  // ─────────────────────────────────────────
  async function loadJobsTab() {
    if (jobsLoaded) return;
    jobsLoaded = true;

    const tbody = document.getElementById('jobs-tab-tbody');
    if (!tbody) return;

    const render = async () => {
      const search = document.getElementById('jobs-search')?.value.trim() || '';
      const status = document.getElementById('jobs-status')?.value || '';

      tbody.innerHTML = `<tr><td colspan="6" class="loading-cell"><span class="spin"></span> Loading…</td></tr>`;

      const params = new URLSearchParams({ page_size: 50 });
      if (search) params.set('search', search);
      if (status) params.set('status', status);

      try {
        const res  = await Auth.fetch(`/api/v1/jobs/?${params}`);
        if (!res.ok) throw new Error();
        const data = await res.json();
        const jobs = Array.isArray(data) ? data : (data.results || []);

        if (!jobs.length) {
          tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:#ccc;font-size:13px;">No jobs found.</td></tr>`;
          return;
        }

        tbody.innerHTML = jobs.map(j => `
          <tr onclick="window.location='/portal/jobs/'">
            <td class="td-bold" style="font-family:monospace;font-size:12.5px;">${esc(j.reference || '#' + j.id)}</td>
            <td>${esc(j.customer_name || j.customer || '—')}</td>
            <td>${esc(j.service_name || j.service || '—')}</td>
            <td>${statusBadge(j.status)}</td>
            <td style="font-family:monospace;">${j.final_price != null ? Number(j.final_price).toFixed(2) : '—'}</td>
            <td style="font-size:12.5px;color:#aaa;">${formatDate(j.created_at)}</td>
          </tr>`).join('');

      } catch {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:40px;color:#ccc;">Could not load.</td></tr>`;
      }
    };

    // Bind search/filter
    let searchTimer;
    document.getElementById('jobs-search')?.addEventListener('input', () => {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(render, 350);
    });
    document.getElementById('jobs-status')?.addEventListener('change', render);

    await render();
  }

  // ─────────────────────────────────────────
  // Inbox Tab (lazy)
  // ─────────────────────────────────────────
  async function loadInboxTab() {
    if (inboxLoaded) return;
    inboxLoaded = true;

    const list = document.getElementById('inbox-tab-list');
    if (!list) return;

    try {
      const res  = await Auth.fetch('/api/v1/communications/');
      if (!res.ok) throw new Error();
      const data = await res.json();
      const convos = Array.isArray(data) ? data : (data.results || []);

      if (!convos.length) {
        list.innerHTML = `<div style="text-align:center;padding:40px;color:#ccc;font-size:13px;">No conversations yet.</div>`;
        return;
      }

      list.innerHTML = convos.slice(0, 12).map(c => {
        const initials = getInitials(c.customer_name || 'Unknown');
        const time     = timeAgo(c.updated_at || c.created_at);
        const preview  = esc(truncate(c.last_message || 'No messages yet', 55));
        const hasUnread = c.unread_count > 0;

        return `
          <div class="inbox-row" onclick="window.location='/portal/inbox/'">
            <div class="inbox-av">${initials}</div>
            <span class="inbox-name">${esc(c.customer_name || 'Unknown')}</span>
            <span class="inbox-preview">${preview}</span>
            <span class="inbox-time">${time}</span>
            ${hasUnread ? '<span class="inbox-unread"></span>' : ''}
          </div>`;
      }).join('');

    } catch {
      list.innerHTML = `<div style="text-align:center;padding:40px;color:#ccc;font-size:13px;">Could not load inbox.</div>`;
    }
  }

  // ─────────────────────────────────────────
  // Services Tab (lazy) + modal population
  // ─────────────────────────────────────────
  async function loadServices() {
    try {
      const res  = await Auth.fetch('/api/v1/jobs/services/');
      if (!res.ok) return;
      const data = await res.json();
      services   = Array.isArray(data) ? data : (data.results || []);

      // Populate modal select
      const sel = document.getElementById('nj-service');
      if (sel) {
        sel.innerHTML = '<option value="">Select service…</option>' +
          services.map(s => `<option value="${s.id}">${esc(s.name)}</option>`).join('');
      }

      // Meta row count
      set('meta-services', services.length);

    } catch { /* silent */ }
  }

  async function loadServicesTab() {
    if (svcLoaded) return;
    svcLoaded = true;

    const grid = document.getElementById('services-grid');
    if (!grid) return;

    if (!services.length) {
      grid.innerHTML = `<div style="grid-column:1/-1;text-align:center;padding:40px;color:#ccc;font-size:13px;">No services available.</div>`;
      set('services-count', '0 services');
      return;
    }

    set('services-count', `${services.length} service${services.length !== 1 ? 's' : ''}`);

    grid.innerHTML = services.map(s => `
      <div class="service-card">
        <div class="service-card-name">${esc(s.name)}</div>
        <div class="service-card-price">${s.base_price != null ? 'GHS ' + Number(s.base_price).toFixed(2) : '—'}</div>
        <div class="service-card-desc">${esc(s.description || '')}</div>
      </div>`).join('');
  }

  // ─────────────────────────────────────────
  // Price Calculation
  // ─────────────────────────────────────────
  async function calculatePrice() {
    clearTimeout(priceTimer);
    priceTimer = setTimeout(_doCalculate, 400);
  }

  async function _doCalculate() {
    const serviceId = document.getElementById('nj-service')?.value;
    const qty       = parseInt(document.getElementById('nj-quantity')?.value) || 1;
    const pages     = parseInt(document.getElementById('nj-pages')?.value)    || 1;
    const color     = document.getElementById('nj-color')?.value === 'true';
    const priceBox  = document.getElementById('price-box');
    const priceEl   = document.getElementById('nj-price');

    if (!serviceId) {
      if (priceBox) priceBox.classList.remove('show');
      return;
    }

    try {
      const res = await Auth.fetch('/api/v1/jobs/price/calculate/', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ service: serviceId, quantity: qty, pages, color }),
      });

      if (!res.ok) throw new Error();
      const data = await res.json();

      if (priceEl)  priceEl.textContent = `GHS ${Number(data.total || data.price || 0).toFixed(2)}`;
      if (priceBox) priceBox.classList.add('show');

    } catch {
      if (priceBox) priceBox.classList.remove('show');
    }
  }

  // ─────────────────────────────────────────
  // Create Job
  // ─────────────────────────────────────────
  async function createJob() {
    const title    = document.getElementById('nj-title')?.value.trim();
    const type     = document.getElementById('nj-type')?.value;
    const service  = document.getElementById('nj-service')?.value;
    const priority = document.getElementById('nj-priority')?.value;
    const channel  = document.getElementById('nj-channel')?.value;
    const qty      = document.getElementById('nj-quantity')?.value;
    const pages    = document.getElementById('nj-pages')?.value;
    const color    = document.getElementById('nj-color')?.value === 'true';

    if (!service) { toast('Please select a service', 'error'); return; }

    const btn = document.querySelector('#new-job-modal .btn-dark');
    if (btn) { btn.disabled = true; btn.textContent = 'Creating…'; }

    try {
      const res = await Auth.fetch('/api/v1/jobs/', {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({
          title, job_type: type, service, priority,
          intake_channel: channel, quantity: qty, pages, color,
        }),
      });

      if (!res.ok) throw new Error('Failed');

      document.getElementById('new-job-modal')?.classList.remove('open');
      toast('Job created successfully', 'success');

      // Refresh
      jobsLoaded  = false;
      inboxLoaded = false;
      await Promise.all([loadStats(), loadRecentJobs()]);

    } catch {
      toast('Could not create job', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.innerHTML = `
        <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        Create Job`; }
    }
  }

  // ─────────────────────────────────────────
  // Helpers
  // ─────────────────────────────────────────
  function set(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function esc(str) {
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function truncate(str, len) {
    return str.length > len ? str.slice(0, len) + '…' : str;
  }

  function getInitials(name) {
    return name.split(' ').slice(0, 2).map(w => w[0]?.toUpperCase() || '').join('') || '?';
  }

  function setDate() {
    const now = new Date();
    set('meta-date', now.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' }));
  }

  function formatDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  }

  function timeAgo(iso) {
    if (!iso) return '—';
    const diff = Date.now() - new Date(iso).getTime();
    if (diff < 60000)    return 'just now';
    if (diff < 3600000)  return `${Math.floor(diff / 60000)}m`;
    if (diff < 86400000) return `${Math.floor(diff / 3600000)}h`;
    return formatDate(iso);
  }

  function statusBadge(status) {
    const map = {
      PENDING:     'badge-pending',
      IN_PROGRESS: 'badge-progress',
      READY:       'badge-ready',
      COMPLETED:   'badge-done',
      CANCELLED:   'badge-cancelled',
    };
    return `<span class="badge ${map[status] || 'badge-cancelled'}">${STATUS_LABELS[status] || status || '—'}</span>`;
  }

  function typeBadge(type) {
    const map = {
      INSTANT:    'badge-instant',
      PRODUCTION: 'badge-production',
      DESIGN:     'badge-design',
    };
    return `<span class="badge ${map[type] || 'badge-cancelled'}">${esc(type || '—')}</span>`;
  }

  function toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  // ─────────────────────────────────────────
  // Public API
  // ─────────────────────────────────────────
  return {
    init,
    loadJobsTab,
    loadInboxTab,
    loadServicesTab,
    calculatePrice,
    createJob,
  };

})();

document.addEventListener('DOMContentLoaded', Dashboard.init);