/* ═══════════════════════════════════════════════
   Stream — 스트림 폴링, 렌더링, 복사
   ═══════════════════════════════════════════════ */

const streamState = {};

function updateJobPreview(jobId) {
  const el = document.getElementById(`jobPreview-${jobId}`);
  if (!el) return;

  const state = streamState[jobId];
  if (!state || state.events.length === 0) return;

  const recent = state.events.slice(-2);
  const lines = recent.map(evt => {
    if (evt.type === 'tool_use') {
      const input = escapeHtml((typeof evt.input === 'string' ? evt.input : JSON.stringify(evt.input || '')).slice(0, 150));
      return `<div class="preview-line"><span class="preview-tool">${escapeHtml(evt.tool || 'Tool')}</span>${input}</div>`;
    }
    if (evt.type === 'result') {
      const text = (typeof evt.result === 'string' ? evt.result : '').slice(0, 150);
      return `<div class="preview-line preview-result">${escapeHtml(text)}</div>`;
    }
    const text = (evt.text || '').split('\n').pop().slice(0, 150);
    if (!text) return '';
    return `<div class="preview-line">${escapeHtml(text)}</div>`;
  }).filter(Boolean);

  if (lines.length > 0) {
    el.innerHTML = `<div class="preview-lines">${lines.join('')}</div>`;
  }
}

function initStream(jobId) {
  if (streamState[jobId] && streamState[jobId].timer) return;
  if (streamState[jobId] && streamState[jobId]._bulkLoading) return;

  if (!streamState[jobId]) {
    streamState[jobId] = { offset: 0, timer: null, done: false, jobData: null, events: [], renderedCount: 0 };
  }

  const state = streamState[jobId];
  if (state.done && state.events.length > 0) {
    renderStreamEvents(jobId);
    return;
  }

  const isDone = state.jobData && (state.jobData.status === 'done' || state.jobData.status === 'failed');
  if (isDone) {
    loadStreamBulk(jobId);
    return;
  }

  pollStream(jobId);
  state.timer = setInterval(() => pollStream(jobId), 500);
}

