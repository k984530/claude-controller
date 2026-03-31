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
