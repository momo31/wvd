# 길드 선택창·시작 로딩 재시작 반복 수정 (2026-09-10, 배포 완료)

- `docs/build-and-release.md` 절차로 `build/release-stage-20260910-192744`에서 Python 3.14.6·PyInstaller 6.22.0 빌드에 성공했다. 이어 `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 `dist/wvd`에 배포했다. 이전 세 항목은 같은 스테이징의 `previous-deploy`에 보관했다.
- 배포 전후 `config.json`, `logs`, `audit`의 154개 파일은 상대 경로·크기·SHA-256이 모두 일치했으며 폴더 존재 상태도 유지됐다. 매니페스트는 같은 스테이징의 `protected-before.json`, `protected-after.json`이다. 빌드·배포 단계에서는 개발 테스트를 다시 실행하거나 exe·스모크·Tcl/Tk·리소스·프로그램 해시 검증을 하지 않았다. 배포된 exe도 실행하지 않았다.

- 사용자 요청: 현재 초기화 반복의 원인을 확인한 후 “원인을 찾았으면 해결을 해”로 수정을 지시했다. 앞선 빌드·배포 요청의 후속 수정으로 빌드·배포까지 진행한다.
- 현재 실패는 `Scorpionesses`의 현상수배 게시판 진입이다. `dist/wvd/logs/20260910_190300.png`에는 Arna의 `I can't.` / `I'll go now.` 선택창이 있다. 일반 길드 진입에는 이 선택지 처리가 빠져 `guildRequest`를 25회 찾지 못했다. 재시작 뒤에는 `Loading master data...` 상태에서 같은 탐색을 재개해 로딩 도중 다시 재시작했다.
- 공통 `FindCoordsOrElseExecuteFallbackAndWait()`에서 단일 목표 `guildRequest`와 `guild` 폴백이 있는 일반 메뉴 진입에만 기존 `guildDecline` 템플릿을 사용한다. 0.95 임계값·제한 ROI에서 검출하고 새 화면을 캡처하며, 3회 선택 후에도 남아 있으면 `guild_dialog_stuck` 사유로 중단한다. `COS/Okay` 같은 복합 퀘스트 목표에는 적용하지 않는다. 기존 파티 재소집 처리는 유지한다.
- 공통 `restartGame()`은 재시작 후 `WaitForGameStartup()`이 끝나야 작업 재시도 신호를 내보낸다. 타이틀·약관·검은 화면·심연 로딩을 기다리고, 시작 화면이 연속 2프레임 사라지면 재개한다. 시작 버튼은 실제 표시될 때만 누르며 300초를 넘기면 `game_startup_timeout` 사유로 중단한다. 로컬·원격 중지도 대기를 끊는다.
- 시작 화면에서 일반 Close 처리를 호출하지 않는다. 실제 19:05:49·19:07:18 로딩 진행 막대가 낮은 임계값의 Close로 오인되는 것을 확인했으며, 시작 대기는 전용 다운로드·세션 종료·시작 버튼만 처리한다. `tools/fixtures/game_startup_loading.png`는 19:05:49 화면의 상단 1490행으로 사용자 ID가 있는 하단은 제외했다.
- 기존 점검 종료 처리를 `StopTaskWithError()`로 재사용하여 위 두 중단 사유도 오류 상세·중단 이벤트·진단 이미지를 보존한다. 이미지 저장 실패가 중단을 취소하지 않으며 기존 `Farm` 완료 처리를 사용한다. 기존 복구 상한·상자 가드·스마트 상자 변경은 유지한다.
- 개발 검증: `build/wvd_py314_venv/Scripts/python.exe -B -X utf8 -W ignore::SyntaxWarning -m unittest -v tools.test_guild_startup_recovery tools.test_server_maintenance tools.test_recovery tools.test_runtime_guards tools.test_screen_health mod.telegram_remote_control.tests.test_title_and_login_transition mod.telegram_remote_control.tests.test_runtime_worker` 71개 통과. `git diff --check` 통과.
- 실제 화면 재생: 로딩 화면 14장에서 불필요한 탭·뒤로가기 0회, 첫 길드 대화 화면에서 `(451, 991)` 선택 1회 및 재시작 0회를 확인했다. 테스트는 장치 입력 없이 캡처·시계를 모사한다. 실제 게임의 선택 이후 진행을 실행한 것은 아니다.

---

# 서버 점검 중 재시작 반복 수정 (2026-09-10, 배포 완료)

- 후속 `빌드하고 배포해` 요청으로 `docs/build-and-release.md`를 확인하고 Python 3.14.6·PyInstaller 6.22.0·`wvd.spec`으로 `build/release-stage-20260910-185449`에서 빌드했다. PyInstaller 종료 코드 0 및 COLLECT 완료 후 `CHANGES_LOG.md`를 복사했다. 앞선 `185357` 스테이징은 PowerShell의 native stderr 처리로 중단됐고, `185430` 스테이징은 Start-Process의 환경 변수 `Path`/`PATH` 중복 오류로 실행되지 않았다. 실제 성공한 빌드는 `185449`뿐이다.
- 새 `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 `dist/wvd`로 이동해 배포했다. 배포 당시 실행 중인 `wvd.exe`는 없었다. 기존 세 항목은 `build/release-stage-20260910-185449/previous-deploy`에 보관했다. `config.json`, `logs`, `audit`의 138개 파일은 배포 전후 상대 경로·크기·SHA-256이 모두 일치했으며 폴더 존재 상태도 일치했다. 매니페스트는 같은 스테이징의 `protected-before.json`, `protected-after.json`에 있다.
- 배포 스크립트 파일 실행은 PowerShell 실행 정책에 막혀, 정책 변경 없이 동일한 배포 명령을 직접 실행했다. 빌드·배포 단계에서는 테스트·exe 실행·스모크·Tcl/Tk·리소스·프로그램 해시 검증을 하지 않았고, 유일한 배포 검증은 위 사용자 데이터 보존 확인이다. 아래 미배포 기록은 소스 수정 직후의 상태이며 이 배포로 완료됐다.

