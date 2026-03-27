#!/usr/bin/env bash
# ============================================================
# 실행 엔진 — 서비스 데몬 패턴
# FIFO로 수신된 JSON 메시지를 파싱하여 claude -p 를 백그라운드로 실행합니다.
# 모든 실행은 비동기이며, 결과는 $LOGS_DIR/job_<id>.out 에 저장됩니다.
# ============================================================

# ── claude -p 실행 (내부 전용) ─────────────────────────────
# JSON에서 파싱한 개별 값을 받아 claude CLI를 호출합니다.
# eval 대신 인자 배열을 직접 사용하여 글로브 확장·인젝션 방지
_run_claude() {
  local prompt="$1"
  local cwd="$2"
  local out_file="$3"
  local session_mode="${4:-}"
  local session_id="${5:-}"

  local args=()
  args+=(-p "$prompt")
  args+=(--output-format json)

  # 모든 도구 권한 허용
  if [[ -n "${DEFAULT_ALLOWED_TOOLS:-}" ]]; then
    args+=(--allowedTools "$DEFAULT_ALLOWED_TOOLS")
  fi

  # 모델 지정
  if [[ -n "${DEFAULT_MODEL:-}" ]]; then
    args+=(--model "$DEFAULT_MODEL")
  fi

  # 시스템 프롬프트 추가
  if [[ -n "${APPEND_SYSTEM_PROMPT:-}" ]]; then
    args+=(--append-system-prompt "$APPEND_SYSTEM_PROMPT")
  fi

  # 작업 디렉토리 — JSON에서 받은 cwd 우선, 없으면 글로벌 WORKING_DIR
  local effective_cwd="${cwd:-${WORKING_DIR:-}}"
  if [[ -n "$effective_cwd" ]]; then
    args+=(--cwd "$effective_cwd")
  fi

  # 세션 이어가기 플래그
  case "${session_mode}" in
    continue)
      args+=(--continue)
      ;;
    resume)
      if [[ -n "$session_id" ]]; then
        args+=(--resume "$session_id")
      fi
      ;;
  esac

  # 직접 실행 — 배열로 안전하게 호출
  "$CLAUDE_BIN" "${args[@]}" > "$out_file" 2>&1
}

# ── JSON 기반 실행 (서비스 데몬의 진입점) ──────────────────
# FIFO에서 수신한 JSON 문자열을 파싱하여 백그라운드로 claude -p 실행
#
# JSON 필드:
#   id      (필수) — 작업 식별자. 외부에서 부여한 고유 ID
#   prompt  (필수) — claude에 전달할 프롬프트
#   cwd     (선택) — 작업 디렉토리. 미지정 시 WORKING_DIR 사용
#   session (선택) — "continue" | "resume:<session_id>"
#
# 반환: stdout에 job_id 출력
execute_from_json() {
  local json_string="$1"

  # ── JSON 유효성 검사 ──
  if ! echo "$json_string" | jq empty 2>/dev/null; then
    echo "[오류] 유효하지 않은 JSON: $json_string" >&2
    return 1
  fi

  # ── 필수 필드 파싱 ──
  local job_id prompt cwd session_raw images_json
  job_id=$(echo "$json_string" | jq -r '.id // empty')
  prompt=$(echo "$json_string" | jq -r '.prompt // empty')
  cwd=$(echo "$json_string" | jq -r '.cwd // empty')
  session_raw=$(echo "$json_string" | jq -r '.session // empty')
  images_json=$(echo "$json_string" | jq -r '.images // empty')

  if [[ -z "$job_id" ]]; then
    echo "[오류] JSON에 'id' 필드가 없습니다." >&2
    return 1
  fi

  if [[ -z "$prompt" ]]; then
    echo "[오류] JSON에 'prompt' 필드가 없습니다." >&2
    return 1
  fi

  # ── 첨부 이미지가 있으면 프롬프트에 경로 삽입 ──
  if [[ -n "$images_json" && "$images_json" != "null" ]]; then
    local img_count
    img_count=$(echo "$images_json" | jq -r 'length')
    if [[ "$img_count" -gt 0 ]]; then
      local img_lines=""
      for i in $(seq 0 $(( img_count - 1 ))); do
        local img_path
        img_path=$(echo "$images_json" | jq -r ".[$i]")
        img_lines="${img_lines}
- ${img_path}"
      done
      prompt="[첨부 파일 — Read 도구로 확인하세요]${img_lines}

${prompt}"
    fi
  fi

  # ── 세션 모드 분리 (예: "resume:abc-123") ──
  local session_mode="" session_id=""
  if [[ -n "$session_raw" ]]; then
    case "$session_raw" in
      resume:*)
        session_mode="resume"
        session_id="${session_raw#resume:}"
        ;;
      continue)
        session_mode="continue"
        ;;
      *)
        echo "[경고] 알 수 없는 session 값: $session_raw" >&2
        ;;
    esac
  fi

  # ── 최대 동시 작업 수 확인 ──
  local running_count=0
  for meta_file in "${LOGS_DIR}"/job_*.meta; do
    [[ -f "$meta_file" ]] || continue
    local STATUS=""
    STATUS=$(_get_meta_field "$meta_file" "STATUS")
    if [[ "$STATUS" == "running" ]]; then
      (( running_count++ )) || true
    fi
  done

  if [[ $running_count -ge $MAX_BACKGROUND_JOBS ]]; then
    echo "[오류] 최대 동시 작업 수($MAX_BACKGROUND_JOBS)에 도달. job_id=$job_id 거부됨" >&2
    return 1
  fi

  # ── Job 등록 (jobs.sh 모듈 사용) ──
  # job_register는 내부 카운터 ID를 반환하지만,
  # 외부 ID(job_id)를 파일명에 직접 사용하여 추적 일관성 확보
  local internal_id
  internal_id=$(job_register "$prompt")

  # 외부 ID ↔ 내부 ID 매핑 저장
  echo "$job_id" > "${LOGS_DIR}/job_${internal_id}.ext_id"

  local out_file="${LOGS_DIR}/job_${internal_id}.out"

  # ── 서브쉘에서 백그라운드 실행 ──
  (
    _run_claude "$prompt" "$cwd" "$out_file" "$session_mode" "$session_id"
    local exit_code=$?

    # 세션 ID 추출 (JSON 출력에서)
    if [[ -f "$out_file" ]]; then
      local sid
      sid=$(jq -r '.session_id // empty' "$out_file" 2>/dev/null)
      [[ -n "$sid" ]] && job_set_session "$internal_id" "$sid"
    fi

    # 완료 상태 갱신
    if [[ $exit_code -eq 0 ]]; then
      job_mark_done "$internal_id"
    else
      job_mark_failed "$internal_id"
    fi
  ) &

  local bg_pid=$!
  job_set_pid "$internal_id" "$bg_pid"

  # 호출자(서비스 데몬)에게 내부 ID 반환
  echo "$internal_id"
}