async function loadStreamBulk(jobId) {
  const state = streamState[jobId];
  if (!state || state._bulkLoading) return;
  state._bulkLoading = true;

  try {
    const data = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/stream?offset=${state.offset}`);
    if (data.events && data.events.length > 0) {
      state.events = state.events.concat(data.events);
      state.offset = data.offset;
      renderStreamEvents(jobId);
    }
    if (data.done || !data.events || data.events.length === 0) {
      state.done = true;
      renderStreamDone(jobId);
      updateJobRowStatus(jobId, state.jobData ? state.jobData.status : 'done');
      const pvRow = document.querySelector(`tr[data-job-id="${CSS.escape(jobId + '__preview')}"]`);
      if (pvRow) pvRow.remove();
    }
  } catch {
    // 네트워크 오류 시 재시도 가능
  } finally {
    state._bulkLoading = false;
  }
}

function stopStream(jobId) {
  const state = streamState[jobId];
  if (!state) return;
  if (state.timer) {
    clearInterval(state.timer);
    state.timer = null;
  }
}

async function pollStream(jobId) {
  const state = streamState[jobId];
  if (!state || state.done) {
    stopStream(jobId);
    return;
  }

  try {
    const data = await apiFetch(`/api/jobs/${encodeURIComponent(jobId)}/stream?offset=${state.offset}`);
    const events = data.events || [];
    const newOffset = data.offset !== undefined ? data.offset : state.offset + events.length;
    const done = !!data.done;

    if (events.length > 0) {
      state.events = state.events.concat(events);
      state.offset = newOffset;
      renderStreamEvents(jobId);
      updateJobPreview(jobId);
    }

    if (done) {
      state.done = true;
      stopStream(jobId);
      renderStreamDone(jobId);
      updateJobRowStatus(jobId, state.jobData ? state.jobData.status : 'done');
      const pvRow = document.querySelector(`tr[data-job-id="${CSS.escape(jobId + '__preview')}"]`);
      if (pvRow) pvRow.remove();
    }
  } catch {
    // Network error — keep retrying
  }
}

function renderStreamEvents(jobId) {
  const container = document.getElementById(`streamContent-${jobId}`);
  if (!container) return;

  const state = streamState[jobId];
  if (!state || state.events.length === 0) return;

  if (!state.renderedCount) state.renderedCount = 0;
  if (state.renderedCount >= state.events.length) return;

  const wasAtBottom = container.scrollHeight - container.scrollTop - container.clientHeight < 40;

  if (state.renderedCount === 0) {
    container.innerHTML = '';
  }

  const fragment = document.createDocumentFragment();
  for (let i = state.renderedCount; i < state.events.length; i++) {
    const evt = state.events[i];
    const type = (evt.type || 'text').toLowerCase();
    const div = document.createElement('div');
    div.className = 'stream-event';

    switch (type) {
      case 'tool_use':
        div.classList.add('stream-event-tool');
        div.innerHTML = `<span class="stream-tool-badge">${escapeHtml(evt.tool || 'Tool')}</span>
          <span class="stream-tool-input">${escapeHtml(typeof evt.input === 'string' ? evt.input : JSON.stringify(evt.input || ''))}</span>`;
        break;
      case 'result':
        div.classList.add('stream-event-result');
        div.innerHTML = `<span class="stream-result-icon">✓</span>
          <span class="stream-result-text">${escapeHtml(typeof evt.result === 'string' ? evt.result : JSON.stringify(evt.result || ''))}</span>`;
        if (evt.session_id) {
          const panel = document.getElementById(`streamPanel-${jobId}`);
          if (panel) panel.dataset.sessionId = evt.session_id;
          const jobRow = document.querySelector(`tr[data-job-id="${CSS.escape(jobId)}"]`);
          if (jobRow) {
            const cells = jobRow.querySelectorAll('td');
            if (cells.length >= 5 && cells[4].textContent !== evt.session_id.slice(0, 8)) {
              cells[4].textContent = evt.session_id.slice(0, 8);
              cells[4].className = 'job-session clickable';
              cells[4].title = evt.session_id;
              const evtCwd = panel ? (panel.dataset.cwd || '') : '';
              cells[4].setAttribute('onclick', `event.stopPropagation(); resumeFromJob('${escapeHtml(evt.session_id)}', '', '${escapeHtml(evtCwd)}')`);
            }
          }
        }
        break;
      case 'error':
        div.classList.add('stream-event-error');
        div.innerHTML = `<span class="stream-error-icon">✗</span>
          <span class="stream-error-text">${escapeHtml(evt.text || evt.error || evt.message || 'Unknown error')}</span>`;
        break;
      case 'text':
      default:
        div.classList.add('stream-event-text');
        div.textContent = evt.text || '';
        break;
    }
    fragment.appendChild(div);
  }

  container.appendChild(fragment);
  state.renderedCount = state.events.length;

  if (wasAtBottom) {
    container.scrollTop = container.scrollHeight;
  }
}

function renderStreamDone(jobId) {
  const panel = document.getElementById(`streamPanel-${jobId}`);
  if (!panel) return;

  const state = streamState[jobId];
  const status = state && state.jobData ? state.jobData.status : 'done';
  const isFailed = status === 'failed';

  let banner = panel.querySelector('.stream-done-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.className = `stream-done-banner${isFailed ? ' failed' : ''}`;
    banner.textContent = isFailed ? '✗ 작업 실패' : '✓ 작업 완료';
    panel.appendChild(banner);
  }

  let actions = panel.querySelector('.stream-actions');
  if (!actions) {
    actions = document.createElement('div');
    actions.className = 'stream-actions';
    actions.innerHTML = `
      <button class="btn btn-sm" onclick="event.stopPropagation(); copyStreamResult('${escapeHtml(jobId)}')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        전체 복사
      </button>
      <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteJob('${escapeHtml(jobId)}')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
        작업 제거
      </button>`;
    panel.appendChild(actions);
  }

  const sessionId = panel.dataset.sessionId;
  if (sessionId && !panel.querySelector('.stream-followup')) {
    const followup = document.createElement('div');
    followup.className = 'stream-followup';
    followup.innerHTML = `
      <span class="stream-followup-label">이어서</span>
      <div class="followup-input-wrap">
        <input type="text" class="followup-input" id="followupInput-${escapeHtml(jobId)}"
               placeholder="이 세션에 이어서 실행할 명령... (파일/이미지 붙여넣기 가능)"
               onkeydown="if(event.key==='Enter'){event.stopPropagation();sendFollowUp('${escapeHtml(jobId)}')}"
               onclick="event.stopPropagation()">
        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); sendFollowUp('${escapeHtml(jobId)}')" style="white-space:nowrap;">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> 전송
        </button>
      </div>
      <div class="followup-previews" id="followupPreviews-${escapeHtml(jobId)}"></div>`;
    panel.appendChild(followup);

    const fInput = document.getElementById(`followupInput-${jobId}`);
    if (fInput) {
      fInput.addEventListener('paste', function(e) {
        const files = e.clipboardData?.files;
        if (files && files.length > 0) {
          e.preventDefault();
          handleFollowUpFiles(jobId, files);
        }
      });
      fInput.addEventListener('drop', function(e) {
        if (e.dataTransfer.files.length > 0) {
          e.preventDefault();
          handleFollowUpFiles(jobId, e.dataTransfer.files);
        }
      });
      fInput.addEventListener('dragover', function(e) { e.preventDefault(); });
    }
  }
}

function copyStreamResult(jobId) {
  const state = streamState[jobId];
  if (!state || state.events.length === 0) {
    showToast(t('msg_copy_no_result'), 'error');
    return;
  }

  const textParts = [];
  for (const evt of state.events) {
    const type = (evt.type || 'text').toLowerCase();
    switch (type) {
      case 'text':
        if (evt.text) textParts.push(evt.text);
        break;
      case 'result': {
        const r = typeof evt.result === 'string' ? evt.result : JSON.stringify(evt.result || '');
        if (r) textParts.push(`[Result] ${r}`);
        break;
      }
      case 'tool_use': {
        const toolName = evt.tool || 'Tool';
        const toolInput = typeof evt.input === 'string' ? evt.input : JSON.stringify(evt.input || '');
        textParts.push(`[${toolName}] ${toolInput}`);
        break;
      }
      case 'error': {
        const errMsg = evt.text || evt.error || evt.message || 'Unknown error';
        textParts.push(`[Error] ${errMsg}`);
        break;
      }
    }
  }

  const text = textParts.join('\n').trim();
  if (!text) {
    showToast(t('msg_copy_no_text'), 'error');
    return;
  }

  navigator.clipboard.writeText(text).then(() => {
    showToast(t('msg_copy_done'));
  }).catch(() => {
    showToast(t('msg_copy_failed'), 'error');
  });
}
