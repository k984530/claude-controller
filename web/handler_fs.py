"""
File System & Config HTTP 핸들러 Mixin

포함 엔드포인트:
  - GET/POST /api/config
  - GET/POST /api/recent-dirs
  - GET  /api/dirs
  - POST /api/mkdir
"""

import json
import os

from config import DATA_DIR, SETTINGS_FILE, RECENT_DIRS_FILE


class FsHandlerMixin:

    def _handle_get_config(self):
        defaults = {
            "skip_permissions": False,
            "allowed_tools": "Bash,Read,Write,Edit,Glob,Grep,Agent,NotebookEdit,WebFetch,WebSearch",
            "model": "",
            "max_jobs": 10,
            "append_system_prompt": "",
            "target_repo": "",
            "base_branch": "main",
            "checkpoint_interval": 5,
            "locale": "ko",
        }
        try:
            if SETTINGS_FILE.exists():
                saved = json.loads(SETTINGS_FILE.read_text("utf-8"))
                defaults.update(saved)
        except (json.JSONDecodeError, OSError):
            pass
        self._json_response(defaults)

    def _handle_save_config(self):
        body = self._read_body()
        if not body or not isinstance(body, dict):
            return self._error_response("설정 데이터가 필요합니다", code="MISSING_FIELD")

        current = {}
        try:
            if SETTINGS_FILE.exists():
                current = json.loads(SETTINGS_FILE.read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            pass

        allowed_keys = {
            "skip_permissions", "allowed_tools", "model", "max_jobs",
            "append_system_prompt", "target_repo", "base_branch",
            "checkpoint_interval", "locale",
            "webhook_url", "webhook_secret", "webhook_events",
        }
        for k, v in body.items():
            if k in allowed_keys:
                current[k] = v

        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            SETTINGS_FILE.write_text(
                json.dumps(current, ensure_ascii=False, indent=2), "utf-8"
            )
            self._json_response({"ok": True, "config": current})
        except OSError as e:
            self._error_response(f"설정 저장 실패: {e}", 500, code="CONFIG_SAVE_FAILED")

    def _handle_get_recent_dirs(self):
        try:
            if RECENT_DIRS_FILE.exists():
                data = json.loads(RECENT_DIRS_FILE.read_text("utf-8"))
            else:
                data = []
            self._json_response(data)
        except (json.JSONDecodeError, OSError):
            self._json_response([])

    def _handle_save_recent_dirs(self):
        body = self._read_body()
        dirs = body.get("dirs")
        if not isinstance(dirs, list):
            return self._error_response("dirs 배열이 필요합니다", code="MISSING_FIELD")
        dirs = [d for d in dirs if isinstance(d, str)][:8]
        try:
            DATA_DIR.mkdir(parents=True, exist_ok=True)
            RECENT_DIRS_FILE.write_text(json.dumps(dirs, ensure_ascii=False), "utf-8")
            self._json_response({"ok": True})
        except OSError as e:
            self._error_response(f"저장 실패: {e}", 500, code="SAVE_FAILED")

    def _handle_dirs(self, dir_path):
        try:
            dir_path = os.path.abspath(os.path.expanduser(dir_path))
            if not os.path.isdir(dir_path):
                return self._error_response("디렉토리가 아닙니다", 400, code="NOT_A_DIRECTORY")

            entries = []
            try:
                items = sorted(os.listdir(dir_path))
            except PermissionError:
                return self._error_response("접근 권한 없음", 403, code="PERMISSION_DENIED")

            parent = os.path.dirname(dir_path)
            if parent != dir_path:
                entries.append({"name": "..", "path": parent, "type": "dir"})

            for item in items:
                if item.startswith("."):
                    continue
                full = os.path.join(dir_path, item)
                entry = {"name": item, "path": full}
                if os.path.isdir(full):
                    entry["type"] = "dir"
                else:
                    entry["type"] = "file"
                    try:
                        entry["size"] = os.path.getsize(full)
                    except OSError:
                        entry["size"] = 0
                entries.append(entry)

            self._json_response({"current": dir_path, "entries": entries})
        except Exception as e:
            self._error_response(f"디렉토리 읽기 실패: {e}", 500, code="DIR_READ_ERROR")

    def _handle_mkdir(self):
        body = self._read_body()
        parent = body.get("parent", "").strip()
        name = body.get("name", "").strip()

        if not parent or not name:
            return self._error_response("parent와 name 필드가 필요합니다", code="MISSING_FIELD")

        if "/" in name or "\\" in name or name in (".", ".."):
            return self._error_response("잘못된 디렉토리 이름입니다", code="INVALID_NAME")

        try:
            parent = os.path.abspath(os.path.expanduser(parent))
            if not os.path.isdir(parent):
                return self._error_response("상위 디렉토리가 존재하지 않습니다", 400, code="DIR_NOT_FOUND")

            new_dir = os.path.join(parent, name)
            if os.path.exists(new_dir):
                return self._error_response("이미 존재하는 이름입니다", 409, code="ALREADY_EXISTS")

            os.makedirs(new_dir)
            self._json_response({"ok": True, "path": new_dir}, 201)
        except PermissionError:
            self._error_response("접근 권한 없음", 403, code="PERMISSION_DENIED")
        except OSError as e:
            self._error_response(f"디렉토리 생성 실패: {e}", 500, code="DIR_CREATE_ERROR")
