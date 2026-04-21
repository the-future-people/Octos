/* ============================================================
   Octos — HR Portal
   hr_portal.js
   ============================================================ */

const HR = (function () {

  // ── State ─────────────────────────────────────────────────
  let _currentPane = 'overview';
  let _currentAppId = null;
  let _currentApp   = null;
  let _allApps      = [];
  let _scoreStage   = null;
  let _scores       = { q1: 0, q2: 0, q3: 0, q4: 0, q5: 0 };

  const PIPELINE_STAGES = [
    { key: 'RECEIVED',     short: 'Received'     },
    { key: 'SCREENING',    short: 'Screening'    },
    { key: 'INTERVIEW_SCHEDULED', short: 'Interview' },
    { key: 'FINAL_REVIEW', short: 'Final Review' },
    { key: 'HIRED',        short: 'Hired'        },
  ];

  function _stageIndex(status) {
    const map = {
      RECEIVED:             0,
      SCREENING:            1,
      INTERVIEW_SCHEDULED:  2,
      INTERVIEW_DONE:       2,
      FINAL_REVIEW:         3,
      HIRED:                4,
      AWAITING_ACCEPTANCE:  4,
      ONBOARDING:           4,
      INFORMATION_SUBMITTED:4,
      INFORMATION_VERIFIED: 4,
      OFFER_ISSUED:         4,
    };
    return map[status] !== undefined ? map[status] : 0;
  }


  // ── Init ──────────────────────────────────────────────────
  async function init() {
    await Auth.guard(['HQ_HR_MANAGER', 'REGIONAL_HR_COORDINATOR']);
    const user = Auth.getUser();
    if (!user) return;

    const initials = ((user.first_name || '')[0] + (user.last_name || '')[0]).toUpperCase();
    _setEl('hr-user-initials', initials || '?');
    _setEl('hr-user-name', user.first_name + ' ' + user.last_name);
    _setEl('hr-profile-name', user.first_name + ' ' + user.last_name);
    _setEl('hr-scope-label', user.branch_name || 'National');

    switchPane('overview');
    _loadAppsBadge();
  }

  // ── Pane switcher ─────────────────────────────────────────
  function switchPane(pane) {
    _currentPane  = pane;
    _currentAppId = null;
    _currentApp   = null;

    document.querySelectorAll('.sidebar-item').forEach(function (el) {
      el.classList.toggle('active', el.dataset.pane === pane);
    });

    const main = document.getElementById('hr-main');
    if (!main) return;
    main.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading...</div>';

    if (pane === 'overview')     _loadOverview();
    if (pane === 'vacancies')    _loadVacancies();
    if (pane === 'applications') _loadApplicationsList();
    if (pane === 'onboarding')   _loadOnboarding();
    if (pane === 'employees')    _loadEmployees();
  }

  // ══════════════════════════════════════════════════════════
  // OVERVIEW
  // ══════════════════════════════════════════════════════════
async function _loadOverview() {
    const main = document.getElementById('hr-main');
    try {
      const [appsRes, vacsRes, empsRes] = await Promise.all([
        Auth.fetch('/api/v1/recruitment/applications/'),
        Auth.fetch('/api/v1/recruitment/vacancies/'),
        Auth.fetch('/api/v1/hr/employees/'),
      ]);
      const apps = appsRes.ok ? await appsRes.json() : [];
      const vacs = vacsRes.ok ? await vacsRes.json() : [];
      const emps = empsRes.ok ? await empsRes.json() : [];

      // ── People stats ──
      const totalStaff   = emps.length;
      const activeStaff  = emps.filter(function(e){return e.status==='ACTIVE';}).length;
      const onLeave      = emps.filter(function(e){return e.status==='ON_LEAVE';}).length;
      const suspended    = emps.filter(function(e){return e.status==='SUSPENDED';}).length;

      // Probation ending soon — within 30 days
      const now = new Date();
      const probationSoon = emps.filter(function(e){
        if(!e.date_joined) return false;
        const joined = new Date(e.date_joined);
        const probEnd = new Date(joined);
        probEnd.setMonth(probEnd.getMonth() + 3);
        const daysLeft = Math.ceil((probEnd - now) / 86400000);
        return daysLeft >= 0 && daysLeft <= 30;
      }).length;

      // ── Recruitment stats ──
      const openVacs   = vacs.filter(function(v){return v.status==='OPEN';}).length;
      const pipeline   = apps.filter(function(a){return ['RECEIVED','SCREENING','INTERVIEW_SCHEDULED','INTERVIEW_DONE','FINAL_REVIEW'].includes(a.status);});
      const onboarding = apps.filter(function(a){return ['ONBOARDING','INFORMATION_SUBMITTED','INFORMATION_VERIFIED','AWAITING_ACCEPTANCE'].includes(a.status);});
      const newThisWeek = apps.filter(function(a){
        const d = new Date(a.created_at);
        const weekAgo = new Date(); weekAgo.setDate(weekAgo.getDate()-7);
        return d >= weekAgo;
      });
      // ── Deltas vs last week ──
      const twoWeeksAgo = new Date(); twoWeeksAgo.setDate(twoWeeksAgo.getDate()-14);
      const weekAgo2    = new Date(); weekAgo2.setDate(weekAgo2.getDate()-7);
      const lastWeekApps = apps.filter(function(a){
        const d = new Date(a.created_at);
        return d >= twoWeeksAgo && d < weekAgo2;
      });
      const newDelta     = newThisWeek.length - lastWeekApps.length;
      const pipeDelta    = null; // needs historical data

      // ── Smart action items ──
      const actions = [];
      apps.forEach(function(a){
        if(a.status==='RECEIVED') actions.push({ id:a.id, name:a.full_name, text:'New application — awaiting CV screening', urgency:'blue', days: Math.floor((now - new Date(a.created_at))/86400000) });
        if(a.status==='SCREENING') {
          const scores = a.stage_scores || [];
          const screening = scores.find(function(s){return s.stage==='SCREENING';});
          if(screening && screening.passed) actions.push({ id:a.id, name:a.full_name, text:'Screening passed — interview not yet scheduled', urgency:'amber', days: Math.floor((now - new Date(a.updated_at))/86400000) });
        }
        if(a.status==='INTERVIEW_DONE') actions.push({ id:a.id, name:a.full_name, text:'Interview complete — decision pending', urgency:'amber', days: Math.floor((now - new Date(a.updated_at))/86400000) });
        if(a.status==='INFORMATION_SUBMITTED') actions.push({ id:a.id, name:a.full_name, text:'Onboarding form submitted — verification needed', urgency:'red', days: Math.floor((now - new Date(a.updated_at))/86400000) });
      });

      // ── Pipeline health ──
      const stageMap = {
        RECEIVED:            { label:'Received',     color:'#1a3599' },
        SCREENING:           { label:'Screening',    color:'#7a5c00' },
        INTERVIEW_SCHEDULED: { label:'Interview',    color:'#7733cc' },
        INTERVIEW_DONE:      { label:'Scored',       color:'#7733cc' },
        FINAL_REVIEW:        { label:'Final Review', color:'#e8a020' },
      };
      const stageCounts = {};
      Object.keys(stageMap).forEach(function(k){ stageCounts[k]=0; });
      pipeline.forEach(function(a){ if(stageCounts[a.status]!==undefined) stageCounts[a.status]++; });

      // ── Vacancy performance ──
      const openVacsList = vacs.filter(function(v){return v.status==='OPEN';});

      // ── Recent activity ──
      const recentApps = apps.slice().sort(function(a,b){
        return new Date(b.created_at) - new Date(a.created_at);
      }).slice(0,8);

      // ── Today's date ──
      const dateStr = now.toLocaleDateString('en-GB',{weekday:'long',day:'numeric',month:'long',year:'numeric'});

      main.innerHTML =

        // Page header
        '<div style="display:flex;align-items:flex-end;justify-content:space-between;margin-bottom:24px;">' +
          '<div>' +
            '<div class="pane-title">HR Overview</div>' +
            '<div class="pane-sub">Summary of people operations and recruitment</div>' +
          '</div>' +
          '<div style="font-size:12px;color:var(--text-3);font-weight:500;">' + _esc(dateStr) + '</div>' +
        '</div>' +

        // ═══ ZONE 1 — PEOPLE SNAPSHOT ═══
        '<div style="margin-bottom:8px;font-size:10px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:var(--text-3);">People</div>' +
        '<div style="display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:24px;">' +

          _statCard('Total Staff', totalStaff, 'across all branches',
            '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>', '#1a3599', '#eef3ff', null) +

          _statCard('Active', activeStaff, 'currently working',
            '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>', '#1a6640', '#edfaf4', null) +

          _statCard('On Leave', onLeave, 'staff on approved leave',
            '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>', '#7a5c00', '#fffbec', null) +

          _statCard('Suspended', suspended, 'pending review',
            '<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>', '#b91c1c', '#fff0f0', null) +

          _statCard('Probation Ending', probationSoon, 'within 30 days',
            '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>', '#7733cc', '#f5f0ff', null) +

        '</div>' +

        // ═══ ZONE 2 — RECRUITMENT ═══
        '<div style="margin-bottom:8px;font-size:10px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:var(--text-3);">Recruitment</div>' +
        '<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-bottom:20px;">' +

          _statCard('Open Vacancies', openVacs, 'positions accepting applications',
            '<path d="M21 13.5V19a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5.5"/><path d="M16 2l4 4-8 8H8v-4l8-8z"/>', '#1a3599', '#eef3ff', null) +

          _statCard('In Pipeline', pipeline.length, 'applications being processed',
            '<polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/>', '#7a5c00', '#fffbec', null) +

          _statCard('In Onboarding', onboarding.length, 'candidates post-hire',
            '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>', '#7733cc', '#f5f0ff', null) +

          _statCard('New This Week', newThisWeek.length, 'applications received',
            '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>', '#1a6640', '#edfaf4', newDelta) +

        '</div>' +

        // Recruitment detail — two columns
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:28px;">' +

          // Requires Action
          '<div class="table-wrap">' +
            '<div style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">' +
              '<div style="font-size:13px;font-weight:700;color:var(--text);">Requires Action</div>' +
              (actions.length ? '<span style="font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;background:#fff0f0;color:#b91c1c;">' + actions.length + ' pending</span>' : '') +
            '</div>' +
            '<div style="padding:0 18px;">' +
              (actions.length ? actions.map(function(a){
                const urgencyColors = { blue:'var(--blue-text)', amber:'var(--amber-text)', red:'var(--red-text)' };
                const urgencyBgs   = { blue:'var(--blue-bg)',   amber:'var(--amber-bg)',   red:'var(--red-bg)'   };
                return '<div class="action-item" style="cursor:pointer;" onclick="HR.openCandidateView(' + a.id + ',\'overview\')">' +
                  '<div class="action-icon" style="background:' + urgencyBgs[a.urgency] + ';color:' + urgencyColors[a.urgency] + ';">' +
                    '<svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                      '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>' +
                    '</svg>' +
                  '</div>' +
                  '<div class="action-text">' +
                    '<div class="action-title">' + _esc(a.name) + (a.days > 0 ? ' <span style="font-size:10px;color:var(--text-3);font-weight:400;">· ' + a.days + 'd ago</span>' : '') + '</div>' +
                    '<div class="action-sub">' + _esc(a.text) + '</div>' +
                  '</div>' +
                '</div>';
              }).join('') :
              '<div class="empty-state" style="padding:32px 0;">' +
                '<div class="empty-state-title">All caught up</div>' +
                '<div>No pending actions right now</div>' +
              '</div>') +
            '</div>' +
          '</div>' +

          // Pipeline health
          '<div class="table-wrap">' +
            '<div style="padding:14px 18px;border-bottom:1px solid var(--border);">' +
              '<div style="font-size:13px;font-weight:700;color:var(--text);">Pipeline Health</div>' +
            '</div>' +
            '<div style="padding:16px 18px;display:flex;flex-direction:column;gap:12px;">' +
              Object.entries(stageCounts).map(function(entry){
                const key   = entry[0];
                const count = entry[1];
                const info  = stageMap[key];
                const maxCount = Math.max(...Object.values(stageCounts), 1);
                const barPct = Math.round((count / maxCount) * 100);
                return '<div>' +
                  '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">' +
                    '<span style="font-size:12px;color:var(--text-2);">' + info.label + '</span>' +
                    '<span style="font-family:\'JetBrains Mono\',monospace;font-size:12px;font-weight:700;color:var(--text);">' + count + '</span>' +
                  '</div>' +
                  '<div style="height:5px;background:var(--border);border-radius:3px;overflow:hidden;">' +
                    '<div style="height:100%;width:' + (count===0?'4':barPct) + '%;background:' + info.color + ';border-radius:3px;opacity:' + (count===0?'0.2':'1') + ';transition:width 0.4s;"></div>' +
                  '</div>' +
                '</div>';
              }).join('') +

              // Closing soon warning
              (function(){
                const closingSoon = openVacsList.filter(function(v){
                  if(!v.closes_at) return false;
                  const days = Math.ceil((new Date(v.closes_at)-now)/86400000);
                  return days<=5 && days>=0;
                });
                if(!closingSoon.length) return '';
                return '<div style="margin-top:8px;padding:10px 12px;background:#fff0f0;border:1px solid #fca5a5;border-radius:var(--radius-sm);">' +
                  '<div style="font-size:11px;font-weight:700;color:#b91c1c;margin-bottom:4px;">⚠ Closing Soon</div>' +
                  closingSoon.map(function(v){
                    const days = Math.ceil((new Date(v.closes_at)-now)/86400000);
                    return '<div style="font-size:11px;color:#b91c1c;">' + _esc(v.title) + ' — ' + days + ' day(s) left</div>';
                  }).join('') +
                '</div>';
              })() +

            '</div>' +
          '</div>' +

        '</div>' +

        // Vacancy performance + Recent activity
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:28px;">' +

          // Vacancy performance
          '<div class="table-wrap">' +
            '<div style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">' +
              '<div style="font-size:13px;font-weight:700;color:var(--text);">Vacancy Performance</div>' +
              '<button onclick="HR.switchPane(\'vacancies\')" style="font-size:11px;color:var(--blue-text);background:none;border:none;cursor:pointer;font-family:inherit;font-weight:600;">View all →</button>' +
            '</div>' +
            '<div style="padding:0 18px;">' +
              (openVacsList.length ? openVacsList.map(function(v){
                const fillRate = v.positions_available > 0
                  ? Math.min(100, Math.round((v.applicant_count/v.positions_available)*100))
                  : 0;
                const daysLeft = v.closes_at ? Math.ceil((new Date(v.closes_at)-now)/86400000) : null;
                const daysColor = daysLeft===null?'var(--text-3)':daysLeft<=5?'#b91c1c':daysLeft<=10?'#7a5c00':'#1a6640';
                return '<div style="padding:14px 0;border-bottom:1px solid var(--border);">' +
                  '<div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">' +
                    '<div>' +
                      '<div style="font-size:13px;font-weight:600;color:var(--text);">' + _esc(v.title) + '</div>' +
                      '<div style="font-size:11px;color:var(--text-3);">' + _esc(v.branch_name||'General') + '</div>' +
                    '</div>' +
                    '<div style="text-align:right;">' +
                      '<div style="font-family:\'JetBrains Mono\',monospace;font-size:13px;font-weight:700;color:var(--text);">' + (v.applicant_count||0) + ' / ' + v.positions_available + '</div>' +
                      '<div style="font-size:10px;font-weight:600;color:' + daysColor + ';">' + (daysLeft!==null ? daysLeft+'d left' : '—') + '</div>' +
                    '</div>' +
                  '</div>' +
                  '<div style="height:4px;background:var(--border);border-radius:2px;overflow:hidden;">' +
                    '<div style="height:100%;width:' + fillRate + '%;background:' + (fillRate>=100?'#22c98a':fillRate>=50?'#e8c84a':'#1a3599') + ';border-radius:2px;transition:width 0.4s;"></div>' +
                  '</div>' +
                '</div>';
              }).join('') :
              '<div class="empty-state" style="padding:32px 0;"><div class="empty-state-title">No open vacancies</div></div>') +
            '</div>' +
          '</div>' +

          // Recent activity
          '<div class="table-wrap">' +
            '<div style="padding:14px 18px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;">' +
              '<div style="font-size:13px;font-weight:700;color:var(--text);">Recent Activity</div>' +
              '<button onclick="HR.switchPane(\'applications\')" style="font-size:11px;color:var(--blue-text);background:none;border:none;cursor:pointer;font-family:inherit;font-weight:600;">View all →</button>' +
            '</div>' +
            '<div style="padding:8px 18px;">' +
              (recentApps.length ? recentApps.map(function(a){
                const statusColors = {
                  RECEIVED:'#1a3599', SCREENING:'#7a5c00',
                  INTERVIEW_SCHEDULED:'#7733cc', INTERVIEW_DONE:'#7733cc',
                  FINAL_REVIEW:'#e8a020', HIRED:'#1a6640', REJECTED:'#b91c1c',
                };
                const dotColor = statusColors[a.status] || 'var(--text-3)';
                const d = new Date(a.created_at);
                const timeStr = d.toLocaleDateString('en-GB',{day:'numeric',month:'short'});
                return '<div style="display:flex;gap:12px;padding:10px 0;border-bottom:1px solid var(--border);align-items:flex-start;">' +
                  '<div style="display:flex;flex-direction:column;align-items:center;gap:0;flex-shrink:0;margin-top:4px;">' +
                    '<div style="width:8px;height:8px;border-radius:50%;background:' + dotColor + ';flex-shrink:0;"></div>' +
                  '</div>' +
                  '<div style="flex:1;min-width:0;">' +
                    '<div style="font-size:12px;font-weight:600;color:var(--text);">' + _esc(a.full_name) + '</div>' +
                    '<div style="font-size:11px;color:var(--text-3);">' + _esc(a.vacancy_title||'General Application') + '</div>' +
                  '</div>' +
                  '<div style="flex-shrink:0;text-align:right;">' +
                    '<div style="font-size:10px;font-weight:700;padding:2px 7px;border-radius:20px;' +
                      'background:' + dotColor + '22;color:' + dotColor + ';margin-bottom:2px;">' +
                      a.status.replace(/_/g,' ') + '</div>' +
                    '<div style="font-size:10px;color:var(--text-3);">' + timeStr + '</div>' +
                  '</div>' +
                '</div>';
              }).join('') :
              '<div class="empty-state" style="padding:32px 0;"><div class="empty-state-title">No activity yet</div></div>') +
            '</div>' +
          '</div>' +

        '</div>' +

        // ═══ ZONE 3 — COMING MODULES ═══
        '<div style="margin-bottom:8px;font-size:10px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:var(--text-3);">Coming to Octos HR</div>' +
        '<div style="display:grid;grid-template-columns:repeat(3,1fr);gap:12px;">' +

          _comingSoonCard('Attendance',
            '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
            'Clock-in tracking, late arrivals, daily attendance rate and shift compliance') +

          _comingSoonCard('Payroll',
            '<rect x="2" y="7" width="20" height="14" rx="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
            'Salary management, pay runs, deductions and payslip generation') +

          _comingSoonCard('Cases & Leave',
            '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>',
            'Disciplinary cases, leave requests, approvals and compliance tracking') +

        '</div>';

    } catch (e) {
      console.error(e);
      main.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load overview.</div>';
    }
  }

  function _statCard(title, num, hint, svgPath, numColor, iconBg, delta) {
    const deltaHtml = delta !== undefined && delta !== null
      ? '<div style="display:flex;align-items:center;gap:3px;font-size:10px;font-weight:700;' +
          'color:' + (delta > 0 ? '#1a6640' : delta < 0 ? '#b91c1c' : 'var(--text-3)') + ';">' +
          (delta > 0 ? '↑' : delta < 0 ? '↓' : '→') +
          ' ' + (delta > 0 ? '+' : '') + delta + ' vs last week' +
        '</div>'
      : '';

    return '<div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">' +
      '<div style="height:3px;background:' + numColor + ';width:100%;"></div>' +
      '<div style="padding:10px 12px;background:' + iconBg + '18;">' +
        '<div style="display:flex;align-items:flex-start;justify-content:space-between;margin-bottom:6px;">' +
          '<div style="width:26px;height:26px;border-radius:6px;background:' + iconBg + ';' +
            'display:flex;align-items:center;justify-content:center;flex-shrink:0;">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" ' +
              'fill="none" stroke="' + numColor + '" stroke-width="2">' + svgPath + '</svg>' +
          '</div>' +
          deltaHtml +
        '</div>' +
        '<div style="font-family:\'JetBrains Mono\',monospace;font-size:20px;font-weight:700;color:' + numColor + ';line-height:1;margin-bottom:3px;">' + num + '</div>' +
        '<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-2);margin-bottom:1px;">' + _esc(title) + '</div>' +
        '<div style="font-size:10px;color:var(--text-3);">' + _esc(hint) + '</div>' +
      '</div>' +
    '</div>';
  }

  function _comingSoonCard(title, svgPath, desc) {
    return '<div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);' +
      'padding:18px 20px;opacity:0.6;">' +
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:10px;">' +
        '<div style="width:32px;height:32px;border-radius:var(--radius-sm);background:var(--bg);' +
          'display:flex;align-items:center;justify-content:center;flex-shrink:0;">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="15" height="15" viewBox="0 0 24 24" ' +
            'fill="none" stroke="var(--text-3)" stroke-width="2">' + svgPath + '</svg>' +
        '</div>' +
        '<div>' +
          '<div style="font-size:13px;font-weight:700;color:var(--text);">' + _esc(title) + '</div>' +
          '<span style="font-size:9px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;' +
            'padding:1px 6px;border-radius:4px;background:var(--border);color:var(--text-3);">Coming Soon</span>' +
        '</div>' +
      '</div>' +
      '<div style="font-size:12px;color:var(--text-3);line-height:1.5;">' + _esc(desc) + '</div>' +
    '</div>';
  }

  function _overviewCard(title, num, hint, color) {
    const hex = { blue:'#1a3599', amber:'#7a5c00', green:'#1a6640', red:'#b91c1c', purple:'#7733cc' }[color] || '#1a1a1a';
    return '<div class="overview-card">' +
      '<div class="overview-card-title">' + _esc(title) + '</div>' +
      '<div class="overview-card-num" style="color:' + hex + ';">' + num + '</div>' +
      '<div class="overview-card-hint">' + _esc(hint) + '</div>' +
      '</div>';
  }

  function _actionItem(a) {
    const map = {
      RECEIVED:              { icon: '📥', cls: 'blue',  text: 'New application received' },
      INFORMATION_SUBMITTED: { icon: '📋', cls: 'amber', text: 'Onboarding form submitted — needs review' },
      INTERVIEW_DONE:        { icon: '🎯', cls: 'green', text: 'Interview scored — awaiting decision' },
    };
    const info = map[a.status] || { icon: '•', cls: 'blue', text: a.status };
    return '<div class="action-item" style="cursor:pointer;" onclick="HR.openCandidateView(' + a.id + ',\'overview\')">' +
      '<div class="action-icon ' + info.cls + '">' + info.icon + '</div>' +
      '<div class="action-text">' +
        '<div class="action-title">' + _esc(a.full_name) + '</div>' +
        '<div class="action-sub">' + _esc(info.text) + '</div>' +
      '</div></div>';
  }

  function _vacancyListItem(v) {
    return '<div class="action-item">' +
      '<div class="action-icon blue">💼</div>' +
      '<div class="action-text">' +
        '<div class="action-title">' + _esc(v.title) + '</div>' +
        '<div class="action-sub">' + _esc(v.branch_name||'General') + ' · ' + v.positions_available + ' position(s)</div>' +
      '</div></div>';
  }

  // ══════════════════════════════════════════════════════════
  // VACANCIES
  // ══════════════════════════════════════════════════════════
  async function _loadVacancies() {
    const main = document.getElementById('hr-main');
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/vacancies/');
      const vacs = res.ok ? await res.json() : [];

      main.innerHTML =
        '<div class="pane-header">' +
          '<div><div class="pane-title">Vacancies</div>' +
          '<div class="pane-sub">All open and closed positions across branches</div></div>' +
          '<button class="btn-primary" onclick="HR.openNewVacancy()">+ New Vacancy</button>' +
        '</div>' +
        '<div class="tab-bar">' +
          '<button class="tab-btn active" onclick="HR.filterVacancies(this,\'ALL\')">All</button>' +
          '<button class="tab-btn" onclick="HR.filterVacancies(this,\'OPEN\')">Open</button>' +
          '<button class="tab-btn" onclick="HR.filterVacancies(this,\'PAUSED\')">Paused</button>' +
          '<button class="tab-btn" onclick="HR.filterVacancies(this,\'FILLED\')">Filled</button>' +
          '<button class="tab-btn" onclick="HR.filterVacancies(this,\'CLOSED\')">Closed</button>' +
        '</div>' +
        '<div id="vacancies-list" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:16px;">' +
          (vacs.length ? vacs.map(_vacancyCard).join('') :
            '<div class="empty-state"><div class="empty-state-title">No vacancies yet</div>' +
            '<div>Create your first vacancy to start receiving applications.</div></div>') +
        '</div>';
    } catch (e) {
      main.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load vacancies.</div>';
    }
  }

  function _vacancyCard(v) {
    const statusColors = { OPEN:'green', PAUSED:'amber', FILLED:'blue', CLOSED:'red' };
    const sc    = statusColors[v.status] || 'blue';
    const scHex = { green:'#1a6640', amber:'#7a5c00', blue:'#1a3599', red:'#b91c1c' }[sc];
    const trackColors = { PUBLIC:'#1a3599', RECOMMENDATION:'#7a5c00', APPOINTMENT:'#7733cc' };
    const trackBgs    = { PUBLIC:'#eef3ff', RECOMMENDATION:'#fffbec', APPOINTMENT:'#f5f0ff' };
    const trackHex = trackColors[v.track] || '#9a9690';
    const trackBg  = trackBgs[v.track]    || '#f2f0eb';
    const daysLeft = v.closes_at ? Math.ceil((new Date(v.closes_at) - new Date()) / 86400000) : null;
    const daysColor = daysLeft === null ? 'var(--text-3)' : daysLeft <= 3 ? '#b91c1c' : daysLeft <= 10 ? '#7a5c00' : '#1a6640';
    const daysLabel = daysLeft === null ? '—' : daysLeft <= 0 ? 'Closing today' : daysLeft === 1 ? '1 day left' : daysLeft + ' days left';
    const empType = { FULL_TIME:'Full Time', PART_TIME:'Part Time', CONTRACT:'Contract' }[v.employment_type] || v.employment_type;

    return '<div class="vacancy-card" data-status="' + v.status + '" ' +
      'style="flex-direction:column;align-items:flex-start;gap:0;padding:0;overflow:hidden;cursor:default;">' +
      '<div style="width:100%;height:3px;background:' + scHex + ';"></div>' +
      '<div style="padding:14px 16px;width:100%;display:flex;flex-direction:column;gap:10px;flex:1;">' +
        '<div style="display:flex;align-items:center;justify-content:space-between;gap:6px;">' +
          '<span class="badge ' + sc + '" style="font-size:10px;padding:2px 8px;">' + v.status + '</span>' +
          '<span style="font-size:9px;font-weight:700;letter-spacing:0.5px;text-transform:uppercase;' +
            'padding:2px 7px;border-radius:4px;background:' + trackBg + ';color:' + trackHex + ';">' + (v.track||'PUBLIC') + '</span>' +
        '</div>' +
        '<div style="font-size:14px;font-weight:700;color:var(--text);line-height:1.3;">' + _esc(v.title) + '</div>' +
        '<div style="font-size:11px;color:var(--text-3);">' + _esc(v.branch_name||'General') + ' · ' + empType + '</div>' +
        '<div style="display:flex;align-items:center;">' +
          '<div style="flex:1;display:flex;flex-direction:column;gap:2px;">' +
            '<span style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);">Applicants</span>' +
            '<span style="font-family:\'JetBrains Mono\',monospace;font-size:15px;font-weight:700;color:var(--text);">' + (v.applicant_count||0) + '</span>' +
          '</div>' +
          '<div style="width:1px;height:28px;background:var(--border);margin:0 12px;"></div>' +
          '<div style="flex:1;display:flex;flex-direction:column;gap:2px;">' +
            '<span style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);">Positions</span>' +
            '<span style="font-family:\'JetBrains Mono\',monospace;font-size:15px;font-weight:700;color:' + scHex + ';">' + v.positions_available + '</span>' +
          '</div>' +
          '<div style="width:1px;height:28px;background:var(--border);margin:0 12px;"></div>' +
          '<div style="flex:1;display:flex;flex-direction:column;gap:2px;">' +
            '<span style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);">Deadline</span>' +
            '<span style="font-size:11px;font-weight:600;color:' + daysColor + ';">' + daysLabel + '</span>' +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div style="padding:10px 16px;border-top:1px solid var(--border);width:100%;display:flex;justify-content:flex-end;">' +
        '<button class="btn-secondary" style="font-size:11px;padding:5px 12px;" onclick="HR.viewVacancyApplicants(' + v.id + ')">View Applicants</button>' +
      '</div></div>';
  }

  function filterVacancies(btn, status) {
    document.querySelectorAll('.tab-bar .tab-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    document.querySelectorAll('#vacancies-list .vacancy-card').forEach(function (card) {
      card.style.display = (status === 'ALL' || card.dataset.status === status) ? '' : 'none';
    });
  }

  function viewVacancyApplicants(vacancyId) {
    _vacancyFilter = vacancyId;
    switchPane('applications');
  }

  // ══════════════════════════════════════════════════════════
  // VIEW 1 — APPLICATIONS LIST
  // ══════════════════════════════════════════════════════════
 let _appSortOrder = 'oldest';
  let _vacancyFilter = null;

  async function _loadApplicationsList() {
    const main = document.getElementById('hr-main');
    try {
      const res = await Auth.fetch('/api/v1/recruitment/applications/');
      _allApps  = res.ok ? await res.json() : [];
      if (_vacancyFilter) {
        _allApps = _allApps.filter(function(a) {
          return String(a.vacancy) === String(_vacancyFilter);
        });
      }
      _renderApplicationsList();
      _vacancyFilter = null;
    } catch (e) {
      main.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load applications.</div>';
    }
  }

  function _renderApplicationsList() {
    const main = document.getElementById('hr-main');
    if (!main) return;

    // Sort
    const sorted = _allApps.slice().sort(function (a, b) {
      if (_appSortOrder === 'oldest')   return new Date(a.created_at) - new Date(b.created_at);
      if (_appSortOrder === 'newest')   return new Date(b.created_at) - new Date(a.created_at);
      if (_appSortOrder === 'priority') return (b.is_priority ? 1 : 0) - (a.is_priority ? 1 : 0);
      return 0;
    });

    const sortLabel = { oldest: 'Oldest First', newest: 'Newest First', priority: 'Priority First' }[_appSortOrder];

    main.innerHTML =
      '<div class="pane-header">' +
        '<div><div class="pane-title">Applications</div>' +
        '<div class="pane-sub">Recruitment pipeline — ' + _allApps.length + ' application(s)</div></div>' +
        '<div style="display:flex;gap:8px;align-items:center;">' +
          '<button class="btn-secondary" style="font-size:12px;padding:7px 14px;" onclick="HR.openRecommend()">+ Recommend</button>' +
          '<button class="btn-secondary" style="font-size:12px;padding:7px 14px;" onclick="HR.openAppoint()">+ Appoint</button>' +
          '<div style="position:relative;">' +
            '<button id="sort-btn" class="btn-secondary" style="font-size:12px;padding:7px 14px;display:flex;align-items:center;gap:6px;" ' +
              'onclick="HR.toggleSortMenu(event)">' +
              '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">' +
                '<line x1="3" y1="6" x2="21" y2="6"/><line x1="6" y1="12" x2="18" y2="12"/><line x1="9" y1="18" x2="15" y2="18"/>' +
              '</svg>' +
              _esc(sortLabel) +
            '</button>' +
            '<div id="sort-menu" style="display:none;position:absolute;top:38px;right:0;width:160px;' +
              'background:var(--panel);border:1px solid var(--border);border-radius:var(--radius-sm);' +
              'box-shadow:var(--shadow-md);z-index:100;overflow:hidden;">' +
              ['oldest','newest','priority'].map(function(opt) {
                const labels = { oldest:'Oldest First', newest:'Newest First', priority:'Priority First' };
                const active = opt === _appSortOrder;
                return '<div onclick="HR.setSort(\'' + opt + '\')" ' +
                  'style="padding:10px 14px;font-size:13px;cursor:pointer;' +
                  'color:' + (active ? 'var(--text)' : 'var(--text-2)') + ';' +
                  'font-weight:' + (active ? '700' : '400') + ';' +
                  'background:' + (active ? 'var(--bg)' : 'var(--panel)') + ';" ' +
                  'onmouseover="this.style.background=\'var(--bg)\'" ' +
                  'onmouseout="this.style.background=\'' + (active ? 'var(--bg)' : 'var(--panel)') + '\'">' +
                  (active ? '✓ ' : '') + labels[opt] +
                '</div>';
              }).join('') +
            '</div>' +
          '</div>' +
        '</div>' +
      '</div>' +

      '<div class="tab-bar" style="margin-bottom:20px;">' +
        '<button class="tab-btn active" onclick="HR.filterApps(this,\'RECEIVED\')">Received</button>' +
        '<button class="tab-btn" onclick="HR.filterApps(this,\'SCREENING\')">Screening</button>' +
        '<button class="tab-btn" onclick="HR.filterApps(this,\'INTERVIEW_SCHEDULED\')">Interview</button>' +
        '<button class="tab-btn" onclick="HR.filterApps(this,\'FINAL_REVIEW\')">Final Review</button>' +
        '<button class="tab-btn" onclick="HR.filterApps(this,\'HIRED\')">Hired</button>' +
      '</div>' +

      '<div id="apps-list" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;">' +
        (sorted.length ? sorted.map(_appCard).join('') :
          '<div class="empty-state"><div class="empty-state-title">No applications yet</div>' +
          '<div>Applications will appear here as candidates apply.</div></div>') +
      '</div>';

    // Apply default filter — Received
    _applyAppFilter('RECEIVED');

    // Close sort menu on outside click
    setTimeout(function() {
      document.addEventListener('click', _closeSortMenuOutside, { once: true });
    }, 0);
  }

  function _applyAppFilter(status) {
    document.querySelectorAll('#apps-list > div').forEach(function (card) {
      card.style.display = (card.dataset.status === status) ? '' : 'none';
    });
  }

  function toggleSortMenu(e) {
    e.stopPropagation();
    const menu = document.getElementById('sort-menu');
    if (!menu) return;
    const isOpen = menu.style.display === 'block';
    menu.style.display = isOpen ? 'none' : 'block';
  }

  function setSort(order) {
    _appSortOrder = order;
    const menu = document.getElementById('sort-menu');
    if (menu) menu.style.display = 'none';
    _renderApplicationsList();
  }

  function _appCard(a) {
    const currentIdx = _stageIndex(a.status);
    const isTerminal = ['REJECTED','WITHDRAWN','DECLINED'].includes(a.status);
    const scMap = {
      RECEIVED:            { bg:'#eef3ff', color:'#1a3599' },
      SCREENING:           { bg:'#fffbec', color:'#7a5c00' },
      INTERVIEW_SCHEDULED: { bg:'#f5f0ff', color:'#7733cc' },
      INTERVIEW_DONE:      { bg:'#f5f0ff', color:'#7733cc' },
      FINAL_REVIEW:        { bg:'#fffbec', color:'#7a5c00' },
      HIRED:               { bg:'#edfaf4', color:'#1a6640' },
      REJECTED:            { bg:'#fff0f0', color:'#b91c1c' },
    };
    const sc = scMap[a.status] || { bg:'#f2f0eb', color:'#9a9690' };

    const stepper = isTerminal ? '' :
      '<div style="margin-top:14px;">' +
        '<div style="display:flex;align-items:center;">' +
          PIPELINE_STAGES.map(function (s, i) {
            const done    = i < currentIdx;
            const current = i === currentIdx;
            const dotBg   = done ? '#22c98a' : current ? '#1a3599' : '#e8e5df';
            const line    = i > 0 ? '<div style="flex:1;height:2px;background:' + (done ? '#22c98a' : '#e8e5df') + ';"></div>' : '';
            return line + '<div style="width:8px;height:8px;border-radius:50%;background:' + dotBg + ';flex-shrink:0;' +
              (current ? 'box-shadow:0 0 0 3px rgba(26,53,153,0.15);' : '') + '"></div>';
          }).join('') +
        '</div>' +
        '<div style="display:flex;margin-top:5px;">' +
          PIPELINE_STAGES.map(function (s, i) {
            const current = i === currentIdx;
            return '<div style="flex:1;font-size:8px;font-weight:' + (current?'700':'400') + ';' +
              'color:' + (current?'#1a3599':'var(--text-3)') + ';text-align:' +
              (i===0?'left':i===PIPELINE_STAGES.length-1?'right':'center') + ';">' +
              (i===0||i===PIPELINE_STAGES.length-1||current ? s.short : '') + '</div>';
          }).join('') +
        '</div>' +
      '</div>';

    return '<div class="table-wrap" data-status="' + a.status + '" ' +
      'style="padding:16px;cursor:pointer;transition:border-color 0.15s,box-shadow 0.15s;" ' +
      'onclick="HR.openCandidateView(' + a.id + ',\'applications\')" ' +
      'onmouseover="this.style.borderColor=\'var(--border-dark)\';this.style.boxShadow=\'var(--shadow)\'" ' +
      'onmouseout="this.style.borderColor=\'var(--border)\';this.style.boxShadow=\'none\'">' +

      '<div style="display:flex;align-items:flex-start;gap:12px;">' +
        '<div class="user-avatar" style="width:38px;height:38px;font-size:13px;flex-shrink:0;">' +
          ((a.full_name||'').split(' ').map(function(n){return n[0]||'';}).join('').slice(0,2).toUpperCase()) +
        '</div>' +
        '<div style="flex:1;min-width:0;">' +
          '<div style="font-size:13px;font-weight:700;color:var(--text);margin-bottom:2px;">' +
            _esc(a.full_name) +
            (a.is_priority ? ' <span style="color:var(--amber-text);font-size:11px;">★</span>' : '') +
          '</div>' +
          '<div style="font-size:11px;color:var(--text-3);">' +
            _esc(a.vacancy_title||'General Application') +
            (a.branch_name ? ' · ' + _esc(a.branch_name) : '') +
          '</div>' +
        '</div>' +
        '<span style="font-size:10px;font-weight:700;padding:3px 9px;border-radius:20px;flex-shrink:0;' +
          'background:' + sc.bg + ';color:' + sc.color + ';white-space:nowrap;">' +
          a.status.replace(/_/g,' ') + '</span>' +
      '</div>' +

      '<div style="display:flex;align-items:center;justify-content:space-between;margin-top:10px;">' +
        '<span class="track-pill ' + (a.track||'').toLowerCase() + '">' + (a.track||'') + '</span>' +
        '<span style="font-size:11px;color:var(--text-3);">' + _fmtDate(a.created_at) + '</span>' +
      '</div>' +

      stepper +
      '</div>';
  }

  function filterApps(btn, status) {
    document.querySelectorAll('.tab-bar .tab-btn').forEach(function (b) { b.classList.remove('active'); });
    btn.classList.add('active');
    _applyAppFilter(status);
  }

  // ══════════════════════════════════════════════════════════
  // VIEW 2 — CANDIDATE PROFILE (full page)
  // ══════════════════════════════════════════════════════════
  async function openCandidateView(id, returnPane) {
    _currentAppId = id;
    const main = document.getElementById('hr-main');
    if (!main) return;
    main.innerHTML = '<div class="loading-cell"><span class="spin"></span> Loading candidate...</div>';

    try {
      const res = await Auth.fetch('/api/v1/recruitment/applications/' + id + '/');
      if (!res.ok) throw new Error();
      _currentApp = await res.json();
      _renderCandidateView(_currentApp, returnPane || 'applications');
    } catch (e) {
      main.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load candidate.</div>';
    }
  }

