/* ═══════════════════════════════════════════════
   Send Task — 작업 전송 및 자동화 토글
   ═══════════════════════════════════════════════ */

let _sendLock = false;
let _automationMode = false;
let _depsMode = false;

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

function toggleDeps() {
  // DAG UI는 숨김 처리됨 — AI가 API depends_on으로 직접 사용
  _depsMode = !_depsMode;
  const row = document.getElementById('depsRow');
  if (row) row.style.display = _depsMode ? 'flex' : 'none';
  if (!_depsMode) {
    const inp = document.getElementById('depsInput');
    if (inp) inp.value = '';
  }
}

function clearPromptForm() {
  document.getElementById('promptInput').value = '';
  clearAttachments();
  updatePromptMirror();
  clearDirSelection();
  if (_automationMode) toggleAutomation();
  if (_depsMode) toggleDeps();
  if (typeof clearPersonaSelection === 'function') clearPersonaSelection();
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
      clearPromptForm();
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
    if (typeof _selectedPersona === 'string' && _selectedPersona) {
      body.persona = _selectedPersona;
    }

    if (_contextSessionId && (_contextMode === 'resume' || _contextMode === 'fork')) {
      body.session = _contextMode + ':' + _contextSessionId;
    }

    if (filePaths.length > 0) body.images = filePaths;

    // 의존성 모드: depends_on 추가
    if (_depsMode) {
      const depsVal = document.getElementById('depsInput').value.trim();
      if (depsVal) {
        body.depends_on = depsVal.split(/[,\s]+/).filter(Boolean);
      }
    }

    const result = await apiFetch('/api/send', { method: 'POST', body: JSON.stringify(body) });
    const modeMsg = _contextMode === 'resume' ? ' (resume)' : _contextMode === 'fork' ? ' (fork)' : '';
    const depMsg = result && result.status === 'pending' ? ' (대기 중 — 선행 작업 완료 후 실행)' : '';
    showToast(t('msg_task_sent') + modeMsg + depMsg);
    if (cwd) addRecentDir(cwd);
    document.getElementById('promptInput').value = '';
    clearAttachments();
    // resume 모드: 세션 컨텍스트를 유지하여 이어서 보낼 수 있게 함
    // fork/new 모드: 컨텍스트 초기화
    if (_contextMode !== 'resume') clearContext();
    if (_depsMode) toggleDeps();
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

/* ═══════════════════════════════════════════════
   Self-Manage — 이 서비스 자체를 AI로 관리
   ═══════════════════════════════════════════════ */

let _controllerDir = null;

const _SELF_MANAGE_PROMPTS = {
  cleanup: `이 프로젝트의 코드를 정리해줘.
1. dead code 검출 (사용되지 않는 import, 함수, 변수)
2. 불필요한 console.log, print, 디버그 코드 제거
3. 코드 포매팅 일관성 확인
4. 발견된 것 중 1건 정리

규칙: 한 번에 1건만. 주석은 의미 있는 것만 남길 것.`,

  test: `이 프로젝트의 테스트를 실행하고 결과를 분석해줘.
1. tests/ 디렉토리의 테스트 파일 목록 확인
2. pytest 또는 unittest로 테스트 실행
3. 실패한 테스트가 있으면 원인 분석
4. 테스트 커버리지가 부족한 영역 식별

결과를 요약해서 보고해줘.`,

  security: `이 프로젝트의 보안을 점검해줘.
1. 외부 입력 검증 누락 (command injection, path traversal)
2. 인증/인가 로직 점검 (auth.py, handler.py)
3. 파일 접근 경로 검증 (uploads, logs 디렉토리)
4. 민감 정보 노출 여부 (토큰, 키, 비밀번호)

가장 심각한 1건을 찾아서 수정해줘.`,

  refactor: `이 프로젝트에서 리팩토링이 필요한 부분을 찾아줘.
1. 가장 복잡한 함수/파일 식별 (줄 수, 중첩 깊이, 순환 복잡도)
2. 중복 코드 패턴 탐지
3. 모듈 간 결합도 분석

가장 임팩트 큰 1건만 리팩토링해줘. 동작은 반드시 유지할 것.`,

  status: `이 프로젝트의 현재 상태를 진단해줘.
1. git status — 미커밋 변경사항 확인
2. git log --oneline -10 — 최근 커밋 이력
3. 서비스 프로세스 상태 (service/ 디렉토리)
4. 에러 로그 확인 (logs/ 디렉토리의 최근 로그)
5. 디스크 사용량 (data/, logs/, uploads/)

간결하게 요약해줘.`,
};

function toggleSelfManageMenu() {
  const menu = document.getElementById('selfManageMenu');
  const isOpen = menu.classList.contains('open');
  menu.classList.toggle('open', !isOpen);

  if (!isOpen) {
    // 바깥 클릭 시 닫기
    setTimeout(() => {
      document.addEventListener('click', _closeSelfManageOnOutside, { once: true });
    }, 0);
  }
}

function _closeSelfManageOnOutside(e) {
  const wrap = document.querySelector('.self-manage-wrap');
  if (wrap && !wrap.contains(e.target)) {
    document.getElementById('selfManageMenu').classList.remove('open');
  } else {
    // 아직 메뉴 안이면 다시 리스너 등록
    document.addEventListener('click', _closeSelfManageOnOutside, { once: true });
  }
}

async function selfManageAction(action) {
  document.getElementById('selfManageMenu').classList.remove('open');

  // controller 경로 가져오기
  if (!_controllerDir) {
    try {
      const status = await apiFetch('/api/status');
      _controllerDir = status.controller_dir;
    } catch {
      showToast('서버에서 경로를 가져올 수 없습니다', 'error');
      return;
    }
  }

  if (action === 'custom') {
    // 직접 입력: CWD만 설정하고 프롬프트에 포커스
    document.getElementById('cwdInput').value = _controllerDir;
    const display = document.getElementById('dirPickerText');
    if (display) { display.textContent = _controllerDir; display.style.color = ''; }
    const clearBtn = document.getElementById('dirPickerClear');
    if (clearBtn) clearBtn.style.display = '';
    document.getElementById('promptInput').focus();
    showToast('CWD → Controller 프로젝트');
    return;
  }

  // 즉시 전송: /api/send로 작업 전달
  const prompt = _SELF_MANAGE_PROMPTS[action];
  if (!prompt) return;

  const btn = document.getElementById('btnSelfManage');
  if (btn) btn.disabled = true;

  try {
    await apiFetch('/api/send', {
      method: 'POST',
      body: JSON.stringify({ prompt, cwd: _controllerDir }),
    });
    showToast(`AI 관리 실행: ${action}`);
    fetchJobs();
  } catch (err) {
    showToast(`실행 실패: ${err.message}`, 'error');
  } finally {
    if (btn) btn.disabled = false;
  }
}
