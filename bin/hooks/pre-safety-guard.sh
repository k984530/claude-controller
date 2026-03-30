#!/bin/bash
# pre-safety-guard.sh — PreToolUse hook: 파괴적 git/bash 명령 차단
#
# 동작:
#   1. Bash 도구 호출 시 command를 추출
#   2. 파괴적 패턴 매칭 (force push, reset --hard, rm -rf 등)
#   3. 매칭 시 차단 JSON 반환 → Claude에게 거부 피드백
#
# stdin: { "tool_name": "Bash", "tool_input": {"command": "..."} }

set -euo pipefail

INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    inp = d.get('tool_input', {})
    if isinstance(inp, str):
        import json as j2; inp = j2.loads(inp)
    print(inp.get('command', ''))
except: print('')
" 2>/dev/null)

[[ -z "$COMMAND" ]] && exit 0

# ── 파괴적 패턴 목록 ──
BLOCKED=""

# git force push (main/master 보호)
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--force|git\s+push\s+-f'; then
  if echo "$COMMAND" | grep -qE '\b(main|master)\b'; then
    BLOCKED="git force push to main/master 금지"
  fi
fi

# git reset --hard
if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard'; then
  BLOCKED="git reset --hard 감지 — 커밋되지 않은 변경사항이 사라질 수 있음"
fi

# rm -rf on project root or broad paths
if echo "$COMMAND" | grep -qE 'rm\s+-rf\s+(/|~|\.\.|\.(/|$))'; then
  BLOCKED="rm -rf 위험 경로 감지"
fi

# git clean -f (untracked 파일 삭제)
if echo "$COMMAND" | grep -qE 'git\s+clean\s+-[a-zA-Z]*f'; then
  BLOCKED="git clean -f 감지 — untracked 파일이 삭제됨"
fi

# git checkout . (모든 변경 폐기)
if echo "$COMMAND" | grep -qE 'git\s+checkout\s+\.\s*$'; then
  BLOCKED="git checkout . 감지 — 모든 변경사항 폐기"
fi

# git branch -D (강제 브랜치 삭제)
if echo "$COMMAND" | grep -qE 'git\s+branch\s+-[a-zA-Z]*D'; then
  BLOCKED="git branch -D 감지 — 브랜치 강제 삭제 위험"
fi

# git restore . (모든 변경 폐기)
if echo "$COMMAND" | grep -qE 'git\s+restore\s+\.\s*$'; then
  BLOCKED="git restore . 감지 — 모든 변경사항 폐기"
fi

# chmod 777 (과도한 권한)
if echo "$COMMAND" | grep -qE 'chmod\s+777'; then
  BLOCKED="chmod 777 감지 — 과도한 파일 권한 설정"
fi

# SQL 파괴 명령 (DROP, TRUNCATE)
if echo "$COMMAND" | grep -qiE '(DROP\s+(TABLE|DATABASE)|TRUNCATE\s+TABLE)'; then
  BLOCKED="SQL 파괴 명령 감지 (DROP/TRUNCATE)"
fi

# --no-verify (hook 우회 방지)
if echo "$COMMAND" | grep -qE 'git\s+.*--no-verify'; then
  BLOCKED="--no-verify 감지 — git hook 우회 금지"
fi

# curl/wget pipe-to-shell (원격 코드 실행 위험)
if echo "$COMMAND" | grep -qE '(curl|wget)\s.*\|\s*(bash|sh|zsh|python|perl|ruby)'; then
  BLOCKED="pipe-to-shell 감지 — 원격 스크립트 직접 실행 금지"
fi

# eval with variable expansion (코드 인젝션)
if echo "$COMMAND" | grep -qE 'eval\s+"\$|eval\s+\$'; then
  BLOCKED="eval \$VAR 감지 — 변수 eval은 코드 인젝션 위험"
fi

# sudo (불필요한 권한 상승)
if echo "$COMMAND" | grep -qE '^\s*sudo\s'; then
  BLOCKED="sudo 감지 — 프로젝트 내 권한 상승 불필요"
fi

# kill -9 (프로세스 강제 종료)
if echo "$COMMAND" | grep -qE 'kill\s+-9\s'; then
  BLOCKED="kill -9 감지 — SIGKILL 대신 graceful shutdown 사용"
