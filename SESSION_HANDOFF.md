# 세션 인계 — 3.2.1 통합 및 영묘 6종 배포 완료

## 출구 반복 실패 추가 수정 — 2026-11-02 00:08 배포 완료

- 20:54 배포 뒤 `log_261101-205805.txt`와 실패 캡처 18개에서 용광로 3번 도착 뒤 출구 Auto-Move 인식이 약 52%로 실패하고 재시작을 반복한 것을 확인했다. 이전 검증은 첫 이동에 그쳐 밝은 출구 버튼을 놓쳤다.
- `StateMapSearch`는 같은 새 프레임에서 기존 어두운 버튼과 `AutoMove_light`를 순서대로 인식한다. 밝은 실제 캡처를 별도 템플릿과 fixture로 추가하고 필수 이미지 목록에도 등록했다. 인식 임계값은 유지한다.
- 밝은 출구 회귀 테스트 RED 확인 후 수정, 지도 테스트 6개 및 전체 tools 299개 PASS. 실제 실패 화면 18장 모두 정확한 버튼 위치에서 0.926~1.0 매칭. 읽기 전용 리뷰 추가 결함 없음. 증거 로그 `.superpowers/sdd/upstream-3.2.1-merge-plan/exit-button-{red,green,full}.log`.
- 기존 자동화 PID 8816을 종료하고 개발용 ADB 검증 완료. 실제 StateMapSearch로 3번 이동, 00:04:35 실제 도착 판정 DONE, 상자 보상 수령 후 00:04:55 밝은 출구 버튼 `[179,1128]` 탭, 00:06경 영묘 선택 화면 복귀를 확인했다. 증거: `build/exit-button-live/entry-034.png`(3번 도착), `entry-055.png`(영묘 선택 메뉴 복귀), `exit-live-third-confirm.log`, `exit-live-return.log`. 전투는 게임 자동 전투, 상자/보상은 직접 입력 및 기존 SmartDisarm을 이용했으므로 전체 자동 루프 무인 완주로 표현하지 않는다. 마지막 진단 스크립트는 이미 메뉴로 복귀하여 'Not a confirmed dungeon/map screen'으로 안전 중단했다. 게임은 영묘 선택 메뉴에 두었다.
- builder(gpt-6-luna/high, Fast 상속)가 새 `build/release-stage-20261102-000710-aaebef` 빌드 성공(종료 코드 0). 메인이 00:08:17 KST 상위 `dist/wvd`에 프로그램 파일 3개만 배포했고 설정·로그·audit 131항목 보존을 확인했다. 이전 프로그램은 stage의 `previous-deploy`에 백업했다. `build/current-deployment-stage.txt`와 stage의 `deployment-receipt.json` 참조. 빌드/배포 중 테스트·실행·스모크 검증은 하지 않았고 배포 exe는 자동 실행하지 않았다.


## 최신 경로 변경 — 2026-11-01 용광로 영묘도 3번 직행 후 복귀

- **20:54:10 KST 재빌드·재배포 완료**. 사용자 재요청에 따라 builder가 현재 소스를 새 `build/release-stage-20261101-205255-016d1b`에 빌드했다(종료 코드 0). 메인이 상위 `dist/wvd`의 프로그램 파일 3개만 교체했고 설정·로그·audit 112항목을 보존했다. 직전 20:50 프로그램은 새 stage의 `previous-deploy`에 백업했다. 배포 exe 자동 실행·추가 테스트는 하지 않았다. 최신 포인터/배포 영수증은 새 stage 기준이다.
- **20:50:31 KST 배포 완료**. builder(gpt-6-luna/high, Fast 상속) 빌드 종료 코드 0, 스테이징 `build/release-stage-20261101-204924-df2111`. 메인이 상위 `dist/wvd`의 프로그램 파일 3개만 교체했고 설정·로그·audit 보호 매니페스트 112항목이 일치했다. 이전 프로그램은 해당 stage의 `previous-deploy`에 보존했다. 배포된 exe는 실행하지 않았다.
- 사용자 요청으로 `LMG-GT` 용광로의 영묘도 다른 6종과 동일하게 **3번 `[555,1235]` → 상자 처리 → 4번 출구 `[178,1240]`** 순서로 변경했다. 기존 앞 두 목표 `[393,545]`, `[657,755]`만 제거했다. 두 목표의 지도 드래그 `右下`와 용광로 고유 입구 `LMG/LMG1F`, 왕도 출발은 유지했다. 아래 용광로 경로를 변경하지 않았다는 설명은 과거 기록이다.
- `resources/quest/quest.json`과 변경 기록을 갱신했다. `tools/test_thief_tomb.py`의 실제 StateDungeon 호출 테스트에 `LMG-GT`를 추가해 상자 처리 후 출구로 진행하는 순서를 검증했다. 변경 전 실패 → 변경 후 영묘/자원/지도 관련 **17개 PASS**, diff 공백 검사 PASS. 로그: `.superpowers/sdd/upstream-3.2.1-merge-plan/crucible-route-{red,green}.log`.
- 이번 경로 변경 후 전체 스위트와 3번 직행 실게임 완주는 추가 실행하지 않았다. 앞선 실게임 확인은 기존 용광로 첫 목표 이동이므로 새 3번 직행 완주 검증으로 표현하지 않는다.

