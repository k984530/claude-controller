#!/bin/bash
# post-bash-error-context.sh — PostToolUse hook: Bash 실패 시 자동 진단 피드백
#
# 동작:
#   1. Bash 도구 실행 결과에서 exit code / 에러 패턴 감지
#   2. 일반적 에러 유형별 진단 힌트를 Claude에게 전달
#   3. Claude가 자가 복구할 수 있도록 actionable context 제공
#
# stdin: { "tool_name": "Bash", "tool_input": {"command": "..."}, "tool_output": "..." }

set -euo pipefail

INPUT=$(cat)

# ── 출력 추출 (CMD / OUTPUT 분리) ──
PARSED=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    inp = d.get('tool_input', {})
    if isinstance(inp, str):
        import json as j2; inp = j2.loads(inp)
    cmd = inp.get('command', '')[:150].replace('\n',' ')
    out = str(d.get('tool_output', ''))[-500:].replace('\n',' ')
    print(cmd + '|||' + out)
except: print('|||')
" 2>/dev/null)

CMD="${PARSED%%|||*}"
OUTPUT="${PARSED#*|||}"

[[ -z "$OUTPUT" ]] && exit 0

# ── 에러 패턴 매칭 및 진단 힌트 ──
HINT=""

# ModuleNotFoundError / ImportError
if echo "$OUTPUT" | grep -qiE 'ModuleNotFoundError|ImportError|No module named'; then
  MODULE=$(echo "$OUTPUT" | sed -n "s/.*No module named '\{0,1\}\([^'\"]*\).*/\1/p" | head -1)
  HINT="Python 모듈 누락: '${MODULE:-unknown}'. pip install 또는 가상환경 확인 필요"
fi

# Permission denied
if echo "$OUTPUT" | grep -qi 'Permission denied'; then
  HINT="권한 부족. 파일 권한 확인 (ls -la) 또는 실행 비트 설정 필요"
fi

# command not found
if echo "$OUTPUT" | grep -qiE 'command not found'; then
  MISSING=$(echo "$OUTPUT" | sed -n 's/.*\([^ ]*\): command not found.*/\1/p' | head -1)
  HINT="명령어 '${MISSING:-unknown}' 미설치. brew install 또는 PATH 확인 필요"
fi

# port already in use
if echo "$OUTPUT" | grep -qiE 'Address already in use|EADDRINUSE|port.*in use'; then
  HINT="포트 충돌. lsof -i :PORT 로 점유 프로세스 확인 후 종료"
fi

# git conflict
if echo "$OUTPUT" | grep -qiE 'CONFLICT|merge conflict|Automatic merge failed'; then
  HINT="Git 머지 충돌 발생. 충돌 파일을 수동으로 해결한 뒤 git add + commit"
fi

# disk space
if echo "$OUTPUT" | grep -qiE 'No space left|ENOSPC|disk full'; then
  HINT="디스크 공간 부족. du -sh /tmp, docker system prune 등으로 정리"
fi

# syntax error (Python traceback)
if echo "$OUTPUT" | grep -qiE 'SyntaxError:|IndentationError:'; then
  HINT="Python 구문 오류. 해당 파일의 들여쓰기/괄호/따옴표 확인 필요"
fi

# Connection refused / timeout
if echo "$OUTPUT" | grep -qiE 'Connection refused|ECONNREFUSED|timed out|ETIMEDOUT'; then
  HINT="연결 실패. 대상 서비스 실행 여부 확인, 방화벽/프록시 점검"
fi

# FileNotFoundError / No such file
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'FileNotFoundError|No such file or directory'; then
  MISSING_F=$(echo "$OUTPUT" | sed -n "s/.*No such file or directory: *'\{0,1\}\([^'\"]*\).*/\1/p" | head -1)
  HINT="파일/디렉토리 없음: '${MISSING_F:-unknown}'. 경로 오타 또는 mkdir -p 필요"
fi

# npm / yarn 에러
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'npm ERR!|ERR_PNPM_|yarn error'; then
  HINT="패키지 매니저 에러. node_modules 삭제 후 재설치, 또는 package.json 의존성 확인"
fi

# OOM / 메모리 부족
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'OOMKilled|JavaScript heap out of memory|MemoryError|Cannot allocate memory'; then
  HINT="메모리 부족. NODE_OPTIONS=--max-old-space-size 조정 또는 배치 크기 축소"
fi

# DNS resolution failure
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'ENOTFOUND|Name or service not known|Could not resolve host|getaddrinfo'; then
  HINT="DNS 해석 실패. 호스트명/URL 확인, 네트워크 연결 점검"
fi

# TypeScript compilation error
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'error TS[0-9]+:|Cannot find module.*\.ts'; then
  HINT="TypeScript 컴파일 에러. 타입 정의 또는 tsconfig.json 설정 확인"
fi

# Docker daemon not running
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'Cannot connect to the Docker daemon|docker daemon.*not running|Is the docker daemon running'; then
  HINT="Docker 데몬 미실행. Docker Desktop 시작 또는 dockerd 실행 필요"
