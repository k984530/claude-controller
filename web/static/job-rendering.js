/* ═══════════════════════════════════════════════
   Job Rendering — 상태 뱃지, 행 HTML, 확장 패널
   ══════════════════════════���════════════════════ */

const ZOMBIE_THRESHOLD_MS = 5 * 60 * 1000;

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
  if (sessionId && !isRunning) {
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
