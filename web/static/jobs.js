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
let _statsPeriod = 'all';
let _selectedProject = null;
let _selectedProjectInfo = null;
let _jobPage = 1;
let _jobLimit = 50;
let _jobPages = 1;
let _jobTotal = 0;
const _GROUP_PAGE_SIZE = 5;
let _groupPages = {};  // { groupName: currentPage(1-based) }

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
  // 그룹별 페이지네이션 사용 → 글로벌 숨김
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