fi

# Git authentication failure
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'Authentication failed|could not read Username|fatal: repository.*not found|Permission denied.*publickey'; then
  HINT="Git 인증 실패. SSH 키 또는 PAT 토큰 설정 확인 (gh auth login / ssh-add)"
fi

# JSON parse error (jq, node, python json)
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'parse error|Unexpected token|json.decoder.JSONDecodeError|JSON\.parse'; then
  HINT="JSON 파싱 오류. 입력 데이터 형식 확인 (잘린 응답, 빈 문자열 등)"
fi

# Segfault / core dump
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'Segmentation fault|core dumped|SIGSEGV|Bus error'; then
  HINT="세그폴트/코어덤프. 메모리 접근 오류 — 네이티브 확장 또는 바이너리 호환성 확인"
fi

# SSL/TLS certificate error
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'SSL.*certificate|CERT_|certificate verify failed|UNABLE_TO_VERIFY_LEAF_SIGNATURE|self.signed'; then
  HINT="SSL 인증서 오류. CA 번들 확인, 자체 서명 인증서인 경우 NODE_TLS_REJECT_UNAUTHORIZED 또는 --insecure 검토"
fi

# Rate limiting / HTTP 429
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE '429|Too Many Requests|rate.limit|quota.exceeded|throttl'; then
  HINT="Rate limit 초과. 요청 간격 조절, 백오프/재시도 로직 적용, API 할당량 확인"
fi

# Git lock file (.git/index.lock)
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'Unable to create.*\.lock|index\.lock.*exists|Another git process'; then
  HINT="Git 잠금 파일 존재. 다른 git 프로세스 확인 후 rm .git/index.lock 검토"
fi

# pytest collection error
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'ERROR collecting|CollectionError|ImportMismatchError|in collection'; then
  HINT="pytest 수집 오류. __init__.py 누락, conftest 충돌, 또는 import 경로 불일치 확인"
fi

# Encoding / Unicode error
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'UnicodeDecodeError|UnicodeEncodeError|codec can.t|invalid byte|charmap'; then
  HINT="인코딩 오류. 파일 인코딩 확인 (file -I), open(..., encoding='utf-8') 명시 또는 errors='replace' 사용"
fi

# RecursionError / maximum recursion depth
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'RecursionError|maximum recursion depth exceeded'; then
  HINT="재귀 깊이 초과. 무한 재귀 루프 확인, sys.setrecursionlimit() 또는 반복문 전환 검토"
fi

# VersionConflict / DistributionNotFound (패키지 버전 충돌)
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'VersionConflict|DistributionNotFound|pkg_resources.*not found|version.*conflict'; then
  HINT="패키지 버전 충돌. pip list로 설치 버전 확인, requirements.txt 의존성 정합성 점검"
fi

# EPERM / Operation not permitted
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'EPERM|Operation not permitted'; then
  HINT="작업 거부(EPERM). 파일 잠금, SIP(macOS), 또는 권한 설정 확인"
fi

# AssertionError (테스트/검증 실패)
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'AssertionError|assert.*failed|assertion.*error'; then
  HINT="Assertion 실패. 기대값 vs 실제값 확인, 테스트 데이터 또는 로직 점검"
fi

# KeyError / AttributeError (Python 자주 발생)
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'KeyError:|AttributeError:'; then
  HINT="Python KeyError/AttributeError. 딕셔너리 키 존재 여부(.get()) 또는 객체 속성 확인"
fi

# EMFILE / ENFILE (열린 파일 수 초과)
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'EMFILE|ENFILE|Too many open files'; then
  HINT="열린 파일 핸들 초과. ulimit -n 확인, 파일 디스크립터 누수 또는 워치 리밋 조정"
fi

# TimeoutError / asyncio.TimeoutError
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'TimeoutError|asyncio\.TimeoutError|timed?\s*out|ETIMEOUT'; then
  HINT="타임아웃 발생. 네트워크/서비스 응답 지연 확인, 타임아웃 값 조정 검토"
fi

# BrokenPipeError / EPIPE
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'BrokenPipeError|EPIPE|Broken pipe'; then
  HINT="Broken pipe. 파이프 소비자가 조기 종료됨 — 출력 대상 프로세스 확인"
fi

# EACCES (npm 등 접근 거부)
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'EACCES|access.*denied'; then
  HINT="접근 거부(EACCES). node_modules 권한 확인, --prefix 또는 nvm 사용 검토"
fi

# ValueError (Python 데이터 변환 실패)
if [[ -z "$HINT" ]] && echo "$OUTPUT" | grep -qiE 'ValueError:'; then
  HINT="Python ValueError. 입력 데이터 형식/범위 검증 필요 — int(), float() 변환 대상 확인"
fi

# ── 결과 출력 ──
if [[ -n "$HINT" ]]; then
  SAFE_HINT=$(echo "$HINT" | tr '\n' ' ' | sed 's/"/\\"/g' | head -c 300)
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PostToolUse\",\"additionalContext\":\"ERROR CONTEXT: $SAFE_HINT\"}}"
fi
