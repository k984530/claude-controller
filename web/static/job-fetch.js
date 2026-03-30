/* ═══════════════════════════════════════════════
   Job Fetch — API 호출, 폴링, 페이지네이션
   ═══════════════════════════════════════════════ */

let _fetchJobsTimer = null;
let _fetchJobsInFlight = false;

async function _fetchJobsCore() {
  if (_fetchJobsInFlight) return;
  _fetchJobsInFlight = true;
  try {
    const params = new URLSearchParams({ limit: _jobLimit });
    if (_jobLimit > 0) params.set('page', _jobPage);
    const data = await apiFetch(`/api/jobs?${params}`);
    if (Array.isArray(data)) {
      _jobTotal = data.length;
      _jobPages = 1;
      _jobPage = 1;
      renderJobs(data);
    } else {
      _jobTotal = data.total || 0;
      _jobPages = data.pages || 1;
      _jobPage = data.page || 1;
      renderJobs(data.jobs || []);
    }
    _renderJobPagination();
  } catch {
    // silent fail for polling
  } finally {
    _fetchJobsInFlight = false;
  }
}

function fetchJobs() {
  if (_fetchJobsTimer) clearTimeout(_fetchJobsTimer);
  _fetchJobsTimer = setTimeout(_fetchJobsCore, 300);
}

function goJobPage(page) {
  _jobPage = Math.max(1, Math.min(page, _jobPages));
  fetchJobs();
}

function _renderJobPagination() {
  let container = document.getElementById('jobPagination');
  if (!container) return;
  // limit=0 → 전체 로드 모드 (그룹별 자체 페이지네이션 사용)
  if (_jobLimit <= 0 || _jobPages <= 1) {
    container.innerHTML = '';
    return;
  }
  const prev = _jobPage > 1;
  const next = _jobPage < _jobPages;
  let html = '<div class="job-pagination">';
  html += `<button class="pg-btn" ${prev ? '' : 'disabled'} onclick="goJobPage(${_jobPage - 1})">&laquo;</button>`;

  const range = _buildPageRange(_jobPage, _jobPages);
  for (const p of range) {
    if (p === '...') {
      html += '<span class="pg-ellipsis">…</span>';
    } else {
      html += `<button class="pg-btn${p === _jobPage ? ' active' : ''}" onclick="goJobPage(${p})">${p}</button>`;
    }
  }

  html += `<button class="pg-btn" ${next ? '' : 'disabled'} onclick="goJobPage(${_jobPage + 1})">&raquo;</button>`;
  html += `<span class="pg-info">${_jobPage}/${_jobPages} (${_jobTotal})</span>`;
  html += '</div>';
  container.innerHTML = html;
}

function _buildPageRange(current, total) {
  if (total <= 7) return Array.from({ length: total }, (_, i) => i + 1);
  const pages = [];
  pages.push(1);
  if (current > 3) pages.push('...');
  for (let i = Math.max(2, current - 1); i <= Math.min(total - 1, current + 1); i++) {
    pages.push(i);
  }
  if (current < total - 2) pages.push('...');
  pages.push(total);
  return pages;
}
