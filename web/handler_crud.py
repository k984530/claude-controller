"""CRUD HTTP 핸들러 — Mixin

프로젝트·파이프라인 CRUD를 ControllerHandler에서 분리.
"""


class ProjectHandlerMixin:
    """프로젝트 관련 API 핸들러."""

    def _handle_list_projects(self):
        self._json_response(self._projects().list_projects())

    def _handle_get_project(self, project_id):
        project, err = self._projects().get_project(project_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(project)

    def _handle_project_jobs(self, project_id):
        project, err = self._projects().get_project(project_id)
        if err:
            return self._error_response(err, 404, code="PROJECT_NOT_FOUND")
        jobs = self._jobs_mod().get_all_jobs(cwd_filter=project["path"])
        self._json_response({"project": project, "jobs": jobs})

    def _handle_add_project(self):
        body = self._read_body()
        path = body.get("path", "").strip()
        if not path:
            return self._error_response("path 필드가 필요합니다", code="MISSING_FIELD")
        project, err = self._projects().add_project(
            path, name=body.get("name", "").strip(), description=body.get("description", "").strip())
        if err:
            self._error_response(err, 409, code="ALREADY_EXISTS")
        else:
            self._json_response(project, 201)

    def _handle_create_project(self):
        body = self._read_body()
        path = body.get("path", "").strip()
        if not path:
            return self._error_response("path 필드가 필요합니다", code="MISSING_FIELD")
        project, err = self._projects().create_project(
            path, name=body.get("name", "").strip(),
            description=body.get("description", "").strip(),
            init_git=body.get("init_git", True))
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(project, 201)

    def _handle_update_project(self, project_id):
        body = self._read_body()
        project, err = self._projects().update_project(
            project_id, name=body.get("name"), description=body.get("description"))
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(project)

    def _handle_remove_project(self, project_id):
        project, err = self._projects().remove_project(project_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response({"removed": True, "project": project})


class PipelineHandlerMixin:
    """파이프라인 관련 API 핸들러."""

    def _handle_list_pipelines(self):
        self._json_response(self._pipeline().list_pipelines())

    def _handle_pipeline_status(self, pipe_id):
        result, err = self._pipeline().get_pipeline_status(pipe_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(result)

    def _handle_pipeline_history(self, pipe_id):
        result, err = self._pipeline().get_pipeline_history(pipe_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response(result)

    def _handle_create_pipeline(self):
        body = self._read_body()
        path = body.get("project_path", "").strip()
        command = body.get("command", "").strip()
        if not path or not command:
            return self._error_response("project_path와 command 필드가 필요합니다", code="MISSING_FIELD")
        skill_ids = body.get("skill_ids")
        if skill_ids and not isinstance(skill_ids, list):
            skill_ids = None
        result, err = self._pipeline().create_pipeline(
            path, command=command,
            interval=body.get("interval", "").strip(),
            name=body.get("name", "").strip(),
            on_complete=body.get("on_complete", "").strip(),
            skill_ids=skill_ids)
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result, 201)

    def _handle_pipeline_run(self, pipe_id):
        body = self._read_body()
        result, err = self._pipeline().run_next(pipe_id)
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result)

    def _handle_pipeline_stop(self, pipe_id):
        result, err = self._pipeline().stop_pipeline(pipe_id)
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result)

    def _handle_update_pipeline(self, pipe_id):
        body = self._read_body()
        result, err = self._pipeline().modify_pipeline(
            pipe_id,
            command=body.get("command"),
            interval=body.get("interval"),
            name=body.get("name"),
            on_complete=body.get("on_complete"),
            skill_ids=body.get("skill_ids"),
        )
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result)

    def _handle_pipeline_reset(self, pipe_id):
        body = self._read_body()
        result, err = self._pipeline().reset_phase(pipe_id, phase=body.get("phase"))
        if err:
            self._error_response(err, 400)
        else:
            self._json_response(result)

    def _handle_delete_pipeline(self, pipe_id):
        result, err = self._pipeline().delete_pipeline(pipe_id)
        if err:
            self._error_response(err, 404)
        else:
            self._json_response({"deleted": True, "pipeline": result})