## 최신 배포 — 2026-11-01 20:24 KST 마을 왕복 수정 재배포 완료

- 실게임 검증 및 전체 tools 298개 통과 후 builder(gpt-6-luna/high, Fast 상속)가 새 `build/release-stage-20261101-202255-f91cfb`에 빌드했다. 종료 코드 0.
- 20:24:05 KST 메인이 상위 `dist/wvd`에 배포 완료. `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 교체하고 설정·로그·audit 보호 매니페스트 111항목의 일치를 확인했다. 이전 프로그램은 같은 stage의 `previous-deploy`에 보존했다.
- 배포된 exe는 자동 실행하지 않았다. 배포 전 개발 검증에서 실제 게임은 용광로 영묘 내부로 진입해 첫 목표를 향해 이동한 상태였다. 빌드/배포 중 게임 입력·스모크·실행 테스트는 수행하지 않았다. 아래 실게임 검증 범위와 전체 완주는 구분한다.

## 최신 개발 확인 — 2026-11-01 마을 왕복 수정 및 실게임 검증

- 사용자가 20:13 배포 후 마을 왕복을 보고하고 직접 조작하며 수정하도록 명시 요청했다. 새 실행 로그 `dist/wvd/logs/log_261101-201417.txt`에서 실제 선택 작업은 `LMG-GT`(용광로 영묘)였다.
- 원인: `StateEoT`가 월드맵 진입 직후 검은 전환 프레임을 공통 `FindCoordsOrElseExecuteFallbackAndWait`에 전달했고, 해당 함수가 즉시 fallback BACK을 실행해 마을로 돌아갔다. 앞선 지도/시작화면 수정만으로는 이 일반 화면전환 경로를 막지 못했다.
- 수정: 공통 목표 탐색에서 BLACK/abyssReadying 프레임 동안 입력 없이 기다리고 일반 재시도 횟수를 소모하지 않는다. 전환이 90초 연속 지속되면 `screen_transition_timeout`으로 중단한다. 정상 프레임을 받으면 전환 제한을 초기화한다.
- 직접 검증: 사용자 허가 후 실제 ADB 입력으로 수정된 생산 코드의 StateEoT/Teleport/FindCoords 경로를 실행했다. 20:19:33 마을 확인 → 월드맵 → 영묘 메뉴 → 20:20:41 LMG-GT 내부 진입 확인(10개 명령, 40개 캡처). 이어 실제 StateMapSearch로 첫 목표 `[393,545]`를 선택하고 검출된 Auto-Move `[392,435]`를 눌렀으며, 20:22:06 미니맵/장면 변화로 실제 이동을 확인했다. 전체 던전 완주·상자 처리를 검증한 것은 아니다.
- 진단 스크립트/원본 캡처는 통합 소스의 `build/live-town-entry.py`, `build/live-first-map-move.py`, `build/town-loop-debug/entry-039.png`(진입), `entry-047.png`(이동)에 있다. 실사용 캐릭터 정보가 있으므로 커밋/배포 대상이 아니다.
- 새 테스트는 기존 코드에서 실패 후 수정본에서 통과했다. 최종 전체 tools **298/298 PASS**, 로그 `.superpowers/sdd/upstream-3.2.1-merge-plan/town-transition-final.log`. AST 추출 기반 파티 테스트에 새 화면 분류 의존성을 연결했다. 기존 FarmConfig RuntimeWarning은 남는다. 리뷰에서 새 blocker 없음(기존 zh_CN 필수 이미지 차단 정책 유지).

## 최신 배포 — 2026-11-01 20:13 KST 반복 이동·재시작 오류 수정 배포 완료

- 사용자 명시 요청으로 `builder` 역할(gpt-6-luna/high, 부모 `service_tier=fast` 상속)에 스테이징 빌드를 위임했다. 빌드 종료 코드 0. 스테이징은 통합 소스의 `build/release-stage-20261101-201248-4fc63a`다.
- 20:13:56 KST `3.2.1-momo.1`을 실제 `C:/Users/admin/Documents/momo31-wvd/dist/wvd`에 배포했다. 아래 반복 오류 수정(Auto-Move 버튼/영문 템플릿, 상자·지도 우선 판정, 시작 화면 확인 후 재개)이 반영됐다.
- `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 교체했다. `config.json`, `logs`, `audit` 보호 매니페스트 110항목이 배포 전후 일치했다. 기존 프로그램 파일은 같은 스테이징의 `previous-deploy`에 보존했다.
- 빌드·배포 단계의 테스트/스모크/실행은 수행하지 않았다. 배포된 exe는 자동 실행하지 않았다. 개발 단계의 296개 테스트 통과와 실게임 완주 검증은 구분한다.
- 기록: 스테이징의 `build.log`, `build-exit-code.txt`, `protected-before.json`, `protected-after.json`, `deployment-receipt.json`. `build/current-deployment-stage.txt` 갱신 완료. 배포 스크립트의 프로세스 경로 조회가 접근 제한으로 실패하여 권한 승인 후 같은 스크립트로 배포를 완료했다.

