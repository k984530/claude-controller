/* ═══════════════════════════════════════════════
   Job-Projects — 프로젝트 관리 UI (jobs.js에서 분리)
   ═══════════════════════════════════════════════ */

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
