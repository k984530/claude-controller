"""
Misc HTTP 핸들러 Mixin — handler.py에서 분리된 잡다한 엔드포인트

포함 엔드포인트:
  - GET/POST /api/auth/verify
  - GET  /api/stats
  - GET  /api/status
  - GET  /api/health
  - GET  /api/audit
  - POST /api/service/start, /api/service/stop
  - POST /api/webhooks/test
  - POST /api/logs/cleanup
"""

import time
from urllib.parse import parse_qs

from auth import verify_token
from config import FIFO_PATH, CONTROLLER_DIR
from utils import parse_ts, is_service_running
from health import collect_health
import config as _cfg
import audit as _audit_mod
import webhook as _webhook_mod


class MiscHandlerMixin:

    def _handle_auth_verify(self):
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if verify_token(token):
                return self._json_response({"valid": True})
        self._json_response({"valid": False}, 401)

    def _handle_stats(self, parsed):
        qs = parse_qs(parsed.query)
        period = qs.get("period", ["all"])[0]
        now = time.time()

        period_map = {"day": 86400, "week": 604800, "month": 2592000}
        if period in period_map:
            from_ts = now - period_map[period]
        elif period == "all":
            from_ts = None
        else:
            from_ts = parse_ts(qs.get("from", [None])[0])

        to_ts = parse_ts(qs.get("to", [None])[0]) or now
        self._json_response(self._jobs_mod().get_stats(from_ts=from_ts, to_ts=to_ts))

    def _handle_status(self):
        running, _ = is_service_running()
        self._json_response({
            "running": running,
            "fifo": str(FIFO_PATH),
            "controller_dir": str(CONTROLLER_DIR),
        })

    def _handle_health(self):
        payload, http_status = collect_health(_cfg)
        self._json_response(payload, http_status)

    def _handle_audit(self, parsed):
        qs = parse_qs(parsed.query)
        result = _audit_mod.search_audit(
            from_ts=parse_ts(qs.get("from", [None])[0]),
            to_ts=parse_ts(qs.get("to", [None])[0]),
            method=qs.get("method", [None])[0],
            path_contains=qs.get("path", [None])[0],
            ip=qs.get("ip", [None])[0],
            status=qs.get("status", [None])[0],
            limit=min(self._safe_int(qs.get("limit", [100])[0], 100), 1000),
            offset=self._safe_int(qs.get("offset", [0])[0], 0),
        )
        self._json_response(result)

    def _handle_webhook_test(self):
        result = _webhook_mod.deliver_webhook("test-0000", "done")
        if result is None:
            return self._error_response(
                "webhook_url이 설정되지 않았습니다. 설정에서 URL을 지정하세요.",
                400, code="WEBHOOK_NOT_CONFIGURED")
        _webhook_mod.cleanup_test_marker()
        self._json_response(result)

    def _handle_service_start(self):
        ok, _ = self._jobs_mod().start_controller_service()
        if ok:
            self._json_response({"started": True})
        else:
            self._error_response("서비스 시작 실패", 500, code="SERVICE_START_FAILED")

    def _handle_service_stop(self):
        ok, err = self._jobs_mod().stop_controller_service()
        if ok:
            self._json_response({"stopped": True})
        else:
            self._error_response(err or "서비스 종료 실패", 500, code="SERVICE_STOP_FAILED")

    def _handle_logs_cleanup(self):
        body = self._read_body() or {}
        retention_days = body.get("retention_days", 30)
        try:
            retention_days = int(retention_days)
            if retention_days < 1:
                retention_days = 1
        except (ValueError, TypeError):
            retention_days = 30
        result = self._jobs_mod().cleanup_old_jobs(retention_days=retention_days)
        self._json_response(result)
