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

function initStream(jobId, jobData) {
  if (streamState[jobId] && streamState[jobId]._bulkLoading) return;

  if (!streamState[jobId]) {
    streamState[jobId] = { offset: 0, timer: null, done: false, jobData: jobData || null, events: [], renderedCount: 0, _initTime: Date.now(), _lastEventTime: Date.now() };
  } else if (jobData) {
    streamState[jobId].jobData = jobData;
  }

  const state = streamState[jobId];

  // expand 패널이 새로 생겼는데 아직 placeholder 상태면 캐시된 이벤트를 즉시 렌더링
  const container = document.getElementById(`streamContent-${jobId}`);
  if (container && state.events.length > 0) {
    const isEmpty = container.querySelector('.stream-empty') || container.children.length === 0;
    if (isEmpty) {
      state.renderedCount = 0;
      renderStreamEvents(jobId);
    }
  }

  // SSE 또는 폴링이 이미 진행 중이면 중복 시작하지 않음
  if (state.timer || state._eventSource) return;

  if (state.done && state.events.length > 0) {
    renderStreamEvents(jobId);
    return;
  }

  const isDone = state.jobData && (state.jobData.status === 'done' || state.jobData.status === 'failed');
  if (isDone) {
    loadStreamBulk(jobId);
    return;
  }

  // SSE 실시간 스트림 시작 (실패 시 자동 폴링 폴백)
  startSSEStream(jobId);
}

function startSSEStream(jobId) {
  const state = streamState[jobId];
  if (!state) return;

  let url = `${API}/api/jobs/${encodeURIComponent(jobId)}/stream`;
  if (AUTH_TOKEN) url += `?token=${encodeURIComponent(AUTH_TOKEN)}`;

  const es = new EventSource(url);
  state._eventSource = es;

  es.onmessage = function(e) {
    try {
      const evt = JSON.parse(e.data);
      state.events.push(evt);
      state._lastEventTime = Date.now();
      renderStreamEvents(jobId);
      updateJobPreview(jobId);
    } catch { /* parse error */ }
  };

  es.addEventListener('done', function(e) {
    es.close();
    state._eventSource = null;
    state.done = true;

    let finalStatus = 'done';
    try {
      const data = JSON.parse(e.data);
      finalStatus = data.status || 'done';
    } catch {}

    const lastResult = state.events.filter(ev => ev.type === 'result').pop();
    if (lastResult && lastResult.is_error) finalStatus = 'failed';
    if (state.jobData) state.jobData.status = finalStatus;

    renderStreamDone(jobId);
    updateJobRowStatus(jobId, finalStatus);
    notifyJobDone(jobId, finalStatus, state.jobData ? state.jobData.prompt : '');

    const pvRow = document.querySelector(`tr[data-job-id="${CSS.escape(jobId + '__preview')}"]`);
    if (pvRow) pvRow.remove();

    fetchJobs();
  });

  es.onerror = function() {
    if (state.done) return;

    // SSE 실패 → 폴링 폴백
    es.close();
    state._eventSource = null;

    if (!state.timer) {
      pollStream(jobId);
      state.timer = setInterval(() => pollStream(jobId), 500);
    }
  };
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
      const lastResult = state.events.filter(e => e.type === 'result').pop();
      const finalStatus = (lastResult && lastResult.is_error) ? 'failed'
        : (state.jobData ? state.jobData.status : 'done');
      if (state.jobData) state.jobData.status = finalStatus;
      renderStreamDone(jobId);
      updateJobRowStatus(jobId, finalStatus);
      const pvRow = document.querySelector(`tr[data-job-id="${CSS.escape(jobId + '__preview')}"]`);
      if (pvRow) pvRow.remove();
    }
  } catch (err) {
    const container = document.getElementById(`streamContent-${jobId}`);
    if (container) {
      const retryId = `retryBulk-${jobId}`;
      container.innerHTML = `<div class="stream-error-state">
        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
        <span>${escapeHtml(t('stream_load_failed'))}</span>
        <button class="btn btn-sm" id="${retryId}" onclick="event.stopPropagation(); loadStreamBulk('${escapeHtml(jobId)}')">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
          ${escapeHtml(t('stream_retry'))}
        </button>
      </div>`;
    }
  } finally {
    state._bulkLoading = false;
  }
}

