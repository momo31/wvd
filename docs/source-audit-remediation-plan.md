# 소스 평가 결과와 수정 계획

## 후속 빌드·배포 완료 — 2026-10-25 01:05 KST

사용자의 후속 빌드·배포 요청으로 이 수정본을 Python 3.14.6 / PyInstaller 6.22.3에서 빌드했다. 스테이징은 recovered-source/build/release-stage-20261025-003730이며 빌드 종료 코드는 0이다. Git에 없는 wvd.spec은 기존 CI 명령의 옵션으로 생성하고 번역 카탈로그를 컴파일했다.

기존 C:/Users/admin/Documents/momo31-wvd/dist/wvd의 _internal, wvd.exe, CHANGES_LOG.md만 교체했다. 이전 실행 파일과 변경 기록은 없었고, 남아 있던 _internal은 스테이징의 previous-deploy에 보존했다. config.json/logs/audit 보호 대상의 파일 867개와 디렉터리 3개가 유지됐고 파일 경로·크기·SHA-256이 모두 일치한다. 배포 폴더의 config.json은 작업 전부터 없었으며 새로 만들지 않았다.

배포 버전은 2.7.1-momo.1이다. protected-before.json, protected-after.json, deployment-result.json을 스테이징에 남겼다. 아래의 개발 검증 이후 빌드 단계에서 테스트를 반복하거나 배포된 exe를 실행하지 않았다. 커밋·push·PR은 하지 않았다. 상세 기록은 [SESSION_HANDOFF.md](../SESSION_HANDOFF.md)를 따른다.

## 목적과 현재 상태

2026-10-24 대화에서 확인한 결함 7건의 계획과 완료 기록이다. 사용자의 “포니테일 원칙에 맞게 소스 수정하고 테스트” 요청으로 recovered-source 작업본에 수정과 회귀 테스트를 적용했다. tools 214개와 원격 제어 54개, 합계 268개 테스트가 통과했고 별도 스마트 개봉 시나리오도 전체 PASS다. 빌드·배포·Git 반영은 하지 않았다. 실제 변경과 검증 한계는 마지막 수정 완료 기록을 따른다.

평가는 커밋되지 않은 변경을 포함한 당시 작업 폴더를 대상으로 했다. 에뮬레이터 한 대를 장시간 실행하는 사용 환경을 가정했다. 핵심 실행·복구·설정·원격 제어·업데이트 경로를 검토했으며, 모든 퀘스트 분기를 전수 검증한 것은 아니다.

**수정 작업에는 새로 받은 recovered-source 폴더를 사용한다.** 문서 최초 저장 시점에는 원래 저장소의 src/main.py, src/script.py, src/gui.py, .git/HEAD와 기존 SESSION_HANDOFF.md를 읽을 수 없었고, git status도 저장소를 인식하지 못했다. 아래 파일명·함수명·줄 번호와 테스트 결과는 앞선 평가 시점의 기록이다. 내려받은 원격 버전에는 당시의 미커밋 변경이 없으므로 현재 코드에서 다시 확인한 뒤 적용해야 한다.

## Git에서 확보한 작업본 — 2026-10-24

- 작업 경로: C:/Users/admin/Documents/momo31-wvd/recovered-source
- 원격: https://github.com/momo31/wvd.git
- 브랜치·커밋: master / 4e907ba8ec40d869cf90dcd8d992afcd1c328ba3 (2026-09-14)
- 원격의 마지막 master 기록과 일치하는 커밋을 새 폴더에 clone했다. 원래 작업 폴더는 덮어쓰지 않았다.
- 핵심 소스, 원격 제어 모듈, 회귀 테스트 파일은 확인됐다. 후속 소스 확인 요청으로 아래 최소 재현과 기존 테스트를 실행했다. 구현 수정은 하지 않았다.
- 이 문서와 새 작업본의 SESSION_HANDOFF.md를 연결했다. 이전 미커밋 변경·개인 데이터는 복구되지 않았다. 개발 환경은 아래와 같이 새로 준비했으며 빌드·배포는 실행하지 않았다.

## 수정 전 복구 소스 확인 결과 — 2026-10-24

확인 기준은 master의 4e907ba8ec40d869cf90dcd8d992afcd1c328ba3이다. 프로그램 소스·기존 테스트·워크플로·requirements.txt는 변경하지 않았다. 아래 결과는 새 작업본에서 직접 확인한 것이며 이전 평가의 통과 기록과 구분한다.

### 개발 환경과 기존 테스트