fi

# fork bomb / 재귀 shell
if echo "$COMMAND" | grep -qE ':\(\)\s*\{.*\|.*&\s*\}\s*;'; then
  BLOCKED="fork bomb 패턴 감지"
fi

# mkfs / disk format
if echo "$COMMAND" | grep -qE '(mkfs|fdisk|dd\s+if=)'; then
  BLOCKED="디스크 포맷/쓰기 명령 감지"
fi

# > /etc/ 또는 > /System/ (시스템 파일 덮어쓰기)
if echo "$COMMAND" | grep -qE '>\s*/(etc|System|usr/lib)/'; then
  BLOCKED="시스템 경로 직접 쓰기 감지"
fi

# npm publish (사고 배포 방지)
if echo "$COMMAND" | grep -qE 'npm\s+publish(\s|$)'; then
  BLOCKED="npm publish 감지 — 의도치 않은 패키지 배포 위험"
fi

# docker system prune -a --volumes (볼륨 데이터 소실)
if echo "$COMMAND" | grep -qE 'docker\s+(system\s+prune\s+-a|volume\s+prune\s+-f)'; then
  BLOCKED="Docker 볼륨/시스템 전체 정리 감지 — 데이터 소실 위험"
fi

# env / printenv (환경변수 전체 덤프 → 시크릿 노출)
if echo "$COMMAND" | grep -qE '^\s*(env|printenv)\s*$'; then
  BLOCKED="env 전체 덤프 감지 — 시크릿 노출 위험. 개별 변수 조회 사용"
fi

# history -c (히스토리 삭제)
if echo "$COMMAND" | grep -qE 'history\s+-c'; then
  BLOCKED="history -c 감지 — 감사 이력 삭제 금지"
fi

# git stash drop --all (모든 stash 삭제)
if echo "$COMMAND" | grep -qE 'git\s+stash\s+(drop\s+--all|clear)'; then
  BLOCKED="git stash clear/drop --all 감지 — 모든 stash 데이터 소실"
fi

# launchctl unload/bootout (macOS 서비스 중단)
if echo "$COMMAND" | grep -qE 'launchctl\s+(unload|bootout|remove)'; then
  BLOCKED="launchctl 서비스 조작 감지 — 시스템 서비스 중단 위험"
fi

# defaults delete (macOS 설정 삭제)
if echo "$COMMAND" | grep -qE 'defaults\s+delete'; then
  BLOCKED="defaults delete 감지 — macOS 설정 삭제 위험"
fi

# diskutil (디스크 조작)
if echo "$COMMAND" | grep -qE 'diskutil\s+(erase|partition|unmount|apfs\s+delete)'; then
  BLOCKED="diskutil 파괴적 명령 감지 — 디스크 데이터 소실 위험"
fi

# xattr -cr (quarantine 일괄 제거)
if echo "$COMMAND" | grep -qE 'xattr\s+-[a-zA-Z]*c[a-zA-Z]*r?\s+/'; then
  BLOCKED="xattr 일괄 제거 감지 — Gatekeeper 보호 해제 위험"
fi

# pip --break-system-packages (시스템 Python 오염)
if echo "$COMMAND" | grep -qE 'pip[3]?\s+install\s+.*--break-system-packages'; then
  BLOCKED="--break-system-packages 감지 — 시스템 Python 패키지 오염 위험"
fi

# git push --delete (원격 브랜치 삭제)
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*--delete'; then
  BLOCKED="git push --delete 감지 — 원격 브랜치/태그 삭제 위험"
fi

# crontab -r (모든 cron job 일괄 삭제)
if echo "$COMMAND" | grep -qE 'crontab\s+-r'; then
  BLOCKED="crontab -r 감지 — 모든 크론 작업 일괄 삭제 위험"
fi

# iptables -F / pfctl -F (방화벽 규칙 전체 삭제)
if echo "$COMMAND" | grep -qE '(iptables|ip6tables)\s+-F|pfctl\s+-[Ff]'; then
  BLOCKED="방화벽 규칙 초기화 감지 — 네트워크 보안 정책 삭제 위험"
fi

# npm link (글로벌 심링크 — 의도치 않은 사이드 이펙트)
if echo "$COMMAND" | grep -qE 'npm\s+link(\s|$)'; then
  BLOCKED="npm link 감지 — 글로벌 심링크 생성은 다른 프로젝트에 영향"