function stopStream(jobId) {
  const state = streamState[jobId];
  if (!state) return;
  if (state._eventSource) {
    state._eventSource.close();
    state._eventSource = null;
  }
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

    // 성공 시 실패 카운터 초기화 + 백오프 복원
    if (state._pollFails > 0) {
      state._pollFails = 0;
      _setPollInterval(jobId, 500);
      _clearPollWarning(jobId);
    }

    if (events.length > 0) {
      state.events = state.events.concat(events);
      state.offset = newOffset;
      state._lastEventTime = Date.now();
      renderStreamEvents(jobId);
      updateJobPreview(jobId);
    }

    if (done) {
      state.done = true;
      stopStream(jobId);

      // result 이벤트의 is_error 로 실제 최종 상태 결정
      const lastResult = state.events.filter(e => e.type === 'result').pop();
      const finalStatus = lastResult && lastResult.is_error ? 'failed' : 'done';
      if (state.jobData) state.jobData.status = finalStatus;

      renderStreamDone(jobId);
      updateJobRowStatus(jobId, finalStatus);
      notifyJobDone(jobId, finalStatus, state.jobData ? state.jobData.prompt : '');
      const pvRow = document.querySelector(`tr[data-job-id="${CSS.escape(jobId + '__preview')}"]`);
      if (pvRow) pvRow.remove();

      // 즉시 전체 행 동기화 (액션 버튼, 필터 등)
      fetchJobs();
    }
  } catch {
    // 네트워크 에러 — 지수 백오프 + 실패 피드백
    state._pollFails = (state._pollFails || 0) + 1;
    const fails = state._pollFails;

    if (fails >= 20) {
      // 20회 연속 실패 (~2분) → 폴링 중단, 재시도 버튼 표시
      stopStream(jobId);
      _showPollRetry(jobId);
    } else if (fails >= 5) {
      // 5회+ 실패 → 경고 표시 + 백오프 (1s → 2s → 4s → 최대 10s)
      const interval = Math.min(500 * Math.pow(2, fails - 4), 10000);
      _setPollInterval(jobId, interval);
      _showPollWarning(jobId);
    }
  }
}

/** 폴링 간격을 동적으로 변경한다. */
function _setPollInterval(jobId, ms) {
  const state = streamState[jobId];
  if (!state || !state.timer) return;
  clearInterval(state.timer);
  state.timer = setInterval(() => pollStream(jobId), ms);
}

/** 연결 불안정 경고를 스트림 패널에 표시한다. */
function _showPollWarning(jobId) {
  const panel = document.getElementById(`streamPanel-${jobId}`);
  if (!panel || panel.querySelector('.stream-poll-warning')) return;
  const warn = document.createElement('div');
  warn.className = 'stream-poll-warning';
  warn.innerHTML = `<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg> ${escapeHtml(t('conn_lost'))}`;
  panel.prepend(warn);
}

function _clearPollWarning(jobId) {
  const panel = document.getElementById(`streamPanel-${jobId}`);
  if (!panel) return;
  const warn = panel.querySelector('.stream-poll-warning');
  if (warn) warn.remove();
}

/** 폴링이 포기된 후 수동 재시도 버튼을 표시한다. */
function _showPollRetry(jobId) {
  _clearPollWarning(jobId);
  const container = document.getElementById(`streamContent-${jobId}`);
  if (!container) return;
  // 이미 표시된 경우 중복 방지
  if (container.querySelector('.stream-poll-retry')) return;
  const retryDiv = document.createElement('div');
  retryDiv.className = 'stream-error-state stream-poll-retry';
  retryDiv.innerHTML = `
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
    <span>${escapeHtml(t('conn_lost'))}</span>
    <button class="btn btn-sm" onclick="event.stopPropagation(); retryPollStream('${escapeHtml(jobId)}')">
      <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/></svg>
      ${escapeHtml(t('stream_reconnect'))}
    </button>`;
  container.appendChild(retryDiv);
}

