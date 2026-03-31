"""
File System & Config HTTP 핸들러 Mixin

포함 엔드포인트:
  - GET/POST /api/config
  - GET/POST /api/recent-dirs
  - GET  /api/dirs
  - POST /api/mkdir
"""

import base64
import os
import subprocess
import time

from config import DATA_DIR, SETTINGS_FILE, SKILLS_FILE, RECENT_DIRS_FILE, UPLOADS_DIR
from utils import load_json_file, atomic_json_save

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

ALLOWED_UPLOAD_EXTS = IMAGE_EXTS | {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml", ".toml",
    ".py", ".js", ".ts", ".jsx", ".tsx", ".html", ".css", ".scss",
    ".sh", ".bash", ".zsh", ".fish",
    ".c", ".cpp", ".h", ".hpp", ".java", ".kt", ".go", ".rs", ".rb",
    ".swift", ".m", ".r", ".sql", ".graphql",
    ".log", ".env", ".conf", ".ini", ".cfg",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".pptx",
    ".zip", ".tar", ".gz",
}


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
        defaults.update(load_json_file(SETTINGS_FILE, {}))
        self._json_response(defaults)

    def _handle_save_config(self):
        body = self._read_body()
        if not body or not isinstance(body, dict):
            return self._error_response("설정 데이터가 필요합니다", code="MISSING_FIELD")

        current = load_json_file(SETTINGS_FILE, {})

        allowed_keys = {
            "skip_permissions", "allowed_tools", "model", "max_jobs",
            "append_system_prompt", "target_repo", "base_branch",
            "checkpoint_interval", "locale",
        }
        for k, v in body.items():
            if k in allowed_keys:
                current[k] = v

        try:
            atomic_json_save(SETTINGS_FILE, current)
            self._json_response({"ok": True, "config": current})
        except OSError as e:
            self._error_response(f"설정 저장 실패: {e}", 500, code="CONFIG_SAVE_FAILED")

    def _handle_get_skills(self):
        self._json_response(load_json_file(SKILLS_FILE, []))

    def _handle_save_skills(self):
        body = self._read_body(allow_list=True)
        if not isinstance(body, list):
            return self._error_response("카테고리 배열이 필요합니다", code="MISSING_FIELD")

        # 구조 검증: [{id, name, color, skills: [{id, name, desc, prompt}]}]
        sanitized = []
        for cat in body:
            if not isinstance(cat, dict) or not cat.get("id") or not cat.get("name"):
                continue
            skills = []
            for s in cat.get("skills", []):
                if not isinstance(s, dict) or not s.get("id") or not s.get("name"):
                    continue
                skills.append({
                    "id": str(s["id"]),
                    "name": str(s["name"]),
                    "desc": str(s.get("desc", "")),
                    "prompt": str(s.get("prompt", "")),
                })
            sanitized.append({
                "id": str(cat["id"]),
                "name": str(cat["name"]),
                "color": str(cat.get("color", "accent")),
                "skills": skills,
            })

        try:
            atomic_json_save(SKILLS_FILE, sanitized)
            self._json_response({"ok": True, "skills": sanitized})
        except OSError as e:
            self._error_response(f"스킬 저장 실패: {e}", 500, code="SKILLS_SAVE_FAILED")

    def _handle_get_recent_dirs(self):
        self._json_response(load_json_file(RECENT_DIRS_FILE, []))

    def _handle_save_recent_dirs(self):
        body = self._read_body()
        dirs = body.get("dirs")
        if not isinstance(dirs, list):
            return self._error_response("dirs 배열이 필요합니다", code="MISSING_FIELD")
        dirs = [d for d in dirs if isinstance(d, str)][:8]
        try:
            atomic_json_save(RECENT_DIRS_FILE, dirs)
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

    def _handle_find_dir(self, name):
        """GET /api/find-dir?name=controller — 이름으로 디렉토리 검색 (macOS mdfind 우선, find 폴백)"""
        if not name or "/" in name or "\\" in name:
            return self._error_response("유효한 폴더 이름이 필요합니다", code="INVALID_NAME")
        home = os.path.expanduser("~")
        # macOS: mdfind (Spotlight) — 즉시 검색
        try:
            result = subprocess.run(
                ["mdfind", f"kMDItemFSName == '{name}' && kMDItemContentType == public.folder"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line and os.path.isdir(line) and line.startswith(home):
                        return self._json_response({"path": line})
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        # 폴백: find (depth 4, 홈 디렉토리)
        try:
            result = subprocess.run(
                ["find", home, "-maxdepth", "4", "-type", "d", "-name", name,
                 "-not", "-path", "*/.*", "-not", "-path", "*/node_modules/*"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    line = line.strip()
                    if line and os.path.isdir(line):
                        return self._json_response({"path": line})
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        self._error_response(f"'{name}' 폴더를 찾을 수 없습니다", 404, code="DIR_NOT_FOUND")

    def _handle_upload(self):
        body = self._read_body()
        data_b64 = body.get("data", "")
        filename = body.get("filename", "file")

        if not data_b64:
            return self._error_response("data 필드가 필요합니다", code="MISSING_FIELD")
        if "," in data_b64:
            data_b64 = data_b64.split(",", 1)[1]

        try:
            raw = base64.b64decode(data_b64)
        except Exception:
            return self._error_response("잘못된 base64 데이터", code="INVALID_DATA")

        ext = os.path.splitext(filename)[1].lower()
        if ext not in ALLOWED_UPLOAD_EXTS:
            return self._error_response(
                f"허용되지 않는 파일 형식입니다: {ext or '(확장자 없음)'}",
                400, code="INVALID_FILE_TYPE")
        prefix = "img" if ext in IMAGE_EXTS else "file"
        safe_name = f"{prefix}_{int(time.time())}_{os.getpid()}_{id(raw) % 10000}{ext}"

        UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
        filepath = UPLOADS_DIR / safe_name
        filepath.write_bytes(raw)

        is_image = ext in IMAGE_EXTS
        self._json_response({
            "path": str(filepath),
            "filename": safe_name,
            "originalName": filename,
            "size": len(raw),
            "isImage": is_image,
        }, 201)

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