- 사용자 요청: `openworldmap`/`dungFlag` 탐색 실패 후 게임 재시작과 앱플레이어 복구 3회가 반복되는 오류를 수정하고 재발을 방지한다.
- 실제 원인은 서버 점검 화면을 게임 멈춤으로 오인한 것이다. `dist/wvd/logs/20260910_141810.png`, `20260910_142005.png` 모두 “현재 점검 중입니다. 종료까지 기다려 주시기 바랍니다.” 안내이며 예정 시간은 2026-09-10 13:00~16:30(JST)이다. 로그에서도 13:00:54부터 점검 화면을 저장하며 재시작하고, 14:20:05에 복구 상한으로 종료했다. 점검 종료 여부를 외부에서 확인한 것은 아니다.
- `src/script.py`의 공통 `ScreenShot()`이 정상 이미지를 반환하기 전에 `StopIfServerMaintenance()`를 호출한다. 한국어 점검 문구를 높은 임계값 0.95와 제한된 ROI로 확인하고, 런타임 종료 사유 `ERROR`/`server_maintenance`를 기록한 뒤 기존 중단 이벤트·예외로 종료한다. 채굴·던전·텔레그램 로그인에 모두 적용되며 게임/ADB/앱플레이어 재시작 횟수 제한은 유지한다. 진단 이미지 저장 실패도 중단을 취소하지 않는다.
- `resources/images/serverMaintenance_ko.png`는 첫 오류 화면의 날짜 없는 고정 문구 영역 `(244, 620, 414, 80)`을 원본 픽셀 그대로 추출했다. `tools/fixtures/server_maintenance_ko.png`는 두 번째 화면의 안내창 영역 `(200, 580, 500, 440)`이며 사용자 ID를 포함하지 않는다. 다른 게임 언어·변경된 점검 문구는 검증된 캡처를 확보한 뒤 별도 템플릿을 추가해야 한다.
- 저장 이미지 재생: 9월 10일 타임스탬프 이미지 53장 중 점검 화면 38장 모두 검출(최저 98.6497%), 나머지 15장은 미검출(최고 16.7456%). 첫 점검 검출은 13:00:53, 마지막은 14:20:05이다.
- 개발 검증: 기존 `tools.test_recovery`, `tools.test_runtime_guards`, `tools.test_screen_health`, `mod.telegram_remote_control.tests.test_title_and_login_transition`, `mod.telegram_remote_control.tests.test_runtime_worker` 62개 통과. 추가 `tools.test_server_maintenance` 3개 통과. Python 명령은 `build/wvd_py314_venv/Scripts/python.exe -B -X utf8 -W ignore::SyntaxWarning -m unittest <모듈명>`이다.
- 새 테스트는 실제 캡처 변환·매칭·채굴 진입·텔레그램 로그인·작업 종료 코드를 장치 없이 실행한다. 점검 문구가 없는 To Title 창은 통과하고, 점검 시 추가 탭/재시작 없음, 복구 횟수 보존, 저장 실패 시 중단 유지, 종료 사유 보존 및 완료 이벤트 1회를 확인한다.
- 이번 수정은 실행 파일 빌드·배포를 하지 않았고 게임 입력도 하지 않았다. 분석 시 실행 중인 배포본은 `dist/wvd/wvd.exe` PID 7372(9월 9일 09:00 시작)였다. 새 수정의 실행 파일 적용에는 별도 빌드·배포가 필요하다. 기존 스마트 상자·길드 재소집 변경은 보존했으며 커밋·push·PR은 하지 않았다.

