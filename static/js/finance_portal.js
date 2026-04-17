'use strict';

const FinancePortal = (() => {

  let _clarifyCloseId  = null;
  let _clearCloseId    = null;
  let _procActiveId    = null;  // active procurement order id

  // ── Boot ──────────────────────────────────────────────────
  async function init() {
    await Auth.guard(['FINANCE', 'SUPER_ADMIN']);
    await _loadContext();
    await _loadBranches();
    await _loadProcurementBadge();
  }

  async function _loadContext() {
    try {
      const res = await Auth.fetch('/api/v1/accounts/me/');
      if (!res.ok) return;
      const user = await res.json();
      const name = user.full_name || user.email || '—';
      const ini  = name.split(' ').slice(0,2).map(w => w[0]?.toUpperCase() || '').join('');
      _set('fin-user-name', name);
      _set('fin-avatar',    ini);
    } catch { /* silent */ }
  }

  // ── Pane switching ────────────────────────────────────────
  function switchPane(pane) {
    document.querySelectorAll('.sidebar-item').forEach(el => {
      el.classList.toggle('active', el.dataset.pane === pane);
    });
    document.querySelectorAll('.pane').forEach(el => {
      el.classList.toggle('active', el.id === `pane-${pane}`);
    });

    if (pane === 'queue')       _loadBranches();
    if (pane === 'history')     _loadHistory();
    if (pane === 'procurement') _loadProcurement();
  }

  // ── Queue ─────────────────────────────────────────────────
  async function _loadBranches() {
    const container = document.getElementById('queue-content');
    if (!container) return;
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    try {
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/my-branches/');
      if (!res.ok) throw new Error();
      const data = await res.json();

      const activeCount = data.filter(b => b.active).length;
      const badge = document.getElementById('queue-badge');
      if (badge) {
        badge.textContent   = activeCount;
        badge.style.display = activeCount ? 'flex' : 'none';
      }

      if (!data.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <svg xmlns="http://www.w3.org/2000/svg" width="40" height="40"
              viewBox="0 0 24 24" fill="none" stroke="currentColor"
              stroke-width="1" style="opacity:0.3;margin-bottom:16px;
              display:block;margin:0 auto 16px;">
              <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/>
              <polyline points="22 4 12 14.01 9 11.01"/>
            </svg>
            <div style="font-size:14px;font-weight:600;color:var(--text);
              margin-bottom:4px;">No branches assigned</div>
            <div style="font-size:13px;">No monthly closes have been assigned to you yet.</div>
          </div>`;
        return;
      }

      container.innerHTML = data.map(b => _renderBranchCard(b)).join('');

    } catch {
      container.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">
        Could not load your queue.</div>`;
    }
  }

  function _renderBranchCard(b) {
    const activeHtml  = b.active  ? _renderActiveClose(b.active, b.branch, b.branch_code)  : `
      <div style="padding:20px 24px;background:var(--bg);border-radius:var(--radius-sm);
        font-size:13px;color:var(--text-3);text-align:center;">
        No active review — all closes cleared ✓
      </div>`;

    const historyHtml = b.history?.length ? _renderBranchHistory(b.history) : '';

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
          ${b.active ? `
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;
              font-weight:700;background:rgba(255,255,255,0.15);color:#fff;">
              ${b.active.status === 'RESUBMITTED' ? '⚠ Resubmitted' : '● Active Review'}
            </span>` : `
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;
              font-weight:700;background:rgba(255,255,255,0.15);color:#fff;">
              ✓ Clear
            </span>`}
        </div>
        <div style="padding:20px;">
          ${activeHtml}
        </div>
        ${historyHtml}
      </div>`;
  }

  function _renderBranchHistory(history) {
    const monthNames = ['January','February','March','April','May','June',
      'July','August','September','October','November','December'];

    const rows = history.map(h => {
      const monthName  = monthNames[(h.month || 1) - 1];
      const clearedAt  = h.finance_cleared_at
        ? new Date(h.finance_cleared_at).toLocaleDateString('en-GB',
            {day:'numeric', month:'short', year:'numeric'})
        : '—';
      const statusBg = h.status === 'LOCKED' ? 'var(--bg)' : 'var(--green-bg)';
      const statusColor = h.status === 'LOCKED' ? 'var(--text-3)' : 'var(--green-text)';

      return `
        <div style="display:flex;align-items:center;justify-content:space-between;
          padding:10px 20px;border-top:1px solid var(--border);">
          <div>
            <span style="font-size:13px;font-weight:600;color:var(--text);">
              ${monthName} ${h.year}
            </span>
            <span style="font-size:11px;color:var(--text-3);margin-left:8px;">
              Cleared ${clearedAt}
            </span>
          </div>
          <div style="display:flex;align-items:center;gap:12px;">
            <span style="font-family:'JetBrains Mono',monospace;font-size:12px;color:var(--text-2);">
              GHS ${parseFloat(h.total_collected||0).toLocaleString('en-GH',{minimumFractionDigits:2})}
            </span>
            <span style="padding:2px 8px;border-radius:20px;font-size:10px;
              font-weight:700;background:${statusBg};color:${statusColor};">
              ${h.status}
            </span>
          </div>
        </div>`;
    }).join('');

    return `
      <div style="border-top:2px solid var(--border);">
        <div style="padding:8px 20px;background:var(--bg);">
          <span style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.6px;">Previous Reviews</span>
        </div>
        ${rows}
      </div>`;
  }

  function _renderActiveClose(c, branchName, branchCode) {
    const monthNames = ['January','February','March','April','May','June',
      'July','August','September','October','November','December'];
    const monthName   = monthNames[(c.month || 1) - 1];
    const submittedAt = c.submitted_at
      ? new Date(c.submitted_at).toLocaleDateString('en-GB',
          {day:'numeric', month:'short', year:'numeric',
           hour:'2-digit', minute:'2-digit'})
      : '—';

    const isResubmitted = c.status === 'RESUBMITTED';
    const fmt = n => `GHS ${parseFloat(n||0).toLocaleString('en-GH',{minimumFractionDigits:2})}`;
    const pct = n => `${parseFloat(n||0).toFixed(1)}%`;

    const weeklyRows = (c.weekly_breakdown || []).map(w => `
      <tr>
        <td style="padding:8px 12px;border-bottom:1px solid var(--border);
          font-size:12px;color:var(--text-3);">
          W${w.week_number}
          <span style="font-size:11px;margin-left:4px;">${w.date_from} – ${w.date_to}</span>
        </td>
        <td style="padding:8px 12px;border-bottom:1px solid var(--border);
          text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;">
          ${fmt(w.cash)}</td>
        <td style="padding:8px 12px;border-bottom:1px solid var(--border);
          text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;">
          ${fmt(w.momo)}</td>
        <td style="padding:8px 12px;border-bottom:1px solid var(--border);
          text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;
          font-weight:700;color:var(--text);">${fmt(w.total)}</td>
        <td style="padding:8px 12px;border-bottom:1px solid var(--border);
          text-align:right;font-size:12px;color:var(--text-3);">${w.jobs}</td>
        <td style="padding:8px 12px;border-bottom:1px solid var(--border);text-align:right;">
          <span style="padding:2px 8px;border-radius:20px;font-size:10px;
            font-weight:700;background:var(--green-bg);color:var(--green-text);">
            ${w.status}
          </span>
        </td>
      </tr>`).join('');

    const serviceRows = (c.top_services || []).map((s, i) => `
      <div style="display:flex;align-items:center;justify-content:space-between;
        padding:8px 0;${i < (c.top_services.length-1) ? 'border-bottom:1px solid var(--border);' : ''}">
        <div style="font-size:12px;color:var(--text-2);flex:1;">${_esc(s.service)}</div>
        <div style="font-size:11px;color:var(--text-3);margin:0 12px;">${s.job_count} jobs</div>
        <div style="font-family:'JetBrains Mono',monospace;font-size:12px;
          font-weight:700;color:var(--text);">${fmt(s.revenue)}</div>
      </div>`).join('');

    const clarifyThread = isResubmitted && (c.clarification_request || c.clarification_response) ? `
      <div style="margin-bottom:16px;">
        <div style="font-size:10px;font-weight:700;color:var(--amber-text);
          text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">
          ⚠ Clarification Thread
        </div>
        ${c.clarification_request ? `
          <div style="background:var(--amber-bg);border:1px solid var(--border);
            border-radius:var(--radius-sm);padding:10px 14px;margin-bottom:6px;">
            <div style="font-size:10px;font-weight:700;color:var(--amber-text);margin-bottom:4px;">
              Your Request</div>
            <div style="font-size:13px;color:var(--text-2);">${_esc(c.clarification_request)}</div>
          </div>` : ''}
        ${c.clarification_response ? `
          <div style="background:var(--bg);border:1px solid var(--border);
            border-radius:var(--radius-sm);padding:10px 14px;">
            <div style="font-size:10px;font-weight:700;color:var(--text-3);margin-bottom:4px;">
              BM Response</div>
            <div style="font-size:13px;color:var(--text-2);">${_esc(c.clarification_response)}</div>
          </div>` : ''}
      </div>` : '';

    return `
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
        <div>
          <div style="font-size:15px;font-weight:700;color:var(--text);">
            ${monthName} ${c.year} Monthly Close
          </div>
          <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
            Submitted by ${_esc(c.submitted_by)} · ${submittedAt}
          </div>
        </div>
        <span style="padding:3px 10px;border-radius:20px;font-size:11px;font-weight:700;
          background:${isResubmitted ? 'var(--amber-bg)' : '#dbeafe'};
          color:${isResubmitted ? 'var(--amber-text)' : '#1e40af'};">
          ${isResubmitted ? 'Resubmitted' : 'Reviewing'}
        </span>
      </div>
      ${clarifyThread}
      <div style="margin-bottom:20px;">
        <div style="font-size:10px;font-weight:700;color:var(--text-3);
          text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;">Revenue Summary</div>
        <div style="background:var(--bg);border:1px solid var(--border);
          border-radius:var(--radius-sm);padding:14px 16px;margin-bottom:10px;
          display:flex;align-items:center;justify-content:space-between;">
          <div style="font-size:12px;color:var(--text-3);">Total Collected</div>
          <div style="font-family:'JetBrains Mono',monospace;font-size:22px;
            font-weight:700;color:var(--text);">${fmt(c.total_collected)}</div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px;margin-bottom:8px;">
          <div style="padding:10px 12px;background:var(--cash-bg);border:1px solid var(--cash-border);border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:var(--cash-text);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">Cash</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:var(--cash-strong);">${fmt(c.total_cash)}</div>
            <div style="font-size:10px;color:var(--cash-text);margin-top:2px;">${pct(c.cash_pct)} of total</div>
          </div>
          <div style="padding:10px 12px;background:var(--momo-bg);border:1px solid var(--momo-border);border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:var(--momo-text);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">MoMo</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:var(--momo-strong);">${fmt(c.total_momo)}</div>
            <div style="font-size:10px;color:var(--momo-text);margin-top:2px;">${pct(c.momo_pct)} of total</div>
          </div>
          <div style="padding:10px 12px;background:var(--pos-bg);border:1px solid var(--pos-border);border-radius:var(--radius-sm);">
            <div style="font-size:10px;font-weight:700;color:var(--pos-text);text-transform:uppercase;letter-spacing:0.5px;margin-bottom:3px;">POS</div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:13px;font-weight:700;color:var(--pos-strong);">${fmt(c.total_pos)}</div>
            <div style="font-size:10px;color:var(--pos-text);margin-top:2px;">${pct(c.pos_pct)} of total</div>
          </div>
        </div>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
          <div style="padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);display:flex;justify-content:space-between;">
            <span style="font-size:11px;color:var(--text-3);">Petty Cash Out</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;color:var(--text);">${fmt(c.total_petty_cash_out)}</span>
          </div>
          <div style="padding:8px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);display:flex;justify-content:space-between;">
            <span style="font-size:11px;color:var(--text-3);">Credit Settled</span>
            <span style="font-family:'JetBrains Mono',monospace;font-size:12px;font-weight:600;color:var(--text);">${fmt(c.total_credit_settled)}</span>
          </div>
        </div>
      </div>
      <div style="margin-bottom:20px;">
        <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;">Jobs Summary</div>
        <div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;">
          <div style="padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:20px;font-weight:800;color:var(--text);">${c.total_jobs}</div>
            <div style="font-size:10px;color:var(--text-3);margin-top:2px;">Total</div>
          </div>
          <div style="padding:10px 12px;background:var(--green-bg);border:1px solid var(--green-border);border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:20px;font-weight:800;color:var(--green-text);">${c.jobs_complete}</div>
            <div style="font-size:10px;color:var(--green-text);margin-top:2px;">Complete</div>
          </div>
          <div style="padding:10px 12px;background:var(--red-bg);border:1px solid var(--red-border);border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:20px;font-weight:800;color:var(--red-text);">${c.jobs_cancelled}</div>
            <div style="font-size:10px;color:var(--red-text);margin-top:2px;">Cancelled</div>
          </div>
          <div style="padding:10px 12px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);text-align:center;">
            <div style="font-size:20px;font-weight:800;color:var(--text);">${c.completion_rate}%</div>
            <div style="font-size:10px;color:var(--text-3);margin-top:2px;">Rate</div>
          </div>
        </div>
      </div>
      ${serviceRows ? `
        <div style="margin-bottom:20px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;">Top Services</div>
          <div style="background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:4px 14px;">${serviceRows}</div>
        </div>` : ''}
      ${weeklyRows ? `
        <div style="margin-bottom:20px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:10px;">Weekly Breakdown</div>
          <div style="background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);overflow:hidden;">
            <table style="width:100%;border-collapse:collapse;">
              <thead>
                <tr style="background:var(--panel);">
                  <th style="padding:8px 12px;text-align:left;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;border-bottom:1px solid var(--border);">Week</th>
                  <th style="padding:8px 12px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;border-bottom:1px solid var(--border);">Cash</th>
                  <th style="padding:8px 12px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;border-bottom:1px solid var(--border);">MoMo</th>
                  <th style="padding:8px 12px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;border-bottom:1px solid var(--border);">Total</th>
                  <th style="padding:8px 12px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;border-bottom:1px solid var(--border);">Jobs</th>
                  <th style="padding:8px 12px;text-align:right;font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;border-bottom:1px solid var(--border);">Status</th>
                </tr>
              </thead>
              <tbody>${weeklyRows}</tbody>
            </table>
          </div>
        </div>` : ''}
      ${c.bm_notes ? `
        <div style="margin-bottom:16px;">
          <div style="font-size:10px;font-weight:700;color:var(--text-3);text-transform:uppercase;letter-spacing:0.6px;margin-bottom:8px;">Branch Manager Notes</div>
          <div style="background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);padding:12px 14px;font-size:13px;color:var(--text-2);">${_esc(c.bm_notes)}</div>
        </div>` : ''}
      <div style="border-top:1px solid var(--border);padding-top:14px;margin-top:4px;">
        <textarea id="fin-notes-${c.id}" rows="2"
          placeholder="Finance notes (optional — saved on clear)…"
          style="width:100%;padding:8px 12px;border:1px solid var(--border);
            border-radius:var(--radius-sm);background:var(--bg);color:var(--text);
            font-size:12px;resize:none;box-sizing:border-box;margin-bottom:10px;
            font-family:'DM Sans',sans-serif;"></textarea>
        <div style="display:flex;gap:8px;justify-content:flex-end;">
          <button class="btn-clarify" onclick="FinancePortal.openClarifyModal(${c.id})">
            Request Clarification
          </button>
          <button class="btn-clear" onclick="FinancePortal.openClearModal(${c.id})">
            ✓ Clear
          </button>
        </div>
      </div>`;
  }

  // ── Clarification modal ───────────────────────────────────
  function openClarifyModal(id) {
    _clarifyCloseId = id;
    document.getElementById('clarify-text').value          = '';
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

    if (!text) {
      errorEl.textContent   = 'Clarification request cannot be empty.';
      errorEl.style.display = 'block';
      return;
    }

    try {
      const res = await Auth.fetch(
        `/api/v1/finance/monthly-close/${_clarifyCloseId}/request-clarification/`, {
          method : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body   : JSON.stringify({ clarification: text }),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent   = err.detail || 'Request failed.';
        errorEl.style.display = 'block';
        return;
      }
      closeClarifyModal();
      _toast('Clarification requested. Branch Manager has 24 hours to respond.', 'success');
      await _loadBranches();
    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    }
  }

  // ── Clear modal ───────────────────────────────────────────
  function openClearModal(id) {
    _clearCloseId = id;
    const inlineNotes = document.getElementById(`fin-notes-${id}`)?.value.trim() || '';
    document.getElementById('clear-notes').value          = inlineNotes;
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
          method : 'POST',
          headers: { 'Content-Type': 'application/json' },
          body   : JSON.stringify({ finance_notes: notes }),
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        errorEl.textContent   = err.detail || 'Clear failed.';
        errorEl.style.display = 'block';
        return;
      }
      closeClearModal();
      _toast('Monthly close cleared. Regional Manager notified.', 'success');
      await _loadBranches();
    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    }
  }

  // ── History ───────────────────────────────────────────────
  async function _loadHistory() {
    const container = document.getElementById('history-content');
    if (!container) return;
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    try {
      const res  = await Auth.fetch('/api/v1/finance/monthly-close/my-history/');
      if (!res.ok) throw new Error();
      const data = await res.json();

      if (!data.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:48px;color:var(--text-3);font-size:13px;">
            No cleared monthly closes yet.
          </div>`;
        return;
      }

      const monthNames = ['January','February','March','April','May','June',
        'July','August','September','October','November','December'];

      container.innerHTML = data.map(c => {
        const monthName = monthNames[(c.month || 1) - 1];
        const clearedAt = c.finance_cleared_at
          ? new Date(c.finance_cleared_at).toLocaleDateString('en-GB',
              {day:'numeric', month:'short', year:'numeric'})
          : '—';
        return `
          <div class="history-item">
            <div>
              <div style="font-size:14px;font-weight:700;color:var(--text);">
                ${_esc(c.branch)} — ${monthName} ${c.year}
              </div>
              <div style="font-size:11px;color:var(--text-3);margin-top:2px;">
                Cleared ${clearedAt}
              </div>
            </div>
            <span style="padding:4px 12px;border-radius:20px;font-size:11px;
              font-weight:700;background:var(--green-bg);color:var(--green-text);">
              ${c.status === 'ENDORSED' || c.status === 'LOCKED' ? 'Endorsed' : 'Cleared'}
            </span>
          </div>`;
      }).join('');

    } catch {
      container.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">
        Could not load history.</div>`;
    }
  }

  // ══════════════════════════════════════════════════════════
  // PROCUREMENT APPROVALS
  // ══════════════════════════════════════════════════════════

  async function _loadProcurementBadge() {
    try {
      const res  = await Auth.fetch('/api/v1/procurement/orders/');
      if (!res.ok) return;
      const data   = await res.json();
      const count  = data.filter(o => o.status === 'PENDING_FINANCE').length;
      const badge  = document.getElementById('procurement-badge');
      if (badge) {
        badge.textContent   = count;
        badge.style.display = count > 0 ? 'flex' : 'none';
      }
    } catch { /* silent */ }
  }

  async function _loadProcurement() {
    const container = document.getElementById('procurement-content');
    if (!container) return;
    container.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading…</div>';

    try {
      const res  = await Auth.fetch('/api/v1/procurement/orders/');
      if (!res.ok) throw new Error();
      const data    = await res.json();
      const pending = data.filter(o => o.status === 'PENDING_FINANCE');
      const approved = data.filter(o =>
        ['FINANCE_APPROVED','IN_TRANSIT','DELIVERED','CLOSED'].includes(o.status)
      );

      // Update pill and badge
      const pill = document.getElementById('procurement-count-pill');
      if (pill) pill.textContent = `${pending.length} pending`;
      const badge = document.getElementById('procurement-badge');
      if (badge) {
        badge.textContent   = pending.length;
        badge.style.display = pending.length > 0 ? 'flex' : 'none';
      }

      if (!pending.length && !approved.length) {
        container.innerHTML = `
          <div style="text-align:center;padding:60px;color:var(--text-3);">
            <div style="font-size:36px;margin-bottom:12px;">✅</div>
            <div style="font-size:14px;font-weight:600;color:var(--text);margin-bottom:4px;">
              All clear</div>
            <div style="font-size:13px;">No replenishment orders require your attention.</div>
          </div>`;
        return;
      }

      let html = '';

      if (pending.length) {
        html += `
          <div style="font-size:10px;font-weight:700;color:var(--amber-text);
            text-transform:uppercase;letter-spacing:0.6px;margin-bottom:12px;">
            ● Awaiting Your Approval (${pending.length})
          </div>`;
        html += pending.map(o => _renderProcurementCard(o, true)).join('');
      }

      if (approved.length) {
        html += `
          <div style="font-size:10px;font-weight:700;color:var(--text-3);
            text-transform:uppercase;letter-spacing:0.6px;
            margin-top:${pending.length ? 28 : 0}px;margin-bottom:12px;">
            Approved Orders
          </div>`;
        html += approved.map(o => _renderProcurementCard(o, false)).join('');
      }

      container.innerHTML = html;

    } catch {
      container.innerHTML = `<div class="loading-cell" style="color:var(--red-text);">
        Could not load procurement orders.</div>`;
    }
  }

  function _renderProcurementCard(o, isPending) {
    const statusColors = {
      PENDING_FINANCE:  { bg: 'var(--amber-bg)',  text: 'var(--amber-text)' },
      FINANCE_APPROVED: { bg: '#dbeafe',           text: '#1e40af' },
      IN_TRANSIT:       { bg: 'var(--purple-bg, #faf0ff)', text: 'var(--purple-text, #6b21a8)' },
      DELIVERED:        { bg: 'var(--amber-bg)',   text: 'var(--amber-text)' },
      CLOSED:           { bg: 'var(--green-bg)',   text: 'var(--green-text)' },
    };
    const sc = statusColors[o.status] || { bg: 'var(--bg)', text: 'var(--text-3)' };
    const statusLabel = {
      PENDING_FINANCE: 'Pending Approval', FINANCE_APPROVED: 'Approved',
      IN_TRANSIT: 'In Transit', DELIVERED: 'Delivered', CLOSED: 'Closed',
    }[o.status] || o.status;

    const budget = o.approved_budget
      ? `GHS ${parseFloat(o.approved_budget).toFixed(2)}`
      : `Est. GHS ${parseFloat(o.estimated_total).toFixed(2)}`;

    return `
      <div style="border:1px solid ${isPending ? 'var(--amber-border, #fde68a)' : 'var(--border)'};
        border-radius:var(--radius);padding:18px 20px;margin-bottom:12px;
        background:${isPending ? 'var(--amber-bg, #fffbeb)' : 'var(--panel)'};">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;
          margin-bottom:10px;">
          <div>
            <div style="font-family:'JetBrains Mono',monospace;font-size:14px;
              font-weight:700;color:var(--text);margin-bottom:4px;">${_esc(o.order_number)}</div>
            <div style="font-size:12px;color:var(--text-3);display:flex;gap:12px;flex-wrap:wrap;">
              <span>🏢 ${_esc(o.branch_name)}</span>
              <span>📅 Week ${o.week_number}, ${o.year}</span>
              <span>📦 ${o.line_item_count || '—'} items</span>
              ${o.submitted_to_finance_at ? `<span>⏱ ${_fmtDate(o.submitted_to_finance_at)}</span>` : ''}
            </div>
          </div>
          <div style="text-align:right;flex-shrink:0;margin-left:16px;">
            <span style="padding:3px 10px;border-radius:20px;font-size:11px;
              font-weight:700;background:${sc.bg};color:${sc.text};">
              ${statusLabel}
            </span>
            <div style="font-family:'JetBrains Mono',monospace;font-size:16px;
              font-weight:700;color:var(--text);margin-top:6px;">${budget}</div>
          </div>
        </div>
        ${isPending ? `
          <div style="display:flex;justify-content:flex-end;padding-top:10px;
            border-top:1px solid var(--amber-border, #fde68a);">
            <button onclick="FinancePortal.openProcApproveModal(${o.id})"
              style="padding:8px 20px;background:var(--text);color:#fff;border:none;
                border-radius:var(--radius-sm);font-size:13px;font-weight:700;
                cursor:pointer;font-family:inherit;">
              Review &amp; Approve
            </button>
          </div>` : ''}
      </div>`;
  }

  // ── Procurement approve modal ─────────────────────────────
  async function openProcApproveModal(orderId) {
    _procActiveId = orderId;

    try {
      const res   = await Auth.fetch(`/api/v1/procurement/orders/${orderId}/`);
      const order = await res.json();

      _set('proc-approve-number',   order.order_number);
      _set('proc-approve-branch',   `${order.branch_name} · Week ${order.week_number}, ${order.year}`);
      _set('proc-approve-estimated', `GHS ${parseFloat(order.estimated_total).toFixed(2)}`);

      const tbody = document.getElementById('proc-approve-tbody');
      let total   = 0;
      tbody.innerHTML = order.line_items.map(li => {
        const lineTotal = parseFloat(li.line_total || 0);
        total          += lineTotal;
        return `
          <tr>
            <td style="padding:9px 14px;border-bottom:1px solid var(--border);
              font-size:13px;font-weight:600;">${_esc(li.consumable_name)}</td>
            <td style="padding:9px 14px;border-bottom:1px solid var(--border);
              text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;">
              ${parseFloat(li.requested_qty).toFixed(2)} ${li.unit_label}</td>
            <td style="padding:9px 14px;border-bottom:1px solid var(--border);
              text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;">
              ${li.unit_cost > 0 ? `GHS ${parseFloat(li.unit_cost).toFixed(2)}` : '—'}</td>
            <td style="padding:9px 14px;border-bottom:1px solid var(--border);
              text-align:right;font-family:'JetBrains Mono',monospace;font-size:12px;
              font-weight:700;">
              ${lineTotal > 0 ? `GHS ${lineTotal.toFixed(2)}` : '—'}</td>
          </tr>`;
      }).join('');

      // Totals row
      tbody.innerHTML += `
        <tr style="background:var(--bg);">
          <td colspan="3" style="padding:10px 14px;font-weight:700;
            text-align:right;font-size:13px;">Total</td>
          <td style="padding:10px 14px;text-align:right;
            font-family:'JetBrains Mono',monospace;font-weight:700;font-size:14px;">
            GHS ${total.toFixed(2)}</td>
        </tr>`;

      // Pre-fill budget
      document.getElementById('proc-budget-input').value  = parseFloat(order.estimated_total).toFixed(2);
      document.getElementById('proc-approve-notes').value = '';
      document.getElementById('proc-approve-error').style.display = 'none';

      document.getElementById('proc-approve-overlay').style.display = 'flex';

    } catch (err) {
      console.error('openProcApproveModal failed:', err);
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
      errorEl.textContent   = 'Please enter a valid approved budget amount.';
      errorEl.style.display = 'block';
      return;
    }

    btn.disabled    = true;
    btn.textContent = 'Approving…';

    try {
      const res  = await Auth.fetch(
        `/api/v1/procurement/orders/${_procActiveId}/approve/`, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ approved_budget: budget, finance_notes: notes }),
        }
      );
      const data = await res.json();

      if (!res.ok) {
        errorEl.textContent   = data.detail || 'Approval failed.';
        errorEl.style.display = 'block';
        return;
      }

      closeProcApproveModal();
      _toast(`Order ${data.order_number} approved. GHS ${budget.toFixed(2)} cleared.`, 'success');
      await _loadProcurement();

    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Approve Budget';
    }
  }

  // ── Procurement reject modal ──────────────────────────────
  function openProcRejectModal() {
    document.getElementById('proc-reject-notes').value          = '';
    document.getElementById('proc-reject-error').style.display  = 'none';
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
      errorEl.textContent   = 'Please provide a rejection reason (min 10 characters).';
      errorEl.style.display = 'block';
      return;
    }

    btn.disabled    = true;
    btn.textContent = 'Rejecting…';

    try {
      const res  = await Auth.fetch(
        `/api/v1/procurement/orders/${_procActiveId}/reject/`, {
          method:  'POST',
          headers: { 'Content-Type': 'application/json' },
          body:    JSON.stringify({ finance_notes: notes }),
        }
      );
      const data = await res.json();

      if (!res.ok) {
        errorEl.textContent   = data.detail || 'Rejection failed.';
        errorEl.style.display = 'block';
        return;
      }

      closeProcRejectModal();
      closeProcApproveModal();
      _toast('Order returned to Operations for revision.', 'info');
      await _loadProcurement();

    } catch {
      errorEl.textContent   = 'Network error. Please try again.';
      errorEl.style.display = 'block';
    } finally {
      btn.disabled    = false;
      btn.textContent = 'Confirm Rejection';
    }
  }

  // ── Helpers ───────────────────────────────────────────────
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

  function _fmtDate(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('en-GB', {
      day:'numeric', month:'short', hour:'2-digit', minute:'2-digit'
    });
  }

  function _toast(msg, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    const el       = document.createElement('div');
    el.className   = `toast ${type}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  return {
    init,
    switchPane,
    openClarifyModal, closeClarifyModal, confirmClarify,
    openClearModal,   closeClearModal,   confirmClear,
    openProcApproveModal, closeProcApproveModal, confirmProcApprove,
    openProcRejectModal,  closeProcRejectModal,  confirmProcReject,
  };

})();

document.addEventListener('DOMContentLoaded', FinancePortal.init);