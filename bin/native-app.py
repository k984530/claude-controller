#!/usr/bin/env python3
"""
Claude Controller — 웹 서버 실행 + 브라우저 자동 오픈
SSL/HTTPS 지원 + 토큰 인증
"""
import http.server
import os
import ssl
import subprocess
import sys
import time
import webbrowser
from pathlib import Path

CONTROLLER_DIR = Path(__file__).resolve().parent.parent
SERVICE_SCRIPT = CONTROLLER_DIR / "service" / "controller.sh"
PID_FILE = CONTROLLER_DIR / "service" / "controller.pid"
LOGS_DIR = CONTROLLER_DIR / "logs"
PORT = int(os.environ.get("PORT", 8420))


def is_service_running():
    if not PID_FILE.exists():
        return False, None
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, 0)
        return True, pid
    except (ValueError, ProcessLookupError, PermissionError, OSError):
        return False, None


def main():
    for d in ["logs", "queue", "sessions", "uploads", "data", "certs"]:
        (CONTROLLER_DIR / d).mkdir(parents=True, exist_ok=True)

    # 서비스 시작
    ok, pid = is_service_running()
    if not ok:
        log_fh = open(LOGS_DIR / "service.log", "a")
        subprocess.Popen(["bash", str(SERVICE_SCRIPT), "start"],
            stdout=log_fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True, cwd=str(CONTROLLER_DIR))
        log_fh.close()
        for _ in range(30):
            time.sleep(0.1)
            ok, pid = is_service_running()
            if ok:
                break

    # 웹 모듈 임포트
    sys.path.insert(0, str(CONTROLLER_DIR / "web"))
    from server import ControllerHandler
    from config import SSL_CERT, SSL_KEY, PUBLIC_URL
    from auth import generate_token

    # 토큰 생성 (매 시작 시 새로 발급)
    token = generate_token()

    # SSL 인증서 확인
    use_ssl = os.path.isfile(SSL_CERT) and os.path.isfile(SSL_KEY)
    scheme = "https" if use_ssl else "http"

    server = http.server.HTTPServer(("127.0.0.1", PORT), ControllerHandler)

    if use_ssl:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(SSL_CERT, SSL_KEY)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)

    # 시작 배너
    print(f"""
  ┌──────────────────────────────────────────────┐
  │  Claude Controller                           │
  ├──────────────────────────────────────────────┤
  │  API   : {scheme}://localhost:{PORT:<24s}│
  │  App   : {PUBLIC_URL:<35s}│
  │  SSL   : {'ON' if use_ssl else 'OFF (HTTP 모드)':<35s}│
  ├──────────────────────────────────────────────┤
  │  Auth Token (아래 토큰을 프론트엔드에 입력):  │
  │  {token:<43s}│
  ├──────────────────────────────────────────────┤
  │  종료  : Ctrl+C                              │
  └──────────────────────────────────────────────┘
""")

    if not use_ssl:
        print(f"  [참고] HTTPS를 사용하려면 mkcert로 인증서를 생성하세요:")
        print(f"    mkcert -install && mkcert -cert-file certs/localhost+1.pem \\")
        print(f"      -key-file certs/localhost+1-key.pem localhost 127.0.0.1\n")

    webbrowser.open(PUBLIC_URL)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  종료됨.")
        server.server_close()


if __name__ == "__main__":
    main()