---

# 파티 재소집 재시작 반복 수정 (2026-09-07, 미배포)

- 후속 `빌드해` 요청으로 `docs/build-and-release.md`를 읽고 Python 3.14.6·PyInstaller 6.22.0·`wvd.spec`을 사용해 `build/release-stage-20260907-162743`에서 빌드했다. 스테이징 내부 캐시를 사용했으며 EXE 생성 후 COLLECT 단계에서 `OSError: [Errno 22] Invalid argument`로 실패했다. 배포 가능한 빌드가 아니다.
- 재시도 `다시해` 요청으로 `build/release-stage-20260907-163054`에서 같은 절차를 다시 수행해 성공했다. 산출물은 `build/release-stage-20260907-163054/dist/wvd`이며 `CHANGES_LOG.md`를 복사했다. 빌드 단계 규칙에 따라 테스트·exe 실행·스모크·Tcl/Tk·리소스·해시 검증은 하지 않았다. 배포는 하지 않았다.
- 후속 `배포해` 요청으로 해당 산출물을 `dist/wvd`에 배포했다. 기존 `_internal`, `wvd.exe`, `CHANGES_LOG.md`는 `build/release-stage-20260907-163054/previous-deploy`에 보관했다. `config.json`, `logs`, `audit` 1,318개 파일은 배포 전후 경로·크기·SHA-256이 모두 일치했다. 배포된 exe는 실행하지 않았고, 문서 절차에 따라 추가 테스트·스모크 검증도 하지 않았다.
- 실패 원인은 Defender 격리로 확인했다. Windows Defender Operational 이벤트 1116(16:28:30)·1117(16:28:44)에 `Trojan:Win32/Bearfoos.A!ml`, 대상 `build/release-stage-20260907-162743/work/wvd/wvd.exe`, 조치 `격리`가 기록됐으며 해당 exe는 없어졌다. 오탐 여부는 확인하지 못했다. 보호 설정·예외·격리 상태는 변경하지 않았다. 사용자의 보안 기록 확인 및 외부 상태 변화가 필요하다.
- 이번 빌드 단계에서 테스트·exe 실행·스모크·Tcl/Tk·리소스·해시 검증은 하지 않았다. `dist/wvd`와 실행 중인 배포본은 변경하지 않았다. 아래 소스 수정 및 개발 검증 결과는 그대로 유효하다.
- 사용자 요청: 곡괭이 소진 후 `PartyManagementTitle`을 찾지 못해 게임 재시작과 앱플레이어 복구 3회를 반복하는 문제를 해결한다.
- 실제 근거는 `dist/wvd/logs/log_260907-092329.txt`와 09:26:51~10:40:11의 재시작 전 스크린샷 44장이다. 길드 진입 시 Arna의 대화가 막고 있으며, 선택창에는 `I can't.` / `I'll go there straight away.`가 표시된다. 첫 선택창과 재시작 후 선택창, 마지막 대화 화면을 직접 확인했다.
- 원인: 공통 `reunionParty()`의 기본 파티·지정 파티 경로 모두 길드 메뉴만 누르고 대화 선택지는 처리하지 않았다. 같은 게임 상태가 재시작 후 복원되므로 ADB/앱플레이어 재시작으로 해결되지 않는다.
- 수정: 두 경로의 기존 bounded fallback 목록에 `guildDecline`을 추가했다. `resources/images/guildDecline.png`는 첫 실패 화면의 `I can't.` 글자 영역 `(390, 972, 122, 38)`을 원본 픽셀 그대로 추출한 템플릿이다. 일반 대화 옵션 목록에 등록하지 않아 퀘스트별 선택에는 영향을 주지 않는다. 공통 이미지 매칭·상자 로직·복구 횟수 제한은 변경하지 않았다.
- `tools/test_recovery.py`에 실제 재소집·탐색·복구 래퍼를 실행하는 회귀 테스트를 추가했다. 기본/지정 파티별 정상 길드, 대화 끼어듦, 재시작 후 선택창에서 시작, 이미 파티 관리 화면인 경우와 응답 없는 선택창의 탐색 횟수 상한을 확인한다. 수정 전에는 대화가 있는 두 경로 모두 재시작을 요청하며 실패했고 수정 후 통과했다.
- 최종 개발 검증: `build/wvd_py314_venv/Scripts/python.exe -B -X utf8 -m unittest tools.test_recovery tools.test_runtime_guards tools.test_upstream_260_merge.Upstream260MergeTests.test_version_changelog_and_party_management_asset` 42개 통과. `git diff --check` 통과.
- 저장 이미지 재생: 44장 중 선택창 17장 모두 정확한 버튼 중심 `(451, 991)` 검출, 최저 일치도 99.96%. 나머지 27장은 최고 57.97%로 검출되지 않았다. 실제 `_check`·`CheckIf`·탐색 함수와 재소집 함수를 연결해 17장 × 기본/지정 파티 = 34건에서 선택 버튼 1회 탭, 모사한 길드/파티 화면 진행 및 재시작 없음 확인. 로컬 재생 스크립트는 `build/guild-recovery/replay.py`에 있다. 실제 게임의 선택 이후 진행은 아직 검증하지 않았다.
- 분석 시작 시 WVD PID 6200(`dist/wvd/wvd.exe`), MuMu PID 4212가 실행 중이었다. 이번 요청은 소스 수정·개발 검증만 수행했으며 게임 입력·실행 파일 빌드·배포·커밋·push·PR은 하지 않았다. 실행 파일에 적용하려면 별도 빌드가 필요하며, 배포에는 명시적 요청과 `docs/build-and-release.md` 절차를 따른다. 아래 스마트 상자 관련 기존 변경은 보존했다.

