/* ═══════════════════════════════════════════════
   Jobs — 작업 목록 렌더링, CRUD, 후속 명령
   ═══════════════════════════════════════════════ */

let expandedJobId = null;
let jobPollTimer = null;
let _jobFilterStatus = 'all';
let _jobFilterProject = 'all';
let _jobSearchQuery = '';
let _allJobs = [];
let _registeredProjects = [];
let _jobListCollapsed = localStorage.getItem('jobListCollapsed') === '1';
let _collapsedGroups = JSON.parse(localStorage.getItem('collapsedGroups') || '{}');
let _selectedProject = null;
let _selectedProjectInfo = null;
let _jobPage = 1;
let _jobLimit = 50;
let _jobPages = 1;
let _jobTotal = 0;
const _GROUP_PAGE_SIZE = 5;
let _groupPages = {};  // { groupName: currentPage(1-based) }

/* ── Stats ── */

async function fetchStats() {
  try {
    const data = await apiFetch('/api/stats');
    renderStats(data);
  } catch { /* 통계 실패는 무시 */ }
}

async function fetchRegisteredProjects() {
  try {
    const data = await apiFetch('/api/projects');
    _registeredProjects = Array.isArray(data) ? data : [];
    if (_allJobs.length > 0) _renderProjectStrip(_allJobs);
  } catch { _registeredProjects = []; }
}

function renderStats(data) {
  const jobs = data.jobs || {};
  const total = jobs.total || 0;
  const done = jobs.done || 0;
  const failed = jobs.failed || 0;
  const running = jobs.running || 0;

  document.getElementById('statTotal').textContent =
    t('stat_jobs_summary').replace('{total}', total).replace('{running}', running);

  const rate = data.success_rate;
  const el = document.getElementById('statSuccess');
  if (rate != null) {
    const pct = (rate * 100).toFixed(1);
    el.textContent = t('stat_success').replace('{pct}', pct);
    el.style.color = rate >= 0.8 ? '' : 'var(--danger, #ef4444)';
  } else {
    el.textContent = '-';
  }

  const avg = data.duration?.avg_ms;
  if (avg != null) {
    const sec = avg / 1000;
    document.getElementById('statDuration').textContent =
      sec >= 60 ? `avg ${(sec / 60).toFixed(1)}m` : `avg ${sec.toFixed(1)}s`;
  } else {
    document.getElementById('statDuration').textContent = '-';
  }
}

function toggleJobListCollapse() {
  _jobListCollapsed = !_jobListCollapsed;
  localStorage.setItem('jobListCollapsed', _jobListCollapsed ? '1' : '0');
  _applyJobListCollapse();
}

function _applyJobListCollapse() {
  const wrap = document.getElementById('jobTableWrap');
  const filterBar = document.getElementById('jobFilterBar');
  const strip = document.getElementById('projectStrip');
  const statsBar = document.getElementById('statsBar');
  const detail = document.getElementById('projectDetail');
  const btn = document.getElementById('btnCollapseJobs');
  if (wrap) wrap.style.display = _jobListCollapsed ? 'none' : '';
  if (filterBar) filterBar.style.display = _jobListCollapsed ? 'none' : '';
  if (strip) strip.style.display = _jobListCollapsed ? 'none' : '';
  if (statsBar) statsBar.style.display = _jobListCollapsed ? 'none' : '';
  if (detail) detail.style.display = _jobListCollapsed ? 'none' : (_selectedProject ? '' : 'none');
  if (btn) btn.classList.toggle('collapsed', _jobListCollapsed);
}

function setJobFilter(status) {
  _jobFilterStatus = status;
  document.querySelectorAll('.job-filter-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.filter === status);
  });
  applyJobFilters();
}

function applyJobFilters() {
  _jobSearchQuery = (document.getElementById('jobSearchInput')?.value || '').toLowerCase().trim();
  _forceFullRender = true;
  renderJobs(_allJobs);
}

function setJobProjectFilter(project) {
  _jobFilterProject = project;
  const sel = document.getElementById('jobProjectSelect');
  if (sel) sel.value = project;

  if (project === 'all') {
    _selectedProject = null;
    _selectedProjectInfo = null;
    _hideProjectDetail();
  } else {
    const projects = _extractProjects(_allJobs);
    _selectedProject = projects.find(p => p.name === project) || null;
    _selectedProjectInfo = null;
    _showProjectDetail();
    if (_selectedProject?.registered && _selectedProject.projectId) {
      _fetchProjectInfo(_selectedProject.projectId);
    }
  }

  applyJobFilters();
}

