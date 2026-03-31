/* ═══════════════════════════════════════════════
   Results — 스킬/자동화 결과 기록 브라우저
   ═══════════════════════════════════════════════ */

let _resultsCache = null;
const _RESULTS_PER_PAGE = 15;
let _resultsPage = 1;

async function loadResults() {
  const container = document.getElementById('resultsBody');
  if (!container) return;

  try {
    const data = await apiFetch('/api/results');
    _resultsCache = data;
    _resultsPage = 1;
    _renderResults(data);
  } catch (err) {
    container.innerHTML = `<div class="empty-state">${t('results_load_failed')}: ${escapeHtml(err.message)}</div>`;
  }
}

function _flattenJobs(data) {
  if (!data || !data.origins) return [];
  const jobs = [];
  for (const g of data.origins) {
    const groupName = g.origin_name || g.origin_id || t('pd_total');
    for (const j of (g.jobs || [])) {
      jobs.push({ ...j, _groupName: groupName, _groupCost: g.total_cost_usd });
    }
  }
  return jobs;
}

function _renderResults(data) {
  const container = document.getElementById('resultsBody');
  if (!data || !data.origins || data.origins.length === 0) {
    container.innerHTML = `<div class="empty-state"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg><div>${t('results_empty')}</div></div>`;
    return;
  }

  const allJobs = _flattenJobs(data);
  const totalPages = Math.ceil(allJobs.length / _RESULTS_PER_PAGE);
  if (_resultsPage > totalPages) _resultsPage = totalPages;
  if (_resultsPage < 1) _resultsPage = 1;

  const start = (_resultsPage - 1) * _RESULTS_PER_PAGE;
  const pageJobs = allJobs.slice(start, start + _RESULTS_PER_PAGE);

  // 페이지 내 job을 그룹별로 묶기
  const groups = [];
  let lastGroup = null;
  for (const j of pageJobs) {
    if (!lastGroup || lastGroup.name !== j._groupName) {
      lastGroup = { name: j._groupName, jobs: [] };
      groups.push(lastGroup);
    }
    lastGroup.jobs.push(j);
  }

  let html = groups.map((g, idx) => {
    const jobRows = g.jobs.map(j => _renderJobRow(j)).join('');
    return `
      <div class="result-group open" id="rg-${start + idx}">
        <div class="result-group-header" onclick="toggleResultGroup(${start + idx})">
          <svg class="result-group-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
          <span class="result-group-name">${escapeHtml(g.name)}</span>
          <span class="job-group-count">${g.jobs.length}</span>
        </div>
        <div class="result-group-body">
          <table class="result-table"><tbody>${jobRows}</tbody></table>
        </div>
      </div>
    `;
  }).join('');

  // 페이지네이션 UI
  if (totalPages > 1) {
    html += _renderResultsPagination(totalPages, allJobs.length);
  }

  container.innerHTML = html;
}

function _renderResultsPagination(totalPages, totalItems) {
  const start = (_resultsPage - 1) * _RESULTS_PER_PAGE + 1;
  const end = Math.min(_resultsPage * _RESULTS_PER_PAGE, totalItems);

  let btns = '';
  // prev
  btns += `<button class="rp-btn${_resultsPage <= 1 ? ' disabled' : ''}" onclick="setResultsPage(${_resultsPage - 1})" ${_resultsPage <= 1 ? 'disabled' : ''}>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="15 18 9 12 15 6"/></svg>
  </button>`;

  // page numbers
  const range = _pageRange(_resultsPage, totalPages);
  for (const p of range) {
    if (p === '...') {
      btns += '<span class="rp-ellipsis">…</span>';
    } else {
      btns += `<button class="rp-btn${p === _resultsPage ? ' active' : ''}" onclick="setResultsPage(${p})">${p}</button>`;
    }
  }

  // next
  btns += `<button class="rp-btn${_resultsPage >= totalPages ? ' disabled' : ''}" onclick="setResultsPage(${_resultsPage + 1})" ${_resultsPage >= totalPages ? 'disabled' : ''}>
    <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
  </button>`;

  return `<div class="results-pagination">
    <span class="rp-info">${start}–${end} / ${totalItems}</span>
    <div class="rp-btns">${btns}</div>
  </div>`;
}

function _pageRange(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = [];
  pages.push(1);
  if (current > 3) pages.push('...');
  for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) pages.push(i);
  if (current < total - 2) pages.push('...');
  pages.push(total);
  return pages;
}

function setResultsPage(page) {
  const allJobs = _flattenJobs(_resultsCache);
  const totalPages = Math.ceil(allJobs.length / _RESULTS_PER_PAGE);
  if (page < 1 || page > totalPages) return;
  _resultsPage = page;
  _renderResults(_resultsCache);
  // 스크롤 to top of results section
  const section = document.getElementById('resultsSection');
  if (section) section.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function _renderJobRow(job) {
  const prompt = job.prompt || '';
  const time = job.created_at || '';
  const cost = job.cost_usd ? `$${job.cost_usd.toFixed(2)}` : '';
  const jobId = job.job_id || '';
  const duration = job.duration_ms ? _formatDuration(job.duration_ms) : '';

  return `
    <tr onclick="toggleResultDetail('${escapeHtml(jobId)}')" title="${escapeHtml(prompt)}">
      <td class="rj-prompt">${escapeHtml(prompt.substring(0, 120))}</td>
      <td class="rj-cost">${duration ? duration + ' · ' : ''}${cost}</td>
      <td class="rj-time">${_shortTime(time)}</td>
    </tr>
    <tr class="result-expand-row" id="result-detail-row-${escapeHtml(jobId)}" style="display:none;">
      <td colspan="3"><div class="result-detail-panel" id="result-detail-${escapeHtml(jobId)}"></div></td>
    </tr>
  `;
}

async function toggleResultDetail(jobId) {
  const row = document.getElementById('result-detail-row-' + jobId);
  const el = document.getElementById('result-detail-' + jobId);
  if (!row || !el) return;

  if (row.style.display !== 'none') {
    row.style.display = 'none';
    return;
  }

  if (el.dataset.loaded) {
    row.style.display = '';
    return;
  }

  row.style.display = '';
  el.innerHTML = `<div class="result-detail-loading">${t('result_loading')}</div>`;

  try {
    const data = await apiFetch(`/api/jobs/${jobId}/result`);
    const resultText = data.result || t('result_none');
    el.innerHTML = `<div class="result-detail-content"><pre>${escapeHtml(resultText)}</pre></div>`;
    el.dataset.loaded = '1';
  } catch (err) {
    el.innerHTML = `<div class="result-detail-error">${t('results_load_failed')}: ${escapeHtml(err.message)}</div>`;
  }
}

function _formatDuration(ms) {
  if (ms < 60000) return Math.round(ms / 1000) + t('unit_sec');
  return Math.round(ms / 60000) + t('unit_min');
}

function toggleResultGroup(idx) {
  const el = document.getElementById('rg-' + idx);
  if (el) el.classList.toggle('open');
}

function _shortTime(ts) {
  if (!ts) return '';
  const m = ts.match(/(\d{2})-(\d{2})\s+(\d{2}:\d{2})/);
  return m ? `${m[1]}-${m[2]} ${m[3]}` : ts.substring(0, 16);
}