---

# 스마트 상자 최적화 작업 인계 (2026-09-07)

현재 목표: 스마트 상자 개봉 로그를 분석하고 실제 개선이 검증될 때까지 반복한다. 아래 Telegram 인계는 과거 기록이며 이번 작업과 별개다.

## 2026-09-07 현재 상태와 후속 수정 (미배포)

- 09:20 사용자 요청으로 빌드만 수행했다. 첫 스테이징 `build/release-stage-20260907-091854`는 EXE 생성 직후 Defender가 `Trojan:Win32/Bearfoos.A!ml`로 탐지해 COLLECT 단계에서 `OSError: [Errno 22] Invalid argument`로 실패했다. 보호 설정·예외·격리 상태는 변경하지 않았고, 사용자가 이후 Defender에서 직접 복원했다고 알렸다. 이 경로는 실패 스테이징으로 취급한다.
- 새 스테이징 `build/release-stage-20260907-092000`에서 Python 3.14.6·PyInstaller 6.22.0·`wvd.spec`으로 재빌드해 성공했다. 최종 빌드 산출물은 `build/release-stage-20260907-092000/dist/wvd`이며 `CHANGES_LOG.md`도 복사됐다. 절차에 따라 테스트·exe 실행·스모크·Tcl/Tk·리소스·해시 검증은 하지 않았다. `dist/wvd`는 변경하지 않았으며 배포는 별도 명시 요청 전까지 진행하지 않는다.
- 사용자 요청: 배포 이후 로그의 개선 여부를 판단한 뒤, `이어서 개선해줘`로 개발을 재개했다. 이번 요청에는 새 빌드·배포를 포함하지 않았다. `dist/wvd`와 실행 중인 앱을 변경하거나 exe를 실행하지 않았다.
- 재개 시 WVD 프로세스는 없었다. 최신 로그는 `dist/wvd/logs/log_260906-014458.txt`(39,520,499바이트, 최종 기록 2026-09-07 00:44:59)이며, 매크로는 09-06 22:03:15에 중지됐다. 이후 기록은 버전 확인과 일시적인 Telegram 연결 오류다. 아래 09-05 당시의 프로세스·새 로그 부재 기록은 과거 상태다.
- 앞선 배포 분석의 비교 구간은 09-05 하루와 09-06 20:58:25까지다. 스마트 호출 127→124회, 탭 140→150회. 탭 대기 중앙값은 0.458→0.288초로 개선됐지만, 스마트를 사용한 실제 상자 처리 시간(겹친 전투 시간 제외)은 110→120상자에서 중앙값 33.11→39.92초, 평균 48.22→48.77초였다. 전반 개선으로 판정하지 않았다.
- 같은 비교에서 캡처 중앙값 0.326→0.495초, 4점 검증 폐기 157→450회, 샘플 상한 폴백 7→20회였다. 스마트 루프 밖 캡처도 0.326→0.493초로 느려져, 전체 지연 증가를 4점 검사만의 비용으로 단정할 수 없다. 09-06 종료 이미지 121장은 보상 후보 59·Oops 함정 확인 21·미확정 41장이었다. 미확정과 무차감을 성공/실패로 강제 분류하지 않는다.
- 연결된 MuMu에 읽기 전용 캡처로 전송 단계만 측정했다. 현재 화면은 1600x900이므로 실제 상자 플레이 부하와 동일하지 않다. EOF 추가 대기는 0~20ms였고, PNG 캡처는 0.848/0.859초로 raw 0.354/0.395초보다 느렸다. 수신 버퍼 64KiB와 1MiB의 교차 4회씩 측정도 중앙값 0.3534/0.3538초로 이득이 없었다. 전송 방식·버퍼·게임 설정은 변경하지 않았다.
- 09-06 전체 로그를 메모리에서 재생했다. 직선성 검사를 제거하거나 마지막 두 점으로 반전 후보를 추가하는 수정은 추가 허용된 추정의 다음 프레임 오차가 컸다(직선성 완화 후보 64건의 중앙값 90px). 채택하지 않았다. 기존 직선성·4점 검증·고속 우회 임계값과 캡처 시각 보정 계수는 유지한다.
- 채택한 최소 수정은 `SmartDisarm.run()`의 중복 캡처 제거다. 탭 후 추가 종료 확인에 사용한 **마지막 정상 프레임 하나**를 다음 조준의 첫 표본으로 재사용한다. 원래 캡처 시작/종료 시각을 함께 보존하고 한 번 사용하면 비운다. 마지막 캡처가 실패하면 이전 확인 화면으로 대체하지 않는다. 종료가 확인되면 기존처럼 즉시 반환하며, 추가 확인 0회 설정도 기존 동작을 유지한다.
- 이에 따라 재조준 경로에서 캡처 1회를 줄인다. 네 개의 서로 다른 관측점 검증은 그대로 수행하며, 오래된 탭 전 표본이나 감속 측정 프레임은 섞지 않는다. 실제 게임 처리 시간·성공률 개선 수치는 아직 없다. 첫 조준의 반복 검증 실패와 전체 캡처 환경 지연은 이번 수정으로 해결됐다고 주장하지 않는다.
- 재사용 시 `[smart_disarm_capture] reuse=settle capture_dt=...`를 기록해 차기 배포 로그에서 적용 여부와 횟수를 확인할 수 있게 했다. `capture_dt`는 재사용한 화면의 원래 캡처 비용이지 실측 절약 시간은 아니다.
- 새 회귀 테스트는 실제 추정·4점 검증을 유지한 채 0.5초 캡처를 모사한다. 정상 재사용(최신 프레임 1회·원래 시각), 마지막 캡처 실패, 추가 확인 중 종료, 추가 확인 비활성의 4개 하위 사례를 검사한다. 수정 전 정상 재사용 사례가 실패했고 수정 후 전부 통과했다.
- 개발 검증: `build/wvd_py314_venv/Scripts/python.exe -B -X utf8 -m unittest tools.test_smart_disarm_state tools.test_runtime_guards` 46개 통과(상자 선택창 Open 우선 fixture 포함). `-B -X utf8 -u tools/test_smart_disarm_fixes.py` 감속·실패 재조준·커서 리셋 시나리오 전체 PASS. 런타임 수정은 `src/smart_disarm.py`에만 추가했으며 새 의존성은 없다.
- 배포본은 아래 09-05 빌드 상태 그대로이고 이번 재사용 수정은 소스에만 있다. 명시적인 다음 빌드·배포 요청을 받으면 먼저 `docs/build-and-release.md`를 읽고 별도 스테이징 및 사용자 데이터 보존 절차를 따른다. 다음 실기 검증에서는 재사용 로그·샘플 상한 폴백·상자 실제 처리 시간·종료 이미지를 함께 비교한다. 전체 최적화 목표를 완료로 표시하지 않았다.