// 프로젝트 관련 함수 → job-projects.js로 분리됨


/* ── Grouped View ── */

function toggleJobViewMode() {
  _forceFullRender = true;
  renderJobs(_allJobs);
}

/** 프로젝트별 통계 계산 — duration, success rate */
// _calcProjectStats → job-projects.js로 분리됨


function _updateViewModeUI() {
  const btn = document.getElementById('btnViewMode');
  if (btn) btn.classList.add('active');
}

function toggleGroupCollapse(groupName) {
  _collapsedGroups[groupName] = !_collapsedGroups[groupName];
  localStorage.setItem('collapsedGroups', JSON.stringify(_collapsedGroups));
  _forceFullRender = true;
  renderJobs(_allJobs);
}

function goGroupPage(groupName, page) {
  _groupPages[groupName] = Math.max(1, page);
  _forceFullRender = true;
  renderJobs(_allJobs);
}

function _renderGroupedView(jobs, tbody) {
  jobs.sort((a, b) => {
    const aR = a.status === 'running' ? 0 : 1;
    const bR = b.status === 'running' ? 0 : 1;
    if (aR !== bR) return aR - bR;
    return (parseInt(b.id || b.job_id || 0)) - (parseInt(a.id || a.job_id || 0));
  });

  const groups = new Map();
  for (const job of jobs) {
    const name = _resolveProjectName(job.cwd);
    const key = (name && name !== '-') ? name : t('pd_other');
    if (!groups.has(key)) groups.set(key, { name: key, cwd: job.cwd, jobs: [] });
    groups.get(key).jobs.push(job);
  }

  const sorted = [...groups.values()].sort((a, b) => {
    const aR = a.jobs.some(j => j.status === 'running') ? 0 : 1;
    const bR = b.jobs.some(j => j.status === 'running') ? 0 : 1;
    if (aR !== bR) return aR - bR;
    return b.jobs.length - a.jobs.length;
  });

  // 프로젝트별 통계
  const pStats = _calcProjectStats(jobs);

  // 포커스·expand row 보존
  const activeEl = document.activeElement;
  const focusId = activeEl?.classList.contains('followup-input') ? activeEl.id : null;
  const focusVal = focusId ? activeEl.value : null;
  const focusCur = focusId ? activeEl.selectionStart : null;

  const savedExpands = new Map();
  for (const tr of [...tbody.querySelectorAll('tr.expand-row')]) {
    savedExpands.set(tr.dataset.jobId, tr);
    tr.remove();
  }

  tbody.innerHTML = '';

  if (sorted.length === 0) {
    tbody.innerHTML = `<tr data-job-id="__empty__"><td colspan="6" class="empty-state">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:40px;height:40px;margin-bottom:12px;opacity:0.3;"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
      <div>${t('no_jobs')}</div></td></tr>`;
    document.getElementById('btnDeleteCompleted').style.display = 'none';
    return;
  }

  let hasCompleted = false;

  for (const group of sorted) {
    const collapsed = !!_collapsedGroups[group.name];
    const running = group.jobs.filter(j => j.status === 'running').length;
    const done = group.jobs.filter(j => j.status === 'done').length;
    const failed = group.jobs.filter(j => j.status === 'failed').length;
    if (done > 0 || failed > 0) hasCompleted = true;

    let statsHtml = '';
    if (running > 0) statsHtml += `<span class="grp-stat grp-stat-running"><span class="grp-dot"></span>${running}</span>`;
    if (done > 0) statsHtml += `<span class="grp-stat grp-stat-done">${done}</span>`;
    if (failed > 0) statsHtml += `<span class="grp-stat grp-stat-failed">${failed}</span>`;

    // 프로젝트별 메트릭 (소요시간, 성공률)
    const ps = pStats[group.name] || {};
    let metaHtml = '';
    if (ps.durCount > 0) {
      const avg = ps.duration / ps.durCount / 1000;
      metaHtml += `<span class="grp-meta grp-meta-dur">avg ${avg < 60 ? avg.toFixed(1) + 's' : (avg / 60).toFixed(1) + 'm'}</span>`;
    }
    const completed = ps.done + ps.failed;
    if (completed > 0) {
      const rate = Math.round((ps.done / completed) * 100);
      const rateClass = rate >= 80 ? 'grp-meta-rate-ok' : 'grp-meta-rate-warn';
      metaHtml += `<span class="grp-meta ${rateClass}">${rate}%</span>`;
    }

    const hdr = document.createElement('tr');
    hdr.className = 'job-group-row';
    hdr.dataset.jobId = `__group__${group.name}`;
    hdr.setAttribute('onclick', `toggleGroupCollapse('${escapeJsStr(group.name)}')`);
    hdr.innerHTML = `<td colspan="6" class="job-group-cell"><div class="job-group-content">
      <svg class="job-group-chevron${collapsed ? ' collapsed' : ''}" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
      <svg class="job-group-folder" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
      <span class="job-group-name">${escapeHtml(group.name)}</span>
      <span class="job-group-count">${group.jobs.length}</span>
      <div class="job-group-stats">${statsHtml}</div>
      ${metaHtml ? `<div class="job-group-meta">${metaHtml}</div>` : ''}
    </div></td>`;
    tbody.appendChild(hdr);

    if (collapsed) continue;

    // 그룹별 페이지네이션: 5개씩
    const gTotal = group.jobs.length;
    const gPages = Math.ceil(gTotal / _GROUP_PAGE_SIZE);
    const gPage = Math.min(_groupPages[group.name] || 1, gPages);
    const gStart = (gPage - 1) * _GROUP_PAGE_SIZE;
    const gEnd = Math.min(gStart + _GROUP_PAGE_SIZE, gTotal);
    const pageJobs = group.jobs.slice(gStart, gEnd);

    for (const job of pageJobs) {
      const id = job.id || job.job_id || '-';
      const isExpanded = expandedJobId === id;
      if (streamState[id]) streamState[id].jobData = job;

      const tr = document.createElement('tr');
      tr.dataset.jobId = id;
      tr.className = `job-group-item${isExpanded ? ' expanded' : ''}`;
      tr.setAttribute('onclick', `toggleJobExpand('${escapeHtml(id)}')`);
      tr.innerHTML = _buildJobRowCells(id, job);
      tbody.appendChild(tr);

      if (isExpanded) {
        const eKey = id + '__expand';
        if (savedExpands.has(eKey)) {
          tbody.appendChild(savedExpands.get(eKey));
          savedExpands.delete(eKey);
          if (job.session_id) {
            const panel = document.getElementById(`streamPanel-${id}`);
            if (panel) panel.dataset.sessionId = job.session_id;
          }
        } else {
          const eTr = document.createElement('tr');
          eTr.className = 'expand-row';
          eTr.dataset.jobId = eKey;
          eTr.innerHTML = _buildExpandRowHtml(id, job);
          tbody.appendChild(eTr);
          initStream(id, job);
        }
      }

      if (job.status === 'running' && !isExpanded) {
        if (!streamState[id]) {
          streamState[id] = { offset: 0, timer: null, done: false, jobData: job, events: [], renderedCount: 0, _initTime: Date.now(), _lastEventTime: Date.now() };
        }
        if (!streamState[id].timer) initStream(id, job);
        const pvTr = document.createElement('tr');
        pvTr.className = 'preview-row';
        pvTr.dataset.jobId = id + '__preview';
        pvTr.innerHTML = `<td colspan="6"><div class="job-preview" id="jobPreview-${escapeHtml(id)}"><span class="preview-text">${escapeHtml(t('stream_preview_wait'))}</span></div></td>`;
        tbody.appendChild(pvTr);
        updateJobPreview(id);
      }
    }

    // 그룹 내 페이지네이션 (6개 이상일 때만)
    if (gPages > 1) {
      const pgTr = document.createElement('tr');
      pgTr.className = 'grp-pg-row';
      pgTr.dataset.jobId = `__grppg__${group.name}`;
      let pgHtml = '<td colspan="6"><div class="grp-pagination">';
      pgHtml += `<button class="pg-btn pg-btn-sm" ${gPage > 1 ? '' : 'disabled'} onclick="event.stopPropagation();goGroupPage('${escapeJsStr(group.name)}',${gPage - 1})">&lsaquo;</button>`;
      pgHtml += `<span class="grp-pg-info">${gStart + 1}–${gEnd} / ${gTotal}</span>`;
      pgHtml += `<button class="pg-btn pg-btn-sm" ${gPage < gPages ? '' : 'disabled'} onclick="event.stopPropagation();goGroupPage('${escapeJsStr(group.name)}',${gPage + 1})">&rsaquo;</button>`;
      pgHtml += '</div></td>';
      pgTr.innerHTML = pgHtml;
      tbody.appendChild(pgTr);
    }
  }

  document.getElementById('btnDeleteCompleted').style.display = hasCompleted ? 'inline-flex' : 'none';

  // 포커스 복원
  if (focusId) {
    const el = document.getElementById(focusId);
    if (el) { el.value = focusVal || ''; el.focus(); if (focusCur !== null) el.setSelectionRange(focusCur, focusCur); }
  }
}

