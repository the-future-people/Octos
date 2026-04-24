'use strict';

const FinancePortal = (() => {

  // ── State ─────────────────────────────────────────────────
  let _currentSection = 'home';
  let _currentTab     = null;
  let _user           = null;
  let _clarifyCloseId = null;
  let _clearCloseId   = null;
  let _procActiveId   = null;
  let _profileOpen    = false;

  // ── Section definitions ───────────────────────────────────
  const SECTIONS = {
    home: {
      tabs: [],
      defaultTab: null,
    },
    reviews: {
      tabs: [
        { id: 'queue',       label: 'Queue',       badge: 'reviews-queue-badge' },
        { id: 'history',     label: 'History',     badge: null },
        { id: 'escalations', label: 'Escalations', badge: null },
      ],
      defaultTab: 'queue',
    },
    budget: {
      tabs: [
        { id: 'overview',   label: 'Overview',  badge: null },
        { id: 'envelopes',  label: 'Envelopes', badge: null },
        { id: 'proposals',  label: 'Proposals', badge: null },
      ],
      defaultTab: 'overview',
    },
    procurement: {
      tabs: [
        { id: 'pending',  label: 'Pending Approval', badge: 'proc-pending-badge' },
        { id: 'progress', label: 'In Progress',      badge: null },
        { id: 'receipts', label: 'Verify Receipts',  badge: 'proc-receipts-badge' },
        { id: 'history',  label: 'History',          badge: null },
      ],
      defaultTab: 'pending',
    },
    vendors: {
      tabs: [
        { id: 'pricelist', label: 'Pricelist',    badge: null },
        { id: 'alerts',    label: 'Price Alerts', badge: null },
      ],
      defaultTab: 'pricelist',
    },
    reports: {
      tabs: [
        { id: 'monthly',   label: 'Monthly',   badge: null },
        { id: 'quarterly', label: 'Quarterly', badge: null },
        { id: 'annual',    label: 'Annual',    badge: null },
      ],
      defaultTab: 'monthly',
    },
  };

  // ── Boot ──────────────────────────────────────────────────
  async function init() {
    await Auth.guard([
      'FINANCE',
      'NATIONAL_FINANCE_HEAD', 'NATIONAL_FINANCE_DEPUTY',
      'BELT_FINANCE_OFFICER',  'BELT_FINANCE_DEPUTY',
      'REGIONAL_FINANCE_OFFICER', 'REGIONAL_FINANCE_DEPUTY',
      'SUPER_ADMIN',
    ]);
    await _loadContext();
    _applyRoleUI();
    await _loadStrip();
    switchSection('home');
  }

  // ── Context ───────────────────────────────────────────────
  async function _loadContext() {
    try {
      const res = await Auth.fetch('/api/v1/accounts/me/');
      if (!res?.ok) return;
      _user = await res.json();

      const name    = _user.full_name || _user.email || '—';
      const initials= name.split(' ').slice(0,2).map(w => w[0]?.toUpperCase() || '').join('');
      const role    = _user.role_detail?.name || _user.role?.name || 'Finance';

      _set('fin-user-name',    name);
      _set('fin-avatar',       initials);
      _set('fin-profile-fullname', name);
      _set('fin-profile-role', role);
      _set('fin-profile-empid', _user.employee_id || '—');
    } catch { /* silent */ }
  }

  // ── Role-based UI ─────────────────────────────────────────
  function _applyRoleUI() {
    const role = _user?.role_detail?.name || _user?.role?.name || '';
    const isRegional = role.includes('REGIONAL');
    const isBelt     = role.includes('BELT');

    // Regional and Belt Finance: hide HQ-only sections
    if (isRegional || isBelt) {
      ['nav-budget', 'nav-procurement', 'nav-vendors'].forEach(id => {
        const el = document.getElementById(id);
        if (el) el.style.display = 'none';
      });
      // Also hide the Finance section header if all items under it are hidden
      document.querySelectorAll('.fin-nav-section').forEach(el => {
        if (el.textContent.trim() === 'Finance') {
          // Check if any siblings are visible
          let next = el.nextElementSibling;
          let allHidden = true;
          while (next && !next.classList.contains('fin-nav-section')) {
            if (next.style.display !== 'none') { allHidden = false; break; }
            next = next.nextElementSibling;
          }
          if (allHidden) el.style.display = 'none';
        }
      });
    }
  }

  // ── Info strip ────────────────────────────────────────────
  async function _loadStrip() {
    try {
      // Scope label
      const role = _user?.role_detail?.name || _user?.role?.name || '';
      let scopeLabel = 'National';
      if (role.includes('BELT'))     scopeLabel = _user?.belt_detail?.name   || _user?.belt_name   || 'Belt';
      if (role.includes('REGIONAL')) scopeLabel = _user?.region_detail?.name || _user?.region_name || 'Region';
      _set('strip-scope', scopeLabel);

      // Reviews pending
      const reviewsRes = await Auth.fetch('/api/v1/finance/monthly-close/my-queue/');
      if (reviewsRes?.ok) {
        const reviews = await reviewsRes.json();
        const el = document.getElementById('strip-reviews');
        if (el) {
          el.textContent = reviews.length;
          el.className   = 'fin-strip-value' + (reviews.length > 0 ? ' warning' : ' good');
        }
        // Nav badge
        const navBadge = document.getElementById('nav-reviews-badge');
        if (navBadge) {
          navBadge.textContent   = reviews.length;
          navBadge.style.display = reviews.length > 0 ? 'flex' : 'none';
        }
      }

      // Procurement pending
      const procRes = await Auth.fetch('/api/v1/procurement/orders/');
      if (procRes?.ok) {
        const orders  = await procRes.json();
        const pending = orders.filter(o => o.status === 'PENDING_FINANCE').length;
        const el = document.getElementById('strip-orders');
        if (el) {
          el.textContent = pending;
          el.className   = 'fin-strip-value' + (pending > 0 ? ' warning' : ' good');
        }
        const navBadge = document.getElementById('nav-procurement-badge');
        if (navBadge) {
          navBadge.textContent   = pending;
          navBadge.style.display = pending > 0 ? 'flex' : 'none';
        }
      }

      // Budget strip — current year utilisation
      const budgetRes = await Auth.fetch('/api/v1/procurement/budgets/');
      if (budgetRes?.ok) {
        const budgets = await budgetRes.json();
        const current = budgets.find(b => b.year === new Date().getFullYear() && b.status === 'APPROVED');
        const el = document.getElementById('strip-budget');
        if (el && current) {
          const envelopes = current.envelopes || [];
          const quarterly = envelopes.filter(e => e.period_type === 'QUARTERLY');
          const avgUtil   = quarterly.length
            ? Math.round(quarterly.reduce((s, e) => s + parseFloat(e.utilisation_pct || 0), 0) / quarterly.length)
            : 0;
          el.textContent = `${avgUtil}%`;
          el.className   = 'fin-strip-value' + (avgUtil > 90 ? ' alert' : avgUtil > 70 ? ' warning' : ' good');
        } else if (el) {
          el.textContent = 'No budget';
          el.className   = 'fin-strip-value';
        }
      }

      _set('strip-alerts', '0');

    } catch { /* silent */ }
  }

  // ── Section switching ─────────────────────────────────────
  function switchSection(section) {
    _currentSection = section;

    // Update sidebar
    document.querySelectorAll('.fin-nav-item').forEach(el => {
      el.classList.toggle('active', el.id === `nav-${section}`);
    });

    // Render tab bar
    _renderTabBar(section);

    // Load default tab or section content
    const def = SECTIONS[section]?.defaultTab;
    if (def) {
      switchTab(def);
    } else {
      _loadSectionContent(section, null);
    }
  }

  function _renderTabBar(section) {
    const tabbar = document.getElementById('fin-tabbar');
    if (!tabbar) return;
    const tabs = SECTIONS[section]?.tabs || [];
    if (!tabs.length) {
      tabbar.innerHTML = '';
      return;
    }
    tabbar.innerHTML = tabs.map(t => `
      <button class="fin-tab" id="tab-${t.id}"
        onclick="FinancePortal.switchTab('${t.id}')">
        ${t.label}
        ${t.badge ? `<span class="fin-tab-badge" id="${t.badge}" style="display:none;"></span>` : ''}
      </button>`).join('');
  }

  function switchTab(tab) {
    _currentTab = tab;
    document.querySelectorAll('.fin-tab').forEach(el => {
      el.classList.toggle('active', el.id === `tab-${tab}`);
    });
    _loadSectionContent(_currentSection, tab);
  }

  // ── Content router ────────────────────────────────────────
  function _loadSectionContent(section, tab) {
    const key = tab ? `${section}/${tab}` : section;
    switch (key) {
      case 'home':               return _renderHome();
      case 'reviews/queue':      return _loadReviewQueue();
      case 'reviews/history':    return _loadReviewHistory();
      case 'reviews/escalations':return _renderEscalations();
      case 'budget/overview':    return _loadBudgetOverview();
      case 'budget/envelopes':   return _loadBudgetEnvelopes();
      case 'budget/proposals':   return _loadBudgetProposals();
      case 'procurement/pending':  return _loadProcurementPending();
      case 'procurement/progress': return _loadProcurementProgress();
      case 'procurement/receipts': return _loadProcurementReceipts();
      case 'procurement/history':  return _loadProcurementHistory();
      case 'vendors/pricelist':  return _loadVendorPricelist();
      case 'vendors/alerts':     return _renderPriceAlerts();
      case 'reports/monthly':    return _loadReportsMonthly();
      case 'reports/quarterly':  return _loadReportsQuarterly();
      case 'reports/annual':     return _loadReportsAnnual();
      default: _setContent('<div class="loading-cell">Coming soon.</div>');
    }
  }

  // ── HOME ──────────────────────────────────────────────────
  async function _renderHome() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const [reviewsRes, procRes, budgetRes] = await Promise.all([
        Auth.fetch('/api/v1/finance/monthly-close/my-queue/'),
        Auth.fetch('/api/v1/procurement/orders/'),
        Auth.fetch('/api/v1/procurement/budgets/'),
      ]);

      const reviews  = reviewsRes?.ok  ? await reviewsRes.json()  : [];
      const orders   = procRes?.ok     ? await procRes.json()     : [];
      const budgets  = budgetRes?.ok   ? await budgetRes.json()   : [];

      const pendingReviews  = reviews.length;
      const pendingOrders   = orders.filter(o => o.status === 'PENDING_FINANCE').length;
      const receiptsNeeded  = orders.filter(o => o.status === 'DELIVERED').length;
      const currentBudget   = budgets.find(b => b.year === new Date().getFullYear() && b.status === 'APPROVED');

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

      // Budget envelope bars
      const envelopeBars = currentBudget
        ? (currentBudget.envelopes || [])
            .filter(e => e.period_type === 'QUARTERLY')
            .slice(0, 8)
            .map(e => {
              const pct = parseFloat(e.utilisation_pct || 0);
              const color = pct > 90 ? 'var(--red-text)' : pct > 70 ? 'var(--amber-text)' : 'var(--green-text)';
              return `
                <div style="display:flex;align-items:center;gap:10px;margin-bottom:8px;">
                  <div style="width:90px;font-size:11px;color:var(--text-3);">${e.category_display}</div>
                  <div style="width:50px;font-size:10px;color:var(--text-3);">${e.period_display}</div>
                  <div style="flex:1;background:var(--bg);border-radius:4px;height:8px;">
                    <div style="width:${Math.min(pct,100)}%;height:100%;background:${color};border-radius:4px;"></div>
                  </div>
                  <div style="font-family:'JetBrains Mono',monospace;font-size:11px;
                    color:var(--text-2);width:100px;text-align:right;">
                    ${fmt(e.available)} left
                  </div>
                  <div style="font-size:10px;color:${color};width:36px;text-align:right;">${pct}%</div>
                </div>`;
            }).join('')
        : '<div style="font-size:13px;color:var(--text-3);">No approved budget for this year.</div>';

      // Recent activity
      const activityRows = orders.slice(0, 5).map(o => `
        <div style="display:flex;align-items:center;justify-content:space-between;
          padding:10px 0;border-bottom:1px solid var(--border);">
          <div>
            <div style="font-size:13px;font-weight:600;color:var(--text);">${o.order_number}</div>
            <div style="font-size:11px;color:var(--text-3);">${o.branch_name} &middot; Week ${o.week_number}</div>
          </div>
          <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;
            background:var(--bg);color:var(--text-3);">${o.status}</span>
        </div>`).join('') || '<div style="font-size:13px;color:var(--text-3);">No recent activity.</div>';

      _setContent(`
        <div class="fin-section-title">Good day, ${(_user?.first_name || 'Finance')} 👋</div>

        <div class="fin-kpi-grid">
          <div class="fin-kpi-card" style="cursor:pointer;" onclick="FinancePortal.switchSection('reviews')">
            <div class="fin-kpi-label">Pending Reviews</div>
            <div class="fin-kpi-value" style="color:${pendingReviews > 0 ? 'var(--amber-text)' : 'var(--green-text)'};">
              ${pendingReviews}
            </div>
            <div class="fin-kpi-sub">Monthly closes awaiting your review</div>
          </div>
          <div class="fin-kpi-card" style="cursor:pointer;" onclick="FinancePortal.switchSection('procurement')">
            <div class="fin-kpi-label">Orders Pending</div>
            <div class="fin-kpi-value" style="color:${pendingOrders > 0 ? 'var(--amber-text)' : 'var(--green-text)'};">
              ${pendingOrders}
            </div>
            <div class="fin-kpi-sub">Replenishment orders awaiting approval</div>
          </div>
          <div class="fin-kpi-card" style="cursor:pointer;" onclick="FinancePortal.switchSection('procurement')">
            <div class="fin-kpi-label">Receipts to Verify</div>
            <div class="fin-kpi-value" style="color:${receiptsNeeded > 0 ? 'var(--amber-text)' : 'var(--green-text)'};">
              ${receiptsNeeded}
            </div>
            <div class="fin-kpi-sub">Delivered orders awaiting receipt verification</div>
          </div>
          <div class="fin-kpi-card">
            <div class="fin-kpi-label">Budget Year</div>
            <div class="fin-kpi-value">${currentBudget ? new Date().getFullYear() : '—'}</div>
            <div class="fin-kpi-sub">${currentBudget ? 'Active budget approved' : 'No active budget'}</div>
          </div>
        </div>

        <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px;">
          <div style="border:1px solid var(--border);border-radius:var(--radius);padding:20px;">
            <div style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.6px;margin-bottom:16px;">
              Budget Utilisation — ${new Date().getFullYear()}
            </div>
            ${envelopeBars}
          </div>
          <div style="border:1px solid var(--border);border-radius:var(--radius);padding:20px;">
            <div style="font-size:11px;font-weight:700;color:var(--text-3);
              text-transform:uppercase;letter-spacing:0.6px;margin-bottom:16px;">
              Recent Procurement Activity
            </div>
            ${activityRows}
          </div>
        </div>
      `);
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load dashboard.</div>');
    }
  }

  // ── REVIEWS ───────────────────────────────────────────────
  async function _loadReviewQueue() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/my-branches/');
      if (!res?.ok) throw new Error();
      const data = await res.json();

      const badge = document.getElementById('reviews-queue-badge');
      const activeCount = data.filter(b => b.active).length;
      if (badge) { badge.textContent = activeCount; badge.style.display = activeCount ? 'flex' : 'none'; }

      if (!data.length) {
        _setContent(_emptyState('No branches assigned', 'No monthly closes have been assigned to you yet.'));
        return;
      }
      _setContent(data.map(b => _renderBranchCard(b)).join(''));
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load queue.</div>');
    }
  }

  async function _loadReviewHistory() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/my-history/');
      if (!res?.ok) throw new Error();
      const data = await res.json();

      if (!data.length) {
        _setContent(_emptyState('No history yet', 'Cleared monthly closes will appear here.'));
        return;
      }

      const months = ['January','February','March','April','May','June',
        'July','August','September','October','November','December'];

      _setContent(`
        <div style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
          ${data.map(c => `
            <div style="display:flex;align-items:center;justify-content:space-between;
              padding:14px 20px;border-bottom:1px solid var(--border);">
              <div>
                <div style="font-size:14px;font-weight:700;color:var(--text);">
                  ${_esc(c.branch)} — ${months[(c.month||1)-1]} ${c.year}
                </div>
                <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
                  Cleared ${c.finance_cleared_at ? new Date(c.finance_cleared_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : '—'}
                </div>
              </div>
              <div style="display:flex;align-items:center;gap:12px;">
                <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-2);">
                  GHS ${parseFloat(c.total_collected||0).toLocaleString('en-GH',{minimumFractionDigits:2})}
                </span>
                <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;
                  background:var(--green-bg);color:var(--green-text);">
                  ${c.status === 'ENDORSED' || c.status === 'LOCKED' ? 'Endorsed' : 'Cleared'}
                </span>
              </div>
            </div>`).join('')}
        </div>`);
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load history.</div>');
    }
  }

  function _renderEscalations() {
    _setContent(_emptyState('No escalations', 'No overdue clarification requests at this time.'));
  }

  // ── BUDGET ────────────────────────────────────────────────
  async function _loadBudgetOverview() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/procurement/budgets/');
      if (!res?.ok) throw new Error();
      const data = await res.json();
      const current = data.find(b => b.year === new Date().getFullYear() && b.status === 'APPROVED');

      if (!current) {
        _setContent(_emptyState('No active budget', 'Propose a budget in the Proposals tab to get started.'));
        return;
      }

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
      const annual = (current.envelopes || []).filter(e => e.period_type === 'ANNUAL');

      const totalApproved = annual.reduce((s,e) => s + parseFloat(e.approved_amount||0), 0);
      const totalSpent    = annual.reduce((s,e) => s + parseFloat(e.spent||0), 0);
      const totalAvail    = annual.reduce((s,e) => s + parseFloat(e.available||0), 0);
      const overallPct    = totalApproved ? Math.round(totalSpent / totalApproved * 100) : 0;

      _setContent(`
        <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-bottom:24px;">
          <div class="fin-kpi-card">
            <div class="fin-kpi-label">Total Approved</div>
            <div style="font-size:22px;font-weight:800;color:var(--text);font-family:'Syne',sans-serif;">
              ${fmt(totalApproved)}
            </div>
            <div class="fin-kpi-sub">Annual budget ${current.year}</div>
          </div>
          <div class="fin-kpi-card">
            <div class="fin-kpi-label">Total Spent</div>
            <div style="font-size:22px;font-weight:800;color:var(--amber-text);font-family:'Syne',sans-serif;">
              ${fmt(totalSpent)}
            </div>
            <div class="fin-kpi-sub">${overallPct}% utilised</div>
          </div>
          <div class="fin-kpi-card">
            <div class="fin-kpi-label">Available</div>
            <div style="font-size:22px;font-weight:800;color:var(--green-text);font-family:'Syne',sans-serif;">
              ${fmt(totalAvail)}
            </div>
            <div class="fin-kpi-sub">Remaining across all categories</div>
          </div>
        </div>

        <div style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
          <div style="padding:14px 20px;border-bottom:1px solid var(--border);
            font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;">
            Category Breakdown — Annual View
          </div>
          ${annual.map(e => {
            const pct   = parseFloat(e.utilisation_pct||0);
            const color = pct > 90 ? 'var(--red-text)' : pct > 70 ? 'var(--amber-text)' : 'var(--green-text)';
            return `
              <div style="padding:14px 20px;border-bottom:1px solid var(--border);
                display:flex;align-items:center;gap:16px;">
                <div style="width:140px;font-size:13px;font-weight:600;color:var(--text);">${e.category_display}</div>
                <div style="flex:1;background:var(--bg);border-radius:4px;height:8px;">
                  <div style="width:${Math.min(pct,100)}%;height:100%;background:${color};border-radius:4px;"></div>
                </div>
                <div style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-2);width:120px;text-align:right;">
                  ${fmt(e.spent)} spent
                </div>
                <div style="font-family:'JetBrains Mono',monospace;font-size:12px;
                  font-weight:700;color:var(--text);width:120px;text-align:right;">
                  ${fmt(e.available)} left
                </div>
                <div style="font-size:11px;color:${color};width:40px;text-align:right;">${pct}%</div>
              </div>`;
          }).join('')}
        </div>`);
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load budget overview.</div>');
    }
  }

  async function _loadBudgetEnvelopes() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/procurement/budgets/');
      if (!res?.ok) throw new Error();
      const data = await res.json();
      const current = data.find(b => b.year === new Date().getFullYear() && b.status === 'APPROVED');

      if (!current) {
        _setContent(_emptyState('No active budget', 'Propose a budget to see envelope details.'));
        return;
      }

      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
      const quarterly = (current.envelopes || []).filter(e => e.period_type === 'QUARTERLY');

      // Group by category
      const byCategory = {};
      quarterly.forEach(e => {
        if (!byCategory[e.category]) byCategory[e.category] = { label: e.category_display, quarters: [] };
        byCategory[e.category].quarters.push(e);
      });

      _setContent(`
        <div style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
          <div style="display:grid;grid-template-columns:140px repeat(4,1fr);
            padding:10px 20px;background:var(--bg);border-bottom:1px solid var(--border);">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;">Category</div>
            ${['Q1','Q2','Q3','Q4'].map(q => `
              <div style="font-size:10px;font-weight:700;color:var(--text-3);
                text-transform:uppercase;text-align:center;">${q}</div>`).join('')}
          </div>
          ${Object.entries(byCategory).map(([cat, data]) => `
            <div style="display:grid;grid-template-columns:140px repeat(4,1fr);
              padding:14px 20px;border-bottom:1px solid var(--border);align-items:center;">
              <div style="font-size:13px;font-weight:600;color:var(--text);">${data.label}</div>
              ${['Q1','Q2','Q3','Q4'].map(q => {
                const env = data.quarters.find(e => e.period === q);
                if (!env) return '<div style="text-align:center;color:var(--text-3);">—</div>';
                const pct   = parseFloat(env.utilisation_pct||0);
                const color = pct > 90 ? 'var(--red-text)' : pct > 70 ? 'var(--amber-text)' : 'var(--green-text)';
                return `
                  <div style="text-align:center;padding:0 8px;">
                    <div style="font-family:'JetBrains Mono',monospace;font-size:11px;
                      font-weight:700;color:var(--text);">${fmt(env.available)}</div>
                    <div style="font-size:10px;color:${color};margin-top:2px;">${pct}% used</div>
                    <div style="background:var(--bg);border-radius:3px;height:4px;margin-top:4px;">
                      <div style="width:${Math.min(pct,100)}%;height:100%;background:${color};border-radius:3px;"></div>
                    </div>
                  </div>`;
              }).join('')}
            </div>`).join('')}
        </div>`);
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load envelopes.</div>');
    }
  }

  async function _loadBudgetProposals() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/procurement/budgets/');
      if (!res?.ok) throw new Error();
      const data = await res.json();
      const proposals = data.filter(b => ['DRAFT','PENDING_APPROVAL'].includes(b.status));

      const html = `
        <div style="display:flex;justify-content:flex-end;margin-bottom:16px;">
          <button onclick="FinancePortal.openProposeBudgetModal()"
            style="padding:8px 18px;background:var(--text);color:#fff;border:none;
              border-radius:var(--radius-sm);font-size:13px;font-weight:700;
              cursor:pointer;font-family:inherit;">
            + Propose Budget
          </button>
        </div>
        ${proposals.length ? proposals.map(b => _renderBudgetCard(b)).join('') :
          _emptyState('No proposals', 'All budgets are approved or no proposals exist yet.')}`;

      _setContent(html);
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load proposals.</div>');
    }
  }

  // ── PROCUREMENT ───────────────────────────────────────────
  async function _loadProcurementPending() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/procurement/orders/');
      if (!res?.ok) throw new Error();
      const data = await res.json();
      const pending = data.filter(o => o.status === 'PENDING_FINANCE');

      const badge = document.getElementById('proc-pending-badge');
      if (badge) { badge.textContent = pending.length; badge.style.display = pending.length ? 'flex' : 'none'; }

      if (!pending.length) {
        _setContent(_emptyState('All clear', 'No replenishment orders awaiting your approval.'));
        return;
      }
      _setContent(pending.map(o => _renderProcCard(o, true)).join(''));
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load orders.</div>');
    }
  }

  async function _loadProcurementProgress() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/procurement/orders/');
      if (!res?.ok) throw new Error();
      const data = await res.json();
      const inProgress = data.filter(o => ['FINANCE_APPROVED','IN_TRANSIT'].includes(o.status));

      if (!inProgress.length) {
        _setContent(_emptyState('Nothing in progress', 'Approved orders will appear here once dispatched.'));
        return;
      }
      _setContent(inProgress.map(o => _renderProcCard(o, false)).join(''));
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load orders.</div>');
    }
  }

  async function _loadProcurementReceipts() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/procurement/orders/');
      if (!res?.ok) throw new Error();
      const data = await res.json();
      const delivered = data.filter(o => o.status === 'DELIVERED');

      const badge = document.getElementById('proc-receipts-badge');
      if (badge) { badge.textContent = delivered.length; badge.style.display = delivered.length ? 'flex' : 'none'; }

      if (!delivered.length) {
        _setContent(_emptyState('No receipts pending', 'Delivered orders with uploaded receipts will appear here.'));
        return;
      }
      _setContent(delivered.map(o => _renderProcCard(o, false)).join(''));
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load receipts.</div>');
    }
  }

  async function _loadProcurementHistory() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/procurement/orders/');
      if (!res?.ok) throw new Error();
      const data = await res.json();
      const closed = data.filter(o => ['CLOSED','CANCELLED'].includes(o.status));

      if (!closed.length) {
        _setContent(_emptyState('No history', 'Closed and cancelled orders will appear here.'));
        return;
      }
      _setContent(closed.map(o => _renderProcCard(o, false)).join(''));
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load history.</div>');
    }
  }

  // ── VENDORS ───────────────────────────────────────────────
  async function _loadVendorPricelist() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/procurement/vendors/');
      if (!res?.ok) throw new Error();
      const data = await res.json();

      const html = `
        <div style="display:flex;justify-content:flex-end;margin-bottom:16px;">
          <button onclick="FinancePortal.openAddVendorModal()"
            style="padding:8px 18px;background:var(--text);color:#fff;border:none;
              border-radius:var(--radius-sm);font-size:13px;font-weight:700;
              cursor:pointer;font-family:inherit;">
            + Add Vendor
          </button>
        </div>
        ${data.length ? data.map(v => _renderVendorCard(v)).join('') :
          _emptyState('No vendors yet', 'Add your first vendor to start building the pricelist.')}`;

      _setContent(html);
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load vendors.</div>');
    }
  }

  function _renderPriceAlerts() {
    _setContent(_emptyState('No price alerts', 'Price variance alerts will appear here after receipt verification.'));
  }

  // ── REPORTS ───────────────────────────────────────────────
  async function _loadReportsMonthly() {
    _setContent('<div class="loading-cell"><span class="spin"></span> Loading...</div>');
    try {
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/my-history/');
      if (!res?.ok) throw new Error();
      const data = await res.json();

      if (!data.length) {
        _setContent(_emptyState('No data', 'No cleared monthly closes found.'));
        return;
      }

      const months = ['January','February','March','April','May','June',
        'July','August','September','October','November','December'];
      const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;

      _setContent(`
        <div style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr 120px;
            padding:10px 20px;background:var(--bg);border-bottom:1px solid var(--border);">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;">Branch</div>
            <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;">Period</div>
            <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;text-align:right;">Revenue</div>
            <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;text-align:right;">Status</div>
          </div>
          ${data.map(c => `
            <div style="display:grid;grid-template-columns:1fr 1fr 1fr 120px;
              padding:12px 20px;border-bottom:1px solid var(--border);align-items:center;">
              <div style="font-size:13px;font-weight:600;color:var(--text);">${_esc(c.branch)}</div>
              <div style="font-size:12px;color:var(--text-2);">${months[(c.month||1)-1]} ${c.year}</div>
              <div style="font-family:'JetBrains Mono',monospace;font-size:12px;
                font-weight:700;color:var(--text);text-align:right;">
                ${fmt(c.total_collected)}
              </div>
              <div style="text-align:right;">
                <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;
                  background:var(--green-bg);color:var(--green-text);">${c.status}</span>
              </div>
            </div>`).join('')}
        </div>`);
    } catch {
      _setContent('<div class="loading-cell" style="color:var(--red-text);">Could not load reports.</div>');
    }
  }

  function _loadReportsQuarterly() {
    _setContent(_emptyState('Quarterly Reports', 'Quarterly aggregated reports coming soon.'));
  }

  function _loadReportsAnnual() {
    _setContent(_emptyState('Annual Reports', 'Annual reports coming soon.'));
  }

  // ── Card renderers ────────────────────────────────────────
  function _renderBranchCard(b) {
    const activeHtml = b.active
      ? _renderActiveClose(b.active, b.branch, b.branch_code)
      : `<div style="padding:20px;background:var(--bg);border-radius:var(--radius-sm);
          font-size:13px;color:var(--text-3);text-align:center;">
          No active review — all closes cleared
        </div>`;

    const historyHtml = b.history?.length ? `
      <div style="border-top:2px solid var(--border);">
        <div style="padding:8px 20px;background:var(--bg);">
          <span style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.6px;">Previous Reviews</span>
        </div>
        ${b.history.map(h => {
          const months = ['January','February','March','April','May','June',
            'July','August','September','October','November','December'];
          const clearedAt = h.finance_cleared_at
            ? new Date(h.finance_cleared_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})
            : '—';
          return `
            <div style="display:flex;align-items:center;justify-content:space-between;
              padding:10px 20px;border-top:1px solid var(--border);">
              <div>
                <span style="font-size:13px;font-weight:600;color:var(--text);">
                  ${months[(h.month||1)-1]} ${h.year}
                </span>
                <span style="font-size:11px;color:var(--text-3);margin-left:8px;">Cleared ${clearedAt}</span>
              </div>
              <div style="display:flex;align-items:center;gap:12px;">
                <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-2);">
                  GHS ${parseFloat(h.total_collected||0).toLocaleString('en-GH',{minimumFractionDigits:2})}
                </span>
                <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;
                  background:var(--green-bg);color:var(--green-text);">${h.status}</span>
              </div>
            </div>`;
        }).join('')}
      </div>` : '';

    return `
      <div style="border:1px solid var(--border);border-radius:var(--radius);
        overflow:hidden;margin-bottom:24px;">
        <div style="padding:14px 20px;background:var(--text);
          display:flex;align-items:center;justify-content:space-between;">
          <div style="display:flex;align-items:center;gap:10px;">
            <span style="font-family:'Syne',sans-serif;font-size:15px;
              font-weight:800;color:#fff;">${_esc(b.branch)}</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:11px;
              color:rgba(255,255,255,0.6);">${_esc(b.branch_code)}</span>
          </div>
          <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;
            background:rgba(255,255,255,0.15);color:#fff;">
            ${b.active ? (b.active.status === 'RESUBMITTED' ? 'Resubmitted' : 'Active Review') : 'Clear'}
          </span>
        </div>
        <div style="padding:20px;">${activeHtml}</div>
        ${historyHtml}
      </div>`;
  }

  function _renderActiveClose(c, branchName, branchCode) {
    const months = ['January','February','March','April','May','June',
      'July','August','September','October','November','December'];
    const monthName   = months[(c.month||1)-1];
    const submittedAt = c.submitted_at
      ? new Date(c.submitted_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',hour:'2-digit',minute:'2-digit'})
      : '—';
    const isResubmitted = c.status === 'RESUBMITTED';
    const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
    const pct = n => `${parseFloat(n||0).toFixed(1)}%`;

    const clarifyThread = isResubmitted && (c.clarification_request || c.clarification_response) ? `
      <div style="margin-bottom:16px;">
        <div style="font-size:10px;font-weight:700;color:var(--amber-text);
          text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">Clarification Thread</div>
        ${c.clarification_request ? `
          <div style="background:var(--amber-bg);border:1px solid var(--border);
            border-radius:var(--radius-sm);padding:10px 14px;margin-bottom:6px;">
            <div style="font-size:10px;font-weight:700;color:var(--amber-text);margin-bottom:4px;">Your Request</div>
            <div style="font-size:13px;color:var(--text-2);">${_esc(c.clarification_request)}</div>
          </div>` : ''}
        ${c.clarification_response ? `
          <div style="background:var(--bg);border:1px solid var(--border);
            border-radius:var(--radius-sm);padding:10px 14px;">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);margin-bottom:4px;">BM Response</div>
            <div style="font-size:13px;color:var(--text-2);">${_esc(c.clarification_response)}</div>
          </div>` : ''}
      </div>` : '';

    return `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
        <div>
          <div style="font-size:15px;font-weight:700;color:var(--text);">${monthName} ${c.year} Monthly Close</div>
          <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
            Submitted by ${_esc(c.submitted_by)} &middot; ${submittedAt}
          </div>
        </div>
        <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;
          background:${isResubmitted ? 'var(--amber-bg)' : '#dbeafe'};
          color:${isResubmitted ? 'var(--amber-text)' : '#1e40af'};">
          ${isResubmitted ? 'Resubmitted' : 'Reviewing'}
        </span>
      </div>
      ${clarifyThread}
      <div style="display:grid;grid-template-columns:1fr;gap:8px;margin-bottom:16px;">
        <div style="background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);
          padding:14px 16px;display:flex;align-items:center;justify-content:space-between;">
          <div style="font-size:12px;color:var(--text-3);">Total Collected</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:22px;
            font-weight:700;color:var(--text);">${fmt(c.total_collected)}</div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;">
          <div style="padding:10px 12px;background:var(--cash-bg,#f0fdf4);border:1px solid var(--cash-border,#bbf7d0);border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:var(--cash-text,#166534);text-transform:uppercase;margin-bottom:3px;">Cash</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;">${fmt(c.total_cash)}</div>
            <div style="font-size:10px;color:var(--text-3);margin-top:2px;">${pct(c.cash_pct)}</div>
          </div>
          <div style="padding:10px 12px;background:var(--momo-bg,#fffbeb);border:1px solid var(--momo-border,#fde68a);border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:var(--momo-text,#92400e);text-transform:uppercase;margin-bottom:3px;">MoMo</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;">${fmt(c.total_momo)}</div>
            <div style="font-size:10px;color:var(--text-3);margin-top:2px;">${pct(c.momo_pct)}</div>
          </div>
          <div style="padding:10px 12px;background:#eff6ff;border:1px solid #bfdbfe;border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:#1e40af;text-transform:uppercase;margin-bottom:3px;">POS</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;">${fmt(c.total_pos)}</div>
            <div style="font-size:10px;color:var(--text-3);margin-top:2px;">${pct(c.pos_pct)}</div>
          </div>
        </div>
      </div>
      ${c.bm_notes ? `
        <div style="margin-bottom:16px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;
            letter-spacing:0.6px;margin-bottom:8px;">BM Notes</div>
          <div style="background:var(--bg);border:1px solid var(--border);
            border-radius:var(--radius-sm);padding:12px 14px;font-size:13px;color:var(--text-2);">
            ${_esc(c.bm_notes)}
          </div>
        </div>` : ''}
      <div style="border-top:1px solid var(--border);padding-top:14px;">
        <textarea id="fin-notes-${c.id}" rows="2"
          placeholder="Finance notes (saved on clear)..."
          style="width:100%;padding:8px 12px;border:1px solid var(--border);
            border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
            font-size:12px;resize:none;box-sizing:border-box;margin-bottom:10px;
            font-family:'DM Sans',sans-serif;"></textarea>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button class="btn-clarify" onclick="FinancePortal.openClarifyModal(${c.id})">
            Request Clarification
          </button>
          <button class="btn-clear" onclick="FinancePortal.openClearModal(${c.id})">
            Clear
          </button>
        </div>
      </div>`;
  }

  function _renderBudgetCard(b) {
    const statusColors = {
      DRAFT:            { bg:'var(--bg)',       text:'var(--text-3)' },
      PENDING_APPROVAL: { bg:'var(--amber-bg)', text:'var(--amber-text)' },
      APPROVED:         { bg:'var(--green-bg)', text:'var(--green-text)' },
      CLOSED:           { bg:'var(--bg)',       text:'var(--text-3)' },
    };
    const sc = statusColors[b.status] || statusColors.DRAFT;
    const approveBtn = b.status === 'PENDING_APPROVAL'
      ? `<button onclick="FinanceBudget.approveBudget(${b.id})"
          style="padding:6px 14px;background:var(--green-text);color:#fff;border:none;
            border-radius:var(--radius-sm);font-size:12px;font-weight:700;cursor:pointer;font-family:inherit;">
          Approve
        </button>` : '';

    return `
      <div style="border:1px solid var(--border);border-radius:var(--radius);
        overflow:hidden;margin-bottom:16px;">
        <div style="padding:14px 20px;background:var(--text);
          display:flex;align-items:center;justify-content:space-between;">
          <span style="font-family:'Syne',sans-serif;font-size:16px;font-weight:800;color:#fff;">
            Budget ${b.year}
          </span>
          <div style="display:flex;align-items:center;gap:10px;">
            ${approveBtn}
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;
              background:${sc.bg};color:${sc.text};">
              ${b.status.replace('_',' ')}
            </span>
          </div>
        </div>
        <div style="padding:16px 20px;font-size:13px;color:var(--text-3);">
          Proposed by ${b.proposed_by_name || '—'}
          ${b.approved_by_name ? ' &middot; Approved by ' + b.approved_by_name : ''}
        </div>
      </div>`;
  }

  function _renderProcCard(o, isPending) {
    const statusColors = {
      PENDING_FINANCE:  { bg:'var(--amber-bg)', text:'var(--amber-text)' },
      FINANCE_APPROVED: { bg:'#dbeafe',         text:'#1e40af' },
      IN_TRANSIT:       { bg:'#f3e8ff',         text:'#6b21a8' },
      DELIVERED:        { bg:'var(--amber-bg)', text:'var(--amber-text)' },
      CLOSED:           { bg:'var(--green-bg)', text:'var(--green-text)' },
      CANCELLED:        { bg:'var(--bg)',       text:'var(--text-3)' },
    };
    const sc = statusColors[o.status] || { bg:'var(--bg)', text:'var(--text-3)' };
    const budget = o.approved_budget
      ? `GHS ${parseFloat(o.approved_budget).toFixed(2)}`
      : `Est. GHS ${parseFloat(o.estimated_total||0).toFixed(2)}`;

    return `
      <div style="border:1px solid ${isPending ? 'var(--amber-border,#fde68a)' : 'var(--border)'};
        border-radius:var(--radius);padding:18px 20px;margin-bottom:12px;
        background:${isPending ? 'var(--amber-bg,#fffbeb)' : 'var(--panel)'};">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:10px;">
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:14px;
              font-weight:700;color:var(--text);margin-bottom:4px;">${_esc(o.order_number)}</div>
            <div style="font-size:12px;color:var(--text-3);display:flex;gap:12px;flex-wrap:wrap;">
              <span>${_esc(o.branch_name)}</span>
              <span>Week ${o.week_number}, ${o.year}</span>
              <span>${o.line_item_count || '—'} items</span>
            </div>
          </div>
          <div style="text-align:right;flex-shrink:0;margin-left:16px;">
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;
              font-weight:700;background:${sc.bg};color:${sc.text};">
              ${o.status.replace(/_/g,' ')}
            </span>
            <div style="font-family:'JetBrains Mono',monospace;font-size:16px;
              font-weight:700;color:var(--text);margin-top:6px;">${budget}</div>
          </div>
        </div>
        ${isPending ? `
          <div style="display:flex;justify-content:flex-end;padding-top:10px;
            border-top:1px solid var(--amber-border,#fde68a);">
            <button onclick="FinancePortal.openProcApproveModal(${o.id})"
              style="padding:8px 20px;background:var(--text);color:#fff;border:none;
                border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                cursor:pointer;font-family:inherit;">
              Review & Approve
            </button>
          </div>` : ''}
      </div>`;
  }

  function _renderVendorCard(v) {
    const itemRows = (v.items || []).map(item => `
      <div style="display:flex;align-items:center;justify-content:space-between;
        padding:8px 0;border-bottom:1px solid var(--border);">
        <div style="font-size:12px;color:var(--text-2);">${_esc(item.consumable_name)}</div>
        <div style="display:flex;align-items:center;gap:12px;">
          ${item.is_preferred ? '<span style="font-size:10px;color:var(--green-text);font-weight:700;">PREFERRED</span>' : ''}
          <div style="font-family:\'JetBrains Mono\',monospace;font-size:12px;font-weight:700;color:var(--text);">
            GHS ${parseFloat(item.current_price||0).toFixed(2)}
          </div>
        </div>
      </div>`).join('');

    return `
      <div style="border:1px solid var(--border);border-radius:var(--radius);
        overflow:hidden;margin-bottom:16px;">
        <div style="padding:12px 18px;background:var(--bg);
          display:flex;align-items:center;justify-content:space-between;">
          <div>
            <div style="font-size:14px;font-weight:700;color:var(--text);">${_esc(v.name)}</div>
            <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
              ${v.phone || ''} ${v.email ? '&middot; ' + v.email : ''} &middot; ${v.payment_term}
            </div>
          </div>
          <span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;
            background:${v.is_active ? 'var(--green-bg)' : 'var(--bg)'};
            color:${v.is_active ? 'var(--green-text)' : 'var(--text-3)'};">
            ${v.is_active ? 'Active' : 'Inactive'}
          </span>
        </div>
        <div style="padding:12px 18px;">
          ${itemRows || '<div style="font-size:12px;color:var(--text-3);">No items on pricelist yet.</div>'}
        </div>
      </div>`;
  }

  // ── Clarification modal ───────────────────────────────────
  function openClarifyModal(id) {
    _clarifyCloseId = id;
    document.getElementById('clarify-text').value = '';
    document.getElementById('clarify-error').style.display = 'none';
    document.getElementById('clarify-modal-overlay').style.display = 'flex';
    setTimeout(() => document.getElementById('clarify-text')?.focus(), 100);
  }

  function closeClarifyModal() {
    document.getElementById('clarify-modal-overlay').style.display = 'none';
    _clarifyCloseId = null;
  }

  async function confirmClarify() {
    const text    = document.getElementById('clarify-text')?.value.trim();
    const errorEl = document.getElementById('clarify-error');
    errorEl.style.display = 'none';
    if (!text) { errorEl.textContent = 'Cannot be empty.'; errorEl.style.display = 'block'; return; }
    try {
      const res = await Auth.fetch(
        `/api/v1/finance/monthly-close/${_clarifyCloseId}/request-clarification/`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ clarification: text }),
        });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent = err.detail || 'Request failed.';
        errorEl.style.display = 'block';
        return;
      }
      closeClarifyModal();
      _toast('Clarification requested. BM has 24 hours to respond.', 'success');
      _loadReviewQueue();
    } catch {
      errorEl.textContent = 'Network error.';
      errorEl.style.display = 'block';
    }
  }

  // ── Clear modal ───────────────────────────────────────────
  function openClearModal(id) {
    _clearCloseId = id;
    const inlineNotes = document.getElementById(`fin-notes-${id}`)?.value.trim() || '';
    document.getElementById('clear-notes').value = inlineNotes;
    document.getElementById('clear-error').style.display = 'none';
    document.getElementById('clear-modal-overlay').style.display = 'flex';
  }

  function closeClearModal() {
    document.getElementById('clear-modal-overlay').style.display = 'none';
    _clearCloseId = null;
  }

  async function confirmClear() {
    const notes   = document.getElementById('clear-notes')?.value.trim() || '';
    const errorEl = document.getElementById('clear-error');
    errorEl.style.display = 'none';
    try {
      const res = await Auth.fetch(
        `/api/v1/finance/monthly-close/${_clearCloseId}/clear/`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ finance_notes: notes }),
        });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent = err.detail || 'Clear failed.';
        errorEl.style.display = 'block';
        return;
      }
      closeClearModal();
      _toast('Monthly close cleared. Regional Manager notified.', 'success');
      _loadReviewQueue();
    } catch {
      errorEl.textContent = 'Network error.';
      errorEl.style.display = 'block';
    }
  }

  // ── Procurement approve modal ─────────────────────────────
  async function openProcApproveModal(orderId) {
    _procActiveId = orderId;
    try {
      const res   = await Auth.fetch(`/api/v1/procurement/orders/${orderId}/`);
      const order = await res.json();
      _set('proc-approve-number',    order.order_number);
      _set('proc-approve-branch',    `${order.branch_name} · Week ${order.week_number}, ${order.year}`);
      _set('proc-approve-estimated', `GHS ${parseFloat(order.estimated_total||0).toFixed(2)}`);
      const tbody = document.getElementById('proc-approve-tbody');
      let total   = 0;
      tbody.innerHTML = (order.line_items || []).map(li => {
        const lt = parseFloat(li.line_total || 0);
        total   += lt;
        return `
          <tr>
            <td style="padding:9px 14px;border-bottom:1px solid var(--border);font-size:13px;font-weight:600;">
              ${_esc(li.consumable_name)}</td>
            <td style="padding:9px 14px;border-bottom:1px solid var(--border);text-align:right;
              font-family:'JetBrains Mono',monospace;font-size:12px;">
              ${parseFloat(li.requested_qty||0).toFixed(2)} ${li.unit_label || ''}</td>
            <td style="padding:9px 14px;border-bottom:1px solid var(--border);text-align:right;
              font-family:'JetBrains Mono',monospace;font-size:12px;">
              ${li.unit_cost > 0 ? `GHS ${parseFloat(li.unit_cost).toFixed(2)}` : '—'}</td>
            <td style="padding:9px 14px;border-bottom:1px solid var(--border);text-align:right;
              font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;">
              ${lt > 0 ? `GHS ${lt.toFixed(2)}` : '—'}</td>
          </tr>`;
      }).join('');
      tbody.innerHTML += `
        <tr style="background:var(--bg);">
          <td colspan="3" style="padding:10px 14px;font-weight:700;text-align:right;font-size:13px;">Total</td>
          <td style="padding:10px 14px;text-align:right;font-family:'JetBrains Mono',monospace;
            font-weight:700;font-size:14px;">GHS ${total.toFixed(2)}</td>
        </tr>`;
      document.getElementById('proc-budget-input').value   = parseFloat(order.estimated_total||0).toFixed(2);
      document.getElementById('proc-approve-notes').value  = '';
      document.getElementById('proc-approve-error').style.display = 'none';
      document.getElementById('proc-approve-overlay').style.display = 'flex';
    } catch {
      _toast('Could not load order details.', 'error');
    }
  }

  function closeProcApproveModal() {
    document.getElementById('proc-approve-overlay').style.display = 'none';
    _procActiveId = null;
  }

  async function confirmProcApprove() {
    const budget  = parseFloat(document.getElementById('proc-budget-input')?.value);
    const notes   = document.getElementById('proc-approve-notes')?.value || '';
    const errorEl = document.getElementById('proc-approve-error');
    const btn     = document.getElementById('btn-proc-approve');
    errorEl.style.display = 'none';
    if (isNaN(budget) || budget <= 0) {
      errorEl.textContent = 'Please enter a valid amount.';
      errorEl.style.display = 'block';
      return;
    }
    btn.disabled = true; btn.textContent = 'Approving...';
    try {
      const res  = await Auth.fetch(
        `/api/v1/procurement/orders/${_procActiveId}/approve/`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approved_budget: budget, finance_notes: notes }),
        });
      const data = await res.json();
      if (!res.ok) { errorEl.textContent = data.detail || 'Approval failed.'; errorEl.style.display = 'block'; return; }
      closeProcApproveModal();
      _toast(`Order approved. GHS ${budget.toFixed(2)} cleared.`, 'success');
      _loadProcurementPending();
    } catch {
      errorEl.textContent = 'Network error.';
      errorEl.style.display = 'block';
    } finally {
      btn.disabled = false; btn.textContent = 'Approve Budget';
    }
  }

  function openProcRejectModal() {
    document.getElementById('proc-reject-notes').value = '';
    document.getElementById('proc-reject-error').style.display = 'none';
    document.getElementById('proc-reject-overlay').style.display = 'flex';
  }

  function closeProcRejectModal() {
    document.getElementById('proc-reject-overlay').style.display = 'none';
  }

  async function confirmProcReject() {
    const notes   = document.getElementById('proc-reject-notes')?.value?.trim();
    const errorEl = document.getElementById('proc-reject-error');
    const btn     = document.getElementById('btn-proc-reject');
    errorEl.style.display = 'none';
    if (!notes || notes.length < 10) {
      errorEl.textContent = 'Please provide a rejection reason (min 10 characters).';
      errorEl.style.display = 'block';
      return;
    }
    btn.disabled = true; btn.textContent = 'Rejecting...';
    try {
      const res  = await Auth.fetch(
        `/api/v1/procurement/orders/${_procActiveId}/reject/`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ finance_notes: notes }),
        });
      const data = await res.json();
      if (!res.ok) { errorEl.textContent = data.detail || 'Rejection failed.'; errorEl.style.display = 'block'; return; }
      closeProcRejectModal();
      closeProcApproveModal();
      _toast('Order returned to Operations for revision.', 'info');
      _loadProcurementPending();
    } catch {
      errorEl.textContent = 'Network error.';
      errorEl.style.display = 'block';
    } finally {
      btn.disabled = false; btn.textContent = 'Confirm Rejection';
    }
  }

  // ── Budget modals (delegated to FinanceBudget) ────────────
  function openProposeBudgetModal()  { if (window.FinanceBudget) FinanceBudget.openProposeBudgetModal(); }
  function closeProposeBudgetModal() { if (window.FinanceBudget) FinanceBudget.closeProposeBudgetModal(); }
  function confirmProposeBudget()    { if (window.FinanceBudget) FinanceBudget.confirmProposeBudget(); }
  function openAddVendorModal()      { if (window.FinanceBudget) FinanceBudget.openAddVendorModal(); }
  function closeAddVendorModal()     { if (window.FinanceBudget) FinanceBudget.closeAddVendorModal(); }
  function confirmAddVendor()        { if (window.FinanceBudget) FinanceBudget.confirmAddVendor(); }

  // ── Profile & theme ───────────────────────────────────────
  function toggleProfileMenu() {
    _profileOpen = !_profileOpen;
    const dd    = document.getElementById('fin-profile-dropdown');
    const arrow = document.getElementById('fin-profile-arrow');
    if (dd)    dd.classList.toggle('open', _profileOpen);
    if (arrow) arrow.style.transform = _profileOpen ? 'rotate(180deg)' : 'rotate(0deg)';
  }

  function toggleTheme() {
    const html  = document.documentElement;
    const isDark = html.getAttribute('data-theme') === 'dark';
    html.setAttribute('data-theme', isDark ? 'light' : 'dark');
    _set('theme-label', isDark ? 'Dark Mode' : 'Light Mode');
  }

  function openSettings() {
    toggleProfileMenu();
    _toast('Settings coming soon.', 'info');
  }

  function toggleNotifications() {
    _toast('Notifications coming soon.', 'info');
  }

  // ── Helpers ───────────────────────────────────────────────
  function _setContent(html) {
    const el = document.getElementById('fin-content');
    if (el) el.innerHTML = `<div class="fin-content-inner">${html}</div>`;
  }

  function _set(id, val) {
    const el = document.getElementById(id);
    if (el) el.textContent = val;
  }

  function _esc(str) {
    if (!str) return '';
    return String(str)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;')
      .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
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

  function _emptyState(title, sub) {
    return `
      <div style="text-align:center;padding:60px;color:var(--text-3);">
        <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">${title}</div>
        <div style="font-size:13px;">${sub}</div>
      </div>`;
  }

  // Close profile menu on outside click
  document.addEventListener('click', e => {
    if (_profileOpen &&
        !e.target.closest('#fin-profile-btn') &&
        !e.target.closest('#fin-profile-dropdown')) {
      _profileOpen = false;
      const dd    = document.getElementById('fin-profile-dropdown');
      const arrow = document.getElementById('fin-profile-arrow');
      if (dd)    dd.classList.remove('open');
      if (arrow) arrow.style.transform = 'rotate(0deg)';
    }
  });

  return {
    init,
    switchSection,
    switchTab,
    // Reviews
    openClarifyModal, closeClarifyModal, confirmClarify,
    openClearModal,   closeClearModal,   confirmClear,
    // Procurement
    openProcApproveModal, closeProcApproveModal, confirmProcApprove,
    openProcRejectModal,  closeProcRejectModal,  confirmProcReject,
    // Budget & Vendors (delegated)
    openProposeBudgetModal, closeProposeBudgetModal, confirmProposeBudget,
    openAddVendorModal,     closeAddVendorModal,     confirmAddVendor,
    // UI
    toggleProfileMenu, toggleTheme, openSettings, toggleNotifications,
  };

})();

document.addEventListener('DOMContentLoaded', FinancePortal.init);