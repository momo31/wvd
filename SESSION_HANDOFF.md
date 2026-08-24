# Telegram 원격 종료 작업 인계

마지막 갱신: 2026-08-25 01:27 KST

## 사용자 규칙

- Codex는 Git 커밋, push, PR 생성·갱신을 하지 않는다.
- 실행 파일 빌드·배포 시 `docs/build-and-release.md`와 `AGENTS.md`의 사용자 데이터 보존 절차를 따른다.
- 상자 선택창과 결과창 인식 불변 규칙은 변경하지 않는다.

## 목표와 현재 결과

Telegram `/start`와 `/stop`으로 게임을 안전하게 제어하는 기능을 실기기에서 검증 중이다.

- `/start`는 2026-08-25 01:22 테스트에서 성공했다. 게임 실행, 시작 고지 탭, `FFXI-Org` 매크로 실행까지 확인했다.
- `/stop`은 아직 실패한다. 첫 재진입 문제는 해결됐지만, 월드맵에서 도시로 들어간 뒤 레거시 복귀 함수가 이미 도시라는 사실을 인식하지 못하고 반복 탭한다.
- 01:25:08에 `City_RoyalCityLuknalia`를 25회 찾지 못해 `restartGame()` 경로로 들어갔고 게임이 종료됐다.
- 01:26:39에 게임과 작업이 예상치 않게 다시 시작됐다. 이 재실행 원인은 아직 분석하지 않았다.
- 마지막 확인 시 WVD PID는 15664, 게임 PID는 10732 계열이었다. 다음 세션 시작 시 실제 상태를 다시 확인하고, 실행 중이면 사용자에게 종료를 요청한 뒤 배포한다.

주요 증거 로그:

- `dist/wvd/logs/log_260825-011941.txt:1067`: 도시 표식을 25회 못 찾고 재시작을 판단
- `dist/wvd/logs/log_260825-011941.txt:1068`: 약 91초 뒤 작업이 다시 초기화됨

## 구현된 변경

- `resources/images/closeAppPrompt.png`: 실제 `Close the app?` 문구의 전용 템플릿
- `mod/telegram_remote_control/title_transition.py`: 종료 문구와 제한된 `OK` ROI를 함께 검증하고, 프로세스 종료 후 앱을 다시 실행해 타이틀에서 대기
- `src/script.py`의 `FindCoordsOrElseExecuteFallbackAndWait`: 각 반복 전에 원격 정지 체크포인트 실행
- `RemoteRuntime.stop_transition_started`: 안전 정지 상태기 내부에서 두 번째 `RemoteStopSignal`이 발생해 즉시 강제 종료되던 문제 방지
- 관련 테스트와 설계 문서·변경 로그 갱신

## 다음 세션의 첫 작업

1. 최신 프로세스와 `dist/wvd/logs/log_260825-011941.txt`의 마지막 부분을 확인한다.
2. `src/script.py`의 `TeleportFromDungeonToCity` 전체 호출자를 확인한다.
3. 최소 수정 후보: 도시 대상 검색 중 `Inn` 또는 기존 도시 표식이 검출되면 이미 도착한 것으로 처리하고, 추가 swipe/tap과 `restartGame()` 없이 반환한다.
4. 좌표 폴백으로 도시에 먼저 진입한 fixture에서 반복 탭·재시작이 발생하지 않는 회귀 테스트를 추가한다.
5. 강제 종료 뒤 01:26:39에 작업이 다시 시작된 원인을 작업 완료 callback, bounded worker, Telegram command lifecycle 순서로 조사한다.
6. 관련 테스트 통과 후 문서 절차대로 새 스테이징 빌드·스모크·배포하고 `/start` → `/stop`을 다시 실기기 검증한다.

수정 후보 위치:

- `src/script.py:1829` `TeleportFromDungeonToCity`
- `src/script.py:1852` 도시 대상만 기다리는 `FindCoordsOrElseExecuteFallbackAndWait`
- `mod/telegram_remote_control/runtime_bridge.py:59,206`
- `mod/telegram_remote_control/stop_orchestrator.py:19`

## 검증과 배포 상태

마지막 소스 검증:

- Telegram 원격제어 unittest 35개 통과
- `tools/test_recovery.py` 14개 통과
- `tools/test_main_controller.py` 2개 통과
- `compileall`, `git diff --check` 통과

현재 배포본:

- `dist/wvd/wvd.exe`
- SHA-256 `3B4B4A9072813E62725D33176BC003FC57DD331B3837F786F9E0898E7F4256B3`
- 스테이징 `build/release-stage-20260825-011506`
- 이전 배포 백업 `build/release-stage-20260825-011506/previous-deploy`
- 스테이징·최종 스모크 각각 10초 이상 통과, config/logs/audit 보존 확인

## Git 작업 트리

브랜치 `merge/upstream-2.6.1`, HEAD `55aa4a662b3a9d5ce9f80fd1c932329cfc0b28d4` 기준이다. 관련 변경은 커밋되지 않았고 작업 트리에 남아 있다. `SESSION_HANDOFF.md`와 `AGENTS.md`도 새 인계 규칙 때문에 변경됐다. 기존 변경을 되돌리거나 덮어쓰지 말고 현재 diff부터 확인한다.
