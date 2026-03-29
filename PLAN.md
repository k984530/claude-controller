# Controller Service — 프로덕트 분석 및 MVP 계획

> 분석 일자: 2026-03-28
> 프로젝트: Claude Code Headless Daemon Controller
> 목적: 테스트 목적 — 5대 페르소나 관점의 서비스 분석 및 MVP 기능 도출

---

## 서비스 요약

Claude Code CLI를 headless 데몬으로 운영하며, FIFO 파이프 기반 비동기 작업 디스패치, Git Worktree 격리 실행, 자동 체크포인트/리와인드, 웹 대시보드를 제공하는 개발 자동화 컨트롤러.

---

## 1. 페르소나별 분석

### 페르소나 1: 일반 사용자 (비개발자)

**핵심 니즈:**
- AI에게 "이 코드 고쳐줘", "README 작성해줘" 같은 자연어 명령을 보내고 결과를 확인하는 **단순한 인터페이스**
- 터미널 없이 웹 브라우저만으로 작업을 관리할 수 있는 환경

**페인포인트:**
- Claude Code CLI를 직접 사용하려면 터미널, Git, JSON 등의 개념을 이해해야 함
- 작업이 실패했을 때 `.out` 로그 파일을 직접 열어봐야 원인을 알 수 있음
- FIFO, Worktree, session 모드 등 개념이 지나치게 기술적

**필수 기능 3가지:**
1. **원클릭 작업 전송** — 프롬프트 입력 → 전송 → 결과 확인까지 웹 UI에서 완결
2. **작업 상태 시각화** — running/done/failed 상태를 실시간으로 보여주는 대시보드
3. **에러 안내 메시지** — 실패 시 기술 로그 대신 사람이 읽을 수 있는 설명 제공

**사용 시나리오:**
- 마케터가 웹 대시보드에서 "landing page의 CTA 버튼 색상을 파란색으로 변경해줘"를 입력하고, 결과 diff를 시각적으로 확인한 뒤 승인
- 비개발 팀원이 "README에 설치 방법 섹션 추가해줘"를 보내고, 완료 알림을 받은 뒤 PR 링크를 클릭

---

### 페르소나 2: 파워 유저 (얼리어답터)

**핵심 니즈:**
- 복수 작업을 **동시에 병렬 실행**하고 각각의 진행 상황을 모니터링
- 세션 fork/resume으로 **대화 흐름을 분기·합류**하며 복잡한 리팩토링 수행
- 파이프라인(plan→design→implement→review→verify) 자동화

**페인포인트:**
- 현재 최대 10개 동시 작업이 가능하지만, 작업 간 **의존성이나 순서를 지정**할 수 없음
- 체크포인트 리와인드가 있지만, 여러 체크포인트를 비교하거나 체리픽하는 것은 불가
- 파이프라인 엔진(pipeline.py)이 있지만, 아직 CLI/UI 통합이 완전하지 않음

**필수 기능 3가지:**
1. **파이프라인 오케스트레이션** — 단계별 자동 진행 + 수동 게이팅(승인 후 다음 단계)
2. **작업 간 의존성 그래프** — "A 완료 후 B 실행" 같은 DAG 기반 스케줄링
3. **체크포인트 diff 비교** — 두 체크포인트 간 코드 변경사항을 시각적으로 비교

**사용 시나리오:**
- 대규모 리팩토링: 5개 모듈을 각각 별도 worktree에서 병렬로 리팩토링하고, 모두 완료되면 자동으로 코드 리뷰 작업을 트리거
- 실험적 분기: session fork로 두 가지 구현 방식을 동시에 시도하고, 결과를 비교한 뒤 더 나은 것을 채택

---

### 페르소나 3: 개발자 (API/SDK 통합)

**핵심 니즈:**
- REST API를 통해 자체 CI/CD 파이프라인이나 내부 도구에서 **프로그래밍 방식으로 작업을 디스패치**
- 작업 결과를 **구조화된 JSON**으로 수신하여 후속 자동화에 활용
- 에러 코드, 재시도 로직, 웹훅 콜백 등 **견고한 API 계약**

**페인포인트:**
- API 응답에 일관된 에러 코드 체계가 없음 (문자열 메시지만 반환)
- 작업 완료 시 알림(webhook/callback)이 없어 결과 확인에 폴링 필요
- `stream` 엔드포인트의 offset 기반 폴링이 비효율적 (SSE/WebSocket이 아님)
- API 문서가 README의 표 하나뿐이며, 요청/응답 스키마가 명시되지 않음

**필수 기능 3가지:**
1. **Webhook 콜백** — 작업 완료/실패 시 지정된 URL로 결과를 POST
2. **구조화된 에러 응답** — `{ "error": { "code": "JOB_LIMIT_REACHED", "message": "..." } }` 형식
3. **SSE(Server-Sent Events) 스트리밍** — 실시간 진행 상황을 push 방식으로 전달

**사용 시나리오:**
- GitHub Actions 워크플로우에서 `POST /api/send`로 코드 리뷰 작업을 디스패치하고, webhook으로 결과를 수신하여 PR 코멘트에 자동 게시
- 내부 슬랙봇이 `/claude 버그 수정해줘` 명령을 받아 Controller API를 호출하고, 완료 후 슬랙 채널에 결과를 요약 전달

---

### 페르소나 4: 비즈니스 의사결정자 (팀 리드/경영진)

**핵심 니즈:**
- 팀 전체의 AI 자동화 **활용도와 ROI를 정량적으로 파악**
- Claude API 사용 **비용 추적 및 예산 관리**
- 기존 개발 워크플로우(GitHub, Jira, Slack)와의 **자연스러운 통합**

**페인포인트:**
- `cost_usd`가 작업별로 기록되지만, 기간별/팀원별/프로젝트별 집계 기능이 없음
- 누가 어떤 작업을 보냈는지 사용자 식별이 되지 않음 (멀티유저 미지원)
- 성공률, 평균 소요 시간, 비용 추이 등 **분석 대시보드가 없음**

**필수 기능 3가지:**
1. **비용/사용량 대시보드** — 일별/주별 API 비용, 작업 수, 성공률 시각화
2. **멀티유저 인증** — 사용자별 작업 이력 추적 및 권한 관리
3. **프로젝트별 작업 분류** — 프로젝트 단위로 비용과 성과를 묶어서 분석

**사용 시나리오:**
- 월간 리뷰에서 "이번 달 Claude 활용으로 절약한 개발 시간"과 "소요 비용" 비교 보고서 확인
- 신규 팀에 Controller 도입을 검토하며 2주간 파일럿 사용 후 비용 효율성 데이터를 기반으로 의사결정

---

### 페르소나 5: 운영/보안 담당자 (인프라/보안 엔지니어)

**핵심 니즈:**
- 서비스 **안정성 보장** — 데몬 프로세스의 자동 복구, 헬스체크, 장애 알림
- **보안 감사** — 누가 어떤 프롬프트를 보냈는지, 어떤 파일이 변경됐는지 추적
- **배포 용이성** — 원커맨드 설치, 환경별 설정 분리, 컨테이너 지원

**페인포인트:**
- REVIEW.md에서 이미 식별된 보안 취약점들 (source 인젝션, FIFO 권한, CORS 등)
- 서비스 자동 재시작(watchdog) 없음 — 크래시 시 수동 복구 필요
- 로그 로테이션 없음 — 장기 운영 시 디스크 소모
- 헬스체크 엔드포인트 부재 — 외부 모니터링 도구 연동 어려움
- `--dangerously-skip-permissions` 기본 활성화 — 보안 감사 시 즉각 적기

**필수 기능 3가지:**
1. **헬스체크 + 자동 복구** — `/api/health` 엔드포인트 + 프로세스 워치독
2. **감사 로그** — 모든 API 호출과 프롬프트 발송을 타임스탬프·사용자와 함께 기록
3. **보안 하드닝** — source 인젝션 제거, FIFO 권한 설정, CORS 제한, skip-permissions 기본값 변경

**사용 시나리오:**
- Grafana 대시보드에서 Controller 서비스의 가동률, 활성 작업 수, 메모리 사용량을 실시간 모니터링
- 보안 감사 시 "최근 30일간 skip-permissions 모드로 실행된 작업 목록"을 조회하여 위험 프롬프트 확인

---

## 2. 핵심 문제 Top 5

모든 페르소나를 관통하는 핵심 문제를 심각도 순으로 정리한다.

