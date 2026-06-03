'use strict';

const Customers = (() => {

  // ── Private state ──────────────────────────────────────────
  let _customersTab = 'all';

  // ── Helpers ────────────────────────────────────────────────
  function _esc(str) {
    return String(str ?? '')
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function _fmt(n) {
    return `GHS ${parseFloat(n || 0).toLocaleString('en-GH', { minimumFractionDigits: 2 })}`;
  }

  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el = document.createElement('div');
    el.className = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  function _normalisePhone(raw) {
    let p = String(raw || '').replace(/[\s\-().]/g, '');
    if (p.startsWith('+233')) p = '0' + p.slice(4);
    if (p.startsWith('233') && p.length >= 12) p = '0' + p.slice(3);
    return p;
  }

  // ── Customers pane ─────────────────────────────────────────
  async function loadCustomersPane() {
    const pane = document.getElementById('pane-customers');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Customers</span>
        <button onclick="Customers.openAddCustomerModal()"
          style="padding:7px 16px;background:var(--text);color:#fff;border:none;
            border-radius:var(--radius-sm);font-size:13px;font-weight:700;
            cursor:pointer;font-family:'DM Sans',sans-serif;">
          + Add Customer
        </button>
      </div>
      <div class="reports-tabs" id="customers-tab-bar">
        <button class="reports-tab active" data-tab="all"
          onclick="Customers.switchCustomersTab('all')">All</button>
        <button class="reports-tab" data-tab="individuals"
          onclick="Customers.switchCustomersTab('individuals')">Individuals</button>
        <button class="reports-tab" data-tab="businesses"
          onclick="Customers.switchCustomersTab('businesses')">Businesses</button>
        <button class="reports-tab" data-tab="institutions"
          onclick="Customers.switchCustomersTab('institutions')">Institutions</button>
        <button class="reports-tab" data-tab="credit"
          onclick="Customers.switchCustomersTab('credit')">Credit Accounts</button>
      </div>
      <div id="customers-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    await _loadCustomersTab('all');
  }

  async function switchCustomersTab(tab) {
    _customersTab = tab;
    document.querySelectorAll('#customers-tab-bar .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    await _loadCustomersTab(tab);
  }

  async function _loadCustomersTab(tab) {
    const content = document.getElementById('customers-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    if (tab === 'all')          await _renderCustomerList(content, {});
    if (tab === 'individuals')  await _renderCustomerList(content, { customer_type: 'INDIVIDUAL' });
    if (tab === 'businesses')   await _renderCustomerList(content, { customer_type: 'BUSINESS' });
    if (tab === 'institutions') await _renderCustomerList(content, { customer_type: 'INSTITUTION' });
    if (tab === 'credit')       await _renderCreditCustomers(content);
  }

// ── Private pagination state ───────────────────────────────
  let _currentPage    = 1;
  let _currentSearch  = '';
  let _currentFilters = {};

  async function _renderCustomerList(container, filters = {}) {
    _currentPage    = 1;
    _currentFilters = filters;
    _currentSearch  = '';
    await _fetchAndRenderCustomers(container);
  }

  async function _fetchAndRenderCustomers(container) {
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';
    try {
      const PAGE_SIZE = 20;
      const params = new URLSearchParams(_currentFilters);
      params.set('page', _currentPage);
      params.set('page_size', PAGE_SIZE);
      if (_currentSearch) params.set('search', _currentSearch);

      const res  = await Auth.fetch(`/api/v1/customers/?${params}`);
      if (!res.ok) throw new Error();
      const data      = await res.json();
      const customers = data.results || [];
      const count     = data.count   || 0;
      const totalPages = Math.ceil(count / PAGE_SIZE);

      if (!customers.length && _currentPage === 1 && !_currentSearch) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32"
              viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1.5" style="opacity:0.3;display:block;margin:0 auto 12px;">
              <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/>
              <circle cx="9" cy="7" r="4"/>
            </svg>
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">No customers found</div>
            <div style="font-size:13px;">Add your first customer to get started.</div>
          </div>`;
        return;
      }

      if (!customers.length && (_currentSearch || _currentPage > 1)) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);font-size:13px;">
            No customers match your search.
          </div>`;
        return;
      }

      const typeConfig = {
        INDIVIDUAL : { label: 'Individual',  bg: '#f0f4fd', color: '#2e4a8a' },
        BUSINESS   : { label: 'Business',    bg: '#f0fdf4', color: '#1a6b3a' },
        INSTITUTION: { label: 'Institution', bg: '#f5f0fd', color: '#5a2e8a' },
      };
      const tierConfig = {
        REGULAR  : { label: 'Regular',   bg: 'var(--bg)',  color: 'var(--text-3)' },
        PREFERRED: { label: 'Preferred', bg: '#fef3c7',    color: '#d97706'       },
        VIP      : { label: 'VIP',       bg: '#fdf0f5',    color: '#8a1a4a'       },
      };
      const subtypeLabel = {
        SCHOOL: 'School', CHURCH: 'Church', NGO: 'NGO',
        GOVT: 'Government', OTHER: 'Institution',
      };

      const from = ((_currentPage - 1) * PAGE_SIZE) + 1;
      const to   = Math.min(_currentPage * PAGE_SIZE, count);

      container.innerHTML = `
        <!-- Search + stats row -->
        <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap;">
          <input type="text" id="customers-search"
            placeholder="Search by name or phone…"
            value="${_esc(_currentSearch)}"
            oninput="Customers.onSearchInput(this.value)"
            style="flex:1;min-width:200px;max-width:320px;padding:8px 14px;
              border:1.5px solid var(--border);border-radius:var(--radius-sm);
              background:var(--bg);color:var(--text);font-size:13px;
              font-family:'DM Sans',sans-serif;outline:none;box-sizing:border-box;">
          <span style="font-size:12px;color:var(--text-3);white-space:nowrap;">
            ${count} customer${count !== 1 ? 's' : ''}
            ${_currentSearch ? `matching "<strong>${_esc(_currentSearch)}</strong>"` : ''}
          </span>
        </div>

        <!-- Table -->
        <div style="background:var(--panel);border:1px solid var(--border);
          border-radius:var(--radius);overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);border-bottom:2px solid var(--border);">
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Customer</th>
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Phone</th>
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Type</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Visits</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Tier</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Score</th>
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Since</th>
                <th style="padding:10px 16px;"></th>
              </tr>
            </thead>
            <tbody>
              ${customers.map((c, idx) => {
                const tc  = typeConfig[c.customer_type]  || typeConfig.INDIVIDUAL;
                const trc = tierConfig[c.tier]           || tierConfig.REGULAR;
                const isIndividual = c.customer_type === 'INDIVIDUAL';
                const name = isIndividual
                  ? (c.full_name || c.display_name || '—')
                  : (c.display_name || '—');
                const sub = isIndividual ? '' : (c.full_name ? `Rep: ${c.full_name}` : '');
                const sinceDate = c.created_at
                  ? new Date(c.created_at).toLocaleDateString('en-GB',
                      { day: 'numeric', month: 'short', year: 'numeric' })
                  : '—';
                const scoreColor = c.confidence_score >= 70
                  ? '#16a34a' : c.confidence_score >= 40 ? '#d97706' : '#dc2626';
                const typeLabel = c.institution_subtype
                  ? subtypeLabel[c.institution_subtype] || tc.label
                  : tc.label;
                return `
                  <tr style="border-bottom:1px solid var(--border);
                    background:${idx % 2 === 0 ? '#fff' : '#fafafa'};
                    cursor:pointer;transition:background 0.12s;"
                    onmouseover="this.style.background='var(--bg)'"
                    onmouseout="this.style.background='${idx % 2 === 0 ? '#fff' : '#fafafa'}'"
                    onclick="Customers.openCustomerDetail(${c.id})">
                    <td style="padding:11px 16px;">
                      <div style="font-size:13px;font-weight:700;color:var(--text);">${_esc(name)}</div>
                      ${sub ? `<div style="font-size:11px;color:var(--text-3);margin-top:1px;">${_esc(sub)}</div>` : ''}
                    </td>
                    <td style="padding:11px 16px;font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-2);">${_esc(c.phone || '—')}</td>
                    <td style="padding:11px 16px;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;background:${tc.bg};color:${tc.color};">${typeLabel}</span>
                    </td>
                    <td style="padding:11px 16px;text-align:center;font-size:13px;font-weight:600;color:var(--text);">${c.visit_count || 0}</td>
                    <td style="padding:11px 16px;text-align:center;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;background:${trc.bg};color:${trc.color};">${trc.label}</span>
                    </td>
                    <td style="padding:11px 16px;text-align:center;">
                      <span style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:${scoreColor};">${c.confidence_score}</span>
                    </td>
                    <td style="padding:11px 16px;font-size:12px;color:var(--text-3);">${sinceDate}</td>
                    <td style="padding:11px 16px;text-align:right;">
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14"
                        viewBox="0 0 24 24" fill="none" stroke="currentColor"
                        stroke-width="2" style="color:var(--text-3);">
                        <polyline points="9 18 15 12 9 6"/>
                      </svg>
                    </td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>

        <!-- Pagination -->
        ${totalPages > 1 ? `
        <div style="display:flex;align-items:center;justify-content:space-between;
          padding:12px 4px;margin-top:8px;">
          <button onclick="Customers.changePage(-1)"
            ${_currentPage <= 1 ? 'disabled' : ''}
            style="padding:6px 16px;font-size:13px;font-weight:600;
              border:1px solid var(--border);border-radius:var(--radius-sm);
              background:var(--panel);color:var(--text-2);cursor:pointer;
              font-family:'DM Sans',sans-serif;
              opacity:${_currentPage <= 1 ? '0.4' : '1'};">
            ← Prev
          </button>
          <span style="font-size:12px;color:var(--text-3);
            font-family:'JetBrains Mono',monospace;">
            ${from}–${to} of ${count}
          </span>
          <button onclick="Customers.changePage(1)"
            ${_currentPage >= totalPages ? 'disabled' : ''}
            style="padding:6px 16px;font-size:13px;font-weight:600;
              border:1px solid var(--border);border-radius:var(--radius-sm);
              background:var(--panel);color:var(--text-2);cursor:pointer;
              font-family:'DM Sans',sans-serif;
              opacity:${_currentPage >= totalPages ? '0.4' : '1'};">
            Next →
          </button>
        </div>` : ''}`;

    } catch(e) {
      console.error('_fetchAndRenderCustomers error:', e);
      container.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">Could not load customers.</div>`;
    }
  }

  async function _renderCreditCustomers(container) {
    try {
      const res      = await Auth.fetch('/api/v1/customers/credit/');
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const accounts = Array.isArray(data) ? data : (data.results || []);

      if (!accounts.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">No credit accounts</div>
            <div style="font-size:13px;">Nominate a customer for credit from their profile.</div>
          </div>`;
        return;
      }

      const statusConfig = {
        ACTIVE   : { bg: '#dcfce7', color: '#16a34a', label: 'Active'    },
        PENDING  : { bg: '#fef3c7', color: '#d97706', label: 'Pending'   },
        SUSPENDED: { bg: '#fee2e2', color: '#dc2626', label: 'Suspended' },
        CLOSED   : { bg: '#f3f4f6', color: '#6b7280', label: 'Closed'    },
      };

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);border-bottom:2px solid var(--border);">
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Customer</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Limit</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Balance</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Available</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Usage</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;">Status</th>
              </tr>
            </thead>
            <tbody>
              ${accounts.map((a, idx) => {
                const sc       = statusConfig[a.status] || statusConfig.PENDING;
                const usagePct = a.utilisation_pct || 0;
                const usageColor = usagePct >= 90 ? '#dc2626' : usagePct >= 70 ? '#d97706' : '#16a34a';
                return `
                  <tr style="border-bottom:1px solid var(--border);background:${idx % 2 === 0 ? '#fff' : '#fafafa'};">
                    <td style="padding:11px 16px;">
                      <div style="display:flex;align-items:center;gap:8px;margin-bottom:3px;">
                        <span style="font-size:13px;font-weight:700;color:var(--text);">${_esc(a.customer_name || '—')}</span>
                        <span style="font-size:9px;font-weight:700;padding:1px 7px;border-radius:20px;
                          background:${a.account_type === 'BUSINESS' ? '#f0fdf4' : '#f0f4fd'};
                          color:${a.account_type === 'BUSINESS' ? '#1a6b3a' : '#2e4a8a'};">
                          ${a.account_type === 'BUSINESS' ? 'Business' : 'Individual'}
                        </span>
                      </div>
                      <div style="font-size:11px;color:var(--text-3);margin-bottom:2px;">
                        ${a.account_type === 'BUSINESS'
                          ? (a.contact_person ? `Rep: ${_esc(a.contact_person)} · ` : '')
                          : (a.customer_company ? `${_esc(a.customer_company)} · ` : '')}
                        <span style="font-family:'JetBrains Mono',monospace;">${_esc(a.customer_phone || '—')}</span>
                      </div>
                      ${a.customer_address ? `<div style="font-size:11px;color:var(--text-3);">${_esc(a.customer_address)}</div>` : ''}
                    </td>
                    <td style="padding:11px 16px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;color:var(--text);">${_fmt(a.credit_limit)}</td>
                    <td style="padding:11px 16px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:#dc2626;">${_fmt(a.current_balance)}</td>
                    <td style="padding:11px 16px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;color:#16a34a;font-weight:600;">${_fmt(a.available_credit)}</td>
                    <td style="padding:11px 16px;text-align:center;">
                      <div style="display:flex;align-items:center;gap:6px;justify-content:center;">
                        <div style="width:60px;height:4px;background:#f3f4f6;border-radius:2px;overflow:hidden;">
                          <div style="height:100%;width:${Math.min(100,usagePct).toFixed(1)}%;background:${usageColor};border-radius:2px;"></div>
                        </div>
                        <span style="font-size:11px;font-weight:600;color:${usageColor};">${usagePct.toFixed(0)}%</span>
                      </div>
                    </td>
                    <td style="padding:11px 16px;text-align:center;">
                      <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;background:${sc.bg};color:${sc.color};">${sc.label}</span>
                    </td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      container.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">Could not load credit accounts.</div>`;
    }
  }

  let _searchTimer = null;

  function onSearchInput(value) {
    clearTimeout(_searchTimer);
    _searchTimer = setTimeout(async () => {
      _currentSearch = _normalisePhone(value.trim()) !== value.trim()
        ? _normalisePhone(value.trim())
        : value.trim();
      _currentPage = 1;
      const content = document.getElementById('customers-content');
      if (content) await _fetchAndRenderCustomers(content);
    }, 350);
  }

  async function changePage(delta) {
    _currentPage += delta;
    const content = document.getElementById('customers-content');
    if (content) await _fetchAndRenderCustomers(content);
    // Scroll to top of pane
    document.getElementById('pane-customers')?.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // ── Customer detail overlay ────────────────────────────────
  async function openCustomerDetail(customerId) {
    const overlay = document.getElementById('customer-profile-overlay');
    const content = document.getElementById('customer-profile-content');
    if (!overlay || !content) return;

    overlay.style.display = 'block';
    content.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;
        min-height:100vh;color:var(--text-3);">
        <span class="spin"></span>
      </div>`;

    try {
      const [profileRes, jobsRes, creditRes] = await Promise.all([
        Auth.fetch(`/api/v1/customers/${customerId}/`),
        Auth.fetch(`/api/v1/jobs/?customer=${customerId}&page_size=100`),
        Auth.fetch(`/api/v1/customers/credit/`),
      ]);

      const customer = profileRes.ok ? await profileRes.json() : null;
      if (!customer) throw new Error();

      const jobsData   = jobsRes.ok   ? await jobsRes.json()   : { results: [] };
      const creditData = creditRes.ok ? await creditRes.json() : { results: [] };
      const jobs       = (jobsData.results || []).filter(j => j.customer == customerId);
      const credit     = (creditData.results || []).find(c => c.customer === customerId) || null;

      _renderCustomerProfile(content, customer, jobs, credit);

    } catch {
      content.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;
          min-height:100vh;flex-direction:column;gap:12px;color:var(--red-text);">
          <div>Could not load customer profile.</div>
          <button onclick="Customers.closeCustomerProfile()"
            style="padding:8px 20px;background:var(--text);color:#fff;border:none;
              border-radius:var(--radius-sm);cursor:pointer;font-family:inherit;">Close</button>
        </div>`;
    }
  }

  function _renderCustomerProfile(container, c, jobs, credit) {
    const isIndividual  = c.customer_type === 'INDIVIDUAL';
    const primaryName   = isIndividual ? (c.full_name || '—') : (c.company_name || '—');
    const secondaryName = isIndividual ? (c.company_name || '') : (c.full_name ? `Rep: ${c.full_name}` : '');

    const typeConfig = {
      INDIVIDUAL : { label: 'Individual',  bg: '#f0f4fd', color: '#2e4a8a' },
      BUSINESS   : { label: 'Business',    bg: '#f0fdf4', color: '#1a6b3a' },
      INSTITUTION: { label: 'Institution', bg: '#f5f0fd', color: '#5a2e8a' },
    };
    const tierConfig = {
      REGULAR  : { label: 'Regular',   color: '#6b7280' },
      PREFERRED: { label: 'Preferred', color: '#d97706' },
      VIP      : { label: 'VIP',       color: '#8a1a4a' },
    };
    const tc  = typeConfig[c.customer_type] || typeConfig.INDIVIDUAL;
    const trc = tierConfig[c.tier]          || tierConfig.REGULAR;

    const sinceDate  = c.created_at
      ? new Date(c.created_at).toLocaleDateString('en-GB', { day: 'numeric', month: 'long', year: 'numeric' })
      : '—';
    const initials   = primaryName.split(' ').slice(0,2).map(w => w[0]?.toUpperCase() || '').join('');
    const scoreColor = c.confidence_score >= 70 ? '#16a34a' : c.confidence_score >= 40 ? '#d97706' : '#dc2626';
    const totalSpent = jobs.reduce((s, j) => s + parseFloat(j.amount_paid||0), 0);
    const scoreToCredit = Math.max(0, 50 - c.confidence_score);

    const timelineHtml = !jobs.length ? `
      <div style="text-align:center;padding:48px 24px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);">
        <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          stroke-width="1.5" style="opacity:0.3;display:block;margin:0 auto 12px;color:var(--text-3);">
          <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/>
          <polyline points="14 2 14 8 20 8"/>
        </svg>
        <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:6px;">No Job History Available for ${_esc(primaryName)}</div>
        <div style="font-size:13px;color:var(--text-3);">Jobs linked to this customer will appear here once created.</div>
      </div>` : `
      <div style="position:relative;">
        ${jobs.map((j, idx) => {
          const dt        = new Date(j.created_at);
          const dateStr   = dt.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', year: 'numeric' });
          const timeStr   = dt.toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' });
          const services  = (j.line_items || []).map(li => li.service_name).join(', ') || '—';
          const isLast    = idx === jobs.length - 1;
          const statusColor = { COMPLETE: '#16a34a', CANCELLED: '#dc2626', IN_PROGRESS: '#d97706', PENDING_PAYMENT: '#d97706' }[j.status] || '#6b7280';
          const statusBg    = { COMPLETE: '#dcfce7', CANCELLED: '#fee2e2', IN_PROGRESS: '#fef3c7', PENDING_PAYMENT: '#fef3c7' }[j.status] || '#f3f4f6';
          const methodColor = { CASH: '#8a6a2e', MOMO: '#1a6b3a', POS: '#2e4a8a', CREDIT: '#8a1a4a' }[j.payment_method] || '#6b7280';
          const methodBg    = { CASH: '#fdf8f0', MOMO: '#f0fdf4', POS: '#f0f4fd', CREDIT: '#fdf0f5' }[j.payment_method] || '#f3f4f6';
          return `
            <div style="display:flex;gap:16px;margin-bottom:0;">
              <div style="display:flex;flex-direction:column;align-items:center;flex-shrink:0;width:32px;">
                <div style="width:12px;height:12px;border-radius:50%;background:${statusColor};border:2px solid #fff;box-shadow:0 0 0 2px ${statusColor};flex-shrink:0;margin-top:16px;"></div>
                ${!isLast ? `<div style="width:2px;flex:1;background:#e5e7eb;margin-top:4px;min-height:24px;"></div>` : ''}
              </div>
              <div style="flex:1;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:12px;">
                <div style="padding:10px 16px;background:var(--text);display:flex;align-items:center;justify-content:space-between;">
                  <div style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:#fff;">${_esc(j.job_number || '—')}</div>
                  <div style="display:flex;align-items:center;gap:6px;">
                    <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;background:rgba(255,255,255,0.15);color:#fff;">${j.job_type || '—'}</span>
                    <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;background:${statusBg};color:${statusColor};">${j.status.replace(/_/g,' ')}</span>
                  </div>
                </div>
                <div style="padding:12px 16px;">
                  <div style="font-size:13px;font-weight:600;color:var(--text);margin-bottom:10px;">${_esc(services)}</div>
                  <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-bottom:10px;">
                    <div>
                      <div style="font-size:9px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.4px;margin-bottom:2px;">Date & Time</div>
                      <div style="font-size:11px;color:var(--text-2);">${dateStr}</div>
                      <div style="font-size:10px;color:var(--text-3);">${timeStr}</div>
                    </div>
                    <div>
                      <div style="font-size:9px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.4px;margin-bottom:2px;">Attendant</div>
                      <div style="font-size:11px;color:var(--text-2);">${_esc(j.intake_by_name || '—')}</div>
                    </div>
                    <div>
                      <div style="font-size:9px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.4px;margin-bottom:2px;">Amount</div>
                      <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:800;color:var(--text);">${_fmt(j.amount_paid)}</div>
                    </div>
                  </div>
                  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
                    ${j.payment_method ? `<span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;background:${methodBg};color:${methodColor};">${j.payment_method}</span>` : ''}
                    ${j.is_routed ? `<span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;background:#f5f0fd;color:#5a2e8a;">→ Routed</span>` : ''}
                  </div>
                </div>
              </div>
            </div>`;
        }).join('')}
      </div>`;

    container.innerHTML = `
      <!-- Topbar -->
      <div style="display:flex;align-items:center;justify-content:space-between;
        padding:14px 28px;border-bottom:1px solid var(--border);
        background:var(--panel);position:sticky;top:0;z-index:10;">
        <div style="display:flex;align-items:center;gap:12px;">
          <button onclick="Customers.closeCustomerProfile()"
            style="display:flex;align-items:center;gap:6px;padding:7px 14px;
              background:none;border:1px solid var(--border);border-radius:var(--radius-sm);
              font-size:13px;font-weight:600;cursor:pointer;color:var(--text-2);font-family:inherit;">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
            </svg>
            Back
          </button>
          <span style="font-size:13px;color:var(--text-3);">Customer Profile</span>
        </div>
        <div style="display:flex;gap:8px;">
          <button onclick="Customers.editCustomer(${c.id})"
            style="padding:7px 16px;background:none;border:1px solid var(--border);
              border-radius:var(--radius-sm);font-size:13px;font-weight:600;
              cursor:pointer;color:var(--text-2);font-family:inherit;">
            Edit Profile
          </button>
          ${!credit && c.confidence_score >= 50 ? `
          <button onclick="Customers.nominateCredit(${c.id})"
            style="padding:7px 16px;background:#16a34a;color:#fff;border:none;
              border-radius:var(--radius-sm);font-size:13px;font-weight:700;
              cursor:pointer;font-family:inherit;">
            Nominate for Credit
          </button>` : ''}
        </div>
      </div>

      <!-- Scrollable body -->
      <div style="max-height:calc(100vh - 120px);overflow-y:auto;">
      <div style="max-width:800px;margin:0 auto;padding:32px 28px;">

        <!-- Profile header -->
        <div style="display:flex;align-items:flex-start;gap:24px;margin-bottom:32px;">
          <div style="position:relative;flex-shrink:0;">
            <svg width="80" height="80" viewBox="0 0 80 80">
              <circle cx="40" cy="40" r="34" fill="none" stroke="#f3f4f6" stroke-width="4"/>
              <circle cx="40" cy="40" r="34" fill="none" stroke="${scoreColor}" stroke-width="4"
                stroke-dasharray="${2 * Math.PI * 34}"
                stroke-dashoffset="${2 * Math.PI * 34 * (1 - c.confidence_score / 100)}"
                stroke-linecap="round" transform="rotate(-90 40 40)"/>
            </svg>
            <div style="position:absolute;inset:0;display:flex;align-items:center;justify-content:center;">
              <div style="width:60px;height:60px;border-radius:50%;background:var(--text);
                display:flex;align-items:center;justify-content:center;
                font-family:'Syne',sans-serif;font-size:20px;font-weight:800;color:#fff;">
                ${initials}
              </div>
            </div>
          </div>
          <div style="flex:1;">
            <div style="font-family:'Syne',sans-serif;font-size:24px;font-weight:800;
              color:var(--text);letter-spacing:-0.4px;margin-bottom:4px;">${_esc(primaryName)}</div>
            ${secondaryName ? `<div style="font-size:13px;color:var(--text-3);margin-bottom:8px;">${_esc(secondaryName)}</div>` : ''}
            <div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap;margin-bottom:12px;">
              <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;background:${tc.bg};color:${tc.color};">${tc.label}</span>
              <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;background:var(--bg);color:${trc.color};border:1px solid var(--border);">${trc.label}</span>
              ${credit ? `<span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;background:#fdf0f5;color:#8a1a4a;">💳 Credit Account</span>` : ''}
            </div>
            <div style="display:flex;gap:20px;flex-wrap:wrap;">
              ${[['Customer since', sinceDate], ['Total visits', c.visit_count || 0], ['Jobs on record', jobs.length], ['Lifetime spend', _fmt(totalSpent)]].map(([label, val]) => `
                <div>
                  <div style="font-size:10px;color:var(--text-3);margin-bottom:1px;">${label}</div>
                  <div style="font-size:13px;font-weight:700;color:var(--text);">${val}</div>
                </div>`).join('')}
            </div>
          </div>
        </div>

        <!-- Info grid -->
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:24px;">
          <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">Contact Details</div>
            ${[['Phone', c.phone || '—'], ['Email', c.email || '—'], ['Address', c.address || '—']].map(([label, val]) => `
              <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);">
                <span style="font-size:12px;color:var(--text-3);">${label}</span>
                <span style="font-size:12px;font-weight:500;color:${val === '—' ? 'var(--text-3)' : 'var(--text)'};">${_esc(val)}</span>
              </div>`).join('')}
          </div>
          <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;">
            ${credit ? `
              <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">Credit Account</div>
              ${[['Limit', _fmt(credit.credit_limit)], ['Balance', _fmt(credit.current_balance)], ['Available', _fmt(credit.available_credit)], ['Terms', `${credit.payment_terms} days`], ['Status', credit.status]].map(([label, val]) => `
                <div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border);">
                  <span style="font-size:12px;color:var(--text-3);">${label}</span>
                  <span style="font-size:12px;font-weight:600;color:${label==='Balance'?'#dc2626':label==='Available'?'#16a34a':'var(--text)'};">${_esc(String(val))}</span>
                </div>`).join('')}
              <div style="margin-top:10px;">
                <div style="height:4px;background:#f3f4f6;border-radius:2px;overflow:hidden;">
                  <div style="height:100%;width:${Math.min(100,credit.utilisation_pct).toFixed(1)}%;background:${credit.utilisation_pct>=90?'#dc2626':credit.utilisation_pct>=70?'#d97706':'#16a34a'};border-radius:2px;"></div>
                </div>
                <div style="font-size:10px;color:var(--text-3);margin-top:3px;text-align:right;">${credit.utilisation_pct.toFixed(0)}% utilised</div>
              </div>` : `
              <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">Credit Eligibility</div>
              <div style="margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;margin-bottom:6px;">
                  <span style="font-size:12px;color:var(--text-2);">Confidence Score</span>
                  <span style="font-size:13px;font-weight:700;color:${scoreColor};">${c.confidence_score} / 100</span>
                </div>
                <div style="height:6px;background:#f3f4f6;border-radius:3px;overflow:hidden;">
                  <div style="height:100%;width:${c.confidence_score}%;background:${scoreColor};border-radius:3px;"></div>
                </div>
              </div>
              <div style="font-size:12px;color:var(--text-3);">
                ${c.confidence_score >= 50 ? '✓ Eligible — use Nominate for Credit button above' : `Needs <strong style="color:var(--text);">${scoreToCredit} more points</strong> to reach credit threshold`}
              </div>`}
          </div>
        </div>

        <!-- BM Notes -->
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px 18px;margin-bottom:24px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;">Branch Manager Notes</div>
          <textarea id="customer-notes-${c.id}" rows="3"
            placeholder="Add notes about this customer…"
            onblur="Customers.saveCustomerNotes(${c.id})"
            style="width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:var(--radius-sm);
              background:var(--bg);color:var(--text);font-size:13px;resize:vertical;
              box-sizing:border-box;font-family:'DM Sans',sans-serif;outline:none;">${_esc(c.notes || '')}</textarea>
          <div style="font-size:10px;color:var(--text-3);margin-top:4px;">Auto-saves when you click away</div>
        </div>

        <!-- Job History -->
        <div style="margin-bottom:32px;">
          <div style="font-family:'Syne',sans-serif;font-size:17px;font-weight:800;color:var(--text);
            letter-spacing:-0.2px;margin-bottom:16px;display:flex;align-items:center;gap:10px;">
            Job History
            <span style="font-size:12px;font-weight:400;color:var(--text-3);font-family:'DM Sans',sans-serif;">
              ${jobs.length} job${jobs.length !== 1 ? 's' : ''} on record
            </span>
          </div>
          ${timelineHtml}
        </div>

      </div>
      </div>`;
  }

  function closeCustomerProfile() {
    const overlay = document.getElementById('customer-profile-overlay');
    if (overlay) overlay.style.display = 'none';
  }

  async function saveCustomerNotes(customerId) {
    const textarea = document.getElementById(`customer-notes-${customerId}`);
    if (!textarea) return;
    try {
      await Auth.fetch(`/api/v1/customers/${customerId}/`, {
        method : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ notes: textarea.value.trim() }),
      });
    } catch { /* silent */ }
  }

  // ── Edit customer ──────────────────────────────────────────
  async function editCustomer(customerId) {
    const content = document.getElementById('customer-profile-content');
    if (!content) return;

    content.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;color:var(--text-3);">
        <span class="spin"></span>
      </div>`;

    try {
      const res = await Auth.fetch(`/api/v1/customers/${customerId}/`);
      if (!res.ok) throw new Error();
      const c = await res.json();
      _renderEditCustomerForm(content, c);
    } catch {
      _toast('Could not load customer for editing.', 'error');
      openCustomerDetail(customerId);
    }
  }

  function _renderEditCustomerForm(container, c) {
    const isIndividual  = c.customer_type === 'INDIVIDUAL';
    const isBusiness    = c.customer_type === 'BUSINESS';
    const isInstitution = c.customer_type === 'INSTITUTION';
    const primaryName   = isIndividual ? (c.full_name || '—') : (c.company_name || '—');
    const showCompany   = isBusiness || isInstitution;
    const showSubtype   = isInstitution;

    const subtypeOptions = [
      ['SCHOOL', 'School'], ['CHURCH', 'Church / Religious'],
      ['NGO', 'NGO / Non-profit'], ['GOVT', 'Government / Public'], ['OTHER', 'Other Institution'],
    ];

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;
        padding:14px 28px;border-bottom:1px solid var(--border);
        background:var(--panel);position:sticky;top:0;z-index:10;">
        <div style="display:flex;align-items:center;gap:12px;">
          <button onclick="Customers.openCustomerDetail(${c.id})"
            style="display:flex;align-items:center;gap:6px;padding:7px 14px;
              background:none;border:1px solid var(--border);border-radius:var(--radius-sm);
              font-size:13px;font-weight:600;cursor:pointer;color:var(--text-2);font-family:inherit;">
            <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>
            </svg>
            Cancel
          </button>
          <span style="font-size:13px;color:var(--text-3);">Editing: <strong style="color:var(--text);">${_esc(primaryName)}</strong></span>
        </div>
        <button id="edit-cust-save-btn" onclick="Customers.saveCustomerEdit(${c.id})"
          style="padding:8px 20px;background:var(--text);color:#fff;border:none;
            border-radius:var(--radius-sm);font-size:13px;font-weight:700;
            cursor:pointer;font-family:'DM Sans',sans-serif;">
          Save Changes
        </button>
      </div>
      <div style="max-height:calc(100vh - 64px);overflow-y:auto;">
      <div style="max-width:680px;margin:0 auto;padding:36px 28px;">
        <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:var(--text);letter-spacing:-0.3px;margin-bottom:6px;">Edit Profile</div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:28px;">Locked fields (tier, score, customer type, visit count) cannot be edited here. All changes are logged in the audit trail.</div>
        <div id="edit-cust-error" style="display:none;font-size:13px;color:var(--red-text);padding:10px 14px;background:var(--red-bg);border:1px solid var(--red-border);border-radius:var(--radius-sm);margin-bottom:20px;"></div>
        <div style="display:flex;flex-direction:column;gap:18px;">

          ${showCompany ? `
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">${isBusiness ? 'Company Name' : 'Institution Name'} *</label>
            <input type="text" id="edit-company" value="${_esc(c.company_name || '')}"
              style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;box-sizing:border-box;">
          </div>` : ''}

          ${showSubtype ? `
          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">Institution Type</label>
            <select id="edit-subtype" style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;">
              <option value="">Select type…</option>
              ${subtypeOptions.map(([val, label]) => `<option value="${val}" ${c.institution_subtype === val ? 'selected' : ''}>${label}</option>`).join('')}
            </select>
          </div>` : ''}

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">Title <span style="font-weight:400;">(optional)</span></label>
              <select id="edit-title" onchange="Customers.editTitleChange()"
                style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;">
                <option value="">No title</option>
                ${['MR','MRS','MISS','MS','MADAM','DR','PROF','REV','ESQ','OTHER'].map(t =>
                  `<option value="${t}" ${c.title===t?'selected':''}>${t.charAt(0)+t.slice(1).toLowerCase()}</option>`
                ).join('')}
              </select>
            </div>
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">Gender <span style="font-weight:400;">(optional)</span></label>
              <select id="edit-gender" style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;">
                <option value="">Not specified</option>
                <option value="MALE" ${c.gender==='MALE'?'selected':''}>Male</option>
                <option value="FEMALE" ${c.gender==='FEMALE'?'selected':''}>Female</option>
                <option value="PREFER_NOT" ${c.gender==='PREFER_NOT'?'selected':''}>Prefer not to say</option>
              </select>
            </div>
          </div>

          <div id="edit-title-other-wrap" style="display:${c.title==='OTHER'?'block':'none'};">
            <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">Custom Title *</label>
            <input type="text" id="edit-title-other" value="${_esc(c.title_other || '')}" placeholder="e.g. Chief, Pastor…"
              style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;box-sizing:border-box;">
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">${isIndividual ? 'First Name' : 'Rep First Name'} *</label>
              <input type="text" id="edit-first-name" value="${_esc(c.first_name || '')}"
                style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;box-sizing:border-box;">
            </div>
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">${isIndividual ? 'Last Name' : 'Rep Last Name'} *</label>
              <input type="text" id="edit-last-name" value="${_esc(c.last_name || '')}"
                style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;box-sizing:border-box;">
            </div>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">Phone Number *</label>
              <input type="tel" id="edit-phone" value="${_esc(c.phone || '')}"
                onblur="Customers.editPhoneNormalise(this)"
                style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;box-sizing:border-box;">
              <div id="edit-phone-feedback" style="font-size:11px;margin-top:5px;"></div>
            </div>
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">Secondary Phone <span style="font-weight:400;">(optional)</span></label>
              <input type="tel" id="edit-secondary-phone" value="${_esc(c.secondary_phone || '')}" placeholder="e.g. 0201234567"
                style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;box-sizing:border-box;">
            </div>
          </div>

          <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">Preferred Contact <span style="font-weight:400;">(optional)</span></label>
              <select id="edit-preferred-contact" style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;">
                <option value="">Not specified</option>
                ${['WHATSAPP','CALL','SMS','EMAIL'].map(v => `<option value="${v}" ${c.preferred_contact===v?'selected':''}>${v.charAt(0)+v.slice(1).toLowerCase()}</option>`).join('')}
              </select>
            </div>
            <div>
              <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">Email <span style="font-weight:400;">(optional)</span></label>
              <input type="email" id="edit-email" value="${_esc(c.email || '')}"
                style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;box-sizing:border-box;">
            </div>
          </div>

          <div>
            <label style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;display:block;margin-bottom:7px;">Address ${!isIndividual ? '*' : '<span style="font-weight:400;">(optional)</span>'}</label>
            <textarea id="edit-address" rows="3"
              style="width:100%;padding:10px 13px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;font-family:'DM Sans',sans-serif;outline:none;resize:vertical;box-sizing:border-box;">${_esc(c.address || '')}</textarea>
          </div>

          <div style="padding:16px 18px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">Read-only Fields</div>
            <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;">
              ${[['Customer Type', c.customer_type], ['Tier', c.tier || 'REGULAR'], ['Confidence Score', c.confidence_score + ' / 100'], ['Total Visits', c.visit_count || 0]].map(([label, val]) => `
                <div>
                  <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.4px;margin-bottom:3px;">${label}</div>
                  <div style="font-size:13px;color:var(--text-3);font-weight:500;">${_esc(String(val))}</div>
                </div>`).join('')}
            </div>
          </div>

        </div>

        <!-- Edit History -->
        <div style="margin-top:36px;">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:12px;">
            <div style="font-family:'Syne',sans-serif;font-size:17px;font-weight:800;color:var(--text);letter-spacing:-0.2px;">Edit History</div>
            <button onclick="Customers.toggleEditHistory(${c.id})" id="edit-history-toggle-btn"
              style="padding:5px 14px;background:none;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:12px;font-weight:600;cursor:pointer;color:var(--text-2);font-family:inherit;">
              Load History
            </button>
          </div>
          <div id="edit-history-content" style="display:none;"></div>
        </div>

      </div>
      </div>`;
  }

  function editTitleChange() {
    const val  = document.getElementById('edit-title')?.value;
    const wrap = document.getElementById('edit-title-other-wrap');
    if (wrap) wrap.style.display = val === 'OTHER' ? 'block' : 'none';
  }

  function editPhoneNormalise(input) {
    const norm = _normalisePhone(input.value);
    input.value = norm;
    const fb = document.getElementById('edit-phone-feedback');
    if (fb) { fb.textContent = norm ? 'Normalised to: ' + norm : ''; fb.style.color = 'var(--text-3)'; }
  }

  async function saveCustomerEdit(customerId) {
    const btn       = document.getElementById('edit-cust-save-btn');
    const errEl     = document.getElementById('edit-cust-error');
    errEl.style.display = 'none';

    const firstName = document.getElementById('edit-first-name')?.value.trim();
    const lastName  = document.getElementById('edit-last-name')?.value.trim();
    const phone     = _normalisePhone(document.getElementById('edit-phone')?.value.trim());
    const showErr   = msg => { errEl.textContent = msg; errEl.style.display = 'block'; errEl.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); };

    if (!firstName) return showErr('First name is required.');
    if (!lastName)  return showErr('Last name is required.');
    if (!phone)     return showErr('Phone number is required.');

    btn.disabled = true; btn.textContent = 'Saving…';

    const payload = { first_name: firstName, last_name: lastName, phone };
    const emailEl   = document.getElementById('edit-email');
    const addressEl = document.getElementById('edit-address');
    const companyEl = document.getElementById('edit-company');
    const subtypeEl = document.getElementById('edit-subtype');
    if (emailEl)   payload.email              = emailEl.value.trim();
    if (addressEl) payload.address            = addressEl.value.trim();
    if (companyEl) payload.company_name       = companyEl.value.trim();
    if (subtypeEl) payload.institution_subtype = subtypeEl.value;
    payload.title             = document.getElementById('edit-title')?.value || '';
    payload.title_other       = document.getElementById('edit-title-other')?.value.trim() || '';
    payload.gender            = document.getElementById('edit-gender')?.value || '';
    payload.secondary_phone   = _normalisePhone(document.getElementById('edit-secondary-phone')?.value.trim() || '');
    payload.preferred_contact = document.getElementById('edit-preferred-contact')?.value || '';

    try {
      const res  = await Auth.fetch(`/api/v1/customers/${customerId}/edit/`, {
        method : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) {
        const msg = typeof data.detail === 'string' ? data.detail : Object.values(data).flat().join(' ');
        btn.disabled = false; btn.textContent = 'Save Changes';
        return showErr(msg || 'Save failed.');
      }
      _toast('Profile updated successfully.', 'success');
      openCustomerDetail(customerId);
    } catch {
      btn.disabled = false; btn.textContent = 'Save Changes';
      showErr('Network error. Please try again.');
    }
  }

  async function toggleEditHistory(customerId) {
    const content = document.getElementById('edit-history-content');
    const btn     = document.getElementById('edit-history-toggle-btn');
    if (!content) return;
    const isVisible = content.style.display !== 'none';
    if (isVisible) { content.style.display = 'none'; btn.textContent = 'Load History'; return; }
    content.style.display = 'block';
    btn.textContent = 'Hide History';
    content.innerHTML = '<div style="padding:16px 0;color:var(--text-3);font-size:13px;"><span class="spin"></span> Loading…</div>';
    await _loadEditHistory(customerId, content);
  }

  async function _loadEditHistory(customerId, container) {
    try {
      const res  = await Auth.fetch(`/api/v1/customers/${customerId}/edit-log/`);
      if (!res.ok) throw new Error();
      const logs = await res.json();

      if (!logs.length) {
        container.innerHTML = `<div style="padding:20px;text-align:center;color:var(--text-3);font-size:13px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);">No edits recorded yet.</div>`;
        return;
      }

      const fieldLabel = field => ({
        first_name: 'First Name', last_name: 'Last Name', phone: 'Phone',
        email: 'Email', address: 'Address', company_name: 'Company / Institution Name',
        institution_subtype: 'Institution Type',
      }[field] || field);

      container.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
          ${logs.map((log, idx) => {
            const dt      = new Date(log.changed_at);
            const dateStr = dt.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
            const timeStr = dt.toLocaleTimeString('en-GH', { hour: '2-digit', minute: '2-digit' });
            const isLast  = idx === logs.length - 1;
            return `
              <div style="display:flex;align-items:flex-start;gap:14px;padding:14px 18px;${!isLast ? 'border-bottom:1px solid var(--border);' : ''}">
                <div style="flex-shrink:0;margin-top:2px;">
                  <span style="padding:3px 9px;border-radius:20px;font-size:10px;font-weight:700;background:var(--bg);color:var(--text-2);border:1px solid var(--border);">${_esc(fieldLabel(log.field_name))}</span>
                </div>
                <div style="flex:1;min-width:0;">
                  <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:5px;">
                    <span style="font-size:13px;color:var(--red-text);font-weight:500;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(log.old_value || '(empty)')}</span>
                    <span style="color:var(--text-3);font-size:12px;">→</span>
                    <span style="font-size:13px;color:var(--green-text);font-weight:600;max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">${_esc(log.new_value || '(empty)')}</span>
                  </div>
                  <div style="font-size:11px;color:var(--text-3);">By <strong style="color:var(--text-2);">${_esc(log.changed_by_name || '—')}</strong> · ${dateStr} at ${timeStr}</div>
                </div>
              </div>`;
          }).join('')}
        </div>`;
    } catch {
      container.innerHTML = `<div style="padding:16px;color:var(--red-text);font-size:13px;background:var(--red-bg);border:1px solid var(--red-border);border-radius:var(--radius-sm);">Could not load edit history.</div>`;
    }
  }

  function nominateCredit(customerId) {
    _toast('Credit nomination coming soon.', 'info');
  }

  // ── Add Customer Modal — delegates to CustomerReg ──────────
  function openAddCustomerModal() {
    CustomerReg.open(async function(data) {
      _toast(`${data.display_name || data.full_name || 'Customer'} registered successfully.`, 'success');
      await _loadCustomersTab(_customersTab);
      if (data.id) setTimeout(() => openCustomerDetail(data.id), 300);
    });
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    loadCustomersPane,
    switchCustomersTab,
    openCustomerDetail,
    closeCustomerProfile,
    saveCustomerNotes,
    editCustomer,
    saveCustomerEdit,
    editPhoneNormalise,
    editTitleChange,
    toggleEditHistory,
    nominateCredit,
    openAddCustomerModal,
    normalisePhone: _normalisePhone,
    onSearchInput,
    changePage,
  };

})();