## 최신 상태 — 2026-11-01 반복 이동·재시작 오류 수정 (미배포)

- 사용자 요청: 계속 발생하는 오류 진단·수정. 실제 배포 로그 `log_261101-145155.txt`와 재시작 전 캡처, 읽기 전용 ADB 포커스/logcat으로 조사했다.
- 첫 원인: 영묘 지도에서 `position [555,1235]` 선택 후 고정 좌표 `[136,1431]`(지도 모드 도구)을 눌러 이동하지 못했다. 지도 하단 아이콘이 `dungFlag`에 0.831로 매칭되어 던전으로 오인하고, Resume 20회 후 재시작을 반복했다. 실제 이동 버튼 중심은 캡처에서 `[553,1128]`이다.
- 수정: `StateMapSearch`는 목적지 선택 후 새 캡처의 `AutoMove`를 찾아 누른다. 없으면 탭하지 않고 지도 재판정으로 돌린다. 기존 영문 AutoMove 템플릿은 최대 0.525로 인식 실패하여 실제 캡처의 버튼 글자/아이콘으로 갱신했고 필수 이미지 목록에 추가했다. `IdentifyState`는 상자 → 지도 → 던전 순서로 판정하며, 이동 실패 시 지도 상태를 유지한다. 영묘 좌표/경로는 변경하지 않았다.
- 두 번째 원인: 재시작 후 시작 표식이 없는 두 프레임을 준비 완료로 간주했다. 이어서 fallback BACK이 게임을 홈으로 보낸 것을 Android `moveTaskToBack` 로그로 확인했다. 이제 실제 게임/메뉴 표식이 두 프레임 연속 확인돼야 중단된 작업을 재개한다. 알 수 없는 화면은 입력 없이 대기한다.
- 테스트: `tools/test_map_movement.py`, `tools/test_guild_startup_recovery.py`에 실제 지도 캡처 재생·버튼 없음·지도 오인·상자 우선·시작 화면 대기/시간제한 회귀 검증을 추가했다. 실패를 먼저 확인한 뒤 수정했다. 최종 전체 tools **296/296 PASS**, 종료 코드 0, diff 공백 검사 PASS. 로그: `.superpowers/sdd/upstream-3.2.1-merge-plan/repeated-errors-final.log`. 기존 FarmConfig RuntimeWarning은 남아 있다. 별도 읽기 전용 검토에서 새 회귀 결함은 발견하지 못했다.
- 빌드·배포·커밋은 수행하지 않았다. 실행본은 14:50 배포본이며 새 소스 변경이 반영되지 않았다. 빌드/배포 요청 시 반드시 builder에 스테이징 빌드를 위임하고, 배포는 메인이 별도로 수행한다. 실제 게임 입력/완주 검증은 하지 않았다. 기존 ScreenShot 내부 복구가 중첩되면 시작 대기 300초가 전체 경과시간의 엄격한 상한은 아니라는 기존 제약은 남는다.

## 최신 상태 — 2026-11-01 14:50 KST 알림 닫기 영구 저장 재배포