fi

# pip install --user (venv 밖에서 사용자 전역 설치)
if echo "$COMMAND" | grep -qE 'pip[3]?\s+install\s+.*--user'; then
  BLOCKED="pip install --user 감지 — venv 없이 전역 설치는 충돌 위험"
fi

# scp/rsync to remote (외부 서버 전송 — 데이터 유출)
if echo "$COMMAND" | grep -qE '(scp|rsync)\s+.*:'; then
  BLOCKED="scp/rsync 외부 전송 감지 — 민감 데이터 유출 위험"
fi

# python http.server / SimpleHTTPServer (포트 노출 — 데이터 접근 허용)
if echo "$COMMAND" | grep -qE 'python[23]?\s+-m\s+(http\.server|SimpleHTTPServer)'; then
  BLOCKED="HTTP 서버 감지 — 로컬 파일 외부 노출 위험"
fi

# nc -l / ncat -l (포트 리스닝 — 의도치 않은 백도어)
if echo "$COMMAND" | grep -qE '(nc|ncat|netcat)\s+.*-[a-zA-Z]*l'; then
  BLOCKED="nc listen 감지 — 포트 리스닝은 보안 위험"
fi

# chown -R on broad paths (재귀 소유권 변경)
if echo "$COMMAND" | grep -qE 'chown\s+-[a-zA-Z]*R\s+.*\s+(/|/usr|/var|/home|~)'; then
  BLOCKED="chown -R 광범위 경로 감지 — 시스템 파일 소유권 변경 위험"
fi

# export PATH= 덮어쓰기 (PATH 하이재킹 — 기존 경로 소실)
if echo "$COMMAND" | grep -qE 'export\s+PATH=[^$]'; then
  BLOCKED="export PATH= 감지 — 기존 PATH 덮어쓰기 위험. PATH=\$PATH:... 사용"
fi

# ssh-keygen 기존 키 덮어쓰기
if echo "$COMMAND" | grep -qE 'ssh-keygen\s.*-f\s+~/.ssh/id_'; then
  BLOCKED="ssh-keygen 기존 키 덮어쓰기 감지 — 키 교체 시 접근 불가 위험"
fi

# git filter-branch / git-filter-repo (히스토리 전체 재작성)
if echo "$COMMAND" | grep -qE 'git\s+(filter-branch|filter-repo)'; then
  BLOCKED="git filter-branch 감지 — 전체 히스토리 재작성은 되돌리기 어려움"
fi

# truncate (파일 내용 제거)
if echo "$COMMAND" | grep -qE 'truncate\s+(-s\s*0|--size\s*[=]?\s*0)'; then
  BLOCKED="truncate -s 0 감지 — 파일 내용 전체 삭제 위험"
fi

# shred (보안 삭제 — 복구 불가능)
if echo "$COMMAND" | grep -qE 'shred\s'; then
  BLOCKED="shred 감지 — 파일 복구 불가능한 삭제 위험"
fi

# spctl --master-disable (macOS Gatekeeper 비활성화)
if echo "$COMMAND" | grep -qE 'spctl\s+--master-disable'; then
  BLOCKED="Gatekeeper 비활성화 감지 — macOS 보안 정책 해제 위험"
fi

# codesign --remove-signature (코드 서명 제거)
if echo "$COMMAND" | grep -qE 'codesign\s+--remove-signature'; then
  BLOCKED="codesign 서명 제거 감지 — 앱 무결성 보증 해제 위험"
fi

# csrutil disable (SIP 비활성화 시도)
if echo "$COMMAND" | grep -qE 'csrutil\s+disable'; then
  BLOCKED="SIP 비활성화 시도 감지 — macOS 시스템 무결성 보호 해제 위험"
fi

# open -a Terminal.app / osascript 'do shell script' (권한 우회 시도)
if echo "$COMMAND" | grep -qE 'osascript\s.*do\s+shell\s+script'; then
  BLOCKED="osascript do shell script 감지 — AppleScript 경유 권한 우회 위험"
fi

# ── 차단 결과 ──
if [[ -n "$BLOCKED" ]]; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"SAFETY GUARD: $BLOCKED\"}}"
fi
