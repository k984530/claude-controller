# Controller Service — 문제점 및 개선점 분석

> 분석 일자: 2026-03-27
> 대상 범위: `controller/` 전체 (bin, lib, service, web)

---

## 1. 보안 취약점 (Critical)

### 1.1 `source "$meta_file"` — 쉘 인젝션

**위치:** `lib/jobs.sh:81,122,189`, `lib/worktree.sh:79,112`, `service/controller.sh:126`

`.meta` 파일을 `source` 명령으로 직접 실행한다. 프롬프트에 쉘 메타문자가 포함되면 **임의 코드가 실행**된다.

```bash
# 현재 방식 — 위험
source "$meta_file"

# 예: 프롬프트가 아래와 같으면 메타파일 source 시 rm 실행됨
# PROMPT='hello'; rm -rf /tmp/test; echo '
```

**개선:** `grep` + 패턴 매칭으로 개별 필드를 추출하거나, 안전한 파서 함수를 사용해야 한다.

```bash
# 안전한 방식
_get_meta_field() {
  local file="$1" key="$2"
  grep "^${key}=" "$file" | head -1 | sed "s/^${key}=//" | sed "s/^['\"]//;s/['\"]$//"
}
STATUS=$(_get_meta_field "$meta_file" "STATUS")
```

---

### 1.2 `eval "$callback"` — 원격 코드 실행

**위치:** `service/controller.sh:235`

FIFO로 수신한 JSON의 `callback` 필드를 `eval`로 직접 실행한다. FIFO에 쓰기 가능한 누구나 시스템에서 임의 명령을 실행할 수 있다.

```bash
# 현재 — 위험
eval "$callback" 2>>"$SERVICE_LOG"
```

**개선:** callback 기능을 제거하거나, 허용된 명령 화이트리스트 방식으로 제한해야 한다.

---

### 1.3 CORS `Access-Control-Allow-Origin: *`

**위치:** `web/server.py:283`

모든 도메인에서 API 호출이 가능하다. 브라우저에서 악의적인 웹페이지가 `localhost:8420/api/send`를 호출하여 프롬프트를 주입할 수 있다.

**개선:** `127.0.0.1` / `localhost`만 허용하거나, 토큰 기반 인증을 추가한다.

---

### 1.4 FIFO 파이프 권한 미설정

**위치:** `service/controller.sh:273`

`mkfifo` 시 권한을 명시하지 않아 기본 umask에 따라 다른 로컬 사용자도 쓸 수 있다.

```bash
# 현재
mkfifo "$FIFO_PATH"

# 개선
mkfifo -m 600 "$FIFO_PATH"
```

---

## 2. 아키텍처 문제

### 2.1 동일 로직 3중 복제

아래 함수/로직이 **서로 독립적으로 3곳에 구현**되어 있다:

| 기능 | `bin/tui` (Python) | `web/server.py` (Python) | `bin/native-app.py` (Python) |
|------|-----|-----|-----|
| `parse_meta_file()` | O | O | - |
| `is_service_running()` | O | O | O |
| `get_all_jobs()` | O | O | - |
| `get_job_result()` | O | O | - |
| `start_service()` | O | O | O |
| `send_to_fifo()` | O | O | - |

**문제:** 한 곳에서 버그를 수정해도 나머지 2곳에는 반영되지 않는다.

**개선:** 공통 모듈(`lib/controller_core.py`)을 만들고 TUI, 웹 서버, 네이티브 앱 모두 import하여 사용한다.

---

### 2.2 `executor.sh` 미사용 (Dead Code)

**위치:** `lib/executor.sh`

`controller.sh`가 `executor.sh`를 source하지만, 실제로는 `executor.sh`의 함수(`execute_from_json`, `_run_claude`)를 **전혀 호출하지 않는다**. `controller.sh`는 자체 `dispatch_job()` 함수에서 직접 claude를 실행한다.