- 릴리즈 알림 닫기를 누르면 `GENERAL.RELEASE_NOTICES_DISMISSED=true`를 저장한다. 작업 실행 중에도 저장되며, 재실행 후 수동 업데이트 안내·신규 버전 알림과 이미 대기 중인 알림을 숨긴다. 개발 단계에서 관련 테스트 33개 및 JS 닫기/저장 실패 처리 검증 PASS.
- 사용자 상시 지시대로 `builder` 서브에이전트(Luna, Fast/priority)가 빌드를 수행했다. 종료 코드 0. 통합 소스의 `build/release-stage-20261101-144959-128565`가 새 스테이징이다.
- 14:50:53 KST `3.2.1-momo.1`을 상위 `dist/wvd`에 재배포했다. `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 교체했고 `config.json`, `logs`, `audit` 보호 매니페스트 72항목이 일치했다. 이전 프로그램은 스테이징의 `previous-deploy`에 보존했다. 배포된 exe를 실행하지 않았다.
- Git: 통합 작업본은 `feature/upstream-3.2.1-tomb-routes`, HEAD `73ecb46a49d7de0a9816311c6a2af252247945cd`이며 해당 커밋은 origin에 푸시됐다. 이번 알림 영구 저장 변경은 그 이후의 미커밋 변경이다. 아래의 detached HEAD·전체 미커밋 설명은 과거 기록이다.

## 최신 배포 — 2026-11-01 12:30 KST 상자 후 출구 이동 및 알림 닫기

- 이 항목은 아래의 3번 직행 경로 설명보다 우선한다. 전사·도적·승려·마법사·기사·Rarities 영묘 6종은 이제 `3번 [555, 1235] → 상자 처리 완료 → 4번 출구 [178, 1240]` 순서다. 두 지점 모두 `右下` 지도 드래그를 사용한다. 용광로 영묘 `LMG-GT`는 유지했다.
- `src/ui.html`의 릴리즈 알림에 별도 닫기 버튼을 추가했다. 다운로드 취소와 별도로 알림을 숨기며 기존 한국어·영어·중국어 번역을 사용한다.
- 개발 검증: 알림 관련 Web UI 10개 PASS, JS 구문·닫기 핸들러·번역 확인. 영묘 변경은 RED 확인 후 6종의 상자 처리/출구 이동 순서를 포함한 관련 38개 PASS. 이번 변경 후 전체 스위트나 실게임 완주 검증은 수행하지 않았다.
- Python/PyInstaller 빌드 종료 코드 0. `2026-11-01T12:30:38+09:00`에 `3.2.1-momo.1`을 실제 `C:/Users/admin/Documents/momo31-wvd/dist/wvd`에 재배포했다.
- 통합 worktree의 스테이징: `build/release-stage-20261101-122756-315932`. 이전 프로그램 파일은 해당 폴더의 `previous-deploy`에 보존했다. 빌드 로그·종료 코드·보호 매니페스트·배포 영수증도 같은 폴더에 있다.
- `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 교체했다. `config.json`, `logs`, `audit` 보호 매니페스트 45항목이 배포 전후 일치했다. 배포된 exe 자동 실행 및 배포 단계 테스트는 수행하지 않았다.

## 최신 상태 — 2026-11-01 01:57 KST 영묘 6종 3번 직행 재배포 완료