## 2026-09-05 확인한 근거와 수정 (배포 완료 기록)

- `dist/wvd/logs`의 872회 호출, 959회 탭과 `dist/wvd/audit/smart_disarm`의 탭 이미지 722장·종료 이미지 599장을 분석했다.
- 밝은 배경이 안전구간과 반사 경계에 섞였다. `disarm_20260905_181016_1_unk.png`의 실제 두 노란 구간 사이 장식을 목표 x484로 탭한 기록이 대표 사례다. `detect()`를 900x1600 고정 게이지 내부 ROI `(16, 60, 881, 56)`로 제한했다. 색으로 반사 경계를 재계산하지 않는다. 기존 게임 좌표에 맞춘 경계 `(16, 896)`는 `DisarmConfig.bar_roi`로 조정 가능하다.
- 722장 재생에서 안전구간 3개 이상 오검출이 25장 → 0장이 됐다. 수정 후 722장 모두 두 구간을 검출했다. 저장 이미지에는 감사용 선이 포함되어 있으므로 이는 실기기 성공률 검증과 구분한다.
- 4점 검증이 가장 오래된 점만 확인해 중간점이 155px 어긋난 반전도 통과했다. `_est_consistent()`에서 최근 네 표본 전체를 확인한다. 과거 표본 재생에서 추가 배제된 추정 118건은 다음 프레임 오차 중앙값 97px, 유지된 525건은 45px였다. 이는 예측 검증이며 게임 성공률이 아니다.
- `log_260904-012305.txt`의 2026-09-05 19:32:52에 마지막 기회 1→1을 성공으로 확정했지만, `disarm_20260905_193237_end.png`에는 `Oops! Critical poison needle`이 보인다. 무차감만으로 성공 라벨을 붙이지 않도록 수정했다.
- 기존 성공 집계 617건은 무차감(미확정)이다. 차감 확정은 232건, 픽셀 차분 추정 실패는 78건이다. 종료 프레임도 보상 문구 후보 359장·미확정 240장으로 구분한다. 보상 문구 부재를 함정으로 단정하지 않는다.
- `tools/analyze_smart_disarm.py`: 실제 안전폭을 구조화 로그로 읽고, 서로 다른 로그 파일의 탭/판정을 연결하지 않으며, 무막대 중단 중복 집계를 제거했다. 모델 추정/게임 판정 이미지 파일명도 구분한다.
- 처음 작업 트리에 남아 있던 안전폭 50px·반주기 1.0s·통합 k=2.5 변경은 오염된 성공 지표로 정당화할 수 없었다. 기존 안전폭 100px·반주기 0.8s·통합 k=1.3을 유지한다. `src/script.py`의 실질 변경은 없다.
- 후속 턴에서 종료 이미지 599장도 게이지 검출기로 재생했다. 144장에 안전구간 후보, 그중 39장에 커서 후보도 있었다. 일부는 폴백 후에도 진행 중인 미니게임이므로 이 수치를 전부 오탐으로 세지 않는다. 보상 화면 `20260903_021014`와 던전 화면 `20260903_013437`에서는 실제 배경 오탐을 확인했다.
- 이 경우 첫 프레임의 `is_done` 판정이 색 검출에 가로막히던 조건을 제거했다. 두 원본 이미지와 실제 상자/결과 템플릿으로 `run()`을 재생했을 때 각각 캡처 1회·탭 0회·폴백 0회로 종료했다. 상자 표식 우선순위는 기존 종료 콜백에서 유지한다.
- 21:28 이후 재개에서 `plan_tap()`이 너무 이른 첫 교차를 건너뛸 때 반사 후 같은 구간으로 돌아오는 교차를 누락함을 확인했다. 기존 `_propagate()`로 실행 가능 시점까지 먼저 이동한 뒤 가장 가까운 교차를 고르게 단순화했다. 입력 지연·감속 리드·안전폭 기준은 변경하지 않았다.
- 오른쪽 진행 x650·속도 1000px/s·구간 중심 225/675·최소 도달 0.35초 사례에서 계획 도달 0.917초 → 0.467초, 왼쪽 진행도 대칭으로 개선된다. 양방향·여러 주기·실행 창 경계의 회귀 테스트는 수정 전 실패하고 수정 후 통과했다.
- 로그 추정값과 저장 탭 이미지가 연결되는 722건으로 계획 함수만 A/B 재생했다. 양쪽 모두 수정된 경계 `(16, 896)`와 이미지에서 읽은 안전구간을 사용했다. 최소 도달 시점을 0.5초로 가정했을 때 295건이 빨라졌고 해당 건 절약 중앙값은 0.529초, 나머지 427건은 동일했다. 최소 도달 0.35/0.65/0.8초 가정에서도 255/322/347건이 개선되고 악화는 없었다. 이는 가정한 실행 가능 시점의 계획 비교이며 실제 게임 처리 시간·성공률이 아니다.

