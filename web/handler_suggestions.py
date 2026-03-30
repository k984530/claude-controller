"""
Suggestion HTTP 핸들러 Mixin

엔드포인트:
  - GET    /api/suggestions              # 제안 목록 (?status=pending)
  - POST   /api/suggestions/generate     # 분석 실행 → 새 제안 생성
  - POST   /api/suggestions/:id/apply    # 제안 적용
  - POST   /api/suggestions/:id/dismiss  # 제안 무시
  - DELETE /api/suggestions/:id          # 제안 삭제
  - POST   /api/suggestions/clear        # 무시된 제안 일괄 삭제
"""

import suggestions as _sug_mod


class SuggestionHandlerMixin:

    def _handle_list_suggestions(self, parsed):
        """GET /api/suggestions?status=pending"""
        from urllib.parse import parse_qs
        qs = parse_qs(parsed.query)
        status = qs.get("status", [None])[0]
        self._json_response(_sug_mod.list_suggestions(status=status))

    def _handle_generate_suggestions(self):
        """POST /api/suggestions/generate — 작업 이력 분석 → 제안 생성"""
        new_suggestions = _sug_mod.generate_suggestions()
        all_pending = _sug_mod.list_suggestions(status="pending")
        self._json_response({
            "generated": len(new_suggestions),
            "total_pending": len(all_pending),
            "new": new_suggestions,
        })

    def _handle_apply_suggestion(self, suggestion_id):
        """POST /api/suggestions/:id/apply"""
        result, err = _sug_mod.apply_suggestion(suggestion_id)
        if err:
            self._error_response(err, 400, code="APPLY_FAILED")
        else:
            self._json_response({"applied": True, "result": result})

    def _handle_dismiss_suggestion(self, suggestion_id):
        """POST /api/suggestions/:id/dismiss"""
        ok = _sug_mod.dismiss_suggestion(suggestion_id)
        if ok:
            self._json_response({"dismissed": True})
        else:
            self._error_response("제안을 찾을 수 없습니다", 404, code="NOT_FOUND")

    def _handle_delete_suggestion(self, suggestion_id):
        """DELETE /api/suggestions/:id"""
        ok = _sug_mod.delete_suggestion(suggestion_id)
        if ok:
            self._json_response({"deleted": True})
        else:
            self._error_response("제안을 찾을 수 없습니다", 404, code="NOT_FOUND")

    def _handle_clear_dismissed(self):
        """POST /api/suggestions/clear"""
        _sug_mod.clear_dismissed()
        self._json_response({"cleared": True})