- Python 3.14.6의 기존 설치 패키지를 공유하는 build/wvd_py314_venv 가상환경을 새로 만들었다. 처음에는 requirements.txt에 선언된 certifi가 없어 일부 테스트 모듈이 로드되지 않았다. 가상환경에 certifi 2026.10.23을 설치한 뒤 두 unittest 묶음을 다시 실행했다. 이는 개발 환경 보완이며 프로그램 의존성 정의 변경은 아니다.
- tools unittest: 187개 통과, 실패·오류·건너뜀 없음.
- mod/telegram_remote_control/tests unittest: 42개 통과, 실패·오류·건너뜀 없음.
- tools/test_smart_disarm_fixes.py: 별도 실행에서 전체 PASS, 종료 코드 0. 이 실행은 certifi를 설치하기 전 시스템 Python 3.14.6으로 완료했으며 해당 시나리오는 certifi를 사용하지 않는다.
- src/script.py:139에서 기존 FarmConfig의 non-string key RuntimeWarning이 출력됐다. 이번 확인으로 수정하거나 새로 만든 경고는 아니다.

### 계획 항목의 현재 동작

| 번호 | 현재 작업본에서 확인한 결과 | 검증 방식 |
| --- | --- | --- |
| 1 | 매칭 점수 0.83을 모사했을 때 공통 상자 가드는 NONE이지만 원격 복귀는 동일 위치를 6회 탭했다. | 가짜 화면·매칭·입력으로 실제 판정 및 복귀 함수를 호출 |
| 2 | 최초 ID 100 정리 → 일시 오류 → 대기 중인 /stop ID 101을 제공했을 때 offset은 [-1, 101, -1, 102], 전달 명령은 0개였다. | 가짜 API와 대기로 실제 수신 루프 호출; /stop 파싱 성공도 별도 확인 |
| 3 | 사용자 중지 이벤트가 없는 초기 ResetDevice 실패도 local_stop으로 종료됐다. 완료 콜백은 1회였다. | 실제 Farm 함수의 AST를 추출하고 장치·대기만 모사 |
| 4 | custom.json 지정 시 원격·헤드리스 목표는 custom-task, GUI 목표는 default-task였다. | 가짜 설정 읽기로 실제 로딩 함수 호출 |
| 5 | 다운로드 창 취소 핸들러가 quit을 1회 호출했다. | 가짜 창으로 실제 취소 핸들러 호출 |
| 6 | 연결 테스트의 성공·실패·시간 초과 결과 후 버튼이 모두 disabled로 남고 활성 요청 ID도 유지됐다. | 실제 테스트 시작 함수와 결과 UI 처리 함수, 가짜 위젯·메시지창 사용 |
| 7 | 유일한 GitHub Actions 워크플로는 원격 테스트만 실행하며 tools 테스트와 스마트 개봉 시나리오가 빠져 있다. | 워크플로 소스 확인; 원격 CI는 미실행 |

최소 재현 결과는 build/recovered-source-check.json에 저장했다. 위 재현은 결함이 아직 남아 있음을 확인한 것이며 수정 후 합격 테스트가 아니다. 기존 테스트 229개와 스마트 개봉 시나리오 통과만으로 이 7건이 해결됐다고 판단하지 않는다. 구현 시 이 재현들을 지속적인 회귀 테스트로 추가한다.

위 내용은 구현 전 기준 기록이다. 실제 게임·ADB 장치·Telegram 통신·Tk 창 실행·업데이트 적용·빌드·배포는 수행하지 않았다. 이후 구현과 최종 테스트 결과는 아래 수정 완료 기록에 있다.

## 작업 재개 점검 — 2026-10-24 18:05 KST

현재 작업 경로를 확인했지만 src/main.py, src/script.py, src/gui.py, .git/HEAD, .git/config는 찾을 수 없었고 git status도 저장소를 인식하지 못했다. src, tools, mod, .github의 Python 소스·YAML 워크플로 검색 결과는 0개였으며 .git/objects와 .git/refs에서도 파일이 검색되지 않았다. 일부 reflog와 빌드 산출물이 있다는 사실만으로 현재 소스나 미커밋 변경을 복구할 수 있다고 판단하지 않았다.

인접한 C:/Users/admin/Documents/wvd-master, 현재 폴더의 .codex-worktrees와 소스·패치·백업 파일 후보도 확인했지만 대상 소스를 찾지 못했다. 지정된 개발 Python 실행 파일도 확인되지 않아 이번 세션에서는 재현 및 회귀 테스트를 실행하지 않았다. 이전 평가의 통과 기록을 이번 검증 결과로 재사용하지 않는다.

