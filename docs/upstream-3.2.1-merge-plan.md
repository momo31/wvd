# 업스트림 3.2.1 통합 Implementation Plan

> **For agentic workers:** 실제 구현 요청을 받은 뒤 `superpowers:executing-plans` 또는 사용자가 선택한 `superpowers:subagent-driven-development`로 작업별 체크리스트를 실행한다. 이 문서 보완 요청은 구현 착수나 실행 방식 선택을 의미하지 않는다. 현재 코드의 결합도를 고려하면 한 구현자가 순서대로 진행하는 방식을 권고한다.

**Goal:** 업스트림 3.2.1의 새 UI와 런타임 기능을 도입하면서 한국어, 스마트 개봉, Telegram 원격 제어, 최근 결함 수정 7건을 보존한다.

**Architecture:** 현재 작업본에 업스트림 변경을 기능별로 이식한다. 설정·리소스를 먼저 이전하고, 실행별 정지와 작업 인계 계약을 유지한 컨트롤러에 WebView UI를 연결한다. 표준 logging과 기존 모듈 경계를 유지하며 `script.py` 전체 재구조화는 포함하지 않는다.

**Tech Stack:** Windows, Python 3.14, unittest, OpenCV/NumPy, pywebview 6.2.1, WebView2, gettext/Babel, PyInstaller.

