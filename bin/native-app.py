#!/usr/bin/env python3
"""
Controller Native App — pywebview 기반 데스크톱 애플리케이션
기존 웹 서버(server.py)를 백그라운드 스레드로 내장 실행하고,
macOS 네이티브 윈도우(WKWebView)에 표시한다.
"""

import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# ── 경로 설정 ──────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
CONTROLLER_DIR = SCRIPT_DIR.parent
WEB_DIR = CONTROLLER_DIR / "web"
SERVICE_SCRIPT = CONTROLLER_DIR / "service" / "controller.sh"
PID_FILE = CONTROLLER_DIR / "service" / "controller.pid"
LOGS_DIR = CONTROLLER_DIR / "logs"
QUEUE_DIR = CONTROLLER_DIR / "queue"
SESSIONS_DIR = CONTROLLER_DIR / "sessions"
WORKTREES_DIR = CONTROLLER_DIR / "worktrees"

# 웹 서버 포트
PORT = int(os.environ.get("PORT", 8420))


def is_service_running():
    """컨트롤러 서비스 실행 여부 확인"""
    if not PID_FILE.exists():
        return False, None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False, None


def ensure_directories():
    """필수 디렉토리 생성"""
    for d in [LOGS_DIR, QUEUE_DIR, SESSIONS_DIR, WORKTREES_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def start_controller_service():
    """컨트롤러 백그라운드 서비스 시작"""
    running, pid = is_service_running()
    if running:
        return True, pid

    if not SERVICE_SCRIPT.exists():
        return False, None

    log_file = LOGS_DIR / "service.log"
    subprocess.Popen(
        ["bash", str(SERVICE_SCRIPT), "start"],
        stdout=open(log_file, "a"),
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
        cwd=str(CONTROLLER_DIR),
    )

    for _ in range(30):
        time.sleep(0.1)
        running, pid = is_service_running()
        if running:
            return True, pid
    return False, None


def is_port_in_use(port):
    """포트가 이미 사용 중인지 확인"""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_web_server():
    """웹 서버를 별도 스레드에서 실행. 이미 사용 중이면 건너뜀."""
    if is_port_in_use(PORT):
        return None  # 기존 서버 사용

    sys.path.insert(0, str(WEB_DIR))
    import http.server
    from server import ControllerHandler

    handler = ControllerHandler
    server = http.server.HTTPServer(("127.0.0.1", PORT), handler)
    server.daemon_threads = True

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def main():
    try:
        import webview
    except ImportError:
        print("[오류] pywebview가 설치되어 있지 않습니다.")
        print("  설치: pip3 install pywebview")
        sys.exit(1)

    # 외부 링크를 시스템 브라우저에서 열지 않도록 설정
    webview.settings['OPEN_EXTERNAL_LINKS_IN_BROWSER'] = False

    # 디렉토리 확인
    ensure_directories()

    # 컨트롤러 서비스 시작
    running, pid = is_service_running()
    if not running:
        ok, pid = start_controller_service()
        if ok:
            print(f"  [서비스] 시작됨 (PID: {pid})")
        else:
            print("  [경고] 서비스 자동 시작 실패")

    # 웹 서버 시작 (백그라운드 스레드)
    server = start_web_server()
    if server:
        print(f"  [웹서버] http://127.0.0.1:{PORT} 시작됨")
    else:
        print(f"  [웹서버] 포트 {PORT} 이미 사용 중 — 기존 서버에 연결합니다")

    # 잠깐 대기 (서버 기동)
    time.sleep(0.3)

    # 네이티브 윈도우 생성
    window = webview.create_window(
        title="Controller",
        url=f"http://127.0.0.1:{PORT}",
        width=1200,
        height=800,
        min_size=(800, 500),
        background_color="#0f1117",
        text_select=True,
    )

    # 윈도우 시작 (블로킹 — 메인 스레드)
    webview.start(
        debug=False,
        gui="cocoa",  # macOS 네이티브
    )

    print("  [종료] Controller 앱을 종료합니다.")


if __name__ == "__main__":
    main()