사용자에게 미커밋 변경이 포함된 원본 프로젝트 경로 또는 현재 경로에서 파일이 보이는지 확인을 요청했다. 소스·Git·배포본은 변경하지 않았고, 이번 변경은 두 인계 문서의 점검 기록뿐이다. 원본 경로가 확인되거나 파일 접근이 복구되면 아래 시작 순서를 다시 수행한다. 접근 문제의 원인은 아직 확인하지 못했다.

후속 진단에서는 사용자 승인을 받아 샌드박스 밖 admin 계정에서도 같은 파일 부재를 확인했다. Defender에는 2026-10-20 01:13경 빌드 중인 wvd.exe 한 개를 격리한 기록이 있었으나, 2026-10-24의 탐지·조치 이벤트나 누락된 소스·Git 파일의 격리 기록은 확인되지 않았다. 이 기록만으로 이번 소스 손실을 백신 탓으로 판단하지 않는다. 상세 진단과 조회 한계는 SESSION_HANDOFF.md의 후속 원인 점검에 기록했다.

이전 Astra 세션의 원본 로그를 대조한 결과 2026-10-24 17:26:58 KST에는 실제 소스 읽기와 git diff가 성공했으며, 17:37:34~56에는 기존 인계 문서·Git·소스 조회가 실패했다. 이 계획서의 최초 저장은 그 이후인 17:42경이다. 따라서 평가 후 문서 저장 전인 약 11분 구간으로 파일 부재 발생 시점을 좁혔다. 관련 디렉터리의 변경 시각은 17:33경이나 손실 원인·실행 주체는 아직 미확인이다. 상세 시간표와 NTFS 변경 기록 조회의 권한 한계는 SESSION_HANDOFF.md에 기록했다.

## 다음 세션 시작 순서

1. C:/Users/admin/Documents/momo31-wvd/recovered-source로 이동하고, 그곳의 [SESSION_HANDOFF.md](../SESSION_HANDOFF.md)와 이 계획서를 완전히 읽는다.
2. 현재 작업 경로, 소스 파일, .git/HEAD, git status --short를 확인한다. 소스가 계속 보이지 않으면 구현에 착수하지 말고 올바른 작업 폴더나 환경 복구가 필요한 지점을 보고한다. 이 문서로 소스 전체를 재작성하거나 git reset, clean, 강제 checkout을 실행하지 않는다.
3. 현재 AGENTS.md와 관련 하위 지침을 읽는다. 이전 인계 문서가 다시 확인되면 그 내용을 보존하고, 이 계획과 합쳐 완료 상태를 재검증한다.
4. 기존 변경을 확인한다. 평가 당시 src/main.py, src/script.py, src/gui.py, src/utils.py, src/auto_updater.py, 로케일, 퀘스트·이미지, 테스트 및 문서에 미커밋 변경이 있었다. 이를 이번 수정의 결과로 간주하거나 덮어쓰지 않는다.
5. 1번과 2번의 현재 동작을 각각 최소 재현 테스트로 확인한다. 이미 수정된 항목은 중복 수정하지 않고 확인 결과를 기록한다.
6. 항목별 수정과 관련 테스트를 완료할 때마다 이 문서의 상태표와 인계 문서를 갱신한다.

## 작업 제약

- Git 커밋, 원격 push, PR 생성·갱신은 수행하지 않는다. 변경과 검증 결과만 보고한다.
- 실행 파일 빌드나 배포는 이번 수정 계획에 포함하지 않는다. 별도 요청을 받으면 먼저 docs/build-and-release.md를 읽는다.
- 빌드는 별도 build/release-stage-*에서 끝내며, 명시적 배포 요청 없이 dist/wvd와 실행 중인 배포본을 변경하지 않는다.
- 빌드 단계에서 테스트 스위트, exe 실행, 스모크 테스트, Tcl/Tk·리소스·해시 검증을 수행하지 않는다. 아래 테스트는 개발 검증 단계의 작업이다.
- 배포가 별도로 요청되면 _internal, wvd.exe, CHANGES_LOG.md만 교체하며, 유일한 검증은 배포 전후 config.json, logs, audit 보존 확인이다.
- 실제 Telegram 메시지 전송, 게임 조작, 에뮬레이터 재시작 없이 가짜 API·화면·장치로 회귀 테스트를 수행한다. 개인 설정이나 토큰을 테스트 데이터·문서·로그에 복사하지 않는다.
- 새 표시 문자열은 기존 gettext와 지원 언어 처리를 따른다. 중국어 원문 폴백, .po 누락, .mo 불일치를 개발 단계에서 확인한다.
- 대규모 구조 변경이나 새 의존성 도입은 우선하지 않는다. 기존 공통 함수와 모듈 경계를 활용해 확인된 결함을 고친다.

