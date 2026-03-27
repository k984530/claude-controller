"""
Controller Service — Checkpoint / Rewind 유틸리티
"""

import json
import os
import re
import signal
import subprocess
import time

from config import LOGS_DIR
from utils import parse_meta_file
from jobs import send_to_fifo


def get_job_checkpoints(job_id):
    """worktree의 git log에서 해당 job의 checkpoint 커밋 목록을 반환한다."""
    meta_file = LOGS_DIR / f"job_{job_id}.meta"
    if not meta_file.exists():
        return None, "작업을 찾을 수 없습니다"

    meta = parse_meta_file(meta_file)
    wt_path = meta.get("WORKTREE", "")
    if not wt_path or not os.path.isdir(wt_path):
        return [], None

    try:
        result = subprocess.run(
            ["git", "log", "--format=%H|%aI|%s", f"--grep=ckpt:{job_id}:"],
            cwd=wt_path, capture_output=True, text=True, timeout=10
        )
        checkpoints = []
        for line in result.stdout.strip().split("\n"):
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            hash_val, ts, msg = parts

            turn_match = re.search(rf"ckpt:{job_id}:(\d+)", msg)
            turn_num = int(turn_match.group(1)) if turn_match else 0

            diff_result = subprocess.run(
                ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", hash_val],
                cwd=wt_path, capture_output=True, text=True, timeout=5
            )
            files = [f for f in diff_result.stdout.strip().split("\n") if f]

            checkpoints.append({
                "hash": hash_val,
                "turn": turn_num,
                "timestamp": ts,
                "message": msg,
                "files_changed": len(files),
                "files": files[:10],
            })

        return checkpoints, None
    except (subprocess.TimeoutExpired, OSError) as e:
        return None, f"체크포인트 조회 실패: {e}"


def extract_conversation_context(out_file, max_chars=4000):
    """stream-json 출력에서 대화 컨텍스트를 추출한다."""
    if not out_file.exists():
        return ""

    parts = []
    turn = 0

    try:
        with open(out_file, "r") as f:
            for line in f:
                try:
                    evt = json.loads(line.strip())
                except json.JSONDecodeError:
                    continue

                evt_type = evt.get("type", "")
                if evt_type == "assistant":
                    turn += 1
                    msg = evt.get("message", {})
                    content = msg.get("content", [])

                    texts = [c.get("text", "")[:300] for c in content if c.get("type") == "text"]
                    tools = [c for c in content if c.get("type") == "tool_use"]

                    if texts:
                        parts.append(f"--- Turn {turn} ---")
                        parts.append("\n".join(texts))

                    for t in tools:
                        name = t.get("name", "?")
                        inp = str(t.get("input", ""))[:150]
                        parts.append(f"[Tool: {name}] {inp}")

                elif evt_type == "result":
                    r = evt.get("result", "")
                    if r:
                        parts.append(f"--- Result ---")
                        parts.append(r[:500])
    except OSError:
        pass

    full = "\n".join(parts)
    return full[:max_chars]


def rewind_job(job_id, checkpoint_hash, new_prompt):
    """job을 특정 checkpoint로 되돌리고 새 job을 디스패치한다."""
    meta_file = LOGS_DIR / f"job_{job_id}.meta"
    out_file = LOGS_DIR / f"job_{job_id}.out"

    if not meta_file.exists():
        return None, "작업을 찾을 수 없습니다"

    meta = parse_meta_file(meta_file)
    wt_path = meta.get("WORKTREE", "")

    if not wt_path or not os.path.isdir(wt_path):
        return None, "워크트리를 찾을 수 없습니다"

    # 실행 중이면 종료
    status = meta.get("STATUS", "")
    pid_str = meta.get("PID", "")
    if status == "running" and pid_str:
        try:
            os.kill(int(pid_str), signal.SIGTERM)
            time.sleep(1)
        except (ProcessLookupError, ValueError, OSError):
            pass

    # checkpoint로 reset
    try:
        subprocess.run(
            ["git", "reset", "--hard", checkpoint_hash],
            cwd=wt_path, capture_output=True, timeout=10, check=True
        )
    except subprocess.CalledProcessError as e:
        return None, f"체크포인트 복원 실패: {e}"

    # 대화 컨텍스트 추출
    context = extract_conversation_context(out_file)

    # 리와인드 프롬프트 구성
    if context:
        full_prompt = (
            f"[이전 작업 컨텍스트 — 아래는 이전 세션에서 수행된 작업 요약입니다]\n"
            f"{context}\n\n"
            f"[Rewind 지시사항]\n"
            f"파일 상태가 위 작업 중간의 체크포인트 시점으로 복원되었습니다.\n"
            f"이전 작업 내용을 참고하되, 이어서 다음을 수행하세요:\n\n"
            f"{new_prompt}"
        )
    else:
        full_prompt = new_prompt

    # FIFO로 새 job 전송 (기존 worktree 재사용)
    result, err = send_to_fifo(
        full_prompt,
        cwd=wt_path,
        reuse_worktree=wt_path,
    )

    if err:
        return None, err

    return {
        "rewound_from": job_id,
        "checkpoint": checkpoint_hash,
        "worktree": wt_path,
        "new_job": result,
    }, None