**Spec:** [이 문서의 범위와 설계 결정](#4-범위와-설계-결정), [AGENTS.md](../AGENTS.md), [최근 수정 기록](source-audit-remediation-plan.md), [빌드 및 배포 절차](build-and-release.md).

조사·Superpowers 검토일: 2026-10-31 KST. 실행일: 2026-10-31~2026-11-01 KST. 상태: **Task 0~8 통합 완료, 독립 검토 5건 수정 및 최종 개발 검증 통과**. 사용자의 실행 요청에 따라 별도 작업본에 통합했다. 현재 결과와 제한 사항은 [병합 보고서](upstream-3.2.1-merge-report.md)를 기준으로 확인한다. 아래 최초 조사·설계 기록은 비교 근거로 보존한다.

## Global Constraints

- 작업 기준은 `recovered-source`의 HEAD와 미커밋 수정이다. 원래 상위 폴더의 남은 소스나 배포본을 작업 기준으로 사용하지 않는다.
- 대상은 고정 커밋 `4ba47a7af16eee874ae1ae178a2ca27055d72f61`이다. 이후 upstream HEAD를 함께 가져오지 않는다.
- 기존 수정과 신규 파일을 보존한다. Codex는 커밋·push·PR 생성·갱신을 하지 않는다. 스킬의 단계별 commit 지시는 검증·diff 기록으로 대체한다.
- `chestFlag`, `whowillopenit`, `chestOpening` 중 하나라도 검출되면 해당 프레임에서 `dialogueNext`를 탭하지 않는다. 현재 임계값 `0.95`와 최대 `3`회 스킵, 상태 재판정 조건을 유지한다.
- UI 언어는 `ko_KR/en_US/zh_CN`, 게임 이미지 언어는 `en_US/zh_CN`을 대상으로 한다. 한국어 UI 지원을 한국어 게임 이미지 지원으로 표시하지 않는다.
- 기본·지정 설정 경로, Telegram 값, 작업별 설정, 스마트 개봉, 전략 설정과 기존 오류 분류를 보존한다. 실제 개인 설정을 테스트 fixture에 복사하지 않는다.
- 개발 검증은 가짜 화면·장치·API를 사용한다. 실제 Telegram 전송·게임 조작·에뮬레이터 재시작·업데이트 적용은 자동 검증에 포함하지 않는다.
- 새 의존성 검증은 별도 개발 환경에서 한다. 빌드·배포는 별도 요청 범위이며, 빌드 단계에서 테스트·exe 실행·리소스/해시 검증을 추가하지 않는다.

## Review Focus

| 위험 입력·상태 | 기대 동작 | 소유 작업·추가 검증 |
|---|---|---|
| 지정 설정이 잘못됐거나 Telegram 키·새 언어 키가 이미 존재함 | 기본 설정으로 대체하지 않고 기존 값·파일을 보존 | Task 1: `test_config_migration_is_idempotent_and_preserves_custom_path` |
| 작업 인계와 정지·중복 시작·이전 작업 완료가 겹침 | 단일 작업만 실행, 정지가 인계보다 우선, 최종 완료 통지는 1회 | Task 4: `test_stop_wins_over_handoff_and_stale_events` |
| 동일 이미지 ID의 언어 전환, 필수 이미지 누락 | 다른 언어 캐시를 재사용하지 않고 실행 전에 누락을 식별 | Task 2: `test_language_cache_and_required_remote_templates` |
| UI 닫기와 원격 귀환·다운로드·지연 콜백이 겹침 | 신규 요청 차단, 정지·취소 후 제한 시간 내 종료 | Task 5·6: `test_close_cancels_workers_before_destroy` |
| 다운로드 취소 뒤 지연된 재시작 이벤트 또는 다른 저장소의 업데이트 정보가 도착함 | 재시작·외부 배포본 적용을 수행하지 않음 | Task 7: `test_cancel_and_foreign_release_never_restart` |

아래 실행 결과에 해당 위험 입력의 검증을 기록한다. 최초 조사 결과와 통합 후 결과를 구분한다.

## 1. 비교 기준과 현재 상태

| 항목 | 확인 결과 |
|---|---|
| 작업 폴더 | `C:/Users/admin/Documents/momo31-wvd/recovered-source` |
| 현재 브랜치 | `master` |
| 현재 HEAD | `4e907ba8ec40d869cf90dcd8d992afcd1c328ba3` |
| 현재 버전 | `2.7.1-momo.1` |
| 미커밋 작업 | 이 문서 작성 전 기준 수정 파일 14개, 신규 파일 6개. 최근 결함 수정 7건 포함 |
| 이번 검토 시작 시 상태 | 수정 파일 14개, 신규 파일 7개. 위 신규 6개에 이 계획서가 추가됨 |
| 사용자 원격 | `https://github.com/momo31/wvd.git` |
| 업스트림 | `https://github.com/arnold2957/wvd.git` |
| 대상 태그 | `3.2.1` |
| 대상 커밋 | `4ba47a7af16eee874ae1ae178a2ca27055d72f61` — 2026-10-31 |
| 기능 비교 기준 태그 | `2.7.1`, `9900fd6fc0be74f7fed81c3d6fe1748b953a0062` |
| 실제 Git 공통 조상 | `2.5.2`, `1a09429598bb48dd10d63307f4df45c82e62215d` |
| 업스트림 2.7.1 이후 변화 | 112개 커밋, 743개 파일 변경, 10,894줄 추가·4,071줄 삭제 |
| 파일 변경 분류 | 추가 320개, 수정 14개, 이동·이름 변경 392개, 삭제 17개 |
| HEAD 병합 시뮬레이션 | 16개 경로에서 충돌 |

현재 작업본은 원래 상위 폴더가 아닌 `recovered-source`다. 다음 작업도 이곳의 [AGENTS.md](../AGENTS.md)와 현재 파일 상태를 기준으로 한다.

기능상 통합 수준은 2.7.1이지만 Git 공통 조상은 2.5.2다. 따라서 실제 Git 병합에서는 이전에 수동 통합한 변경이 다시 충돌할 수 있다. 기능별 검토에는 `2.7.1..3.2.1` 차이를 함께 사용하고, 이미 적용된 로컬 수정과 중복되는 부분을 구분한다.

## 2. 업스트림 변경 사항

3.2.1의 핵심은 Tk UI를 HTML/pywebview로 전환하고 요약 화면을 개편한 것이다. 업스트림 변경 기록은 이 버전도 아직 테스트 버전이라고 명시한다. 작업명·전투 전략의 언어 전환 표시와 전갈녀·식스암즈 경로도 변경됐다.

2.7.1 이후 누적된 주요 변경은 다음과 같다.

- 게임 언어별 이미지 분리와 UI 언어·게임 언어 설정 분리.
- 낚시, 미끼 보충, 낚시 결과 집계.
- 재기 자원 소진 후 채굴·7000G·낚시 작업 전환.
- 요정 아이템 감지에 따른 후속 작업 자동 전환.
- 던전 진입, 층 이름 판정, 잘못 진입한 층의 이탈 처리 개선.
- 전투 대상 화살표 탐지 개선.
- 정지 대기와 ADB 연결 종료 처리 변경.

퀘스트 카탈로그는 업스트림 2.7.1의 56개에서 62개로 바뀌었다. 신규 8개에는 낚시, FFXI 1F 정예·4F, 요정 선행·후속 작업 등이 포함되며, 기존 `DOE`와 `jier`는 삭제됐다. 저장된 기존 작업 ID에 대한 호환 처리가 필요하다.

근거: [대상 변경 기록](https://github.com/arnold2957/wvd/blob/4ba47a7af16eee874ae1ae178a2ca27055d72f61/CHANGES_LOG.md), [대상 소스](https://github.com/arnold2957/wvd/tree/4ba47a7af16eee874ae1ae178a2ca27055d72f61/src), [대상 퀘스트 데이터](https://github.com/arnold2957/wvd/blob/4ba47a7af16eee874ae1ae178a2ca27055d72f61/resources/quest/quest.json).

## 3. 병합 위험과 처리 방향

| 영역 | 확인한 차이 | 처리 방향 |
|---|---|---|
| 설정 보존 | 업스트림 저장 코드가 `GENERAL`을 새로 구성해 Telegram 설정을 잃을 수 있다. | 현재의 알 수 없는 설정 키 보존, 원자적 저장, 사용자 설정 위치, `-config` 처리를 유지한다. |
| 한국어 | 새 UI의 언어 선택은 중국어·영어만 지원한다. 정적으로 추출 가능한 신규 Python 번역 키 중 48개가 현재 한국어 카탈로그에 없다. HTML에도 중국어 표시 문자열이 있다. | `ko_KR` 선택과 HTML 번역을 추가하고, Python·작업명·카테고리·전략명·도움말·변경 기록을 함께 검증한다. 48개는 동적 문자열과 HTML을 제외한 수치다. |
| 이미지 경로 | 이미지가 `common/en_US/zh_CN`으로 재배치된다. 현재에만 있는 이미지 17개가 있다. | 로컬 이미지와 Telegram 제목 화면 인식 경로를 함께 이전한다. 이미지 캐시는 언어를 구분한다. |
| 상자 처리 | 업스트림에는 현재의 스마트 개봉과 상자 우선 판정이 없다. 새 요정 작업은 상자 결과에서 특정 아이템을 감지한다. | 스마트 개봉·상자 가드를 유지하면서 아이템 감지와 후속 작업 전환을 결합한다. |
| 작업 전환·정지 | 업스트림은 공용 정지 이벤트와 `switch_quest`를 사용한다. 현재 인계 처리 일부는 `7000G`에 한정돼 있다. | 실행별 정지·원격 귀환·완료 통지를 유지하고, 기존 인계 처리를 신규 대상 작업까지 확장한다. |
| 컨트롤러·UI | 현재 `AppController`와 Telegram 설정 패널은 Tk 이벤트 처리에 연결돼 있다. | 기존 작업 관리 기능을 새 이벤트 처리 방식에 연결하고, Telegram 설정·상태·연결 테스트를 새 UI에 제공한다. |
| 로그·요약 | 새 UI의 로그 수신부는 loguru에 의존한다. | 현재 표준 logging을 유지하면서 구조화된 요약 데이터를 새 UI에 연결한다. |
| 업데이트 | 현재의 다운로드 취소 수정은 새 UI에도 연결해야 한다. | 취소 이벤트, 중복 다운로드 방지, 실패 후 UI 복원을 유지한다. 자동 업데이트 배포 채널도 확인한다. |
| 의존성·패키징 | `pywebview==6.2.1`과 `src/ui.html`이 추가된다. | Python 3.14·WebView2 호환성을 개발 단계에서 확인하고, 현재 CI와 로컬 빌드 설정을 갱신한다. |

주요 대상 파일은 `src/main.py`, `src/gui.py`, `src/ui.html`, `src/script.py`, `src/utils.py`, `src/auto_updater.py`, `resources/quest/quest.json`, 이미지·로케일, Telegram 어댑터·워커·설정 UI, 빌드 워크플로다.

16개 충돌 경로는 **미커밋 변경을 포함하지 않는 HEAD 기준**의 `git merge-tree` 결과다. 미커밋 수정은 별도로 주요 텍스트 파일 12개에 대해 실제 공통 조상·현재 파일·대상 파일의 3방향 검사를 수행했다. 자동으로 합쳐지는 파일도 동작 호환성을 보장하지 않는다.

## 4. 범위와 설계 결정

### 4.1 방식과 인계 상태

| 검토한 방식 | 장단점 | 이 계획의 선택 |
|---|---|---|
| `git merge --no-commit --no-ff`로 직접 통합 | 업스트림 조상을 기록할 수 있지만 실제 공통 조상이 2.5.2라 이미 이식한 변경도 충돌한다. 미커밋 수정과 충돌 해결이 섞이고 초기 단계마다 실행 가능한 상태를 유지하기 어렵다. | 정식 merge commit 이력이 요구될 때 별도로 선택한다. |
| 현재 작업 트리에서 기능별 이식 | 현재 수정 7건을 기준으로 작은 단위의 실패→수정→통과를 반복할 수 있다. Git 조상 관계는 갱신되지 않는다. | **작성자 권고안.** 기존 방향을 구체화한 소스 통합 방식이다. |

완료 산출물은 별도 작업본의 **일반 미커밋 diff와 신규 파일**이다. `MERGE_HEAD`를 남기지 않고 HEAD는 시작 커밋 그대로 유지한다. 따라서 이를 정식 Git merge 완료라고 보고하지 않는다. 사용자가 정식 merge 이력을 요구하면 구현 전 방식부터 조정한다. 다음 병합 때도 공통 조상이 오래된 상태라는 점을 인계한다.

### 4.2 구현자가 추측하지 않을 계약

다음은 이번 문서 보완에서 정한 **권고 동작**이며 사용자가 이미 선택한 실행 정책으로 간주하지 않는다.

| 항목 | 권고 동작 |
|---|---|
| 자동 작업 전환 | 실행 중에는 대상 작업 ID로 저장된 설정을 다시 조합한다. `GENERAL`은 유지하고 `TASK_SPECIFIC_CONFIG=True`이며 대상 섹션이 있으면 그 섹션, 그 외에는 `DEFAULT`를 사용한다. 이전 작업의 전략·회복 옵션을 무조건 상속하지 않는다. |
| 선택값 저장 | 자동 전환은 현재 실행과 UI의 실행 대상만 바꾼다. 저장된 `FARM_TARGET`은 유지한다. 다른 옵션 저장·창 닫기에서도 실행 대상을 선택값으로 덮어쓰지 않는다. 사용자의 GUI/Telegram 작업 선택은 기존처럼 저장하되 자동 시작하지 않는다. |
| 실행 수명 | 인계 체인 동안 `run_id`, `RemoteRuntime`, 최종 완료 latch를 유지한다. 워커마다 증가하는 `worker_generation`으로 같은 실행의 이전 워커 이벤트도 구분한다. 새 작업용 `FarmConfig`, `Factory`, `RuntimeContext`를 만들고 작업별 카운터·전략은 초기화한다. 이전 작업 종료 전 신규 작업 실행은 금지한다. |
| 정지·오류 | 로컬 정지는 현재 실행의 강제 정지 이벤트, `/stop`은 기존 귀환·제목 화면 전환 경로를 사용한다. ADB 복구 실패는 `ERROR`다. 새로운 전역 정지 이벤트를 병렬로 두지 않는다. |
| 이번 회차 후 정지 | 새 UI의 예약 정지는 `RemoteRuntime.stop_after_run_event`에 실행별로 보관한다. 현재 회차 완료 또는 다음 작업 인계 경계에서 `LOCAL_STOP`으로 끝내고 다음 작업을 시작하지 않는다. 예약 취소는 즉시 반영하며 새 실행은 예약 해제 상태로 시작한다. |
| 앱 닫기 | 컨트롤러가 신규 시작·인계·다운로드를 차단하고 강제 정지·다운로드 취소를 요청한다. 기존 서비스 종료 한도 36초와 작업 종료 한도 15초를 전체 45초 안에서 병행 처리한다. 정상 정리 후 창을 닫고, 한도 초과 시 오류를 남기고 자기 프로세스만 종료하는 마지막 수단을 둔다. 진행 중인 원격 귀환을 10분 기다리는 동작으로 바꾸지 않는다. |
| 업데이트 | 자동 다운로드 후보는 `momo31/wvd`의 포크 배포본으로 한정한다. 포크 메타데이터가 없거나 유효하지 않으면 수동 릴리스 링크만 제공하고 업스트림 배포본으로 대체하지 않는다. |
| 버전·공개 | 통합 버전 제안은 `3.2.1-momo.1`. 현재 CI의 prerelease 분류는 유지한다. 자동 업데이트용 Pages 게시 정책 변경과 실제 공개는 후속 릴리스 범위이며, 이번 통합에서는 준비되지 않은 채널을 비활성으로 표시한다. |

범위에 포함하는 것은 3.2.1의 사용자 기능과 기존 로컬 기능 보존이다. QQ 알림, 전체 로깅 라이브러리 교체, 전면 모듈 분리, 신규 게임 언어용 이미지 제작, 실제 릴리스·배포는 제외한다. 지원 언어에서 실행에 필요한 이미지가 없는 작업은 선택 단계에서 사유를 표시하고 실행하지 않는다.

### 4.3 파일 책임과 순서

| 파일·영역 | 책임 | 소유 작업 |
|---|---|---|
| `src/utils.py`, `src/script.py::CONFIG_VAR_LIST`, `src/gui.py::LoadConfig`, `mod/telegram_remote_control/config.py` | 설정 이전·저장·대상 작업 설정 조합 | 1 |
| `resources/images`, `resources/quest/quest.json`, `src/utils.py`, `mod/telegram_remote_control/adapters.py` | 리소스 탐색·캐시·퀘스트 ID와 언어 지원 | 2 |
| `src/script.py`, `src/combat_strategy.py`, 기존 가드 모듈 | 화면·던전·전투·상자 불변 조건 | 3 |
| `src/main.py`, `src/script.py`, `mod/telegram_remote_control/{runtime_bridge,worker,feature}.py` | 작업 인계와 신규 자동화 | 4 |
| `src/main.py`, `mod/telegram_remote_control/adapters.py` | 단일 컨트롤러 이벤트 처리·종료 | 5 |
| `src/gui.py`, 새 `src/ui.html`, `src/utils.py`, `locale`, Telegram 로케일·설정 UI | WebBridge, 한국어, 로그·요약, 원격 설정 | 6 |
| `src/main.py`, `src/auto_updater.py`, `src/gui.py`, `src/ui.html` | 포크 업데이트와 취소·재시작 | 7 |
| `requirements.txt`, `.github/workflows/build-executable.yml`, 로컬 `wvd.spec`, 문서 | 개발 검증·패키징 계약·최종 인계 | 0·8 |

의존 순서는 **0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8**이다. 같은 `main.py/script.py/utils.py`를 수정하므로 동시 구현하지 않는다. Task 0의 환경 확인은 UI 구현 전에 끝내며, 실패하면 Python 버전을 임의로 낮추지 않고 원인과 대안을 기록한다.

## 5. 실행 체크리스트

아래 체크박스는 모두 **향후 구현 작업**이다. 새 테스트는 먼저 실패 이유가 목표 행동의 부재인지 확인하고, 최소 수정 후 동일 테스트의 통과를 확인한다. 단순 파일 이동·데이터 이식은 실패 재현 대신 파일 목록·참조·기존 행동 검사로 검증한다. 각 작업 종료 시 diff와 검증 결과를 기록하며 커밋하지 않는다.

### 공통 실행 환경

아래 명령은 Task 0에서 준비한 **통합 작업본의 루트**에서 실행한다. 이후 `$mergePython`을 사용하는 명령은 이 설정을 전제로 한다. PowerShell에서 종료 코드가 0이 아니면 다음 단계로 진행하지 않는다.

```powershell
$mergeRoot = (Get-Location).Path
$mergePython = Join-Path $mergeRoot 'build/wvd_py314_venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $mergePython)) { throw '통합 작업본의 개발 Python이 없습니다.' }
$env:PYTHONPATH = "$mergeRoot;$mergeRoot/src"
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:PYTHONUTF8 = '1'
```

### Task 0: 현재 작업 보존과 새 UI 환경 확인

**Files:** 원본의 추적·미추적 변경 전체; 별도 작업본의 `build/merge-321-baseline/`; `requirements.txt`.
**Interfaces:** 입력은 고정 HEAD와 현재 작업 트리, 출력은 동일 파일 내용을 가진 통합 작업본·SHA-256 목록·Python/WebView 환경 기록이다. Git 인덱스와 미추적 파일은 패치 하나로 모두 보존되지 않는다.

- [x] `git status --porcelain=v1`, HEAD, diff와 신규 파일 목록을 기록한다. `git diff --binary HEAD --output=<절대경로>`로 누적 패치를 보관하고, staged/unstaged 차이도 각각 기록한다. PowerShell `>`로 바이너리 패치를 재인코딩하지 않는다.
- [x] 미추적 파일은 목록의 상대 경로대로 별도 복사하고, 수정 전 파일·신규 파일·로컬 `wvd.spec`의 SHA-256 목록을 만든다. 로그·개인 설정·배포 폴더를 산출물에 포함하지 않는다.
- [x] 실행 시 `using-git-worktrees`로 기존 격리를 확인하고 네이티브 도구를 우선 사용한다. 기준 ref를 `4e907ba8ec40d869cf90dcd8d992afcd1c328ba3`로 명시한다. 자동으로 변경이 이전됐는지 확인해 중복 적용을 피한다. Git fallback 경로는 작업 공간 안의 `git check-ignore`로 확인된 디렉터리로 제한한다.
- [x] 새 작업본에 패치를 `git apply --check` 후 적용하고 신규 파일·로컬 spec을 복사한다. 원본과의 해시 일치, 원본 상태 불변, `MERGE_HEAD` 부재를 확인한다. `stash/reset/clean`으로 원본을 정리하지 않는다.
- [x] 통합 작업본 안에 Python 3.14 가상환경을 만들고 현재 의존성을 설치한다. 기본·Telegram 카탈로그를 컴파일한 후 아래 전체 검증으로 기준 결과를 확보한다. 이전의 268개는 비교 자료이며 새 작업본의 실행 결과로 대체한다.
- [x] 같은 격리 환경에 `pywebview==6.2.1`을 설치하고 `pip check`, import, Python·WebView2 버전을 기록한다. 별도 최소 개발 창에서 로드·JS bridge 호출·닫기를 확인한다. 이 검사는 앱·Telegram·ADB를 실행하지 않는 개발 환경 확인이다. 통과 후 `requirements.txt`에 의존성을 반영한다.

**통과 조건:** 원본과 작업본의 기준 파일 내용이 일치하고 기준 테스트가 통과하며, WebView 최소 창의 로드·호출·닫기 결과가 기록돼 있다. 설치 또는 창 확인 실패 시 UI 의존 작업은 미완료로 남긴다.

### Task 1: 설정 이전과 실행 대상 설정 계약

**Files:** Modify `src/utils.py`, `src/script.py`, `src/gui.py`, `src/main.py`, `mod/telegram_remote_control/config.py`; Test `tools/test_custom_config.py`, `tools/test_config_persistence.py`, `mod/telegram_remote_control/tests/test_config_and_commands.py`.
**Interfaces:** 기존 `LoadRawConfigFromFile(config_file_path=None, migrate_recovery=True)`와 `SaveConfigToFile(config_data, config_file_path=None)`를 유지한다. 새 `src/utils.py::_migrate_language_settings(config_data: dict) -> tuple[dict, bool]`와 `mod/telegram_remote_control/config.py::load_farm_setting_for_target(config_path, target: str, load_raw, build_setting) -> Any`를 추가한다. 후자는 저장 없이 새 설정을 반환하고 `_CONFIG_PATH`를 유지한다.

- [x] `test_config_migration_is_idempotent_and_preserves_custom_path`를 추가한다. `LANGUAGE=ko_KR`만 있는 임시 파일은 새 UI 키가 `ko_KR`, 게임 키가 `en_US`가 된다. 새 키가 있으면 유지하고 두 번째 이전은 `changed=False`여야 한다. `TELEGRAM_*`, `SMART_DISARM_CHEST`, `BYPASS_FAST_GAME`, `ACTIVE_BEG_MONEY`, 전략·다른 작업 섹션과 기본 파일 바이트는 보존한다.
- [x] `test_handoff_loads_target_settings_without_persisting_selection`을 추가한다. `TASK_SPECIFIC_CONFIG=True`인 `fishing` 섹션의 전략은 사용하지만 저장된 원래 `FARM_TARGET`과 파일 바이트는 유지되는지 단언한다. 대상 섹션 부재·기능 비활성은 `DEFAULT`를 사용한다.
- [x] 아래 명령으로 새 테스트 실패를 확인한 뒤 기존 원자적 저장·복구 키 이전에 새 키 이전을 연결한다. 언어는 지정 설정을 읽은 뒤 GUI/script가 사용하도록 초기화하고, 새 UI 완성 전에는 기존 `LANGUAGE` 호환도 유지한다.
- [x] 삭제된 `DOE/jier`와 유효하지 않은 대상은 GUI/Telegram/헤드리스 모두 시작을 거부한다. 설정은 보존하고 GUI에는 재선택 안내, 헤드리스에는 오류 종료를 제공한다. 잘못된 명시적 설정 파일의 fallback 금지 회귀도 유지한다.
- [x] 검증: `& $mergePython -B -X utf8 -m unittest tools.test_custom_config tools.test_config_persistence mod.telegram_remote_control.tests.test_config_and_commands -v` → 종료 0, 추가 사례 포함 `OK`.

새 이전 테스트의 핵심 단언은 다음과 같다. 실제 파일·다른 키 보존 검증은 기존 `CustomConfigTests`의 임시 설정 fixture를 확장한다.

```python
migrated, changed = utils._migrate_language_settings({"GENERAL": {"LANGUAGE": "ko_KR"}})
self.assertTrue(changed)
self.assertEqual(migrated["GENERAL"]["LANGUAGE_SCRIPT"], "ko_KR")
self.assertEqual(migrated["GENERAL"]["LANGUAGE_GAME"], "en_US")
self.assertEqual(utils._migrate_language_settings(migrated), (migrated, False))
```

### Task 2: 이미지·퀘스트 데이터 이전

**Files:** Modify `src/utils.py`, `resources/images`, `resources/quest/quest.json`, `mod/telegram_remote_control/adapters.py`, 기존 이미지 경로 고정 테스트; Create/Test `tools/test_upstream_321_merge.py`의 `ResourceMigrationTests`.
**Interfaces:** `LoadTemplateImage(shortPathOfTarget, language=None)`는 선택 언어와 `common`, 기존 mod 지원 경로 순서로 탐색하고 `(language, shortPathOfTarget)`별로 캐시한다. `reflectImage(folder, lang=None)`는 대화는 선택 게임 언어, 캐릭터는 `common`을 사용한다. 새 `ValidateQuestResources(target: str, language: str) -> list[str]`는 누락된 필수 이미지 ID를 반환하며 기기를 조작하지 않는다.

- [x] `test_language_cache_and_required_remote_templates`를 추가한다. 임시 `fixture.png`의 en/zh 픽셀을 각각 10/20으로 만들고 `self.assertEqual(int(LoadTemplateImage('fixture', 'en_US')[0, 0, 0]), 10)` 및 zh의 20을 확인한다. 필수 템플릿을 임시 트리에서 누락시키면 `self.assertIn(missing_id, ValidateQuestResources(target, language))`여야 한다. mod 탐색과 캐시 재사용도 검사한다.
- [x] 이동 392개와 로컬 전용 17개를 ID·기존 경로·새 경로·적용 언어로 대응시킨다. 문자 포함 이미지를 임의로 `common`에 넣지 않는다. 한국어 점검 공지는 게임 언어와 별개로 감지하는 기존 조건을 보존한다. Telegram `image_root()/match_mod()`와 상자 fixture의 직접 경로도 함께 바꾼다.
- [x] 고정 대상 커밋의 퀘스트 변경을 작업 ID 기준으로 이식한다. 신규 8개·삭제 2개와 이름이 유지된 기존 작업의 경로 변경까지 비교하고 `_FloorCheck`, `_SPECIALJUNK`, `_SPECIALJUNK_CALLBACK` 참조를 검증한다.
- [x] 정적 퀘스트 참조와 동적 분기의 필수 리소스 목록으로 `ValidateQuestResources`를 구현하고 시작 전 호출한다. 중국어 전용 작업이나 제목 화면 리소스가 없는 원격 시작은 사용 불가 사유를 표시한다. 다른 게임 언어의 이미지로 조용히 대체하지 않는다.
- [x] 검증: `& $mergePython -B -X utf8 -m unittest tools.test_upstream_321_merge.ResourceMigrationTests tools.test_runtime_guards mod.telegram_remote_control.tests.test_title_and_login_transition -v` → 종료 0. 이전 버전 테스트의 경로·바이트 크기 단언은 해당 자산이 바뀐 이유를 기록하고 실제 식별 행동 검증으로 갱신한다.

### Task 3: 화면·전투·던전·상자 동작 통합

**Files:** Modify `src/script.py`, `src/utils.py`, 필요한 `src/combat_strategy.py`; Test `tools/test_upstream_321_merge.py`의 `RuntimeIntegrationTests`, `tools/test_runtime_guards.py`, 기존 복구·스마트 개봉 테스트.
**Interfaces:** 업스트림 `CheckFloorName(screenImage, template_name, errorThreshold=0.1)`, `StateCombat_DetectArrow(screenshot)`, `Fishing_DetectBobber(screenshot)`를 이식하되 호출자는 현재 `Factory` 내부 상태와 가드를 사용한다. `StateChest()`, `CheckIfAtThreshold(...)`, `decide_chest_guard_action(...)`의 상자 우선 계약은 유지한다.

- [x] 먼저 `test_wrong_floor_exits_once_and_loading_does_not_restart_loop`와 `test_arrow_detection_preserves_bounded_fallback`을 추가한다. 틀린 층에서는 이탈 동작 1개만 예약하고, 로딩 화면에서는 새 재시작을 연속 요청하지 않으며, 화살표 미검출은 기존 제한된 대상 탐색을 유지해야 한다.
- [x] 기존 합성 상자 fixture에 `_SPECIALJUNK` 활성 사례를 추가한다. `chestFlag`와 거짓 `dialogueNext`가 동시에 보여도 기존 fixture의 `namespace['Press'].assert_called_once_with(expected_open)`을 유지한다. 스마트 개봉·빠른 개봉에서도 아이템 확인 전 결과를 건너뛰지 않는다.
- [x] 목표 테스트 실패를 확인한 뒤 EoT·층 판정·전투 감지·상자 결과 감지를 함수 단위로 이식한다. `recovery.py/network_guard.py/screen_health.py/post_combat.py`와 서버 점검·길드·시작 화면 가드를 보존한다. ADB 소켓 종료 개선은 현재 오류 분류와 정지 검사를 유지하며 적용한다.
- [x] 검증: `& $mergePython -B -X utf8 -m unittest tools.test_upstream_321_merge.RuntimeIntegrationTests tools.test_runtime_guards tools.test_adb_failure tools.test_combat_strategy tools.test_post_combat tools.test_guild_startup_recovery tools.test_server_maintenance -v` → 종료 0.
- [x] 검증: `& $mergePython -B -X utf8 tools/test_smart_disarm_fixes.py` → 종료 0, `전체 PASS`. 인식 변경의 실제 게임 검증 여부는 별도로 기록한다.

### Task 4: 낚시·채굴·요정 작업과 일반 작업 인계

**Files:** Modify `src/main.py`, `src/script.py`, `mod/telegram_remote_control/runtime_bridge.py`, `worker.py`, 필요한 `feature.py`; Create/Test `tools/test_quest_handoff.py`; Test `mod/telegram_remote_control/tests/test_runtime_worker.py`.
**Interfaces:** Task 1의 `load_farm_setting_for_target`을 사용한다. 기존 `request_task_handoff(runtime, event_queue, *, target, event_name) -> bool`, `RemoteRuntime.is_handoff_requested(target=None)`와 `register_adapter(..., handoff_target=None)`를 재사용한다. 이벤트는 `("switch_quest", {"run_id": str, "worker_generation": int, "target": str})`, 컨트롤러 진입점은 `AppController._handle_handoff(value: dict) -> None`으로 통일한다. 이전 `turn_to_7000G`도 생산부에서 동일 payload로 바꾼다. 컨트롤러가 새 워커 시작 전에 `runtime.worker_generation`을 증가시킨다. `worker.py::make_worker_completion_callback(runtime, latch, worker_generation: int) -> Callable[[], bool]`은 현재 세대의 최종 종료만 latch에 전달하며, `run_farm_worker`의 종료 처리와 `_FINISHINGCALLBACK`이 이 콜백을 사용한다.

- [x] `test_stop_wins_over_handoff_and_stale_events`를 추가한다. 작업 인계 요청 직후 로컬/원격 정지, 중복 이벤트, 다른 `run_id`, 같은 `run_id`의 이전 세대 이벤트, 이전 작업이 살아 있는 경우를 각각 검사한다. 유효한 인계 1건은 `start_task.call_count == 1`이고, 중복·오래된·정지 이후 이벤트는 호출 수를 늘리지 않아야 한다. 이전 워커가 살아 있는 동안에는 시작을 보류하며 오래된 완료 콜백은 latch도 소진하지 않아야 한다.
- [x] `test_handoff_chain_completes_once`를 추가한다. `7000G/fishing/FFXI-Org/shiphold-fairy`를 실제 카탈로그 ID와 대조해 순차 전환시키고, 이전 워커의 `SystemExit`는 인계로 처리하며 체인 마지막에만 완료 이벤트가 1개 나와야 한다. `_FINISHINGCALLBACK`도 이전 워커에서 UI 종료를 발생시키지 않아야 한다.
- [x] 목표 실패를 확인한 뒤 `7000G` 하드코딩을 제거하고 §4.2 설정·수명 계약으로 일반화한다. 대상 ID·리소스 검증 실패는 `ERROR` 종료로 보고한다. 인계 대기는 기존 `WORKER_EXIT_TIMEOUT_SECONDS=15`를 적용하고 초과하면 새 워커를 시작하지 않는다.
- [x] 낚시·미끼 보충·0자원 대체 작업·요정 결과 전환을 연결한다. 우선순위는 업스트림대로 채굴 → 7000G → 낚시이며, 모든 비활성·미끼 없음·잘못된 목표 ID·전환 요청 실패를 가짜 화면으로 검증한다. 문자열 대소문자는 `quest.json`의 실제 ID를 기준으로 한다.
- [x] `test_stop_after_current_round_is_run_scoped`로 예약 전에는 `self.assertFalse(runtime.worker_force_stop_event.is_set())`, 회차 종료 뒤에는 `self.assertTrue(runtime.worker_force_stop_event.is_set())`와 `start_task.assert_not_called()`를 확인한다. 예약 취소 뒤 회차 완료는 계속 실행하고 새 실행의 `stop_after_run_event`는 해제돼야 한다. 전역 `StopAfterRunEvent/GlobalStopEvent`를 추가하지 않고 회차 종료 지점과 인계 경계에 같은 판정을 연결한다.
- [x] 검증: `& $mergePython -B -X utf8 -m unittest tools.test_quest_handoff mod.telegram_remote_control.tests.test_runtime_worker mod.telegram_remote_control.tests.test_feature -v` → 종료 0. 작업·인계 중 추가 `Farm` 스레드가 남지 않아야 한다.

정지 우선 테스트는 `patch.object(controller, '_start_task', new=start_task)`로 작업 시작만 모의 처리하고 실제 `_handle_handoff`를 호출한다. 정상 체인 테스트는 가짜 Farm과 실제 컨트롤러 이벤트 처리를 사용하며 큐의 이벤트를 `events`에 수집한다. 서로 다른 두 시나리오의 핵심 단언이다.

```python
# 정지 직후 인계: 새 워커를 만들지 않는다.
start_task.assert_not_called()
# 정상 인계 체인이 끝난 뒤: 최종 완료를 한 번만 알린다.
self.assertEqual(sum(name == "task_finished" for name, _ in events), 1)
```

### Task 5: 컨트롤러 이벤트 처리와 종료

**Files:** Modify `src/main.py`, 필요한 `mod/telegram_remote_control/adapters.py`; Test `tools/test_main_controller.py`, `mod/telegram_remote_control/tests/test_feature.py`.
**Interfaces:** `AppController(headless: bool, config_path: str | None)`의 작업 관리 포트를 유지하고 Tk 상속을 제거한다. `run() -> None`, `schedule_after(delay_ms: int, callback) -> None`, `request_shutdown() -> None`를 제공한다. 컨트롤러 소유 스레드 한 개에서 `_dispatch`, 예약 콜백, `remote_feature.tick()`을 처리하고 WebView는 메인 스레드에서 실행한다. `ControllerPorts.schedule_after`를 이 스케줄러에 연결한다.

- [x] `test_controller_serializes_start_stop_and_stale_completion`과 `test_close_cancels_workers_before_destroy`를 추가한다. 동시 시작은 워커 1개, 지연 완료는 현재 실행을 바꾸지 않음, 종료 시작 뒤 추가 시작·인계·재시작은 0회여야 한다.
- [x] 종료 테스트는 가짜 시계와 서비스로 `CONTROLLER_TICK_MILLISECONDS=100`, 서비스 36초·작업 15초·전체 45초 상한을 검증한다. 자기 프로세스 종료를 `force_exit = Mock()`으로 교체해 정상 종료는 `force_exit.assert_not_called()`, 한도 초과는 `force_exit.assert_called_once_with(1)`을 단언한다. 테스트에서 실제 종료 함수를 실행하지 않는다.
- [x] 실패를 확인한 뒤 기존 `_dispatch`·완료 latch·원격 상태 기계를 새 큐 루프에 연결한다. `self.after` 호출은 `schedule_after`로 이전하고 종료 중 예약 콜백은 폐기한다. 종료 정리는 이벤트 루프를 막지 않도록 진행한다.
- [x] `-headless -config`는 WebView 창 없이 같은 설정·작업 제어를 사용한다. GUI import만으로 창·네트워크·ADB가 시작되지 않도록 분리하고 테스트의 `main/gui` import 경로를 유지한다.
- [x] 검증: `& $mergePython -B -X utf8 -m unittest tools.test_main_controller tools.test_custom_config mod.telegram_remote_control.tests.test_feature -v` → 종료 0. 실제 WebView 연결은 Task 6에서 확인한다.

### Task 6: 새 UI·한국어·Telegram·로그 연결

**Files:** Modify `src/gui.py`, `src/utils.py`, `locale/*/LC_MESSAGES/messages.po`, Telegram 설정 UI·로케일; Create `src/ui.html`, `tools/test_web_ui.py`; Test `tools/test_connection_test_ui.py`.
**Interfaces:** `ConfigPanelApp(master_controller, version, msg_queue)`는 Task 5 컨트롤러를 받는다. `WebBridge.bootstrap() -> dict`, `poll() -> list[dict]`, `start_quest()/stop_quest()/close_window() -> dict`, `set_stop_after(enabled: bool) -> dict`, `save_telegram(patch: dict) -> dict`, `cancel_update() -> dict`를 제공한다. bridge의 상태 변경은 컨트롤러 큐에서 처리한다. bootstrap에는 별도 `uiLanguages`, `gameLanguages`, gettext로 채운 `i18n` 표시 사전과 비밀값을 제외한 `values`를 제공하고 HTML이 이를 사용한다. Tk 위젯 직접 접근은 `ConfigPanelApp.apply_remote_control_state(state)`, `show_connection_test_result(result)`, `push_event(event: dict)`로 대체한다. Python `logging`의 `extra`에 `summary`, `summary_data`, `summary_events`를 담아 `{"type": "summary", "data": summary_data, "events": summary_events}` 이벤트로 전달한다.

- [x] `test_bridge_uses_controller_and_masks_secrets`를 추가한다. 시작 거부 시 `self.assertFalse(bridge.bootstrap()['running'])`, 임시 토큰에 대해 `self.assertNotIn('fixture-secret', json.dumps(bridge.bootstrap()))`을 단언한다. 상태·로그에도 토큰을 포함하지 않고, 제목·로그 문자열은 HTML 실행이 아닌 텍스트로 표시해야 한다.
- [x] `test_korean_ui_and_strategy_round_trip`를 추가한다. ko/en/zh 전환 후 작업 ID·전략·스마트 개봉 값은 동일하고, 새 Python 번역 키·HTML 라벨·작업명·카테고리·도움말은 해당 언어로 표시돼야 한다. UI 언어와 이미지 언어 목록을 별도로 검사한다.
- [x] 실패를 확인한 뒤 업스트림 HTML을 연결하고 Telegram 저장·연결 테스트·원격 상태·스마트 개봉·업데이트 취소를 구현한다. 설정 토큰 입력은 미입력 시 기존 값 유지, 명시적 지우기만 삭제로 처리한다. 로그 sink는 표준 `logging.Handler`로 구현하고 종료 시 제거한다.
- [x] `test_auto_handoff_display_does_not_overwrite_saved_selection`으로 자동 전환 후 다른 옵션 저장·창 닫기에도 `self.assertEqual(reloaded['GENERAL']['FARM_TARGET'], original_target)`을 확인한다. 이번 회차 후 정지 버튼·취소·새 실행 초기화는 Task 4의 실행별 상태에 연결한다.
- [x] 연결 테스트의 성공·실패·20초 시간 초과 후 현재 요청 ID와 버튼을 복원하고 오래된 응답은 무시한다. 로컬 정지와 원격 귀환 상태를 구분해 표시한다. 기존 Tk 설정 패널은 웹 기능 동등성 확인 후 제거하고 테스트는 새 포트로 옮긴다.
- [x] 기본·Telegram 카탈로그를 컴파일하고 `& $mergePython -B -X utf8 -m unittest tools.test_web_ui tools.test_connection_test_ui tools.test_main_controller -v` → 종료 0을 확인한다. `_TIPS` 및 동적 표시 문자열도 별도 목록으로 점검한다.
- [x] 개발용 임시 설정과 가짜 컨트롤러로 실제 WebView에서 시작 거부·정지·연결 테스트 결과·언어별 표시·닫기를 확인한다. 성공 기록 없이 import 또는 모의 테스트만으로 UI 완료를 선언하지 않는다.

### Task 7: 포크 업데이트와 취소 계약

**Files:** Modify `src/main.py`, `src/auto_updater.py`, `src/gui.py`, `src/ui.html`; Create/Test `tools/test_updater_channel.py`; Test `tools/test_updater_cancel.py`.
**Interfaces:** `AutoUpdater` 생성자의 owner/repo는 `momo31/wvd`로 지정한다. `_is_newer_version(new_version: str) -> bool`은 `N.N.N-momo.N`의 숫자 순서를 비교한다. `_is_allowed_update(update_data: dict) -> bool`을 추가해 포크 버전과 `https://github.com/momo31/wvd/releases/download/` 경로를 다운로드 전에 검증한다. 기존 `cancel_event`, `download_finished`, `restart_ready` 이벤트를 유지한다.

- [x] `test_fork_revision_comparison`에 `3.2.1-momo.2 > 3.2.1-momo.1`, 같은 버전·역행·잘못된 문자열 거부를 단언한다. 순수 upstream 버전은 자동 적용 후보로 인정하지 않는다.
- [x] `test_cancel_and_foreign_release_never_restart`에 취소 직후 지연된 `restart_ready`, 다른 owner/repo URL, 메타데이터 404·형식 오류를 넣고 다운로드·재시작 호출이 0회임을 단언한다. 포크 채널 부재는 수동 다운로드 안내 상태가 된다.
- [x] 실패를 확인한 뒤 포크 비교·출처 검증과 WebBridge 취소를 연결한다. 다운로드 완료 전 새 다운로드를 시작하지 않고, 성공·실패·취소 모두 `download_finished`로 버튼을 복원한다. 실제 재시작도 Task 5 종료 계약을 따른다.
- [x] 검증: `& $mergePython -B -X utf8 -m unittest tools.test_updater_channel tools.test_updater_cancel tools.test_web_ui -v` → 종료 0. 가짜 응답·파일만 사용하며 실제 설치 폴더를 교체하지 않는다.

포크 버전 테스트는 `AutoUpdater`를 `current_version='3.2.1-momo.1'`로 생성해 다음을 검증한다.

```python
self.assertTrue(updater._is_newer_version("3.2.1-momo.2"))
self.assertFalse(updater._is_newer_version("3.2.1-momo.1"))
self.assertFalse(updater._is_newer_version("3.2.1-momo.0"))
self.assertFalse(updater._is_newer_version("3.2.2"))
self.assertFalse(updater._is_newer_version("invalid"))
```

### Task 8: CI·패키징 계약과 최종 인계

**Files:** Modify `.github/workflows/build-executable.yml`, `requirements.txt`, `src/gui.py`, 로컬 `wvd.spec`, `CHANGES_LOG.md`, `README.md`, `docs/build-and-release.md`, 이 계획서; Test `tools/test_upstream_321_merge.py`의 `PackagingContractTests` 및 기존 버전 고정 테스트.
**Interfaces:** `src/ui.html`은 번들 루트의 `ui.html`로 포함한다. `src/gui.py::ResolveUiPath() -> str`은 개발 시 `gui.py`와 같은 디렉터리의 HTML, `sys._MEIPASS`가 있는 번들에서는 `ResourcePath('ui.html')`을 반환한다. 기존 `ResourcePath`의 리소스 루트 계약은 유지한다. 리소스·기본 로케일·Telegram 로케일과 webview 수집 옵션을 CI와 로컬 spec에 동일하게 적용한다. `wvd.spec`은 현재 Git 미추적/ignore 대상이므로 변경 사실과 재현 방법을 문서에 남긴다.

- [x] `test_packaging_contract_includes_webview_and_locales`로 HTML 경로·세 로케일·Telegram 카탈로그·webview 수집 옵션·`build.needs=validate`를 검증한다. 원본 HTML 바이트를 `expected_html`로 읽고 소스/모의 frozen 경로에서 `self.assertEqual(Path(gui.ResolveUiPath()).read_bytes(), expected_html)`을 확인한다. 새 exe를 실행하는 검사는 아니다.
- [x] 버전 제안과 로컬 변경 기록을 반영하고 기존 버전 문자열·Tk 구조 고정 테스트를 의미 있는 행동 검사로 이전한다. 없애는 테스트는 대체 검증 위치를 기록한다. 핵심·원격·스마트 개봉 검증을 개발 CI에 유지하고 카탈로그 컴파일을 테스트 전에 수행한다.
- [x] 원본 기준 최근 수정 7건 각각의 구현과 테스트를 아래 대응표로 대조한다. 업스트림 변경 파일 전체에 대해 반영·로컬 유지·제외 이유를 기록해 누락을 찾는다. QQ 알림 제외와 모의 환경 한계도 기록한다.
- [x] 아래 전체 검증 명령을 순서대로 실행한다. 변경 후에는 최종 작업 트리에서 재검증하고 종료 코드·테스트 수·결과를 기록한다. 실패·skip 증가·예상 밖 테스트 수 감소는 원인을 해결하거나 미완료로 명시한다.
- [x] 원본 해시·HEAD·개인 설정 불변, 통합 작업본의 충돌 표식 부재, `MERGE_HEAD` 부재와 미커밋 diff를 확인한다. 문서·추가 파일을 포함한 최종 인계 목록을 제공하며 커밋·push·PR·빌드·배포는 하지 않는다.

```powershell
& $mergePython -B -X utf8 -m babel.messages.frontend compile -d locale -D messages
if ($LASTEXITCODE -ne 0) { throw '기본 번역 컴파일 실패' }
& $mergePython -B -X utf8 -m babel.messages.frontend compile -d mod/telegram_remote_control/locale -D telegram_remote_control
if ($LASTEXITCODE -ne 0) { throw 'Telegram 번역 컴파일 실패' }
& $mergePython -B -X utf8 -m unittest discover -s tools -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'tools 회귀 실패' }
& $mergePython -B -X utf8 -m unittest discover -s mod/telegram_remote_control/tests -p 'test_*.py' -v
if ($LASTEXITCODE -ne 0) { throw 'Telegram 회귀 실패' }
& $mergePython -B -X utf8 tools/test_smart_disarm_fixes.py
if ($LASTEXITCODE -ne 0) { throw '스마트 개봉 회귀 실패' }
git diff --check
if ($LASTEXITCODE -ne 0) { throw 'diff 공백 검사 실패' }
```

`git diff --check`는 미추적 파일을 검사하지 않으므로 새 텍스트 파일은 별도로 `git -c core.autocrlf=false diff --no-index --check -- NUL <파일>`로 검사한다. 이 명령은 새 파일 차이 때문에 종료 코드 1을 반환할 수 있다. **종료 코드가 0 또는 1이며 진단 출력이 비어 있을 때** 통과로 판정하고, 공백 오류나 다른 Git 오류는 해결한다. 검증 결과에는 이번에 실행한 것과 이전 기록, 모의 검사와 실제 UI 확인을 구분한다.

### 최근 수정 7건 보존 대응표

| 기존 수정 | 소유 작업 | 유지·이전할 검증 |
|---|---|---|
| 상자 우선·반복 탭 제한 | 2·3 | `tools/test_runtime_guards.py`, `mod/telegram_remote_control/tests/test_return_to_town.py` |
| Telegram 재연결 명령 보존 | 4·5 | `mod/telegram_remote_control/tests/test_command_service.py` |
| ADB 복구 실패 오류 분류 | 3·5 | `tools/test_adb_failure.py`, `mod/telegram_remote_control/tests/test_feature.py` |
| 지정 설정 경로 일관성 | 1·6 | `tools/test_custom_config.py`, `tools/test_config_persistence.py` |
| 다운로드 취소 | 7 | `tools/test_updater_cancel.py` |
| 연결 테스트 UI 복원 | 6 | `tools/test_connection_test_ui.py` |
| 개발 CI 분리 | 8 | `PackagingContractTests`, 실제 원격 CI는 미실행으로 구분 |

## 6. 실패 시 중단·복구와 완료 기준

- Task 0의 파일 비교 또는 기준 테스트가 실패하면 기능 이식을 시작하지 않는다. 원본은 보존하고 통합 작업본·기록으로 원인을 확인한다.
- 각 작업 시작 전 해당 작업이 수정할 파일의 내용·해시와 미커밋 diff를 `build/merge-321-checkpoints/task-N/`에 보관한다. 새 파일도 목록으로 기록한다. 실패하면 그 작업본에서 소유 파일만 이전 체크포인트로 복원하고 이미 통과한 전제 작업을 재검증한다.
- 코드와 설정 마이그레이션은 임시 설정으로 검증한다. 실제 사용자 설정을 이전하는 시험을 수행하지 않는다. 자동 업데이트나 배포본을 이용해 개발 단계의 복구를 시도하지 않는다.
- 정리 시 파일 이동·삭제 대상의 절대 경로가 통합 작업본 또는 명시적 체크포인트 안인지 확인한다. 실패한 작업본은 즉시 지우지 않고 원인·복구 자료를 남긴다. 원본에서 `git reset --hard`, `git clean`, 강제 checkout을 실행하지 않는다.
- 완료 조건은 기능별 신규 테스트와 기존 행동 검증 통과, 별도 실제 개발 UI 확인, 한국어 누락·미해결 자산 참조 없음, 최근 수정 7건 보존, 원본 불변이다. 실제 게임·Telegram·원격 CI·배포가 미검증이면 그 한계를 그대로 인계한다.
- 빌드·배포를 나중에 요청받으면 [빌드 및 배포 절차](build-and-release.md)를 다시 읽는다. 개발 검증 결과를 빌드 단계로 옮기지 않고, 스테이징 빌드와 사용자 데이터 보존 배포 규칙을 따른다.

## 7. 최초 조사에서 수행한 검증

| 검증 | 결과 |
|---|---|
| 현재 tools unittest | 214개 통과 |
| 현재 Telegram unittest | 54개 통과 |
| 현재 unittest 합계 | 268개 통과 |
| 스마트 개봉 독립 시나리오 | 전체 PASS |
| `git diff --check` | 통과 |
| HEAD 병합 시뮬레이션 | 16개 경로 충돌 확인 |
| 미커밋 수정 포함 주요 텍스트 파일 비교 | 12개 파일의 3방향 검사 수행 |

최초 테스트는 `build/wvd_py314_venv/Scripts/python.exe`와 저장소 루트·`src`를 포함한 `PYTHONPATH`로 실행했다. 위 통과 결과는 **최초 조사 당시 작업본의 통합 전 기준**이다. 이번 문서 보완에서 테스트 스위트를 다시 실행하지 않았으며 3.2.1 통합 성공의 근거로 사용하지 않는다. 기존 `FarmConfig`의 `non-string key in the __dict__` RuntimeWarning은 남아 있다.

## 8. Superpowers 검토 기록과 산출물

적용한 기준은 [writing-plans](C:/Users/admin/.codex/skills/writing-plans/SKILL.md)의 파일·인터페이스·작업별 검증·자체 검토, [brainstorming](C:/Users/admin/.codex/skills/brainstorming/SKILL.md)의 기존 맥락 확인과 독립 builder check, [verification-before-completion](C:/Users/admin/.codex/skills/verification-before-completion/SKILL.md)의 증거 기반 완료 판정이다. 사용자가 지정한 기존 문서 위치와 저장소의 커밋 금지 규칙을 스킬 기본값보다 우선한다.

독립 검토에서 나온 네 질문은 §4.1의 Git 인계 상태, §4.2와 Task 4의 대상 설정·저장 정책, Task 5의 앱 종료 계약, Task 7의 포크 채널·버전 비교로 보완했다. 요구 사항→작업 대응, 인터페이스 명칭, Review Focus 5건의 검증 위치를 자체 검토했고, 같은 실행의 이전 워커 이벤트·예약 정지·자동 전환 선택값 보존·HTML 경로도 보완했다. 실행 방식은 아직 선택되지 않았으며 실제 구현 요청 시 사용자 지시를 따른다.

이번 문서 검증에서는 Task 0~8과 미완료 체크박스, 로컬 링크·앵커 15개, Python 예시 3개와 PowerShell 명령 블록 2개의 구문, 공백 오류 부재를 확인했다. 명령 예시는 구문만 검사했다. 이 계획서를 제외한 기존 추적·미추적 파일 529개의 SHA-256과 HEAD가 검토 시작 시점과 같고 `MERGE_HEAD`가 없음을 확인했다.

조사 산출물은 Git에서 제외되는 `build/upstream-321-review`에 있다. 이 문서를 다른 환경으로 옮길 때 아래 로컬 산출물이 함께 제공되는 것은 아니다.

- [HEAD 병합 시뮬레이션](../build/upstream-321-review/head-merge-tree.txt)
- [미커밋 수정 포함 파일별 충돌 집계](../build/upstream-321-review/working-tree-conflicts.json)
- [업스트림 파일 변경 목록](../build/upstream-321-review/upstream-name-status.txt)
- [tools 테스트 로그](../build/upstream-321-review/tools-tests.log)
- [Telegram 테스트 로그](../build/upstream-321-review/remote-tests.log)
- [스마트 개봉 테스트 로그](../build/upstream-321-review/smart-disarm.log)

최초 조사 당시에는 새 UI 실제 실행, Python 3.14·WebView2 조합, 실게임·ADB·Telegram 실통신, 업데이트 적용, 원격 CI를 검증하지 않았으며 소스 통합도 착수 전이었다. 통합 후 실제 개발 UI 및 모의 검증은 아래에 별도로 기록한다. 실행 파일 빌드·배포와 실게임·실통신은 수행하지 않았다.

후속 작업에서는 먼저 현재 HEAD·미커밋 변경·대상 커밋을 다시 확인한다. 이 계획의 기준과 달라졌으면 차이를 반영한 뒤 진행한다. Git 커밋·push·PR 생성·갱신은 저장소 지침에 따라 사용자가 수행한다.

## 9. 실행 결과 (2026-11-01)

- 통합 작업본: `recovered-source/build/merge-321-worktree`, 버전 `3.2.1-momo.1`. 원본 보존과 기능별 이식 방식으로 수행했다. 커밋·push·PR·배포는 하지 않았다.
- 기본·Telegram 카탈로그 컴파일 후 tools 281개, Telegram 55개가 통과했고 스마트 개봉 독립 시나리오는 전체 PASS다. `.superpowers/sdd/upstream-3.2.1-merge-plan/final-*.log`에 명령·종료 코드를 남겼다.
- 실제 숨김 WebView2에서 시작 거부·정지·연결 테스트 결과·ko/en/zh 전환·닫기를 확인했다. 모든 표시 패널을 순회했을 때 한국어 화면의 중국어 잔여와 JavaScript 오류는 0건이었다. 실제 컨트롤러 루프와 로그 수명 주기를 사용하고 장치·서비스 동작은 가짜 구현으로 격리했다.
- 원본 530개 파일 해시와 두 HEAD가 일치하고 `MERGE_HEAD` 및 충돌 표식이 없다. 추적 diff와 새 텍스트 파일의 공백 검사가 통과했다.
- 743개 업스트림 변경 파일과 작업별 누락 자산을 [CSV](upstream-3.2.1-file-inventory.csv) 및 [JSON](upstream-3.2.1-resource-availability.json)에 기록했다. 영어 61/62 작업이 자산 검증을 통과한다. 중국어 게임은 로컬 안전 인식 자산 8종이 없어 시작을 차단하며 영어 FloralHoney도 차단한다.
- 새 UI·기본/Telegram 번역·캐릭터·도움말·변경 기록을 보완했다. 옛 Tk 구조 고정 테스트는 새 Web 모델과 실제 표시 결과 검증으로 이전했다.
- 독립 검토의 Important 5건(일반 GUI 로그, 실제 진입점의 언어 전환, UI 큐 포화, 실제 원격 작업 종료 대기, CI 배포 분류)을 모두 수정했다. 회귀 테스트 9개의 실패 후 통과를 확인했고 전체 검증도 다시 통과했다. CI의 기존 사전 출시/Pages 게시 정책은 유지한다. 상세 결과는 [병합 보고서](upstream-3.2.1-merge-report.md)의 최종 검증 절에 기록했다.