function filterJobs(jobs) {
  return jobs.filter(job => {
    if (_jobFilterStatus !== 'all' && job.status !== _jobFilterStatus) return false;
    if (_jobFilterProject !== 'all' && _resolveProjectName(job.cwd) !== _jobFilterProject) return false;
    if (_jobSearchQuery && !(job.prompt || '').toLowerCase().includes(_jobSearchQuery)) return false;
    return true;
  });
}

// statusBadgeHtml, isZombieJob, jobActionsHtml, _buildJobRowCells, _buildExpandRowHtml → job-rendering.js

// quickForkSession, resumeFromJob, openFollowUp, sendFollowUp, retryJob → job-actions.js

// fetchJobs, _fetchJobsCore, goJobPage, _renderJobPagination, _buildPageRange → job-fetch.js

let _lastJobsFingerprint = '';
let _forceFullRender = false;

function _jobsFingerprint(jobs) {
  return jobs.map(j => `${j.id||j.job_id}:${j.status}`).join('|');
}

function renderJobs(jobs) {
  _allJobs = jobs;
  _updateProjectDropdown(jobs);
  _renderProjectStrip(jobs);
  if (_selectedProject) _showProjectDetail();
  const filtered = filterJobs(jobs);
  const tbody = document.getElementById('jobTableBody');
  const countEl = document.getElementById('jobCount');
  const totalCount = _jobTotal || jobs.length;
  const isFiltered = _jobFilterStatus !== 'all' || _jobFilterProject !== 'all' || _jobSearchQuery;
  countEl.textContent = totalCount > 0
    ? isFiltered ? `(${t('job_count_filtered').replace('{filtered}', filtered.length).replace('{total}', totalCount)})` : `(${t('job_count').replace('{n}', totalCount)})`
    : '';

  _updateViewModeUI();
  const thead = tbody.closest('table')?.querySelector('thead');
  if (thead) thead.style.display = 'none';

  const fp = _jobsFingerprint(filtered);

  // 1) 변화 없음 → 렌더 건너뜀
  if (!_forceFullRender && fp === _lastJobsFingerprint) {
    return;
  }

  // 2) 구조 동일, 상태만 변경 → 뱃지만 교체
  const oldIds = _lastJobsFingerprint.split('|').map(s => s.split(':')[0]).filter(Boolean);
  const newIds = fp.split('|').map(s => s.split(':')[0]).filter(Boolean);
  const sameStructure = !_forceFullRender
    && oldIds.length === newIds.length
    && oldIds.length > 0
    && oldIds.every((id, i) => id === newIds[i]);

  if (sameStructure) {
    for (const job of filtered) {
      updateJobRowStatus(job.id || job.job_id, job.status);
    }
    _lastJobsFingerprint = fp;
    return;
  }

  // 3) 구조 변경 → 전체 재렌더
  _forceFullRender = false;
  _lastJobsFingerprint = fp;
  _renderGroupedView(filtered, tbody);
}

