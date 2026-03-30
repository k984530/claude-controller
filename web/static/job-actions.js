/* ═══════════════════════════════════════════════
   Job Actions — 후속 명령, 재시도, 포크, 세션 이어가기
   ═══════════════════════════════════════════════ */

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
