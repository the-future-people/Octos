'use strict';

const Reports = (() => {

  // ── Private state ──────────────────────────────────────────
  let _servicesPeriod  = 'month';
  let _historyLevel    = 'year';
  let _historyYear     = null;
  let _historyMonth    = null;
  let _historyWeek     = null;
  let _historyCharts   = {};
  let _openDailySheet  = null;
  let _openHistoryWeek = null;

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

  // ── Reports pane ───────────────────────────────────────────
  async function loadReportsPane() {
    const pane = document.getElementById('pane-reports');
    if (!pane) return;

    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Reports & Filing</span>
      </div>
      <div class="reports-tabs">
        <button class="reports-tab active" data-tab="daily"
          onclick="Reports.switchReportsTab('daily')">Daily</button>
        <button class="reports-tab" data-tab="filing"
          onclick="Reports.switchReportsTab('filing')">Weekly</button>
        <button class="reports-tab" data-tab="monthly"
          onclick="Reports.switchReportsTab('monthly')">Monthly</button>
        <button class="reports-tab" data-tab="yearly"
          onclick="Reports.switchReportsTab('yearly')">Yearly</button>
        <button class="reports-tab" data-tab="ledger"
          onclick="Reports.switchReportsTab('ledger')">Job Ledger</button>
      </div>
      <div id="reports-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;

    await _loadReportsTab('daily');
  }

  async function setReportsPeriod(period) {
    const activeTab = document.querySelector('.reports-tab.active')?.dataset.tab || 'daily';
    await _loadReportsTab(activeTab);
  }

  async function switchReportsTab(tab) {
    document.querySelectorAll('#pane-reports .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    await _loadReportsTab(tab);
  }

  async function _loadReportsTab(tab) {
    const content = document.getElementById('reports-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';
    if (tab === 'daily')   await _renderDailySheets(content);
    if (tab === 'filing')  await _renderWeeklyFiling(content);
    if (tab === 'monthly') await _renderMonthlyClose(content);
    if (tab === 'yearly')  await _renderYearlySummary(content);
    if (tab === 'ledger')  _renderHistoryReport(content);
  }

  // ── Service Performance ────────────────────────────────────
  async function _renderServicesReport(container) {
    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
        <div style="font-size:10.5px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.8px;">Service Performance</div>
        <div style="display:flex;gap:4px;">
          ${['day','week','month','year'].map(p => `
            <button onclick="Reports.setServicesPeriod('${p}')"
              class="reports-tab ${_servicesPeriod === p ? 'active' : ''}"
              data-period="${p}" style="padding:5px 12px;font-size:12px;">
              ${p.charAt(0).toUpperCase() + p.slice(1)}
            </button>`).join('')}
        </div>
      </div>
      <div id="services-report-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;
    await _fetchServicesReport();
  }

  async function _fetchServicesReport() {
    const content = document.getElementById('services-report-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';
    try {
      const res      = await Auth.fetch(`/api/v1/jobs/reports/services/?period=${_servicesPeriod}`);
      if (!res.ok) throw new Error();
      const data     = await res.json();
      const services = data.services || [];
      if (!services.length) {
        content.innerHTML = '<div class="loading-cell">No service data for this period.</div>';
        return;
      }
      const maxRev = Math.max(...services.map(s => parseFloat(s.revenue||0)));
      content.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:16px;">
          <div style="font-size:12px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:16px;">Revenue by Service</div>
          ${services.slice(0,10).map(s => {
            const pct = maxRev ? (parseFloat(s.revenue||0) / maxRev * 100) : 0;
            return `
              <div style="margin-bottom:10px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
                  <span style="font-size:12px;font-weight:500;color:var(--text);">${s.service}</span>
                  <span style="font-size:12px;font-family:'JetBrains Mono',monospace;color:var(--text-2);">${_fmt(s.revenue)}</span>
                </div>
                <div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden;">
                  <div style="height:100%;width:${pct}%;background:var(--text);border-radius:3px;transition:width 0.4s ease;"></div>
                </div>
              </div>`;
          }).join('')}
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">
          <table class="p-table">
            <thead><tr><th>Service</th><th>Jobs</th><th>Revenue</th><th>% of Total</th></tr></thead>
            <tbody>
              ${services.map(s => `
                <tr>
                  <td>${s.service}</td>
                  <td>${s.job_count}</td>
                  <td style="font-family:'JetBrains Mono',monospace;font-weight:600;">${_fmt(s.revenue)}</td>
                  <td>
                    <div style="display:flex;align-items:center;gap:8px;">
                      <div style="width:60px;height:4px;background:var(--border);border-radius:2px;">
                        <div style="height:100%;width:${s.percentage}%;background:var(--green-text);border-radius:2px;"></div>
                      </div>
                      <span style="font-size:12px;color:var(--text-2);">${s.percentage}%</span>
                    </div>
                  </td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    } catch {
      content.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load service data.</div>';
    }
  }

  async function setServicesPeriod(period) {
    _servicesPeriod = period;
    document.querySelectorAll('.reports-tab[data-period]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.period === period);
    });
    await _fetchServicesReport();
  }

  // ── Monthly Close ──────────────────────────────────────────
  async function _renderMonthlyClose(container) {
    if (!container) return;
    const now   = new Date();
    const month = now.getMonth() + 1;
    const year  = now.getFullYear();

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:var(--text);letter-spacing:-0.3px;">Monthly Close</div>
          <div style="font-size:12.5px;color:var(--text-3);margin-top:3px;">End-of-month operations closure and Finance review</div>
        </div>
      </div>
      <div id="monthly-current-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>
      <div id="monthly-history" style="margin-top:24px;"></div>`;

    try {
      const res     = await Auth.fetch(`/api/v1/finance/monthly-close/?month=${month}&year=${year}`);
      const content = document.getElementById('monthly-current-content');
      if (!content) return;
      if (!res.ok) {
        const monthName = ['January','February','March','April','May','June','July','August','September','October','November','December'][month - 1];
        content.innerHTML = `
          <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:24px 20px;text-align:center;color:var(--text-3);">
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:6px;">${monthName} ${year}</div>
            <div style="font-size:13px;">No monthly close record yet. Submit at month end when all integrity gates are met.</div>
          </div>`;
      } else {
        const data = await res.json();
        _renderMonthlyCloseDetail(content, data);
      }
    } catch {
      const content = document.getElementById('monthly-current-content');
      if (content) content.innerHTML = `
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:24px 20px;text-align:center;color:var(--text-3);font-size:13px;">
          Monthly close not yet initiated for this month.
        </div>`;
    }
    await _loadMonthlyHistory();
  }

  async function _loadMonthlyHistory() {
    const container = document.getElementById('monthly-history');
    if (!container) return;
    const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    try {
      const now          = new Date();
      const year         = now.getFullYear();
      const currentMonth = now.getMonth() + 1;
      const fetches      = [];
      for (let m = 1; m < currentMonth; m++) {
        fetches.push(
          Auth.fetch(`/api/v1/finance/monthly-close/?month=${m}&year=${year}`)
            .then(r => r.ok ? r.json() : null).catch(() => null)
        );
      }
      const results = await Promise.all(fetches);
      const closes  = results.filter(r => r && r.status && r.status !== 'OPEN').sort((a, b) => b.month - a.month);
      if (!closes.length) return;

      const statusConfig = {
        SUBMITTED          : { bg: 'var(--amber-bg)',  text: 'var(--amber-text)',  label: 'Awaiting Finance' },
        FINANCE_REVIEWING  : { bg: '#dbeafe',           text: '#1e40af',            label: 'Finance Reviewing' },
        NEEDS_CLARIFICATION: { bg: 'var(--amber-bg)',  text: 'var(--amber-text)',  label: 'Needs Clarification' },
        RESUBMITTED        : { bg: 'var(--amber-bg)',  text: 'var(--amber-text)',  label: 'Resubmitted' },
        FINANCE_CLEARED    : { bg: 'var(--green-bg)',  text: 'var(--green-text)',  label: 'Finance Cleared' },
        ENDORSED           : { bg: 'var(--green-bg)',  text: 'var(--green-text)',  label: 'Endorsed ✓' },
        LOCKED             : { bg: 'var(--green-bg)',  text: 'var(--green-text)',  label: 'Locked ✓' },
        REJECTED           : { bg: 'var(--red-bg)',    text: 'var(--red-text)',    label: 'Rejected' },
      };

      container.innerHTML = `
        <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">Previous Monthly Closes</div>
        ${closes.map(c => {
          const snap    = c.summary_snapshot || {};
          const revenue = snap.revenue || {};
          const jobs    = snap.jobs    || {};
          const sc      = statusConfig[c.status] || { bg:'var(--bg)', text:'var(--text-3)', label: c.status };
          const canDownload = ['ENDORSED','LOCKED'].includes(c.status);
          return `
            <div style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:10px;">
              <div style="padding:16px 20px;background:var(--panel);border-bottom:1px solid var(--border);">
                <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:10px;">
                  <div>
                    <div style="font-size:15px;font-weight:700;color:var(--text);">${monthNames[(c.month||1)-1]} ${c.year}</div>
                    <div style="font-size:11px;color:var(--text-3);margin-top:2px;">Submitted by ${c.submitted_by || '—'}${c.submitted_at ? ' · ' + new Date(c.submitted_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : ''}</div>
                  </div>
                  <div style="display:flex;align-items:center;gap:8px;">
                    <span style="padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;background:${sc.bg};color:${sc.text};">${sc.label}</span>
                    ${canDownload ? `<button onclick="Reports.downloadMonthlyPDF(${c.id})" style="display:inline-flex;align-items:center;gap:5px;padding:6px 14px;background:var(--text);color:#fff;border:none;border-radius:var(--radius-sm);font-size:12px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;">PDF</button>` : ''}
                  </div>
                </div>
                ${snap.revenue ? `
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
                  ${[['Total Collected',_fmt(revenue.total_collected||0),'var(--text)'],['Cash',_fmt(revenue.total_cash||0),'var(--cash-strong)'],['MoMo',_fmt(revenue.total_momo||0),'var(--momo-strong)'],['Jobs',jobs.total||0,'var(--text)']].map(([label,val,color]) => `
                    <div style="padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);">
                      <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">${label}</div>
                      <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:${color};">${val}</div>
                    </div>`).join('')}
                </div>` : ''}
              </div>
              <div style="padding:12px 20px;background:var(--bg);">
                <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Audit Trail</div>
                <div style="display:flex;flex-direction:column;gap:6px;">
                  ${[['Submitted',c.submitted_by,c.submitted_at,'#3355cc'],['Finance Cleared',c.finance_reviewer,c.finance_cleared_at,'#22c98a'],['Endorsed',c.endorsed_by,c.endorsed_at,'#9b59b6'],['Locked',c.locked_at?'System':null,c.locked_at,'#666']].filter(([,actor])=>actor).map(([label,actor,ts,color]) => `
                    <div style="display:flex;align-items:center;gap:10px;">
                      <div style="width:6px;height:6px;border-radius:50%;background:${color};flex-shrink:0;"></div>
                      <span style="font-size:12px;font-weight:600;color:var(--text);min-width:120px;">${label}</span>
                      <span style="font-size:12px;color:var(--text-2);">${actor||'—'}</span>
                      ${ts ? `<span style="font-size:11px;color:var(--text-3);margin-left:auto;">${new Date(ts).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})}</span>` : ''}
                    </div>`).join('')}
                </div>
                ${c.rejection_reason ? `<div style="margin-top:10px;padding:8px 12px;background:var(--red-bg);border:1px solid var(--red-border);border-radius:var(--radius-sm);font-size:12px;color:var(--red-text);"><strong>Rejection reason:</strong> ${c.rejection_reason}</div>` : ''}
              </div>
            </div>`;
        }).join('')}`;
    } catch { /* silent */ }
  }

  function _renderMonthlyCloseDetail(container, data) {
    const snap     = data.summary_snapshot || {};
    const revenue  = snap.revenue || {};
    const jobs     = snap.jobs    || {};
    const inv      = snap.inventory || {};
    const invItems = (inv.items || []).filter(i => i.consumed > 0);
    const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const monthName  = monthNames[(data.month||1)-1];

    const statusConfig = {
      SUBMITTED          : { bg: 'var(--amber-bg)',  text: 'var(--amber-text)',  label: 'Awaiting Finance' },
      FINANCE_REVIEWING  : { bg: '#dbeafe',           text: '#1e40af',            label: 'Finance Reviewing' },
      NEEDS_CLARIFICATION: { bg: 'var(--amber-bg)',  text: 'var(--amber-text)',  label: 'Needs Clarification' },
      RESUBMITTED        : { bg: 'var(--amber-bg)',  text: 'var(--amber-text)',  label: 'Resubmitted' },
      FINANCE_CLEARED    : { bg: 'var(--green-bg)',  text: 'var(--green-text)',  label: 'Finance Cleared' },
      ENDORSED           : { bg: 'var(--green-bg)',  text: 'var(--green-text)',  label: 'Endorsed ✓' },
      LOCKED             : { bg: 'var(--green-bg)',  text: 'var(--green-text)',  label: 'Locked ✓' },
      REJECTED           : { bg: 'var(--red-bg)',    text: 'var(--red-text)',    label: 'Rejected' },
    };
    const sc = statusConfig[data.status] || { bg:'var(--bg)', text:'var(--text-3)', label: data.status };

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;padding:16px 20px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);">
        <div>
          <div style="font-size:16px;font-weight:700;color:var(--text);">${monthName} ${data.year}</div>
          <div style="font-size:11px;color:var(--text-3);margin-top:3px;">Submitted by ${_esc(data.submitted_by || '—')}${data.submitted_at ? ' · ' + new Date(data.submitted_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : ''}</div>
        </div>
        <span style="padding:4px 14px;border-radius:20px;font-size:11px;font-weight:700;background:${sc.bg};color:${sc.text};">${sc.label}</span>
      </div>
      ${revenue.total_collected != null ? `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px;">
        ${[['Total Collected',_fmt(revenue.total_collected||0),'var(--text)'],['Cash',_fmt(revenue.total_cash||0),'var(--cash-strong, var(--green-text))'],['MoMo',_fmt(revenue.total_momo||0),'var(--momo-strong, var(--amber-text))'],['Jobs',jobs.total||0,'var(--text)']].map(([label,val,color]) => `
          <div style="padding:12px 14px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">${label}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:700;color:${color};">${val}</div>
          </div>`).join('')}
      </div>` : ''}
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;margin-bottom:16px;">
        <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">Inventory Consumed This Month</div>
        ${invItems.length ? `
        <table style="width:100%;border-collapse:collapse;font-size:12px;">
          <thead><tr style="background:var(--bg);border-bottom:1px solid var(--border);">
            <th style="padding:5px 10px;text-align:left;font-size:9px;font-weight:700;color:var(--text-3);text-transform:uppercase;">Consumable</th>
            <th style="padding:5px 10px;text-align:right;font-size:9px;font-weight:700;color:var(--text-3);text-transform:uppercase;">Consumed</th>
            <th style="padding:5px 10px;text-align:right;font-size:9px;font-weight:700;color:var(--text-3);text-transform:uppercase;">Closing</th>
            <th style="padding:5px 10px;text-align:center;font-size:9px;font-weight:700;color:var(--text-3);text-transform:uppercase;">Status</th>
          </tr></thead>
          <tbody>
            ${invItems.map(item => {
              const isToner = item.unit === '%';
              const closing = parseFloat(item.closing);
              const isLow   = item.is_low;
              const color   = isToner ? (closing >= 30 ? 'var(--green-text)' : closing >= 15 ? 'var(--amber-text)' : 'var(--red-text)') : (isLow ? 'var(--red-text)' : 'var(--text-2)');
              const badge   = isLow
                ? `<span style="background:#fee2e2;color:var(--red-text);padding:1px 6px;border-radius:4px;font-size:9px;font-weight:700;">LOW</span>`
                : `<span style="background:#dcfce7;color:var(--green-text);padding:1px 6px;border-radius:4px;font-size:9px;font-weight:700;">OK</span>`;
              return `<tr style="border-bottom:1px solid var(--border);">
                <td style="padding:6px 10px;color:var(--text);">${_esc(item.consumable)}</td>
                <td style="padding:6px 10px;text-align:right;color:var(--text-3);font-family:'JetBrains Mono',monospace;">${item.consumed} ${item.unit}</td>
                <td style="padding:6px 10px;text-align:right;font-weight:600;font-family:'JetBrains Mono',monospace;color:${color};">${item.closing} ${item.unit}</td>
                <td style="padding:6px 10px;text-align:center;">${badge}</td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>` : `<div style="font-size:12px;color:var(--text-3);padding:8px 0;">${data.status === 'OPEN' ? 'Inventory snapshot is generated when the month is submitted.' : 'No consumption recorded for this month.'}</div>`}
      </div>
      ${data.bm_notes ? `
      <div style="padding:12px 16px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);">
        <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">Branch Manager Notes</div>
        <div style="font-size:13px;color:var(--text-2);">${_esc(data.bm_notes)}</div>
      </div>` : ''}`;
  }

  async function submitMonthlyClose(month, year) {
    const btn   = document.getElementById('monthly-submit-btn');
    const notes = document.getElementById('monthly-bm-notes')?.value.trim() || '';
    if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }
    try {
      const res = await Auth.fetch('/api/v1/finance/monthly-close/submit/', {
        method : 'POST',
        headers: { 'Content-Type': 'application/json' },
        body   : JSON.stringify({ month, year, bm_notes: notes }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        const msg = Array.isArray(err.detail) ? err.detail.join(' ') : (err.detail || 'Submission failed.');
        _toast(msg, 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Submit for Endorsement'; }
        return;
      }
      _toast('Monthly close submitted. Awaiting Belt Manager endorsement.', 'success');
      const content = document.getElementById('reports-content');
      if (content) await _renderMonthlyClose(content);
    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Submit for Endorsement'; }
    }
  }

  async function downloadMonthlyPDF(id) {
    try {
      const res = await Auth.fetch(`/api/v1/finance/monthly-close/${id}/pdf/`);
      if (!res.ok) { _toast('Could not generate PDF.', 'error'); return; }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = `monthly_close_${id}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch { _toast('Download failed.', 'error'); }
  }

  // ── Yearly Summary ─────────────────────────────────────────
  async function _renderYearlySummary(container) {
    if (!container) return;
    const year       = new Date().getFullYear();
    const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:var(--text);letter-spacing:-0.3px;">${year} Annual Overview</div>
          <div style="font-size:12.5px;color:var(--text-3);margin-top:3px;">Month-by-month summary for the current year</div>
        </div>
      </div>
      <div id="yearly-content"><div class="loading-cell"><span class="spin"></span> Loading…</div></div>`;

    try {
      const res = await Auth.fetch(`/api/v1/jobs/history/?level=month&year=${year}`);
      if (!res.ok) throw new Error();
      const data    = await res.json();
      const content = document.getElementById('yearly-content');
      if (!content) return;

      const kpis       = data.kpis || {};
      const items      = data.items || [];
      const maxRevenue = Math.max(...items.map(i => i.revenue || 0), 1);

      const kpiHtml = `
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:24px;">
          ${[
            { label:'Total Jobs', value: kpis.total?.value||0,   fmt: v=>v,       color:'#3355cc' },
            { label:'Revenue',    value: kpis.revenue?.value||0, fmt: v=>_fmt(v), color:'#22c98a' },
            { label:'Pending',    value: kpis.pending?.value||0, fmt: v=>v,       color:'#e8a820' },
            { label:'Completion', value: kpis.rate?.value||0,    fmt: v=>v+'%',   color:'#9b59b6' },
          ].map(k => `
            <div style="background:var(--panel);border:1px solid var(--border);border-top:3px solid ${k.color};border-radius:var(--radius);padding:14px 16px;">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:6px;">${k.label}</div>
              <div style="font-size:20px;font-weight:800;color:${k.color};font-family:'Outfit',sans-serif;">${k.fmt(k.value)}</div>
            </div>`).join('')}
        </div>`;

      const tableHtml = `
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:20px;">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:var(--bg);">
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);">Month</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);">Jobs</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);">Revenue</th>
                <th style="padding:10px 16px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);">Rate</th>
                <th style="padding:10px 16px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);">Trend</th>
                <th style="padding:10px 16px;text-align:center;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;border-bottom:2px solid var(--border);">Close</th>
              </tr>
            </thead>
            <tbody>
              ${monthNames.map((name, i) => {
                const m        = i + 1;
                const item     = items.find(it => it.month === m);
                const now      = new Date();
                const isPast   = m < now.getMonth() + 1;
                const isCurr   = m === now.getMonth() + 1;
                const isFuture = m > now.getMonth() + 1;
                if (isFuture) return `
                  <tr style="border-bottom:1px solid var(--border);opacity:0.3;">
                    <td style="padding:12px 16px;font-size:13px;font-weight:600;color:var(--text-3);">${name}</td>
                    <td colspan="5" style="padding:12px 16px;font-size:12px;color:var(--text-3);text-align:center;">—</td>
                  </tr>`;
                const total   = item?.total   || 0;
                const revenue = item?.revenue  || 0;
                const rate    = item?.rate     || 0;
                const barPct  = maxRevenue > 0 ? (revenue / maxRevenue * 100) : 0;
                return `
                  <tr style="border-bottom:1px solid var(--border);${isCurr?'background:var(--bg);':''}transition:background 0.12s;"
                    onmouseover="this.style.background='var(--bg)'"
                    onmouseout="this.style.background='${isCurr?'var(--bg)':''}'">
                    <td style="padding:12px 16px;">
                      <div style="display:flex;align-items:center;gap:8px;">
                        <span style="font-size:13px;font-weight:700;color:var(--text);">${name}</span>
                        ${isCurr ? `<span style="padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;background:var(--amber-bg);color:var(--amber-text);">Current</span>` : ''}
                      </div>
                    </td>
                    <td style="padding:12px 16px;text-align:right;font-size:13px;font-weight:600;color:var(--text);">${total}</td>
                    <td style="padding:12px 16px;text-align:right;font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:var(--text);">${_fmt(revenue)}</td>
                    <td style="padding:12px 16px;text-align:right;font-size:13px;font-weight:600;color:${rate>=95?'var(--green-text)':rate>=80?'var(--amber-text)':'var(--red-text)'};">${rate}%</td>
                    <td style="padding:12px 16px;">
                      <div style="height:6px;background:var(--border);border-radius:3px;width:120px;overflow:hidden;">
                        <div style="height:100%;width:${barPct.toFixed(1)}%;background:var(--text);border-radius:3px;transition:width 0.4s ease;"></div>
                      </div>
                    </td>
                    <td style="padding:12px 16px;text-align:center;">
                      ${isPast||isCurr ? `<button onclick="Reports.switchReportsTab('monthly')" style="padding:4px 12px;background:none;border:1px solid var(--border);border-radius:var(--radius-sm);font-size:11px;font-weight:600;cursor:pointer;color:var(--text-2);font-family:'DM Sans',sans-serif;">View</button>` : '—'}
                    </td>
                  </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>`;

      content.innerHTML = kpiHtml + tableHtml;
    } catch {
      const content = document.getElementById('yearly-content');
      if (content) content.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">Could not load yearly summary.</div>`;
    }
  }

  // ── Daily Sheets ───────────────────────────────────────────
  async function _renderDailySheets(container) {
    if (!container) return;
    const now = new Date();
    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:var(--text);letter-spacing:-0.3px;">Daily Sheets</div>
          <div style="font-size:12.5px;color:var(--text-3);margin-top:3px;">Closed sheets for ${now.toLocaleDateString('en-GB',{month:'long',year:'numeric'})} — read-only records</div>
        </div>
      </div>
      <div id="daily-sheets-list"><div class="loading-cell"><span class="spin"></span> Loading…</div></div>`;

    try {
      const res    = await Auth.fetch('/api/v1/finance/sheets/?period=month&page_size=31');
      if (!res.ok) throw new Error();
      const data   = await res.json();
      const sheets = (Array.isArray(data) ? data : (data.results || []))
        .filter(s => s.status !== 'OPEN')
        .sort((a, b) => new Date(b.date) - new Date(a.date));

      const list = document.getElementById('daily-sheets-list');
      if (!list) return;

      if (!sheets.length) {
        list.innerHTML = `
          <div style="text-align:center;padding:48px;color:var(--text-3);">
            <svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="opacity:0.3;display:block;margin:0 auto 12px;">
              <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
            </svg>
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">No closed sheets this month</div>
            <div style="font-size:13px;">Sheets appear here once closed by the Branch Manager.</div>
          </div>`;
        return;
      }

      list.innerHTML = sheets.map(s => {
        const total   = parseFloat(s.total_cash||0) + parseFloat(s.total_momo||0) + parseFloat(s.total_pos||0);
        const dateObj = new Date(s.date);
        const dayName = dateObj.toLocaleDateString('en-GB',{weekday:'long'});
        const dateStr = dateObj.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
        const isAuto  = s.status === 'AUTO_CLOSED';
        return `
          <div style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:10px;">
            <div onclick="Reports.toggleDailySheet(${s.id})"
              style="display:flex;align-items:center;justify-content:space-between;padding:14px 20px;background:var(--panel);cursor:pointer;transition:background 0.12s;"
              onmouseover="this.style.background='var(--bg)'" onmouseout="this.style.background='var(--panel)'">
              <div style="display:flex;align-items:center;gap:14px;">
                <div style="text-align:center;min-width:44px;">
                  <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;">${dateObj.toLocaleDateString('en-GB',{month:'short'})}</div>
                  <div style="font-size:22px;font-weight:800;color:var(--text);font-family:'Syne',sans-serif;line-height:1;">${dateObj.getDate()}</div>
                  <div style="font-size:10px;color:var(--text-3);">${dateObj.toLocaleDateString('en-GB',{weekday:'short'})}</div>
                </div>
                <div style="width:1px;height:40px;background:var(--border);"></div>
                <div>
                  <div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:3px;">
                    ${s.sheet_number ? `<span style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:600;color:var(--text-3);margin-right:6px;">${s.sheet_number}</span>` : ''}${dayName} · ${dateStr}
                  </div>
                  <div style="display:flex;align-items:center;gap:16px;">
                    <span style="font-size:12px;color:var(--text-3);">${s.total_jobs_created||0} jobs</span>
                    <span style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:var(--text);">${_fmt(total)}</span>
                  </div>
                </div>
              </div>
              <div style="display:flex;align-items:center;gap:10px;">
                <span style="padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;background:${isAuto?'var(--amber-bg)':'var(--green-bg)'};color:${isAuto?'var(--amber-text)':'var(--green-text)'};">${isAuto?'Auto-closed':'Closed'}</span>
                <svg id="daily-chevron-${s.id}" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--text-3);transition:transform 0.2s;">
                  <polyline points="6 9 12 15 18 9"/>
                </svg>
              </div>
            </div>
            <div id="daily-detail-${s.id}" style="display:none;">
              <div style="padding:16px 20px;border-top:1px solid var(--border);background:var(--bg);">
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px;">
                  ${[['Cash',s.total_cash,'cash'],['MoMo',s.total_momo,'momo'],['POS',s.total_pos,'pos'],['Net Cash in Till',s.net_cash_in_till,'green']].map(([label,val,theme]) => `
                    <div style="padding:10px 12px;background:var(--${theme}-bg,var(--bg));border:1px solid var(--${theme}-border,var(--border));border-radius:var(--radius-sm);">
                      <div style="font-size:10px;font-weight:700;color:var(--${theme}-text,var(--text-3));text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">${label}</div>
                      <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:var(--${theme}-strong,var(--text));">${_fmt(val)}</div>
                    </div>`).join('')}
                </div>
                <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px;">
                  ${[['Jobs Created',s.total_jobs_created||0,false],['Petty Cash Out',s.total_petty_cash_out,true],['Credit Issued',s.total_credit_issued,true],['Credit Settled',s.total_credit_settled,true]].map(([label,val,isMoney]) => `
                    <div style="padding:10px 12px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);">
                      <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">${label}</div>
                      <div style="font-size:15px;font-weight:700;color:var(--text);">${isMoney?_fmt(val):val}</div>
                    </div>`).join('')}
                </div>
                <div style="margin-bottom:14px;" id="daily-inv-${s.id}">
                  <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">Inventory Consumed</div>
                  <div class="loading-cell" style="padding:12px;"><span class="spin"></span></div>
                </div>
                <div style="display:flex;justify-content:flex-end;gap:8px;">
                  ${s.status !== 'OPEN' ? `
                    <button onclick="Dashboard.initiateSheetDownload(${s.id},'${s.date}')"
                      style="display:inline-flex;align-items:center;gap:6px;padding:7px 16px;background:var(--text);color:#fff;border:none;border-radius:var(--radius-sm);font-size:12px;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;">
                      <svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>
                      </svg>
                      Download PDF
                    </button>` : ''}
                </div>
              </div>
            </div>
          </div>`;
      }).join('');
    } catch {
      const list = document.getElementById('daily-sheets-list');
      if (list) list.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">Could not load daily sheets.</div>`;
    }
  }

  function toggleDailySheet(sheetId) {
    const detail  = document.getElementById(`daily-detail-${sheetId}`);
    const chevron = document.getElementById(`daily-chevron-${sheetId}`);
    const isOpen  = detail.style.display !== 'none';

    if (_openDailySheet && _openDailySheet !== sheetId) {
      const prev        = document.getElementById(`daily-detail-${_openDailySheet}`);
      const prevChevron = document.getElementById(`daily-chevron-${_openDailySheet}`);
      if (prev)        prev.style.display        = 'none';
      if (prevChevron) prevChevron.style.transform = 'rotate(0deg)';
    }

    if (isOpen) {
      detail.style.display    = 'none';
      chevron.style.transform = 'rotate(0deg)';
      _openDailySheet         = null;
    } else {
      detail.style.display    = 'block';
      chevron.style.transform = 'rotate(180deg)';
      _openDailySheet         = sheetId;
      loadDailySheetInventory(sheetId);
    }
  }

  async function loadDailySheetInventory(sheetId) {
    const container = document.getElementById(`daily-inv-${sheetId}`);
    if (!container) return;
    try {
      const res   = await Auth.fetch(`/api/v1/finance/sheets/${sheetId}/eod-summary/`);
      if (!res.ok) throw new Error();
      const data  = await res.json();
      const items = data.inventory_consumption || [];

      if (!items.length) {
        container.innerHTML = `
          <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">Inventory Consumed</div>
          <div style="font-size:12px;color:var(--text-3);padding:10px 0;">No inventory movements recorded.</div>`;
        return;
      }

      container.innerHTML = `
        <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">Inventory Consumed</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">
          ${items.map(item => {
            const closing    = parseFloat(item.closing);
            const consumed   = parseFloat(item.consumed || 0);
            const isPct      = item.unit === '%';
            const isCrit     = closing === 0;
            const isLow      = !isCrit && item.is_low;
            const statusColor= isCrit ? '#dc2626' : isLow ? '#d97706' : '#16a34a';
            const fmtQty     = n => isPct ? `${parseFloat(n).toFixed(1)}%` : parseFloat(n).toLocaleString('en-GH',{maximumFractionDigits:1});
            const total      = closing + consumed;
            const fillPct    = total > 0 ? Math.min(100,(closing/total)*100) : isPct ? Math.min(100,closing) : 0;
            return `
              <div style="position:relative;overflow:hidden;padding:9px 12px;background:var(--panel);border:1px solid ${isCrit?'#fca5a5':isLow?'#fcd34d':'var(--border)'};border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:space-between;gap:8px;">
                <div style="position:absolute;top:0;right:0;width:4px;height:100%;background:#e5e7eb;border-radius:0 var(--radius-sm) var(--radius-sm) 0;">
                  <div style="position:absolute;bottom:0;left:0;width:100%;height:${fillPct.toFixed(1)}%;background:${statusColor};border-radius:0 0 var(--radius-sm) var(--radius-sm);transition:height 0.3s ease;"></div>
                </div>
                <span style="font-size:11px;font-weight:600;color:${isCrit?'#dc2626':isLow?'#d97706':'var(--text)'};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;" title="${_esc(item.consumable)}">${_esc(item.consumable)}</span>
                <div style="display:flex;align-items:center;gap:5px;flex-shrink:0;padding-right:8px;">
                  ${consumed > 0 ? `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:600;color:#dc2626;">-${fmtQty(consumed)}</span><span style="color:var(--border);font-size:10px;">·</span>` : ''}
                  <span style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:${isCrit?'#dc2626':isLow?'#d97706':'var(--text)'};">${fmtQty(closing)}</span>
                </div>
              </div>`;
          }).join('')}
        </div>`;
    } catch {
      container.innerHTML = `
        <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">Inventory Consumed</div>
        <div style="font-size:12px;color:var(--red-text);">Could not load inventory data.</div>`;
    }
  }

  // ── Weekly Filing ──────────────────────────────────────────
  async function _renderWeeklyFiling(container) {
    if (!container) return;
    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:20px;">
        <div>
          <div style="font-family:'Syne',sans-serif;font-size:18px;font-weight:800;color:var(--text);letter-spacing:-0.3px;">Weekly Filing</div>
          <div style="font-size:12.5px;color:var(--text-3);margin-top:3px;">Monday – Saturday consolidated operations report</div>
        </div>
        <button id="weekly-prepare-btn" onclick="Reports.weeklyPrepare()"
          style="padding:8px 18px;background:var(--text);color:#fff;border:none;border-radius:var(--radius-sm);font-size:13px;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;">
          Prepare This Week
        </button>
      </div>
      <div id="weekly-content"><div class="loading-cell"><span class="spin"></span> Loading…</div></div>
      <div id="weekly-history" style="margin-top:24px;"></div>`;
    await _loadWeeklyReport();
    await _loadWeeklyHistory();
  }

  async function _loadWeeklyReport() {
    const content = document.getElementById('weekly-content');
    if (!content) return;
    try {
      const res     = await Auth.fetch('/api/v1/finance/weekly/');
      if (!res.ok) throw new Error();
      const data    = await res.json();
      const reports = Array.isArray(data) ? data : (data.results || []);
      const today   = new Date().toISOString().split('T')[0];
      const current = reports.find(r => r.date_from <= today && r.date_to >= today);

      if (current) {
        const detailRes = await Auth.fetch(`/api/v1/finance/weekly/${current.id}/`);
        if (!detailRes.ok) throw new Error();
        const fullReport = await detailRes.json();
        const prepareBtn = document.getElementById('weekly-prepare-btn');
        if (prepareBtn) prepareBtn.style.display = fullReport.status === 'LOCKED' ? 'none' : '';
        _renderWeeklyReportDetail(content, fullReport);
      } else {
        const prepareBtn = document.getElementById('weekly-prepare-btn');
        if (prepareBtn) prepareBtn.style.display = '';
        _renderWeeklyEmpty(content);
      }
    } catch {
      content.innerHTML = `<div style="text-align:center;padding:60px;color:var(--text-3);font-size:13px;">Could not load weekly filing.</div>`;
    }
  }

  async function _loadWeeklyHistory() {
    const container = document.getElementById('weekly-history');
    if (!container) return;
    try {
      const res     = await Auth.fetch('/api/v1/finance/weekly/');
      if (!res.ok) throw new Error();
      const data    = await res.json();
      const now       = new Date();
      const thisYear  = now.getFullYear();
      const thisMonth = now.getMonth() + 1;

      const reports = (Array.isArray(data) ? data : (data.results || []))
        .filter(r => {
          if (r.status !== 'LOCKED') return false;
          const from = new Date(r.date_from);
          const to   = new Date(r.date_to);
          // Include week if any part of it falls in the current month/year
          return (
            (from.getFullYear() === thisYear && from.getMonth() + 1 === thisMonth) ||
            (to.getFullYear()   === thisYear && to.getMonth()   + 1 === thisMonth)
          );
        })
        .sort((a, b) => b.year !== a.year ? b.year - a.year : b.week_number - a.week_number);
      if (!reports.length) return;

      container.innerHTML = `
        <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">Previous Filed Weeks</div>
        ${reports.map(r => {
          const total       = parseFloat(r.total_cash||0) + parseFloat(r.total_momo||0) + parseFloat(r.total_pos||0);
          const dateFrom    = new Date(r.date_from).toLocaleDateString('en-GB',{day:'numeric',month:'short'});
          const dateTo      = new Date(r.date_to).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
          const submittedAt = r.submitted_at ? new Date(r.submitted_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}) : '—';
          return `
            <div style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:8px;">
              <div onclick="Reports.toggleHistoryWeek(${r.id})"
                style="display:flex;align-items:center;justify-content:space-between;padding:14px 20px;background:var(--panel);cursor:pointer;transition:background 0.12s;"
                onmouseover="this.style.background='var(--bg)'" onmouseout="this.style.background='var(--panel)'">
                <div>
                  <div style="font-size:14px;font-weight:700;color:var(--text);margin-bottom:3px;">
                    Week ${r.week_number}, ${r.year}
                    <span style="font-size:12px;font-weight:400;color:var(--text-3);margin-left:8px;">${dateFrom} – ${dateTo}</span>
                  </div>
                  <div style="font-size:11px;color:var(--text-3);">Filed by ${r.submitted_by_name||'—'} · ${submittedAt}</div>
                </div>
                <div style="display:flex;align-items:center;gap:10px;">
                  <span style="padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;background:var(--green-bg);color:var(--green-text);">✓ Locked</span>
                  <button onclick="event.stopPropagation();Reports.weeklyDownloadPDF(${r.id})"
                    style="display:inline-flex;align-items:center;gap:5px;padding:6px 14px;background:var(--text);color:#fff;border:none;border-radius:var(--radius-sm);font-size:12px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;">
                    <svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>
                    PDF
                  </button>
                  <svg id="history-week-chevron-${r.id}" xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--text-3);transition:transform 0.2s;">
                    <polyline points="6 9 12 15 18 9"/>
                  </svg>
                </div>
              </div>
              <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:0;border-top:1px solid var(--border);">
                ${[['Total',_fmt(total),'var(--text)','var(--panel)'],['Cash',_fmt(r.total_cash),'var(--cash-strong)','var(--cash-bg)'],['MoMo',_fmt(r.total_momo),'var(--momo-strong)','var(--momo-bg)'],['Jobs',r.total_jobs_created||0,'var(--text)','var(--panel)']].map(([label,val,color,bg]) => `
                  <div style="padding:10px 16px;background:${bg};border-right:1px solid var(--border);">
                    <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">${label}</div>
                    <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:${color};">${val}</div>
                  </div>`).join('')}
              </div>
              <div id="history-week-detail-${r.id}" style="display:none;">
                <div style="padding:16px 20px;border-top:1px solid var(--border);background:var(--bg);">
                  <div class="loading-cell"><span class="spin"></span> Loading…</div>
                </div>
              </div>
            </div>`;
        }).join('')}`;
    } catch { /* silent */ }
  }

  async function toggleHistoryWeek(reportId) {
    const detail  = document.getElementById(`history-week-detail-${reportId}`);
    const chevron = document.getElementById(`history-week-chevron-${reportId}`);
    if (!detail) return;
    const isOpen = detail.style.display !== 'none';

    if (_openHistoryWeek && _openHistoryWeek !== reportId) {
      const prev        = document.getElementById(`history-week-detail-${_openHistoryWeek}`);
      const prevChevron = document.getElementById(`history-week-chevron-${_openHistoryWeek}`);
      if (prev)        prev.style.display        = 'none';
      if (prevChevron) prevChevron.style.transform = 'rotate(0deg)';
    }

    if (isOpen) {
      detail.style.display    = 'none';
      chevron.style.transform = 'rotate(0deg)';
      _openHistoryWeek        = null;
      return;
    }

    detail.style.display    = 'block';
    chevron.style.transform = 'rotate(180deg)';
    _openHistoryWeek        = reportId;

    const inner = detail.querySelector('div');
    try {
      const res    = await Auth.fetch(`/api/v1/finance/weekly/${reportId}/`);
      if (!res.ok) throw new Error();
      const report = await res.json();

      const days      = ['Mon','Tue','Wed','Thu','Fri','Sat'];
      const sheets    = report.daily_sheets || [];
      const sheetGrid = days.map((day, i) => {
        const sheet    = sheets.find(s => new Date(s.date).getDay() === (i + 1));
        if (!sheet) return `<div style="flex:1;padding:8px 6px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);text-align:center;"><div style="font-size:9px;font-weight:700;color:var(--text-3);text-transform:uppercase;margin-bottom:3px;">${day}</div><div style="font-size:9px;color:var(--text-3);">No sheet</div></div>`;
        const isClosed = sheet.status !== 'OPEN';
        const dotColor = isClosed ? 'var(--green-text)' : 'var(--amber-text)';
        const dotBg    = isClosed ? 'var(--green-bg)'   : 'var(--amber-bg)';
        const tot      = parseFloat(sheet.total_cash||0) + parseFloat(sheet.total_momo||0) + parseFloat(sheet.total_pos||0);
        return `<div style="flex:1;padding:8px 6px;background:${dotBg};border:1px solid ${isClosed?'var(--green-border)':'var(--amber-border)'};border-radius:var(--radius-sm);text-align:center;"><div style="font-size:9px;font-weight:700;color:${dotColor};text-transform:uppercase;margin-bottom:3px;">${day}</div><div style="font-size:9px;color:${dotColor};font-weight:600;">${isClosed?'✓':'●'}</div><div style="font-size:8px;color:${dotColor};margin-top:2px;font-family:'JetBrains Mono',monospace;">${_fmt(tot)}</div></div>`;
      }).join('');

      inner.innerHTML = `
        <div style="margin-bottom:14px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">Daily Sheets</div>
          <div style="display:flex;gap:6px;">${sheetGrid}</div>
        </div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:14px;">
          ${[['Jobs Created',report.total_jobs_created||0,'var(--text)'],['Completed',report.total_jobs_complete||0,'var(--green-text)'],['Cancelled',report.total_jobs_cancelled||0,'var(--red-text)'],['Carry Forward',report.carry_forward_count||0,'var(--amber-text)']].map(([label,val,color]) => `
            <div style="padding:10px 12px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);text-align:center;">
              <div style="font-size:18px;font-weight:700;color:${color};">${val}</div>
              <div style="font-size:10px;color:var(--text-3);margin-top:2px;">${label}</div>
            </div>`).join('')}
        </div>
        <div style="margin-bottom:14px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">Inventory Consumed This Week</div>
          ${_renderWeeklyInventory(report.inventory_snapshot)}
        </div>
        <div style="padding:10px 14px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">Branch Manager Notes</div>
          <div style="font-size:13px;color:var(--text-2);">${report.bm_notes||'—'}</div>
        </div>`;
    } catch {
      inner.innerHTML = `<div style="color:var(--red-text);font-size:13px;">Could not load week detail.</div>`;
    }
  }

  function _renderWeeklyEmpty(container) {
    const now      = new Date();
    const monday   = new Date(now);
    monday.setDate(now.getDate() - now.getDay() + 1);
    const saturday = new Date(monday);
    saturday.setDate(monday.getDate() + 5);
    const fmt = d => d.toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
    container.innerHTML = `
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:32px;text-align:center;">
        <div style="width:48px;height:48px;border-radius:12px;background:var(--bg);border:1px solid var(--border);display:flex;align-items:center;justify-content:center;margin:0 auto 16px;color:var(--text-3);">
          <svg xmlns="http://www.w3.org/2000/svg" width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
            <path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>
          </svg>
        </div>
        <div style="font-family:'Syne',sans-serif;font-size:15px;font-weight:700;color:var(--text);margin-bottom:6px;">No filing for this week</div>
        <div style="font-size:13px;color:var(--text-3);margin-bottom:20px;">${fmt(monday)} – ${fmt(saturday)}</div>
        <button onclick="Reports.weeklyPrepare()"
          style="padding:8px 20px;background:var(--text);color:#fff;border:none;border-radius:var(--radius-sm);font-size:13px;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;">
          Prepare Filing
        </button>
      </div>`;
  }

  function _renderWeeklyReportDetail(container, report) {
    const total    = parseFloat(report.total_cash||0) + parseFloat(report.total_momo||0) + parseFloat(report.total_pos||0);
    const dateFrom = new Date(report.date_from).toLocaleDateString('en-GB',{day:'numeric',month:'short'});
    const dateTo   = new Date(report.date_to).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'});
    const isLocked = report.status === 'LOCKED';
    const isDraft  = report.status === 'DRAFT';
    const statusConfig = {
      DRAFT    : { bg: 'var(--bg)',       text: 'var(--text-3)',     label: 'Draft' },
      SUBMITTED: { bg: 'var(--amber-bg)', text: 'var(--amber-text)', label: 'Submitted' },
      LOCKED   : { bg: 'var(--green-bg)', text: 'var(--green-text)', label: '✓ Locked' },
    };
    const sc = statusConfig[report.status] || statusConfig.DRAFT;

    container.innerHTML = `
      <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 20px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);margin-bottom:16px;">
        <div>
          <div style="font-size:15px;font-weight:700;color:var(--text);">Week ${report.week_number}, ${report.year} <span style="font-size:12px;font-weight:400;color:var(--text-3);margin-left:8px;">${dateFrom} – ${dateTo}</span></div>
          ${report.submitted_at ? `<div style="font-size:11px;color:var(--text-3);margin-top:3px;">Submitted ${new Date(report.submitted_at).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})}</div>` : ''}
        </div>
        <div style="display:flex;align-items:center;gap:10px;">
          <span style="padding:4px 12px;border-radius:20px;font-size:11px;font-weight:700;background:${sc.bg};color:${sc.text};">${sc.label}</span>
          ${isLocked ? `<button onclick="Reports.weeklyDownloadPDF(${report.id})" style="display:inline-flex;align-items:center;gap:5px;padding:6px 14px;background:var(--text);color:#fff;border:none;border-radius:var(--radius-sm);font-size:12px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;"><svg xmlns="http://www.w3.org/2000/svg" width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>PDF</button>` : ''}
        </div>
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px;">
        ${[['Cash',_fmt(report.total_cash),'var(--cash-bg,var(--bg))','var(--cash-strong,var(--text))'],['MoMo',_fmt(report.total_momo),'var(--momo-bg,var(--bg))','var(--momo-strong,var(--text))'],['POS',_fmt(report.total_pos),'var(--pos-bg,var(--bg))','var(--pos-strong,var(--text))'],['Total',_fmt(total),'var(--panel)','var(--text)']].map(([label,val,bg,color]) => `
          <div style="padding:12px 14px;background:${bg};border:1px solid var(--border);border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">${label}</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:14px;font-weight:700;color:${color};">${val}</div>
          </div>`).join('')}
      </div>
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:16px;">
        ${[['Jobs Created',report.total_jobs_created||0,'var(--text)'],['Completed',report.total_jobs_complete||0,'var(--green-text)'],['Cancelled',report.total_jobs_cancelled||0,'var(--red-text)'],['Carry Forward',report.carry_forward_count||0,'var(--amber-text)']].map(([label,val,color]) => `
          <div style="padding:12px 14px;background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:20px;font-weight:700;color:${color};">${val}</div>
            <div style="font-size:10px;color:var(--text-3);margin-top:3px;">${label}</div>
          </div>`).join('')}
      </div>
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;margin-bottom:16px;">
        <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">Inventory Consumed This Week</div>
        ${_renderWeeklyInventory(report.inventory_snapshot)}
      </div>
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:16px 20px;">
        <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:8px;">Branch Manager Notes</div>
        ${isDraft ? `
        <textarea id="weekly-notes" rows="3"
          style="width:100%;padding:10px 12px;border:1.5px solid var(--border);border-radius:var(--radius-sm);background:var(--bg);color:var(--text);font-size:13px;resize:vertical;box-sizing:border-box;font-family:'DM Sans',sans-serif;outline:none;margin-bottom:12px;"
          placeholder="Add notes before submitting…">${_esc(report.bm_notes||'')}</textarea>
        <button id="weekly-submit-btn" onclick="Reports.weeklySubmit(${report.id})"
          style="padding:10px 24px;background:var(--text);color:#fff;border:none;border-radius:var(--radius-sm);font-size:13px;font-weight:700;cursor:pointer;font-family:'DM Sans',sans-serif;">
          Submit & Lock Filing
        </button>` : `<div style="font-size:13px;color:var(--text-2);">${_esc(report.bm_notes||'—')}</div>`}
      </div>`;
  }

  function _renderWeeklyInventory(snapshot) {
    if (!snapshot || !snapshot.items || !snapshot.items.length) {
      return `<div style="font-size:12px;color:var(--text-3);padding:10px 0;">No inventory data for this week.</div>`;
    }
    const items = snapshot.items.filter(i => i.consumed > 0);
    if (!items.length) {
      return `<div style="font-size:12px;color:var(--text-3);padding:10px 0;">No consumption recorded this week.</div>`;
    }
    return `
      <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(200px,1fr));gap:8px;">
        ${items.map(item => {
          const closing    = parseFloat(item.closing);
          const consumed   = parseFloat(item.consumed||0);
          const isPct      = item.unit === '%';
          const isCrit     = closing === 0;
          const isLow      = !isCrit && item.is_low;
          const statusColor= isCrit ? '#dc2626' : isLow ? '#d97706' : '#16a34a';
          const fmtQty     = n => isPct ? `${parseFloat(n).toFixed(1)}%` : parseFloat(n).toLocaleString('en-GH',{maximumFractionDigits:1});
          const total      = closing + consumed;
          const fillPct    = total > 0 ? Math.min(100,(closing/total)*100) : isPct ? Math.min(100,closing) : 0;
          return `
            <div style="position:relative;overflow:hidden;padding:9px 12px;background:var(--panel);border:1px solid ${isCrit?'#fca5a5':isLow?'#fcd34d':'var(--border)'};border-radius:var(--radius-sm);display:flex;align-items:center;justify-content:space-between;gap:8px;">
              <div style="position:absolute;top:0;right:0;width:4px;height:100%;background:#e5e7eb;border-radius:0 var(--radius-sm) var(--radius-sm) 0;">
                <div style="position:absolute;bottom:0;left:0;width:100%;height:${fillPct.toFixed(1)}%;background:${statusColor};border-radius:0 0 var(--radius-sm) var(--radius-sm);transition:height 0.3s ease;"></div>
              </div>
              <span style="font-size:11px;font-weight:600;color:${isCrit?'#dc2626':isLow?'#d97706':'var(--text)'};overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1;min-width:0;" title="${_esc(item.consumable)}">${_esc(item.consumable)}</span>
              <div style="display:flex;align-items:center;gap:5px;flex-shrink:0;padding-right:8px;">
                ${consumed > 0 ? `<span style="font-family:'JetBrains Mono',monospace;font-size:10px;font-weight:600;color:#dc2626;">-${fmtQty(consumed)}</span><span style="color:var(--border);font-size:10px;">·</span>` : ''}
                <span style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:700;color:${isCrit?'#dc2626':isLow?'#d97706':'var(--text)'};">${fmtQty(closing)}</span>
              </div>
            </div>`;
        }).join('')}
      </div>`;
  }

  async function weeklyPrepare() {
    const btn = document.getElementById('weekly-prepare-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Preparing…'; }
    try {
      const res = await Auth.fetch('/api/v1/finance/weekly/prepare/', { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Could not prepare weekly report.', 'error');
        return;
      }
      const report  = await res.json();
      const content = document.getElementById('weekly-content');
      if (content) _renderWeeklyReportDetail(content, report);
      _toast('Weekly filing prepared.', 'success');
    } catch {
      _toast('Network error.', 'error');
    } finally {
      if (btn) { btn.disabled = false; btn.textContent = 'Prepare This Week'; }
    }
  }

  async function weeklySubmit(reportId) {
    const btn = document.getElementById('weekly-submit-btn');
    if (btn) { btn.disabled = true; btn.textContent = 'Submitting…'; }
    const notes = document.getElementById('weekly-notes')?.value.trim() || '';
    if (notes) {
      await Auth.fetch(`/api/v1/finance/weekly/${reportId}/notes/`, {
        method: 'PATCH', headers: {'Content-Type':'application/json'}, body: JSON.stringify({bm_notes:notes}),
      }).catch(() => {});
    }
    try {
      const res = await Auth.fetch(`/api/v1/finance/weekly/${reportId}/submit/`, { method: 'POST' });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        _toast(err.detail || 'Submission failed.', 'error');
        if (btn) { btn.disabled = false; btn.textContent = 'Submit & Lock Filing'; }
        return;
      }
      const report  = await res.json();
      const content = document.getElementById('weekly-content');
      if (content) _renderWeeklyReportDetail(content, report);
      _toast('Weekly filing submitted and locked.', 'success');
    } catch {
      _toast('Network error.', 'error');
      if (btn) { btn.disabled = false; btn.textContent = 'Submit & Lock Filing'; }
    }
  }

  async function weeklyDownloadPDF(reportId) {
    try {
      const res = await Auth.fetch(`/api/v1/finance/weekly/${reportId}/pdf/`);
      if (!res.ok) { _toast('Could not generate PDF.', 'error'); return; }
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement('a');
      a.href = url; a.download = `weekly_report_${reportId}.pdf`; a.click();
      URL.revokeObjectURL(url);
    } catch { _toast('Download failed.', 'error'); }
  }

  // ── Job Ledger (drill-down history) ────────────────────────
  function _renderHistoryReport(container) {
    _historyLevel = 'year';
    _historyYear  = null;
    _historyMonth = null;
    _historyWeek  = null;
    _fetchAndRenderHistory(container);
  }

  async function _fetchAndRenderHistory(container) {
    if (!container) container = document.getElementById('reports-content');
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';
    Object.values(_historyCharts).forEach(c => { try { c.destroy(); } catch {} });
    _historyCharts = {};

    const params = new URLSearchParams({ level: _historyLevel });
    if (_historyYear)         params.set('year',  _historyYear);
    if (_historyMonth)        params.set('month', _historyMonth);
    if (_historyWeek !== null) params.set('week',  _historyWeek);

    try {
      const res  = await Auth.fetch(`/api/v1/jobs/history/?${params}`);
      if (!res.ok) throw new Error();
      const data = await res.json();
      _renderHistoryData(container, data);
    } catch {
      container.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load history.</div>';
    }
  }

  function _renderHistoryData(container, data) {
    const kpis = data.kpis || {};

    const crumbs = [{ label: 'All Years', level: 'year', year: null, month: null, week: null }];
    if (_historyYear)  crumbs.push({ label: String(_historyYear), level: 'month', year: _historyYear, month: null, week: null });
    if (_historyMonth) {
      const mn = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][_historyMonth-1];
      crumbs.push({ label: mn, level: 'week', year: _historyYear, month: _historyMonth, week: null });
    }
    if (_historyWeek !== null) crumbs.push({ label: `Week ${_historyWeek}`, level: 'day', year: _historyYear, month: _historyMonth, week: _historyWeek });

    const breadcrumbHtml = crumbs.map((c, i) => {
      const isLast = i === crumbs.length - 1;
      return isLast
        ? `<span style="font-size:13px;font-weight:700;color:var(--text);">${c.label}</span>`
        : `<span onclick="Reports.historyNav('${c.level}',${c.year},${c.month},${c.week})"
             style="font-size:13px;color:var(--text-3);cursor:pointer;"
             onmouseover="this.style.color='var(--text)'" onmouseout="this.style.color='var(--text-3)'">${c.label}</span>
           <span style="color:var(--border-dark);margin:0 6px;">›</span>`;
    }).join('');

    let itemsHtml = '';
    if (data.level === 'year' || data.level === 'month') {
      const heading = data.level === 'year' ? 'Years' : 'Months';
      itemsHtml = `
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px;">${heading}</div>
        <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:10px;margin-bottom:24px;">
          ${(data.items||[]).map((item, i) => {
            const colors = ['#1a1a2e','#6b47d9','#1a3a2e','#2e1a1a','#1a2e3a','#3a2e1a'];
            const bg = colors[i % colors.length];
            return `
              <div onclick="Reports.historyDrill(this)" data-item="${JSON.stringify(item).replace(/"/g,'&quot;')}"
                style="border:1px solid var(--border);border-radius:8px;overflow:hidden;cursor:pointer;transition:all 0.15s;display:flex;height:64px;box-shadow:0 1px 4px rgba(0,0,0,0.05);"
                onmouseover="this.style.transform='translateY(-2px)';this.style.boxShadow='0 4px 12px rgba(0,0,0,0.1)'"
                onmouseout="this.style.transform='translateY(0)';this.style.boxShadow='0 1px 4px rgba(0,0,0,0.05)'">
                <div style="background:${bg};background-image:repeating-linear-gradient(45deg,rgba(255,255,255,0.04) 0px,rgba(255,255,255,0.04) 1px,transparent 1px,transparent 7px);width:80px;flex-shrink:0;display:flex;align-items:center;justify-content:center;">
                  <div style="font-family:'Outfit',sans-serif;font-size:18px;font-weight:800;color:#fff;letter-spacing:-0.01em;">${item.label}</div>
                </div>
                <div style="background:var(--panel);flex:1;padding:0 14px;display:flex;align-items:center;gap:20px;">
                  <div>
                    <div style="font-size:13px;font-weight:700;color:var(--text);">${item.total} jobs</div>
                    <div style="font-size:11px;color:var(--text-3);font-family:'JetBrains Mono',monospace;">${_fmt(item.revenue)}</div>
                  </div>
                  <div style="flex:1;">
                    <div style="height:3px;background:var(--border);border-radius:2px;">
                      <div style="height:100%;width:${item.rate}%;background:var(--green-text);border-radius:2px;"></div>
                    </div>
                    <div style="font-size:10px;color:var(--text-3);margin-top:3px;font-family:'JetBrains Mono',monospace;">${item.rate}% complete</div>
                  </div>
                </div>
              </div>`;
          }).join('')}
        </div>`;
    } else if (data.level === 'week') {
      itemsHtml = `
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px;">Weeks</div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:24px;">
          ${(data.items||[]).map(item => `
            <div onclick="Reports.historyDrill(this)" data-item="${JSON.stringify(item).replace(/"/g,'&quot;')}"
              style="display:flex;align-items:center;justify-content:space-between;padding:14px 20px;border-bottom:1px solid var(--border);cursor:pointer;transition:background 0.12s;"
              onmouseover="this.style.background='var(--bg)'" onmouseout="this.style.background=''">
              <div>
                <div style="font-size:14px;font-weight:700;color:var(--text);">${item.label}</div>
                <div style="font-size:11px;color:var(--text-3);margin-top:2px;font-family:'JetBrains Mono',monospace;">${item.start} → ${item.end}</div>
              </div>
              <div style="display:flex;align-items:center;gap:24px;">
                <div style="text-align:right;">
                  <div style="font-size:13px;font-weight:600;color:var(--text);">${item.total} jobs</div>
                  <div style="font-size:12px;color:var(--text-3);">${_fmt(item.revenue)}</div>
                </div>
                <div style="font-size:12px;color:var(--green-text);font-weight:600;min-width:40px;text-align:right;">${item.rate}%</div>
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="color:var(--text-3);"><polyline points="9 18 15 12 9 6"/></svg>
              </div>
            </div>`).join('')}
        </div>`;
    } else if (data.level === 'day') {
      itemsHtml = `
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:12px;">Days</div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;margin-bottom:24px;">
          <table class="p-table">
            <thead><tr><th>Day</th><th>Jobs</th><th>Complete</th><th>Pending</th><th>Revenue</th><th>Sheet</th><th></th></tr></thead>
            <tbody>
              ${(data.items||[]).map(item => `
                <tr>
                  <td style="font-weight:600;color:var(--text);">${item.label}</td>
                  <td>${item.total}</td>
                  <td style="color:var(--green-text);font-weight:600;">${item.complete}</td>
                  <td style="color:var(--amber-text);">${item.pending}</td>
                  <td style="font-family:'JetBrains Mono',monospace;font-size:12px;">${_fmt(item.revenue)}</td>
                  <td>${item.sheet_status ? `<span class="badge badge-${item.sheet_status==='OPEN'?'progress':'done'}">${item.sheet_status}</span>` : '<span style="color:var(--text-3);font-size:12px;">No sheet</span>'}</td>
                  <td>${item.sheet_id && item.sheet_status !== 'OPEN' ? `<button onclick="Dashboard.downloadSheetPDF(${item.sheet_id},'${item.date}')" style="font-size:12px;color:var(--text-2);background:none;border:none;cursor:pointer;font-weight:600;padding:0;">PDF ↓</button>` : '—'}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>`;
    }

    const kpiCards = [
      { key:'total',   label:'Total Jobs', value: kpis.total?.value||0,   fmt: v=>v,         border:'#3355cc', text:'#3355cc' },
      { key:'revenue', label:'Revenue',    value: kpis.revenue?.value||0, fmt: v=>_fmt(v),   border:'#22c98a', text:'#22c98a' },
      { key:'pending', label:'Pending',    value: kpis.pending?.value||0, fmt: v=>v,         border:'#e8a820', text:'#e8a820' },
      { key:'rate',    label:'Completion', value: kpis.rate?.value||0,    fmt: v=>v + '%',   border:'#9b59b6', text:'#9b59b6' },
    ];

    const kpiHtml = `
      <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:20px;">
        ${kpiCards.map(k => {
          const change = kpis[k.key]?.change;
          const isPos  = change?.startsWith('+');
          const isNeg  = change?.startsWith('-');
          return `
            <div style="background:var(--panel);border:1px solid var(--border);border-top:3px solid ${k.border};border-radius:8px;padding:10px 12px;">
              <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:4px;">${k.label}</div>
              <div style="font-size:17px;font-weight:800;color:${k.text};font-family:'Outfit',sans-serif;letter-spacing:-0.01em;margin-bottom:3px;">${k.fmt(k.value)}</div>
              ${change ? `<div style="font-size:9px;font-weight:700;font-family:'JetBrains Mono',monospace;color:${isPos?'#22c98a':isNeg?'#e8294a':'var(--text-3)'};">${isPos?'↑':isNeg?'↓':''} ${change} vs prev</div>` : `<div style="font-size:9px;color:var(--text-3);">no prev data</div>`}
            </div>`;
        }).join('')}
      </div>`;

    const chartsHtml = `
      <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:20px;margin-bottom:16px;">
        <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:16px;">Trend</div>
        <canvas id="history-trend-chart" height="70"></canvas>
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px;">
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:20px;">
          <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:16px;">Distribution</div>
          <canvas id="history-bar-chart" height="140"></canvas>
        </div>
        <div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);padding:20px;">
          <div style="font-size:11px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:16px;">Activity Heatmap</div>
          <div id="history-heatmap"></div>
        </div>
      </div>`;

    container.innerHTML = `
      <div style="display:flex;align-items:center;gap:4px;margin-bottom:20px;flex-wrap:wrap;">${breadcrumbHtml}</div>
      ${itemsHtml}
      ${kpiHtml}
      ${chartsHtml}`;

    _drawHistoryCharts(data);
  }

  function _drawHistoryCharts(data) {
    if (typeof Chart === 'undefined') {
      const script  = document.createElement('script');
      script.src    = 'https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js';
      script.onload = () => _drawHistoryCharts(data);
      document.head.appendChild(script);
      return;
    }
    const textColor   = getComputedStyle(document.documentElement).getPropertyValue('--text-3').trim() || '#999';
    const borderColor = getComputedStyle(document.documentElement).getPropertyValue('--border').trim()  || '#eee';

    const trendCtx = document.getElementById('history-trend-chart');
    if (trendCtx && data.trend) {
      _historyCharts.trend = new Chart(trendCtx, {
        type: 'line',
        data: { labels: data.trend.labels, datasets: [
          { label:'Jobs',         data:data.trend.jobs,    borderColor:'#3355cc', backgroundColor:'rgba(51,85,204,0.08)', tension:0.4, fill:true, yAxisID:'y'  },
          { label:'Revenue (GHS)',data:data.trend.revenue, borderColor:'#22c98a', backgroundColor:'rgba(34,201,138,0.08)',tension:0.4, fill:true, yAxisID:'y1' },
        ]},
        options: { responsive:true, interaction:{mode:'index',intersect:false}, plugins:{legend:{labels:{color:textColor,font:{size:11}}}},
          scales:{x:{ticks:{color:textColor,font:{size:10}},grid:{color:borderColor}},y:{ticks:{color:textColor,font:{size:10}},grid:{color:borderColor},position:'left'},y1:{ticks:{color:textColor,font:{size:10}},grid:{display:false},position:'right'}} },
      });
    }
    const barCtx = document.getElementById('history-bar-chart');
    if (barCtx && data.bar) {
      _historyCharts.bar = new Chart(barCtx, {
        type:'bar',
        data:{ labels:data.bar.labels, datasets:[{label:'Jobs',data:data.bar.data,backgroundColor:'rgba(51,85,204,0.7)',borderRadius:4}] },
        options:{ responsive:true, plugins:{legend:{display:false}}, scales:{x:{ticks:{color:textColor,font:{size:10}},grid:{display:false}},y:{ticks:{color:textColor,font:{size:10}},grid:{color:borderColor}}} },
      });
    }
    _drawHeatmap(data);
  }

  function _drawHeatmap(data) {
    const el = document.getElementById('history-heatmap');
    if (!el || !data.heatmap) return;
    let items = [];
    if (data.level === 'day') {
      data.heatmap.forEach(day => day.hours.forEach(h => items.push(h.count)));
    } else {
      items = data.heatmap.map(w => (typeof w === 'object' && w.count !== undefined) ? w.count : 0);
    }
    const max      = Math.max(...items, 1);
    const cellSize = 14;

    if (data.level === 'day') {
      const days  = data.heatmap;
      const hours = Array.from({length:12}, (_,i) => i + 8);
      el.innerHTML = `
        <div style="overflow-x:auto;">
          <table style="border-collapse:separate;border-spacing:2px;font-size:9px;color:var(--text-3);">
            <thead><tr><td></td>${days.map(d=>`<td style="text-align:center;padding-bottom:4px;">${new Date(d.date).toLocaleDateString('en-GB',{weekday:'short'})}</td>`).join('')}</tr></thead>
            <tbody>${hours.map(h=>`<tr><td style="padding-right:6px;text-align:right;">${h}h</td>${days.map(d=>{const hdata=d.hours.find(x=>x.hour===h);const count=hdata?.count||0;const alpha=count?0.15+(count/max)*0.85:0.05;return`<td title="${count} jobs" style="width:${cellSize}px;height:${cellSize}px;border-radius:2px;background:rgba(51,85,204,${alpha.toFixed(2)});cursor:default;"></td>`;}).join('')}</tr>`).join('')}</tbody>
          </table>
        </div>`;
    } else {
      const weeks = data.heatmap;
      let html = '<div style="display:flex;flex-wrap:wrap;gap:2px;">';
      weeks.forEach(w => {
        const count = Array.isArray(w) ? w.reduce((s,d)=>s+d.count,0) : (w.count||0);
        const alpha = count ? 0.15+(count/max)*0.85 : 0.05;
        html += `<div title="${count} jobs" style="width:${cellSize}px;height:${cellSize}px;border-radius:2px;background:rgba(51,85,204,${alpha.toFixed(2)});"></div>`;
      });
      html += '</div>';
      el.innerHTML = html;
    }
  }

  function historyDrill(elOrItem) {
    let item = elOrItem;
    if (elOrItem instanceof HTMLElement) {
      try { item = JSON.parse(elOrItem.dataset.item.replace(/&quot;/g,'"')); } catch { return; }
    } else if (typeof elOrItem === 'string') {
      try { item = JSON.parse(elOrItem.replace(/&quot;/g,'"')); } catch { return; }
    }
    _historyYear  = item.year  || _historyYear;
    _historyMonth = item.month || null;
    _historyWeek  = item.week  !== undefined ? item.week : null;
    if (_historyMonth && _historyWeek !== null) _historyLevel = 'day';
    else if (_historyMonth)                     _historyLevel = 'week';
    else if (_historyYear)                      _historyLevel = 'month';
    const container = document.getElementById('reports-content');
    _fetchAndRenderHistory(container);
  }

  function historyNav(level, year, month, week) {
    _historyLevel = level;
    _historyYear  = year;
    _historyMonth = month;
    _historyWeek  = week;
    const container = document.getElementById('reports-content');
    _fetchAndRenderHistory(container);
  }

  // ── Public API ─────────────────────────────────────────────
  return {
    loadReportsPane,
    switchReportsTab,
    setReportsPeriod,
    setServicesPeriod,
    submitMonthlyClose,
    downloadMonthlyPDF,
    weeklyPrepare,
    weeklySubmit,
    weeklyDownloadPDF,
    toggleDailySheet,
    loadDailySheetInventory,
    toggleHistoryWeek,
    historyDrill,
    historyNav,
    // Exposed for dashboard.js performance pane
    renderServicesReport: _renderServicesReport,
    renderWeeklyReportDetail: _renderWeeklyReportDetail,
    renderWeeklyInventory: _renderWeeklyInventory,
    renderMonthlyClose: _renderMonthlyClose,
    renderMonthlyCloseDetail: _renderMonthlyCloseDetail,
  };

})();