function updateJobRowStatus(jobId, status) {
  const tbody = document.getElementById('jobTableBody');
  const row = tbody.querySelector(`tr[data-job-id="${CSS.escape(jobId)}"]`);
  if (!row || row.classList.contains('expand-row')) return;
  const cells = row.querySelectorAll('td');
  if (cells.length >= 2) {
    const job = _allJobs.find(j => String(j.id || j.job_id) === String(jobId));
    const newBadge = statusBadgeHtml(status, jobId, job);
    if (cells[1].innerHTML !== newBadge) cells[1].innerHTML = newBadge;
  }
  // running → done/failed: preview row 제거
  if (status !== 'running') {
    const pvRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(jobId + '__preview')}"]`);
    if (pvRow) pvRow.remove();
  }
  // 그룹 헤더 통계 업데이트
  _updateGroupStats();
}

function _updateGroupStats() {
  const tbody = document.getElementById('jobTableBody');
  if (!tbody) return;
  const filtered = filterJobs(_allJobs);
  const groups = new Map();
  for (const job of filtered) {
    const name = _resolveProjectName(job.cwd);
    const key = (name && name !== '-') ? name : t('pd_other');
    if (!groups.has(key)) groups.set(key, { running: 0, done: 0, failed: 0 });
    const g = groups.get(key);
    if (job.status === 'running') g.running++;
    else if (job.status === 'done') g.done++;
    else if (job.status === 'failed') g.failed++;
  }
  for (const [name, counts] of groups) {
    const hdr = tbody.querySelector(`tr[data-job-id="${CSS.escape('__group__' + name)}"]`);
    if (!hdr) continue;
    const statsEl = hdr.querySelector('.job-group-stats');
    if (!statsEl) continue;
    let html = '';
    if (counts.running > 0) html += `<span class="grp-stat grp-stat-running"><span class="grp-dot"></span>${counts.running}</span>`;
    if (counts.done > 0) html += `<span class="grp-stat grp-stat-done">${counts.done}</span>`;
    if (counts.failed > 0) html += `<span class="grp-stat grp-stat-failed">${counts.failed}</span>`;
    if (statsEl.innerHTML !== html) statsEl.innerHTML = html;
  }
}