또한 두 모듈 간 출력 형식이 다르다:
- `executor.sh`: `--output-format json`
- `controller.sh`: `--output-format stream-json`

**개선:** `executor.sh`를 삭제하거나, `dispatch_job()`이 `_run_claude()`를 호출하도록 통합한다.

---

### 2.3 `claude-sh` → 존재하지 않는 파일 참조

**위치:** `bin/claude-sh:13`

```bash
exec bash "${SCRIPT_DIR}/claude-shell.sh" "$@"
```

`claude-shell.sh` 파일이 프로젝트 내에 존재하지 않는다. 실행하면 항상 실패한다.

---

### 2.4 단일 파일 프론트엔드 (2,528줄)

**위치:** `web/static/index.html`

HTML, CSS, JavaScript가 하나의 파일에 2,528줄로 합쳐져 있다. 유지보수가 어렵고 캐싱 전략도 적용할 수 없다.

**개선:** 최소한 `style.css`, `app.js`, `index.html`로 분리한다.

---

## 3. 안정성 문제

### 3.1 Job 카운터 데드락 가능성

**위치:** `lib/jobs.sh:14-22`

`mkdir`로 스핀락을 구현하고 있는데, 프로세스가 락을 잡은 상태에서 크래시하면 **영구 데드락**이 발생한다.

```bash
# 크래시 시 .lock 디렉토리가 남아서 모든 신규 작업이 무한 대기
while ! mkdir "$lockfile" 2>/dev/null; do
  sleep 0.01  # 영원히 대기
done
```

**개선:** 타임아웃 + stale lock 감지를 추가한다.

```bash
local waited=0
while ! mkdir "$lockfile" 2>/dev/null; do
  sleep 0.01
  (( waited++ ))
  if [[ $waited -gt 500 ]]; then  # 5초 후 강제 해제
    rmdir "$lockfile" 2>/dev/null || true
  fi
done
```

---

### 3.2 FIFO 블로킹

**위치:** `bin/send:169`

```bash
echo "$PAYLOAD" > "$FIFO_PATH"
```

수신자(서비스)가 없으면 `echo`가 **무한 블로킹**된다. TUI(`bin/tui:153`)에서는 `O_NONBLOCK`을 사용하지만, CLI `send`에서는 사용하지 않는다.

**개선:** 타임아웃 또는 non-blocking 쓰기를 적용한다.

```bash
# 타임아웃 적용
timeout 5 bash -c "echo '$PAYLOAD' > '$FIFO_PATH'" || {
  echo "[오류] 서비스 응답 없음 (5초 타임아웃)" >&2
  exit 1
}
```

---

### 3.3 워치독 / 자동 재시작 없음

서비스가 예기치 않게 종료되면 수동으로 다시 시작해야 한다. TUI/웹 서버가 살아있어도 FIFO 수신자가 없어 모든 `send`가 실패한다.

**개선:** `launchd` plist 또는 간단한 감시 루프를 추가한다.

---

### 3.4 자식 프로세스 고아화

**위치:** `service/controller.sh:65-71`

서비스 종료 시 `wait`만 호출하고, 실행 중인 `claude` 프로세스에 시그널을 보내지 않는다. 서비스가 죽어도 claude 프로세스는 계속 실행된다.

**개선:** 프로세스 그룹 kill 또는 child PID 추적 후 일괄 종료를 구현한다.

---

### 3.5 `.meta` 파일 비원자적 쓰기

**위치:** `lib/jobs.sh:53-54` (sed -i), `service/controller.sh:145,153,154,201`

`sed -i`와 `echo >>` 가 동시에 같은 `.meta` 파일에 접근하면 데이터가 깨질 수 있다. 특히 `dispatch_job()`에서 job을 등록한 직후 서브쉘과 메인 프로세스가 동시에 `.meta`를 수정한다.

**개선:** 원자적 쓰기(temp → rename) 패턴을 사용한다.

---

## 4. 기능 문제