## 우선순위와 상태

| 번호 | 우선순위 | 작업 | 상태 |
| --- | --- | --- | --- |
| 1 | 높음 | 원격 정지의 결과창 판정과 반복 탭 제한 | 구현·개발 검증 완료 |
| 2 | 높음 | Telegram 재연결 중 정지 명령 누락 방지 | 구현·개발 검증 완료 |
| 3 | 중간 | ADB 복구 실패를 오류로 보고 | 구현·개발 검증 완료 |
| 4 | 중간 | 지정 설정 경로를 모든 실행·저장 경로에 적용 | 구현·개발 검증 완료 |
| 5 | 중간 | 다운로드 취소와 앱 종료 분리 | 구현·개발 검증 완료 |
| 6 | 낮음 | 연결 테스트 완료 후 UI 상태 복원 | 구현·개발 검증 완료 |
| 7 | 개발 검증 | 핵심 회귀 테스트를 별도 CI 검증에 포함 | 구성 수정·로컬 명령 검증 완료; 원격 CI 미실행 |

권장 순서는 1 → 2 → 3 → 4 → 5 → 6 → 7이다. 각 결함의 회귀 테스트는 해당 수정과 함께 작성하며, 7번까지 미루지 않는다.

## 1 원격 정지의 결과창 오탐과 반복 탭

**확인한 문제:** 일반 상자 판정은 dialogueNext에 0.95 임계값과 3회 제한을 적용하지만, 원격 마을 복귀는 0.80을 사용하고 동일 화면에 대한 별도 시도 제한이 없다. 전체 정지 제한 시간 600초가 있어도 그 안에서 같은 좌표를 계속 누를 수 있다. 점수 0.83을 반환하는 모의 화면을 6회 제공했을 때 일반 판정은 NONE, 원격 복귀는 같은 위치에 6회 탭을 수행했다. 실제 이미지에서 0.83을 새로 측정한 결과는 아니다.

**확인 위치:** src/chest_guard.py의 decide_chest_guard_action, mod/telegram_remote_control/constants.py:66, return_to_town.py:100과 _classify. 관련 검사는 tools/test_runtime_guards.py와 mod/telegram_remote_control/tests/test_return_to_town.py에 있다.

**수정 계획**

- 기존 공통 상자 판정과 엄격한 임계값을 재사용해 원격 경로에 별도 규칙이 남지 않게 한다. 모듈 경계와 import 경로를 확인하고, 같은 판정 구현을 복사하지 않는다.
- chestFlag, whowillopenit, chestOpening 중 하나라도 검출되면 해당 프레임의 dialogueNext 탭을 차단한다.
- 매 탭 뒤 새 프레임으로 상자 상태와 화면 변화를 확인한다. 변화가 없으면 상태를 재판정하고, 동일 화면에 대한 시도는 최대 3회로 제한한다. 탭을 보냈다는 사실만으로 시도 횟수를 초기화하지 않는다.
- 결과창 전용 표식이 있는 경로는 함께 검증한다. 전용 표식 없이 진행 아이콘만 쓰는 경로는 상자 표식 부재·높은 임계값·제한된 재시도를 모두 지킨다.
- 연속된 정상 보상 페이지와 마을 복귀, 기존 전체 제한 시간·강제 종료 경로는 유지한다.

**완료 조건:** 상자 선택창 fixture에서 Open 처리가 우선되고 결과창 좌표는 한 번도 탭되지 않는다. 0.83의 단독 매칭은 탭하지 않는다. 고신뢰도 매칭이라도 화면이 그대로면 3회를 넘기지 않는다. 화면이 실제로 바뀌는 정상 보상 페이지는 진행된다. 합성 fixture와 실제 캡처를 구분해 검증 결과에 적는다.

## 2 Telegram 재연결 중 정지 명령 누락

**확인한 문제:** TelegramCommandService._poll_loop는 통신 재시도 때도 get_updates(-1, timeout=0)의 결과를 버리고 다음 ID로 넘어간다. 가짜 API에서 시작 시 ID 100 정리 → 일시 오류 → 대기 중인 /stop ID 101의 순서를 제공했더니 호출 offset은 [-1, 101, -1, 102], 전달된 정지 명령은 0개였다.

**확인 위치:** mod/telegram_remote_control/command_service.py:312의 _poll_loop, _apply_settings, _last_update_id와 세대 번호 처리. tests/test_config_and_commands.py는 명령 파싱도 다룬다. 수신 루프 동작 테스트는 필요하면 tests/test_command_service.py로 추가한다.