- 이 항목은 아래의 미배포·4번 좌표 설명보다 우선한다. 사용자 요청으로 전사·도적·승려·마법사·기사·Rarities(`LMG-FT/TH/PR/MG/KN/RA`) 모두 `[["position", "右下", [555, 1235]]]` 한 지점 직행으로 변경했다. 기존 `[178, 1240]`은 출구였다. 별도 경로의 용광로 영묘 `LMG-GT`는 유지했다.
- 테스트 RED 확인 후 관련 32개 PASS, 전체 tools **285/285 PASS**. 소스 변경은 퀘스트 데이터·관련 테스트·변경 기록이며, 실행 중 엔진이나 안전 인식 조건을 변경하지 않았다.
- 빌드 종료 코드 0. **01:57:24 KST `3.2.1-momo.1` 재배포 완료**, 실제 위치 `C:/Users/admin/Documents/momo31-wvd/dist/wvd`. `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 교체했다. `config.json`, `logs`, `audit` 보호 매니페스트 40항목이 배포 전후 일치했다.
- 최신 스테이징: 통합 worktree의 `build/release-stage-20261101-015641-163372`. 이 폴더의 `previous-deploy`에 이전 배포본을 보존했다. 기록은 `build.log`, `build-exit-code.txt`, `protected-before.json`, `protected-after.json`, `deployment-receipt.json`. 포인터 `build/current-deployment-stage.txt`도 갱신됐다.
- 배포된 exe를 자동 실행하거나 스모크/해시 검증하지 않았다. 3번 좌표의 실게임 이동·전투·완주는 아직 미검증이다. 다음 실행 결과를 보고 후속 판단한다.

## 2026-11-01 후속 수정 — 도적 영묘 3번 지점 직행 (미배포)

- 이 항목은 아래 01:36 인계의 도적 경로 설명보다 우선한다. 사용자가 도적 영묘 이동 실패를 보고하여 실행 로그와 ADB 연속 캡처로 조사했다.
- 원인: `右下` 드래그 후 `[178, 1240]`은 실제 지도 왼쪽 아래 출구였다. 로그 01:49:47/01:50:50에서 이 좌표를 누른 뒤 전투 없이 영묘 메뉴로 복귀했다. 다른 화면 후보의 DEBUG 이미지 매칭 실패는 이 문제의 직접 원인이 아니다.
- 사용자 지시: 기존 **3번 좌표**로 이동. 통합 worktree의 `resources/quest/quest.json`에서 **LMG-TH만 `[555, 1235]` 한 지점 직행**으로 변경했다. 지도 드래그는 `右下` 유지. 전사·승려·마법사·기사·Rarities 및 용광로 경로는 변경하지 않았다. 명시적 퇴장 지점은 추가하지 않았다.
- `tools/test_thief_tomb.py`의 목표 기대값을 갱신하여 RED 1건 → 관련 32개 PASS를 확인했다. Telegram 55개 PASS, 스마트 개봉 독립 시나리오 전체 PASS. 기존 FarmConfig RuntimeWarning은 그대로다.
- **빌드·배포는 하지 않았다. 현재 실행 중인 `dist/wvd/wvd.exe`는 여전히 출구 좌표를 사용하는 이전 배포본이다.** 새 좌표의 실게임 이동·전투·완주는 검증하지 않았다. 사용자 빌드/배포 요청이 오면 기존 배포 절차를 따른다.
- 진단 캡처는 통합 worktree의 `build/thief-movement-debug`에 있다. `cycle-02.png`는 드래그 후 실제 도적 지도이며 출구와 3번 지점을 확인할 수 있다. 데스크톱/캐릭터 캡처는 배포·커밋 대상이 아니다.
- 개발 검증 로그: `.superpowers/sdd/upstream-3.2.1-merge-plan/thief-third-point-*.log`.
- 전체 tools 검사: 첫 실행 285개 중 `test_shutdown_deadlines_are_bounded`의 download 하위 사례 1건 실패(실제 보조 스레드가 아직 살아 있는 타이밍). 해당 테스트 단독 재검사 PASS, 소스·테스트 추가 변경 없이 전체 재실행 **285/285 PASS**. 이 종료 테스트의 타이밍 민감성은 이번 좌표 수정 범위에서 변경하지 않았다.

작성: 2026-11-01 01:36 KST. 이 문서가 이전 세션 인계보다 우선한다. 아래 경로·프로세스는 다음 세션에서 다시 확인한다.

## 다음 세션에서 가장 먼저 확인할 것

1. **실제 수정 대상은 아래 통합 worktree다.** 상위 폴더의 잔여 소스나 `recovered-source` 본체에서 기능 수정을 시작하지 않는다.
2. 통합 worktree의 `AGENTS.md`와 이 문서를 읽고 현재 HEAD·미커밋 변경을 확인한다. 변경을 초기화하거나 worktree를 삭제하지 않는다.
3. 마지막 사용자 요청까지 구현·재배포를 완료했다. 사용자 후속 요청이나 실제 사용 결과를 기준으로 진행한다. 과거 인계에 적힌 미완료 버그·옛 빌드를 현재 상태로 반복하지 않는다.
4. 개발 검증과 배포 절차를 구분한다. 새 빌드·배포가 필요하면 `docs/build-and-release.md`를 먼저 읽는다.

## 경로와 Git 상태

| 용도 | 절대 경로 |
|---|---|
| 대화 시작 폴더 | `C:/Users/admin/Documents/momo31-wvd` |
| 원래 복구 저장소 | `C:/Users/admin/Documents/momo31-wvd/recovered-source` |
| **현재 통합 소스·개발 환경** | `C:/Users/admin/Documents/momo31-wvd/recovered-source/build/merge-321-worktree` |
| **실제 배포본** | `C:/Users/admin/Documents/momo31-wvd/dist/wvd` |
| 실행 파일 | `C:/Users/admin/Documents/momo31-wvd/dist/wvd/wvd.exe` |

- 원래 저장소와 worktree의 기준 HEAD: `4e907ba8ec40d869cf90dcd8d992afcd1c328ba3`.
- 통합 worktree는 **detached HEAD이며 변경은 미커밋**이다. 커밋·push·PR은 하지 않았다. 프로그램 버전은 `3.2.1-momo.1`이다.
- 업스트림 고정 대상: `4ba47a7af16eee874ae1ae178a2ca27055d72f61` (3.2.1). Git merge commit 대신 기존 로컬 수정을 보존한 기능별 소스 이식이다.
- worktree 생성 시 호스트 도구가 불완전한 상위 폴더에서 실패하여 Git worktree로 만들었다. 현재 디렉터리를 Git이 관리하며 호스트 작업본 UI의 자동 관리 대상은 아니다.
- 인계 갱신 직전 worktree 상태 항목은 505개였다. 이동·삭제·미추적 디렉터리가 있어 이 수치를 실제 변경 파일 수와 같다고 해석하지 않는다.
- 원본 소스 530개 보존 검증은 병합 완료 때 수행했다. 이번 인계 요청으로 세 위치의 `SESSION_HANDOFF.md`를 갱신하므로, 이후 원본 해시 검사에서 인계 문서 변경은 의도된 차이로 구분해야 한다.

## 업스트림 통합 완료 내용

- Task 0~8 완료. pywebview/WebView2 UI, 공통 설정 계층, UI/게임 언어 분리, 신규 작업·이미지 구조, 런타임 개선을 도입했다.
- 한국어 UI, Telegram 제어, 스마트 개봉, 상자 우선 판정과 기존 로컬 복구·안전 조건을 보존했다.
- 실행별 runtime/worker generation, 단일 컨트롤러 큐, 정지 우선 작업 인계, 회차 후 정지, 종료 제한 시간, 포크 전용 업데이트 검증을 연결했다.
- 독립 최종 검토의 Important 5건을 모두 수정했다: 일반 GUI 로그 시작·flush, 실제 `__main__`의 언어 변경, 포화된 UI 큐의 비차단 처리, 실제 Telegram/보조 작업 종료 대기, CI 사전 출시 정책 복구.
- CI에서 `-` 포함 버전의 기존 사전 출시 분류를 유지한다. `3.2.1-momo.1`을 임의로 정식 배포/Pages 게시 대상으로 바꾸지 않는다.

상세 계획·보고서·검토 기록은 모두 통합 worktree 아래에 있다.

- `docs/upstream-3.2.1-merge-plan.md`
- `docs/upstream-3.2.1-merge-report.md`
- `.superpowers/sdd/upstream-3.2.1-merge-plan/progress.md`
- `.superpowers/sdd/upstream-3.2.1-merge-plan/final-review.md`
- `docs/upstream-3.2.1-file-inventory.csv`: 업스트림 변경 743개 판정(722 통합, 17 로컬 보존, 4 제외).
- `docs/upstream-3.2.1-resource-availability.json`, `final-file-list.json` 등 **병합 시점의 인벤토리는 아래 후속 영묘 추가 이전 자료**다. 현재 전체 상태라고 단정하지 않는다.

## 이번 후속 수정: 영묘 6종

사용자가 전사영묘의 기존 1~3번 방문 지점을 생략하고, 종전 4번 좌표로 즉시 이동하도록 요청했다. 이어 같은 맵을 쓰는 도적·Priest·Mage·Knight·Rarities를 추가했다.

| 작업 코드 | 한국어 UI 이름 | 영어 게임 진입 이미지 |
|---|---|---|
| `LMG-FT` | `[뼈] 전사 영묘` | `LMG/FTB1F` (기존) |
| `LMG-TH` | `[뼈] 도적 영묘` | `LMG/THB1F` |
| `LMG-PR` | `[뼈] 승려 영묘` | `LMG/PRB1F` |
| `LMG-MG` | `[뼈] 마법사 영묘` | `LMG/MGB1F` |
| `LMG-KN` | `[뼈] 기사 영묘` | `LMG/KNB1F` |
| `LMG-RA` | `[뼈] Rarities 영묘` | `LMG/RAB1F` |

- 6종 모두 `_TYPE: dungeon`, 경로는 **`[["position", "右下", [178, 1240]]]` 하나**다.
- `右下`는 지도 표시를 맞추는 드래그 `(700,1200) → (100,250)`를 뜻한다. 캐릭터를 우하단으로 직접 걷게 하는 명령이 아니다.
- 공통 세계 지도 목적지는 `LMG/LMG`. 각 작업의 `_EOT` L1/L2에서 위의 독립 진입 이미지를 사용한다.
- 경로·세 언어 표시명: `resources/quest/quest.json`. 한국어 역매핑: `src/config_model.py`.
- 새 영어 이미지 5개: `resources/images/en_US/LMG/{THB1F,PRB1F,MGB1F,KNB1F,RAB1F}.png`.
- 현재 기본 퀘스트 JSON은 **67개 레코드**다(병합 당시 62개 + 새 영묘 5개).
- 기존 `LMG-GT` 용광로 영묘는 이번 직행 경로 변경 대상이 아니다. 기존 4개 목표 지점을 유지한다.
- 이동·전투·상자·회복·휴식·반복은 기존 `StateDungeon`/`DungeonFarm`을 사용한다. 특정 보스나 뼈 획득을 확인하는 전용 조건은 추가하지 않았다.
- 마지막 좌표에 도달하면 공통 로직이 화면을 다시 판정한다. 경로 자체에는 명시적 퇴장이 없다. 귀환 화면이면 휴식/재진입 조건을 따르고, 던전에 남아 있으면 경로를 다시 처리할 수 있다.

## 실제 화면 캡처와 이미지 검증

- 사용자가 에뮬레이터에 메뉴를 띄운 뒤 직접 캡처하라고 요청하여, **실제 ADB 화면 읽기와 캡처를 수행했다**. 이전 문서의 “실제 ADB를 전혀 사용하지 않음”은 이 후속 작업까지 설명하지 않는다.
- MuMu ADB: `C:/Program Files/Netease/MuMuPlayer/nx_device/12.0/shell/adb.exe`.
- 당시 장치 목록: `127.0.0.1:16384`, `emulator-5554`. 두 주소에서 동일한 900×1600 메뉴 화면이 캡처됐다. 다음 세션에는 실제 연결 상태를 다시 확인한다.
- 원본: 통합 worktree의 `build/thief-tomb-capture/tcp.png`, `emulator.png`. 사용자 캐릭터 화면이 포함되어 있으므로 배포/커밋할 자료가 아니다.
- 원본 픽셀에서 각 이름만 추출했다. AI 생성 이미지나 전사 이름의 대체 사용은 하지 않았다.
- 양성 매칭 약 1.0. 해당 행을 제외한 다른 메뉴의 최대 매칭: 도적 0.742, 승려 0.696, 마법사 0.697, 기사 0.723, Rarities 0.439로 기존 0.8 임계값 미만이다.
- 기록: `build/thief-tomb-capture/match-result.json`, `build/class-tombs-match-results.json`, `build/rarities-tomb-match-result.json`.
- 나중에 찍은 `build/class-tombs-menu.png`는 정보 팝업이 떠 있는 화면이다. 이미지 추출에는 앞선 선명한 메뉴 원본을 사용했다.
- 메뉴 선택·던전 진입·실전 전투/완주를 자동 실행해 확인한 것은 아니다.

## 개발 검증 결과와 범위

- 병합 최종 전체 검증: **tools 281/281, Telegram 55/55, 스마트 개봉 독립 시나리오 전체 PASS**. 기본/Telegram 6개 카탈로그 재컴파일 바이트 일치, 실제 숨김 WebView2 UI PASS, 한국어 패널의 중국어 잔여/JS 오류 0, JavaScript 구문 검사 PASS.
- 위 전체 검증은 후속 영묘 추가 전 결과다. 이후 전체 스위트를 다시 돌렸다고 보고하지 않는다.
- 전사 직행 변경: 실제 `LoadQuest` 경로 확인, 다른 퀘스트 데이터 불변 확인, 자원 관련 7개 테스트 PASS.
- 도적 추가: RED→GREEN, 관련 31개 PASS. 실제 진입 이미지 추가 후 영어 자산 검사가 빈 누락 목록을 반환했다.
- 나머지 영묘 추가: `tools/test_class_tombs.py`를 확장해 RED→GREEN. Rarities까지 반영한 최종 관련 **32개 PASS**. 이는 parameter/subTest 항목 수가 아니라 unittest 테스트 수다.
- 후속 테스트: `tools/test_thief_tomb.py`, `tools/test_class_tombs.py` 및 기존 자원/컨트롤러/Web UI 회귀 테스트.
- 로그: `.superpowers/sdd/upstream-3.2.1-merge-plan/{lmg-ft-route-regression,thief-tomb-*,class-tombs-*,rarities-tomb-*}.log`.
- 기존 `FarmConfig`의 `non-string key in __dict__` RuntimeWarning은 남아 있다.

개발용 실행 예(통합 worktree에서):

```powershell
& './build/wvd_py314_venv/Scripts/python.exe' -X utf8 build/check.py tombs-check -m unittest tools.test_class_tombs tools.test_thief_tomb tools.test_upstream_321_merge.ResourceMigrationTests tools.test_main_controller tools.test_web_ui -v
```

## 최신 배포 — 완료

- **2026-11-01 01:31:38 KST**, `3.2.1-momo.1` 재배포 완료. 도적·승려·마법사·기사·Rarities 추가와 전사 직행을 모두 포함한다. 미배포 상태가 아니다.
- 소스: 위 통합 worktree. 배포 위치는 **상위 폴더의 `dist/wvd`**다. `recovered-source/dist`나 worktree 내부의 일반 `dist`를 배포본으로 혼동하지 않는다.
- Python 3.14.6 / PyInstaller 6.22.3 / hooks 2026.9. 빌드는 종료 코드 0.
- 최신 스테이징(worktree 상대 경로): `build/release-stage-20261101-013050-048912`.
- 이전 프로그램 백업: 같은 스테이징의 **`previous-deploy`**. 사용자가 새 배포를 확인할 때까지 보존한다.
- `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 교체했다. `config.json`, `logs`, `audit`의 존재 상태·상대 경로·크기·SHA-256을 비교해 일치를 확인했다. 최신 보호 매니페스트 항목은 38개다(파일 수와 동일한 의미가 아님).
- 기록: 스테이징의 `build.log`, `build-exit-code.txt`, `protected-before.json`, `protected-after.json`, `deployment-receipt.json`.
- 최신 스테이징 포인터: `build/current-deployment-stage.txt`. 교체 스크립트: `build/deploy-321.ps1`(명시 경로 제한·사용자 데이터 보존·실패 시 프로그램 파일 롤백 포함).
- 첫 배포 때 PowerShell이 정상 stderr 로그를 오류로 처리해 중단한 적이 있다. 이후 Python `subprocess.run(..., stdout=log, stderr=STDOUT)`로 빌드 로그를 저장해 해결했다. 이 방식을 유지하면 같은 셸 오류를 피할 수 있다.
- 배포 단계에서는 테스트·exe 실행·스모크·리소스/프로그램 해시 검증을 하지 않았다. 배포된 exe를 자동 실행하지 않았다.
- 01:36 KST 프로세스 확인 시 실행 중인 `wvd.exe`는 없었고 MuMuNxDevice PID 14004가 있었다. 이 PID와 화면은 다음 세션에서 다시 확인한다.