| # | 핵심 문제 | 영향 페르소나 | 심각도 |
|---|----------|-------------|--------|
| 1 | **보안 취약점 미해결** — source 인젝션, FIFO 권한, CORS, skip-permissions 기본값 | 운영/보안, 비즈니스 | Critical |
| 2 | **작업 결과 수신의 비효율** — 폴링 전용, 웹훅/SSE 없음, 에러 코드 체계 부재 | 개발자, 파워유저 | High |
| 3 | **관찰 가능성(Observability) 부재** — 비용 집계, 성공률, 사용량 통계, 헬스체크 없음 | 비즈니스, 운영, 일반 사용자 | High |
| 4 | **운영 안정성 미흡** — 워치독 없음, 로그 로테이션 없음, 고아 프로세스 문제, 카운터 데드락 | 운영/보안, 모든 사용자 | High |
| 5 | **사용자 경험 갭** — 전문 용어(FIFO, worktree, session mode) 직접 노출, 에러 메시지 불친절 | 일반 사용자, 비즈니스 | Medium |

---

## 3. MVP 기능 목록

우선순위순으로 나열한다. P0은 출시 전 필수, P1은 초기 채택에 필요, P2는 확장 단계.

### P0 — 출시 전 필수 (보안 + 기본 안정성)

| # | 기능 | 설명 |
|---|------|------|
| 1 | ✅ **보안 하드닝** | source 인젝션→grep 파서 교체, FIFO `chmod 600`, CORS 화이트리스트, skip-permissions 기본값 false |
| 2 | ✅ **헬스체크 엔드포인트** | `GET /api/health` — 서비스 상태, 활성 작업 수, 디스크 사용량 반환 |
| 3 | ✅ **구조화된 에러 응답** | 모든 API 에러에 `{ "error": { "code": "...", "message": "..." } }` 형식 적용 |
| 4 | ✅ **카운터 데드락 방지** | 스핀락에 타임아웃 + stale lock 감지 추가 |
| 5 | ✅ **meta 파일 원자적 쓰기** | temp→rename 패턴으로 .meta 파일 동시 접근 문제 해결 |

### P1 — 초기 채택 (핵심 UX + 통합)

| # | 기능 | 설명 |
|---|------|------|
| 6 | ✅ **작업 완료 웹훅** | 작업 완료/실패 시 등록된 URL로 결과 POST (설정에서 webhook_url 지정) |
| 7 | ✅ **SSE 실시간 스트림** | `GET /api/jobs/:id/stream` 을 offset 폴링에서 SSE로 전환 |
| 8 | ✅ **비용/사용량 집계 API** | `GET /api/stats` — 기간별 총 비용, 작업 수, 성공률, 평균 소요 시간 |
| 9 | ✅ **프로세스 워치독** | launchd plist 또는 감시 루프로 데몬 자동 재시작 |
| 10 | ✅ **에러 메시지 사용자화** | 실패 시 기술 로그 대신 사람이 읽을 수 있는 요약 + 원인 + 다음 단계 안내 |
| 11 | ✅ **프로젝트별 작업 필터** | 웹 대시보드에서 프로젝트(cwd) 기준으로 작업을 그룹화하여 표시 |

### P2 — 확장 (파워유저 + 엔터프라이즈)

| # | 기능 | 설명 |
|---|------|------|
| 12 | ✅ **파이프라인 UI 통합** | pipeline.py의 plan→verify 단계를 웹 대시보드에서 시각적으로 관리 |
| 13 | ✅ **작업 의존성 DAG** | 작업 간 선행/후행 관계 지정 — A 완료 후 자동으로 B 트리거. `depends_on` 필드로 pending→자동 디스패치 |
| 14 | ✅ **체크포인트 diff 뷰어** | 두 체크포인트 간 변경사항을 unified diff로 시각화 — `GET /api/jobs/:id/diff` API + 프론트엔드 뷰어 |
| 15 | **멀티유저 인증** | 사용자별 토큰 발급, 작업 이력 추적, 역할 기반 권한 (admin/user) |
| 16 | ✅ **감사 로그** | 모든 API 호출을 타임스탬프·IP·상태·소요시간과 함께 JSONL 기록, `GET /api/audit` 조회 API 제공 |
| 17 | ✅ **로그 로테이션** | service.log 크기 기반 로테이션 + 오래된 job_*.out 자동 정리 |
| 18 | ✅ **Docker 컨테이너 지원** | Dockerfile + docker-compose.yml 제공으로 원커맨드 배포 |

---

## 4. 기술 요구사항

### 현재 스택

