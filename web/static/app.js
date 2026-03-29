/* ═══════════════════════════════════════════════
   Controller Service Dashboard — Entry Point

   모듈 로드 순서 (index.html에서):
   1. i18n.js      — 국제화
   2. utils.js     — 유틸리티
   3. api.js       — API 호출
   4. context.js   — 세션 컨텍스트
   5. attachments.js — 파일 첨부
   6. dirs.js      — 디렉토리 브라우저
   7. send.js      — 작업 전송
   8. stream.js    — 스트림 폴링/렌더링
   9. jobs.js      — 작업 목록
   10. pipelines.js — 자동화 파이프라인
   11. settings.js  — 설정
   12. app.js       — 초기화 (이 파일)
   ═══════════════════════════════════════════════ */

async function autoConnect() {
  const isSameOrigin = location.hostname === 'localhost' || location.hostname === '127.0.0.1';

  if (isSameOrigin) {
    API = '';
    _backendConnected = true;
  } else {
    try {
      const resp = await fetch(`${LOCAL_BACKEND}/api/status`, { signal: AbortSignal.timeout(3000) });
      if (resp.ok) {
        API = LOCAL_BACKEND;
        _backendConnected = true;
      }
    } catch {
      _backendConnected = false;
    }
  }
}

async function init() {
  applyI18n();
  applyTheme(localStorage.getItem('theme') || 'dark');
  await autoConnect();
  loadRecentDirs();
  fetchPersonas();
  fetchPipelines();
  checkStatus();
  fetchRegisteredProjects();
  fetchJobs();
  fetchStats();
  _applyJobListCollapse();
  requestNotificationPermission();

  jobPollTimer = setInterval(fetchJobs, 3000);
  setInterval(fetchStats, 15000);
  setInterval(fetchRegisteredProjects, 30000);
  setInterval(checkStatus, 10000);

  const promptInput = document.getElementById('promptInput');
  promptInput.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      document.getElementById('sendForm').dispatchEvent(new Event('submit'));
    }
  });

  promptInput.addEventListener('input', updatePromptMirror);
  promptInput.addEventListener('scroll', function() {
    const mirror = document.getElementById('promptMirror');
    if (mirror) mirror.scrollTop = this.scrollTop;
  });

  // ── File Drag & Drop ──
  const wrapper = document.getElementById('promptWrapper');
  const dropZone = document.getElementById('sendTask');
  let dragCounter = 0;

  dropZone.addEventListener('dragenter', function(e) {
    e.preventDefault();
    dragCounter++;
    wrapper.classList.add('drag-over');
  });

  dropZone.addEventListener('dragover', function(e) {
    e.preventDefault();
  });

  dropZone.addEventListener('dragleave', function(e) {
    e.preventDefault();
    dragCounter--;
    if (dragCounter <= 0) {
      dragCounter = 0;
      wrapper.classList.remove('drag-over');
    }
  });

  dropZone.addEventListener('drop', function(e) {
    e.preventDefault();
    dragCounter = 0;
    wrapper.classList.remove('drag-over');
    if (e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  });

  document.addEventListener('dragover', function(e) { e.preventDefault(); });
  document.addEventListener('drop', function(e) {
    if (e.dataTransfer.files.length > 0) {
      e.preventDefault();
      handleFiles(e.dataTransfer.files);
    }
  });

  // ── Clipboard Paste ──
  document.getElementById('promptInput').addEventListener('paste', function(e) {
    const files = e.clipboardData?.files;
    if (files && files.length > 0) {
      handleFiles(files);
    }
  });

  // ── File Picker ──
  document.getElementById('filePickerInput').addEventListener('change', function(e) {
    if (e.target.files.length > 0) {
      handleFiles(e.target.files);
      e.target.value = '';
    }
  });
}

init();
