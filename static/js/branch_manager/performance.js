'use strict';

const Performance = (() => {

  let _performanceTab = 'metrics';

  function loadPerformancePane() {
    const pane = document.getElementById('pane-performance');
    if (!pane) return;
    pane.innerHTML = `
      <div class="section-head">
        <span class="section-title">Performance</span>
      </div>
      <div class="reports-tabs" id="performance-tab-bar">
        <button class="reports-tab active" data-tab="metrics"
          onclick="Performance.switchPerformanceTab('metrics')">Branch Metrics</button>
        <button class="reports-tab" data-tab="services"
          onclick="Performance.switchPerformanceTab('services')">Service Performance</button>
      </div>
      <div id="performance-tab-content">
        <div class="loading-cell"><span class="spin"></span> Loading…</div>
      </div>`;
    switchPerformanceTab('metrics');
  }

  function switchPerformanceTab(tab) {
    _performanceTab = tab;
    document.querySelectorAll('#performance-tab-bar .reports-tab').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.tab === tab);
    });
    const content = document.getElementById('performance-tab-content');
    if (!content) return;

    if (tab === 'metrics') {
      content.innerHTML = `
        <div class="section-head" style="margin-top:16px;">
          <span></span>
          <div class="period-tabs">
            <button class="period-tab active" data-period="day"   onclick="Dashboard.setPeriod('day')">Day</button>
            <button class="period-tab"        data-period="week"  onclick="Dashboard.setPeriod('week')">Week</button>
            <button class="period-tab"        data-period="month" onclick="Dashboard.setPeriod('month')">Month</button>
          </div>
        </div>
        <div style="width:100%;">
          <div id="metrics-grid" style="width:100%;">
            <div class="loading-cell" style="padding:40px;">
              <span class="spin"></span> Loading metrics…
            </div>
          </div>
        </div>`;
      Dashboard._renderMetrics(Dashboard._getCurrentPeriod());
    }

    if (tab === 'services') {
      content.innerHTML = `
        <div id="services-report-content" style="margin-top:16px;">
          <div class="loading-cell"><span class="spin"></span> Loading…</div>
        </div>`;
      Reports.renderServicesReport(content);
    }
  }

  return {
    loadPerformancePane,
    switchPerformanceTab,
  };

})();