| 레이어 | 기술 | 비고 |
|--------|------|------|
| 데몬/코어 | Bash (service/controller.sh, lib/*.sh) | FIFO 수신, claude -p 실행, 작업 관리 |
| 웹 서버 | Python 3.8+ (http.server 기반) | REST API, 파일 업로드, 인증 |
| 프론트엔드 | Vanilla JS + CSS | 외부 의존성 없음 |
| 데이터 저장 | 파일 시스템 (.meta, .out, .json) | DB 없음 |
| 버전 관리 | Git Worktree | 작업 격리 |

### MVP에 필요한 추가 기술

| 필요 기술 | 용도 | 대안 |
|-----------|------|------|
| **SSE (Server-Sent Events)** | 실시간 스트림 push | 현재 offset 폴링 유지 (차선) |
| **launchd / systemd** | 프로세스 워치독 | 간단한 bash 감시 루프 |
| **mkcert** | 로컬 HTTPS 인증서 | HTTP만 사용 (개발 환경) |
| **SQLite** (P2) | 감사 로그, 사용량 통계 저장 | JSON 파일 유지 (스케일 제한) |
| **Docker** (P2) ✅ | 컨테이너 배포 | 수동 설치 유지 |

### 인프라 요구사항

- **OS:** macOS / Linux (Windows 미지원 — FIFO, Git Worktree 의존)
- **런타임:** Python 3.8+, Bash 4+, Git 2.20+, jq
- **외부 의존성:** Claude Code CLI (`claude` 바이너리 또는 npm 패키지)
- **네트워크:** localhost 전용 (원격 접근 시 SSH 터널 또는 HTTPS + 인증 필수)
- **디스크:** Worktree당 저장소 크기만큼 사용 — 자동 정리 정책 필요

---

## 5. 성공 지표 (KPI)

### 채택 지표

| 지표 | 측정 방법 | 목표 (3개월) |
|------|----------|-------------|
| **일간 활성 작업 수** | `GET /api/stats` — 일별 작업 수 집계 | 일 평균 20+ 작업 |
| **작업 성공률** | done / (done + failed) | 90% 이상 |
| **반복 사용률** | 동일 사용자의 주간 재사용 비율 | 70% 이상 |
| **npm 설치 수** | npm weekly downloads | 100+ |

### 효율 지표

| 지표 | 측정 방법 | 목표 |
|------|----------|------|
| **평균 작업 소요 시간** | duration_ms 중앙값 | < 120초 |
| **작업당 평균 비용** | cost_usd 평균 | < $0.50 |
| **월간 총 비용** | cost_usd 합계 | 예산 대비 80% 이내 |
| **Rewind 사용률** | rewind 작업 수 / 전체 작업 수 | > 5% (기능 활용 증거) |

### 안정성 지표

| 지표 | 측정 방법 | 목표 |
|------|----------|------|
| **서비스 가동률** | 헬스체크 ping 기반 | 99.5% (월 3.6시간 이하 다운타임) |
| **평균 장애 복구 시간 (MTTR)** | 워치독 자동 재시작 시간 | < 30초 |
| **고아 프로세스 수** | 주기적 ps 점검 | 0개 |
| **보안 취약점** | REVIEW.md 체크리스트 | P0 전부 해결 |

---

## 6. 로드맵 요약

```
Phase 1 (1-2주)  ─  보안 + 안정성 (P0)  ✅ 완료 (2026-03-29)
  └─ source 인젝션 수정, FIFO 권한, CORS, 카운터 데드락, 헬스체크
  └─ 추가 해결: 구조화된 에러 응답, meta 원자적 쓰기, pipelines.json 레이스 컨디션

Phase 2 (3-4주)  ─  핵심 UX + 통합 (P1)  ✅ 완료 (2026-03-29)
  └─ ✅ 웹훅, ✅ SSE 스트림, ✅ 비용 집계, ✅ 워치독, ✅ 프로젝트 필터, ✅ 에러 메시지 사용자화

Phase 3 (5-8주)  ─  확장 (P2)  ✅ 완료 (2026-03-29)
  └─ ✅ 로그 로테이션 (#17), ✅ 작업 의존성 DAG (#13), ✅ 감사 로그 (#16)
  └─ ✅ 체크포인트 diff 뷰어 (#14), ✅ 파이프라인 UI 통합 (#12), ✅ Docker (#18)
  └─ #15 멀티유저 인증은 별도 프로젝트로 분리

Phase 4 (9주~)  ─  품질 보증 + 안정화  🔄 진행 중 (2026-03-29~)
  └─ API 통합 테스트 자동 작성 (tests/ 디렉토리)
  └─ 코드 품질 지속 개선 (버그·보안·회귀 중심, i18n/CSS/문서 제외)
  └─ 파이프라인 체제 (2026-03-29 04:56 최적화):
      integration-test  60분 (←30분, 프롬프트 리팩터: 엔드포인트별 테스트 파일 명시)
      code-quality      30분 (P0-P3 우선순위 체계, 저임팩트 작업 제외)
      maintenance       60분 (유지)
      regression-guard  60분 (프롬프트 v2: 코드레벨 검증 추가, "배포 갭" 반복보고 제거)
      self-evolution    ~30분 (유지)
  └─ 누적 비용: $56.03 (45회 총 실행, 2026-03-29 05:00 기준)
  └─ 메타 분석 #10 (2026-03-29 05:00):
      - regression-guard 프롬프트 리라이트: py_compile 구문검사 + import 검증 추가,
        404 신규 엔드포인트를 회귀로 오판하지 않도록 명시적 규칙 추가
      - 비용 구조: integration-test $17.54 > regression-guard $15.61 > code-quality $13.13
  └─ 메타 분석 #11 (2026-03-29 06:03):
      - integration-test 프롬프트 v2 리라이트:
        (1) pytest → unittest(stdlib) 전환 — pytest 미설치로 인한 테스트 실행 실패 해소
        (2) requests → urllib.request(stdlib) 전환 — 외부 패키지 의존 제거
        (3) "서비스 코드 수정 금지" 규칙 강화 — 보안수정/리팩토링 영역 침범 차단
        (4) 남은 5개 테스트 파일 목록 명시 (health, stats, audit, send, presets)
      - 해결된 과제: integration-test ↔ code-quality 결과 중복 (역할 경계 명확화)
      - 누적 비용: ~$54.43 (last-10 합산), 총 실행 약 70회
  └─ 메타 분석 #12 (2026-03-29 06:39):
      - 시스템 코드 개선: pipeline.py _classify_result() 분류 정확도 8.7% → 76.1%
        (1) _CHANGE_PATTERNS 복합 정규식을 개별 키워드로 분리 (7단어 1점 → 각 1점)
        (2) _NO_CHANGE_PATTERNS에 "회귀.*없", "오류\s*없", "고임팩트.*없" 추가
        (3) "교체" 키워드 추가 (i18n 교체 작업 등 분류 누락 해소)
      - 효과: 적응형 인터벌 시스템이 사실상 비활성 → 활성화
        unknown 42건 → 11건, has_change 0건 → 29건, no_change 4건 → 6건
      - 발견: handler.py가 _HOT_MODULES 외부라 on_complete API 업데이트 불가 (커밋 필요)
      - 누적 비용: ~$72 (72회 실행), 시간당 ~$7.57
  └─ 최적화 후 예상 시간당 비용: ~$5.50/hr (←$7.57, 적응형 인터벌 활성화로 no_change 시 자동 감속)
  └─ 메타 분석 #13 (2026-03-29 07:27):
      - 비용 추적 정상화 확인: cost_usd 필드가 히스토리에 정상 기록 중
        (이전 분석의 "cost=0" 진단은 필드명 오류 — cost vs cost_usd)
      - 비용 분석 (last-10 히스토리):
        integration-test $14.13 (avg $1.41), code-quality $14.10 (avg $1.41),
        regression-guard $12.84 (avg $1.28), self-evolution $10.75 (avg $1.07),
        maintenance $1.82 (avg $0.30) — 합계 $53.63
      - 핵심 개선: regression-guard 프롬프트 v3 리라이트
        (1) unittest discover 기반으로 전환 — tests/ 디렉토리의 기존 테스트를 실행
        (2) integration-test와 py_compile 중복 제거
        (3) "회귀 없음" 시 한 줄 보고로 축소 — 비용 절감 기대
        (4) 선순환 구조: integration-test가 테스트 작성 → regression-guard가 실행
      - 효과 기대: regression-guard 평균 비용 $1.28 → ~$0.50 (응답 축소)
      - 누적: ~$53.63 (last-10), 총 실행 77회, 시간당 ~$7.69
  └─ 메타 분석 #14 (2026-03-29 08:15):
      - 비용 분석 (last-10 히스토리, 갱신):
        code-quality $15.64 (avg $1.56, 28회), integration-test $13.72 (avg $1.37, 19회),
        regression-guard $12.88 (avg $1.29, 14회), self-evolution $12.11 (avg $1.21, 13회),
        maintenance $2.09 (avg $0.30, 8회) — 합계 $56.44, 총 82회
      - 핵심 발견: code-quality가 전체 비용의 40% ($3.12/hr) — 유일한 30분 인터벌 +
        git diff HEAD~2가 고정된 33파일 5800줄 diff를 매번 재스캔
      - 핵심 개선: code-quality 프롬프트 v2 + 인터벌 60분 통일
        (1) HEAD~2 → find -mmin -90 전환: 최근 수정 파일만 스캔 (context 축소)
        (2) 인터벌 30분 → 60분: 시간당 2회 → 1회 (실행 횟수 50% 감소)
        (3) 보고 간결화: 파일/취약점/수정을 각 1줄로 제한
        (4) 중복 방어 검증 제외 규칙 추가 (handler가 이미 검증하는 하위 함수 재검증 차단)
      - 예상 효과: code-quality $3.12/hr → ~$1.00/hr (68% 감소)
        전체 시간당 비용: ~$7.70/hr → ~$5.58/hr (28% 감소)
      - regression-guard v3 효과 미달: $1.28 → $0.50 예상했으나 $1.45로 증가
        원인: Section B(py_compile) + C(불변조건)가 context 소비, 다음 분석에서 추가 최적화 예정
  └─ 메타 분석 #15 (2026-03-29 09:00):
      - 비용 분석 (last-10 히스토리, 갱신):
        code-quality $15.93 (avg $1.59, 29회), integration-test $13.72 (avg $1.37, 19회),
        regression-guard $12.88 (avg $1.29, 14회), self-evolution $12.25 (avg $1.22, 14회),
        maintenance $2.41 (avg $0.30, 9회) — 합계 $57.19, 총 85회
      - 핵심 발견: self-evolution이 전체 비용의 45% ($3.66/hr) — 유일한 20분 인터벌
        다른 4개 파이프라인 모두 60분인데 self-evolution만 3배 빈도로 실행
        최근 3회 중 2회 no_change — 초기 최적화 단계 종료, 발견할 개선점 감소 중
      - 핵심 개선: self-evolution 인터벌 20분 → 60분
        (1) 시간당 비용: $3.66/hr → $1.22/hr (67% 감소)
        (2) 전체 시간당 비용: $8.21/hr → $5.77/hr (30% 감소)
        (3) 일간 절감: ~$58.56/day → ~$41.54/day ($17 절감)
        (4) 모든 파이프라인이 60분 인터벌로 통일 — 예측 가능한 실행 패턴
      - regression-guard $1.29 → $0.50 최적화는 다음 분석으로 이월
      - 파이프라인 체제 최종:
          integration-test  60분, code-quality 60분, maintenance 60분,
          regression-guard 60분, self-evolution 60분 (←20분)
```

---

## 부록: REVIEW.md 보안 이슈 매핑

| REVIEW.md 항목 | MVP 대응 | 상태 |
|---------------|----------|------|
| 1.1 source 인젝션 | P0 #1 보안 하드닝 | **해결** — `_get_meta_field()` grep 파서로 교체 |
| 1.2 eval callback | 이미 제거됨 (controller.sh에서 callback 필드 파싱 제거) | **해결** |
| 1.3 CORS | P0 #1 보안 하드닝 | **해결** — Origin 화이트리스트 적용 (config.py ALLOWED_ORIGINS) |
| 1.4 FIFO 권한 | P0 #1 보안 하드닝 | **해결** — `mkfifo -m 600` + 기존 FIFO chmod 600 적용 |
| skip-permissions 기본값 | P0 #1 보안 하드닝 | **해결** — config.sh + postinstall.sh + ctl + handler_fs.py 전체 기본값 false로 통일 |
| 2.1 로직 3중 복제 | web/ 모듈로 통합 진행 중 | **부분 해결** |
| 2.2 executor.sh 미사용 | P1에서 정리 | 미해결 |
| 3.1 카운터 데드락 | P0 #4 | **해결** — 스핀락 타임아웃 + stale lock 감지 추가 |
| 3.5 meta 비원자적 쓰기 | P0 #5 | **해결** — `_meta_set_field()` temp→rename 패턴 적용 |
| pipelines.json 레이스 컨디션 | 운영 안정성 | **해결** — `fcntl.flock` 배타적 잠금 + temp→rename 원자적 쓰기 적용 (pipeline.py) |
| 헬스체크 엔드포인트 부재 | P0 #2 | **해결** — `GET /api/health` 구현 (서비스/FIFO/작업/디스크 상태, 3단계 판정, 인증 면제) |
| 구조화된 에러 응답 부재 | P0 #3 | **해결** — `{"error": {"code": "ERROR_CODE", "message": "..."}}` 형식 전체 적용, HTTP 상태별 기본 코드 + 30개 이상 구체적 에러 코드 |

---

# Part II — AGI 고도화: 자율 개발 에이전트 시스템

> 작성일: 2026-03-28
> 목표: 프롬프트 수신형 도구 → 목표 자율 수행 시스템으로 진화
> 핵심 전환: "사람이 프롬프트를 보내면 실행" → "목표를 설정하면 스스로 계획·실행·평가·학습"

---

## 7. 비전: Cognitive Development Agent

현재 시스템은 **반응형(reactive)** 구조다 — 사용자가 프롬프트를 보내야 동작한다.
AGI 지향 시스템은 **자율형(autonomous)** 구조여야 한다 — 목표를 받으면 스스로 계획을 세우고, 실행하고, 결과를 평가하고, 다음 행동을 결정한다.

```
현재 (Reactive)                    목표 (Autonomous)
─────────────────                  ──────────────────────────────
User → Prompt → Execute → Done     User → Goal → [Cognitive Loop] → Done
                                          ↓
                                    ┌─────────────────────────────────┐
                                    │  Plan → Execute → Evaluate      │
                                    │    ↑                    ↓       │
                                    │    └── Learn ← Reflect ─┘       │
                                    └─────────────────────────────────┘
```

### 핵심 차이점

| 관점 | 현재 (Controller) | 목표 (Cognitive Agent) |
|------|-------------------|----------------------|
| 입력 | 구체적 프롬프트 ("이 함수 리팩토링해") | 추상적 목표 ("코드 품질 개선") |
| 계획 | 없음 (단일 프롬프트 = 단일 작업) | 자동 분해 (목표 → 서브태스크 DAG) |
| 실행 | 1 프롬프트 = 1 claude -p | 다수 전문 에이전트 병렬 협업 |
| 평가 | 없음 (성공/실패만 확인) | 자동 리뷰 + 테스트 + 품질 게이트 |
| 학습 | 없음 | 결과 기반 패턴 축적, 프롬프트 자기 개선 |
| 메모리 | 세션 내 대화만 | 영구 지식 저장소 (결정, 패턴, 실패 원인) |

---

## 8. 인지 아키텍처 (Cognitive Architecture)

### 8.1 전체 구조

```
                         ┌─────────────┐
                         │   사용자     │
                         │  (Goal UI)   │
                         └──────┬──────┘
                                │ 목표 설정
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                    Orchestrator (두뇌)                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌───────────┐ │
│  │ Goal Engine│  │  Planner   │  │ Dispatcher │  │ Evaluator │ │
│  │ 목표 관리   │→│ DAG 생성   │→│ 작업 배분   │→│ 결과 평가  │ │
│  └────────────┘  └────────────┘  └────────────┘  └─────┬─────┘ │
│        ↑                                                │       │
│        └────────────── Feedback Loop ───────────────────┘       │
└──────────────────────────┬───────────────────────────────────────┘
                           │
            ┌──────────────┼──────────────┐
            ▼              ▼              ▼
   ┌──────────────┐ ┌───────────┐ ┌────────────┐
   │ Worker Pool  │ │  Memory   │ │  Tool      │
   │ (claude -p)  │ │  Store    │ │  Registry  │
   │ ┌──────────┐ │ │           │ │            │
   │ │ Coder    │ │ │ decisions │ │ built-in   │
   │ │ Reviewer │ │ │ patterns  │ │ generated  │
   │ │ Tester   │ │ │ failures  │ │ external   │
   │ │ Writer   │ │ │ context   │ │            │
   │ └──────────┘ │ └───────────┘ └────────────┘
   └──────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│  Controller (기존 인프라)              │
│  FIFO · Worktree · Checkpoint · Web  │
└──────────────────────────────────────┘
```

### 8.2 핵심 컴포넌트

#### ① Goal Engine — 목표 관리자

```
역할: 추상적 목표를 구조화하고, 진행 상태를 추적하며, 완료 조건을 판단
입력: "이 프로젝트의 테스트 커버리지를 80%로 올려"
출력: { goal_id, objective, success_criteria, sub_goals[], status }
```

- 목표의 **완료 조건(success criteria)**을 자동 도출
- 목표를 **측정 가능한 서브 목표**로 분해
- 진행률 추적 및 **목표 달성 여부 자동 판단**

#### ② Planner — 계획 생성기

```
역할: 목표를 실행 가능한 태스크 DAG(방향성 비순환 그래프)로 변환
입력: Goal + Codebase Context + Memory
출력: Task DAG (선행/후행 관계 포함)
```

- 코드베이스 분석 → **영향 범위 파악** → 태스크 분해
- 태스크 간 **의존성 자동 추론** (파일 충돌 감지 포함)
- 병렬 실행 가능한 태스크 그룹 식별

#### ③ Dispatcher — 작업 배분기

```
역할: DAG의 실행 순서에 따라 적절한 Worker에게 태스크를 할당
정책: 의존성 충족된 태스크만 실행, 동시성 제한 준수, 실패 시 재시도/대체 경로
```

- **토폴로지 정렬** 기반 실행 순서 결정
- Worker 유형에 따른 **전문화된 시스템 프롬프트** 주입
- 실패 태스크의 **자동 재시도** (최대 2회, 프롬프트 변형 포함)

#### ④ Worker Pool — 전문 에이전트 풀

| Worker 유형 | 역할 | 시스템 프롬프트 핵심 |
|-------------|------|---------------------|
| **Coder** | 코드 작성/수정 | "최소 변경 원칙, 테스트 포함" |
| **Reviewer** | 코드 리뷰 | "보안·성능·가독성 관점, 구체적 제안" |
| **Tester** | 테스트 작성/실행 | "엣지 케이스 포함, 커버리지 보고" |
| **Analyst** | 코드 분석/조사 | "구조 파악, 의존성 맵, 영향 범위" |
| **Writer** | 문서 작성 | "코드 기반 정확한 문서, 예제 포함" |

각 Worker는 `claude -p` 헤드리스 프로세스로 실행되며, **worktree 격리** 환경에서 동작.

#### ⑤ Evaluator — 자동 평가기

```
역할: Worker 산출물의 품질을 자동으로 검증
파이프라인: 코드 변경 → 린트 → 테스트 → 리뷰 → 승인/반려
```

- **정적 분석**: lint, type check, security scan
- **동적 분석**: 테스트 실행, 커버리지 측정
- **AI 리뷰**: 별도 Reviewer Worker가 코드 변경을 평가
- **게이팅**: 모든 검증 통과 시에만 merge 허용

#### ⑥ Memory Store — 영구 지식 저장소

```
역할: 세션을 넘어 축적되는 지식 — 과거 결정, 패턴, 실패 원인, 코드베이스 맥락
저장소: data/memory/ 디렉토리 (JSON)
```

| 메모리 유형 | 예시 | 활용 |
|-------------|------|------|
| **Decision** | "auth는 JWT 대신 session 방식 채택" | Planner가 일관된 결정 |
| **Pattern** | "이 프로젝트는 에러를 Result 타입으로 처리" | Coder가 관례 준수 |
| **Failure** | "SQLite 동시 쓰기에서 BUSY 에러 발생" | 같은 실수 반복 방지 |
| **Context** | "모듈 A와 B는 순환 의존성 있음" | Analyst가 빠른 분석 |

#### ⑦ Learning Module — 자기 개선

```
역할: 태스크 실행 결과를 분석하여 시스템 자체를 개선
```

- **프롬프트 최적화**: 실패한 프롬프트 패턴 분석 → 개선된 프롬프트 템플릿 생성
- **시간/비용 추정 개선**: 과거 실행 데이터 기반 추정 정확도 향상
- **Worker 선택 최적화**: 태스크 유형별 최적 Worker 매핑 학습

---

## 9. 서비스 기획: 사용자 경험 설계

### 9.1 Goal-Oriented UI

기존 "프롬프트 입력 → 전송" 인터페이스에서 **목표 설정 → 진행 관찰 → 승인/개입** 인터페이스로 전환.

```
┌─────────────────────────────────────────────────────────┐
│  🎯 목표 설정                                            │
│  ┌───────────────────────────────────────────────────┐  │
│  │ "API 응답 시간을 50% 단축"                          │  │
│  └───────────────────────────────────────────────────┘  │
│  [목표 설정] [템플릿에서 선택]                             │
├─────────────────────────────────────────────────────────┤
│  📋 실행 계획 (자동 생성)                     [승인] [수정] │
│                                                         │
│  ┌─ 1. 프로파일링 (Analyst) ───────── ✅ 완료            │
│  │     → 병목: DB 쿼리 3개, 직렬 API 호출 2개            │
│  ├─ 2. DB 쿼리 최적화 (Coder) ─────── 🔄 진행 중        │
│  │     ├─ 2a. N+1 쿼리 제거 ──────── ✅ 완료             │
│  │     └─ 2b. 인덱스 추가 ─────────── 🔄 진행 중         │
│  ├─ 3. API 호출 병렬화 (Coder) ────── ⏳ 대기 (2 의존)   │
│  ├─ 4. 테스트 (Tester) ───────────── ⏳ 대기 (2,3 의존)  │
│  └─ 5. 리뷰 (Reviewer) ──────────── ⏳ 대기 (4 의존)     │
│                                                         │
│  진행률: ██████░░░░░░ 35%    예상 비용: $1.20            │
├─────────────────────────────────────────────────────────┤
│  💬 에이전트 로그 (실시간)                                 │
│  [14:32] Analyst: DB 쿼리 분석 완료 — users 테이블 풀스캔 │
│  [14:33] Coder-1: users.email에 인덱스 추가 중           │
│  [14:33] Coder-2: get_orders() N+1 → JOIN 변환 완료      │
└─────────────────────────────────────────────────────────┘
```

### 9.2 사용자 개입 모드

| 모드 | 설명 | 적합한 상황 |
|------|------|------------|
| **Full Auto** | 목표 설정 후 완전 자율 실행 | 신뢰도 높은 반복 작업 |
| **Gate Mode** | 각 단계 완료 시 사용자 승인 필요 | 중요한 프로덕션 변경 |
| **Watch Mode** | 자율 실행하되 실시간 관찰 + 중단 가능 | 실험적 작업 |
| **Pair Mode** | 각 태스크 결과를 사용자와 함께 리뷰 | 학습/온보딩 목적 |

### 9.3 목표 템플릿 라이브러리

자주 사용되는 목표를 템플릿화하여 원클릭 실행:

| 템플릿 | 자동 생성 계획 |
|--------|---------------|
| **버그 수정** | 재현 → 원인 분석 → 수정 → 테스트 → 리뷰 |
| **기능 추가** | 설계 → 구현 → 테스트 → 문서 → 리뷰 |
| **리팩토링** | 분석 → 영향 범위 → 단계별 변경 → 테스트 → 리뷰 |
| **성능 개선** | 프로파일링 → 병목 식별 → 최적화 → 벤치마크 → 리뷰 |
| **보안 감사** | 스캔 → 취약점 분류 → 수정 → 검증 → 보고서 |
| **코드 품질** | 분석 → 데드코드 제거 → 린트 수정 → 테스트 보강 |

---

## 10. 기술 설계: 구현 계획

### 10.1 디렉토리 구조 (확장)

```
controller/
├── (기존 구조 유지)
├── cognitive/                    # 🆕 인지 레이어
│   ├── goal_engine.py            # 목표 관리 + 완료 조건 판단
│   ├── planner.py                # 태스크 DAG 생성기
│   ├── dispatcher.py             # DAG 기반 작업 배분
│   ├── evaluator.py              # 자동 평가 파이프라인
│   ├── learning.py               # 결과 분석 + 자기 개선
│   └── prompts/                  # Worker 유형별 시스템 프롬프트
│       ├── coder.md
│       ├── reviewer.md
│       ├── tester.md
│       ├── analyst.md
│       └── writer.md
├── memory/                       # 🆕 영구 지식 저장소
│   ├── store.py                  # 메모리 CRUD + 검색
│   ├── decisions/                # 아키텍처/설계 결정
│   ├── patterns/                 # 코드 패턴/관례
│   ├── failures/                 # 실패 원인/해결책
│   └── context/                  # 코드베이스 맥락
├── dag/                          # 🆕 DAG 실행 엔진
│   ├── graph.py                  # DAG 자료구조 + 토폴로지 정렬
│   ├── executor.py               # DAG 순회 + 태스크 실행
│   └── visualizer.py             # DAG → Mermaid/SVG 변환
└── web/
    └── static/
        ├── goals.js              # 🆕 목표 관리 UI
        ├── goals.css
        ├── dag-view.js           # 🆕 DAG 시각화
        └── memory-view.js        # 🆕 메모리 탐색 UI
```

### 10.2 데이터 흐름

```
1. 사용자가 목표 설정
   POST /api/goals { "objective": "테스트 커버리지 80%", "mode": "gate" }

2. Goal Engine이 목표 구조화
   → success_criteria: ["coverage >= 80%", "모든 테스트 통과"]
   → context: 현재 커버리지 45%, 미테스트 모듈 12개

3. Planner가 DAG 생성 (claude -p로 실행)
   → Task 1: 커버리지 분석 (Analyst, 의존성 없음)
   → Task 2-7: 모듈별 테스트 작성 (Coder x6, 병렬, Task 1 의존)
   → Task 8: 통합 테스트 실행 (Tester, Task 2-7 의존)
   → Task 9: 커버리지 검증 (Evaluator, Task 8 의존)

4. Dispatcher가 DAG 순서대로 실행
   → Task 1 완료 → Task 2-7 동시 디스패치 → ...

5. Evaluator가 각 태스크 결과 검증
   → 린트 통과? 테스트 통과? 리뷰 통과?
   → 실패 시: 재시도 또는 Planner에게 대체 경로 요청

6. 모든 태스크 완료 → Goal Engine이 성공 기준 확인
   → 커버리지 82% → ✅ 목표 달성 → 사용자에게 보고
```

### 10.3 API 설계 (신규 엔드포인트)

```
# Goal Management
POST   /api/goals              # 목표 생성
GET    /api/goals              # 목표 목록
GET    /api/goals/:id          # 목표 상세 (DAG 포함)
PUT    /api/goals/:id          # 목표 수정 (모드 변경 등)
DELETE /api/goals/:id          # 목표 취소
POST   /api/goals/:id/approve  # Gate 모드: 다음 단계 승인

# DAG / Task
GET    /api/goals/:id/dag      # DAG 구조 (시각화용)
GET    /api/goals/:id/tasks    # 태스크 목록 + 상태
POST   /api/goals/:id/tasks/:tid/retry  # 실패 태스크 재시도

# Memory
GET    /api/memory             # 메모리 검색
POST   /api/memory             # 메모리 추가
DELETE /api/memory/:id         # 메모리 삭제

# Learning
GET    /api/insights           # 학습된 인사이트 조회
GET    /api/stats/goals        # 목표별 성공률/비용 통계
```

---

## 11. 개발 로드맵 (AGI 고도화)

기존 Phase 1-3 (MVP) 위에 Phase 4-7을 추가한다.

```
Phase 1-3 (기존)  ─  MVP: 보안 + UX + 확장
  └─ ✅ 대부분 해결 (REVIEW.md 이슈 매핑 참조)

Phase 4 (2주)  ─  인지 기반: Goal Engine + Memory
  ├─ ✅ goal_engine.py: 목표 CRUD + 완료 조건 자동 도출
  ├─ ✅ memory/store.py: JSON 기반 영구 메모리 CRUD + 유사도 검색
  ├─ ✅ prompts/: Worker 유형별 시스템 프롬프트 5종
  ├─ ✅ API: /api/goals 엔드포인트 (handler_goals.py GoalHandlerMixin, 2026-03-29)
  ├─ ✅ API: /api/memory 엔드포인트 (handler_memory.py MemoryHandlerMixin, 2026-03-29)
  └─ UI: 목표 설정 + 목표 목록 화면

Phase 5 (2주)  ─  계획 엔진: Planner + DAG
  ├─ planner.py: 목표 → 태스크 DAG 자동 생성
  ├─ dag/graph.py: DAG 자료구조 + 토폴로지 정렬
  ├─ dag/executor.py: DAG 순회 + claude -p 디스패치
  ├─ dispatcher.py: Worker 유형별 라우팅 + 동시성 관리
  └─ UI: DAG 시각화 (Mermaid 기반)

Phase 6 (2주)  ─  자동 평가: Evaluator + Gate
  ├─ evaluator.py: 린트/테스트/리뷰 자동 파이프라인
  ├─ Gate 모드: 사용자 승인 워크플로우
  ├─ 자동 재시도: 실패 태스크 프롬프트 변형 후 재실행
  └─ UI: 태스크별 평가 결과 + 승인 버튼

Phase 7 (지속적)  ─  학습 루프: Learning + Self-Improvement
  ├─ learning.py: 실행 결과 패턴 분석
  ├─ 프롬프트 자기 최적화: 성공/실패 패턴 → 프롬프트 템플릿 갱신
  ├─ 비용/시간 추정 모델: 과거 데이터 기반 정확도 향상
  └─ 목표 템플릿 자동 생성: 반복 패턴 → 재사용 가능 템플릿
```

---

## 12. 성공 지표 (AGI 고도화)

### 자율성 지표

| 지표 | 측정 방법 | 목표 |
|------|----------|------|
| **목표 자율 완료율** | 사용자 개입 없이 완료된 목표 비율 | > 60% |
| **계획 정확도** | Planner 생성 DAG 중 수정 없이 실행된 비율 | > 70% |
| **평균 개입 횟수** | 목표당 사용자가 개입한 횟수 | < 2회 |
| **재시도 성공률** | 실패 후 자동 재시도로 성공한 비율 | > 50% |

### 학습 지표

| 지표 | 측정 방법 | 목표 |
|------|----------|------|
| **프롬프트 개선율** | Learning 모듈이 개선한 프롬프트의 성공률 변화 | +20%p |
| **추정 정확도** | 실제 소요 시간/비용 vs 추정값의 오차 | < 30% |
| **메모리 활용률** | 태스크 실행 시 메모리를 참조한 비율 | > 40% |
| **반복 실패 감소** | 동일 원인 실패의 월별 추이 | 매월 -30% |

---

## 13. 리스크 및 완화 전략

| 리스크 | 영향 | 완화 |
|--------|------|------|
| **Planner 환각** — 존재하지 않는 파일/함수 참조 | 실행 실패 | Analyst 선행 분석으로 실제 코드 상태 확인 |
| **DAG 폭발** — 목표가 너무 많은 태스크로 분해 | 비용 초과 | 태스크 수 상한(20) + 비용 예산 설정 |
| **Worker 충돌** — 병렬 Worker가 같은 파일 수정 | 머지 충돌 | Worktree 격리 + 충돌 감지 시 직렬화 |
| **학습 오버피팅** — 특정 프로젝트에만 유효한 패턴 일반화 | 다른 프로젝트에서 실패 | 메모리에 프로젝트 스코프 태그 부착 |
| **비용 폭주** — 자율 실행 중 재시도 루프 | 예산 초과 | 목표당 비용 상한 + 자동 중단 |

---

## 14. Phase 5 — Cognitive Layer 통합 + 안정화 (2026-03-29 분석)

> 분석 기준일: 2026-03-29
> 분석 대상: 전체 프로젝트 상태, 미커밋 변경, 테스트 현황, 모듈 통합도

### 14.1 현황 진단

| 영역 | 상태 | 상세 |
|------|------|------|
| cognitive/ | ✅ 코드 완성 (1,785줄) | GoalEngine, Planner, Dispatcher, Evaluator, LearningModule, Orchestrator 모두 import 성공 |
| memory/ | ✅ 코드 완성 (227줄) | MemoryStore CRUD + 유사도 검색 구현 |
| dag/ | ⚠️ 부분 완성 (227줄) | graph.py만 존재. **executor.py, visualizer.py 미구현** |
| Web API 연동 | ❌ 미연결 | handler.py에서 cognitive/memory/dag 참조 **0건** — /api/goals, /api/memory 엔드포인트 없음 |
| 테스트 | ⚠️ 1 fail / 99 total | test_api_send.py: 구조화 에러 응답 변경 미반영. cognitive/dag/memory 테스트 **0건** |
| 미커밋 | ⚠️ 33파일, ~6,000줄 | Phase 2-4 변경사항이 단일 워킹 디렉토리에 축적 |

### 14.2 개선사항 Top 3 (우선순위순)

#### 🥇 1순위: Cognitive Layer → Web API 통합

**Why:** cognitive/ 모듈이 완성됐지만 웹에서 접근할 방법이 없다. 이 통합 없이는 Phase 5-7(계획 엔진, 자동 평가, 학습 루프) 진행 불가. 사용자가 목표를 설정하고 DAG를 관찰하고 Gate 승인하는 것이 전체 아키텍처의 핵심 사용자 경험.

**Impact:** Cognitive Agent 시스템의 사용자 접점 확보. Full Auto / Gate / Watch / Pair 모드가 실제로 동작하게 됨.

#### 🥈 2순위: 테스트 안정화 + Cognitive 단위 테스트

**Why:** 자율 실행 시스템의 핵심 로직(Goal 상태 전이, DAG 토폴로지 정렬, Memory 검색)이 검증 없이 프로덕션에 투입되면 런타임 실패 위험이 높다. 기존 1건 실패도 수정 필요.

**Impact:** GoalEngine 상태 머신, DAG 위상 정렬, MemoryStore 검색의 정확성 보장.

#### 🥉 3순위: DAG Executor 구현 + 미커밋 정리

**Why:** dag/graph.py가 자료구조를 정의하지만 실행 엔진(executor.py)이 없어 Planner→Dispatcher→Worker 파이프라인이 끊어져 있다. 6,000줄 미커밋은 작업 손실 위험 + 리뷰 불가 상태.

**Impact:** 목표 → DAG → 실제 claude -p 실행까지의 완전한 파이프라인 완성.

---

### 14.3 1순위 구현 계획: Cognitive Layer → Web API 통합

#### Step 1: handler_goals.py 신규 생성 (Goal + DAG API)

기존 handler_jobs.py, handler_fs.py 패턴을 따라 handler_goals.py를 분리 모듈로 생성.

**파일:** `web/handler_goals.py` (신규)

```
구현 엔드포인트:

GET  /api/goals                    — 목표 목록 (status 필터)
POST /api/goals                    — 목표 생성 (objective, mode, cwd)
GET  /api/goals/:id                — 목표 상세 (DAG 포함)
PUT  /api/goals/:id                — 목표 수정 (mode 변경)
DELETE /api/goals/:id              — 목표 취소
POST /api/goals/:id/approve        — Gate 모드 다음 단계 승인
POST /api/goals/:id/plan           — 수동 계획 생성 트리거
POST /api/goals/:id/execute        — 수동 실행 트리거
GET  /api/goals/:id/dag            — DAG 구조 (시각화용)
GET  /api/goals/:id/tasks          — 태스크 목록 + 상태
POST /api/goals/:id/tasks/:tid/retry — 실패 태스크 재시도
```

**의존성:** `cognitive.orchestrator.Orchestrator` 인스턴스를 handler에서 초기화.
Orchestrator가 GoalEngine, Planner, Dispatcher, Evaluator를 내부적으로 관리하므로
handler는 Orchestrator만 참조하면 됨.

**핵심 구현:**
```python
# handler_goals.py 골격
class GoalHandlerMixin:
    """Handler에 mix-in되는 Goal API 메서드들."""

    _orchestrator = None  # 싱글턴

    def _orch(self):
        if not GoalHandlerMixin._orchestrator:
            GoalHandlerMixin._orchestrator = Orchestrator(
                base_dir=str(BASE_DIR),
                claude_bin=_get_claude_bin()
            )
        return GoalHandlerMixin._orchestrator

    def _handle_create_goal(self):
        body = self._read_json_body()
        goal = self._orch().set_goal(
            objective=body["objective"],
            cwd=body.get("cwd"),
            mode=body.get("mode", "gate"),
        )
        self._json_response(goal, status=201)

    def _handle_goal_detail(self, goal_id):
        goal = self._orch().get_status(goal_id)
        if not goal:
            return self._error_response("Goal not found", 404, code="GOAL_NOT_FOUND")
        self._json_response(goal)

    # ... approve, plan, execute, dag, tasks 등
```

#### Step 2: handler_memory.py 신규 생성 (Memory API)

**파일:** `web/handler_memory.py` (신규)

```
구현 엔드포인트:

GET    /api/memory              — 메모리 검색 (query, type, project 파라미터)
POST   /api/memory              — 메모리 추가
GET    /api/memory/:id          — 메모리 상세
PUT    /api/memory/:id          — 메모리 수정
DELETE /api/memory/:id          — 메모리 삭제
GET    /api/insights            — 학습 인사이트 조회
GET    /api/stats/goals         — 목표별 통계
```

**의존성:** `memory.store.MemoryStore` 직접 사용 + `cognitive.learning.LearningModule` (insights).

#### Step 3: handler.py 라우팅 통합

**파일:** `web/handler.py` (수정)

변경 내용:
1. `_dispatch_get()`에 Goal/Memory GET 라우트 추가 (L295-362 사이)
2. `_dispatch_post()`에 Goal/Memory POST 라우트 추가
3. `_dispatch_delete()`에 Goal/Memory DELETE 라우트 추가
4. handler_goals.py, handler_memory.py를 mix-in 또는 delegation 패턴으로 연결

```python
# _dispatch_get() 추가분 (기존 /api/pipelines 뒤)
if path == "/api/goals":
    return self._handle_list_goals(parsed)
if path == "/api/memory":
    return self._handle_search_memory(parsed)
if path == "/api/insights":
    return self._handle_insights()

match = re.match(r"^/api/goals/([^/]+)$", path)
if match:
    return self._handle_goal_detail(match.group(1))
match = re.match(r"^/api/goals/([^/]+)/dag$", path)
if match:
    return self._handle_goal_dag(match.group(1))
match = re.match(r"^/api/goals/([^/]+)/tasks$", path)
if match:
    return self._handle_goal_tasks(match.group(1))
```

#### Step 4: 프론트엔드 UI 추가

**파일:** `web/static/goals.js` (신규), `web/static/goals.css` (신규)

기능:
- 목표 생성 폼 (objective 텍스트, mode 선택, cwd 선택)
- 목표 목록 (상태별 필터: active, completed, failed, cancelled)
- 목표 상세: DAG 시각화 (Mermaid.js 또는 CSS grid 기반 트리 뷰)
- Gate 승인 버튼, 실시간 진행률 바
- 에이전트 로그 스트림 (SSE 기반, 기존 stream.js 재활용)

**파일:** `web/static/index.html` (수정)
- 네비게이션에 "Goals" 탭 추가
- goals.js, goals.css 스크립트 로드

**파일:** `web/static/memory-view.js` (신규)
- 메모리 목록/검색 UI
- 타입별 필터 (decision, pattern, failure, context)

#### Step 5: i18n 확장

**파일:** `web/static/i18n.js` (수정)

Goal/Memory 관련 번역 키 추가:
```
goal_create, goal_objective, goal_mode, goal_status,
dag_view, task_pending, task_running, task_completed,
memory_search, memory_type, memory_add
```

#### 예상 작업량

| 파일 | 작업 | 예상 줄 수 |
|------|------|-----------|
| web/handler_goals.py | 신규 생성 | ~300줄 |
| web/handler_memory.py | 신규 생성 | ~150줄 |
| web/handler.py | 라우팅 추가 | +40줄 |
| web/static/goals.js | 신규 생성 | ~400줄 |
| web/static/goals.css | 신규 생성 | ~200줄 |
| web/static/memory-view.js | 신규 생성 | ~200줄 |
| web/static/index.html | 탭 추가 | +20줄 |
| web/static/i18n.js | 번역 키 추가 | +30줄 |
| **합계** | | **~1,340줄** |

#### 의존성 및 리스크

| 의존성 | 상태 | 대응 |
|--------|------|------|
| Orchestrator.run() → claude -p 실행 | 정상 (테스트 필요) | 단위 테스트에서 mock claude 사용 |
| memory/store.py 경로 | memory/ 디렉토리 존재 확인 | config.py에 MEMORY_DIR 추가 |
| dag/executor.py 미구현 | ⚠️ Dispatcher가 직접 실행 불가 | 3순위에서 해결. 1순위는 API 레이어만 구현하고 실행은 기존 파이프라인(pipeline.py) 위임 가능 |
| 프론트엔드 Mermaid.js | 외부 의존성 | CDN 로드 또는 순수 CSS 트리뷰로 대체 |

---

### 14.4 2순위 구현 계획: 테스트 안정화

| 작업 | 파일 | 내용 |
|------|------|------|
| 기존 실패 수정 | tests/test_api_send.py:69 | `assertIsInstance(data["error"], str)` → `assertIsInstance(data["error"], dict)` + code/message 필드 검증 |
| GoalEngine 테스트 | tests/test_goal_engine.py (신규) | 목표 CRUD, 상태 전이(planning→executing→evaluating→completed), cancel, DAG attach |
| DAG 테스트 | tests/test_dag_graph.py (신규) | 토폴로지 정렬, 순환 감지, ready 노드 추출, 상태 업데이트 |
| MemoryStore 테스트 | tests/test_memory_store.py (신규) | CRUD, 유사도 검색, 타입 필터, 프로젝트 스코프 |

### 14.5 3순위 구현 계획: DAG Executor + 커밋 정리

| 작업 | 파일 | 내용 |
|------|------|------|
| DAG Executor | dag/executor.py (신규) | DAG 순회 → ready 노드 추출 → claude -p 디스패치 → 결과 수집 → 상태 업데이트 루프 |
| DAG Visualizer | dag/visualizer.py (신규) | DAG → Mermaid 문법 변환 (프론트엔드 렌더링용) |
| 커밋 분리 | git | (1) Phase 4 QA 변경 (tests/ + pipeline 최적화), (2) Cognitive Layer 코드 (cognitive/ + memory/ + dag/), (3) 웹 UI/UX 개선 (web/ 변경분) |

---

## 15. Phase 5 갱신 — 현황 재진단 및 실행 계획 (2026-03-29 오후)

> 분석 기준일: 2026-03-29 오후
> 목적: 14장 진단 이후 변경된 상태를 반영하고, 다음 3가지 작업의 우선순위와 구체적 계획을 재정리

### 15.1 14장 대비 변경사항

| 14장 진단 | 현재 상태 | 비고 |
|-----------|----------|------|
| ❌ Web API 미연결 (handler↔cognitive 참조 0건) | ✅ **해결** | handler_goals.py(203줄), handler_memory.py(203줄) 구현 완료. handler.py에 GET/POST/DELETE 라우팅 전부 연결 |
| ❌ /api/goals, /api/memory 엔드포인트 없음 | ✅ **해결** | 13개 엔드포인트 라우팅 완료 (goals 8개 + memory 5개) |
| ⚠️ 1 fail / 99 tests | ✅ **해결** | 98 passed, 1 skipped, 0 failed |
| ⚠️ dag/ 부분 완성 | ⚠️ **변동 없음** | graph.py(222줄)만 존재. executor.py, visualizer.py 미구현 |
| ❌ 프론트엔드 UI 없음 | ❌ **변동 없음** | goals.js, goals.css, memory-view.js 미생성. index.html에 Goals 탭 없음 |
| ⚠️ cognitive/dag/memory 테스트 0건 | ⚠️ **변동 없음** | 기존 99개 테스트는 모두 API 레벨. 단위 테스트 0건 |

### 15.2 개선사항 Top 3 (우선순위 재정렬)

#### 🥇 1순위: Goals/Memory 프론트엔드 UI

**Why:** 백엔드 API가 완성됐지만 사용자 접점이 없다. cognitive/ 1,880줄 + handler 406줄의 투자가 UI 없이는 사용 불가. 목표 설정→DAG 관찰→Gate 승인이라는 핵심 UX 사이클을 완성하는 마지막 퍼즐.

**Impact:** Cognitive Agent 시스템 전체가 웹 대시보드를 통해 사용 가능해짐.

#### 🥈 2순위: DAG Executor + Visualizer

**Why:** Planner가 DAG를 생성해도 실행 엔진이 없으면 "계획만 세우는 시스템". Dispatcher→Worker Pool→claude -p 실행 파이프라인을 완성해야 자율 실행이 가능. Visualizer는 프론트엔드 DAG 시각화의 필수 데이터 소스.

**Impact:** 목표→DAG→실제 코드 생성까지의 end-to-end 파이프라인 완성.

#### 🥉 3순위: Cognitive/DAG/Memory 단위 테스트

**Why:** 핵심 상태 머신(GoalEngine 7단계 전이, TaskDAG 토폴로지 정렬, MemoryStore 유사도 검색)이 검증 없이 프로덕션에 투입된 상태. 자율 실행 시스템에서 상태 전이 버그는 치명적.

**Impact:** 핵심 로직의 정확성 보장, 향후 리팩토링 시 안전망.

---

### 15.3 1순위 구현 계획: Goals/Memory 프론트엔드 UI

#### A. 파일 목록 및 변경 내용

| 파일 | 작업 | 예상 줄 수 | 설명 |
|------|------|-----------|------|
| `web/static/goals.js` | 🆕 신규 | ~450줄 | Goal CRUD UI, DAG 트리 뷰, Gate 승인 버튼, 실시간 상태 폴링 |
| `web/static/goals.css` | 🆕 신규 | ~220줄 | 목표 카드, DAG 노드/연결선, 진행률 바, 상태 뱃지 스타일 |
| `web/static/memory-view.js` | 🆕 신규 | ~200줄 | 메모리 목록/검색, 타입별 필터(decision/pattern/failure/context), 추가/삭제 |
| `web/static/index.html` | 수정 | +60줄 | Goals 섹션 HTML 골격 + Memory 섹션 HTML + 네비게이션 탭 추가 + JS/CSS 로드 |
| `web/static/i18n.js` | 수정 | +40줄 | goal_*, dag_*, memory_*, task_* 번역 키 (ko/en) |
| `web/static/api.js` | 수정 | +30줄 | Goals/Memory API 호출 함수 (fetchGoals, createGoal, approveGate, fetchMemory 등) |
| **합계** | | **~1,000줄** | |

#### B. goals.js 핵심 기능 설계

```
1. Goal 목록 렌더링
   - GET /api/goals → 목표 카드 목록
   - 상태별 필터: all / active / completed / failed / cancelled
   - 각 카드: objective, mode, progress %, created_at, cost_usd

2. Goal 생성 폼
   - objective (텍스트), mode (full_auto/gate/watch/pair 라디오),
     cwd (디렉토리 선택기 재활용), budget (optional)
   - POST /api/goals → 생성 후 목록 갱신

3. Goal 상세 뷰 (카드 클릭 시 확장)
   - DAG 트리 뷰: 태스크 노드를 CSS grid/flexbox 기반 트리로 시각화
     - 노드 색상: pending(회색), running(파랑), completed(녹색), failed(빨강)
     - 노드 간 연결선: CSS border + pseudo-element 또는 SVG
   - Gate 승인: mode=gate일 때 "다음 단계 승인" 버튼 표시
   - 태스크 결과 인라인 표시: 각 노드 클릭 시 result 텍스트 펼침

4. 실시간 갱신
   - 5초 간격 폴링 (SSE는 goals에 아직 미구현이므로 폴링 우선)
   - 상태 변경 시 시각적 트랜지션
```

#### C. 네비게이션 구조 변경

현재 index.html은 섹션 기반 (Send Task → Job List → Presets → Automations).
Goals 섹션을 Job List 뒤에 삽입, Memory 섹션을 그 뒤에 삽입:

```
Send Task → Job List → 🆕 Goals → 🆕 Memory → Presets → Automations
```

#### D. DAG 시각화 접근법

Mermaid.js CDN 로드 대신 **순수 CSS 트리 뷰** 채택:
- 외부 의존성 0 (기존 Vanilla JS 철학 유지)
- `<ul>/<li>` 중첩 구조 + CSS `::before`/`::after`로 연결선
- 노드 상태에 따른 색상 클래스: `.dag-pending`, `.dag-running`, `.dag-completed`, `.dag-failed`
- 병렬 태스크는 flex row로 표현

**대안 (복잡한 DAG):** dag/visualizer.py가 구현되면 Mermaid 문법 문자열을 반환하고, 프론트엔드에서 Mermaid.js CDN으로 렌더링하는 방식으로 전환 가능.

#### E. 의존성 및 리스크

| 항목 | 상태 | 대응 |
|------|------|------|
| /api/goals API | ✅ 완성 | 즉시 연결 가능 |
| /api/memory API | ✅ 완성 | 즉시 연결 가능 |
| DAG 실행 (execute) | ❌ executor 미구현 | UI에서 "Plan" 버튼은 활성화, "Execute" 버튼은 비활성 상태로 표시 + 툴팁 "DAG Executor 미구현" |
| Mermaid.js | 불필요 | 순수 CSS 트리 뷰 선택 |
| SSE for goals | 미구현 | 폴링 방식 우선, 향후 SSE 전환 |

---

### 15.4 2순위 구현 계획: DAG Executor + Visualizer

| 파일 | 작업 | 예상 줄 수 | 설명 |
|------|------|-----------|------|
| `dag/executor.py` | 🆕 신규 | ~250줄 | 메인 루프: ready 노드 추출→Worker 프롬프트 조립→claude -p 디스패치→결과 수집→상태 갱신→다음 ready 노드. 동시성 제한(max_concurrent), 실패 재시도(max_retries=2), 비용 예산 체크 |
| `dag/visualizer.py` | 🆕 신규 | ~100줄 | TaskDAG → Mermaid 문법 변환 + 순수 dict 트리 변환 (프론트엔드용) |
| `dag/__init__.py` | 수정 | +5줄 | executor, visualizer export 추가 |
| `cognitive/orchestrator.py` | 수정 | +30줄 | execute() 메서드에서 dag/executor.py 호출로 전환 (현재 stub) |

**executor.py 핵심 루프:**
```
while dag.has_pending():
    ready = dag.get_ready_nodes()
    for node in ready[:max_concurrent]:
        node.status = "running"
        prompt = build_worker_prompt(node, memory_context)
        job_id = dispatch_claude_p(prompt, cwd, worktree=True)
        running[node.id] = job_id

    for node_id, job_id in list(running.items()):
        result = poll_job_result(job_id)
        if result:
            dag.update_node(node_id, status=result.status, ...)
            del running[node_id]

    check_budget(dag.total_cost, goal.budget)
    sleep(poll_interval)
```

### 15.5 3순위 구현 계획: 단위 테스트

| 파일 | 테스트 대상 | 예상 테스트 수 |
|------|-----------|--------------|
| `tests/test_goal_engine.py` | GoalEngine: create→list→update_status→cancel, 상태 전이 (pending→planning→executing→evaluating→completed), attach_dag, evaluate_completion | ~15개 |
| `tests/test_dag_graph.py` | TaskDAG: add_node, add_edge, topological_sort, 순환 감지, get_ready_nodes, update_status | ~12개 |
| `tests/test_memory_store.py` | MemoryStore: add/get/update/delete, search(키워드), get_relevant(유사도), 타입 필터, 프로젝트 스코프 | ~10개 |
| `tests/test_api_goals.py` | Goals API 통합: POST/GET/DELETE /api/goals, approve, 에러 응답 검증 | ~10개 |
| `tests/test_api_memory.py` | Memory API 통합: POST/GET/DELETE /api/memory, 검색 파라미터 검증 | ~8개 |
| **합계** | | **~55개** |

---

### 15.6 로드맵 갱신

```
Phase 5a (현재 → 1주)  ─  프론트엔드 UI 완성
  ├─ goals.js + goals.css: 목표 CRUD + DAG 트리 뷰 + Gate 승인
  ├─ memory-view.js: 메모리 검색/CRUD
  ├─ index.html: Goals/Memory 섹션 + 네비게이션 탭
  ├─ i18n.js: 번역 키 확장
  └─ api.js: Goals/Memory API 호출 함수

Phase 5b (1-2주)  ─  DAG 실행 엔진
  ├─ dag/executor.py: DAG 순회 + claude -p 디스패치 루프
  ├─ dag/visualizer.py: DAG → Mermaid/dict 변환
  └─ cognitive/orchestrator.py: execute() stub → executor 연결

Phase 5c (2-3주)  ─  테스트 보강
  ├─ tests/test_goal_engine.py: GoalEngine 단위 테스트
  ├─ tests/test_dag_graph.py: TaskDAG 단위 테스트
  ├─ tests/test_memory_store.py: MemoryStore 단위 테스트
  ├─ tests/test_api_goals.py: Goals API 통합 테스트
  └─ tests/test_api_memory.py: Memory API 통합 테스트

Phase 6 (3-4주)  ─  자동 평가: Evaluator + Gate (기존 계획 유지)
Phase 7 (지속적)  ─  학습 루프: Learning + Self-Improvement (기존 계획 유지)
```
