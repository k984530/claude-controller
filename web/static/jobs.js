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
let _jobViewMode = localStorage.getItem('jobViewMode') || 'flat';
let _jobViewModeManual = localStorage.getItem('jobViewModeManual') === '1'; // 사용자가 수동 전환한 적 있는지
let _collapsedGroups = JSON.parse(localStorage.getItem('collapsedGroups') || '{}');
let _statsPeriod = 'all';
let _selectedProject = null;
let _selectedProjectInfo = null;
let _jobPage = 1;
let _jobLimit = 10;
let _jobPages = 1;
let _jobTotal = 0;

/* ── Stats ── */

function setStatsPeriod(period) {
  _statsPeriod = period;
  document.querySelectorAll('.stats-period-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.period === period);
  });
  fetchStats();
}

async function fetchStats() {
  try {
    const data = await apiFetch(`/api/stats?period=${_statsPeriod}`);
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

function _extractProjects(jobs) {
  const map = {};

  // 1) 등록된 프로젝트를 먼저 삽입 (이름·경로 우��� 사용)
  for (const rp of _registeredProjects) {
    const name = rp.name || formatCwd(rp.path);
    const js = rp.job_stats || {};
    map[name] = {
      name,
      cwd: rp.path,
      projectId: rp.id,
      registered: true,
      count: js.total || 0,
      running: js.running || 0,
    };
  }

  // 2) job cwd에서 추출한 프로젝트 병합 — 등록 프로젝트와 경로가 같으면 통합
  for (const job of jobs) {
    const cwdName = formatCwd(job.cwd);
    if (!cwdName || cwdName === '-') continue;

    // 등록 프로젝트 중 같은 경로인지 확인
    const matchKey = Object.keys(map).find(k => {
      const mp = map[k];
      return mp.cwd && job.cwd && _normPath(mp.cwd) === _normPath(job.cwd);
    });

    if (matchKey) {
      // 등록 프로젝트와 매칭 — job 단위 카운트는 이미 job_stats에 있으므로 skip
      continue;
    }

    // 등록되지 않은 ad-hoc 프로젝트
    if (!map[cwdName]) map[cwdName] = { name: cwdName, cwd: job.cwd, count: 0, running: 0, registered: false };
    map[cwdName].count++;
    if (job.status === 'running') map[cwdName].running++;
  }

  // 등록 프로젝트 우선, 그 안에서 count 역순
  return Object.values(map).sort((a, b) => {
    if (a.registered !== b.registered) return a.registered ? -1 : 1;
    return b.count - a.count;
  });
}

function _normPath(p) {
  if (!p) return '';
  return p.replace(/\/+$/, '');
}

function _updateProjectDropdown(jobs) {
  const sel = document.getElementById('jobProjectSelect');
  if (!sel) return;
  const projects = _extractProjects(jobs);
  const prev = sel.value;
  sel.innerHTML = `<option value="all">${t('all_projects')} (${jobs.length})</option>`;
  for (const p of projects) {
    const label = p.name + ` (${p.count})`;
    sel.innerHTML += `<option value="${escapeHtml(p.name)}">${escapeHtml(label)}</option>`;
  }
  sel.value = (prev && projects.some(p => p.name === prev)) ? prev : 'all';
  _jobFilterProject = sel.value;
}

function _renderProjectStrip(jobs) {
  const container = document.getElementById('projectStrip');
  if (!container) return;
  if (_jobListCollapsed) { container.style.display = 'none'; return; }

  const projects = _extractProjects(jobs);
  const dropdown = document.querySelector('.job-project-filter');

  // 등록 프로젝트가 있으면 항상 스트립 표시
  const hasRegistered = _registeredProjects.length > 0;
  if (projects.length <= 1 && !hasRegistered) {
    container.style.display = 'none';
    if (dropdown) dropdown.style.display = projects.length > 0 ? 'flex' : 'none';
    return;
  }
  container.style.display = '';
  if (dropdown) dropdown.style.display = 'none';

  // 프로젝트별 상태 카운트 (job 데이터에서 실시간 집계)
  const sc = {};
  for (const job of jobs) {
    const name = _resolveProjectName(job.cwd);
    if (!sc[name]) sc[name] = { running: 0, done: 0, failed: 0 };
    const s = job.status;
    if (s === 'running') sc[name].running++;
    else if (s === 'done') sc[name].done++;
    else if (s === 'failed') sc[name].failed++;
  }

  let html = `<button class="project-chip${_jobFilterProject === 'all' ? ' active' : ''}" onclick="setJobProjectFilter('all')">
    <svg class="pchip-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/></svg>
    <span class="pchip-name">${t('all_projects')}</span>
    <span class="pchip-count">${jobs.length}</span>
  </button>`;

  for (const p of projects) {
    const active = _jobFilterProject === p.name ? ' active' : '';
    const dot = p.running > 0 ? '<span class="pchip-dot"></span>' : '';
    const s = sc[p.name] || {};
    let stats = '';
    if (s.running > 0) stats += `<span class="pchip-stat pchip-stat-running">${s.running}</span>`;
    if (s.done > 0) stats += `<span class="pchip-stat pchip-stat-done">${s.done}</span>`;
    if (s.failed > 0) stats += `<span class="pchip-stat pchip-stat-failed">${s.failed}</span>`;

    const regBadge = p.registered ? '<span class="pchip-reg"></span>' : '';

    html += `<button class="project-chip${active}${p.registered ? ' registered' : ''}" onclick="setJobProjectFilter('${escapeHtml(escapeJsStr(p.name))}')" title="${escapeHtml(p.cwd)}">
      ${dot}${regBadge}
      <svg class="pchip-icon" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
      <span class="pchip-name">${escapeHtml(p.name)}</span>
      <span class="pchip-count">${p.count}</span>
      ${stats}
    </button>`;
  }

  container.innerHTML = html;
}

/** job의 cwd를 등록 프로젝트 이름으로 resolve한다. 매칭 실패 시 formatCwd 사용. */
function _resolveProjectName(cwd) {
  if (!cwd) return '-';
  const norm = _normPath(cwd);
  for (const rp of _registeredProjects) {
    if (_normPath(rp.path) === norm) return rp.name || formatCwd(rp.path);
  }
  return formatCwd(cwd);
}

/* ── Project Detail Panel ── */

async function _fetchProjectInfo(projectId) {
  try {
    const data = await apiFetch(`/api/projects/${projectId}`);
    _selectedProjectInfo = data;
    _showProjectDetail();
  } catch { /* silent */ }
}

function _showProjectDetail() {
  const container = document.getElementById('projectDetail');
  if (!container || !_selectedProject) { _hideProjectDetail(); return; }

  const projectJobs = _allJobs.filter(j => _resolveProjectName(j.cwd) === _selectedProject.name);

  let running = 0, done = 0, failed = 0, totalDuration = 0, durCount = 0;
  for (const j of projectJobs) {
    if (j.status === 'running') running++;
    else if (j.status === 'done') done++;
    else if (j.status === 'failed') failed++;
    if (j.duration_ms != null) { totalDuration += j.duration_ms; durCount++; }
  }

  const completed = done + failed;
  const successRate = completed > 0 ? Math.round((done / completed) * 100) : null;
  const avgDuration = durCount > 0 ? totalDuration / durCount / 1000 : null;

  const info = _selectedProjectInfo;
  const metaItems = [];
  if (_selectedProject.cwd) metaItems.push(`<span class="pd-path-text">${escapeHtml(_selectedProject.cwd)}</span>`);
  if (info?.branch) metaItems.push(`<span class="pd-branch">${escapeHtml(info.branch)}</span>`);
  if (info?.remote) {
    const remote = info.remote.replace(/\.git$/, '').replace(/^https?:\/\//, '').replace(/^git@([^:]+):/, '$1/');
    metaItems.push(`<span class="pd-remote" title="${escapeHtml(info.remote)}">${escapeHtml(remote)}</span>`);
  }

  let statsHtml = `<div class="pd-stat"><div class="pd-stat-val">${projectJobs.length}</div><div class="pd-stat-label">${escapeHtml(t('pd_total'))}</div></div>`;
  if (running > 0) statsHtml += `<div class="pd-stat pd-running"><div class="pd-stat-val">${running}</div><div class="pd-stat-label">${escapeHtml(t('pd_running'))}</div></div>`;
  statsHtml += `<div class="pd-stat pd-done"><div class="pd-stat-val">${done}</div><div class="pd-stat-label">${escapeHtml(t('pd_done'))}</div></div>`;
  if (failed > 0) statsHtml += `<div class="pd-stat pd-failed"><div class="pd-stat-val">${failed}</div><div class="pd-stat-label">${escapeHtml(t('pd_failed'))}</div></div>`;
  if (avgDuration != null) {
    const durStr = avgDuration < 60 ? `${avgDuration.toFixed(1)}s` : `${(avgDuration / 60).toFixed(1)}m`;
    statsHtml += `<div class="pd-stat"><div class="pd-stat-val">${durStr}</div><div class="pd-stat-label">${escapeHtml(t('pd_avg'))}</div></div>`;
  }
  if (successRate != null) {
    const rateClass = successRate >= 80 ? 'pd-rate-ok' : 'pd-rate-warn';
    statsHtml += `<div class="pd-stat ${rateClass}"><div class="pd-stat-val">${successRate}%</div><div class="pd-stat-label">${escapeHtml(t('pd_success_rate'))}</div></div>`;
  }

  const regBadge = _selectedProject.registered ? `<span class="pd-badge">${escapeHtml(t('pd_registered'))}</span>` : '';
  const cwdAttr = escapeHtml(escapeJsStr(_selectedProject.cwd || ''));

  container.innerHTML = `
    <div class="pd-header">
      <div class="pd-title-row">
        <svg class="pd-icon" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>
        <span class="pd-name">${escapeHtml(_selectedProject.name)}</span>
        ${regBadge}
        <div class="pd-actions">
          <button class="btn btn-sm btn-primary" onclick="sendTaskToProject('${cwdAttr}')" title="${escapeHtml(t('pd_send_task_title'))}">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            ${escapeHtml(t('pd_send_task'))}
          </button>
          <button class="pd-close" onclick="setJobProjectFilter('all')" title="${escapeHtml(t('pd_show_all_title'))}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>
      ${metaItems.length ? `<div class="pd-meta">${metaItems.join(' <span class="pd-sep">\u00b7</span> ')}</div>` : ''}
    </div>
    <div class="pd-stats">${statsHtml}</div>
  `;
  container.style.display = '';
}

function _hideProjectDetail() {
  const container = document.getElementById('projectDetail');
  if (container) { container.style.display = 'none'; container.innerHTML = ''; }
}

function sendTaskToProject(cwd) {
  if (cwd) {
    addRecentDir(cwd);
    selectRecentDir(cwd, true);
  }
  document.getElementById('promptInput')?.focus();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

/* ── Grouped View ── */

function toggleJobViewMode() {
  _jobViewMode = _jobViewMode === 'flat' ? 'grouped' : 'flat';
  _jobViewModeManual = true;
  localStorage.setItem('jobViewMode', _jobViewMode);
  localStorage.setItem('jobViewModeManual', '1');
  renderJobs(_allJobs);
}

/** 프로젝트별 통계 계산 — duration, success rate */
function _calcProjectStats(jobs) {
  const stats = {};
  for (const job of jobs) {
    const name = _resolveProjectName(job.cwd);
    const key = (name && name !== '-') ? name : t('pd_other');
    if (!stats[key]) stats[key] = { duration: 0, done: 0, failed: 0, durCount: 0 };
    const s = stats[key];
    if (job.duration_ms != null) { s.duration += job.duration_ms; s.durCount++; }
    if (job.status === 'done') s.done++;
    if (job.status === 'failed') s.failed++;
  }
  return stats;
}

function _updateViewModeUI() {
  const btn = document.getElementById('btnViewMode');
  if (btn) btn.classList.toggle('active', _jobViewMode === 'grouped');
}

function toggleGroupCollapse(groupName) {
  _collapsedGroups[groupName] = !_collapsedGroups[groupName];
  localStorage.setItem('collapsedGroups', JSON.stringify(_collapsedGroups));
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

    for (const job of group.jobs) {
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

const ZOMBIE_THRESHOLD_MS = 5 * 60 * 1000; // 5분간 스트림 데이터 없으면 좀비 의심

function statusBadgeHtml(status, jobId, job) {
  const s = (status || 'unknown').toLowerCase();
  const labels = { running: t('status_running'), done: t('status_done'), failed: t('status_failed'), pending: t('status_pending') };
  const cls = { running: 'badge-running', done: 'badge-done', failed: 'badge-failed', pending: 'badge-pending' };
  let badge = `<span class="badge ${cls[s] || 'badge-pending'}">${labels[s] || s}</span>`;
  if (s === 'running' && jobId && isZombieJob(jobId)) {
    badge += ` <span class="badge badge-zombie" title="${escapeHtml(t('job_zombie_title'))}">${escapeHtml(t('job_zombie'))}</span>`;
  }
  if (job && (s === 'done' || s === 'failed') && job.duration_ms != null) {
    const info = formatDuration(job.duration_ms);
    if (info) badge += `<span class="job-meta-info">${escapeHtml(info)}</span>`;
  }
  // 의존성 뱃지
  if (job && job.depends_on && job.depends_on.length > 0) {
    const depIds = job.depends_on.map(d => '#' + d).join(', ');
    badge += ` <span class="badge badge-dep" title="${escapeHtml(t('job_dep_title').replace('{deps}', depIds))}">⛓ ${escapeHtml(depIds)}</span>`;
  }
  return badge;
}

function isZombieJob(jobId) {
  const state = streamState[jobId];
  if (!state) return false;
  const lastEventTime = state._lastEventTime || state._initTime;
  if (!lastEventTime) return false;
  return (Date.now() - lastEventTime) > ZOMBIE_THRESHOLD_MS;
}

function jobActionsHtml(id, status, sessionId, cwd) {
  const isRunning = status === 'running';
  const escapedCwd = escapeHtml(escapeJsStr(cwd || ''));
  let btns = '';
  if (!isRunning) {
    btns += `<button class="btn-retry-job" onclick="event.stopPropagation(); retryJob('${escapeHtml(id)}')" title="${escapeHtml(t('job_retry_title'))}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></button>`;
  }
  if (sessionId) {
    btns += `<button class="btn-continue-job" onclick="event.stopPropagation(); openFollowUp('${escapeHtml(id)}')" title="${escapeHtml(t('job_resume_title'))}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="13 17 18 12 13 7"/><polyline points="6 17 11 12 6 7"/></svg></button>`;
    btns += `<button class="btn-fork-job" onclick="event.stopPropagation(); quickForkSession('${escapeHtml(sessionId)}', '${escapedCwd}')" title="${escapeHtml(t('job_fork_title'))}" style="color:var(--yellow);"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><path d="M6 9v3c0 3.3 2.7 6 6 6h3"/></svg></button>`;
  }
  if (!isRunning) {
    btns += `<button class="btn-delete-job" onclick="event.stopPropagation(); deleteJob('${escapeHtml(id)}')" title="${escapeHtml(t('job_delete_title'))}"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>`;
  }
  if (!btns) return '';
  return `<div style="display:flex; align-items:center; gap:4px;">${btns}</div>`;
}

/** job row의 6개 셀 HTML을 생성한다 — flat/grouped 뷰 공용. */
function _buildJobRowCells(id, job) {
  return `
    <td class="job-id">${escapeHtml(String(id).slice(0, 8))}</td>
    <td>${statusBadgeHtml(job.status, id, job)}</td>
    <td class="prompt-cell" title="${escapeHtml(job.prompt)}">${renderPromptHtml(job.prompt)}</td>
    <td class="job-cwd" title="${escapeHtml(job.cwd || '')}">${escapeHtml(formatCwd(job.cwd))}</td>
    <td class="job-session${job.session_id ? ' clickable' : ''}" title="${escapeHtml(job.session_id || '')}" ${job.session_id ? `onclick="event.stopPropagation(); resumeFromJob('${escapeHtml(escapeJsStr(job.session_id))}', '${escapeHtml(escapeJsStr(truncate(job.prompt, 40)))}', '${escapeHtml(escapeJsStr(job.cwd || ''))}')"` : ''}>${job.session_id ? escapeHtml(job.session_id.slice(0, 8)) : (job.status === 'running' ? '<span style="color:var(--text-muted);font-size:0.7rem;">—</span>' : '-')}</td>
    <td>${jobActionsHtml(id, job.status, job.session_id, job.cwd)}</td>`;
}

/** expand row의 inner HTML을 생성한다 — flat/grouped 뷰 공용. */
function _buildExpandRowHtml(id, job) {
  const sessionId = job.session_id || '';
  const jobCwd = job.cwd || '';
  const eid = escapeHtml(id);

  let actionsHtml = '';
  if (job.status !== 'running') {
    actionsHtml = `<div class="stream-actions">
      <button class="btn btn-sm" onclick="event.stopPropagation(); retryJob('${eid}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> ${escapeHtml(t('job_retry'))}</button>
      <button class="btn btn-sm" onclick="event.stopPropagation(); copyStreamResult('${eid}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> ${escapeHtml(t('stream_copy_all'))}</button>
      <button class="btn btn-sm" onclick="event.stopPropagation(); toggleCheckpointPanel('${eid}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 20V10"/><path d="M18 20V4"/><path d="M6 20v-4"/></svg> ${escapeHtml(t('checkpoints'))}</button>
      <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteJob('${eid}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg> ${escapeHtml(t('stream_delete_job'))}</button>
    </div>`;
  }

  let followupHtml = '';
  if (job.status !== 'running' && sessionId) {
    followupHtml = `<div class="stream-followup">
      <span class="stream-followup-label">${escapeHtml(t('stream_followup_label'))}</span>
      <div class="followup-input-wrap">
        <input type="text" class="followup-input" id="followupInput-${eid}" placeholder="${escapeHtml(t('stream_followup_placeholder'))}" onkeydown="if(event.key==='Enter'){event.stopPropagation();sendFollowUp('${eid}')}" onclick="event.stopPropagation()">
        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); sendFollowUp('${eid}')" style="white-space:nowrap;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> ${escapeHtml(t('send'))}</button>
      </div>
    </div>`;
  }

  return `<td colspan="6">
    <div class="stream-panel" id="streamPanel-${eid}" data-session-id="${escapeHtml(sessionId)}" data-cwd="${escapeHtml(jobCwd)}">
      <div class="stream-content" id="streamContent-${eid}">
        <div class="stream-empty">${escapeHtml(t('stream_loading'))}</div>
      </div>
      ${job.status === 'done' ? `<div class="stream-done-banner">✓ ${escapeHtml(t('stream_job_done'))}</div>` : ''}
      ${job.status === 'failed' ? `<div class="stream-done-banner failed">✗ ${escapeHtml(t('stream_job_failed'))}</div>` : ''}
      ${actionsHtml}
      ${followupHtml}
      <div id="ckptPanel-${eid}" class="ckpt-panel" style="display:none"></div>
    </div>
  </td>`;
}

function quickForkSession(sessionId, cwd) {
  _contextMode = 'fork';
  _contextSessionId = sessionId;
  _contextSessionPrompt = null;
  _updateContextUI();
  if (cwd) {
    addRecentDir(cwd);
    selectRecentDir(cwd, true);
  }
  showToast(t('msg_fork_mode') + ' (' + sessionId.slice(0, 8) + '...). ' + t('msg_fork_input'));
  document.getElementById('promptInput').focus();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function resumeFromJob(sessionId, promptHint, cwd) {
  _contextMode = 'resume';
  _contextSessionId = sessionId;
  _contextSessionPrompt = promptHint || null;
  _updateContextUI();
  if (cwd) {
    addRecentDir(cwd);
    selectRecentDir(cwd, true);
  }
  showToast(t('msg_resume_mode').replace('{sid}', sessionId.slice(0, 8) + '...'));
  document.getElementById('promptInput').focus();
  window.scrollTo({ top: 0, behavior: 'smooth' });
}

function openFollowUp(jobId) {
  if (expandedJobId !== jobId) {
    toggleJobExpand(jobId);
    setTimeout(() => focusFollowUpInput(jobId), 200);
  } else {
    focusFollowUpInput(jobId);
  }
}

function focusFollowUpInput(jobId) {
  const input = document.getElementById(`followupInput-${jobId}`);
  if (input) {
    input.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    input.focus();
  }
}

const followUpAttachments = {};

async function handleFollowUpFiles(jobId, files) {
  if (!followUpAttachments[jobId]) followUpAttachments[jobId] = [];
  const container = document.getElementById(`followupPreviews-${jobId}`);
  for (const file of files) {
    try {
      const data = await uploadFile(file);
      followUpAttachments[jobId].push({ serverPath: data.path, filename: data.filename || file.name });
      if (container) {
        const chip = document.createElement('span');
        chip.className = 'followup-file-chip';
        chip.textContent = data.filename || file.name;
        chip.title = data.path;
        container.appendChild(chip);
      }
      const input = document.getElementById(`followupInput-${jobId}`);
      if (input) {
        const space = input.value.length > 0 && !input.value.endsWith(' ') ? ' ' : '';
        input.value += space + '@' + data.path + ' ';
        input.focus();
      }
    } catch (err) {
      showToast(`${t('msg_upload_failed')}: ${file.name}`, 'error');
    }
  }
}

async function sendFollowUp(jobId) {
  if (_sendLock) return;

  const input = document.getElementById(`followupInput-${jobId}`);
  if (!input) return;
  const prompt = input.value.trim();
  if (!prompt) {
    showToast(t('msg_continue_input'), 'error');
    return;
  }

  const panel = document.getElementById(`streamPanel-${jobId}`);
  const sessionId = panel ? panel.dataset.sessionId : '';
  const cwd = panel ? panel.dataset.cwd : '';

  if (!sessionId) {
    showToast(t('msg_no_session_id'), 'error');
    return;
  }

  _sendLock = true;
  const btn = input.parentElement.querySelector('.btn-primary');
  const origHtml = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner" style="width:12px;height:12px;"></span>';

  try {
    const images = (followUpAttachments[jobId] || []).map(a => a.serverPath);
    const body = { prompt, session: `resume:${sessionId}` };
    if (cwd) body.cwd = cwd;
    if (images.length > 0) body.images = images;

    await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
    showToast(t('msg_continue_sent'));
    input.value = '';
    delete followUpAttachments[jobId];
    const container = document.getElementById(`followupPreviews-${jobId}`);
    if (container) container.innerHTML = '';
    fetchJobs();
  } catch (err) {
    showToast(`${t('msg_send_failed')}: ${err.message}`, 'error');
  } finally {
    _sendLock = false;
    btn.disabled = false;
    btn.innerHTML = origHtml;
  }
}

async function retryJob(jobId) {
  if (_sendLock) return;

  const job = _allJobs.find(j => String(j.id || j.job_id) === String(jobId));
  if (!job || !job.prompt) {
    showToast(t('msg_no_original_prompt'), 'error');
    return;
  }

  _sendLock = true;
  try {
    const body = { prompt: job.prompt };
    if (job.cwd) body.cwd = job.cwd;

    await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
    showToast(t('msg_rerun_done'));
    fetchJobs();
  } catch (err) {
    showToast(`${t('msg_rerun_failed')}: ${err.message}`, 'error');
  } finally {
    _sendLock = false;
  }
}

let _fetchJobsTimer = null;
let _fetchJobsInFlight = false;

async function _fetchJobsCore() {
  if (_fetchJobsInFlight) return;
  _fetchJobsInFlight = true;
  try {
    const params = new URLSearchParams({ page: _jobPage, limit: _jobLimit });
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
  if (_jobPages <= 1) {
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

  // 프로젝트 2개 이상 + 사용자가 수동 전환한 적 없으면 자동 grouped
  if (!_jobViewModeManual) {
    const projectCount = _extractProjects(jobs).length;
    if (projectCount >= 2 && _jobViewMode !== 'grouped') {
      _jobViewMode = 'grouped';
      localStorage.setItem('jobViewMode', 'grouped');
    } else if (projectCount < 2 && _jobViewMode === 'grouped') {
      _jobViewMode = 'flat';
      localStorage.setItem('jobViewMode', 'flat');
    }
  }

  _updateViewModeUI();
  const thead = tbody.closest('table')?.querySelector('thead');
  if (_jobViewMode === 'grouped') {
    if (thead) thead.style.display = 'none';
    _renderGroupedView(filtered, tbody);
    return;
  }
  if (thead) thead.style.display = '';

  jobs = filtered;

  if (jobs.length === 0) {
    tbody.innerHTML = `<tr data-job-id="__empty__"><td colspan="6" class="empty-state">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" style="width:40px;height:40px;margin-bottom:12px;opacity:0.3;"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
      <div>${t('no_jobs')}</div>
    </td></tr>`;
    return;
  }

  jobs.sort((a, b) => {
    const aRunning = a.status === 'running' ? 0 : 1;
    const bRunning = b.status === 'running' ? 0 : 1;
    if (aRunning !== bRunning) return aRunning - bRunning;
    return (parseInt(b.id || b.job_id || 0)) - (parseInt(a.id || a.job_id || 0));
  });

  for (const job of jobs) {
    const id = job.id || job.job_id || '-';
    if (streamState[id]) {
      streamState[id].jobData = job;
    }
  }

  const existingRows = {};
  for (const row of tbody.querySelectorAll('tr[data-job-id]')) {
    existingRows[row.dataset.jobId] = row;
  }

  const newIds = [];
  for (const job of jobs) {
    const id = job.id || job.job_id || '-';
    newIds.push(id);
    if (expandedJobId === id) newIds.push(id + '__expand');
  }

  const emptyRow = tbody.querySelector('tr[data-job-id="__empty__"]');
  if (emptyRow) emptyRow.remove();

  for (const job of jobs) {
    const id = job.id || job.job_id || '-';
    const isExpanded = expandedJobId === id;
    const existing = existingRows[id];

    if (existing && !existing.classList.contains('expand-row')) {
      const cells = existing.querySelectorAll('td');
      if (cells.length >= 6) {
        const newStatus = statusBadgeHtml(job.status, id, job);
        if (cells[1].innerHTML !== newStatus) cells[1].innerHTML = newStatus;
        const newCwd = escapeHtml(formatCwd(job.cwd));
        if (cells[3].innerHTML !== newCwd) {
          cells[3].innerHTML = newCwd;
          cells[3].title = job.cwd || '';
        }
        const newSession = job.session_id ? job.session_id.slice(0, 8) : (job.status === 'running' ? '—' : '-');
        if (cells[4].textContent !== newSession) {
          cells[4].textContent = newSession;
          if (job.session_id) {
            cells[4].className = 'job-session clickable';
            cells[4].title = job.session_id;
            cells[4].setAttribute('onclick', `event.stopPropagation(); resumeFromJob('${escapeJsStr(job.session_id)}', '${escapeJsStr(truncate(job.prompt, 40))}', '${escapeJsStr(job.cwd || '')}')`);
          }
        }
        const newActions = jobActionsHtml(id, job.status, job.session_id, job.cwd);
        if (cells[5].innerHTML !== newActions) {
          cells[5].innerHTML = newActions;
        }
      }
      existing.className = isExpanded ? 'expanded' : '';
      delete existingRows[id];
    } else if (!existing) {
      const tr = document.createElement('tr');
      tr.dataset.jobId = id;
      tr.className = isExpanded ? 'expanded' : '';
      tr.setAttribute('onclick', `toggleJobExpand('${escapeHtml(id)}')`);
      tr.innerHTML = _buildJobRowCells(id, job);
      tbody.appendChild(tr);
    } else {
      delete existingRows[id];
    }

    const expandKey = id + '__expand';
    const existingExpand = existingRows[expandKey] || tbody.querySelector(`tr[data-job-id="${CSS.escape(expandKey)}"]`);

    if (isExpanded) {
      if (!existingExpand) {
        const expandTr = document.createElement('tr');
        expandTr.className = 'expand-row';
        expandTr.dataset.jobId = expandKey;
        expandTr.innerHTML = _buildExpandRowHtml(id, job);
        const jobRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id)}"]`);
        if (jobRow && jobRow.nextSibling) {
          tbody.insertBefore(expandTr, jobRow.nextSibling);
        } else {
          tbody.appendChild(expandTr);
        }
        initStream(id, job);
      } else {
        delete existingRows[expandKey];
      }
    } else if (existingExpand) {
      existingExpand.remove();
      delete existingRows[expandKey];
    }

    // 실행 중인 작업: 미리보기 행
    const previewKey = id + '__preview';
    const existingPreview = existingRows[previewKey] || tbody.querySelector(`tr[data-job-id="${CSS.escape(previewKey)}"]`);

    if (job.status === 'running' && !isExpanded) {
      if (!streamState[id]) {
        streamState[id] = { offset: 0, timer: null, done: false, jobData: job, events: [], renderedCount: 0 };
      }
      if (!streamState[id].timer) {
        initStream(id, job);
      }
      if (!existingPreview) {
        const pvTr = document.createElement('tr');
        pvTr.className = 'preview-row';
        pvTr.dataset.jobId = previewKey;
        pvTr.innerHTML = `<td colspan="6"><div class="job-preview" id="jobPreview-${escapeHtml(id)}"><span class="preview-text">${escapeHtml(t('stream_preview_wait'))}</span></div></td>`;
        const jobRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id)}"]`);
        if (jobRow && jobRow.nextSibling) {
          tbody.insertBefore(pvTr, jobRow.nextSibling);
        } else {
          tbody.appendChild(pvTr);
        }
        newIds.splice(newIds.indexOf(id) + 1, 0, previewKey);
      } else {
        delete existingRows[previewKey];
        newIds.splice(newIds.indexOf(id) + 1, 0, previewKey);
      }
      updateJobPreview(id);
    } else {
      if (existingPreview) {
        existingPreview.remove();
        delete existingRows[previewKey];
      }
    }
  }

  for (const [key, row] of Object.entries(existingRows)) {
    row.remove();
  }

  const currentOrder = [...tbody.querySelectorAll('tr[data-job-id]')].map(r => r.dataset.jobId);
  if (JSON.stringify(currentOrder) !== JSON.stringify(newIds)) {
    for (const nid of newIds) {
      const row = tbody.querySelector(`tr[data-job-id="${CSS.escape(nid)}"]`);
      if (row) tbody.appendChild(row);
    }
  }

  const hasCompleted = jobs.some(j => j.status === 'done' || j.status === 'failed');
  const deleteBtn = document.getElementById('btnDeleteCompleted');
  deleteBtn.style.display = hasCompleted ? 'inline-flex' : 'none';
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
}

function toggleJobExpand(id) {
  const tbody = document.getElementById('jobTableBody');
  if (expandedJobId === id) {
    stopStream(expandedJobId);
    const expandRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id + '__expand')}"]`);
    if (expandRow) expandRow.remove();
    const jobRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id)}"]`);
    if (jobRow) jobRow.className = '';
    expandedJobId = null;
  } else {
    if (expandedJobId) {
      stopStream(expandedJobId);
      const prevExpand = tbody.querySelector(`tr[data-job-id="${CSS.escape(expandedJobId + '__expand')}"]`);
      if (prevExpand) prevExpand.remove();
      const prevRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(expandedJobId)}"]`);
      if (prevRow) prevRow.className = '';
    }
    expandedJobId = id;
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

/* ═══════════════════════════════════════════════
   Checkpoint Diff Viewer
   ═══════════════════════════════════════════════ */

let _ckptCache = {};  // jobId → checkpoints array

async function toggleCheckpointPanel(jobId) {
  const panel = document.getElementById(`ckptPanel-${jobId}`);
  if (!panel) return;

  if (panel.style.display !== 'none') {
    panel.style.display = 'none';
    return;
  }
  panel.style.display = '';
  panel.innerHTML = `<div class="ckpt-loading">${t('diff_loading')}</div>`;

  try {
    const checkpoints = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/checkpoints`);
    _ckptCache[jobId] = checkpoints;
    renderCheckpointSelector(jobId, checkpoints);
  } catch (err) {
    panel.innerHTML = `<div class="ckpt-empty">${t('diff_no_checkpoints')}</div>`;
  }
}

function renderCheckpointSelector(jobId, checkpoints) {
  const panel = document.getElementById(`ckptPanel-${jobId}`);
  if (!panel) return;

  if (!checkpoints || checkpoints.length === 0) {
    panel.innerHTML = `<div class="ckpt-empty">${t('diff_no_checkpoints')}</div>`;
    return;
  }

  const optionsHtml = checkpoints.map((c, i) => {
    const label = `#${c.turn} — ${c.hash.slice(0, 7)} (${c.files_changed} ${t('diff_files')})`;
    return `<option value="${escapeHtml(c.hash)}"${i === 0 ? ' selected' : ''}>${escapeHtml(label)}</option>`;
  }).join('');

  const prevDefault = checkpoints.length > 1 ? checkpoints[1].hash : '';
  const prevOptions = checkpoints.map((c, i) => {
    const label = `#${c.turn} — ${c.hash.slice(0, 7)}`;
    return `<option value="${escapeHtml(c.hash)}"${i === 1 ? ' selected' : ''}>${escapeHtml(label)}</option>`;
  }).join('');

  panel.innerHTML = `
    <div class="ckpt-selector">
      <div class="ckpt-select-group">
        <label>From</label>
        <select id="ckptFrom-${escapeHtml(jobId)}" onclick="event.stopPropagation()">${prevOptions}</select>
      </div>
      <span class="ckpt-arrow">→</span>
      <div class="ckpt-select-group">
        <label>To</label>
        <select id="ckptTo-${escapeHtml(jobId)}" onclick="event.stopPropagation()">${optionsHtml}</select>
      </div>
      <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); loadDiff('${escapeHtml(jobId)}')">${t('diff_compare')}</button>
    </div>
    <div class="ckpt-hint">${t('diff_select_hint')}</div>
    <div id="diffResult-${escapeHtml(jobId)}" class="diff-result"></div>`;

  // 자동으로 첫 체크포인트의 단독 diff 로드
  if (checkpoints.length >= 1) {
    loadSingleDiff(jobId, checkpoints[0].hash);
  }
}

async function loadSingleDiff(jobId, hash) {
  const container = document.getElementById(`diffResult-${jobId}`);
  if (!container) return;
  container.innerHTML = `<div class="ckpt-loading">${t('diff_loading')}</div>`;

  try {
    const data = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/diff?from=${encodeURIComponent(hash)}`);
    renderDiffResult(container, data);
  } catch (err) {
    container.innerHTML = `<div class="ckpt-empty">${err.message || t('diff_no_changes')}</div>`;
  }
}

async function loadDiff(jobId) {
  const fromEl = document.getElementById(`ckptFrom-${jobId}`);
  const toEl = document.getElementById(`ckptTo-${jobId}`);
  if (!fromEl || !toEl) return;

  const container = document.getElementById(`diffResult-${jobId}`);
  if (!container) return;
  container.innerHTML = `<div class="ckpt-loading">${t('diff_loading')}</div>`;

  try {
    const data = await apiFetch(
      `/api/jobs/${encodeURIComponent(jobId)}/diff?from=${encodeURIComponent(fromEl.value)}&to=${encodeURIComponent(toEl.value)}`
    );
    renderDiffResult(container, data);
  } catch (err) {
    container.innerHTML = `<div class="ckpt-empty">${err.message || t('diff_no_changes')}</div>`;
  }
}

function renderDiffResult(container, data) {
  if (!data.files || data.files.length === 0) {
    container.innerHTML = `<div class="ckpt-empty">${t('diff_no_changes')}</div>`;
    return;
  }

  const summary = `<div class="diff-summary">
    <span class="diff-stat-files">${data.total_files} ${t('diff_files')}</span>
    <span class="diff-stat-add">+${data.total_additions} ${t('diff_additions')}</span>
    <span class="diff-stat-del">-${data.total_deletions} ${t('diff_deletions')}</span>
  </div>`;

  const filesHtml = data.files.map((f, idx) => {
    const lines = f.chunks.map(line => {
      const escaped = escapeHtml(line);
      if (line.startsWith('@@')) return `<div class="diff-line diff-hunk">${escaped}</div>`;
      if (line.startsWith('+')) return `<div class="diff-line diff-add">${escaped}</div>`;
      if (line.startsWith('-')) return `<div class="diff-line diff-del">${escaped}</div>`;
      if (line.startsWith('\\')) return `<div class="diff-line diff-meta">${escaped}</div>`;
      return `<div class="diff-line">${escaped}</div>`;
    }).join('');

    return `<div class="diff-file">
      <div class="diff-file-header" onclick="event.stopPropagation(); this.parentElement.classList.toggle('collapsed')">
        <span class="diff-file-name">${escapeHtml(f.file)}</span>
        <span class="diff-file-stats">
          <span class="diff-stat-add">+${f.additions}</span>
          <span class="diff-stat-del">-${f.deletions}</span>
        </span>
      </div>
      <div class="diff-file-body"><pre class="diff-code">${lines}</pre></div>
    </div>`;
  }).join('');

  container.innerHTML = summary + filesHtml;
}