## 2026-09-05 검증과 배포 기록

- 개발 검증: `build/wvd_py314_venv/Scripts/python.exe -X utf8 -m unittest discover -s tools -p test_smart_disarm_state.py` 20개 통과(첫 프레임 오탐·반사 후 재교차 회귀 포함).
- `test_runtime_guards.py` 같은 명령으로 25개 통과. 새 상자 선택창 이미지 fixture에서도 Open이 우선되고 dialogueNext 좌표는 조회되지 않는다.
- `build/wvd_py314_venv/Scripts/python.exe -X utf8 -u tools/test_smart_disarm_fixes.py`: 감속/재조준/리셋 커서 시나리오 전체 PASS. 반사 후 재교차 수정 후에도 전체 재실행해 통과했다. 첫 기본 Python 실행은 cp949 출력 인코딩 오류로 중단됐으며 UTF-8 재실행은 통과했다.
- 계획 도달 시점은 독립적인 펼친 왕복 경로 공식으로도 비교했다. 고정 seed 20260905의 난수 입력 10,000건(양방향·속도 80~2500px/s·최소 도달 0~8초·실행 창 0.05~2.6초) 모두 가장 이른 교차와 일치했다.
- `git diff --check` 통과. 커밋/push/PR은 하지 않았다.
- 전체 분석 실행: `python -X utf8 tools/analyze_smart_disarm.py --logs dist/wvd/logs --img dist/wvd/audit/smart_disarm`.
- 현재 배포본 `dist/wvd/wvd.exe`에는 이번 스마트 상자 수정이 적용됐다. 사용자 `진행해`로 빌드·배포 승인을 받은 뒤 `build/release-stage-20260905-214745`에서 새 빌드를 완료하고 `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 배포했다. 배포 전 WVD 프로세스는 없었고 새 exe를 실행하지 않았다.
- 배포 전후 `config.json`, `logs`, `audit`의 파일 1,335개(1,082,140,619바이트)에 대해 상대 경로·크기·SHA-256이 모두 일치했다. 디렉터리 목록도 동일했다. 보존 목록은 해당 스테이징의 `preservation-before.csv`, `preservation-after.csv`에 남겼다.
- 이전 프로그램 파일 세 항목은 `build/release-stage-20260905-214745/previous-deploy`에 보관했다. 삭제나 덮어쓰기로 제거하지 않았으며 새 실행 파일을 사용자가 확인할 때까지 유지한다.
- 스테이징 `build/release-stage-20260905-203411` 빌드는 실패했다. EXE 생성 후 COLLECT 단계에서 원본 exe 읽기가 `OSError: [Errno 22] Invalid argument`로 실패했고, 이후 해당 exe가 없음을 확인했다. 배포 가능한 산출물이 아니다.
- 원인은 Defender 격리다. Windows Defender Operational 이벤트 1116(20:34:48)·1117(20:35:03)에 `Trojan:Win32/Bearfoos.A!ml`, 대상 `build/release-stage-20260905-203411/work/wvd/wvd.exe`, 조치 `격리`가 기록됐다. 오탐 여부는 확인되지 않았다. 보호 설정이나 예외 목록은 변경하지 않았다.
- 21:47 새 빌드는 같은 문서의 Python 3.14 환경·`wvd.spec`으로 성공했다. 새 빌드 시작 이후 배포 직전까지 저장소 관련 Defender 1116/1117 이벤트는 없었다. 이전 탐지의 오탐 여부를 판정한 것은 아니며 격리 복원·보호 설정·예외 목록 변경은 하지 않았다. `Get-MpComputerStatus` 조회는 권한 거부로 실패해 보호 설정 전체 상태는 확인하지 못했다.
- 빌드는 문서의 Python 3.14 환경과 `wvd.spec`, 별도 dist/work 경로로 수행했다. PyInstaller 캐시도 `PYINSTALLER_CONFIG_DIR`를 통해 해당 스테이징 내부에 뒀다. 빌드 중 테스트·exe 실행·스모크·Tcl/Tk/리소스/해시 검증은 하지 않았다. 빌드·배포에는 최신 `docs/build-and-release.md`만 적용하며 아래 과거 Telegram 인계의 스모크 절차를 따라서는 안 된다.
- 빌드·배포 요청은 완료했지만 전체 최적화 목표는 아직 완료하지 않았다. 사용자가 새 배포본을 실행한 뒤 실제 상자 결과·처리 시간·폴백 빈도를 확인해야 한다. 이번 빌드·배포 단계에서는 문서대로 테스트·exe 실행·스모크·Tcl/Tk/리소스/프로그램 해시 검증을 하지 않았다. 배포 검증은 위 사용자 데이터 보존 확인만 수행했다.
- 첫 두 목표 턴은 소스 수정·회귀 검증·로그 재생을 수행한 progress다. 세 번째 턴에서 동일 빌드의 Defender 격리와 exe 부재, 새 상자 로그 부재를 다시 확인했다. 최신 상자 종료 기록은 여전히 2026-09-05 19:32:59이며, 실행 중인 PID 9156은 기존 배포본이다. 진행 중인 빌드나 수정본 검증 프로세스는 없다.
- 앞선 동일 차단 조건이 3개 연속 목표 턴에서 확인돼 목표를 `blocked`로 기록했었다. 완료로 판정한 것이 아니다.
- 사용자 `다음 진행해`로 21:28에 재개한 턴에서는 위 반사 후 교차 수정·회귀 검증을 수행했다. 이어 사용자 `진행해`를 받은 이번 턴은 새 스테이징 빌드·배포·사용자 데이터 보존 확인을 완료한 progress다. 기존 Defender 격리가 현재 빌드·배포를 계속 막는 상태라고 반복 보고하지 않는다.
- 실행을 하지 않았으므로 새 수정본의 실전 기록은 아직 없다. 마지막 확인한 로그의 20:23·21:23 추가분은 버전 확인뿐이며 상자 종료 기록은 19:32:59다. 다음 최적화 반복은 새 배포본의 실행 기록에서 시작한다. 과거 실패 빌드나 완료된 소스 검증·배포를 반복하지 않는다.

---

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