**수정 계획**

- 과거 메시지 정리를 서비스의 최초 활성화 또는 계정·설정 세대 변경에 한정한다.
- 같은 세대의 일시적 통신 오류·시간 초과·요청 제한에서는 마지막 처리 offset을 보존해 재시도한다.
- 명령을 큐에 전달하기 전에 offset을 앞당기지 않는다. 중복 update_id와 이전 세대에서 늦게 도착한 응답도 검증한다.
- 현재 허용 Chat ID 확인, 비허가 명령 무응답, 종료 시 동작을 유지한다.

**완료 조건:** 오류 중 도착한 /stop이 재연결 뒤 정확히 한 번 전달된다. 이미 처리한 명령은 반복 실행하지 않는다. 계정 변경 뒤 이전 계정의 응답은 실행되지 않는다. 최초 시작의 과거 명령 정리 정책은 유지된다. 테스트는 가짜 API와 가짜 대기를 사용한다.

## 3 ADB 복구 실패의 종료 사유

**확인한 문제:** Farm 시작 시 ResetDevice가 False이면 TaskStoppedException을 발생시키고, 예외 처리에서 LOCAL_STOP으로 기록한다. 사용자 중지 이벤트가 False인 실패 재현에서도 종료 사유가 local_stop이었고 완료 콜백은 1회 호출됐다. TelegramRemoteFeature는 이 사유를 일반 중지로 처리하므로 오류 알림을 보내지 않는다.

**확인 위치:** src/script.py의 ResetDevice, DeviceShell, ScreenShot, Farm:5581·5628, mod/telegram_remote_control/worker.py, feature.py의 _finalize_payload.

**수정 계획**

- ResetDevice 실패를 사용하는 모든 호출부를 검색한다. 장치 연결·복구 실패와 사용자의 중지 요청을 구분한다.
- 복구 실패에는 ERROR와 구체적인 failure_phase를 기록하고, 실제 사용자 중지 이벤트가 있을 때만 LOCAL_STOP을 사용한다.
- 이미 기록된 더 구체적인 오류를 덮어쓰지 않는다. 원격 정지 중 복구 억제와 폴백의 기존 종료 사유도 보존한다.
- 정상·오류·수동 중지 모두 완료 통지는 한 번만 발생하게 유지한다.

**완료 조건:** 초기 ADB 연결 실패와 실행 중 복구 실패가 ERROR로 종료되고 오류 알림을 큐에 넣는다. 수동 중지는 오류로 보고하지 않는다. 종료 콜백 중복과 실행 중 UI 고착이 없다. tools/test_main_controller.py, tools/test_recovery.py 및 원격 worker·feature 테스트를 함께 확인한다.

## 4 지정 설정 파일의 일관성

**확인한 문제:** -config custom.json을 지정한 경우 원격 시작은 custom.json을 읽지만 GUI의 LoadConfig는 기본 파일을 읽는다. 가짜 설정 두 개로 원격 목표 custom-task, GUI 목표 default-task를 재현했다. SetOneVarInGeneralConfig도 지정 경로를 받지 않아 런타임 카르마 변경을 기본 파일에 저장한다.

**확인 위치:** src/main.py의 AppController.__init__, _load_latest_setting, _select_quest_target, HeadlessActive; src/gui.py의 LoadConfig:739, save_config:858, toggle_start_stop; src/utils.py의 설정 함수와 SetOneVarInGeneralConfig:546; src/script.py의 런타임 저장 호출.

**수정 계획**

- 실행 시 선택한 설정 경로를 컨트롤러에서 GUI 읽기·저장과 로컬·원격·헤드리스 실행에 동일하게 전달한다.
- 실행 설정에 해당 경로를 보관해 카르마 등 런타임 변경도 같은 파일에 저장한다. 기본 파일 경로를 쓰는 모든 읽기·쓰기 호출부를 검색한다.
- CONFIG_FILE을 전역으로 바꾸는 것만으로 해결했다고 판단하지 않는다. 함수 기본 인자에 이미 저장된 경로와 import 시 언어 설정을 읽는 경로도 확인한다.
- 명시적 경로가 없을 때의 기존 기본 파일·이전 설정 마이그레이션·원자적 저장 동작을 유지한다. 잘못된 명시 파일을 다른 파일로 조용히 대체하거나 덮어쓰지 않는다.