## 남은 제약과 다음 작업 판단

- UI 언어는 한국어·영어·중국어를 지원한다. 게임 이미지 언어와 별개다. 이번 5개 진입 캡처는 **영어 게임용**이다.
- 중국어 게임은 로컬 안전 인식 이미지 `EVENT`, `abyssReadying`, `connection`, `didnottakethequest`, `guildDecline`, `settrap`, `startupDisclaimer`, `tabtostart` 등이 부족해 실행을 차단한다. 새 영묘의 중국어 진입 이미지도 없다. 영어 이미지로 대체하거나 안전 검사를 우회하지 않는다.
- 영어 `FloralHoney`는 해당 작업 이미지가 중국어 전용이라 실행이 차단된다. 병합 시점의 영어 61/62 가용 수치를 현재 67개 카탈로그의 수치로 그대로 사용하지 않는다.
- 이번 영묘의 실제 이동 경로/반복/귀환 완주와 실제 Telegram 통신·업데이트 적용은 검증하지 않았다. 이미지 인식과 모의 회귀 검증 결과를 실게임 완주 성공으로 표현하지 않는다.
- **진행 중인 필수 미완료 작업은 없다.** 다음 요청이 실제 영묘 실행 중 문제라면 해당 배포 로그와 현재 화면을 먼저 읽어 재현 조건을 확인한다.