function retryPollStream(jobId) {
  const state = streamState[jobId];
  if (!state) return;
  state._pollFails = 0;
  // 재시도 UI 제거
  const container = document.getElementById(`streamContent-${jobId}`);
  if (container) {
    const retry = container.querySelector('.stream-poll-retry');
    if (retry) retry.remove();
  }
  // SSE 우선 시도, 실패 시 자동 폴링 전환
  startSSEStream(jobId);
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
        if (evt.is_error && evt.user_error) {
          div.classList.add('stream-event-result-error');
          div.innerHTML = `<span class="stream-result-icon">✗</span>
            <span class="stream-result-text">${escapeHtml(evt.user_error.summary)}</span>`;
        } else {
          div.innerHTML = `<span class="stream-result-icon">✓</span>
            <span class="stream-result-text">${escapeHtml(typeof evt.result === 'string' ? evt.result : JSON.stringify(evt.result || ''))}</span>`;
        }
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
              cells[4].setAttribute('onclick', `event.stopPropagation(); resumeFromJob('${escapeJsStr(evt.session_id)}', '', '${escapeJsStr(evtCwd)}')`);
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

  // 이벤트가 0개면 "불러오는 중" placeholder를 "출력 없음"으로 교체
  if (state && state.events.length === 0) {
    const container = document.getElementById(`streamContent-${jobId}`);
    if (container && (container.querySelector('.stream-empty') || container.children.length === 0)) {
      container.innerHTML = `<div class="stream-no-output">${t('stream_no_output')}</div>`;
    }
  }

  // 소요시간 추출
  const lastResult = state ? state.events.filter(e => e.type === 'result').pop() : null;
  let bannerDetails = '';
  if (lastResult) {
    const info = formatDuration(lastResult.duration_ms);
    if (info) bannerDetails = ` — ${info}`;
  }

  let banner = panel.querySelector('.stream-done-banner');
  if (!banner) {
    banner = document.createElement('div');
    banner.className = `stream-done-banner${isFailed ? ' failed' : ''}`;
    banner.textContent = (isFailed ? `✗ ${t('stream_job_failed')}` : `✓ ${t('stream_job_done')}`) + bannerDetails;
    panel.appendChild(banner);
  } else if (bannerDetails && !banner.textContent.includes('—')) {
    banner.textContent = (isFailed ? `✗ ${t('stream_job_failed')}` : `✓ ${t('stream_job_done')}`) + bannerDetails;
  }

  // 실패 시 사용자 친화적 에러 카드 표시
  if (isFailed && lastResult && !panel.querySelector('.user-error-card')) {
    const ue = lastResult.user_error;
    if (ue) {
      const card = document.createElement('div');
      card.className = 'user-error-card';
      const stepsHtml = (ue.next_steps || []).map(s => `<li>${escapeHtml(s)}</li>`).join('');
      const rawText = typeof lastResult.result === 'string' ? lastResult.result : '';
      const detailsHtml = rawText ? `<details class="user-error-details"><summary>${escapeHtml(t('err_show_log'))}</summary><pre class="user-error-raw">${escapeHtml(rawText.slice(0, 2000))}</pre></details>` : '';
      card.innerHTML = `<div class="user-error-summary">${escapeHtml(ue.summary)}</div>
        <div class="user-error-cause">${escapeHtml(ue.cause)}</div>
        ${stepsHtml ? `<ul class="user-error-steps">${stepsHtml}</ul>` : ''}
        ${detailsHtml}`;
      banner.insertAdjacentElement('afterend', card);
    }
  }

  let actions = panel.querySelector('.stream-actions');
  if (!actions) {
    actions = document.createElement('div');
    actions.className = 'stream-actions';
    actions.innerHTML = `
      <button class="btn btn-sm" onclick="event.stopPropagation(); copyStreamResult('${escapeHtml(jobId)}')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
        ${escapeHtml(t('stream_copy_all'))}
      </button>
      <button class="btn btn-sm btn-danger" onclick="event.stopPropagation(); deleteJob('${escapeHtml(jobId)}')">
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
        ${escapeHtml(t('stream_delete_job'))}
      </button>`;
    panel.appendChild(actions);
  }

  const sessionId = panel.dataset.sessionId;
  if (sessionId && !panel.querySelector('.stream-followup')) {
    const followup = document.createElement('div');
    followup.className = 'stream-followup';
    followup.innerHTML = `
      <span class="stream-followup-label">${escapeHtml(t('stream_followup_label'))}</span>
      <div class="followup-input-wrap">
        <input type="text" class="followup-input" id="followupInput-${escapeHtml(jobId)}"
               placeholder="${escapeHtml(t('stream_followup_placeholder'))}"
               onkeydown="if(event.key==='Enter'){event.stopPropagation();sendFollowUp('${escapeHtml(jobId)}')}"
               onclick="event.stopPropagation()">
        <button class="btn btn-primary btn-sm" onclick="event.stopPropagation(); sendFollowUp('${escapeHtml(jobId)}')" style="white-space:nowrap;">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> ${escapeHtml(t('send'))}
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
