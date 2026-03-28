/* ═══════════════════════════════════════════════
   Send Task — 작업 전송 및 자동화 토글
   ═══════════════════════════════════════════════ */

let _sendLock = false;
let _automationMode = false;

function toggleAutomation() {
  _automationMode = !_automationMode;
  const row = document.getElementById('automationRow');
  const btn = document.getElementById('btnAutoToggle');
  const sendBtn = document.getElementById('btnSend');
  if (_automationMode) {
    row.style.display = 'flex';
    btn.style.cssText = 'border-color:var(--accent);color:var(--accent);background:rgba(99,102,241,0.1);';
    sendBtn.querySelector('span').textContent = '자동화 등록';
  } else {
    row.style.display = 'none';
    btn.style.cssText = '';
    sendBtn.querySelector('span').textContent = t('send');
    document.getElementById('automationInterval').value = '';
  }
}

function clearPromptForm() {
  document.getElementById('promptInput').value = '';
  clearAttachments();
  updatePromptMirror();
  clearDirSelection();
  if (_automationMode) toggleAutomation();
}

async function sendTask(e) {
  e.preventDefault();
  if (_sendLock) return false;

  const prompt = document.getElementById('promptInput').value.trim();
  if (!prompt) {
    showToast(t('msg_prompt_required'), 'error');
    return false;
  }

  // ── 자동화 모드: 파이프라인 생성 ──
  if (_automationMode) {
    const cwd = document.getElementById('cwdInput').value.trim();
    if (!cwd) { showToast('디렉토리를 선택하세요', 'error'); return false; }
    const interval = document.getElementById('automationInterval').value.trim();
    _sendLock = true;
    const btn = document.getElementById('btnSend');
    btn.disabled = true;
    try {
      const pipe = await apiFetch('/api/pipelines', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ project_path: cwd, command: prompt, interval }),
      });
      showToast(`자동화 등록: ${pipe.name || pipe.id}`);
      document.getElementById('promptInput').value = '';
      toggleAutomation();
      fetchPipelines();
      runPipeline(pipe.id);
    } catch (err) {
      showToast(`등록 실패: ${err.message}`, 'error');
    } finally {
      _sendLock = false;
      btn.disabled = false;
      btn.querySelector('span').textContent = t('send');
    }
    return false;
  }

  // ── 일반 전송 모드 ──
  _sendLock = true;
  const cwd = document.getElementById('cwdInput').value.trim();
  const btn = document.getElementById('btnSend');
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span> 전송 중...';

  try {
    let finalPrompt = prompt;
    const filePaths = [];
    attachments.forEach((att, idx) => {
      if (att && att.serverPath) {
        finalPrompt = finalPrompt.replace(new RegExp(`@image${idx}\\b`, 'g'), `@${att.serverPath}`);
        filePaths.push(att.serverPath);
      }
    });

    const body = { prompt: finalPrompt };
    if (cwd) body.cwd = cwd;

    if (_contextSessionId && (_contextMode === 'resume' || _contextMode === 'fork')) {
      body.session = _contextMode + ':' + _contextSessionId;
    }

    if (filePaths.length > 0) body.images = filePaths;

    await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
    const modeMsg = _contextMode === 'resume' ? ' (resume)' : _contextMode === 'fork' ? ' (fork)' : '';
    showToast(t('msg_task_sent') + modeMsg);
    if (cwd) addRecentDir(cwd);
    document.getElementById('promptInput').value = '';
    clearAttachments();
    clearContext();
    fetchJobs();
  } catch (err) {
    showToast(`${t('msg_send_failed')}: ${err.message}`, 'error');
  } finally {
    _sendLock = false;
    btn.disabled = false;
    btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg> <span data-i18n="send">' + t('send') + '</span>';
  }
  return false;
}
