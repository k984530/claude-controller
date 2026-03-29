/* ═══════════════════════════════════════════════
   Checkpoint Diff Viewer — 체크포인트 비교 UI
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