**완료 조건:** 기본 파일과 별도 파일을 임시 폴더에 준비해 GUI 시작·원격 시작·헤드리스 시작의 목표가 일치하는지 확인한다. GUI 저장·원격 목표 변경·카르마 갱신은 지정 파일만 바꾸고 기본 파일은 그대로 유지한다. 기존 Telegram 설정과 작업별 설정도 보존된다. tools/test_config_persistence.py, tools/test_main_controller.py 및 원격 설정 테스트를 갱신한다.

## 5 다운로드 취소 처리

**확인한 문제:** Progressbar._on_cancel:40은 창을 닫으면서 self.quit()을 호출한다. Tk의 공유 이벤트 루프가 종료되어 앱 종료로 이어진다. canceled 값은 진행창에만 있고 다운로드 작업으로 취소 요청이 전달되지 않는다.

**확인 위치:** src/auto_updater.py의 Progressbar, AutoUpdater.download, _download_bar_and_retry; src/main.py의 다운로드 이벤트 처리와 main 이벤트 루프.

**수정 계획**

- 창 닫기로 앱 전체 quit을 호출하지 않는다. 다운로드 작업에 공유 취소 이벤트를 전달하고 창 수명과 작업 수명을 구분한다.
- 다운로드 시작·청크 읽기·재시도·검증·압축 해제·재시작 준비 전에 취소 상태를 확인한다. 네트워크 대기에 유한한 timeout을 적용한다.
- 취소를 일반 오류와 구분하고 restart_ready를 전송하지 않는다. 진행창이 사라진 뒤의 큐 이벤트도 안전하게 처리한다.
- 이전 다운로드가 살아 있는 동안 취소 이벤트를 초기화하거나 같은 임시 파일에 새 다운로드를 겹쳐 시작하지 않는다.

**완료 조건:** 가짜 응답 스트림을 다운로드하다 취소하면 앱 이벤트 루프 종료 호출 없이 작업이 끝난다. 이후 압축 해제·재시작 준비가 실행되지 않는다. 오류·취소 후 정상 재시작 다운로드가 가능하며, 일반 다운로드 성공 경로도 유지된다. 실제 HTTP와 재시작 배치 실행 없이 도구 테스트를 추가한다.

## 6 연결 테스트 완료 후 UI 복원

**확인한 문제:** settings_ui.py는 테스트 시작 시 버튼을 비활성화한다. AppController._show_connection_test_result는 메시지창만 표시한다. 성공 결과를 처리한 뒤에도 버튼이 disabled인 것을 재현했다. 다른 상태 변경이 생기기 전까지 바로 재시도할 수 없다.

**확인 위치:** mod/telegram_remote_control/settings_ui.py:77, feature.py의 _handle_test_result:624, src/main.py의 _show_connection_test_result:356, src/gui.py의 set_controls_state.

**수정 계획**

- 현재 요청에 대한 성공·실패·시간 초과 결과를 처리할 때 요청 ID와 상태 문구를 정리한다.
- 매크로 실행 중 잠금 정책을 지키면서 연결 테스트 버튼 상태를 복원한다.
- 이전 요청의 늦은 결과가 새 테스트의 버튼이나 메시지를 바꾸지 않게 한다.

**완료 조건:** 성공·실패·시간 초과 후 유휴 상태에서는 재시도할 수 있다. 매크로 실행 중에는 임의로 버튼을 활성화하지 않는다. 오래된 요청 ID의 결과는 무시한다. 실제 Tk 창과 Telegram 연결 없이 상태 변경을 검증한다.

## 7 개발 검증 CI 보완

**확인한 문제:** 평가 당시 .github/workflows/build-executable.yml:59에는 원격 제어 테스트 실행만 있었고 tools의 핵심 런타임 회귀 테스트는 실행하지 않았다. 일부 런타임 검사는 소스에 특정 문자열이 있는지만 확인하므로 위와 같은 실행 경로의 불일치를 놓칠 수 있다.

**수정 계획**

- 테스트를 빌드와 별도인 개발 검증 작업으로 구성한다. 현재 빌드 작업 안의 테스트도 저장소의 빌드 규칙에 맞게 정리하고 검증 통과 여부를 연결한다.
- Windows·Python 3.14에서 저장소 루트와 src를 PYTHONPATH에 넣고 tools와 mod/telegram_remote_control/tests를 모두 실행한다.
- unittest discover에 포함되지 않는 tools/test_smart_disarm_fixes.py도 별도 실행 대상으로 명시한다.
- 이번 결함의 회귀 검사는 실제 함수 호출과 관찰 가능한 동작을 검증한다. 문자열 존재 검사만 추가하고 완료로 처리하지 않는다.
- CI는 테스트를 위해 exe를 실행하거나 실제 게임·Telegram 계정·사용자 설정을 사용하지 않는다.

