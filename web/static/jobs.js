/* ═══════════════════════════════════════════════
   Jobs — 작업 목록 렌더링, CRUD, 후속 명령
   ═══════════════════════════════════════════════ */

let expandedJobId = null;
let jobPollTimer = null;

function statusBadgeHtml(status) {
  const s = (status || 'unknown').toLowerCase();
  const labels = { running: t('status_running'), done: t('status_done'), failed: t('status_failed'), pending: t('status_pending') };
  const cls = { running: 'badge-running', done: 'badge-done', failed: 'badge-failed', pending: 'badge-pending' };
  return `<span class="badge ${cls[s] || 'badge-pending'}">${labels[s] || s}</span>`;
}

function jobActionsHtml(id, status, sessionId, cwd) {
  const isRunning = status === 'running';
  const escapedCwd = escapeHtml(cwd || '');
  let btns = '';
  if (!isRunning) {
    btns += `<button class="btn-retry-job" onclick="event.stopPropagation(); retryJob('${escapeHtml(id)}')" title="같은 프롬프트로 다시 실행"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg></button>`;
  }
  if (sessionId) {
    btns += `<button class="btn-continue-job" onclick="event.stopPropagation(); openFollowUp('${escapeHtml(id)}')" title="세션 이어서 명령 (resume)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="13 17 18 12 13 7"/><polyline points="6 17 11 12 6 7"/></svg></button>`;
    btns += `<button class="btn-fork-job" onclick="event.stopPropagation(); quickForkSession('${escapeHtml(sessionId)}', '${escapedCwd}')" title="이 세션에서 분기 (fork)" style="color:var(--yellow);"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="18" cy="18" r="3"/><circle cx="6" cy="6" r="3"/><circle cx="18" cy="6" r="3"/><path d="M6 9v3c0 3.3 2.7 6 6 6h3"/></svg></button>`;
  }
  if (!isRunning) {
    btns += `<button class="btn-delete-job" onclick="event.stopPropagation(); deleteJob('${escapeHtml(id)}')" title="작업 제거"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg></button>`;
  }
  if (!btns) return '';
  return `<div style="display:flex; align-items:center; gap:4px;">${btns}</div>`;
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
  showToast('Resume 모드: ' + sessionId.slice(0, 8) + '... 세션에 이어서 전송합니다.');
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
  _sendLock = true;

  try {
    const data = await apiFetch('/api/jobs');
    const jobs = Array.isArray(data) ? data : (data.jobs || []);
    const job = jobs.find(j => String(j.id || j.job_id) === String(jobId));
    if (!job || !job.prompt) {
      showToast(t('msg_no_original_prompt'), 'error');
      return;
    }

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

async function fetchJobs() {
  try {
    const data = await apiFetch('/api/jobs');
    const jobs = Array.isArray(data) ? data : (data.jobs || []);
    renderJobs(jobs);
  } catch {
    // silent fail for polling
  }
}

function renderJobs(jobs) {
  const tbody = document.getElementById('jobTableBody');
  const countEl = document.getElementById('jobCount');
  countEl.textContent = jobs.length > 0 ? `(${jobs.length}건)` : '';

  if (jobs.length === 0) {
    tbody.innerHTML = `<tr data-job-id="__empty__"><td colspan="7" class="empty-state">
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
      if (cells.length >= 7) {
        const newStatus = statusBadgeHtml(job.status);
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
            cells[4].setAttribute('onclick', `event.stopPropagation(); resumeFromJob('${escapeHtml(job.session_id)}', '${escapeHtml(truncate(job.prompt, 40))}', '${escapeHtml(job.cwd || '')}')`);
          }
        }
        const newActions = jobActionsHtml(id, job.status, job.session_id, job.cwd);
        if (cells[6].innerHTML !== newActions) {
          cells[6].innerHTML = newActions;
        }
      }
      existing.className = isExpanded ? 'expanded' : '';
      delete existingRows[id];
    } else if (!existing) {
      const tr = document.createElement('tr');
      tr.dataset.jobId = id;
      tr.className = isExpanded ? 'expanded' : '';
      tr.setAttribute('onclick', `toggleJobExpand('${escapeHtml(id)}')`);
      tr.innerHTML = `
        <td class="job-id">${escapeHtml(String(id).slice(0, 8))}</td>
        <td>${statusBadgeHtml(job.status)}</td>
        <td class="prompt-cell" title="${escapeHtml(job.prompt)}">${renderPromptHtml(job.prompt)}</td>
        <td class="job-cwd" title="${escapeHtml(job.cwd || '')}">${escapeHtml(formatCwd(job.cwd))}</td>
        <td class="job-session${job.session_id ? ' clickable' : ''}" title="${escapeHtml(job.session_id || '')}" ${job.session_id ? `onclick="event.stopPropagation(); resumeFromJob('${escapeHtml(job.session_id)}', '${escapeHtml(truncate(job.prompt, 40))}', '${escapeHtml(job.cwd || '')}')"` : ''}>${job.session_id ? escapeHtml(job.session_id.slice(0, 8)) : (job.status === 'running' ? '<span style="color:var(--text-muted);font-size:0.7rem;">—</span>' : '-')}</td>
        <td class="job-time">${formatTime(job.created || job.created_at)}</td>
        <td>${jobActionsHtml(id, job.status, job.session_id, job.cwd)}</td>`;
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
        const sessionId = job.session_id || '';
        const jobCwd = job.cwd || '';
        expandTr.innerHTML = `<td colspan="7">
          <div class="stream-panel" id="streamPanel-${escapeHtml(id)}" data-session-id="${escapeHtml(sessionId)}" data-cwd="${escapeHtml(jobCwd)}">
            <div class="stream-content" id="streamContent-${escapeHtml(id)}">
              <div class="stream-empty">스트림 데이터를 불러오는 중...</div>
            </div>
            ${job.status === 'done' ? '<div class="stream-done-banner">✓ 작업 완료</div>' : ''}
            ${job.status === 'failed' ? '<div class="stream-done-banner failed">✗ 작업 실패</div>' : ''}
            ${job.status !== 'running' ? `<div class="stream-actions"><button class="btn btn-sm" onclick="event.stopPropagation(); retryJob('${escapeHtml(id)}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg> 다시 실행</button><button class="btn btn-sm" onclick="event.stopPropagation(); copyStreamResult('${escapeHtml(id)}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg> 전체 복사</button><button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteJob('${escapeHtml(id)}')"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg> 작업 제거</button></div>` : ''}
            ${(job.status !== 'running' && sessionId) ? `<div class="stream-followup"><span class="stream-followup-label">이어서</span><div class="followup-input-wrap"><input type="text" class="followup-input" id="followupInput-${escapeHtml(id)}" placeholder="이 세션에 이어서 실행할 명령..." onkeydown="if(event.key==='Enter'){event.stopPropagation();sendFollowUp('${escapeHtml(id)}')}" onclick="event.stopPropagation()"><button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); sendFollowUp('${escapeHtml(id)}')" style="white-space:nowrap;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> 전송</button></div></div>` : ''}
          </div>
        </td>`;
        const jobRow = tbody.querySelector(`tr[data-job-id="${CSS.escape(id)}"]`);
        if (jobRow && jobRow.nextSibling) {
          tbody.insertBefore(expandTr, jobRow.nextSibling);
        } else {
          tbody.appendChild(expandTr);
        }
        initStream(id);
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
        initStream(id);
      }
      if (!existingPreview) {
        const pvTr = document.createElement('tr');
        pvTr.className = 'preview-row';
        pvTr.dataset.jobId = previewKey;
        pvTr.innerHTML = `<td colspan="7"><div class="job-preview" id="jobPreview-${escapeHtml(id)}"><span class="preview-text">대기 중...</span></div></td>`;
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
    const newBadge = statusBadgeHtml(status);
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
    fetchJobs();
  }
}

async function deleteJob(jobId) {
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
