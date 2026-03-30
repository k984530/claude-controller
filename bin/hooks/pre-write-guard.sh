#!/bin/bash
# pre-write-guard.sh — PreToolUse hook: 민감 파일 쓰기 차단
#
# 동작:
#   1. Write/Edit 대상 파일 경로 추출
#   2. .env, credentials, secrets 등 민감 파일 패턴 매칭
#   3. 매칭 시 차단 JSON 반환
#
# stdin: { "tool_name": "Write|Edit", "tool_input": {"file_path": "..."} }

set -euo pipefail

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    inp = d.get('tool_input', {})
    if isinstance(inp, str):
        import json as j2; inp = j2.loads(inp)
    print(inp.get('file_path', ''))
except: print('')
" 2>/dev/null)

[[ -z "$FILE_PATH" ]] && exit 0

BASENAME=$(basename "$FILE_PATH")
BLOCKED=""

# .env 파일 (환경 변수 / 시크릿)
if echo "$BASENAME" | grep -qE '^\.(env|env\.local|env\.production|env\.secret)$'; then
  BLOCKED=".env 파일 쓰기 차단 — 시크릿 유출 위험"
fi

# credentials / secrets 파일
if echo "$BASENAME" | grep -qiE '^(credentials|secrets|service.?account).*\.(json|yaml|yml|key|pem)$'; then
  BLOCKED="인증 정보 파일 쓰기 차단"
fi

# SSH 키
if echo "$FILE_PATH" | grep -qE '\.ssh/(id_|authorized_keys|known_hosts)'; then
  BLOCKED="SSH 키 파일 쓰기 차단"
fi

# 인증서 비밀키
if echo "$BASENAME" | grep -qiE '\.(key|p12|pfx)$'; then
  BLOCKED="비밀키 파일 쓰기 차단"
fi

# .npmrc (npm auth 토큰 포함 가능)
if echo "$BASENAME" | grep -qE '^\.(npmrc|yarnrc)$'; then
  BLOCKED=".npmrc/.yarnrc 쓰기 차단 — 인증 토큰 유출 위험"
fi

# kubeconfig
if echo "$FILE_PATH" | grep -qE '(kubeconfig|\.kube/config)'; then
  BLOCKED="kubeconfig 쓰기 차단 — 클러스터 접근 정보"
fi

# AWS credentials / config
if echo "$FILE_PATH" | grep -qE '\.aws/(credentials|config)$'; then
  BLOCKED="AWS 자격증명 파일 쓰기 차단"
fi

# Docker config (registry auth)
if echo "$FILE_PATH" | grep -qE '\.docker/config\.json$'; then
  BLOCKED="Docker 레지스트리 인증 파일 쓰기 차단"
fi

# GitHub/GitLab 토큰 파일
if echo "$BASENAME" | grep -qiE '^\.(gitconfig|netrc|git-credentials)$'; then
  BLOCKED="Git 인증 파일 쓰기 차단"
fi

# .pypirc (PyPI 인증 토큰)
if echo "$BASENAME" | grep -qE '^\.pypirc$'; then
  BLOCKED=".pypirc 쓰기 차단 — PyPI 인증 토큰 유출 위험"
fi

# GCP 서비스 계정 키
if echo "$FILE_PATH" | grep -qE '\.config/gcloud/|application_default_credentials\.json'; then
  BLOCKED="GCP 인증 파일 쓰기 차단 — 서비스 계정 키 유출 위험"
fi

# Terraform 상태 파일 (인프라 시크릿 포함)
if echo "$BASENAME" | grep -qE '\.tfstate(\.backup)?$'; then
  BLOCKED="Terraform 상태 파일 쓰기 차단 — 인프라 시크릿 포함 가능"
fi

# HashiCorp Vault 토큰
if echo "$BASENAME" | grep -qiE '^\.?vault[-_]?token$'; then
  BLOCKED="Vault 토큰 파일 쓰기 차단 — 인프라 접근 키 유출 위험"
fi

# .htpasswd (Apache 인증 파일)
if echo "$BASENAME" | grep -qE '^\.htpasswd$'; then
  BLOCKED=".htpasswd 쓰기 차단 — 웹서버 인증 정보 유출 위험"
fi

# GPG 키 디렉토리
if echo "$FILE_PATH" | grep -qE '\.gnupg/(private-keys|secring|trustdb)'; then
  BLOCKED="GPG 비밀키 쓰기 차단 — 서명/암호화 키 유출 위험"
fi

# Firebase 서비스 계정 키
if echo "$BASENAME" | grep -qiE '^firebase.*service.?account.*\.json$|^firebase-adminsdk.*\.json$'; then
  BLOCKED="Firebase 서비스 계정 키 쓰기 차단 — 클라우드 접근 키 유출 위험"
fi

# .env 변형 (staging, development, test 등)
if echo "$BASENAME" | grep -qE '^\.env\.(staging|development|test|preview|ci)$'; then
  BLOCKED=".env 변형 파일 쓰기 차단 — 환경별 시크릿 유출 위험"
fi

# Kaggle API 키
if echo "$FILE_PATH" | grep -qE '\.kaggle/kaggle\.json$'; then
  BLOCKED="Kaggle API 키 파일 쓰기 차단 — 인증 정보 유출 위험"
fi

# age 암호화 키 파일
if echo "$BASENAME" | grep -qE '\.age$|^keys\.txt$' && echo "$FILE_PATH" | grep -qiE '(age|key|secret|crypt)'; then
  BLOCKED="age 키 파일 쓰기 차단 — 복호화 키 유출 위험"
fi

# 1Password / Bitwarden CLI 설정
if echo "$FILE_PATH" | grep -qE '\.op/config|\.config/Bitwarden'; then
  BLOCKED="패스워드 매니저 설정 쓰기 차단 — 볼트 접근 정보 유출 위험"
fi

# Stripe / 결제 키 파일
if echo "$BASENAME" | grep -qiE '^stripe.*\.json$|^(merchant|payment).*key'; then
  BLOCKED="결제 서비스 키 파일 쓰기 차단 — 결제 시크릿 유출 위험"
fi

if [[ -n "$BLOCKED" ]]; then
  echo "{\"hookSpecificOutput\":{\"hookEventName\":\"PreToolUse\",\"permissionDecision\":\"deny\",\"permissionDecisionReason\":\"WRITE GUARD: $BLOCKED\"}}"
fi
