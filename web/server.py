#!/usr/bin/env python3
"""
Controller Service — HTTP REST API 서버
native-app.py에서 `from server import ControllerHandler`로 임포트된다.

모듈 구조:
  config.py     — 경로 및 설정 상수
  utils.py      — 유틸리티 함수 (meta 파싱, 서비스 상태 등)
  jobs.py       — Job 관리 및 서비스 제어
  checkpoint.py — Checkpoint / Rewind 유틸리티
  handler.py    — HTTP REST API 핸들러 (ControllerHandler)
"""

# backward-compatible: native-app.py가 `from server import ControllerHandler`로 사용
from handler import ControllerHandler  # noqa: F401
from config import PORT  # noqa: F401
