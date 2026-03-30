#!/usr/bin/env bash
# ============================================================
# meta-io.sh — .meta 파일 원자적 append 헬퍼
# 기존 meta 파일 끝에 KEY=VALUE 행을 추가한다.
# temp → mv 패턴으로 부분 쓰기(partial write)를 방지한다.
# ============================================================

# _meta_append <meta_file> <line1> [line2 ...]
#   meta 파일 끝에 여러 줄을 원자적으로 추가한다.
#   예: _meta_append "$meta_file" "UUID=${uuid}" "CWD=${cwd}"
_meta_append() {
  local meta_file="$1"
  shift
  [[ -f "$meta_file" ]] || return 1
  local _tmp="${meta_file}.tmp.$$"
  {
    cat "$meta_file"
    for _line in "$@"; do
      echo "$_line"
    done
  } > "$_tmp" && mv -f "$_tmp" "$meta_file"
}
