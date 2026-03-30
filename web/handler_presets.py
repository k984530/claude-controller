"""Presets HTTP 핸들러 — Mixin"""


class PresetHandlerMixin:
    """프리셋 CRUD API 핸들러."""

    # GET /api/presets
    def _handle_list_presets(self):
        self._json_response(self._presets().list_presets())

    # GET /api/presets/<id>
    def _handle_get_preset(self, preset_id):
        preset, err = self._presets().get_preset(preset_id)
        if err:
            return self._error_response(err, 404, code="NOT_FOUND")
        self._json_response(preset)

    # POST /api/presets
    def _handle_create_preset(self):
        body = self._read_body()
        name = (body.get("name") or "").strip()
        if not name:
            return self._error_response("name 필드가 필요합니다", 400, code="MISSING_FIELD")
        preset, err = self._presets().create_preset(
            name=name,
            config=body.get("config", {}),
            description=body.get("description", ""),
        )
        if err:
            return self._error_response(err, 400, code="BAD_REQUEST")
        self._json_response(preset, 201)

    # PUT /api/presets/<id>
    def _handle_update_preset(self, preset_id):
        body = self._read_body()
        preset, err = self._presets().update_preset(preset_id, **body)
        if err:
            return self._error_response(err, 404, code="NOT_FOUND")
        self._json_response(preset)

    # DELETE /api/presets/<id>
    def _handle_delete_preset(self, preset_id):
        preset, err = self._presets().delete_preset(preset_id)
        if err:
            return self._error_response(err, 404, code="NOT_FOUND")
        self._json_response({"deleted": True, "preset": preset})