### 4.1 TUI 키 바인딩 충돌

**위치:** `bin/tui:714-722`

`k` 키가 "작업 종료(kill)"와 "위로 이동(vim 스타일)" 두 가지에 매핑되어 있다. 코드에서 이를 인지하고 있지만 해결하지 못한 상태다:

```python
elif key in (curses.KEY_UP, ord('k') if False else -999):
    # 위 화살표 — ord('k')는 kill에 매핑했으므로 화살표만
    pass
```

`if False`는 dead code이며, 결과적으로 `k`는 항상 kill로만 동작한다.

---

### 4.2 TUI에서 한글 입력 불가

**위치:** `bin/tui:498-501`

```python
if 32 <= key <= 126:
    self.input_buf += chr(key)
# 한글 등 멀티바이트 처리 — curses.get_wch 로 전환 필요시
# 지금은 ASCII 입력만 지원
```

한국어 프로젝트인데 한글 프롬프트를 입력할 수 없다.

**개선:** `stdscr.get_wch()`로 전환하여 유니코드 입력을 지원한다.

---

### 4.3 완료된 작업의 worktree가 자동 정리되지 않음

작업이 완료되어도 생성된 git worktree가 디스크에 남아있다. 수동으로 `worktree_remove`를 호출해야 한다.

**개선:** `dispatch_job()`의 서브쉘에서 작업 완료 시 자동으로 worktree를 정리하는 옵션을 추가한다.

---

## 5. 운영 문제

### 5.1 로그 로테이션 없음

`logs/service.log`와 `job_*.out` 파일이 무한히 쌓인다. 장기 운영 시 디스크 공간을 소모한다.

**개선:** 크기 기반 로테이션 또는 오래된 로그 자동 삭제를 구현한다.

---

### 5.2 하드코딩된 경로

| 파일 | 하드코딩 | 문제 |
|------|----------|------|
| `config.sh:7` | `/Applications/cmux.app/Contents/Resources/bin/claude` | cmux 앱 미설치 시 실패 |
| `bin/app-launcher.sh:5` | `/Users/choiwon/Desktop/Orchestration/controller` | 다른 사용자/경로에서 동작 불가 |

---

### 5.3 테스트 없음

전체 프로젝트에 테스트 파일이 하나도 없다. 핵심 기능(JSON 파싱, meta 파일 읽기, 작업 상태 전이)에 대한 단위 테스트가 필요하다.

---

### 5.4 에러 복구 메커니즘 없음

`.meta` 파일이 손상되거나 `.job_counter` 파일이 유실되면 서비스 전체가 오작동한다. 자가 진단 및 복구 로직이 없다.

---

## 6. 개선 우선순위

| 우선순위 | 항목 | 난이도 | 영향도 |
|:--------:|------|:------:|:------:|
| **P0** | 1.1 source 인젝션 수정 | 낮음 | 치명적 |
| **P0** | 1.2 eval callback 제거 | 낮음 | 치명적 |
| **P1** | 2.1 공통 Python 모듈 추출 | 중간 | 높음 |
| **P1** | 3.1 카운터 데드락 방지 | 낮음 | 높음 |
| **P1** | 3.5 meta 파일 원자적 쓰기 | 중간 | 높음 |
| **P2** | 1.3 CORS 제한 | 낮음 | 중간 |
| **P2** | 2.2 executor.sh 정리 | 낮음 | 중간 |
| **P2** | 3.2 FIFO 블로킹 해결 | 낮음 | 중간 |
| **P2** | 4.2 TUI 한글 입력 | 중간 | 중간 |
| **P3** | 2.3 claude-sh 데드 코드 제거 | 낮음 | 낮음 |
| **P3** | 2.4 프론트엔드 파일 분리 | 중간 | 낮음 |
| **P3** | 5.1 로그 로테이션 | 낮음 | 낮음 |
| **P3** | 5.3 테스트 추가 | 높음 | 높음 |
