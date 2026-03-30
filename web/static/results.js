/* ═══════════════════════════════════════════════
   Results — 스킬/자동화 결과 기록 브라우저
   ═══════════════════════════════════════════════ */

let _resultsCache = null;

async function loadResults() {
  const container = document.getElementById('resultsBody');
  if (!container) return;

  try {
    const data = await apiFetch('/api/results');
    _resultsCache = data;
    _renderResults(data);
  } catch (err) {
    container.innerHTML = `<div class="results-empty">결과를 불러올 수 없습니다: ${escapeHtml(err.message)}</div>`;
  }
}

function _renderResults(data) {
  const container = document.getElementById('resultsBody');
  if (!data || !data.origins || data.origins.length === 0) {
    container.innerHTML = '<div class="results-empty">아직 기록된 결과가 없습니다</div>';
    return;
  }

  container.innerHTML = '<div class="results-groups">' +
    data.origins.map((g, idx) => _renderGroup(g, idx)).join('') +
    '</div>';
}

function _renderGroup(group, idx) {
  const iconClass = group.origin_type === 'skill' ? 'skill'
    : group.origin_type === 'pipeline' ? 'pipeline' : 'manual';
  const iconLabel = group.origin_type === 'skill' ? 'SK'
    : group.origin_type === 'pipeline' ? 'AU' : '--';
  const name = group.origin_name || group.origin_id || '직접 입력';
  const costStr = group.total_cost_usd ? `$${group.total_cost_usd.toFixed(3)}` : '';

  const jobRows = (group.jobs || []).map(j => _renderJobRow(j)).join('');

  return `
    <div class="result-group" id="rg-${idx}">
      <div class="result-group-header" onclick="toggleResultGroup(${idx})">
        <div class="result-group-icon ${iconClass}">${iconLabel}</div>
        <div class="result-group-info">
          <div class="result-group-name">${escapeHtml(name)}</div>
          <div class="result-group-meta">${_originTypeLabel(group.origin_type)} · ${group.total}건 실행</div>
        </div>
        <div class="result-group-stats">
          ${group.done ? `<span class="result-stat-done">${group.done} done</span>` : ''}
          ${group.failed ? `<span class="result-stat-fail">${group.failed} fail</span>` : ''}
          ${costStr ? `<span class="result-stat-cost">${costStr}</span>` : ''}
        </div>
        <svg class="result-group-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      </div>
      <div class="result-group-body">${jobRows || '<div style="color:var(--text-muted);font-size:0.78rem;">결과 없음</div>'}</div>
    </div>
  `;
}

function _renderJobRow(job) {
  const prompt = job.prompt || '';
  const summary = job.result_summary || '';
  const time = job.created_at || '';
  const cost = job.cost_usd ? `$${job.cost_usd.toFixed(3)}` : '';
  const status = job.status || 'done';

  return `
    <div class="result-job-row">
      <div class="result-job-status ${status}"></div>
      <div class="result-job-content">
        <div class="result-job-prompt" title="${escapeHtml(prompt)}">${escapeHtml(prompt.substring(0, 120))}</div>
        ${summary ? `<div class="result-job-summary">${escapeHtml(summary)}</div>` : ''}
      </div>
      <div class="result-job-cost">${cost}</div>
      <div class="result-job-time">${_shortTime(time)}</div>
    </div>
  `;
}

function toggleResultGroup(idx) {
  const el = document.getElementById('rg-' + idx);
  if (el) el.classList.toggle('open');
}

function _originTypeLabel(type) {
  if (type === 'skill') return '스킬';
  if (type === 'pipeline') return '자동화';
  return '수동';
}

function _shortTime(ts) {
  if (!ts) return '';
  // "2026-03-30 12:00:00" → "03-30 12:00"
  const m = ts.match(/(\d{2})-(\d{2})\s+(\d{2}:\d{2})/);
  return m ? `${m[1]}-${m[2]} ${m[3]}` : ts.substring(0, 16);
}