function toggleJobExpand(id) {
  const tbody = document.getElementById('jobTableBody');
  if (expandedJobId === id) {
    // running 작업인지 확인 — running이면 스트림 유지, 아니면 중지
    const state = streamState[id];
    const isRunning = state && state.jobData && state.jobData.status === 'running';
    if (!isRunning) stopStream(id);

    const expandRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id + '__expand')}"]`);
    if (expandRow) expandRow.remove();
    const jobRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id)}"]`);
    if (jobRow) jobRow.classList.remove('expanded');
    expandedJobId = null;

    // running 작업이면 preview 행 복원
    if (isRunning && jobRow) {
      const pvTr = document.createElement('tr');
      pvTr.className = 'preview-row';
      pvTr.dataset.jobId = id + '__preview';
      pvTr.innerHTML = `<td colspan="6"><div class="job-preview" id="jobPreview-${escapeHtml(id)}"><span class="preview-text">${escapeHtml(t('stream_preview_wait'))}</span></div></td>`;
      jobRow.after(pvTr);
      updateJobPreview(id);
    }
  } else {
    if (expandedJobId) {
      const prevState = streamState[expandedJobId];
      const prevRunning = prevState && prevState.jobData && prevState.jobData.status === 'running';
      if (!prevRunning) stopStream(expandedJobId);

      const prevExpand = tbody.querySelector(`tr[data-job-id="${CSS.escape(expandedJobId + '__expand')}"]`);
      if (prevExpand) prevExpand.remove();
      const prevRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(expandedJobId)}"]`);
      if (prevRow) prevRow.classList.remove('expanded');

      // 이전 running 작업의 preview 행 복원
      if (prevRunning && prevRow) {
        const pvTr = document.createElement('tr');
        pvTr.className = 'preview-row';
        pvTr.dataset.jobId = expandedJobId + '__preview';
        pvTr.innerHTML = `<td colspan="6"><div class="job-preview" id="jobPreview-${escapeHtml(expandedJobId)}"><span class="preview-text">${escapeHtml(t('stream_preview_wait'))}</span></div></td>`;
        prevRow.after(pvTr);
        updateJobPreview(expandedJobId);
      }
    }
    expandedJobId = id;
    _forceFullRender = true;
    renderJobs(_allJobs);
  }
}

async function deleteJob(jobId) {
  if (!confirm(t('confirm_delete_job'))) return;
  try {
    await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}`, { method: 'DELETE' });
    if (streamState[jobId]) {
      stopStream(jobId);
      delete streamState[jobId];
    }
    if (expandedJobId === jobId) expandedJobId = null;
    showToast(t('msg_job_deleted'));
    fetchJobs();
  } catch (err) {
    showToast(`${t('msg_delete_failed')}: ${err.message}`, 'error');
  }
}

async function deleteCompletedJobs() {
  if (!confirm(t('confirm_delete_completed'))) return;
  try {
    const data = await apiFetch('/api/jobs', { method: 'DELETE' });
    const count = data.count || 0;
    for (const id of (data.deleted || [])) {
      if (streamState[id]) {
        stopStream(id);
        delete streamState[id];
      }
      if (expandedJobId === id) expandedJobId = null;
    }
    showToast(count + t('msg_batch_deleted'));
    fetchJobs();
  } catch (err) {
    showToast(`${t('msg_batch_delete_failed')}: ${err.message}`, 'error');
  }
}