## 반드시 유지할 작업 규칙

- 사용자 변경·개인 설정 보존. 커밋·push·PR 금지. 복구 백업·worktree를 임의 삭제하지 않는다.
- 상자 표식(`chestFlag`/`whowillopenit`/`chestOpening`)이 있으면 결과창 스킵보다 상자 처리가 우선한다. 0.95 결과창 임계값·최대 3회 스킵·상태 재판정을 유지한다.
- 빌드·배포는 명시 요청 범위에서 수행한다. 개발 테스트는 빌드 전 완료하고, 빌드는 매번 새 `build/release-stage-*`에서 수행한다.
- 배포 검증은 사용자 데이터 보존만 수행하며, exe를 실행하거나 스모크 테스트하지 않는다.
- PowerShell에서 한국어/중국어 here-string을 Python stdin으로 넘기면 `?`로 바뀔 수 있다. 비ASCII 파일 작성은 UTF-8 파일을 `apply_patch`로 만들고 실행한다.
- 새/미추적 텍스트 파일은 LF를 사용한다. tracked whitespace 검사는 일반 `git diff --check`를 쓰며, tracked 파일에 `core.autocrlf=false`를 강제해 모든 CRLF를 오류로 출력하지 않는다.

이 문서는 상위 작업 폴더·복구 저장소·통합 worktree의 `SESSION_HANDOFF.md`에 동일하게 저장한다. 교체 전 인계 파일들은 상위 작업 폴더의 `build/session-handoff-backup-*`에 보존한다.