**완료 조건:** 두 테스트 묶음과 스마트 개봉 시나리오의 실패가 개발 검증을 실패시키고, 검증 실패 상태에서 빌드·릴리스가 진행되지 않는다. 실제 push나 릴리스 없이 워크플로 정의와 로컬 동등 명령을 확인하고 원격 CI 미실행 여부를 보고한다.

## 평가 시점의 검증 기록

| 검증 | 결과 |
| --- | --- |
| tools의 unittest discover | 222개 통과, 실패·오류·건너뜀 없음 |
| mod/telegram_remote_control/tests의 unittest discover | 42개 통과, 실패·오류·건너뜀 없음 |
| tools/test_smart_disarm_fixes.py | 전체 PASS |
| 추가 재현 | 위 1·2·3·4·6번의 가짜 화면·API·장치·UI 재현 확인 |
| 다운로드 취소 | 취소 핸들러의 quit·destroy 호출과 로컬 Tk quit 구현 확인 |

이 결과는 앞선 평가 실행의 기록이다. 스마트 개봉의 전체 PASS 출력은 당시 build/source-audit-smart-disarm.txt에 저장했으나 문서 저장 시점에는 그 파일도 확인되지 않았다. 다음 세션의 수정 완료 결과로 이 기록을 재사용하지 않는다.

평가 시 src/script.py:133의 FarmConfig 선언에서 non-string key RuntimeWarning이 출력됐다. LoadSettingFromDict가 실행 설정을 채우는 경로에서는 테스트가 통과했으므로 위 7건의 확정 결함에 추가하지 않았다. 다음 세션에서 경고를 보더라도 새 수정 때문에 생긴 것이라고 단정하지 않는다.

실제 에뮬레이터 인식 정확도, 장시간 실기 실행, Telegram 실통신, 업데이트 적용, 실행 파일 빌드·배포는 검증하지 않았다. 특히 스마트 개봉의 실기 적중률은 합성 시나리오 통과만으로 보장하지 않는다.

## 개발 검증 명령

아래 명령은 정상 작업 폴더와 기존 Python 환경이 다시 확인된 뒤 사용한다. 환경이 없으면 먼저 기존 개발 환경을 확인하고, 테스트 실행을 위해 배포본을 시작하지 않는다.

~~~powershell
$env:PYTHONPATH = "$PWD;$PWD/src"

build/wvd_py314_venv/Scripts/python.exe -B -X utf8 -W ignore::SyntaxWarning -m unittest discover -s tools -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw 'tools 테스트 실패' }

build/wvd_py314_venv/Scripts/python.exe -B -X utf8 -W ignore::SyntaxWarning -m unittest discover -s mod/telegram_remote_control/tests -p 'test_*.py'
if ($LASTEXITCODE -ne 0) { throw '원격 제어 테스트 실패' }

build/wvd_py314_venv/Scripts/python.exe -u -B -X utf8 -W ignore::SyntaxWarning tools/test_smart_disarm_fixes.py
if ($LASTEXITCODE -ne 0) { throw '스마트 개봉 시나리오 실패' }
~~~

개별 수정 중에는 관련 테스트부터 실행하고, 구현이 모두 끝나면 전체 개발 검증을 수행한다. 새 변경이나 실패 원인 없이 이미 통과한 검사를 반복하지 않는다. 테스트 수는 추가에 따라 늘어날 수 있으므로 222·42라는 숫자 자체를 합격 기준으로 고정하지 않는다.

## 수정 완료 기록 — 2026-10-24 23:22 KST

작업 기준은 위 Git 커밋이며 포니테일 원칙에 따라 기존 공통 가드, 설정 저장 함수, 종료 사유와 큐 구조를 재사용했다. 새 프로그램 의존성, 별도 프레임워크, 대규모 구조 변경은 추가하지 않았다. 착수 전 문서 변경은 보존했고 소스·테스트·워크플로 변경은 이번 요청으로 작성했다. 과거에 유실된 미커밋 변경을 복구한 결과는 아니다.