function _renderCandidateView(a, returnPane) {
    const main = document.getElementById('hr-main');
    if (!main) return;

    const currentIdx = _stageIndex(a.status);
    const isTerminal = ['REJECTED','WITHDRAWN','DECLINED'].includes(a.status);
    const scores     = a.stage_scores || [];
    const screening  = scores.find(function (s) { return s.stage === 'SCREENING'; });
    const interview  = scores.find(function (s) { return s.stage === 'INTERVIEW'; });

    main.innerHTML =
      // Back button
      '<div style="margin-bottom:16px;">' +
        '<button onclick="HR.switchPane(\'' + returnPane + '\')" ' +
          'style="display:inline-flex;align-items:center;gap:6px;font-size:13px;font-weight:600;' +
          'color:var(--text-2);background:none;border:none;cursor:pointer;padding:0;">' +
          '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" ' +
            'fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>' +
          'Back to ' + (returnPane === 'onboarding' ? 'Onboarding' : 'Applications') +
        '</button>' +
      '</div>' +

      // Single unified candidate card
      '<div style="background:var(--panel);border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">' +

        // Name + meta
        '<div style="padding:20px 24px;display:flex;align-items:center;gap:14px;">' +
          '<div class="user-avatar" style="width:44px;height:44px;font-size:15px;flex-shrink:0;">' +
            ((a.full_name||'').split(' ').map(function(n){return n[0]||'';}).join('').slice(0,2).toUpperCase()) +
          '</div>' +
          '<div style="flex:1;">' +
            '<div style="font-family:\'Syne\',sans-serif;font-size:20px;font-weight:800;color:var(--text);">' +
              _esc(a.full_name) +
              (a.is_priority ? ' <span style="font-size:13px;color:var(--amber-text);">★ Priority</span>' : '') +
            '</div>' +
            '<div style="font-size:12px;color:var(--text-3);margin-top:2px;">' +
              _esc(a.vacancy_title||'General Application') +
              (a.branch_name ? ' · ' + _esc(a.branch_name) : '') +
            '</div>' +
          '</div>' +
          (isTerminal && a.status !== 'HIRED'
            ? '<span style="font-size:11px;font-weight:700;padding:4px 12px;border-radius:20px;background:#fff0f0;color:#b91c1c;">' +
                a.status.replace(/_/g,' ') + '</span>'
            : '') +
        '</div>' +

        // Stepper
        '<div style="padding:16px 24px;border-top:1px solid var(--border);border-bottom:1px solid var(--border);">' +
          '<div style="display:flex;align-items:flex-start;position:relative;">' +
            '<div style="position:absolute;top:10px;left:10px;right:10px;height:2px;background:var(--border);z-index:0;"></div>' +
            PIPELINE_STAGES.map(function (s, i) {
              const done    = i < currentIdx;
              const current = i === currentIdx && !isTerminal;
              const dotBg   = done ? '#22c98a' : current ? '#1a3599' : '#e8e5df';
              const textCol = done ? '#1a6640' : current ? '#1a3599' : 'var(--text-3)';
              return '<div style="display:flex;flex-direction:column;align-items:center;gap:6px;flex:1;z-index:1;">' +
                '<div style="width:22px;height:22px;border-radius:50%;background:' + dotBg + ';' +
                  'display:flex;align-items:center;justify-content:center;' +
                  (current ? 'box-shadow:0 0 0 4px rgba(26,53,153,0.1);' : '') + '">' +
                  (done
                    ? '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="3"><polyline points="20 6 9 17 4 12"/></svg>'
                    : '<div style="width:7px;height:7px;border-radius:50%;background:' + (current?'white':'#c8c5bf') + ';"></div>') +
                '</div>' +
                '<div style="font-size:10px;font-weight:' + (current?'700':'500') + ';color:' + textCol + ';text-align:center;">' +
                  s.short + '</div>' +
              '</div>';
            }).join('') +
          '</div>' +
        '</div>' +

        // Info strip — full values, no truncation
        '<div style="display:flex;flex-wrap:wrap;border-bottom:1px solid var(--border);">' +
          [
            { label: 'Email',   val: a.email || '—' },
            { label: 'Phone',   val: a.phone || '—' },
            { label: 'Channel', val: a.preferred_channel || '—' },
            { label: 'Applied', val: _fmtDate(a.created_at) },
            { label: 'Track',   val: a.track || '—' },
          ].map(function (item) {
            return '<div style="padding:14px 20px;border-right:1px solid var(--border);flex-shrink:0;">' +
              '<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;' +
                'color:var(--text-3);margin-bottom:4px;">' + _esc(item.label) + '</div>' +
              '<div style="font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;">' +
                _esc(String(item.val)) + '</div>' +
            '</div>';
          }).join('') +
        '</div>' +

        // Stage action area
        '<div style="padding:20px 24px;">' +
          _buildStageContent(a, screening, interview) +
        '</div>' +

      '</div>';
  }

  function _infoCell(label, val) {
    return '<div style="background:var(--panel);padding:14px 18px;">' +
      '<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);margin-bottom:4px;">' + _esc(label) + '</div>' +
      '<div style="font-size:13px;font-weight:600;color:var(--text);">' + _esc(String(val)) + '</div>' +
      '</div>';
  }

  function _buildStageContent(a, screening, interview) {
    const s = a.status;

    function box(title, body, footer) {
      return '<div style="border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;">' +
        '<div style="padding:14px 20px;background:var(--bg);border-bottom:1px solid var(--border);' +
          'font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-2);">' + title + '</div>' +
        '<div style="padding:20px;">' + body + '</div>' +
        (footer ? '<div style="padding:14px 20px;border-top:1px solid var(--border);display:flex;gap:8px;flex-wrap:wrap;">' + footer + '</div>' : '') +
        '</div>';
    }

    function p(text) { return '<p style="font-size:13px;color:var(--text-2);line-height:1.6;">' + text + '</p>'; }

    if (s === 'RECEIVED') {
      return box('New Application — Awaiting Review',
        p('Review the candidate\'s details and CV above, then begin CV screening to start scoring.') +
        (a.cv ? '<div style="margin-top:14px;"><a href="' + a.cv + '" target="_blank" class="btn-secondary" style="display:inline-block;font-size:12px;padding:7px 14px;text-decoration:none;">Open CV →</a></div>' : ''),
        '<button class="btn-primary" onclick="HR.startScreening()">Begin CV Screening →</button>'
      );
    }
    if (s === 'SCREENING') {
      const scoreHtml = screening
        ? _scoreDisplay(screening) + '<div style="margin-top:12px;">' +
            (screening.passed ? p('Passed CV screening. Proceed to schedule the interview.') : p('Did not pass CV screening.')) + '</div>'
        : p('CV has not been scored yet.');
      return box('CV Screening', scoreHtml,
        screening && screening.passed
          ? '<button class="btn-green" onclick="HR.openInviteModal()">Schedule Interview →</button>'
          : '<button class="btn-primary" onclick="HR.startScreening()">' + (screening?'Re-score CV':'Score CV →') + '</button>' +
            (screening ? '<button class="btn-danger" onclick="HR.decide(\'REJECT\')">Reject</button>' : '')
      );
    }
    if (s === 'INTERVIEW_SCHEDULED') {
      return box('Interview Scheduled',
        p('Interview has been scheduled. Once conducted, submit the interview scores.'),
        '<button class="btn-primary" onclick="HR.startInterviewScoring()">Submit Interview Scores →</button>'
      );
    }
    if (s === 'INTERVIEW_DONE') {
      return box('Interview Complete',
        (interview ? _scoreDisplay(interview) + '<div style="margin-top:14px;"></div>' : '') + p('Review scores and make your final decision.'),
        '<button class="btn-green" onclick="HR.decide(\'HIRE\')">Hire Candidate</button>' +
        '<button class="btn-danger" onclick="HR.decide(\'REJECT\')">Reject</button>'
      );
    }
    if (s === 'FINAL_REVIEW') {
      return box('Final Review',
        (screening ? '<div style="margin-bottom:16px;"><div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);margin-bottom:8px;">CV Screening</div>' + _scoreDisplay(screening) + '</div>' : '') +
        (interview ? '<div><div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);margin-bottom:8px;">Interview</div>' + _scoreDisplay(interview) + '</div>' : ''),
        '<button class="btn-green" onclick="HR.decide(\'HIRE\')">Confirm Hire</button>' +
        '<button class="btn-danger" onclick="HR.decide(\'REJECT\')">Reject</button>'
      );
    }
    if (s === 'AWAITING_ACCEPTANCE') {
      return box('Awaiting Candidate Acceptance',
        p('Candidate has been notified. Record their response when received.'),
        '<button class="btn-green" onclick="HR.recordAcceptance(true)">Record Acceptance</button>' +
        '<button class="btn-danger" onclick="HR.recordAcceptance(false)">Record Decline</button>'
      );
    }
    if (s === 'ONBOARDING') {
      const token   = a.onboarding_token;
      const baseUrl = window.location.origin;
      const formLink = token ? baseUrl + '/onboarding/' + token + '/' : null;
      const tokenExpiry = a.onboarding_token_expires_at ? _fmtDate(a.onboarding_token_expires_at) : '—';
      return box('Onboarding — Form Link',
        '<div style="display:flex;flex-direction:column;gap:16px;">' +
          '<div style="display:flex;align-items:center;gap:10px;padding:12px 14px;' +
            'background:#edfaf4;border:1px solid #a8dfc0;border-radius:var(--radius-sm);">' +
            '<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" ' +
              'fill="none" stroke="#1a6640" stroke-width="2">' +
              '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>' +
            '</svg>' +
            '<div>' +
              '<div style="font-size:12px;font-weight:700;color:#1a6640;">Candidate has accepted the offer</div>' +
              '<div style="font-size:11px;color:#1a6640;opacity:0.8;">Onboarding form has been generated and is ready to share</div>' +
            '</div>' +
          '</div>' +
          (formLink
            ? '<div style="display:flex;flex-direction:column;gap:6px;">' +
                '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);">Onboarding Form Link</div>' +
                '<div style="display:flex;gap:8px;align-items:center;">' +
                  '<div style="flex:1;padding:10px 12px;background:var(--bg);border:1px solid var(--border);' +
                    'border-radius:var(--radius-sm);font-size:11px;color:var(--text-2);' +
                    'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-family:\'JetBrains Mono\',monospace;">' +
                    _esc(formLink) +
                  '</div>' +
                  '<button onclick="HR.copyOnboardingLink(\'' + _esc(formLink) + '\')" ' +
                    'class="btn-secondary" style="font-size:11px;padding:8px 14px;white-space:nowrap;flex-shrink:0;">' +
                    'Copy Link' +
                  '</button>' +
                '</div>' +
                '<div style="font-size:11px;color:var(--text-3);">Link expires: <strong>' + tokenExpiry + '</strong> · Share via candidate\'s preferred channel</div>' +
              '</div>'
            : '<div style="padding:12px 14px;background:#fff0f0;border:1px solid #fca5a5;border-radius:var(--radius-sm);font-size:12px;color:#b91c1c;">No onboarding token found.</div>') +
          '<div style="padding:12px 14px;background:var(--bg);border:1px solid var(--border);border-radius:var(--radius-sm);">' +
            '<div style="font-size:11px;color:var(--text-2);line-height:1.5;">' +
              '<strong>Preferred channel:</strong> ' + _esc(a.preferred_channel||'—') + '<br/>' +
              'Send the link above to the candidate via their preferred channel.' +
            '</div>' +
          '</div>' +
        '</div>',
        ''
      );
    }
    if (s === 'INFORMATION_SUBMITTED') {
      return box('Onboarding — Information Submitted',
        p('The candidate has submitted their onboarding form. Verify all information before issuing the offer letter.'),
        '<button class="btn-green" onclick="HR.verifyInfo()">Verify Information →</button>'
      );
    }
    if (s === 'INFORMATION_VERIFIED') {
      return box('Information Verified',
        p('All information verified. Issue the formal offer letter to complete the process.'),
        '<button class="btn-primary" onclick="HR.openOfferModal()">Issue Offer Letter →</button>'
      );
    }
    if (s === 'OFFER_ISSUED') {
      return box('Offer Letter Issued', p('The offer letter has been sent. Awaiting candidate confirmation.'), '');
    }
    if (s === 'HIRED') {
      return box('✓ Hired', '<p style="font-size:14px;font-weight:600;color:var(--green-text);">This candidate has been successfully hired and is now an active employee.</p>', '');
    }
    if (s === 'REJECTED') {
      return box('Rejected', '<p style="font-size:13px;color:var(--red-text);">Application was rejected.' + (a.rejection_reason ? ' Reason: ' + _esc(a.rejection_reason) : '') + '</p>', '');
    }
    return box(s.replace(/_/g,' '), p('No actions available at this stage.'), '');
  }

  function copyOnboardingLink(link) {
    navigator.clipboard.writeText(link).then(function() {
      _toast('Onboarding link copied to clipboard.', 'success');
    }).catch(function() {
      _toast('Could not copy — please copy manually.', 'error');
    });
  }

  function _scoreDisplay(score) {
    const pct = Math.round((score.raw_score / 25) * 100);
    const barColor = pct >= 70 ? '#22c98a' : pct >= 50 ? '#e8c84a' : '#E8000D';
    return '<div>' +
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
        '<span style="font-size:12px;color:var(--text-3);">' + score.stage + ' Score</span>' +
        '<span style="font-family:\'JetBrains Mono\',monospace;font-size:15px;font-weight:700;color:var(--text);">' + score.raw_score + '/25</span>' +
      '</div>' +
      '<div style="height:8px;background:var(--border);border-radius:4px;overflow:hidden;">' +
        '<div style="height:100%;width:' + pct + '%;background:' + barColor + ';border-radius:4px;transition:width 0.4s;"></div>' +
      '</div>' +
      '<div style="margin-top:6px;font-size:12px;font-weight:600;color:' + (score.passed?'#1a6640':'#b91c1c') + ';">' +
        (score.passed ? '✓ Passed threshold' : '✗ Did not meet threshold') +
      '</div></div>';
  }

  // ══════════════════════════════════════════════════════════
  // VIEW 3 — SCORING MODAL (CV + Score Cards)
  // ══════════════════════════════════════════════════════════
  function startScreening() {
    if (!_currentApp) return;
    const qs = (_currentApp.questions||[]).filter(function(q){return q.stage==='SCREENING';});
    _openScoringModal('SCREENING', qs);
  }

  function startInterviewScoring() {
    if (!_currentApp) return;
    const qs = (_currentApp.questions||[]).filter(function(q){return q.stage==='INTERVIEW';});
    _openScoringModal('INTERVIEW', qs);
  }

  function _openScoringModal(stage, questions) {
    _scoreStage = stage;
    _scores = { q1:0, q2:0, q3:0, q4:0, q5:0 };

    document.getElementById('score-modal-title').textContent = stage === 'SCREENING' ? 'CV Screening' : 'Interview Scoring';
    document.getElementById('score-modal-sub').textContent   = _currentApp ? _currentApp.full_name : '—';

    const body  = document.getElementById('score-modal-body');
    const cvUrl = _currentApp && _currentApp.cv ? _currentApp.cv : null;
    const labels = ['Poor','Weak','Adequate','Strong','Excellent'];

    if (!questions.length) {
      body.innerHTML =
        '<div class="empty-state"><div class="empty-state-title">No questions configured</div>' +
        '<div>Questions for this role and stage have not been seeded.</div></div>' +
        '<button class="btn-secondary" style="width:100%;margin-top:16px;" onclick="HR.closeScoreModal()">Close</button>';
      document.getElementById('score-modal').classList.add('open');
      return;
    }

    const _token = localStorage.getItem('octos_access') || '';
    const cvSrc = _currentAppId
      ? '/api/v1/recruitment/applications/' + _currentAppId + '/cv/?token=' + _token
      : null;

    // Left panel — CV for screening, interview context card for interview
    const cvPanel = stage === 'SCREENING'
      ? // ── CV viewer ──
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">' +
          '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);margin-bottom:10px;">Candidate CV</div>' +
          (cvUrl
            ? '<iframe src="' + cvSrc + '" ' +
                'style="width:100%;height:100%;border:1px solid var(--border);' +
                'border-radius:var(--radius-sm);background:var(--bg);display:block;" ' +
                'frameborder="0" title="Candidate CV"></iframe>'
            : '<div style="height:100%;border:1px solid var(--border);border-radius:var(--radius-sm);' +
                'display:flex;flex-direction:column;align-items:center;justify-content:center;' +
                'gap:8px;background:var(--bg);color:var(--text-3);">' +
                '<div style="font-size:32px;">📄</div>' +
                '<div style="font-size:13px;">No CV uploaded</div>' +
              '</div>') +
        '</div>'

      : // ── Interview context card ──
        '<div style="flex:1;min-width:0;display:flex;flex-direction:column;">' +
          '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);margin-bottom:10px;">Interview Session</div>' +
          '<div style="flex:1;border:1px solid var(--border);border-radius:var(--radius);overflow:hidden;' +
            'display:flex;flex-direction:column;">' +

            // Illustration
            '<div style="flex:1;display:flex;align-items:center;justify-content:center;' +
              'background:linear-gradient(135deg,#eef3ff 0%,#f5f0ff 100%);padding:40px;">' +
              '<svg viewBox="0 0 400 260" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:360px;">' +

                // Table
                '<rect x="60" y="160" width="280" height="12" rx="6" fill="#c8c5bf"/>' +
                '<rect x="90" y="172" width="12" height="60" rx="4" fill="#c8c5bf"/>' +
                '<rect x="298" y="172" width="12" height="60" rx="4" fill="#c8c5bf"/>' +

                // Interviewer (left) — body
                '<ellipse cx="120" cy="148" rx="22" ry="28" fill="#1a3599" opacity="0.15"/>' +
                '<circle cx="120" cy="108" r="22" fill="#1a3599" opacity="0.2"/>' +
                // Interviewer head
                '<circle cx="120" cy="100" r="18" fill="#e8c8a0"/>' +
                '<ellipse cx="120" cy="96" rx="10" ry="8" fill="#8B6914"/>' +
                // Interviewer body
                '<path d="M90 148 Q120 130 150 148" fill="#1a3599" opacity="0.7"/>' +
                '<rect x="95" y="148" width="50" height="40" rx="8" fill="#1a3599" opacity="0.7"/>' +
                // Interviewer arm — writing
                '<path d="M140 165 Q160 158 168 155" stroke="#e8c8a0" stroke-width="6" stroke-linecap="round" fill="none"/>' +
                // Notepad
                '<rect x="162" y="148" width="30" height="22" rx="3" fill="white" stroke="#e8e5df" stroke-width="1"/>' +
                '<line x1="166" y1="154" x2="188" y2="154" stroke="#e8e5df" stroke-width="1"/>' +
                '<line x1="166" y1="158" x2="188" y2="158" stroke="#e8e5df" stroke-width="1"/>' +
                '<line x1="166" y1="162" x2="182" y2="162" stroke="#e8e5df" stroke-width="1"/>' +
                // Pen
                '<line x1="188" y1="148" x2="196" y2="140" stroke="#1a3599" stroke-width="2.5" stroke-linecap="round"/>' +

                // Candidate (right) — body
                '<circle cx="280" cy="100" r="18" fill="#d4a870"/>' +
                '<ellipse cx="280" cy="95" rx="9" ry="7" fill="#4a2800"/>' +
                '<path d="M250 148 Q280 130 310 148" fill="#22c98a" opacity="0.5"/>' +
                '<rect x="255" y="148" width="50" height="40" rx="8" fill="#22c98a" opacity="0.5"/>' +
                // Candidate arm — on table
                '<path d="M260 165 Q240 162 230 160" stroke="#d4a870" stroke-width="6" stroke-linecap="round" fill="none"/>' +
                '<path d="M300 165 Q320 162 330 160" stroke="#d4a870" stroke-width="6" stroke-linecap="round" fill="none"/>' +

                // Speech bubble from candidate
                '<ellipse cx="310" cy="72" rx="42" ry="22" fill="white" stroke="#e8e5df" stroke-width="1.5"/>' +
                '<path d="M288 90 L282 100 L296 88" fill="white" stroke="#e8e5df" stroke-width="1.5" stroke-linejoin="round"/>' +
                '<circle cx="298" cy="72" r="3" fill="#e8e5df"/>' +
                '<circle cx="310" cy="72" r="3" fill="#c8c5bf"/>' +
                '<circle cx="322" cy="72" r="3" fill="#e8e5df"/>' +

                // Subtle background circles
                '<circle cx="50" cy="50" r="30" fill="#1a3599" opacity="0.04"/>' +
                '<circle cx="360" cy="220" r="40" fill="#22c98a" opacity="0.04"/>' +

              '</svg>' +
            '</div>' +

            // Candidate info strip
            '<div style="border-top:1px solid var(--border);padding:20px 24px;background:var(--panel);">' +
              '<div style="display:flex;align-items:center;gap:12px;margin-bottom:16px;">' +
                '<div class="user-avatar" style="width:40px;height:40px;font-size:14px;flex-shrink:0;background:#1a3599;">' +
                  ((_currentApp && _currentApp.full_name) ? _currentApp.full_name.split(' ').map(function(n){return n[0]||'';}).join('').slice(0,2).toUpperCase() : '?') +
                '</div>' +
                '<div>' +
                  '<div style="font-size:15px;font-weight:700;color:var(--text);">' + _esc((_currentApp && _currentApp.full_name) || '—') + '</div>' +
                  '<div style="font-size:12px;color:var(--text-3);">' + _esc((_currentApp && _currentApp.vacancy_title) || 'General Application') + ((_currentApp && _currentApp.branch_name) ? ' · ' + _esc(_currentApp.branch_name) : '') + '</div>' +
                '</div>' +
              '</div>' +

              // Interview details
              (function(){
                const scores = (_currentApp && _currentApp.stage_scores) || [];
                const interviewScore = scores.find(function(s){ return s.stage === 'INTERVIEW'; });
                const scheduledAt = interviewScore && interviewScore.interview_scheduled_at;
                const location   = interviewScore && interviewScore.interview_location;
                return '<div style="display:flex;flex-direction:column;gap:8px;">' +
                  (scheduledAt
                    ? '<div style="display:flex;align-items:center;gap:10px;">' +
                        '<div style="width:28px;height:28px;border-radius:6px;background:#eef3ff;display:flex;align-items:center;justify-content:center;flex-shrink:0;">' +
                          '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#1a3599" stroke-width="2">' +
                            '<rect x="3" y="4" width="18" height="18" rx="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>' +
                          '</svg>' +
                        '</div>' +
                        '<div>' +
                          '<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);">Scheduled</div>' +
                          '<div style="font-size:12px;font-weight:600;color:var(--text);">' + _fmtDate(scheduledAt) + '</div>' +
                        '</div>' +
                      '</div>'
                    : '') +
                  (location
                    ? '<div style="display:flex;align-items:center;gap:10px;">' +
                        '<div style="width:28px;height:28px;border-radius:6px;background:#edf9f4;display:flex;align-items:center;justify-content:center;flex-shrink:0;">' +
                          '<svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#1a6640" stroke-width="2">' +
                            '<path d="M21 10c0 7-9 13-9 13s-9-6-9-13a9 9 0 0 1 18 0z"/><circle cx="12" cy="10" r="3"/>' +
                          '</svg>' +
                        '</div>' +
                        '<div>' +
                          '<div style="font-size:9px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);">Location</div>' +
                          '<div style="font-size:12px;font-weight:600;color:var(--text);">' + _esc(location) + '</div>' +
                        '</div>' +
                      '</div>'
                    : '') +
                  '<div style="margin-top:4px;padding:8px 12px;background:#fffbec;border:1px solid #f0d878;border-radius:6px;font-size:11px;color:#7a5c00;line-height:1.5;">' +
                    '🎯 Score based on verbal responses only — not the CV.' +
                  '</div>' +
                '</div>';
              })() +

            '</div>' +
          '</div>' +
        '</div>';

    const scorePanel =
      '<div style="width:300px;flex-shrink:0;display:flex;flex-direction:column;height:100%;overflow-y:auto;padding-right:4px;">' +
        '<div style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.5px;color:var(--text-3);margin-bottom:10px;">Score Each Question (1–5)</div>' +
        (stage === 'SCREENING'
          ? '<div style="padding:10px 12px;background:#eef3ff;border:1px solid #b0c4f8;border-radius:var(--radius-sm);margin-bottom:14px;font-size:11px;color:#1a3599;line-height:1.5;">' +
              '📄 <strong>CV Review Mode</strong> — Score based on what the CV demonstrates, not verbal responses.' +
            '</div>'
          : '<div style="padding:10px 12px;background:#fffbec;border:1px solid #f0d878;border-radius:var(--radius-sm);margin-bottom:14px;font-size:11px;color:#7a5c00;line-height:1.5;">' +
              '🎯 <strong>Interview Mode</strong> — Score based on the candidate\'s verbal responses during the interview.' +
            '</div>') +
        questions.map(function(q, i) {
          const qKey = 'q' + (i+1);
          return '<div style="margin-bottom:16px;padding-bottom:16px;border-bottom:1px solid var(--border);">' +
            '<div style="font-size:12px;font-weight:600;color:var(--text);margin-bottom:4px;line-height:1.4;">Q' + (i+1) + '. ' + _esc(q.question_text) + '</div>' +
            (q.guidance ? '<div style="font-size:11px;color:var(--text-3);margin-bottom:8px;font-style:italic;">' + _esc(q.guidance) + '</div>' : '') +
            '<div style="display:flex;gap:5px;">' +
              [1,2,3,4,5].map(function(n) {
                return '<div id="sc-' + qKey + '-' + n + '" data-q="' + qKey + '" data-val="' + n + '" ' +
                  'onclick="HR.selectScoreCard(this,\'' + qKey + '\',' + n + ')" ' +
                  'style="flex:1;border:1.5px solid var(--border);border-radius:var(--radius-sm);' +
                  'padding:7px 3px;text-align:center;cursor:pointer;transition:all 0.12s;background:var(--bg);">' +
                  '<div style="font-family:\'JetBrains Mono\',monospace;font-size:14px;font-weight:700;color:var(--text-2);">' + n + '</div>' +
                  '<div style="font-size:8px;color:var(--text-3);margin-top:2px;">' + labels[n-1] + '</div>' +
                '</div>';
              }).join('') +
            '</div>' +
          '</div>';
        }).join('') +

        '<div id="live-score-wrap" style="padding:12px;background:var(--bg);border-radius:var(--radius-sm);border:1px solid var(--border);margin-bottom:12px;">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px;">' +
            '<span style="font-size:11px;font-weight:600;color:var(--text-2);">Running Score</span>' +
            '<span id="live-score-val" style="font-family:\'JetBrains Mono\',monospace;font-size:14px;font-weight:700;color:var(--text);">0 / 25</span>' +
          '</div>' +
          '<div style="height:6px;background:var(--border);border-radius:3px;overflow:hidden;">' +
            '<div id="live-score-bar" style="height:100%;width:0%;border-radius:3px;transition:all 0.3s;background:var(--border-dark);"></div>' +
          '</div>' +
          '<div id="live-score-hint" style="margin-top:6px;font-size:11px;color:var(--text-3);">Score all questions to enable submit</div>' +
        '</div>' +

        '<div style="margin-bottom:12px;">' +
          '<label style="font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:0.4px;color:var(--text-2);display:block;margin-bottom:5px;">Notes (optional)</label>' +
          '<textarea id="score-notes" class="form-textarea" style="min-height:56px;" placeholder="General observations..."></textarea>' +
        '</div>' +

        '<button id="score-submit-btn" class="btn-primary" style="width:100%;opacity:0.38;cursor:not-allowed;" ' +
          'disabled onclick="HR.submitScore()">Submit Scores</button>' +
      '</div>';

    body.innerHTML =
      '<div style="display:flex;gap:24px;height:78vh;overflow:hidden;">' + cvPanel + scorePanel + '</div>';

    const box = document.querySelector('#score-modal .modal-box');
    if (box) { box.style.maxWidth = '1100px'; box.style.maxHeight = '95vh'; }

    document.getElementById('score-modal').classList.add('open');
  }

  function selectScoreCard(el, qKey, val) {
    _scores[qKey] = val;
    document.querySelectorAll('[data-q="' + qKey + '"]').forEach(function (card) {
      const selected = parseInt(card.dataset.val) === val;
      card.style.borderColor = selected ? '#1a3599' : 'var(--border)';
      card.style.background  = selected ? '#eef3ff' : 'var(--bg)';
      card.querySelector('div').style.color = selected ? '#1a3599' : 'var(--text-2)';
    });
    _updateLiveScore();
  }

  function _updateLiveScore() {
    const total   = Object.values(_scores).reduce(function(s,v){return s+v;},0);
    const scored  = Object.values(_scores).filter(function(v){return v>0;}).length;
    const allDone = scored === 5;
    const pct     = Math.round((total/25)*100);
    const barColor = !allDone ? 'var(--border-dark)' : pct>=70 ? '#22c98a' : pct>=50 ? '#e8c84a' : '#E8000D';

    const val  = document.getElementById('live-score-val');
    const bar  = document.getElementById('live-score-bar');
    const hint = document.getElementById('live-score-hint');
    const btn  = document.getElementById('score-submit-btn');

    if (val)  val.textContent = total + ' / 25';
    if (bar)  { bar.style.width=pct+'%'; bar.style.background=barColor; }
    if (hint) {
      hint.textContent = !allDone ? scored+' of 5 questions scored'
        : pct>=70 ? '✓ Strong score — will pass'
        : pct>=60 ? '~ Borderline — check threshold'
        : '✗ Low score — may not pass';
      hint.style.color = !allDone ? 'var(--text-3)' : pct>=70 ? '#1a6640' : pct>=60 ? '#7a5c00' : '#b91c1c';
    }
    if (btn) {
      btn.disabled      = !allDone;
      btn.style.opacity = allDone ? '1' : '0.38';
      btn.style.cursor  = allDone ? 'pointer' : 'not-allowed';
    }
  }

  async function submitScore() {
    if (!_currentAppId || !_scoreStage) return;
    if (Object.values(_scores).filter(function(v){return v===0;}).length > 0) {
      _toast('Please score all 5 questions.', 'error'); return;
    }
    const payload = {
      stage: _scoreStage,
      q1_score:_scores.q1, q2_score:_scores.q2, q3_score:_scores.q3,
      q4_score:_scores.q4, q5_score:_scores.q5,
      general_comment: document.getElementById('score-notes')?.value || '',
    };
    const endpoint = _scoreStage === 'SCREENING'
      ? '/api/v1/recruitment/applications/' + _currentAppId + '/screen/'
      : '/api/v1/recruitment/applications/' + _currentAppId + '/interview/';
    try {
      const res  = await Auth.fetch(endpoint, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok) { _toast(Object.values(data).flat().join(' ')||'Error.','error'); return; }
      closeScoreModal();
      _toast(data.passed
        ? '✓ Passed (' + data.raw_score + '/25)' + (_scoreStage==='SCREENING' ? ' — schedule the interview.' : ' — ready for decision.')
        : '✗ Did not pass (' + data.raw_score + '/25).', data.passed ? 'success' : 'info');
      await openCandidateView(_currentAppId, 'applications');
      if (data.passed && _scoreStage === 'SCREENING') {
        setTimeout(function(){ openInviteModal(); }, 350);
      }
    } catch (e) { _toast('Network error.', 'error'); }
  }

  function closeScoreModal() {
    const modal = document.getElementById('score-modal');
    if (modal) modal.classList.remove('open');
    const box = document.querySelector('#score-modal .modal-box');
    if (box) { box.style.maxWidth = ''; box.style.maxHeight = ''; }
    _scoreStage = null;
    _scores = { q1:0, q2:0, q3:0, q4:0, q5:0 };
  }

  // ══════════════════════════════════════════════════════════
  // ONBOARDING
  // ══════════════════════════════════════════════════════════
  async function _loadOnboarding() {
    const main = document.getElementById('hr-main');
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/applications/');
      const all  = res.ok ? await res.json() : [];
      const apps = all.filter(function(a){return ['ONBOARDING','INFORMATION_SUBMITTED','INFORMATION_VERIFIED','AWAITING_ACCEPTANCE','OFFER_ISSUED'].includes(a.status);});
      main.innerHTML =
        '<div class="pane-header"><div><div class="pane-title">Onboarding</div>' +
        '<div class="pane-sub">Candidates in the post-hire onboarding flow</div></div></div>' +
        '<div class="table-wrap"><table class="hr-table"><thead><tr>' +
          '<th>Candidate</th><th>Role</th><th>Branch</th><th>Status</th><th>Track</th><th></th>' +
        '</tr></thead><tbody>' +
          (apps.length ? apps.map(_onboardingRow).join('') :
            '<tr><td colspan="6" style="text-align:center;padding:48px;color:var(--text-3);">No candidates in onboarding</td></tr>') +
        '</tbody></table></div>';
    } catch(e) {
      main.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load onboarding.</div>';
    }
  }

  function _onboardingRow(a) {
    const cls = { ONBOARDING:'onboarding', INFORMATION_SUBMITTED:'screening', INFORMATION_VERIFIED:'verified', AWAITING_ACCEPTANCE:'awaiting', OFFER_ISSUED:'offer-issued' }[a.status] || 'received';
    return '<tr style="cursor:pointer;" onclick="HR.openCandidateView(' + a.id + ',\'onboarding\')">' +
      '<td><strong>' + _esc(a.full_name) + '</strong><br/><span style="font-size:11px;color:var(--text-3);">' + _esc(a.email||'') + '</span></td>' +
      '<td>' + _esc(a.vacancy_title||'—') + '</td><td>' + _esc(a.branch_name||'—') + '</td>' +
      '<td><span class="badge ' + cls + '">' + a.status.replace(/_/g,' ') + '</span></td>' +
      '<td><span class="track-pill ' + (a.track||'').toLowerCase() + '">' + (a.track||'') + '</span></td>' +
      '<td><button class="btn-secondary" style="font-size:11px;padding:5px 12px;" ' +
        'onclick="event.stopPropagation();HR.openCandidateView(' + a.id + ',\'onboarding\')">View</button></td></tr>';
  }

  // ══════════════════════════════════════════════════════════
  // EMPLOYEES
  // ══════════════════════════════════════════════════════════
  async function _loadEmployees() {
    const main = document.getElementById('hr-main');
    try {
      const res  = await Auth.fetch('/api/v1/hr/employees/');
      const emps = res.ok ? await res.json() : [];
      main.innerHTML =
        '<div class="pane-header"><div><div class="pane-title">Employees</div>' +
        '<div class="pane-sub">' + emps.length + ' staff across all branches</div></div></div>' +
        '<div class="table-wrap"><table class="hr-table"><thead><tr>' +
          '<th>Employee</th><th>Branch</th><th>Role</th><th>Status</th><th>Joined</th>' +
        '</tr></thead><tbody>' +
          (emps.length ? emps.map(_employeeRow).join('') :
            '<tr><td colspan="5" style="text-align:center;padding:48px;color:var(--text-3);">No employees found</td></tr>') +
        '</tbody></table></div>';
    } catch(e) {
      main.innerHTML = '<div class="loading-cell" style="color:var(--red-text);">Could not load employees.</div>';
    }
  }

  function _employeeRow(e) {
    const sc = { ACTIVE:'green', SUSPENDED:'amber', TERMINATED:'red', ON_LEAVE:'blue' }[e.status] || 'blue';
    return '<tr>' +
      '<td><div style="display:flex;align-items:center;gap:10px;">' +
        '<div class="user-avatar" style="width:28px;height:28px;font-size:10px;">' +
          ((e.full_name||'').split(' ').map(function(n){return n[0]||'';}).join('').slice(0,2).toUpperCase()) +
        '</div>' +
        '<div><div style="font-weight:600;color:var(--text);">' + _esc(e.full_name) + '</div>' +
        '<div style="font-size:11px;color:var(--text-3);">' + _esc(e.employee_number||'') + '</div></div>' +
      '</div></td>' +
      '<td>' + _esc(e.branch_name||'—') + '</td><td>' + _esc(e.role_name||'—') + '</td>' +
      '<td><span class="badge ' + sc + '">' + (e.status||'—') + '</span></td>' +
      '<td>' + _fmtDate(e.date_joined) + '</td></tr>';
  }

  // ══════════════════════════════════════════════════════════
  // ACTIONS
  // ══════════════════════════════════════════════════════════
  function openInviteModal() {
    document.getElementById('gen-modal-title').textContent = 'Schedule Interview';
    document.getElementById('gen-modal-sub').textContent   = 'Set date, time and location';
    document.getElementById('gen-modal-body').innerHTML =
      '<div class="form-group"><label class="form-label">Interview Date & Time</label>' +
        '<input class="form-input" type="datetime-local" id="invite-dt"/></div>' +
      '<div class="form-group"><label class="form-label">Location</label>' +
        '<input class="form-input" type="text" id="invite-loc" placeholder="e.g. Westland Branch Office"/></div>' +
      '<button class="btn-primary" style="width:100%;" onclick="HR.submitInvite()">Send Invite</button>';
    document.getElementById('gen-modal').classList.add('open');
  }

  async function submitInvite() {
    const dt  = document.getElementById('invite-dt')?.value;
    const loc = document.getElementById('invite-loc')?.value || '';
    if (!dt) { _toast('Please select a date and time.','error'); return; }
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/applications/' + _currentAppId + '/invite/', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({interview_scheduled_at:dt,interview_location:loc}) });
      const data = await res.json();
      if (!res.ok) { _toast(Object.values(data).flat().join(' ')||'Error.','error'); return; }
      closeGenModal();
      _toast('Interview scheduled. Candidate will be notified.','success');
      await openCandidateView(_currentAppId,'applications');
    } catch(e) { _toast('Network error.','error'); }
  }

  async function decide(decision) {
    if (!_currentAppId) return;
    let reason = '';
    if (decision==='REJECT') reason = prompt('Reason for rejection (optional):') || '';
    if (decision==='HIRE' && !confirm('Confirm hiring this candidate?')) return;
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/applications/' + _currentAppId + '/decide/', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({decision:decision,rejection_reason:reason}) });
      const data = await res.json();
      if (!res.ok) { _toast(Object.values(data).flat().join(' ')||'Error.','error'); return; }
      _toast(decision==='HIRE' ? 'Candidate hired. Awaiting acceptance.' : 'Candidate rejected.','success');
      await openCandidateView(_currentAppId,'applications');
    } catch(e) { _toast('Network error.','error'); }
  }

  async function recordAcceptance(accepted) {
    if (!_currentAppId) return;
    if (!confirm(accepted ? 'Record candidate acceptance?' : 'Record candidate decline?')) return;
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/applications/' + _currentAppId + '/accept/', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({accepted:accepted}) });
      const data = await res.json();
      if (!res.ok) { _toast(Object.values(data).flat().join(' ')||'Error.','error'); return; }
      _toast(data.message||'Updated.','success');
      await openCandidateView(_currentAppId,'applications');
    } catch(e) { _toast('Network error.','error'); }
  }

  function verifyInfo() {
    document.getElementById('gen-modal-title').textContent = 'Verify Onboarding Information';
    document.getElementById('gen-modal-sub').textContent   = 'Confirm all submitted information is accurate';
    document.getElementById('gen-modal-body').innerHTML =
      '<div class="form-group"><label class="form-label">Verification Notes (optional)</label>' +
        '<textarea class="form-textarea" id="verify-notes" placeholder="Any notes..."></textarea></div>' +
      '<button class="btn-green" style="width:100%;" onclick="HR.submitVerify()">Confirm Verified</button>';
    document.getElementById('gen-modal').classList.add('open');
  }

  async function submitVerify() {
    const notes = document.getElementById('verify-notes')?.value || '';
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/applications/' + _currentAppId + '/verify-info/', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({verification_notes:notes}) });
      const data = await res.json();
      if (!res.ok) { _toast(Object.values(data).flat().join(' ')||'Error.','error'); return; }
      closeGenModal();
      _toast('Information verified. Ready to issue offer letter.','success');
      await openCandidateView(_currentAppId,'onboarding');
    } catch(e) { _toast('Network error.','error'); }
  }

  function openOfferModal() {
    document.getElementById('gen-modal-title').textContent = 'Issue Offer Letter';
    document.getElementById('gen-modal-sub').textContent   = 'Set terms for the formal offer';
    document.getElementById('gen-modal-body').innerHTML =
      '<div class="form-group"><label class="form-label">Salary Offered (GHS)</label><input class="form-input" type="number" id="offer-salary" placeholder="0.00"/></div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
        '<div class="form-group"><label class="form-label">Employment Type</label><select class="form-select" id="offer-type"><option value="FULL_TIME">Full Time</option><option value="PART_TIME">Part Time</option><option value="CONTRACT">Contract</option></select></div>' +
        '<div class="form-group"><label class="form-label">Pay Frequency</label><select class="form-select" id="offer-freq"><option value="MONTHLY">Monthly</option><option value="BI_WEEKLY">Bi-Weekly</option><option value="WEEKLY">Weekly</option></select></div>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
        '<div class="form-group"><label class="form-label">Start Date</label><input class="form-input" type="date" id="offer-start"/></div>' +
        '<div class="form-group"><label class="form-label">Probation (months)</label><input class="form-input" type="number" id="offer-probation" value="3"/></div>' +
      '</div>' +
      '<div class="form-group"><label class="form-label">Branch ID</label><input class="form-input" type="number" id="offer-branch"/></div>' +
      '<div class="form-group"><label class="form-label">Additional Terms (optional)</label><textarea class="form-textarea" id="offer-terms"></textarea></div>' +
      '<button class="btn-primary" style="width:100%;" onclick="HR.submitOffer()">Issue Offer Letter</button>';
    document.getElementById('gen-modal').classList.add('open');
  }

  async function submitOffer() {
    const payload = {
      branch: parseInt(document.getElementById('offer-branch')?.value),
      salary_offered: parseFloat(document.getElementById('offer-salary')?.value),
      employment_type: document.getElementById('offer-type')?.value,
      pay_frequency: document.getElementById('offer-freq')?.value,
      start_date: document.getElementById('offer-start')?.value,
      probation_months: parseInt(document.getElementById('offer-probation')?.value||3),
      additional_terms: document.getElementById('offer-terms')?.value||'',
    };
    if (!payload.branch||!payload.salary_offered||!payload.start_date) { _toast('Please fill in all required fields.','error'); return; }
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/applications/' + _currentAppId + '/issue-offer/', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok) { _toast(Object.values(data).flat().join(' ')||'Error.','error'); return; }
      closeGenModal();
      _toast('Offer letter issued successfully.','success');
      await openCandidateView(_currentAppId,'onboarding');
    } catch(e) { _toast('Network error.','error'); }
  }

  function openRecommend() {
    document.getElementById('gen-modal-title').textContent = 'Recommend Candidate';
    document.getElementById('gen-modal-sub').textContent   = 'They will go through the full process';
    document.getElementById('gen-modal-body').innerHTML =
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
        '<div class="form-group"><label class="form-label">First Name</label><input class="form-input" type="text" id="rec-first"/></div>' +
        '<div class="form-group"><label class="form-label">Last Name</label><input class="form-input" type="text" id="rec-last"/></div>' +
      '</div>' +
      '<div class="form-group"><label class="form-label">Email</label><input class="form-input" type="email" id="rec-email"/></div>' +
      '<div class="form-group"><label class="form-label">Phone</label><input class="form-input" type="tel" id="rec-phone"/></div>' +
      '<div class="form-group"><label class="form-label">Note</label><textarea class="form-textarea" id="rec-note"></textarea></div>' +
      '<button class="btn-primary" style="width:100%;" onclick="HR.submitRecommend()">Submit Recommendation</button>';
    document.getElementById('gen-modal').classList.add('open');
  }

  async function submitRecommend() {
    const payload = { first_name:document.getElementById('rec-first')?.value.trim(), last_name:document.getElementById('rec-last')?.value.trim(), email:document.getElementById('rec-email')?.value.trim(), phone:document.getElementById('rec-phone')?.value.trim(), recommendation_note:document.getElementById('rec-note')?.value||'' };
    if (!payload.first_name||!payload.email||!payload.phone) { _toast('Please fill in all required fields.','error'); return; }
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/recommend/', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok) { _toast(Object.values(data).flat().join(' ')||'Error.','error'); return; }
      closeGenModal(); _toast('Candidate recommended.','success'); _loadApplicationsList();
    } catch(e) { _toast('Network error.','error'); }
  }

  function openAppoint() {
    document.getElementById('gen-modal-title').textContent = 'Direct Appointment';
    document.getElementById('gen-modal-sub').textContent   = 'CEO track — skips to onboarding';
    document.getElementById('gen-modal-body').innerHTML =
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
        '<div class="form-group"><label class="form-label">First Name</label><input class="form-input" type="text" id="apt-first"/></div>' +
        '<div class="form-group"><label class="form-label">Last Name</label><input class="form-input" type="text" id="apt-last"/></div>' +
      '</div>' +
      '<div class="form-group"><label class="form-label">Email</label><input class="form-input" type="email" id="apt-email"/></div>' +
      '<div class="form-group"><label class="form-label">Phone</label><input class="form-input" type="tel" id="apt-phone"/></div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
        '<div class="form-group"><label class="form-label">Role ID</label><input class="form-input" type="number" id="apt-role"/></div>' +
        '<div class="form-group"><label class="form-label">Branch ID</label><input class="form-input" type="number" id="apt-branch"/></div>' +
      '</div>' +
      '<div class="form-group"><label class="form-label">Note</label><textarea class="form-textarea" id="apt-note"></textarea></div>' +
      '<button class="btn-primary" style="width:100%;" onclick="HR.submitAppoint()">Appoint Directly</button>';
    document.getElementById('gen-modal').classList.add('open');
  }

  async function submitAppoint() {
    const payload = { first_name:document.getElementById('apt-first')?.value.trim(), last_name:document.getElementById('apt-last')?.value.trim(), email:document.getElementById('apt-email')?.value.trim(), phone:document.getElementById('apt-phone')?.value.trim(), role:parseInt(document.getElementById('apt-role')?.value), branch:parseInt(document.getElementById('apt-branch')?.value), appointment_note:document.getElementById('apt-note')?.value||'' };
    if (!payload.first_name||!payload.email||!payload.role||!payload.branch) { _toast('Please fill in all required fields.','error'); return; }
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/appoint/', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok) { _toast(Object.values(data).flat().join(' ')||'Error.','error'); return; }
      closeGenModal(); _toast('Candidate appointed. Awaiting their acceptance.','success'); _loadApplicationsList();
    } catch(e) { _toast('Network error.','error'); }
  }

  function openNewVacancy() {
    document.getElementById('gen-modal-title').textContent = 'New Vacancy';
    document.getElementById('gen-modal-sub').textContent   = 'Create a new open position';
    document.getElementById('gen-modal-body').innerHTML =
      '<div class="form-group"><label class="form-label">Title</label><input class="form-input" type="text" id="vac-title" placeholder="e.g. Cashier"/></div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
        '<div class="form-group"><label class="form-label">Role ID</label><input class="form-input" type="number" id="vac-role"/></div>' +
        '<div class="form-group"><label class="form-label">Branch ID (optional)</label><input class="form-input" type="number" id="vac-branch"/></div>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
        '<div class="form-group"><label class="form-label">Positions</label><input class="form-input" type="number" id="vac-positions" value="1"/></div>' +
        '<div class="form-group"><label class="form-label">Employment Type</label><select class="form-select" id="vac-type"><option value="FULL_TIME">Full Time</option><option value="PART_TIME">Part Time</option><option value="CONTRACT">Contract</option></select></div>' +
      '</div>' +
      '<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;">' +
        '<div class="form-group"><label class="form-label">Opens</label><input class="form-input" type="date" id="vac-opens"/></div>' +
        '<div class="form-group"><label class="form-label">Closes</label><input class="form-input" type="date" id="vac-closes"/></div>' +
      '</div>' +
      '<div class="form-group"><label class="form-label">Description</label><textarea class="form-textarea" id="vac-desc"></textarea></div>' +
      '<button class="btn-primary" style="width:100%;" onclick="HR.submitVacancy()">Create Vacancy</button>';
    document.getElementById('gen-modal').classList.add('open');
  }

  async function submitVacancy() {
    const payload = { title:document.getElementById('vac-title')?.value.trim(), role:parseInt(document.getElementById('vac-role')?.value), branch:parseInt(document.getElementById('vac-branch')?.value)||null, positions_available:parseInt(document.getElementById('vac-positions')?.value||1), employment_type:document.getElementById('vac-type')?.value, opens_at:document.getElementById('vac-opens')?.value, closes_at:document.getElementById('vac-closes')?.value, description:document.getElementById('vac-desc')?.value||'', track:'PUBLIC' };
    if (!payload.title||!payload.role||!payload.opens_at||!payload.closes_at) { _toast('Please fill in all required fields.','error'); return; }
    try {
      const res  = await Auth.fetch('/api/v1/recruitment/vacancies/', { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload) });
      const data = await res.json();
      if (!res.ok) { _toast(Object.values(data).flat().join(' ')||'Error.','error'); return; }
      closeGenModal(); _toast('Vacancy created successfully.','success'); _loadVacancies();
    } catch(e) { _toast('Network error.','error'); }
  }

  function closeGenModal() { document.getElementById('gen-modal').classList.remove('open'); }
  function closeDetail() {}

  async function _loadAppsBadge() {
    try {
      const res   = await Auth.fetch('/api/v1/recruitment/applications/?status=RECEIVED');
      const data  = res.ok ? await res.json() : [];
      const badge = document.getElementById('sidebar-apps-badge');
      if (badge) { badge.textContent=data.length; badge.style.display=data.length>0?'flex':'none'; }
    } catch(e) {}
  }

  function _esc(s) { if(!s)return''; return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function _fmtDate(d) { if(!d)return'—'; return new Date(d).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'}); }
  function _setEl(id,text) { const el=document.getElementById(id); if(el)el.textContent=text; }
  function _toast(msg,type) {
    const c=document.getElementById('toast-container'); if(!c)return;
    const t=document.createElement('div'); t.className='toast '+(type||'info'); t.textContent=msg;
    c.appendChild(t); setTimeout(function(){t.remove();},3500);
  }

  document.addEventListener('DOMContentLoaded', init);

  document.addEventListener('click', function (e) {
    if (e.target === document.getElementById('gen-modal')) closeGenModal();

    // Close sort menu on any outside click
    const menu = document.getElementById('sort-menu');
    const btn  = document.getElementById('sort-btn');
    if (menu && menu.style.display === 'block') {
      if (!menu.contains(e.target) && !(btn && btn.contains(e.target))) {
        menu.style.display = 'none';
      }
    }
  });

  return {
    switchPane,
    openCandidateView,
    filterApps,
    toggleSortMenu,
    setSort,
    filterVacancies,
    viewVacancyApplicants,
    startScreening,
    startInterviewScoring,
    selectScoreCard,
    submitScore,
    closeScoreModal,
    openInviteModal,
    submitInvite,
    decide,
    recordAcceptance,
    verifyInfo,
    submitVerify,
    openOfferModal,
    submitOffer,
    openRecommend,
    submitRecommend,
    openAppoint,
    submitAppoint,
    openNewVacancy,
    submitVacancy,
    closeGenModal,
    closeDetail,
    copyOnboardingLink,
  };

})();

const HRProfile = { toggle: function() {
  const dd=document.getElementById('hr-profile-dropdown');
  const arrow=document.getElementById('hr-profile-arrow');
  const open=dd&&dd.style.display==='block';
  if(dd) dd.style.display=open?'none':'block';
  if(arrow) arrow.style.transform=open?'':'rotate(180deg)';
}};

const HRNotif = { toggle: function() { HR.closeDetail&&HR.closeDetail(); } };