| 항목 | 구현 내용 | 주요 회귀 테스트 |
| --- | --- | --- |
| 1 | return_to_town이 chest_guard 판정을 공유한다. 상자·축복 우선순위, 0.95 임계값과 ROI를 유지하며 연속 결과창 탭은 최대 3회다. 매회 새 화면을 분류하고 UNKNOWN/LOADING으로 횟수를 초기화하지 않는다. 전체 제한 시간의 강제 종료 경로를 유지했다. | test_return_to_town.py의 low_confidence, unchanged_dialogue, normal_reward_pages, total_deadline_fallback 테스트; test_runtime_guards.py의 synthetic_chest_selection_fixture |
| 2 | command_service의 초기 메시지 정리는 설정 세대별 1회다. 재연결 시 offset을 유지하고 큐 전달 후에만 ID를 갱신한다. 이전 세대 응답과 중복 ID를 무시한다. | test_command_service.py: reconnect_delivers_pending_stop_exactly_once, old_generation_response, offset_only_advances_after_command_delivery 등 5개 |
| 3 | ResetDevice에서 연결·복구 실패를 ERROR로 기록한다. 에뮬레이터 부팅 실패의 adb_boot_timeout과 기존 오류를 보존한다. 실제 중지 이벤트는 TaskStoppedException으로 분리하고 Farm의 초기 대기도 완료 처리 범위에 넣었다. | tools/test_adb_failure.py 7개 및 test_feature.py의 오류 알림·실행 상태 해제 검사; 기존 worker/recovery/maintenance 검사 |
| 4 | GUI의 모든 설정 읽기·저장·작업별 전환·실행 완료 재읽기, 로컬/원격/헤드리스 실행, KARMA_ADJUST 저장에 선택 경로를 전달한다. CLI의 언어 설정은 GUI import 전에 적용한다. 명시 파일 읽기 실패 시 다른 설정으로 대체하지 않으며 import 중 마이그레이션 저장을 막았다. | tools/test_custom_config.py 6개, 기존 test_config_persistence.py; 임시 기본·사용자 지정 파일의 보존 검사 |
| 5 | Progressbar는 공유 Event를 설정하고 창만 닫는다. 다운로드 읽기·재시도·검증·압축 해제·재시작 준비에서 취소를 확인하고 HTTP timeout은 15초다. 종료 이벤트를 소비할 때까지 중복 다운로드를 차단한다. 취소 뒤 늦은 progress/restart_ready와 재시작 안내 중 취소도 처리한다. | tools/test_updater_cancel.py 9개; 실제 네트워크·배치·프로세스 실행 없음 |
| 6 | 현재 request_id의 성공·실패·시간 초과 결과에서 ID와 상태를 정리하고 버튼을 복원한다. 매크로 실행 중 잠금, 진행 중 테스트의 잠금, 오래된 결과 무시를 유지한다. | tools/test_connection_test_ui.py 4개; 가짜 위젯 사용 |
| 7 | build-executable.yml에 Windows/Python 3.14 validate 작업을 추가했다. tools·원격·스마트 개봉 검증을 실행하고 build는 needs: validate로 연결했다. 빌드 작업 안의 테스트 단계는 제거했다. | 세 명령의 로컬 실행 통과; 작업 의존성과 검증 명령 위치의 정적 확인 통과 |

위 개발 검증 명령을 recovered-source에서 프로젝트 가상환경으로 실행했다. 최종 tools unittest는 **214개 통과**, 원격 제어 unittest는 **54개 통과**이며 실패·오류·건너뜀은 없다. 기존 229개에 회귀 테스트 39개가 추가됐다. 스마트 개봉 독립 시나리오는 **전체 PASS**, 종료 코드 0이다. 최종 소스 변경은 스마트 개봉 알고리즘을 바꾸지 않았으므로 이미 통과한 독립 시나리오를 불필요하게 반복하지 않았다. git diff --check도 통과했다.

상자 검사는 실제 이미지 템플릿을 중립 배경에 넣은 **합성 fixture**이며 실제 게임 캡처가 아니다. 실제 StateChest가 Open 좌표만 누르고 원격 분류도 CHEST를 선택하는 것을 확인했다. 화면 픽셀 변화는 진행 증거로 쓰지 않는다. 다른 확정 상태 없이 결과창만 네 페이지 이상 이어지는 경우에도 3회 제한이 적용되어 전체 제한 시간 폴백으로 갈 수 있다. 이 상한을 넓히려면 실제 캡처에서 보상 페이지 전환을 식별할 표식을 검증해야 한다.

실제 게임·ADB 장치·Telegram API·Tk 창, 업데이트 적용, GitHub Actions 실행은 검증하지 않았다. 모든 퀘스트 분기의 장시간 실사용 검증도 아니다. src/script.py:139의 기존 FarmConfig non-string key RuntimeWarning은 남아 있다. 취소는 현재 네트워크 읽기나 압축 파일 한 개의 해제가 반환된 다음 관찰될 수 있지만 취소 후 재시작은 차단한다. 빌드·배포·커밋·push·PR은 수행하지 않았다.
