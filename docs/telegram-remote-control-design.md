# 텔레그램 원격 정지·재개 기능 설계

- 문서 상태: 구현 기준 확정
- 작성일: 2026-08-12
- 대상 애플리케이션: WvDAS `2.5.4-momo.6` 이후
- 참고 사양: [Telegram Bot API](https://core.telegram.org/bots/api)

## 1. 목적

WvDAS가 실행 중일 때 허가된 텔레그램 개인 채팅에서 원격 명령을 받아 다음 동작을 수행한다.

1. `정지` 명령을 받으면 현재 전투 또는 상자 상호작용을 안전하게 마친다.
2. 던전 이동을 중단하고 마을로 돌아간다.
3. 게임을 타이틀 화면으로 이동시키되 WvDAS와 텔레그램 수신기는 계속 실행한다.
4. 이후 `동작` 명령을 받으면 게임 진입을 시도하고 최신 저장 설정의 매크로를 새 실행 세션으로 시작한다.

이 기능의 핵심은 기존 UI 정지와 다른 **안전 정지(graceful stop)** 경로를 제공하는 것이다. 기존 UI 정지는 `_FORCESTOPING` 이벤트를 통해 ADB 작업까지 즉시 중단하므로 마을 복귀와 타이틀 전환에 사용할 수 없다.

## 2. 확정된 제품 정책

| 항목 | 결정 |
| --- | --- |
| 텔레그램 수신 범위 | WvDAS 프로세스가 실행 중일 때만 수신 |
| 정지 중 WvDAS | 계속 실행 |
| 정지 후 게임 상태 | 마을 복귀 후 타이틀 화면에서 대기 |
| 안전 정지 시점 | 전투·상자 상호작용 완료 직후 |
| 전체 정지 제한 시간 | 명령 접수부터 600초 |
| 제한 시간 초과 | 게임 패키지를 강제 종료하고 실패 내용을 통지 |
| 재개할 설정 | 명령 수신 시점의 최신 저장 설정 |
| 허용 채널 | 설정된 개인 채팅 1개 |
| 명령 형식 | 슬래시 명령과 한국어 별칭 모두 지원 |
| 이전 명령 처리 | WvDAS 수신기 시작 전에 쌓인 업데이트는 폐기 |
| Bot Token 보관 | Git에서 제외된 로컬 `config.json`, UI에서는 마스킹 |

실제 게임 계정에서 로그아웃하거나 계정 ID·암호를 입력하는 기능은 포함하지 않는다. 여기서 로그인은 인증 세션이 유지된 게임의 `Tap to Start` 진입 절차를 뜻한다.

## 3. 범위

### 포함

- Telegram Bot API long polling 수신기
- 개인 채팅 및 채팅 ID 기반 명령 인증
- 원격 시작·안전 정지·상태 조회
- 텔레그램 단계별 결과 통지
- GUI 설정 및 연결 테스트
- 원격 명령과 GUI 작업 상태 동기화
- 던전, 전투, 상자, 지도, 마을, 타이틀 상태 전환
- 복귀 실패 시 게임 강제 종료 폴백
- GUI 모드와 헤드리스 모드 지원

### 제외

- WvDAS가 종료된 상태에서의 명령 수신
- Windows 서비스 또는 별도 상주 프로세스
- 그룹·채널에서의 제어
- 실제 계정 로그아웃 및 자격 증명 입력
- 여러 사용자 또는 여러 채팅 동시 허용
- 텔레그램을 통한 매크로 설정 변경
- 이미지·로그 파일 전송

## 4. 현재 구조와 제약

현재 `AppController`는 `(command, value)` 튜플을 `msg_queue`로 받아 작업 스레드를 시작하거나 중단한다. GUI의 시작 버튼은 저장 설정을 읽어 `start_quest`를 전송하며, 중지 버튼은 `stop_quest`를 전송한다.

작업 실행 중 `_FORCESTOPING`이 설정되면 `Sleep`, `DeviceShell`, 화면 인식 루프가 `TaskStoppedException`을 발생시킨다. 따라서 `_FORCESTOPING`을 먼저 설정하면 복귀용 ADB 입력도 실행할 수 없다.

기존 상태 머신에는 다음 재사용 지점이 있다.

- `IdentifyState`: 던전·지도·상자·전투·여관·도시 상태 판정
- `leaveDung`, `ReturnText`, `returntotown`: 던전 이탈 관련 템플릿(실제 파일 stem의 대소문자와 동일)
- 퀘스트별 `_RTT`: 월드맵에서 마을로 이동하는 경로
- `totitle`: 마을 종료 메뉴의 `To Title` 버튼 판정
- `ResetDevice`, `restartGame`: ADB 연결 및 게임 Activity 재실행

기존 `totitle`은 **타이틀 화면 표식이 아니라 `To Title` 동작 버튼**이다. `HandleSessionExpiry`는 이 버튼을 눌러 세션 만료 창을 처리하고, `IdentifyState`도 같은 버튼을 발견하면 누른 뒤 알 수 없는 시작 화면에서 중앙을 자동 터치한다. 따라서 원격 정지에서 `IdentifyState`를 그대로 호출하면 타이틀에 도착한 직후 다시 게임에 진입할 수 있다.

타이틀 전환은 `IdentifyState`, `HandleSessionExpiry`, `HandleBlockingOverlay`와 분리된 전용 판정 루프로 구현한다. ADB 원본 `900x1600` 화면에서 획득한 `resources/images/titlelogo.png`를 타이틀 확정 표식으로 사용한다. 깜빡이는 `resources/images/tabtostart.png`는 시작 좌표를 찾는 보조 표식으로만 사용하며, 보이지 않는 프레임에서는 검증된 고정 좌표를 누른다. 앱 재시작 직후의 `resources/images/startupDisclaimer.png`는 타이틀과 구분하고 한 번만 누른다.

## 5. 목표 아키텍처

```text
Telegram Bot API
       │ getUpdates / sendMessage
       ▼
TelegramCommandService ── telegram_command ──▶ AppController
       ▲                                             │
       │ outbound status                             │ start/stop event
       │                                             ▼
       └──────── task progress/result ◀────── Farm worker
                                                     │
                                                     ▼
                                              ADB / game UI
```

### 5.1 구현 디렉터리 계약

이 문서를 바탕으로 새로 작성하는 **모든 기능 본체, 테스트와 번역 파일은 저장소 루트의 `mod/telegram_remote_control/` 아래에 둔다.** 화면 템플릿은 기존 자동화 코드와 PyInstaller가 함께 사용하는 루트 `resources/images/`에 둔다. `src` 아래에 텔레그램 모듈이나 타이틀 전환 모듈을 새로 만들지 않는다.

```text
mod/
├── __init__.py                 # 로컬 기능 패키지 표시, 부작용 없음
├── README.md
└── telegram_remote_control/
    ├── __init__.py
    ├── constants.py             # 패키지·시간 제한·handoff 고정값
    ├── feature.py               # 기능 조립, 시작·종료, 컨트롤러 이벤트 처리
    ├── models.py                # 명령·상태·결과 Enum 및 dataclass
    ├── bot_api.py               # Telegram Bot API HTTPS 클라이언트
    ├── command_service.py       # long polling, 인증, 수신·송신 큐
    ├── recent_logs.py           # 최근 로그 시간 필터·크기 제한·비밀 마스킹
    ├── config.py                # 설정 키, 검증, 토큰 마스킹
    ├── adapters.py              # 기존 게임 자동화 함수의 호출 계약
    ├── settings_ui.py           # GUI 설정 영역과 연결 테스트
    ├── runtime_bridge.py        # Farm 안전 지점 이벤트 및 진행 통지
    ├── worker.py                # Farm 종료 결과를 정확히 한 번 큐에 전달
    ├── fallback.py              # 게임 강제 종료의 단일 실행·검증
    ├── return_to_town.py        # 안전 지점→마을 복귀 상태 머신
    ├── title_transition.py      # 마을→타이틀 전용 상태 머신
    ├── title_screen.py          # 시작 안내·타이틀 공통 화면 판정
    ├── stop_orchestrator.py     # 복귀·타이틀·종료 결과를 한 번에 조립
    ├── login_transition.py      # 타이틀/앱 종료 상태→게임 진입 상태 머신
    ├── i18n.py                  # 모듈 전용 gettext 로더
    ├── babel.cfg                # tests를 제외한 Python gettext 추출 규칙
    ├── locale/
    │   ├── telegram_remote_control.pot
    │   ├── ko_KR/LC_MESSAGES/
    │   │   ├── telegram_remote_control.po
    │   │   └── telegram_remote_control.mo
    │   ├── en_US/LC_MESSAGES/
    │   │   ├── telegram_remote_control.po
    │   │   └── telegram_remote_control.mo
    │   └── zh_CN/LC_MESSAGES/
    │       ├── telegram_remote_control.po
    │       └── telegram_remote_control.mo
    └── tests/
        ├── fixtures/            # 토큰·개인 정보가 없는 화면 픽스처
        ├── test_bot_api.py
        ├── test_commands.py
        ├── test_service.py
        ├── test_adapters.py
        ├── test_runtime_bridge.py
        ├── test_state_machine.py
        ├── test_title_transition.py
        ├── test_return_to_town.py
        ├── test_stop_orchestrator.py
        ├── test_login_transition.py
        ├── test_config.py
        ├── test_fallback.py
        ├── test_worker.py
        ├── test_i18n.py
        └── test_integration_hooks.py
```

기존 소스에는 기능 본체를 작성하지 않고 다음 **최소 연결 지점**만 수정한다.

| 기존 파일 | 허용되는 연결 변경 |
| --- | --- |
| `src/main.py` | 저장소 루트를 import 경로에 추가하고 `feature.py`의 시작·큐 처리·종료 훅 호출 |
| `src/gui.py` | `settings_ui.py`가 제공하는 설정 패널을 장착하고 저장·재구성 이벤트 전달 |
| `src/script.py` | `runtime_bridge.py`의 안전 정지 체크포인트 호출 및 기존 ADB/화면 함수를 adapter로 전달 |
| 빌드 설정 | 루트 `mod` import 경로와 모듈 전용 `resources`, `locale` 데이터 포함 |

연결 코드에는 Telegram HTTP 처리, 명령 파싱, 상태 전이, 타이틀 전환 알고리즘을 넣지 않는다. 기존 파일에서 10줄을 넘는 독립 로직이 필요하면 해당 로직을 `mod/telegram_remote_control/`로 옮기고 기존 파일에는 함수 호출만 남긴다.

`runtime_bridge.py`는 기존 `Factory` 내부 함수에 직접 의존하지 않고 19.7의 `GameAutomationAdapter`만 받는다. 이 adapter를 통해 로그인·복귀·타이틀 로직을 단위 테스트할 때 실제 ADB나 Tk를 실행하지 않는다.

개발 실행 시 `python src/main.py`에서도 루트 `mod` 패키지를 찾을 수 있도록 `src/main.py` 시작부에서 프로젝트 루트를 한 번만 `sys.path`에 추가한다. PyInstaller는 분석 경로에 저장소 루트를 추가하며, 런타임 리소스는 모듈 내부 helper가 개발 환경의 `Path(__file__).parent` 또는 frozen 환경의 `sys._MEIPASS/mod/telegram_remote_control`에서 찾는다.

### 5.2 `TelegramBotClient`

Telegram HTTPS 요청만 담당한다.

- `get_me()`: 토큰 검증
- `get_updates(offset, timeout, allowed_updates)`: long polling
- `send_message(chat_id, text)`: 상태 응답
- JSON 인코딩과 HTTP 오류 정규화
- 모든 오류 문자열에서 Bot Token 제거
- `certifi` CA 번들로 TLS 서버 인증서를 검증하고 인증서 검증 비활성화는 허용하지 않음

HTTP와 JSON 처리는 표준 라이브러리 `urllib.request`와 `json`으로 구현하고, 신뢰할 CA 목록만 `certifi`에서 제공받는다.

### 5.3 `TelegramCommandService`

daemon 스레드에서 수신·송신 큐를 관리한다.

- 활성화 시 이전 업데이트 폐기
- `message.text`만 처리하고 편집 메시지·미디어·봇 메시지는 무시
- 개인 채팅과 허용 채팅 ID 검증
- 텍스트를 `RemoteCommand`로 변환
- 유효 명령을 Tk 메인 큐에 전달
- 응답 전송은 별도 outbound 큐에서 수행
- 네트워크 장애 시 매크로 스레드와 독립적으로 재접속

### 5.4 `AppController`

`AppController`는 작업 스레드와 `TelegramRemoteFeature`의 단일 소유자다. canonical `ControlState` 값은 feature가 보관하되, 변경 메서드는 AppController의 Tk 메인 큐에서만 호출한다.

- GUI와 텔레그램에서 들어온 시작 요청을 동일한 시작 함수로 처리
- 작업 스레드가 이미 존재하면 중복 시작 차단
- 원격 정지 이벤트 설정 및 진행 상태 관리
- 작업 진행 이벤트를 GUI와 텔레그램에 반영
- 최신 설정과 실행 시 전달된 `-config` 경로를 일관되게 사용
- 앱 종료 시 텔레그램 수신기 종료 요청

### 5.5 Farm 작업 스레드

기존 즉시 중단 이벤트와 별도로 원격 안전 정지 이벤트를 받는다.

- `_FORCESTOPING`: 로컬 UI의 즉시 중단 및 비상 중단
- `_REMOTE_RUNTIME.stop_event`: 안전 지점에서 처리할 원격 정지 요청
- `_START_REASON`: `LOCAL` 또는 `TELEGRAM`
- 작업 완료 시 `TaskExitReason`을 포함한 결과 이벤트 전송

## 6. 상태 모델

```text
IDLE ── start ──▶ STARTING ── ready ──▶ RUNNING
  ▲                  │                     │
  │                  └── stop ─────────────┤
  │                                        ▼
  │                                STOP_REQUESTED
  │                                        │ safe checkpoint
  │                                        ▼
  │                              RETURNING_TO_TOWN
  │                                        │ town confirmed
  │                                        ▼
  │                              RETURNING_TO_TITLE
  │                                        │ title confirmed
  │                                        ▼
  └──────────── start 이후 재진입 ─────── AT_TITLE

정지 실패 ──▶ GAME_STOPPED_FALLBACK
기타 복구 불가 오류 ──▶ ERROR
```

### 상태 정의

| 상태 | 의미 |
| --- | --- |
| `IDLE` | 매크로 스레드가 없고 게임 상태는 확정하지 않음 |
| `STARTING` | ADB 연결, 게임 시작, 타이틀 진입 또는 최초 상태 확인 중 |
| `RUNNING` | 설정된 매크로 수행 중 |
| `STOP_REQUESTED` | 원격 정지를 접수하고 안전 지점을 기다리는 중 |
| `RETURNING_TO_TOWN` | 던전 이탈 및 마을 이동 중 |
| `RETURNING_TO_TITLE` | 마을 확인 후 타이틀 전환 중 |
| `AT_TITLE` | 타이틀 화면을 2회 연속 확인하고 매크로가 종료된 상태 |
| `GAME_STOPPED_FALLBACK` | 안전 정지 실패 후 게임 패키지를 강제 종료한 상태 |
| `ERROR` | 자동 복구할 수 없는 설정·ADB·로그인 오류 상태 |

상태 변경은 `AppController`의 메인 큐에서 `TelegramRemoteFeature`가 직렬 처리한다. 텔레그램 스레드나 Farm 스레드는 canonical 상태 값을 직접 변경하지 않고 명령·진행 이벤트만 큐에 넣는다.

## 7. 텔레그램 명령 계약

### 7.1 지원 명령

| 정규 명령 | 별칭 | 동작 |
| --- | --- | --- |
| `/stop` | `정지` | 원격 안전 정지 요청 |
| `/start` | `동작` | 최신 저장 설정으로 새 실행 시작 |
| `/status` | `상태` | UI 메시지의 최근 60초 조회 |
| `/stat`, `stat` | 없음 | UI 메시지의 최근 60초 조회 |
| `/menu`, `menu` | `메뉴` | 지원 명령 목록 조회 |

앞뒤 공백은 제거하고 슬래시 명령은 대소문자를 구분하지 않는다. 개인 채팅에서 `/start@bot_name` 형태가 들어오면 `@bot_name`을 제거한 뒤 판정한다. 한국어 별칭은 완전히 일치할 때만 허용한다.

### 7.2 명령별 상태 처리

| 현재 상태 | `/stop` | `/start` |
| --- | --- | --- |
| `RUNNING`, `STARTING` | 안전 정지 접수 | 이미 실행 중 응답 |
| `STOP_REQUESTED`, `RETURNING_TO_TOWN`, `RETURNING_TO_TITLE` | 처리 중 응답 | 정지 완료 후 다시 요청하도록 응답 |
| `AT_TITLE`, `GAME_STOPPED_FALLBACK`, `IDLE` | 이미 정지됨 응답 | 실행 시작 |
| `ERROR` | 이미 정지됨 응답 | 설정 재검증 후 재시도 |

알 수 없는 명령은 허가된 채팅에만 `menu`를 입력하라는 안내를 응답한다. 명령 목록 전체는 `menu`에서만 제공한다. 비허가 채팅에는 어떠한 응답도 보내지 않는다.

### 7.3 상태 응답

`/status`와 `/stat` 응답에는 UI 로그 창과 같은 메시지 본문만 최근 60초 순서로 포함한다. 파일 formatter의 시각·레벨·모듈 접두사는 제거하고 `INFO` 이상만 보낸다. 메시지 자체가 여러 줄이면 연속 줄을 유지한다.

Bot Token, 전체 설정 경로, ADB 명령 출력, 스택 트레이스는 포함하지 않는다.

`status`와 `stat`은 실행 디렉터리의 `logs`에서 수정 시각이 가장 최신인 `log_*.txt`를 현재 로그로 선택한다. 각 레코드의 `YYYY-MM-DD HH:MM:SS` 시각을 기준으로 요청 시점 직전 60초만 포함하고, traceback 같은 연속 줄은 앞 레코드의 시각을 상속한다. 파일 읽기는 끝부분 512 KiB로 제한하며 Telegram 응답은 헤더를 보존한 채 3,900자 이하의 최신 줄로 제한한다. 잘린 경우 그 사실을 응답에 표시한다. 설정된 Bot Token·허용 Chat ID와 token 형태 문자열은 전송 전에 마스킹한다. 최근 기록이 없으면 `최근 60초 내 UI 메시지가 없습니다.`를 응답한다.

`menu`는 `/start`, `/stop`, `/status`, `stat`, `menu`와 한국어 별칭의 설명을 반환한다.

## 8. 설정과 GUI

`CONFIG_VAR_LIST`의 `GENERAL` 범주에 다음 값을 추가한다.

| 키 | 타입 | 기본값 | 설명 |
| --- | --- | --- | --- |
| `TELEGRAM_ENABLED` | Boolean | `False` | 텔레그램 수신기 사용 여부 |
| `TELEGRAM_BOT_TOKEN` | String | `""` | BotFather에서 발급한 토큰 |
| `TELEGRAM_ALLOWED_CHAT_ID` | String | `""` | 허용할 개인 채팅 ID |

채팅 ID는 32비트 범위를 넘을 수 있으므로 설정에는 문자열로 저장하고, 숫자 문자열로 정규화한 뒤 비교한다. 세 값은 작업별 설정에 복사하지 않고 항상 `GENERAL`에 저장한다.

GUI에는 접을 수 있는 `텔레그램 원격 제어` 영역을 추가한다.

- 사용 여부 체크박스
- Bot Token 입력: `show="*"` 적용
- 허용 Chat ID 입력
- `연결 테스트` 버튼
- 현재 연결 상태 레이블

연결 테스트는 UI 스레드를 막지 않고 다음을 순서대로 수행한다.

1. `getMe`로 토큰 유효성 확인
2. 설정된 채팅 ID로 테스트 메시지 전송
3. 성공·실패를 GUI에 표시

설정을 저장하면 `telegram_reconfigure` 이벤트를 컨트롤러에 보내 기존 수신기를 안전하게 중단하고 새 설정으로 다시 시작한다. 토큰 또는 Chat ID가 비어 있으면 활성화를 거부하되 로컬 매크로 기능은 정상 유지한다.

## 9. 수신, 인증 및 보안

### 9.1 long polling

- `getUpdates`의 `timeout`은 25초로 사용한다.
- HTTP 읽기 제한은 long polling보다 긴 35초로 설정한다.
- `allowed_updates`는 `["message"]`로 제한한다.
- 각 응답에서 가장 큰 `update_id + 1`을 다음 `offset`으로 사용한다.

수신기 시작 시 `offset=-1`, `timeout=0`으로 마지막 대기 업데이트를 읽되 실행하지 않는다. 반환된 마지막 `update_id + 1`부터 정상 polling을 시작하여 WvDAS 실행 전 명령을 모두 폐기한다. Telegram은 `getUpdates`의 높은 `offset`으로 이전 업데이트를 확인 처리한다.

기존 webhook이 설정되어 `getUpdates`가 충돌하면 webhook을 자동 삭제하지 않는다. 텔레그램 기능을 오류 상태로 두고 전용 Bot을 사용하거나 webhook을 해제하라는 안내를 표시한다.

### 9.2 인증

명령을 실행하려면 다음 조건을 모두 만족해야 한다.

1. `message.chat.type == "private"`
2. `message.chat.id`가 `TELEGRAM_ALLOWED_CHAT_ID`와 일치
3. `message.from`이 객체이고 `message.from.is_bot is False`
4. 새 `message` 업데이트이며 `edited_message`가 아님
5. 지원하는 텍스트 명령임

### 9.3 토큰 보호

- `config.json`은 현재처럼 Git에서 제외한다.
- 토큰을 logger 인자, URL 로그, 예외 메시지, 텔레그램 답변에 넣지 않는다.
- HTTP 예외를 기록하기 전에 토큰 문자열과 `/bot<token>/` 구간을 마스킹한다.
- `repr(config)` 또는 전체 설정 덤프를 로그로 남기지 않는다.
- 비허가 메시지 본문과 Chat ID는 로그에 남기지 않고 거부 횟수만 debug 수준에서 기록한다.

## 10. 안전 정지 상세 흐름

### 10.1 요청 접수

1. 컨트롤러가 600초 제한 타이머를 시작한다.
2. 현재 작업의 `_REMOTE_RUNTIME.request_stop()`을 호출해 stop event와 deadline을 설정한다.
3. 상태를 `STOP_REQUESTED`로 변경한다.
4. 텔레그램에 `안전 정지 요청을 접수했습니다.`를 전송한다.

이 시점에는 `_FORCESTOPING`을 설정하지 않는다.

### 10.2 안전 지점 진입

`remote_stop_checkpoint`를 다음 위치에 둔다.

- `DungeonFarm`의 바깥 상태 루프
- `StateDungeon`이 `DungeonState.Dungeon`으로 안정된 직후
- 상자 개봉 결과창 처리가 끝나 던전 화면으로 돌아온 직후
- 전투 후 던전·상자 상태가 확정된 직후
- `QuestFarm` 각 작업의 바깥 반복과 `RestartableSequenceExecution` 작업 묶음 사이
- 여관·도시·월드맵 상태를 확인한 직후

전투 또는 상자 상태에서는 이벤트를 확인하더라도 현재 원자적 상호작용을 중단하지 않는다. 지도 상태에서는 Android Back으로 지도부터 닫고 `dungFlag`를 확인한다. 안전 지점이 확인되면 일반 매크로 흐름을 `GracefulStopSignal`로 빠져나와 전용 복귀 흐름으로 이동한다.

기존 화면 정지 감지와 게임 재시작 보호는 안전 지점을 기다리는 동안 계속 동작한다. 단, 재시작 후에도 원격 정지 이벤트는 유지하며 매크로 경로로 복귀하지 않고 안전 지점 탐색을 계속한다.

### 10.3 마을 복귀

상태별 동작은 다음과 같다.

| 감지 상태 | 처리 |
| --- | --- |
| `Inn` 또는 도시 표식 | 복귀 완료로 처리 |
| `mapFlag` | Android Back 후 `dungFlag` 확인 |
| `dungFlag` | `leaveDung`으로 이동 메뉴를 열고 `ReturnText` 선택 |
| `returntotown` | 마을 복귀 항목을 선택하고 결과 상태 재확인 |
| `openworldmap`, `worldmapflag` | 퀘스트 `_RTT`로 마을 이동 |
| 알 수 없는 상태 | 모달·재시도 처리 후 제한된 횟수만 재판정 |

일반 `IdentifyState`의 `ACTIVE_REST` 조건은 원격 정지에 적용하지 않는다. 원격 정지는 여관 휴식 사용 여부와 관계없이 반드시 마을 이동을 시도한다.

성공 조건은 `Inn` 또는 지원 도시 표식 중 하나가 연속 2회 검출되는 것이다. `_RTT`가 없는 특수 작업은 화면의 `returntotown` 경로를 우선 사용하고, 실패하면 전체 제한 시간 폴백으로 처리한다.

### 10.4 타이틀 전환

마을에서 타이틀로 이동하는 동작은 `return_town_to_title(adapter, runtime)` 함수 하나가 소유한다. 이 함수는 `runtime.stop_deadline_monotonic`을 전체 상한으로 사용하고 일반 매크로 상태 판정기를 호출하지 않는다.

```python
class TitleTransitionPhase(Enum):
    VERIFY_TOWN = "verify_town"
    OPEN_EXIT_MENU = "open_exit_menu"
    WAIT_FOR_TITLE = "wait_for_title"

class TitleTransitionScreen(Enum):
    TITLE = "title"
    TO_TITLE_BUTTON = "to_title_button"
    TOWN = "town"
    LOADING = "loading"
    RETRY_DIALOG = "retry_dialog"
    UNKNOWN = "unknown"
```

공개 반환값은 19.3의 `TransitionOutcome`을 사용한다. `TitleTransitionPhase`와 `TitleTransitionScreen`은 `title_transition.py` 내부 구현 열거형이다.

#### 10.4.1 화면 판정 우선순위

`classify_title_transition_screen(adapter, screen)`은 다음 순서로 단 한 가지 상태만 반환한다.

1. 안정적인 `titlelogo`가 보이면 `TITLE`
2. 기존 `totitle` 버튼이 보이면 `TO_TITLE_BUTTON`
3. `abyssReadying`, 검은 프레임 또는 화면 평균 밝기 기반 로딩이면 `LOADING`
4. 기존 네트워크 `retry`가 보이면 `RETRY_DIALOG`
5. `Inn` 또는 지원 도시 표식이 보이면 `TOWN`
6. 나머지는 `UNKNOWN`

`TO_TITLE_BUTTON`을 `TOWN`보다 먼저 검사한다. 종료 메뉴가 마을 화면 위에 겹쳐 표시되면 배경의 도시 표식도 동시에 인식될 수 있기 때문이다.

템플릿 판정 조건은 다음으로 고정한다.

| 표식 | 검색 범위 | 임계값 | 추가 조건 |
| --- | --- | --- | --- |
| `totitle` | 우선 `[300, 820, 300, 170]`, 실패 시 중앙 대화창 `[180, 650, 540, 500]` | 첫 ROI `0.86`, 확장 ROI `0.92` | 중앙 대화창 밖 일치는 거부 |
| `titlelogo` | 화면 상단 60% | `0.88` | 0.5초 간격 2회 연속 일치 시 타이틀 확정 |
| `tabtostart` | 화면 하단 50% | `0.88` | 시작 입력 좌표용 보조 표식이며 타이틀 확정에는 불필요 |
| `Inn`, 도시 표식 | 기존 ROI | 기존 `0.80` | 0.5초 간격 2회 연속 일치 |

타이틀 성공은 `TITLE` 판정이 0.5초 이상의 간격으로 2회 연속 나왔을 때만 확정한다. 중간에 다른 상태가 나오면 연속 횟수를 0으로 되돌린다. 타이틀 판정 루프에서는 어떠한 중앙 터치나 `[1, 1]` 탭도 실행하지 않는다.

#### 10.4.2 단계별 알고리즘

1. 컨트롤러 상태를 `RETURNING_TO_TITLE`로 변경하고 텔레그램에 마을 복귀 완료를 통지한다.
2. `VERIFY_TOWN`에서 `Inn` 또는 도시 표식을 0.5초 간격으로 2회 확인한다.
3. `OPEN_EXIT_MENU`에서 Android `KEYCODE_BACK`을 한 번 전송하고 2초 동안 화면 변화를 기다린다.
4. `TO_TITLE_BUTTON`이 보이면 버튼 중심을 한 번만 누르고 `WAIT_FOR_TITLE`로 이동한다.
5. Back 이후에도 `TOWN`이 유지되면 하위 마을 패널이 한 단계 닫힌 것으로 보고 1초 후 Back을 다시 보낸다. Back 입력은 최대 3회다.
6. `WAIT_FOR_TITLE`에서는 검은 화면과 `abyssReadying`을 정상 로딩으로 처리하고 입력 없이 기다린다.
7. `RETRY_DIALOG`만 예외적으로 기존 `TryPressRetry`로 처리한다. 일반 `OK`, `close`, `dialogueNext` 또는 화면 중앙을 추측해서 누르지 않는다.
8. 타이틀을 2회 연속 확인하면 `AT_TITLE`을 반환한다.

단계별 제한은 다음과 같다. 모든 제한은 원격 정지 접수 시 계산한 600초 `overall_deadline`을 넘을 수 없다.

| 단계 | 제한 |
| --- | --- |
| 마을 안정 확인 | 10초 |
| 종료 메뉴 열기 및 `To Title` 탐색 | 30초, Back 최대 3회 |
| `To Title` 클릭 후 타이틀 로딩 | 120초 |

동일 버튼을 연속으로 누르지 않도록 마지막 입력 종류·좌표·시각을 기록한다. 같은 좌표 입력은 화면 판정 상태가 바뀌거나 2초가 지나기 전에는 다시 보내지 않는다.

#### 10.4.3 의사 코드

```python
def return_town_to_title(adapter, runtime):
    overall_deadline = runtime.stop_deadline_monotonic
    if overall_deadline is None:
        return TransitionOutcome(
            TransitionStatus.ERROR,
            "원격 정지 제한 시간이 설정되지 않았습니다.",
            "missing_stop_deadline",
        )
    phase = TitleTransitionPhase.VERIFY_TOWN
    back_attempts = 0
    title_reopen_used = False
    stable_town_frames = 0
    stable_title_frames = 0
    last_screen = None
    phase_deadline = min(overall_deadline, monotonic() + 10)

    while monotonic() < overall_deadline:
        if adapter.local_stop_requested():
            return TransitionOutcome(TransitionStatus.LOCAL_ABORT)
        if runtime.is_timeout_fallback_started():
            return force_stop_game_once(adapter, runtime, failure_phase=phase.value)

        screen = adapter.screenshot()
        last_screen = screen
        state, action_pos = classify_title_transition_screen(adapter, screen)

        # 세션 만료 등으로 이미 타이틀에 도착했다면 어느 단계에서든 성공시킨다.
        if state is TitleTransitionScreen.TITLE:
            stable_title_frames += 1
            if stable_title_frames >= 2:
                return TransitionOutcome(TransitionStatus.AT_TITLE)
            adapter.sleep(0.5)
            continue
        stable_title_frames = 0

        if state is TitleTransitionScreen.RETRY_DIALOG:
            adapter.try_press_retry(screen)
            adapter.sleep(0.5)
            continue

        if phase is TitleTransitionPhase.VERIFY_TOWN:
            stable_town_frames = (
                stable_town_frames + 1
                if state is TitleTransitionScreen.TOWN
                else 0
            )
            if stable_town_frames >= 2:
                phase = TitleTransitionPhase.OPEN_EXIT_MENU
                phase_deadline = min(overall_deadline, monotonic() + 30)
                continue

        elif phase is TitleTransitionPhase.OPEN_EXIT_MENU:
            if state is TitleTransitionScreen.TO_TITLE_BUTTON:
                adapter.press(action_pos)
                phase = TitleTransitionPhase.WAIT_FOR_TITLE
                phase_deadline = min(overall_deadline, monotonic() + 120)
                continue
            if (
                state is TitleTransitionScreen.TOWN
                and back_attempts < 3
                and input_cooldown_elapsed()
            ):
                adapter.press_back()
                back_attempts += 1
                adapter.sleep(2)
                continue

        elif phase is TitleTransitionPhase.WAIT_FOR_TITLE:
            if state is TitleTransitionScreen.TOWN and not title_reopen_used:
                title_reopen_used = True
                phase = TitleTransitionPhase.OPEN_EXIT_MENU
                phase_deadline = min(overall_deadline, monotonic() + 30)
                continue
            if state is TitleTransitionScreen.LOADING:
                adapter.sleep(0.75)
            # UNKNOWN에서는 오입력을 피하고 화면만 다시 확인한다.

        if monotonic() >= phase_deadline:
            break
        adapter.sleep(0.5)

    if last_screen is not None:
        adapter.save_failure_frame(last_screen, phase.value)
    return force_stop_game_once(adapter, runtime, failure_phase=phase.value)
```

실제 구현에서는 위 의사 코드의 생략된 clock과 input cooldown helper를 constructor 기본 인자로 주입 가능하게 만들며, `phase_deadline`이 단계 전환마다 반드시 갱신되는지 단위 테스트한다. loop 전체에서 `adapter.local_stop_exception_type`만 잡아 `LOCAL_ABORT`로 반환하고 `RemoteRecoverySuppressed`는 다시 발생시킨다.

#### 10.4.4 기존 코드와의 격리 규칙

- 이 흐름에서 `IdentifyState()`를 호출하지 않는다.
- `HandleSessionExpiry()`를 호출하지 않는다. `totitle` 버튼 클릭은 이 상태 머신만 수행한다.
- `HandleBlockingOverlay()`를 호출하지 않는다. 종료 메뉴 자체를 차단 모달로 오판해 닫을 수 있기 때문이다.
- 기존 `totitle.png`는 파일을 유지하되 코드상 의미를 `TO_TITLE_BUTTON`으로 명확히 명명한다.
- `quit.png`는 특정 퀘스트 대화 선택지에 쓰일 수 있으므로 종료 메뉴 판정에 재사용하지 않는다.
- `TransitionStatus.AT_TITLE`이 반환되기 전에는 정상 완료용 `_FINISHINGCALLBACK`을 호출하지 않는다.
- 원격 정지 이벤트는 ADB 입력을 막지 않는다. 로컬 `_FORCESTOPING`만 전환 루프를 즉시 중단한다.

#### 10.4.5 예외 화면 처리

- 세션 만료로 이미 타이틀에 도착한 경우 마을 복귀를 더 시도하지 않고 `AT_TITLE`로 완료하되, 텔레그램에는 `세션이 먼저 종료되어 타이틀에서 정지했습니다.`라고 알린다.
- Back을 눌렀는데 종료 메뉴가 아닌 마을 하위 패널이 닫히면 `TOWN` 재검출 후 다음 Back을 보낸다.
- `To Title` 버튼을 누른 뒤 다시 마을이 보이면 클릭이 반영되지 않은 것으로 보고 `OPEN_EXIT_MENU`로 한 번만 되돌아간다. 전체 Back 횟수는 초기화하지 않는다.
- 확인되지 않은 `OK`나 `Close` 버튼은 누르지 않는다. 30초 내 `To Title`을 확인하지 못하면 실패 프레임을 저장하고 폴백한다.
- 타이틀 로딩 중 검은 화면은 120초 동안 기다리되 화면 탭을 보내지 않는다.

#### 10.4.6 완료 처리

성공하면 Farm 스레드는 `TaskFinishedPayload(reason=REMOTE_STOP, detail="at_title")`을 메인 큐에 넣고 반환한다. `AppController`가 이를 받아 다음 순서로 한 번만 처리한다.

1. `quest_threading` 종료 여부 확인
2. `ControlState.AT_TITLE` 설정
3. GUI 시작 버튼을 시작 상태로 변경하고 설정 컨트롤 활성화
4. 실행 중 매크로 참조 해제
5. 종료 작업의 매크로 이름, 정지 요청 시각, 완료 시각과 소요 시간을 확정
6. 텔레그램 완료 알림을 우선순위 송신 큐에 등록

텔레그램 수신기와 Tk 메인 루프는 종료하지 않는다.

완료 알림은 다음 형식으로 보낸다.

```text
✅ 종료 작업 완료
상태: 마을 복귀 후 타이틀 화면 대기
매크로: {farm_target_text}
소요 시간: {elapsed_mm_ss}
```

`종료 작업 완료` 알림은 다음 조건을 모두 만족한 이후에만 등록한다.

1. 타이틀 화면이 2회 연속 확인됨
2. Farm 스레드가 더 이상 실행 중이지 않음
3. `ControlState`가 `AT_TITLE`로 반영됨
4. GUI가 정지 상태로 동기화됨

타이틀 확인 전의 접수·진행 메시지에는 `완료`라는 표현을 사용하지 않는다. 세션 만료 때문에 마을 복귀가 생략된 경우에는 상태 줄을 `세션 종료로 타이틀 화면 대기`로 바꾼다.

완료 알림에는 실행별 고유 키 `remote-stop-complete:{run_id}`를 부여한다. `TelegramCommandService`는 이 키를 기준으로 중복된 `task_finished` 이벤트나 컨트롤러 큐 재처리가 발생해도 한 번만 전송한다.

완료 알림은 일반 진행 메시지보다 높은 `TERMINAL` 우선순위를 갖는다. 일시적인 네트워크 오류가 발생하면 메모리의 pending 알림을 유지하고 기존 1·2·5·10·30초 백오프로 전송 성공 시까지 재시도한다. 재시도는 명령 수신 long polling을 막지 않는 outbound 송신 루프에서 수행한다. HTTP 401·403처럼 재시도로 해결되지 않는 오류는 GUI와 로그에 `완료 알림 전송 실패`로 표시하되 성공한 것처럼 기록하지 않는다.

강제 종료 폴백에는 성공 알림을 보내지 않고 다음과 같이 명확히 구분한다.

```text
⚠️ 종료 작업 비정상 완료
상태: 안전 복귀 실패 후 게임 강제 종료
실패 단계: {failure_phase}
매크로: {farm_target_text}
```

### 10.5 실패 폴백

600초가 지나거나 복귀 흐름에서 복구 불가 오류가 발생하면 다음 순서를 사용한다.

1. 안전 종료 전용 ADB 경로로 `am force-stop jp.co.drecom.wizardry.daphne` 실행
2. Farm 스레드를 `REMOTE_STOP_FALLBACK` 결과로 종료
3. 상태를 `GAME_STOPPED_FALLBACK`으로 변경
4. GUI를 정지 상태로 동기화
5. 텔레그램에 실패 단계와 게임 강제 종료 사실을 통지

게임 패키지를 중단한 후에만 작업 중단 이벤트를 확정한다. `_FORCESTOPING` 때문에 `am force-stop` 자체가 차단되어서는 안 된다.

## 11. 원격 재개 상세 흐름

### 11.1 시작 전 검증

`/start`를 받으면 컨트롤러가 다음을 확인한다.

1. 기존 Farm 스레드가 살아 있지 않음
2. 정지 처리 상태가 아님
3. 최신 설정 파일을 읽을 수 있음
4. `FARM_TARGET`, ADB 주소, 에뮬레이터 설정이 유효함
5. 작업 시작 함수가 한 번만 호출됨

헤드리스 실행에서 지정된 `-config` 경로가 있으면 그 파일에서, GUI 실행이면 기존 `CONFIG_FILE`에서 다시 읽는다. 정지 당시의 `FarmConfig` 객체는 재사용하지 않는다.

### 11.2 게임 진입

1. 상태를 `STARTING`으로 변경한다.
2. 새 `FarmConfig`, `_FORCESTOPING`, `RemoteRuntime`을 만든다.
3. ADB 장치를 연결하고 게임 패키지 실행 여부를 확인한다.
4. 게임이 강제 종료된 상태면 Activity를 조회해 `am start`한다.
5. `startupDisclaimer`가 보이면 중심을 정확히 한 번 누르고, 화면이 바뀔 때까지 추가 입력하지 않는다.
6. `titlelogo`가 보이면 타이틀로 판정한다. `tabtostart`가 보이면 그 중심을 누르고, 깜빡임으로 보이지 않으면 검증된 고정 좌표 `(450, 1367)`을 누른다.
7. 다운로드·네트워크 재시도·세션 종료처럼 기존 템플릿으로 명확히 확인된 시작 화면만 처리한다.
8. `Inn`, 도시, 던전 중 하나를 확인하면 로그인 완료로 판정한다.

한 번의 로그인 준비 제한은 180초다. 실패하면 게임 패키지를 한 번 재시작하고 다시 180초 동안 시도한다. 두 번째 시도도 실패하면 Farm 스레드를 만들지 않거나 종료하고 `ERROR`로 전환한다.

### 11.3 매크로 재시작

게임 상태가 확인되면 새 `RuntimeContext`로 매크로를 시작한다.

- 이전 실행 횟수·전투 전략 진행률·상자 통계는 이어받지 않는다.
- 선택된 퀘스트와 옵션은 최신 저장 설정을 사용한다.
- 상태를 `RUNNING`으로 변경한다.
- GUI는 실행 버튼을 `정지`로 바꾸고 설정 컨트롤을 비활성화한다.
- 텔레그램에 실제 시작한 매크로 이름을 통지한다.

## 12. 내부 타입과 큐 이벤트

### 12.1 열거형

열거형의 정확한 상속과 전체 항목은 19.3을 사용한다. 문자열 직렬화가 필요한 상태·명령·종료 사유는 `str, Enum`, 우선순위는 `IntEnum`으로 구현한다.

### 12.2 메시지 페이로드

메시지 dataclass의 정확한 필드와 타입은 19.3을 사용한다. 모든 작업 이벤트에는 `run_id`를 포함해 이전 작업의 늦은 이벤트가 현재 작업 상태를 변경하지 못하게 한다.

### 12.3 메인 큐 이벤트

| 이벤트 | 생산자 | 소비자 | 용도 |
| --- | --- | --- | --- |
| `telegram_command` | Telegram 서비스 | `AppController` | 시작·정지·상태·최근 로그·메뉴 명령 |
| `telegram_reconfigure` | GUI | `AppController` | 수신기 설정 갱신 |
| `telegram_test_connection` | GUI | `AppController` | 현재 입력값으로 일회성 연결 시험 |
| `telegram_test_result` | 연결 시험 worker | `AppController` | 연결 시험 결과 표시 |
| `telegram_service_status` | Telegram 서비스 | `AppController` | 연결·재시도·영구 오류 상태 표시 |
| `remote_progress` | Farm 스레드 | `AppController` | 복귀 단계 변경 |
| `task_completion_requested` | Farm 스레드 | `AppController` | worker 종료 확인 시작 |
| `task_finished` | `AppController` | Telegram feature | worker 종료가 확인된 최종 결과 |

Farm 스레드는 Tk 위젯을 직접 호출하지 않는다. 작업 종료 콜백은 반드시 메인 큐를 거쳐 한 번만 처리한다.

## 13. 동시성 및 우선순위

- 작업 스레드는 최대 하나만 존재한다.
- `AppController`가 시작 요청을 원자적으로 승인하고 스레드 참조를 먼저 기록한다.
- `/start`와 GUI 시작이 동시에 들어와도 두 번째 요청은 거절한다.
- 원격 정지 중 `/start`는 큐에 예약하지 않고 거절한다.
- 로컬 UI 정지는 비상 중단으로 간주하여 안전 정지를 즉시 취소할 수 있다.
- 로컬 즉시 중단으로 복귀가 취소되면 텔레그램에 `로컬 중지로 안전 복귀가 취소되었습니다.`를 통지한다.
- WvDAS 종료 시 polling 중단 이벤트를 설정한다. long polling 제한 후 daemon 스레드는 자연 종료한다.

## 14. 오류 및 재시도 정책

### 텔레그램 네트워크

- 재시도 간격: 1초, 2초, 5초, 10초, 이후 최대 30초
- 성공한 요청이 한 번 발생하면 백오프 초기화
- 네트워크 장애 때문에 Farm 작업을 중단하지 않음
- 전송 실패 메시지는 outbound 큐에 무기한 쌓지 않고 최신 상태 메시지를 우선
- HTTP 401은 토큰 오류로 보고 자동 재시도를 중단
- HTTP 409는 webhook 충돌로 보고 설정 오류 표시
- HTTP 429는 `retry_after`를 우선 적용
- TLS 인증서 오류는 검증 코드만 기록하고 URL·토큰·인증서 본문은 기록하지 않음

### ADB 및 게임 상태

- 기존 `ResetDevice` 복구 정책 재사용
- 안전 정지 제한 시간 동안 게임 재시작이 발생해도 정지 요청 유지
- 마을·타이틀 상태는 단일 프레임이 아니라 2회 연속 확인
- 원격 시작 로그인 실패는 게임 재시작 1회를 포함해 최대 2회 시도

## 15. 로깅과 로케일

다음 이벤트는 일반 로그에 남긴다.

- 텔레그램 수신기 시작·중단·재연결
- 허가된 명령 종류와 처리 결과
- 제어 상태 전환
- 안전 지점 대기, 마을 복귀, 타이틀 전환
- 제한 시간 초과와 게임 강제 종료

명령 원문, Bot Token, 전체 Telegram API URL, 비허가 Chat ID는 기록하지 않는다.

새 GUI 문자열, 상태 메시지, 오류 안내는 모두 모듈 전용 gettext 대상으로 만들고 다음 카탈로그를 갱신한다.

- `mod/telegram_remote_control/locale/ko_KR/LC_MESSAGES/telegram_remote_control.po`
- `mod/telegram_remote_control/locale/en_US/LC_MESSAGES/telegram_remote_control.po`
- `mod/telegram_remote_control/locale/zh_CN/LC_MESSAGES/telegram_remote_control.po`
- `mod/telegram_remote_control/locale/telegram_remote_control.pot`

한국어 UI에서 중국어 원문이 폴백으로 노출되지 않도록 모든 새 msgid의 한국어 번역을 필수로 한다.

## 16. 테스트 계획

### 16.1 단위 테스트

- `/start`, `/stop`, `/status`, `stat`, `menu`와 한국어 별칭 파싱
- 공백, 대소문자, `@bot_name` 처리
- 개인 채팅·Chat ID·봇 발신자 인증
- 비허가 채팅 무응답
- 시작 시 이전 update 폐기 및 offset 증가
- 중복 update와 중복 명령의 멱등 처리
- 토큰 마스킹과 예외 문자열 정제
- 최신 로그 선택, 최근 60초 필터, 연속 줄, 3,900자 제한, 비밀 마스킹
- 네트워크 백오프, 401·409·429 처리
- `ControlState` 전이와 금지된 전이
- GUI와 텔레그램 동시 시작 시 단일 작업 보장
- 타이틀·스레드·GUI 조건이 모두 충족되기 전에는 완료 알림이 생성되지 않음
- 같은 `run_id`의 완료 이벤트를 반복 처리해도 완료 알림이 한 번만 전송됨
- 일시적인 송신 오류 후 완료 알림이 보존되어 재연결 시 전송됨
- 401·403 오류에서는 완료 알림을 전송 성공으로 기록하지 않음

### 16.2 Farm 상태 테스트

- 던전 이동 중 정지 요청이 안전 지점에서 처리됨
- 전투 중 요청은 전투 종료까지 대기함
- 상자 개봉 중 요청은 결과 처리까지 대기함
- 지도 화면을 닫은 뒤 복귀함
- `ACTIVE_REST=False`에서도 마을로 복귀함
- `_RTT` 경로로 여관·도시를 확인함
- 마을에서 `totitle`을 선택함
- 타이틀 템플릿을 2회 연속 확인함
- 600초 초과 시 게임 패키지를 강제 종료함
- 로컬 UI 정지가 안전 정지보다 우선함

### 16.3 원격 재개 테스트

- `AT_TITLE`에서 게임 진입 후 최신 매크로 시작
- `GAME_STOPPED_FALLBACK`에서 Activity 실행 후 시작
- 변경된 `config.json`의 최신 목표 사용
- `-config`로 지정한 설정 파일 재사용
- 로그인 실패 후 1회 게임 재시작
- 두 번째 로그인 실패 시 `ERROR` 처리
- 작업 카운터와 전략 진행률이 새 세션으로 초기화됨

### 16.4 통합 및 수동 검증

실제 1600x900, 영어 UI 에뮬레이터에서 다음 시나리오를 수행한다.

1. 던전 이동 중 `정지` → 마을 → 타이틀 → `동작`
2. 전투 중 `정지` → 전투 종료 → 마을 → 타이틀
3. 상자 개봉 중 `정지` → 개봉 종료 → 마을 → 타이틀
4. 마을에서 `정지` → 즉시 타이틀
5. 네트워크 단절 중 매크로 유지 → 복구 후 명령 수신
6. 복귀 실패 유도 → 600초 제한 또는 테스트용 축소 제한 → 게임 강제 종료
7. WvDAS 재실행 전에 보낸 오래된 명령이 실행되지 않음
8. 허용되지 않은 계정의 명령이 실행되지 않음
9. 정상 정지 완료 후 텔레그램 완료 알림이 정확히 한 번 도착함
10. 복귀 실패 시 정상 완료 문구 없이 강제 종료 알림만 도착함

번역 카탈로그 검증과 `.mo` 컴파일 후 PyInstaller onedir 빌드를 수행한다. 빌드 결과에서 설정 저장, 텔레그램 연결, 타이틀 템플릿 로딩을 다시 확인한다.

## 17. 완료 기준

다음 조건을 모두 만족하면 기능 구현이 완료된 것으로 본다.

1. 허가된 개인 채팅만 게임 제어 가능
2. 전투·상자 작업을 중간에 끊지 않고 안전 지점에서 복귀 시작
3. 여관 설정과 관계없이 마을 복귀 시도
4. 타이틀 화면 확인 후 Farm 스레드가 종료되고 WvDAS는 계속 실행
5. 실패 시 600초 안에 게임 강제 종료 폴백 수행
6. `/start`가 최신 저장 설정으로 정확히 한 개의 Farm 작업만 시작
7. GUI 버튼과 원격 상태가 항상 일치
8. 네트워크 장애가 기존 매크로 수행에 영향을 주지 않음
9. 로그·설정 UI·오류 메시지에서 Bot Token이 노출되지 않음
10. 한국어 UI에 중국어 새 문자열이 노출되지 않음
11. 기존 로컬 시작·즉시 중지 동작에 회귀가 없음
12. 정상 원격 정지 완료 후 텔레그램에 종료 작업 완료 알림이 정확히 한 번 전송됨

## 18. 배포 및 호환성

- 텔레그램 기능은 기본 비활성화하므로 기존 `config.json` 마이그레이션이 필요 없다.
- 새 설정 키가 없으면 기본값을 사용한다.
- 외부 Python 의존성을 추가하지 않는다.
- 모든 신규 Python 소스는 `mod/telegram_remote_control/`에 위치한다. 기존 `src` 변경은 5.1의 연결 지점으로 제한한다.
- 소스 실행 경로에는 저장소 루트를, PyInstaller 분석에는 `--paths "."`를 추가해 루트 `mod` 패키지를 찾게 한다.
- PyInstaller 데이터 옵션에 `mod/telegram_remote_control/resources`와 `mod/telegram_remote_control/locale`을 명시적으로 추가한다.
- 새 타이틀 템플릿과 번역 파일이 누락된 빌드는 빌드 스모크 테스트에서 실패시킨다.
- WvDAS 프로세스가 종료되면 원격 제어도 종료된다는 제한을 GUI 도움말과 README에 명시한다.
- 전용 Telegram Bot 사용을 권장하며 다른 webhook 서비스와 같은 Bot Token을 공유하지 않는다.

## 19. 구현 실행 명세 — Luna 기준

이 절은 구현 순서와 코드 계약을 고정하는 규범적 명세다. 앞 절과 표현이 모호하게 충돌하면 이 절을 우선한다. 구현자는 여기에서 정한 이름, 이벤트, 제한 시간과 실패 정책을 임의로 변경하지 않는다.

### 19.1 고정 상수와 호환 조건

모든 시간 계산은 `time.monotonic()`을 사용한다. 사용자에게 표시하는 시각만 timezone-aware `datetime.now().astimezone()`을 사용한다. 아래 값은 모두 `constants.py`에 한 번만 정의하고 다른 모듈은 import해서 사용한다.

```python
GAME_PACKAGE = "jp.co.drecom.wizardry.daphne"
DEFAULT_GAME_ACTIVITY = (
    "jp.co.drecom.wizardry.daphne/"
    "com.google.firebase.MessagingUnityPlayerActivity"
)
BOT_API_ORIGIN = "https://api.telegram.org"

POLL_TIMEOUT_SECONDS = 25
LONG_POLL_HTTP_TIMEOUT_SECONDS = 35
SHORT_HTTP_TIMEOUT_SECONDS = 15
SEND_BACKOFF_SECONDS = (1, 2, 5, 10, 30)
SERVICE_THREAD_JOIN_TIMEOUT_SECONDS = 36
SENT_KEY_CACHE_SIZE = 4096
MAX_PENDING_MESSAGES = 256

REMOTE_STOP_TIMEOUT_SECONDS = 600
TOWN_CONFIRM_TIMEOUT_SECONDS = 10
EXIT_MENU_TIMEOUT_SECONDS = 30
TITLE_LOAD_TIMEOUT_SECONDS = 120
MAX_EXIT_MENU_BACK_PRESSES = 3
INPUT_COOLDOWN_SECONDS = 2
EDGE_TO_TOWN_TIMEOUT_SECONDS = 60
QUEST_RTT_TIMEOUT_SECONDS = 180

LOGIN_ATTEMPT_TIMEOUT_SECONDS = 180
MAX_LOGIN_ATTEMPTS = 2
APP_START_SETTLE_SECONDS = 10
STABLE_FRAME_COUNT = 2
STABLE_FRAME_INTERVAL_SECONDS = 0.5
FALLBACK_SUBPROCESS_TIMEOUT_SECONDS = 7
FALLBACK_VERIFY_TIMEOUT_SECONDS = 5
FALLBACK_WAIT_TIMEOUT_SECONDS = 15
WORKER_EXIT_TIMEOUT_SECONDS = 15
GUI_CONNECTION_TEST_TIMEOUT_SECONDS = 20
CONTROLLER_TICK_MILLISECONDS = 100
WORKER_POLL_MILLISECONDS = 50
MAX_EVENTS_PER_TICK = 50
HANDOFF_TARGET_7000G = "7000G"
SUPPORTED_TOWN_PATTERNS = (
    "Inn",
    "City_RoyalCityLuknalia",
    "City_fortress",
    "City_DHI",
    "City_portTownGrandLegion",
)
TO_TITLE_PRIMARY_ROI = ((300, 820, 300, 170),)
TO_TITLE_DIALOG_ROI = ((180, 650, 540, 500),)
TITLE_LOGO_ROI = ((0, 0, 900, 960),)
TITLE_TAP_ROI = ((0, 800, 900, 800),)
TO_TITLE_PRIMARY_THRESHOLD = 0.86
TO_TITLE_DIALOG_THRESHOLD = 0.92
TITLE_TEMPLATE_THRESHOLD = 0.88
```

`City_VNH.png`는 리소스에는 있지만 현재 `IdentifyState`의 지원 도시 목록에 없으므로 임의로 포함하지 않는다. 나중에 기존 상태 판정이 지원하면 이 상수와 회귀 테스트를 함께 갱신한다.

19절에서 같은 의미로 쓰는 숫자 literal은 구현 시 모두 이 상수로 대체한다. 테스트에서만 생성자나 함수에 더 짧은 값을 주입할 수 있으며 production 기본값은 위와 같아야 한다.

- Python 3.10 이상에서 동작해야 한다.
- `requests`, `python-telegram-bot`, 비동기 프레임워크 등 새 의존성을 추가하지 않는다.
- Telegram 통신은 HTTPS Bot API long polling만 사용한다. webhook을 자동 생성·삭제하지 않는다.
- 게임은 1600x900, 영어 UI라는 기존 전제를 유지한다.
- 텔레그램 기능이 비활성화됐거나 설정이 잘못돼도 기존 로컬 매크로는 동작해야 한다.

### 19.2 모듈 의존 방향과 공개 API

`mod/telegram_remote_control` 내부 의존 방향은 아래처럼 단방향으로 유지한다.

```text
L0  constants
L1  models, i18n, recent_logs
L2  config, bot_api, adapters, runtime_bridge
L3  command_service, worker, fallback, settings_ui
L4  return_to_town, title_transition, login_transition
L5  stop_orchestrator, feature
```

높은 레이어는 낮은 레이어만 import할 수 있다. 같은 레이어끼리는 import하지 않는다. `feature`만 아래 모듈들을 조립하며 `src`는 공개 API를 호출할 뿐 이 레이어 그래프 안으로 역참조되지 않는다.

- `mod` 모듈은 `src.main`, `src.gui`, `src.script`를 import하지 않는다.
- 기존 코드의 객체와 함수는 `adapters.py`의 callback을 통해서만 받는다.
- `feature.py`만 애플리케이션 이벤트 큐를 알고, Bot API 스레드는 Tk 객체를 알지 못한다.
- `__init__.py`는 `TelegramRemoteFeature`, `ControllerPorts`, `extend_config_var_list`, `RemoteStopSignal`만 재노출한다.

파일별 필수 공개 항목은 다음과 같다.

| 파일 | 반드시 제공할 공개 항목 |
| --- | --- |
| `constants.py` | 19.1의 모든 고정 상수 |
| `models.py` | 모든 Enum과 이벤트 dataclass |
| `config.py` | `extend_config_var_list`, `read_telegram_settings`, `load_latest_farm_setting`, `resolve_adb_executable`, 설정 검증 함수 |
| `bot_api.py` | `TelegramBotClient`, 정규화된 API 예외 클래스 |
| `command_service.py` | `TelegramCommandService.start/stop/reconfigure/enqueue` |
| `recent_logs.py` | `read_recent_log`, `redact_log_text`, `fit_tail_text` |
| `adapters.py` | `GameAutomationAdapter`, `ControllerPorts` |
| `runtime_bridge.py` | `RemoteRuntime`, `RemoteStopSignal`, `RemoteRecoverySuppressed`, `BoundedOperationTimeout`, `remote_stop_checkpoint`, `request_task_handoff`, `raise_if_remote_recovery_disallowed`, `run_bounded_operation` |
| `worker.py` | `TaskCompletionLatch`, `run_farm_worker` |
| `fallback.py` | `force_stop_game_once` |
| `return_to_town.py` | `return_to_town` |
| `title_transition.py` | `return_town_to_title` |
| `stop_orchestrator.py` | `execute_remote_stop`, `execute_recovery_suppressed_fallback` |
| `login_transition.py` | `ensure_game_ready`, `prepare_telegram_run` |
| `settings_ui.py` | `mount_telegram_settings`, `TelegramSettingsWidgets` |
| `feature.py` | `TelegramRemoteFeature` |

### 19.3 `models.py` 데이터 계약

열거형은 문자열 직렬화와 로그 판독을 위해 `str, Enum`을 함께 상속한다. 알림 우선순위만 `IntEnum`을 사용한다.

```python
class RemoteCommand(str, Enum):
    START = "start"
    STOP = "stop"
    STATUS = "status"
    STAT = "stat"
    MENU = "menu"

class StartReason(str, Enum):
    LOCAL = "local"
    TELEGRAM = "telegram"

class ControlState(str, Enum):
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOP_REQUESTED = "stop_requested"
    RETURNING_TO_TOWN = "returning_to_town"
    RETURNING_TO_TITLE = "returning_to_title"
    AT_TITLE = "at_title"
    GAME_STOPPED_FALLBACK = "game_stopped_fallback"
    ERROR = "error"

class TaskExitReason(str, Enum):
    COMPLETED = "completed"
    LOCAL_STOP = "local_stop"
    REMOTE_STOP = "remote_stop"
    REMOTE_STOP_FALLBACK = "remote_stop_fallback"
    ERROR = "error"

class CheckpointKind(str, Enum):
    DUNGEON_STABLE = "dungeon_stable"
    BETWEEN_OPERATIONS = "between_operations"
    TOWN_STABLE = "town_stable"

class NotificationPriority(IntEnum):
    TERMINAL = 0
    ACKNOWLEDGEMENT = 10
    PROGRESS = 20

class ServiceStatus(str, Enum):
    DISABLED = "disabled"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RETRYING = "retrying"
    ERROR = "error"
    STOPPED = "stopped"

class TransitionStatus(str, Enum):
    TOWN_READY = "town_ready"
    AT_TITLE = "at_title"
    GAME_READY = "game_ready"
    FALLBACK_COMPLETE = "fallback_complete"
    LOCAL_ABORT = "local_abort"
    ERROR = "error"
```

다음 dataclass는 필드 이름과 타입을 그대로 사용한다.

```python
@dataclass(frozen=True)
class TelegramSettings:
    enabled: bool
    bot_token: str
    allowed_chat_id: str

@dataclass(frozen=True)
class TelegramCommandPayload:
    command: RemoteCommand
    update_id: int
    chat_id: str
    received_at: datetime
    service_generation: int

@dataclass(frozen=True)
class RemoteProgressPayload:
    run_id: str
    state: ControlState
    detail: str = ""

@dataclass(frozen=True)
class TaskFinishedPayload:
    run_id: str
    reason: TaskExitReason
    detail: str
    farm_target_text: str
    started_at: datetime
    stop_requested_at: datetime | None
    finished_at: datetime
    elapsed_seconds: float
    failure_phase: str | None = None
    notification_chat_id: str | None = None

@dataclass(frozen=True)
class StatusSnapshot:
    state: ControlState
    run_id: str | None
    farm_target_text: str | None
    started_at: datetime | None
    stop_requested_at: datetime | None
    last_error: str | None

@dataclass(frozen=True)
class OutboundMessage:
    key: str
    chat_id: str
    text: str
    priority: NotificationPriority

@dataclass(frozen=True)
class TransitionOutcome:
    status: TransitionStatus
    detail: str = ""
    failure_phase: str | None = None

@dataclass(frozen=True)
class ConnectionTestRequest:
    request_id: str
    settings: TelegramSettings

@dataclass(frozen=True)
class ConnectionTestResult:
    request_id: str
    succeeded: bool
    public_message: str

@dataclass(frozen=True)
class ServiceStatusPayload:
    service_generation: int
    status: ServiceStatus
    public_message: str = ""

@dataclass(frozen=True)
class ForceStopResult:
    run_id: str
    game_stopped: bool
    public_message: str
```

Bot Token은 설정 경계를 나타내는 `TelegramSettings`와 이를 메모리에서 전달하는 `ConnectionTestRequest`에만 존재할 수 있다. 작업·상태·완료 dataclass에는 넣지 않는다. `TaskFinishedPayload.detail`, `last_error`에는 정제된 짧은 문장만 넣고 예외 `repr`이나 전체 ADB 출력을 넣지 않는다.

### 19.4 `config.py` 구현 계약

#### 19.4.1 GUI 설정 항목 추가

`extend_config_var_list(base_list, tk_module)`은 기존 리스트의 복사본 뒤에 다음 세 항목을 추가해 반환한다. 원본 리스트를 함수 내부에서 중복 확장하지 않는다.

```python
[
    ["GENERAL", "TELEGRAM_ENABLED", tk_module.BooleanVar, False],
    ["GENERAL", "TELEGRAM_BOT_TOKEN", tk_module.StringVar, ""],
    ["GENERAL", "TELEGRAM_ALLOWED_CHAT_ID", tk_module.StringVar, ""],
]
```

`src/script.py`는 `CONFIG_VAR_LIST` 선언 직후 정확히 한 번 `CONFIG_VAR_LIST = extend_config_var_list(CONFIG_VAR_LIST, tk)`를 호출한다. 이로써 기존 GUI 생성·저장 루프가 세 값을 항상 `GENERAL`에 보존한다.

#### 19.4.2 값 검증

- 비활성화 상태에서는 토큰과 Chat ID가 비어 있어도 유효하다.
- 활성화 상태에서는 토큰과 Chat ID가 모두 필요하다.
- 토큰은 공백 제거 후 `:`가 정확히 하나 있고, 왼쪽은 숫자이며, 오른쪽은 공백 없는 20자 이상의 문자열이어야 한다.
- Chat ID는 공백 제거 후 10진수 양의 정수여야 하고 `1 <= id <= 2**63 - 1`이어야 한다.
- 사용자 이름, `@name`, 그룹의 음수 Chat ID는 허용하지 않는다.
- `mask_token`은 토큰 길이와 관계없이 항상 `"***"` 또는 `"<empty>"`만 반환한다.

검증 실패는 `TelegramConfigError(public_message)`로 반환한다. `public_message`에는 실제 토큰을 넣지 않는다.

#### 19.4.3 최신 매크로 설정 읽기

현재 `HeadlessActive`는 전달받은 `config_path`를 사용하지 않으므로 원격 시작에서는 `gui.LoadConfig()`를 호출하지 않는다. `load_latest_farm_setting`은 다음 순서로 동작한다.

```python
def load_latest_farm_setting(config_path, load_raw, build_setting):
    raw = load_raw(str(config_path) if config_path else None) or {}
    general = dict(raw.get("GENERAL", {}))
    target = general.get("FARM_TARGET")
    if general.get("TASK_SPECIFIC_CONFIG") and target:
        task = dict(raw.get(target, {}))
    else:
        task = dict(raw.get("DEFAULT", {}))
    merged = {**general, **task}
    setting = build_setting(merged)
    if not getattr(setting, "FARM_TARGET", None):
        raise TelegramConfigError("실행할 매크로가 설정되지 않았습니다.")
    return setting
```

- GUI 모드에서는 `config_path=None`으로 frozen 실행 파일의 사용자 데이터 경로(`%LOCALAPPDATA%\WvDAS\config.json`, `WVDAS_CONFIG_PATH`로 재정의 가능)를 사용한다. 기존 실행 파일 옆 `config.json`은 새 빌드 첫 실행 시 자동으로 이 경로로 이관한다.
- 헤드리스 모드에서만 CLI `-config` 값을 `Path.resolve(strict=False)`한 뒤 사용한다.
- 명시한 파일이 없거나 JSON이 손상됐으면 기본 설정으로 폴백하지 않고 시작을 거부한다.
- Farm 스레드에 넘기기 직전에 `TELEGRAM_BOT_TOKEN`과 `TELEGRAM_ALLOWED_CHAT_ID` 속성을 빈 문자열로 바꿔 작업 객체가 비밀 값을 보유하지 않게 한다.

`read_telegram_settings(config_path, load_raw)`은 같은 경로의 raw JSON에서 `GENERAL` 세 키만 읽어 `TelegramSettings`를 만든다. task-specific 또는 `DEFAULT` 값은 절대 병합하지 않는다. 명시 경로 오류는 `TelegramConfigError`, 키가 없는 기존 설정은 `enabled=False` 기본값이다.

`resolve_adb_executable(emu_path)`는 기존 규칙과 동일하게 파일명을 변환한다.

- `HD-Player.exe` → 같은 경로의 `HD-Adb.exe`
- `MuMuPlayer.exe` → 같은 경로의 `adb.exe`
- `MuMuNxDevice.exe` → 같은 경로의 `adb.exe`

결과 파일이 없으면 `None`을 반환한다. runtime 생성 시 이 값을 저장하며, adapter 등록 전 watchdog 폴백에 사용한다. 외부 ADB 명령은 이 명시 경로만 사용하고 PATH의 임의 `adb.exe`를 찾지 않는다.

### 19.5 `bot_api.py` 구현 계약

`TelegramBotClient` 생성자는 토큰, logger, 선택적 `urlopen` callback을 받는다. 테스트에서는 `urlopen`을 가짜 함수로 교체한다.

```python
class TelegramBotClient:
    def __init__(self, token, logger, urlopen=urllib.request.urlopen): ...
    def get_me(self) -> dict: ...
    def get_updates(self, offset, timeout=25) -> list[dict]: ...
    def send_message(self, chat_id, text) -> dict: ...
```

모든 호출은 `Content-Type: application/json; charset=utf-8`의 POST 요청을 사용한다.

- `getMe`: 빈 JSON 객체
- `getUpdates`: `offset`, `timeout`, `allowed_updates=["message"]`; `offset == -1`인 startup 폐기 호출에만 `limit=1` 추가
- `sendMessage`: `chat_id`, `text`; Markdown/HTML parse mode는 사용하지 않음
- `getUpdates` HTTP timeout: 35초
- 다른 호출 HTTP timeout: 15초

응답 JSON에서 `ok is True`가 아니면 예외로 변환한다.

| 조건 | 예외 |
| --- | --- |
| 401, 403 | `TelegramAuthError`, 영구 오류 |
| 409 또는 `getUpdates` 실패 설명에 webhook 충돌이 명시됨 | `TelegramWebhookConflictError`, 영구 오류 |
| 429 | `TelegramRateLimitError(retry_after)` |
| 5xx, timeout, DNS, 연결 오류 | `TelegramTransientError` |
| JSON 손상, 필수 필드 누락 | `TelegramProtocolError` |

예외 생성 전에 메시지에서 원본 토큰과 `/bot<token>/`을 제거한다. 완성된 URL, 요청 본문, 응답 전체를 logger로 출력하지 않는다.

### 19.6 `command_service.py` 구현 계약

서비스는 최초 활성화 후 polling 스레드와 송신 스레드 각 하나만 daemon으로 유지한다. 프로세스 시작부터 비활성 상태이면 스레드를 만들지 않는다. 한 번 활성화된 뒤 설정에서 기능을 끄면 두 스레드는 종료하지 않고 `Condition`에서 네트워크 호출 없이 대기한다. 다시 활성화하면 같은 스레드를 깨워 사용한다. 애플리케이션 종료의 `stop()`만 final stop event를 설정해 스레드를 끝낸다.

```python
class TelegramCommandService:
    def __init__(self, event_queue, logger, client_factory=TelegramBotClient): ...
    @property
    def generation(self) -> int: ...
    def start(self, settings: TelegramSettings) -> None: ...
    def reconfigure(self, settings: TelegramSettings) -> None: ...
    def enqueue(self, message: OutboundMessage) -> bool: ...
    def stop(self) -> None: ...
```

`start`와 `reconfigure`는 Tk 메인 큐에서 호출되지만 thread join은 수행하지 않는다. 서비스의 공유 상태(`generation`, immutable settings snapshot, pending/sent key 집합)는 하나의 `threading.Condition(threading.RLock())`으로 보호한다. generation은 유효 설정을 적용할 때마다 1 증가하고 0으로 되돌리지 않는다.

#### 19.6.1 시작과 과거 명령 폐기

1. 설정을 검증하고 `CONNECTING` service status를 큐에 넣는다.
2. `getMe`로 토큰을 확인한다.
3. `getUpdates(offset=-1, timeout=0)`을 한 번 호출한다. client는 이 경우에만 `limit=1`을 보낸다.
4. 결과가 있으면 마지막 `update_id + 1`, 없으면 `None`을 정상 polling의 초기 offset으로 사용한다.
5. 폐기 단계에서 받은 메시지는 파싱하거나 컨트롤러에 전달하지 않는다.
6. 이후 `getUpdates(offset=current_offset, timeout=25)`를 반복한다.

각 응답은 `update_id` 오름차순으로 처리하며 처리 여부와 관계없이 가장 큰 ID 다음으로 offset을 전진시킨다. 같은 update가 다시 와도 `update_id <= last_update_id`이면 무시한다.

이 startup 호출은 Bot API의 음수 offset 규칙을 이용해 큐 끝의 한 건만 받고 그보다 앞선 update를 폐기한다. 반환된 마지막 update도 파싱하지 않으며 다음 정상 호출의 `offset=last_update_id+1`로 확인 처리한다. Telegram 공식 계약상 webhook이 설정된 동안 `getUpdates`는 동작하지 않으므로 자동 `deleteWebhook`으로 사용자의 외부 설정을 변경하지 않는다.

polling loop는 매 요청 전에 lock 안에서 `(generation, settings)`를 snapshot하고 generation별 client를 만든다. `getMe`, startup 폐기, 정상 `getUpdates`에서 돌아온 직후 snapshot generation이 현재 값과 같은지 다시 확인한다. 다르면 응답 전체를 버리고 새 설정으로 초기화부터 다시 시작한다. 일시 오류 backoff도 `Condition.wait_for`를 사용해 설정 변경이나 final stop에 즉시 깨어난다.

초기화와 polling의 일시 오류는 `RETRYING`, 정상 응답은 `CONNECTED`, 인증·webhook 영구 오류는 `ERROR`, final stop은 `STOPPED`의 `ServiceStatusPayload`를 큐에 넣는다. 설정 비활성화는 `DISABLED`다. 모든 payload에 snapshot generation을 포함한다. `TelegramCommandPayload.service_generation`도 같은 값을 사용한다.

#### 19.6.2 명령 인증과 파싱

다음 조건을 모두 만족한 `message.text`만 처리한다.

- `chat.type == "private"`
- `str(chat.id) == allowed_chat_id`
- `from`이 dict이고 `from.get("is_bot") is False`
- text가 문자열

정규화 순서:

1. 앞뒤 공백 제거
2. 슬래시 명령이면 첫 공백 전 토큰만 사용
3. `/stop@BotName` 형태에서 `@BotName` 제거
4. 슬래시 명령만 `.lower()` 적용
5. `/start`, `/stop`, `/status`, `/stat`, `/menu`, `stat`, `menu`, `동작`, `정지`, `상태`, `메뉴`에 정확히 매핑

허가된 채팅의 알 수 없는 텍스트에는 `menu` 안내를 한 번 응답한다. 명령 목록은 `menu` 명령에서만 응답한다. 비허가 채팅에는 응답과 본문 로그를 모두 남기지 않는다.

유효 명령은 `controller_queue.put(("telegram_command", payload))`로만 전달한다. polling 스레드는 상태를 변경하거나 작업을 시작하지 않는다.

#### 19.6.3 송신 큐와 완료 알림 보존

송신 큐는 `(priority, sequence, key)`를 담는 `PriorityQueue`이고, lock으로 보호하는 `pending_by_key: dict[str, OutboundMessage]`가 실제 메시지의 authoritative 저장소다. stale queue 항목의 key가 dict에 없으면 건너뛴다. `key`가 `sent_keys` 또는 `pending_by_key`에 있으면 다시 넣지 않는다.

- 성공: pending에서 제거하고 sent에 추가
- 일시 오류: 1·2·5·10·30초 순서로 `stop_event.wait(delay)` 후 같은 메시지를 다시 시도
- 429: 서버 `retry_after`를 사용
- 영구 오류: pending에서 제거하지 않고 서비스 상태를 오류로 바꾸며 GUI에 알림
- 서비스 정상 reconfigure: 양쪽 설정이 모두 enabled이고 Chat ID가 같으면 TERMINAL pending과 sent-key LRU를 유지하고 나머지 pending은 dict에서 제거; Chat ID가 다르거나 disabled가 되면 pending과 sent-key를 모두 폐기

`sent_keys`는 set과 deque로 구성한 4096개 LRU로 제한한다. pending은 최대 256개다. 한도에 도달하면 오래된 PROGRESS, ACKNOWLEDGEMENT 순으로 제거하고 TERMINAL은 제거하지 않는다. 256개가 모두 TERMINAL이면 새 알림 등록을 거절하고 `ERROR` service status를 발생시킨다.

sender는 각 전송 직전에 현재 `(generation, settings)`를 snapshot한다. disabled이거나 message Chat ID가 현재 allowed Chat ID와 다르면 해당 key를 폐기한다. 같으면 현재 token으로 만든 client를 사용한다. 전송이 끝난 뒤 key가 아직 pending이고 Chat ID도 같으면 성공은 sent로 확정하고, 명시적 일시 실패는 현재 generation에서 다시 시도한다. Chat ID 변경·비활성화로 key가 이미 제거됐으면 늦은 결과를 무시한다. 전송 중 token만 바뀐 요청은 취소할 수 없으며, 성공 응답이면 새 token으로 다시 보내지 않는다.

완료 알림 재시도는 polling 스레드를 막지 않는다. 프로세스 종료 시 메모리 pending은 영속화하지 않는다. Telegram `sendMessage`에는 idempotency key가 없으므로 로컬 queue 중복은 막지만, 서버가 메시지를 수락한 뒤 HTTP 응답만 유실된 경우에는 재시도로 같은 문장이 드물게 두 번 도착할 수 있다. terminal 전달 성공률을 위해 이 네트워크 수준 중복 가능성을 허용한다.

#### 19.6.4 재구성과 종료

- `reconfigure(new_settings)`는 lock 안에서 generation 번호와 settings snapshot을 교체하고 `Condition.notify_all()`을 호출한다.
- 이전 generation의 HTTP 결과와 컨트롤러에 늦게 도착한 명령은 generation 불일치로 폐기한다.
- enabled인 새 설정은 token 변경 여부와 관계없이 `getMe`와 과거 명령 폐기 절차를 다시 수행한다.
- disabled 설정은 `DISABLED` status를 즉시 넣고 두 loop를 condition 대기로 보낸다.
- `stop()`은 final stop event 설정, condition notify, 별도 cleanup daemon thread 시작 후 즉시 반환한다.
- cleanup thread만 polling·sender를 각각 최대 36초 join하고, 여전히 살아 있으면 경고만 남긴다. Tk main thread와 Python 종료를 무기한 막지 않는다.

### 19.7 `adapters.py` 계약

`mod`가 `Factory()`의 중첩 함수에 접근할 수 있도록 `src/script.py`가 아래 callback 객체를 생성한다.

```python
@dataclass(frozen=True)
class GameAutomationAdapter:
    screenshot: Callable[[], Any]
    match_base: Callable[[Any, str, Sequence[Sequence[int]] | None, float], list[int] | None]
    press: Callable[[list[int]], bool]
    press_back: Callable[[], None]
    sleep: Callable[[float], None]
    try_press_retry: Callable[[Any], bool]
    device_shell: Callable[[str], str]
    control_shell: Callable[[list[str]], str]
    return_via_quest_rtt: Callable[[], bool]
    finish_combat_or_chest: Callable[[str], bool]
    is_black_frame: Callable[[Any], bool]
    local_stop_requested: Callable[[], bool]
    local_stop_exception_type: type[BaseException]
    failure_dir: Path

    def match_mod(
        self,
        screen,
        name: str,
        roi: Sequence[Sequence[int]] | None = None,
        threshold: float = 0.8,
    ) -> list[int] | None: ...
    def save_failure_frame(self, screen, phase) -> str | None: ...
```

- `match_base`는 기존 `CheckIfAtThreshold`를 호출한다.
- `match_mod`는 callback이 아니라 `adapters.py`의 concrete method다. `mod/telegram_remote_control/resources/images`의 템플릿을 캐시해 OpenCV로 비교한다.
- callback은 성공 여부 또는 명시된 결과를 반환하고 예외를 삼키지 않는다.
- `local_stop_exception_type`에는 `src.script.TaskStoppedException`을 넘긴다. `mod` 상태 머신은 이 타입만 잡아 `LOCAL_ABORT`로 바꾸며 그 외 예외를 로컬 중지로 오인하지 않는다. fake adapter는 전용 fake 예외 타입을 넘긴다.
- `control_shell(argv)`는 `_FORCESTOPING`을 검사하지 않는 one-shot `setting._ADBDEVICE.shell(" ".join(argv), timeout=5)` wrapper다. 자동 ADB·게임 재시작을 수행하지 않으며 package 실행·강제 종료·검증에만 사용한다.
- `return_via_quest_rtt`는 `quest._RTT`가 있을 때만 `TeleportFromDungeonToCity(*quest._RTT)`를 호출한다.
- `finish_combat_or_chest`는 복귀 도중 새 전투·상자가 발생한 경우 기존 `StateCombat` 또는 `StateChest`를 끝낸다.

`BuildRemoteAdapter()`의 연결은 다음 표를 그대로 따른다. 이 표의 callback 나열은 연결 코드이므로 5.1의 10줄 제한에서 제외하지만 분기 알고리즘을 추가해서는 안 된다.

| adapter 항목 | `src/script.py` 연결 |
| --- | --- |
| `screenshot` | `ScreenShot` |
| `match_base` | `lambda screen, name, roi, threshold: CheckIfAtThreshold(screen, name, threshold=threshold, roi=roi)` |
| `press` | `Press` |
| `press_back` | `PressReturn` |
| `sleep` | `Sleep` |
| `try_press_retry` | `TryPressRetry` |
| `device_shell` | `DeviceShell` |
| `control_shell` | `_FORCESTOPING`을 보지 않는 위 one-shot wrapper |
| `return_via_quest_rtt` | `quest`와 `quest._RTT`가 있으면 `TeleportFromDungeonToCity(*quest._RTT)` 후 `True`, 없으면 `False` |
| `finish_combat_or_chest` | `"combat"`이면 `StateCombat`, `"chest"`이면 `StateChest`, 다른 값은 `ValueError` |
| `is_black_frame` | `lambda screen: classify_screen(screen) is ScreenHealth.BLACK` |
| `local_stop_requested` | `setting._FORCESTOPING.is_set` |
| `local_stop_exception_type` | `TaskStoppedException` |
| `failure_dir` | `Path(LOGS_FOLDER_NAME)` |

`save_failure_frame`는 `failure_dir`을 만들고 `remote_{sanitized_phase}_{UTC timestamp}.png`만 저장한다. phase는 영문자·숫자·`_`·`-` 외 문자를 `_`로 바꾸며, 실패한 이미지 저장 때문에 원래 종료 결과를 바꾸지 않도록 `None`을 반환할 수 있다. 성공 시 절대 경로 문자열을 반환하지만 Telegram 메시지에는 이 로컬 경로를 넣지 않는다.

`match_mod`의 리소스와 좌표 계약:

1. 개발 환경: `Path(__file__).resolve().parent / "resources/images"`
2. frozen 환경: `Path(sys._MEIPASS) / "mod/telegram_remote_control/resources/images"`
3. `np.fromfile`과 `cv2.imdecode(..., cv2.IMREAD_COLOR)`로 PNG를 읽고 모듈 전역 dict에 캐시
4. 이미지가 없거나 decode 실패면 `ModResourceError` 발생
5. ROI가 없으면 전체 화면, 있으면 첫 `[x, y, w, h]`만 검색
6. 템플릿이 검색 영역보다 크면 `None`
7. `cv2.TM_CCOEFF_NORMED`의 최대값이 threshold 이상이면 전체 화면 기준 템플릿 중심 좌표 반환, 아니면 `None`
8. 타이틀 템플릿은 resize하지 않음

`match_base`와 `match_mod` 모두 입력 screenshot을 변경하지 않는다. 기존 `CutRoI`는 전달 이미지에 검은 영역을 쓸 수 있으므로 adapter wrapper에서는 사용하지 않는다.

세 화면 상태 머신은 각 loop의 callback 호출 구간을 `try/except adapter.local_stop_exception_type`으로 감싸 `TransitionStatus.LOCAL_ABORT`로 바꾼다. `RemoteRecoverySuppressed`는 잡지 않고 orchestrator까지 전달한다. 그 밖의 예외는 해당 상태 머신에서 failure frame을 저장한 뒤 fallback해야 하는 경우만 변환하며, 단순 프로그래밍 오류를 `LOCAL_ABORT`로 숨기지 않는다.

`ControllerPorts`는 Tk 메인 스레드에서만 호출한다.

```python
@dataclass(frozen=True)
class ControllerPorts:
    load_raw_config: Callable[[str | None], dict | None]
    load_latest_setting: Callable[[], Any]
    start_task: Callable[[Any, StartReason, str, "RemoteRuntime"], bool]
    task_is_alive: Callable[[], bool]
    sync_ui_state: Callable[[ControlState], None]
    schedule_after: Callable[[int, Callable[[], None]], None]
```

### 19.8 `runtime_bridge.py`와 작업 종료 계약

#### 19.8.1 `RemoteRuntime`

작업마다 새 인스턴스를 만들며 재사용하지 않는다. 내부 변경은 `threading.Lock`으로 보호한다.

```python
def remote_stop_checkpoint(
    runtime: "RemoteRuntime | None",
    kind: CheckpointKind,
) -> None:
    ...
```

runtime이 없거나 stop 요청이 없으면 즉시 반환한다. 안전 화면이면 `RemoteStopSignal(kind)`을 발생시키고, 그 외에는 반환한다.

```python
def request_task_handoff(
    runtime: "RemoteRuntime | None",
    event_queue: queue.Queue,
    *,
    target: str,
    event_name: str,
) -> bool:
    ...
```

이 함수는 `remote_stop_checkpoint(runtime, CheckpointKind.BETWEEN_OPERATIONS)`을 먼저 호출한다. runtime이 없으면 레거시 호환을 위해 `(event_name, "")`을 넣고 `True`를 반환한다. runtime이 있고 `runtime.request_handoff(target)`이 거짓이면 queue에 아무것도 넣지 않고 `False`를 반환한다. 참이면 `(event_name, runtime.run_id)`를 넣고 `True`를 반환한다. `Queue.put`이 실패하면 `runtime.clear_handoff(target)` 후 예외를 다시 발생시킨다.

```python
def raise_if_remote_recovery_disallowed(
    runtime: "RemoteRuntime | None",
    operation: str,
) -> None:
    ...
```

runtime, adapter 등록, remote stop 요청이 모두 존재할 때 `RemoteRecoverySuppressed(operation)`을 발생시키고 그 외에는 반환한다. 원격 정지 중 게임·ADB·에뮬레이터 자동 재시작을 막되, adapter 등록 전 최초 연결 복구는 막지 않는 경계다.

```python
def run_bounded_operation(
    operation: Callable[[], Any],
    *,
    runtime: "RemoteRuntime",
    deadline_monotonic: float,
) -> Any:
    ...
```

기존 RTT·전투·상자 callback처럼 내부 timeout 인자가 없는 작업을 daemon helper thread에서 실행하고 결과 또는 예외를 호출자에게 전달한다. 호출자는 `Event.wait(0.1)`로 기다리며 local stop, fallback 시작, 단계 deadline을 확인한다. 단계 deadline이면 `BoundedOperationTimeout`을 발생시킨다. `return_to_town`이 이를 잡아 `force_stop_game_once`를 호출하며, helper는 fallback이 설정한 worker force-stop event로 기존 루프에서 빠져나온다. 이렇게 하여 `runtime_bridge.py`가 `fallback.py`를 import하는 순환 의존을 만들지 않는다.

필수 필드:

```python
run_id: str
start_reason: StartReason
farm_target_text: str
started_at: datetime
started_monotonic: float
stop_event: threading.Event
stop_requested_at: datetime | None
stop_deadline_monotonic: float | None
notification_chat_id: str | None
exit_reason: TaskExitReason | None
detail: str
failure_phase: str | None
adapter: GameAutomationAdapter | None
event_queue: queue.Queue
worker_force_stop_event: threading.Event
adb_executable: str | None
adb_address: str
timeout_fallback_started: threading.Event
fallback_dispatch_started: threading.Event
fallback_done: threading.Event
fallback_succeeded: bool | None
handoff_target: str | None
```

생성자는 위 필드 중 `run_id`, `start_reason`, `farm_target_text`, `event_queue`, `worker_force_stop_event`, `adb_executable`, `adb_address`, `started_at`, `started_monotonic`을 받고 선택적으로 `notification_chat_id`를 받으며 나머지는 기본값으로 초기화한다. Telegram `/start`는 명령 Chat ID, 로컬 시작은 `None`으로 생성한다. `started_at`은 timezone-aware 값이어야 한다.

이벤트 소유권은 다음과 같이 고정한다.

- `stop_event`: runtime 생성자가 내부에서 새로 만드는 **graceful remote stop 전용** 이벤트. 기존 Farm 함수는 직접 보지 않는다.
- `worker_force_stop_event`: runtime 밖에서 생성해 주입하며 `setting._FORCESTOPING`에 **동일 객체 참조**를 연결한다. 로컬 즉시 중지와 폴백만 설정한다.
- 한 실행에서 `_FORCESTOPING`용 `Event`를 두 번 만들거나 worker 시작 시 교체하지 않는다.
- `RemoteRuntime`은 `worker_force_stop_event`가 `threading.Event` 호환 객체가 아니면 `TypeError`를 발생시킨다.

필수 메서드:

- `request_stop(now, monotonic_now, chat_id) -> bool`: 첫 요청만 기록하고 600초 deadline 및 완료 알림 대상 chat ID 설정
- `is_stop_requested() -> bool`
- `report_progress(new_state, detail="")`: canonical 상태를 바꾸지 않고 `remote_progress` 이벤트 전송
- `register_adapter(adapter, handoff_target=None)`: 첫 worker는 target 없이 등록하고, 후속 worker는 현재 handoff와 일치할 때만 원자적으로 교체
- `mark_exit(reason, detail="", failure_phase=None)`: 첫 종료 결과만 기록
- `request_handoff(target) -> bool`: 종료 결과와 stop 요청이 없을 때만 handoff 대상 기록
- `is_handoff_requested(target=None) -> bool`
- `clear_handoff(target) -> bool`: 컨트롤러가 새 worker를 시작하기 직전에 일치하는 handoff만 제거
- `update_farm_target(text)`: handoff 후 상태·완료 메시지의 현재 매크로 이름 갱신
- `begin_timeout_fallback() -> bool`: watchdog 경쟁에서 한 스레드만 폴백 수행
- `is_timeout_fallback_started() -> bool`
- `begin_fallback_dispatch() -> bool`: AppController가 helper thread를 한 번만 생성하도록 보장
- `finish_fallback(succeeded, detail, failure_phase)`: 결과 저장 후 `fallback_done` 설정
- `wait_for_fallback(timeout) -> bool | None`
- `build_finished_payload(finished_at=None, finished_monotonic=None) -> TaskFinishedPayload`

`RemoteStopSignal`은 `Exception`을 상속하고 생성자에서 `checkpoint_kind: CheckpointKind`를 필수로 받아 읽기 전용 속성에 보관한다. `RestartableSequenceExecution`이 잡지 않게 하고 최상위 `Farm`만 처리한다.

`RemoteRecoverySuppressed`는 `Exception`을 상속하고 정제된 `operation: str`을 읽기 전용 속성에 보관한다. 원래 ADB 예외나 명령 출력은 문자열에 넣지 않는다.

`BoundedOperationTimeout`은 `Exception`을 상속하고 `failure_phase: str`을 보관한다.

`build_finished_payload`는 lock 안에서 종료 필드를 snapshot한다. `exit_reason`이 아직 없으면 `RuntimeError`를 발생시킨다. 인자가 없을 때 `finished_at=datetime.now(timezone.utc)`, `finished_monotonic=time.monotonic()`을 사용하고 `elapsed_seconds=max(0.0, finished_monotonic-started_monotonic)`으로 계산한다. 테스트는 두 값을 명시해 시간 의존성을 제거한다. 반환 객체에는 adapter, event, token, raw 예외를 포함하지 않는다.

#### 19.8.2 정확히 한 번 끝나는 콜백

기존 `Factory()`는 여러 경로에서 인자 없는 `_FINISHINGCALLBACK()`을 호출한다. 이를 모두 변경하지 말고 `TaskCompletionLatch.callback()`을 주입한다.

```python
class TaskCompletionLatch:
    def __init__(self, event_queue, run_id): ...
    def callback(self) -> bool: ...
    @property
    def called(self) -> bool: ...
```

`callback()`은 내부 `Lock`으로 보호하며 첫 호출에서만 이벤트를 넣고 `True`, 이후에는 아무 일 없이 `False`를 반환한다.

- 첫 호출: `controller_queue.put(("task_completion_requested", run_id))`
- 이후 호출: 무시
- worker가 예상하지 못한 `Exception`으로 끝나고 callback이 호출되지 않은 경우 `run_farm_worker`의 `finally`가 오류 결과로 callback 요청
- `SystemExit`은 runtime에 `handoff_target`이 선등록된 경우에만 기존 `turn_to_7000G` 전환으로 인정
- handoff 표시 없는 `SystemExit`은 `ERROR/farm_worker_system_exit`로 기록하고 완료 callback 요청

`task_completion_requested`를 받은 시점에는 worker가 아직 살아 있을 수 있다. `AppController`는 `quest_threading.is_alive()`가 참이면 `after(50, ...)`로 다시 확인하고, 거짓이 된 뒤에만 `TaskFinishedPayload`를 확정해 feature에 전달한다. Tk 스레드에서 `join()` 또는 busy wait를 실행하지 않는다.

컨트롤러의 `_finalize_task_when_dead(run_id)`는 다음 순서다.

1. `run_id != self.current_run_id`이면 늦은 이벤트로 보고 무시
2. worker가 살아 있으면 `after(50, lambda: ...)`로 재예약
3. runtime의 exit reason이 없으면 worker wrapper 결과를 기다리지 말고 `ERROR`로 보완
4. `payload = runtime.build_finished_payload()` 생성
5. AppController의 `quest_threading`, `quest_setting`, completion latch, current run ID 참조 해제. feature가 가진 current runtime은 아직 해제하지 않음
6. `("task_finished", payload)`를 같은 메인 큐 뒤에 추가

GUI 완료 처리는 여기서 직접 호출하지 않는다. 뒤이어 feature가 `task_finished`를 처리하며 run ID를 확인하고 최종 상태를 결정한 뒤 current runtime을 해제하고 `ports.sync_ui_state`를 정확히 한 번 호출한다.

`worker.py`의 실행 래퍼는 다음 의미를 그대로 구현한다.

```python
def run_farm_worker(farm_callable, setting, runtime, latch, logger):
    handed_off = False
    try:
        farm_callable(setting)
    except SystemExit:
        if runtime.is_handoff_requested("7000G"):
            # 같은 논리 실행을 새 worker로 넘기는 명시적 기존 경로
            handed_off = True
            return
        runtime.mark_exit(
            TaskExitReason.ERROR,
            detail="작업 스레드가 예기치 않게 종료되었습니다.",
            failure_phase="farm_worker_system_exit",
        )
    except Exception as exc:
        runtime.mark_exit(
            TaskExitReason.ERROR,
            detail="작업 스레드에서 예기치 않은 오류가 발생했습니다.",
            failure_phase="farm_worker",
        )
        logger.exception("farm worker failed")
    finally:
        if not handed_off:
            if runtime.exit_reason is None:
                reason = (
                    TaskExitReason.LOCAL_STOP
                    if setting._FORCESTOPING.is_set()
                    else TaskExitReason.COMPLETED
                )
                runtime.mark_exit(reason)
            latch.callback()
```

명시적으로 등록된 handoff의 `SystemExit`은 다시 던지지 않고 정상 반환해 traceback을 만들지 않는다. 이때 `finally`는 실행되지만 `handed_off=True`이므로 완료 callback을 생략한다. 등록되지 않은 `SystemExit`은 일반 완료나 handoff로 오인하지 않는다.

`register_adapter`의 첫 호출은 `adapter is None`일 때만 허용한다. 이미 adapter가 있으면 `handoff_target`이 runtime의 현재 handoff와 정확히 같고 종료 결과가 없을 때만 새 adapter로 교체한 뒤 handoff를 지운다. 그 외 중복 등록은 `RuntimeError`다. 따라서 handoff로 생성된 새 `Factory`의 callback이 이전 worker의 closure를 확실히 교체한다.

`QuestFarm`의 기존 `turn_to_7000G` 분기에서는 queue 이벤트보다 먼저 `remote_stop_checkpoint(runtime, BETWEEN_OPERATIONS)`를 호출하고 `runtime.request_handoff("7000G")`가 참인지 확인한다. 거짓이면 이벤트를 넣거나 `SystemExit`을 발생시키지 않고 현재 종료 원인을 따른다. 참이면 `("turn_to_7000G", run_id)`를 넣은 뒤 `SystemExit`을 발생시킨다. 이 순서 때문에 이미 접수된 원격 정지가 7000G 전환에 의해 유실되지 않는다.

`turn_to_7000G` 이벤트를 받은 컨트롤러는 payload의 `run_id`가 현재 실행과 같고 runtime의 handoff 대상이 `7000G`인지 다시 확인한다. 기존 worker가 끝났는지 `after(50, ...)`로 확인한 뒤, 설정의 `FARM_TARGET`과 `_REMOTE_HANDOFF_TARGET`을 각각 `7000G`로 바꾸고 `runtime.update_farm_target("7000G")`를 호출한다. 그 다음 같은 `run_id`, `RemoteRuntime`, `TaskCompletionLatch`와 설정 객체를 사용해 새 worker를 시작한다. 새 worker의 `BuildRemoteAdapter` 직후 `runtime.register_adapter(adapter, handoff_target=setting._REMOTE_HANDOFF_TARGET)`가 adapter를 교체하면서 handoff를 지우고, 설정의 `_REMOTE_HANDOFF_TARGET`도 `None`으로 돌린다. 새 논리 실행으로 계산하거나 시작 완료 알림을 다시 보내지 않는다. worker 시작이 실패하면 `runtime.clear_handoff("7000G")`, `ERROR/handoff_start`, latch 순서로 처리한다.

handoff 요청 뒤 Telegram `/stop`이 queue에 들어온 경우 queue FIFO에 따라 handoff가 먼저 시작될 수 있으나, 같은 runtime의 stop event가 새 worker에 전달되어 다음 체크포인트에서 안전 정지를 계속한다. handoff 전에 stop event가 이미 설정된 경우에는 위 체크포인트가 handoff를 막는다.

#### 19.8.3 `fallback.py`

```python
def force_stop_game_once(
    adapter: GameAutomationAdapter | None,
    runtime: RemoteRuntime,
    *,
    failure_phase: str,
) -> TransitionOutcome:
    ...
```

동작 계약:

1. `runtime.begin_timeout_fallback()`이 참이면 현재 호출자가 owner다.
2. adapter `control_shell`로 process 확인을 먼저 시도하고, adapter 명령 자체가 실패하면 명시된 외부 ADB 경로로 한 번만 전환한다.
3. process가 이미 없으면 force-stop 입력 없이 성공으로 확정한다.
4. process가 있으면 같은 transport로 `am force-stop GAME_PACKAGE`를 실행한다.
5. 0.5초 간격으로 최대 5초 동안 process가 사라졌는지 확인한다.
6. 아직 살아 있으면 같은 transport로 force-stop을 한 번 더 실행하고 다시 최대 5초 확인한다.
7. 성공이면 `runtime.mark_exit(REMOTE_STOP_FALLBACK, ..., failure_phase)` 후 `finish_fallback(True, ...)` 호출
8. 실패이면 `runtime.mark_exit(ERROR, ..., failure_phase)` 후 `finish_fallback(False, ...)` 호출
9. `finally`에서 `runtime.worker_force_stop_event.set()`으로 기존 Farm 루프의 즉시 종료를 요청
10. owner만 `remote_force_stop_result` 이벤트를 정확히 한 번 큐에 넣음

owner가 아니면 ADB 명령을 실행하지 않고 `runtime.wait_for_fallback(15)`를 호출한다. 결과가 참이면 `FALLBACK_COMPLETE`, 거짓 또는 timeout이면 `ERROR` 상태의 `TransitionOutcome`을 반환한다.

함수 진입 시 worker force-stop event가 이미 설정됐고 fallback owner가 아직 없으면 `LOCAL_ABORT`를 반환한다. 이 검사와 owner 획득은 runtime lock 안에서 한 번에 수행해 로컬 중지와 watchdog의 경합 결과를 결정적으로 만든다.

외부 ADB는 `runtime.adb_executable`이 실제 파일일 때만 `subprocess.run([...], shell=False, capture_output=True, text=True, timeout=7)`로 호출한다. 인자 형태는 `<adb> -s <address> shell am force-stop <package>`와 `<adb> -s <address> shell pidof <package>`다. adapter transport가 실패하고 외부 ADB도 없으면 `ERROR`다.

`pidof`의 stdout이 빈 문자열이면 미실행, package PID 숫자가 있으면 실행 중이다. `not found`, `unknown command`, exit code 127처럼 명령 미지원이면 `<adb> -s <address> shell dumpsys activity processes`를 실행하고 Python에서 package 문자열 존재 여부를 검사한다. 두 검증 명령이 모두 실패하면 프로세스가 종료됐다고 추정하지 않고 `ERROR`로 처리한다. transport 전환 후 검증과 force-stop을 섞지 않고, 선택된 한 transport로 해당 시도를 끝낸다.

### 19.9 `feature.py` 상태 및 명령 처리

`TelegramRemoteFeature`는 AppController가 소유하지만 모든 메서드는 Tk 메인 큐에서 호출한다. background 서비스는 이벤트만 넣는다.

feature의 `self.state`가 canonical `ControlState`다. `RemoteRuntime.state`는 제거하고 worker가 보내는 단계는 `report_progress` 이벤트로만 표현한다. feature가 이벤트의 `run_id`가 현재 runtime과 일치하는지 확인한 뒤 허용 전이 표를 적용하고 GUI·Telegram을 갱신한다.

필수 API:

```python
class TelegramRemoteFeature:
    def __init__(self, event_queue, config_path, ports, logger, language): ...
    def start(self) -> None: ...
    def stop(self) -> None: ...
    def handle_event(self, command, value) -> bool: ...
    def on_task_started(self, runtime) -> None: ...
    def on_task_finished(self, payload) -> None: ...
    def tick(self, monotonic_now) -> None: ...
    def status_snapshot(self) -> StatusSnapshot: ...
```

`handle_event`가 소비하는 이벤트:

| 이벤트 | 처리 |
| --- | --- |
| `telegram_command` | 명령 상태 검사 후 시작·정지·상태·최근 로그·메뉴 처리 |
| `telegram_reconfigure` | 파일에서 설정 재로드 후 서비스 재구성 |
| `telegram_test_connection` | background 연결 테스트 시작 |
| `telegram_test_result` | 요청 ID가 현재 GUI 테스트와 일치하면 결과 표시 |
| `telegram_service_status` | generation이 현재 서비스와 일치하면 GUI 상태 갱신 |
| `remote_progress` | 상태 전이, GUI와 Telegram 진행 알림 |
| `task_finished` | 최종 상태와 terminal 알림 처리 |
| `remote_force_stop_result` | watchdog 폴백 결과 반영 |

처리하지 않은 이벤트에는 `False`, 처리한 이벤트에는 `True`를 반환한다.

`telegram_command` 처리 첫 단계에서 `payload.service_generation == command_service.generation`과 `payload.chat_id == current_settings.allowed_chat_id`를 다시 검증한다. 둘 중 하나라도 다르면 늦은 명령으로 폐기하고 응답하지 않는다.

canonical 상태의 허용 전이는 다음 표로 고정한다. 표에 없는 전이는 로그 경고 후 무시한다.

| 현재 상태 | 허용 다음 상태 |
| --- | --- |
| `IDLE` | `STARTING`, `RUNNING`, `ERROR` |
| `STARTING` | `RUNNING`, `STOP_REQUESTED`, `ERROR`, `IDLE` |
| `RUNNING` | `STOP_REQUESTED`, `IDLE`, `ERROR` |
| `STOP_REQUESTED` | `RETURNING_TO_TOWN`, `RETURNING_TO_TITLE`, `AT_TITLE`, `GAME_STOPPED_FALLBACK`, `ERROR`, `IDLE` |
| `RETURNING_TO_TOWN` | `RETURNING_TO_TITLE`, `AT_TITLE`, `GAME_STOPPED_FALLBACK`, `ERROR`, `IDLE` |
| `RETURNING_TO_TITLE` | `AT_TITLE`, `GAME_STOPPED_FALLBACK`, `ERROR`, `IDLE` |
| `AT_TITLE` | `STARTING`, `IDLE` |
| `GAME_STOPPED_FALLBACK` | `STARTING`, `IDLE` |
| `ERROR` | `STARTING`, `IDLE` |

작업 종료 사유의 최종 상태 매핑:

| `TaskExitReason` | 최종 상태 | terminal Telegram 알림 |
| --- | --- | --- |
| `COMPLETED` | `IDLE` | 없음 |
| `LOCAL_STOP` | `IDLE` | 원격 정지 요청이 있었으면 취소 안내, 아니면 없음 |
| `REMOTE_STOP` | `AT_TITLE` | 정상 종료 완료 |
| `REMOTE_STOP_FALLBACK` | `GAME_STOPPED_FALLBACK` | 비정상 완료 |
| `ERROR` | `ERROR` | Telegram 활성 시 현재 허용 채팅에 오류 안내 |

로컬 GUI에서 시작한 작업도 `RemoteRuntime(StartReason.LOCAL)`을 가진다. 따라서 실행 도중 Telegram `/stop`을 받을 수 있다. 로컬 시작은 `on_task_started`에서 즉시 `RUNNING`으로 전이하고 로그인 gate를 건너뛴다. Telegram `/start`만 `STARTING`으로 전이한 뒤 READY 확인 후 `RUNNING`이 된다.

폴백 terminal 알림은 `ForceStopResult.game_stopped=True`와 `TaskFinishedPayload.reason=REMOTE_STOP_FALLBACK`가 같은 `run_id`로 모두 도착해야 생성한다. 도착 순서는 상관없으며 feature가 먼저 온 값을 보관한다. 한쪽이 없으면 `GAME_STOPPED_FALLBACK`으로 확정하거나 완료 알림을 보내지 않는다.

정상·폴백 완료 알림은 `TaskFinishedPayload.notification_chat_id`가 현재 활성 Telegram 설정의 `allowed_chat_id`와 같을 때만 큐에 넣는다. 작업 중 허용 Chat ID가 변경되거나 기능이 비활성화되면 이전 채팅으로 결과를 보내지 않으며 새 채팅으로도 과거 작업 결과를 전달하지 않는다. GUI와 로컬 로그에는 완료 상태를 그대로 반영한다.

`ERROR` 종료는 시작 경로가 로컬 GUI인지 Telegram인지와 관계없이 Telegram이 활성화된 경우 현재 `allowed_chat_id`로 한 번 알린다. 알림에는 매크로명, 정제된 오류 문장, `failure_phase`, 경과 시간과 `stat` 안내를 넣고 traceback·토큰·ADB 원문은 넣지 않는다. 전체 WvDAS 프로세스가 즉시 종료되어 송신 스레드까지 사라진 경우에는 이 알림을 보장할 수 없다.

feature 시작 시 `read_telegram_settings`로 설정을 읽는다. `enabled=False`이면 서비스 스레드를 만들지 않고 `DISABLED`로 표시한다. `enabled=True`이고 설정이 유효하면 매크로 실행 여부와 무관하게 즉시 polling·송신 스레드를 시작한다. 따라서 `IDLE`, 실행 중, 안전 정지 중, `AT_TITLE` 상태 모두에서 명령을 계속 받는다.

알림 key와 발송 시점은 다음으로 고정한다.

| 알림 | key | 우선순위 | 발송 조건 |
| --- | --- | --- | --- |
| 명령 접수 | `command:{update_id}` | ACKNOWLEDGEMENT | 유효 start/stop 명령을 최초 수락 |
| 진행 단계 | `progress:{run_id}:{state}` | PROGRESS | 해당 상태 최초 진입 |
| 시작 완료 | `start-complete:{run_id}` | TERMINAL | Telegram 시작이 READY 후 RUNNING 진입 |
| 정상 정지 완료 | `remote-stop-complete:{run_id}` | TERMINAL | worker 종료 확인 후 AT_TITLE |
| 폴백 정지 완료 | `remote-stop-fallback:{run_id}` | TERMINAL | 게임 종료와 worker 종료 모두 확인 |
| 비정상 종료 | `abnormal-exit:{run_id}` | TERMINAL | `TaskExitReason.ERROR`, 로컬·원격 시작 공통 |

`/status`와 `/stat`은 중복 방지 대상이 아니며 요청마다 다음 형식으로 즉시 응답한다.

```text
📋 WvDAS UI 메시지 (최근 60초)

{ui_message_body_lines}
```

`status`, `stat`, `menu`는 `update_id`를 key에 포함해 요청마다 한 번 응답한다. 알 수 없는 텍스트는 명령 목록 대신 `menu` 안내만 반환한다.

진행 알림은 한 상태당 한 번만 보낸다. 동일 상태의 detail 변경만으로 새 메시지를 보내지 않아 네트워크 장애나 화면 재판정 중 Telegram 메시지가 폭주하지 않게 한다.

#### `/stop`

1. `RUNNING` 또는 `STARTING`인지 확인한다.
2. `runtime.request_stop(now, monotonic_now, payload.chat_id)`를 호출한다.
3. `STOP_REQUESTED`로 전이한다.
4. ACK 알림을 큐에 넣는다.
5. 이후 중복 `/stop`은 새 deadline을 만들지 않고 현재 단계를 응답한다.

#### `/start`

1. `IDLE`, `AT_TITLE`, `GAME_STOPPED_FALLBACK`, `ERROR` 중 하나이며 worker가 죽어 있는지 확인한다.
2. 최신 설정을 읽고 검증한다.
3. `uuid.uuid4().hex`로 run ID를 만든다.
4. `worker_force_stop_event = threading.Event()`를 하나 만들고 명령 Chat ID를 `notification_chat_id`로 넣어 새 `RemoteRuntime(StartReason.TELEGRAM)`을 만든다.
5. Farm 설정 객체에서 Telegram 비밀 필드를 비운다.
6. `ports.start_task`가 참을 반환하면 그 안의 `on_task_started(runtime)`이 `STARTING` 전이를 정확히 한 번 수행했는지 확인하고 접수 알림을 보낸다.
7. 거부되면 runtime을 저장하지 않고 오류 응답만 보낸다.

`/start` handler 자체는 `STARTING`을 다시 설정하지 않는다. `on_task_started`만 작업 시작 상태 전이의 단일 소유자다. `ports.start_task`가 참인데 feature의 current run ID가 전달한 run ID와 다르거나 상태가 `STARTING`이 아니면 연결 계약 위반으로 `ERROR/start_task_contract`를 기록한다.

`RUNNING`에서 `/start`는 `이미 실행 중입니다.`로, 정지 진행 상태에서는 `정지 완료 후 다시 동작 명령을 보내십시오.`로 응답한다. 명령을 예약하지 않는다.

#### watchdog

`AppController.check_queue`의 마지막에서 매 100ms `feature.tick(time.monotonic())`을 호출한다. stop deadline을 넘기고 runtime이 끝나지 않았다면 `begin_fallback_dispatch()`를 원자적으로 호출하고, 참을 반환한 한 번만 helper thread를 생성한다. 실제 ADB owner 획득은 helper 안의 `force_stop_game_once`가 `begin_timeout_fallback()`으로 수행한다.

tick은 deadline보다 먼저 `runtime.worker_force_stop_event.is_set()`을 확인한다. 로컬 즉시 중지가 먼저 설정돼 있으면 fallback을 시작하지 않고 worker의 `LOCAL_STOP` 완료를 기다린다. fallback owner가 먼저 결정된 뒤 들어온 로컬 중지는 이미 시작한 게임 강제 종료를 취소하지 않는다.

폴백은 daemon helper thread에서 `fallback.force_stop_game_once`를 호출한다. 작업 스레드가 결정적 복귀 실패를 먼저 발견해도 같은 함수를 호출하며 `begin_timeout_fallback()`을 성공한 단 하나의 호출자만 실제 ADB 명령을 실행한다. 다른 호출자는 `fallback_done`을 최대 15초 기다려 같은 결과를 사용한다.

게임 중단을 확인하지 못하면 `ERROR`로 표시하고 성공 폴백 알림을 보내지 않는다. `remote_force_stop_result(game_stopped=True)`를 받은 feature는 worker 종료 확인을 별도로 시작한다. 15초 안에 `task_finished`가 오지 않으면 새 작업 시작을 금지한 채 `ERROR`를 유지한다. Python worker 스레드를 강제로 종료하려고 시도하지 않는다.

`begin_timeout_fallback()`이 참을 반환한 즉시 runtime 내부 fallback event가 설정된다. `return_to_town`, `return_town_to_title`, `ensure_game_ready`는 모든 스크린샷·탭·Back·retry 직전에 이 event를 확인하고 설정돼 있으면 새 ADB 입력 없이 반환한다. watchdog의 강제 종료 명령 이후 worker가 뒤늦게 이동 입력을 보내는 경쟁을 허용하지 않는다.

### 19.10 `src` 최소 연결 변경

#### 19.10.1 `src/main.py`

`from gui import *`보다 앞에서 저장소 루트를 import 경로에 넣는다.

```python
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
```

그 다음 `mod.telegram_remote_control`의 공개 항목만 import한다.

`AppController` 변경 순서:

1. `self.headless`, `self.config_path`, task 참조와 `self.remote_runtime` 저장
2. GUI 또는 Headless 초기화
3. `ControllerPorts`와 `TelegramRemoteFeature` 생성
4. feature 시작
5. 기존 업데이트 확인과 queue polling 시작

`self.config_path`는 `config_path if headless else None`으로 정규화한다. `ControllerPorts.load_raw_config`에는 `LoadRawConfigFromFile`, `load_latest_setting`에는 `lambda: load_latest_farm_setting(self.config_path, LoadRawConfigFromFile, LoadSettingFromDict)`를 전달한다. feature는 Telegram 설정을 읽을 때 반드시 `ports.load_raw_config(self.config_path)`를 사용해 frozen EXE의 기존 config fallback 규칙을 보존한다. feature 생성자의 `language`는 같은 raw config의 `GENERAL.LANGUAGE`를 사용하고, 값이 `ko_KR`, `en_US`, `zh_CN` 중 하나가 아니면 `ko_KR`로 정규화한다.

기존 `start_quest` case 본문은 `_start_task(setting, start_reason, run_id, runtime)` 메서드로 이동한다.

1. 살아 있는 worker가 있거나 feature에 current runtime이 있으면 `False` 반환
2. `_MSGQUEUE`, `_REMOTE_RUNTIME`, `_START_REASON`, `_TASK_RUN_ID` 설정
3. `_FORCESTOPING = runtime.worker_force_stop_event`로 같은 객체를 연결하며 새 `Event()`를 만들지 않음
4. 새 `TaskCompletionLatch`를 만들고 `latch.callback`을 `_FINISHINGCALLBACK`에 설정
5. controller의 current runtime·run ID·setting·latch 참조 설정
6. `remote_feature.on_task_started(runtime)` 호출
7. `Thread(target=run_farm_worker, ..., daemon=True)` 객체를 controller에 설정하고 시작
8. 성공 시 `True`

feature 등록을 worker 시작보다 먼저 수행해 매우 빠른 `remote_progress`나 완료 이벤트도 current run으로 인식하게 한다. `Thread.start()`가 실패하면 runtime을 `ERROR/thread_start`로 기록하고 latch를 호출한다. 이 시점에는 요청이 이미 등록됐으므로 `_start_task`는 `True`를 반환하고 정상 `task_finished` 흐름이 오류를 알리게 한다. `False`는 1번의 사전 거부에만 사용한다. 실패 경로에서 `on_task_started`를 되돌리려고 직접 UI를 만지지 않는다.

GUI 시작은 `StartReason.LOCAL`, Telegram 시작은 `StartReason.TELEGRAM`을 전달한다. 로컬 시작에도 runtime을 만들되 Telegram 로그인 gate는 실행하지 않는다. 두 경로 모두 runtime보다 먼저 `worker_force_stop_event = Event()`를 정확히 하나 생성해 constructor에 전달한다.

`check_queue`는 한 tick에 최대 50개 메시지를 처리하도록 반복하고, 각 메시지에서 먼저 `remote_feature.handle_event(command, value)`를 호출한다. 반환값이 참이면 기존 `match`로 넘기지 않는다. 마지막에 `remote_feature.tick()`을 호출한다.

기존 `quest_finished` case는 `task_completion_requested`/`task_finished` 흐름으로 대체한다. `turn_to_7000G`의 worker 대기는 `while` busy loop 대신 `after(50, ...)` 재확인으로 바꿔 Tk 정지를 막는다.

`HeadlessActive`는 더 이상 전달받은 `config_path`를 무시하지 않는다. `load_latest_farm_setting(config_path, LoadRawConfigFromFile, LoadSettingFromDict)`으로 설정을 만들고 `("start_quest", setting)`을 큐에 넣는다. feature에도 같은 `config_path`를 전달해 `GENERAL`의 Telegram 설정을 읽는다. 명시 설정 파일이 없거나 JSON이 손상되었으면 logger에 공개 오류만 남기고 Farm을 시작하지 않으며 Telegram 서비스 상태도 `ERROR`로 표시한다. AppController mainloop는 유지한다.

GUI의 기존 `start_quest` 이벤트를 처리할 때는 AppController가 `StartReason.LOCAL`의 새 runtime·run ID·latch를 만든다. Telegram `/start` 경로에서 이미 생성된 runtime을 또 만들지 않는다. `_start_task` 호출 직전에는 시작 사유와 관계없이 Farm 설정 객체의 Telegram token과 Chat ID 속성을 빈 문자열로 바꾼다.

`main()`의 `finally`에서 `controller.remote_feature.stop()` 후 기존 로그 listener를 중단한다.

#### 19.10.2 `src/gui.py`

- `ConfigPanelApp` 생성 후 이미 만들어진 `TELEGRAM_*` Tk 변수를 사용한다.
- `create_widgets()`에서 에뮬레이터 섹션 바로 다음, 목표 섹션 바로 앞에 `mount_telegram_settings(...)`를 호출한다.
- 반환된 `TelegramSettingsWidgets`를 `self.telegram_settings_widgets`에 보관한다.
- Telegram 설정 위젯은 매크로 실행 중에도 토큰 복구와 수신기 비활성화가 가능해야 하므로 `set_controls_state`의 비활성화 목록에 넣지 않는다.
- `settings_ui`의 연결 테스트 버튼은 19.13의 `ConnectionTestRequest`를 `("telegram_test_connection", request)`로 넣고 결과가 올 때까지 자체 버튼만 비활성화한다.
- Telegram `저장 및 적용` 또는 사용 체크박스 변경으로 저장한 직후에만 `("telegram_reconfigure", None)`을 큐에 넣는다. 기존 일반 저장 동작은 service를 재시작하지 않는다.
- `apply_remote_control_state(state)`를 추가해 `STOP_REQUESTED`부터 `RETURNING_TO_TITLE`까지 시작 버튼 문구를 `즉시 중지`로 유지한다. 이 버튼을 누르면 기존 `stop_quest`를 보내 로컬 강제 중지를 수행한다.
- `AT_TITLE`, `GAME_STOPPED_FALLBACK`, `ERROR`, `IDLE`에서는 시작 버튼과 설정 컨트롤을 정상 상태로 복구한다.

기존 `save_config()` 루프가 Telegram 세 키를 자동 저장하므로 별도 JSON 쓰기 코드를 만들지 않는다.

#### 19.10.3 `src/script.py`

`src`만 `sys.path`에 넣은 기존 테스트에서도 `mod` import가 성공하도록, 기존 `from pathlib import Path` 바로 다음에 `import sys`와 아래 경로 등록을 추가한다. `Path`를 두 번 import하지 않는다.

```python
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
```

그 다음 아래 import만 추가한다.

```python
from mod.telegram_remote_control import (
    RemoteStopSignal,
    extend_config_var_list,
)
from mod.telegram_remote_control.adapters import GameAutomationAdapter
from mod.telegram_remote_control.constants import HANDOFF_TARGET_7000G
from mod.telegram_remote_control.login_transition import prepare_telegram_run
from mod.telegram_remote_control.models import (
    CheckpointKind,
    StartReason,
    TaskExitReason,
)
from mod.telegram_remote_control.runtime_bridge import (
    RemoteRecoverySuppressed,
    raise_if_remote_recovery_disallowed,
    remote_stop_checkpoint,
    request_task_handoff,
)
from mod.telegram_remote_control.stop_orchestrator import (
    execute_recovery_suppressed_fallback,
    execute_remote_stop,
)
```

`FarmConfig.__init__`에 `_REMOTE_RUNTIME`, `_START_REASON`, `_TASK_RUN_ID`, `_REMOTE_HANDOFF_TARGET` 기본값 `None`을 추가한다.

watchdog가 adapter 등록 전에도 worker를 15초 안에 끝낼 수 있도록 `CheckAndRecoverDevice`의 직접 `time.sleep`을 다음 helper로 교체한다.

```python
def WaitForDeviceRecovery(setting, seconds):
    stop_event = getattr(setting, "_FORCESTOPING", None)
    if stop_event is None:
        time.sleep(seconds)
        return True
    return not stop_event.wait(seconds)
```

`CheckAndRecoverDevice`, 내부 `KillAdb`, `KillEmulator`, `StartEmulator`, ADB retry loop, Android boot wait는 각 반복 시작과 대기 직후 stop event를 확인하고 설정되면 `None`을 반환한다. 기존 subprocess 호출 하나의 timeout은 유지하되 새 subprocess를 시작하지 않는다. 이 변경은 로컬 즉시 중지의 ADB 초기화 지연도 함께 줄인다.

기존 자동 복구가 안전 정지 도중 게임이나 에뮬레이터를 다시 띄우지 않도록 `ResetDevice`와 `restartGame`의 실제 부작용보다 앞에 각각 아래 guard를 넣는다. `ResetDevice`의 `nonlocal` 선언은 guard보다 앞에 둬도 되지만 subprocess·kill·start보다 반드시 앞이어야 한다.

```python
raise_if_remote_recovery_disallowed(
    getattr(setting, "_REMOTE_RUNTIME", None),
    "reset_device",  # restartGame에서는 "restart_game"
)
```

adapter 등록 전 최초 `ResetDevice`에는 guard가 개입하지 않는다. adapter 등록 뒤 remote stop이 접수된 상태에서 기존 `DeviceShell`, `ScreenShot`, `FindCoordsOrElseExecuteFallbackAndWait`가 자동 복구를 요청하면 예외가 발생해 fallback으로 전환된다.

`Factory()` 안에 `BuildRemoteAdapter()`를 추가하되 callback 연결 외 로직은 넣지 않는다. 초기화 순서는 `ReloadStrategy → ResetDevice → LoadQuest → BuildRemoteAdapter → runtime.register_adapter → Telegram 로그인 gate → DungeonFarm/QuestFarm`으로 고정한다. quest를 먼저 읽어 adapter의 RTT callback이 로그인 gate 도중 들어온 stop에도 사용할 수 있게 한다. local 시작은 로그인 gate 한 단계만 건너뛴다. `ResetDevice`, `LoadQuest`, adapter 생성, 로그인 gate 중 어느 단계든 실패하면 Farm 본 루프를 시작하지 않고 단계별 `failure_phase`와 `ERROR`로 종료한다.

`LoadQuest(setting.FARM_TARGET)`가 `None`이면 `runtime.mark_exit(ERROR, "매크로 설정을 불러오지 못했습니다.", "load_quest")`, callback, return 순서로 끝낸다. Telegram 시작일 때만 `prepare_telegram_run(adapter, runtime)`를 호출한다. `False`면 함수가 runtime 종료 결과를 이미 기록했으므로 callback 후 반환한다.

```python
quest = LoadQuest(setting.FARM_TARGET)
if quest is None:
    runtime.mark_exit(TaskExitReason.ERROR, "매크로 설정을 불러오지 못했습니다.", "load_quest")
    setting._FINISHINGCALLBACK()
    return

adapter = BuildRemoteAdapter()
runtime.register_adapter(adapter, handoff_target=setting._REMOTE_HANDOFF_TARGET)
setting._REMOTE_HANDOFF_TARGET = None
if start_reason is StartReason.TELEGRAM and not prepare_telegram_run(adapter, runtime):
    setting._FINISHINGCALLBACK()
    return
```

`prepare_telegram_run` 내부의 `ensure_game_ready`가 마을·던전·전투·상자에서 stop 요청을 발견해 `RemoteStopSignal`을 발생시키면 이 분기보다 바깥의 `Farm` handler가 그대로 처리한다. `LoadQuest()`의 예상하지 못한 예외도 worker 오류 처리로 전달한다.

안전 정지 체크포인트는 아래 위치에만 넣는다.

1. `StateDungeon`, `case DungeonState.Dungeon`에서 전투 후 상태 해소가 끝난 뒤, `Press([1,1])`보다 앞
2. `DungeonFarm` 바깥 루프에서 force-stop 확인 직후
3. `DungeonFarm`이 `State.Inn` 또는 `State.EoT`를 처리하기 직전
4. `RestartableSequenceExecution`의 각 `op()` 실행 직전
5. `QuestFarm` 안의 기존 `_FORCESTOPING` 확인문 바로 다음

체크포인트 종류는 1번 `DUNGEON_STABLE`, 3번의 `State.Inn`만 `TOWN_STABLE`, 나머지는 `BETWEEN_OPERATIONS`를 사용한다. `State.EoT`는 마을이 아니라 마을 가장자리일 수 있으므로 `TOWN_STABLE`로 간주하지 않는다.

각 호출은 다음 형태를 사용한다.

```python
remote_stop_checkpoint(
    getattr(setting, "_REMOTE_RUNTIME", None),
    CheckpointKind.DUNGEON_STABLE,  # 위치에 따라 BETWEEN_OPERATIONS/TOWN_STABLE
)
```

체크포인트 함수는 stop 요청이 없으면 screenshot을 찍지 않고 즉시 반환한다. `StateCombat`와 `StateChest` 내부에는 remote 예외를 발생시키지 않는다. 이로써 전투와 상자 상호작용은 끝까지 처리된다.

`QuestFarm`의 `cursedWheel_timeLeap`/`ACTIVE_BEG_MONEY` 분기는 기존 두 줄을 아래 의미로 교체한다. runtime이 없는 레거시 직접 호출에서는 기존 handoff를 보존한다.

```python
if request_task_handoff(
    getattr(setting, "_REMOTE_RUNTIME", None),
    setting._MSGQUEUE,
    target=HANDOFF_TARGET_7000G,
    event_name="turn_to_7000G",
):
    raise SystemExit
continue
```

`HANDOFF_TARGET_7000G`는 `constants.py`에서 가져온다. `request_handoff`와 queue 입력 사이에는 게임 입력을 추가하지 않는다.

`Farm`의 예외 순서는 다음으로 고정한다.

```python
try:
    # 기존 시작 및 Farm 로직
except RemoteStopSignal as signal:
    execute_remote_stop(adapter, runtime, signal)
    setting._FINISHINGCALLBACK()
except RemoteRecoverySuppressed as suppressed:
    execute_recovery_suppressed_fallback(adapter, runtime, suppressed)
    setting._FINISHINGCALLBACK()
except TaskStoppedException:
    # 기존 처리, runtime 결과가 있으면 그 종료 사유 보존
except RestartSignal:
    # 기존 처리
```

remote 복귀 코드에서 `setting._FORCESTOPING`을 설정하지 않는다. watchdog 폴백이나 로컬 즉시 중지만 이 이벤트를 설정한다.

기존 `tools/test_upstream_247_merge.py`처럼 `sys.path`에 `src`만 추가한 뒤 `import script`하는 회귀 테스트를 반드시 실행해 `mod` 경로 연결로 인한 import 실패가 없음을 확인한다.

### 19.11 안전 정지와 마을 복귀 알고리즘

```python
def return_to_town(
    adapter: GameAutomationAdapter,
    runtime: RemoteRuntime,
    signal: RemoteStopSignal,
) -> TransitionOutcome:
    ...
```

진입 즉시 `runtime.report_progress(RETURNING_TO_TOWN, "마을로 복귀 중입니다.")`를 호출한다. 이미 타이틀이면 `AT_TITLE`, 마을 2프레임 확인 시 `TOWN_READY`, 로컬 중지 시 `LOCAL_ABORT`, 강제 종료 성공 시 `FALLBACK_COMPLETE`, 그 외 복구 불가 오류는 `ERROR`를 반환한다.

`remote_stop_checkpoint`는 stop 요청 중일 때만 화면을 확인한다.

- 명시적으로 `DUNGEON_STABLE` 또는 `TOWN_STABLE`이면 즉시 `RemoteStopSignal`
- `BETWEEN_OPERATIONS`이면 화면을 한 번 분류
- `dungFlag`, `mapFlag`, `Inn`, 도시, `worldmapflag`, `openworldmap`, `returntotown`이면 안전 신호
- 전투, 상자, 로딩, 알 수 없는 화면이면 반환하고 다음 체크포인트까지 기다림
- deadline 초과는 자체 ADB 명령을 실행하지 않고 watchdog에 맡김

`return_to_town` 화면 판정 우선순위:

1. 타이틀 로고 + Tap to Start
2. 전투
3. 상자
4. 전리품·결과 화면의 `dialogueNext`(화면 우하단 ROI)
5. `ReturnText`
6. `returntotown`
7. `mapFlag`
8. `worldmapflag`, `openworldmap`
9. `Inn`, 도시
10. `dungFlag`
11. retry/로딩/unknown

동작:

- 이미 타이틀: 마을 복귀를 생략했다는 detail과 함께 성공
- 전투·상자: `run_bounded_operation(finish_combat_or_chest, overall_deadline)` 후 재판정
- `dialogueNext`: 활성 상자 UI가 아님을 먼저 확인한 뒤 우하단 ROI에서 0.80 이상으로 일치한 좌표를 누르고 0.35초 후 재판정. 여러 전리품 페이지도 같은 단계에서 연속 처리
- `mapFlag`: Back 한 번 후 `dungFlag` 확인
- `dungFlag`: `leaveDung` 아이콘을 누르고 `ReturnText` 대기
- `ReturnText`: 해당 버튼 중심을 한 번 누름
- `returntotown`: `edge_to_town` 단계로 전환하고 60초 deadline 설정. 최초 진입과 이후 2초 cooldown마다 `press_back()`, 0.2초 대기, `press([1, 1])`을 순서대로 한 번씩 보내고 화면을 재판정
- 월드맵: 180초 단계 deadline으로 `run_bounded_operation(return_via_quest_rtt, ...)` 호출
- `Inn`/도시: 0.5초 간격 2회 확인 후 성공
- retry: 기존 retry 처리
- unknown: 임의 좌표를 누르지 않고 0.5초 후 재확인

`ACTIVE_REST`는 읽지 않는다. `_RTT`가 없고 60초 안에 던전 이탈 UI를 찾지 못하거나, RTT 시작 후 180초 안에 마을을 확인하지 못하면 실패 프레임을 저장하고 즉시 `force_stop_game_once`를 호출한다. watchdog도 같은 함수를 사용하므로 중복 ADB 강제 종료는 발생하지 않는다. 모든 단계는 600초 전체 deadline을 공유한다.

`edge_to_town`은 기존 `FindCoordsOrElseExecuteFallbackAndWait`를 호출하지 않는다. 그 함수는 자체 실패 시 게임 재시작을 수행하므로 안전 정지 경로와 호환되지 않는다. 60초 안에 `Inn`/도시 2프레임을 확인하지 못하면 `failure_phase="edge_to_town"`으로 바로 fallback한다.

`BoundedOperationTimeout`이나 callback 예외가 발생하면 `failure_phase`를 `finish_interaction`, `edge_to_town`, `quest_rtt` 중 해당 값으로 기록한다. `adapter.local_stop_exception_type`과 일치하는 예외만 `LOCAL_ABORT`로 바꾸고, 그 외 예외는 실패 프레임 저장 후 fallback을 호출한다.

`stop_orchestrator.py`는 두 상태 머신과 종료 사유 매핑을 `src` 밖에서 조립한다.

```python
def execute_remote_stop(
    adapter: GameAutomationAdapter,
    runtime: RemoteRuntime,
    signal: RemoteStopSignal,
) -> TransitionOutcome:
    try:
        result = return_to_town(adapter, runtime, signal)
        if result.status is TransitionStatus.TOWN_READY:
            result = return_town_to_title(adapter, runtime)
    except RemoteRecoverySuppressed as suppressed:
        return execute_recovery_suppressed_fallback(adapter, runtime, suppressed)

    if result.status is TransitionStatus.AT_TITLE:
        runtime.mark_exit(TaskExitReason.REMOTE_STOP, result.detail)
    elif result.status is TransitionStatus.FALLBACK_COMPLETE:
        runtime.mark_exit(
            TaskExitReason.REMOTE_STOP_FALLBACK,
            result.detail,
            result.failure_phase,
        )
    elif result.status is TransitionStatus.LOCAL_ABORT:
        runtime.mark_exit(TaskExitReason.LOCAL_STOP, result.detail)
    else:
        runtime.mark_exit(
            TaskExitReason.ERROR,
            result.detail or "안전 정지 작업에 실패했습니다.",
            result.failure_phase or "stop_orchestrator",
        )
    return result
```

이 함수는 `_FINISHINGCALLBACK`을 호출하지 않고 worker force-stop event도 직접 설정하지 않는다. 예상하지 못한 Python 예외는 삼키지 않아 `run_farm_worker`가 기록하게 한다. `TOWN_READY` 외 상태에서는 타이틀 전환을 호출하지 않는다.

```python
def execute_recovery_suppressed_fallback(
    adapter: GameAutomationAdapter,
    runtime: RemoteRuntime,
    suppressed: RemoteRecoverySuppressed,
) -> TransitionOutcome:
    phase = f"suppressed_{suppressed.operation}"
    result = force_stop_game_once(adapter, runtime, failure_phase=phase)
    if result.status is TransitionStatus.FALLBACK_COMPLETE:
        runtime.mark_exit(
            TaskExitReason.REMOTE_STOP_FALLBACK,
            result.detail,
            phase,
        )
    elif result.status is TransitionStatus.LOCAL_ABORT:
        runtime.mark_exit(TaskExitReason.LOCAL_STOP, result.detail, phase)
    else:
        runtime.mark_exit(TaskExitReason.ERROR, result.detail, phase)
    return result
```

이 함수도 callback을 호출하지 않는다. operation 값은 `reset_device` 또는 `restart_game`만 허용하며 다른 값은 `suppressed_unknown`으로 정규화한다.

### 19.12 원격 시작과 로그인 gate

`ensure_game_ready`와 이를 감싸는 `prepare_telegram_run`은 Telegram 시작에서만 실행한다. 로컬 시작의 기존 동작을 변경하지 않는다.

```python
def prepare_telegram_run(
    adapter: GameAutomationAdapter,
    runtime: RemoteRuntime,
) -> bool:
    result = ensure_game_ready(adapter, runtime)
    if result.status is TransitionStatus.GAME_READY:
        runtime.report_progress(
            ControlState.RUNNING,
            "게임 로그인과 매크로 준비가 완료되었습니다.",
        )
        return True
    if result.status is TransitionStatus.AT_TITLE and runtime.is_stop_requested():
        runtime.mark_exit(TaskExitReason.REMOTE_STOP, result.detail)
    elif result.status is TransitionStatus.FALLBACK_COMPLETE:
        runtime.mark_exit(
            TaskExitReason.REMOTE_STOP_FALLBACK,
            result.detail,
            result.failure_phase,
        )
    elif result.status is TransitionStatus.LOCAL_ABORT:
        runtime.mark_exit(TaskExitReason.LOCAL_STOP, result.detail)
    else:
        runtime.mark_exit(
            TaskExitReason.ERROR,
            result.detail or "게임 로그인에 실패했습니다.",
            result.failure_phase or "login_gate",
        )
    return False
```

`prepare_telegram_run`은 callback을 호출하지 않으며 `RemoteStopSignal`을 잡지 않는다. start-complete 알림은 이 함수가 보낸 `RUNNING` progress를 feature가 처리할 때 생성한다.

각 판정 루프 시작과 모든 입력 직전에 runtime stop event를 확인한다. `/stop`이 `STARTING` 중 도착하면 다음처럼 처리한다.

- 게임 process가 없으면 새로 실행하지 않고 `force_stop_game_once(..., failure_phase="game_not_running_on_stop")`로 미실행 상태를 검증해 `FALLBACK_COMPLETE` 반환
- 현재 화면이 타이틀이면 입력하지 않고 `TransitionStatus.AT_TITLE` 반환
- 마을이면 `RemoteStopSignal(TOWN_STABLE)` 발생
- 던전·지도·월드맵이면 해당 `CheckpointKind`의 `RemoteStopSignal` 발생
- 전투·상자면 `adapter.finish_combat_or_chest`로 현재 상호작용을 끝낸 뒤 `RemoteStopSignal(DUNGEON_STABLE)` 발생
- 로딩·unknown이면 입력 없이 actionable 화면을 기다리며 600초 stop watchdog이 상한을 보장

stop event가 설정된 뒤에는 Tap to Start, 중앙 탭, retry를 포함한 로그인용 입력을 새로 보내지 않는다.

local stop event가 설정됐거나 adapter callback에서 `local_stop_exception_type`이 발생하면 즉시 `LOCAL_ABORT`를 반환한다. remote stop과 local stop이 같은 lock 구간에서 경쟁하면 19.8.3의 소유권 규칙대로 먼저 확정된 local stop이 우선한다.

시도별 알고리즘:

1. `pidof GAME_PACKAGE` 확인
2. 프로세스가 없으면 `cmd package resolve-activity --brief GAME_PACKAGE` 실행
3. 결과를 trim하고 `^jp\.co\.drecom\.wizardry\.daphne/[A-Za-z0-9_.$]+$`와 일치할 때만 사용하며, 그 외에는 `DEFAULT_GAME_ACTIVITY` 사용
4. `am start -n <activity>` 후 10초 대기
5. 화면을 1초 간격으로 판정

판정 우선순위와 동작:

| 화면 | 동작 |
| --- | --- |
| 기존 `totitle` 세션 만료 버튼 | 배경 표식보다 먼저 버튼을 누르고 타이틀 대기 |
| `Inn`, 도시, `dungFlag`, 전투, 상자, `worldmapflag`, `openworldmap`, `returntotown` | READY 반환 |
| 타이틀 로고 + Tap to Start | Tap to Start 중심을 한 번 누름 |
| `startdownload`, `retry`, `retry_blank` | 기존 retry 처리 |
| `abyssReadying`, 검은 화면 | 입력 없이 대기 |
| unknown | 입력 없이 대기하고 시도 timeout 시 실패 프레임 저장 |

세션 만료 팝업 뒤의 타이틀 로고나 게임 표식도 동시에 검출될 수 있으므로 `totitle`은 모든 배경 상태보다 먼저 판정한다.

180초 안에 READY가 아니면 `am force-stop`, `am start`로 게임을 한 번 재시작하고 두 번째 180초 시도를 수행한다. 두 번째도 실패하면 실패 프레임을 저장하고 `ERROR`로 종료한다.

unknown 화면에서는 중앙·`[1,1]`·generic OK를 누르지 않는다. 로그인 ID·비밀번호 입력, 새 약관 또는 새 공지처럼 템플릿이 없는 화면은 사용자에게 `저장된 게임 세션으로 자동 진입하지 못했습니다.`를 보내고 매크로를 시작하지 않는다.

READY 직후에만 다음 시작 완료 알림을 보낸다.

```text
▶️ 동작 시작 완료
매크로: {farm_target_text}
상태: 실행 중
```

### 19.13 GUI와 모듈 전용 로케일

`settings_ui.py`의 공개 함수 시그니처는 다음으로 고정한다.

```python
def mount_telegram_settings(
    parent,
    *,
    enabled_var,
    token_var,
    chat_id_var,
    event_queue,
    save_config,
    translator,
) -> TelegramSettingsWidgets:
    ...
```

`TelegramSettingsWidgets`는 `section`, `enabled_check`, `token_entry`, `chat_id_entry`, `apply_button`, `test_button`, `status_label`, `active_test_request_id`를 가진다.

레이아웃은 다음 순서다.

1. `원격 제어 사용` 체크박스
2. `Bot Token` 마스킹 Entry(`show="*"`)
3. `허용 Chat ID` Entry
4. `저장 및 적용`, `연결 테스트` 버튼
5. 연결 상태 레이블

`저장 및 적용` 동작:

1. 현재 Tk 변수로 `TelegramSettings` 생성
2. `config.validate_telegram_settings` 호출
3. 실패하면 저장하지 않고 status label에 공개 오류 표시
4. 성공하면 기존 `ConfigPanelApp.save_config()` 호출
5. `event_queue.put(("telegram_reconfigure", None))`

기존 일반 `save_config()` 호출은 Telegram service를 재시작하지 않는다. 오직 이 적용 버튼과 원격 제어 사용 체크박스 변경만 reconfigure를 요청한다. 체크박스를 끄면 즉시 저장·적용하고 polling을 중단한다.

`연결 테스트` 동작:

1. 현재 입력값을 검증하되 config 파일에 저장하지 않음
2. `request_id=uuid.uuid4().hex` 생성
3. `ConnectionTestRequest`를 `telegram_test_connection` 이벤트로 전달
4. test 버튼만 비활성화하고 status를 `연결 확인 중...`으로 표시
5. background worker가 `getMe` 후 설정 Chat ID에 `WvDAS 연결 테스트가 완료되었습니다.` 전송
6. 같은 request ID의 `telegram_test_result`를 받으면 버튼 복구 및 결과 표시
7. 20초 안에 결과가 없으면 GUI timeout으로 버튼을 복구하되 background 요청을 강제 종료하지 않음

연결 테스트 설정 객체는 메모리에만 존재하며 logger에 출력하지 않는다. 서비스가 이미 실행 중이어도 테스트는 서비스 generation이나 polling offset을 변경하지 않는다.

`i18n.py`는 기존 설정의 `LANGUAGE` 값을 받아 독립 도메인을 로드한다.

```python
gettext.translation(
    "telegram_remote_control",
    localedir=module_locale_path,
    languages=[language],
    fallback=True,
)
```

`module_locale_path`는 개발 환경에서 `Path(__file__).resolve().parent / "locale"`, frozen 환경에서 `Path(sys._MEIPASS) / "mod/telegram_remote_control/locale"`다. `language`은 `ko_KR`, `en_US`, `zh_CN`만 허용하고 그 외 값은 `ko_KR`로 정규화한다. `fallback=True`이더라도 배포 전에 locale 테스트가 필수 msgid의 빈 번역을 거부한다.

필수 한국어 msgid/표시 문구:

- 텔레그램 원격 제어
- 원격 제어 사용
- Bot Token
- 허용 Chat ID
- 연결 테스트
- 저장 및 적용
- 연결 확인 중...
- WvDAS 연결 테스트가 완료되었습니다.
- 연결됨 / 연결 실패
- 동작 요청을 접수했습니다.
- 안전 정지 요청을 접수했습니다.
- 전투 또는 상자 작업이 끝나기를 기다리는 중입니다.
- 마을로 복귀 중입니다.
- 타이틀 화면으로 이동 중입니다.
- 종료 작업 완료
- 종료 작업 비정상 완료
- 즉시 중지

한국어·영어·중국어 `.po`에 모든 항목을 채운다. 한국어와 영어는 번역되지 않은 중국어 문자열이 하나라도 있으면 locale 테스트를 실패시킨다.

문자열을 추가·변경할 때의 개발 명령:

```powershell
python -m babel.messages.frontend extract `
  -F mod/telegram_remote_control/babel.cfg `
  -o mod/telegram_remote_control/locale/telegram_remote_control.pot `
  mod/telegram_remote_control
python -m babel.messages.frontend update `
  -i mod/telegram_remote_control/locale/telegram_remote_control.pot `
  -d mod/telegram_remote_control/locale `
  -D telegram_remote_control
```

`babel.cfg` 내용은 다음으로 고정해 `tests/` 문자열을 번역 카탈로그에 넣지 않는다.

```ini
[ignore: tests/**]
[python: **.py]
```

update 후 세 언어의 fuzzy·빈 msgstr을 모두 해소한 뒤 compile한다. 생성된 세 `.mo`도 추적해 기존 `run.bat`가 루트 locale만 compile하더라도 `python src/main.py` 실행에서 모듈 번역을 즉시 읽을 수 있게 한다. `.po`를 바꾼 커밋에서 대응 `.mo`가 달라지지 않으면 locale 테스트를 실패시킨다.

### 19.14 타이틀 이미지 자산 획득 절차

타이틀 자산은 다음 절차로 획득하고 검증한다.

1. 1600x900, 영어 UI에서 수동으로 타이틀 화면까지 이동
2. 시작 안내와 타이틀 화면을 각각 ADB `screencap -p`로 무손실 캡처
3. 계정명·알림 등 개인 정보가 보이지 않는지 확인하고 원본을 `tests/fixtures/title_screen_900x1600.png`로 저장
4. 게임 로고의 정적인 부분을 최소 여백으로 잘라 `resources/images/titlelogo.png` 저장
5. `Tap to Start` 문구가 가장 밝은 프레임을 잘라 `resources/images/tabtostart.png` 저장
6. 시작 안내 문구 한 줄을 잘라 `resources/images/startupDisclaimer.png` 저장
7. 원본에서 세 템플릿이 각각 0.88 이상 일치하는지 검사
8. 로딩·마을·종료 메뉴 화면에서는 `titlelogo` 조건이 성립하지 않는지 검사

MuMu 창 설정은 1600x900이지만 현재 ADB 캡처와 좌표계는 세로 `900x1600`이다. 자산 검증은 `image.shape[:2] == (1600, 900)`을 요구한다. 다른 크기면 템플릿을 만들거나 런타임 resize하지 말고 캡처 환경을 먼저 바로잡는다.

템플릿 둘 중 하나가 없으면 `match_mod`는 조용히 `None`을 반환하지 않고 설정 오류를 발생시킨다. PyInstaller 스모크 테스트도 두 파일 존재 여부를 검사한다.

### 19.15 자동 테스트 명세

테스트는 표준 `unittest`만 사용하고 실제 Telegram, ADB, Tk mainloop를 호출하지 않는다. fake clock은 `monotonic`, `sleep`, `datetime`을 주입받아 대기 없이 timeout을 진행한다.

#### 파일별 최소 테스트

| 테스트 파일 | 필수 시나리오 |
| --- | --- |
| `test_bot_api.py` | fake urlopen의 정상 JSON, 401/403/409/429/5xx/timeout/손상 JSON, token redaction |
| `test_commands.py` | 여섯 명령 별칭, bot suffix, unknown, 개인 채팅 인증, 비허가 무응답 |
| `test_service.py` | startup offset 폐기, update 중복 제거, 401/409/429/5xx, terminal 재시도·중복 방지, reconfigure stale 응답 폐기, disable 대기·재활성화 |
| `test_adapters.py` | 실제 title fixture 양성 일치, ROI 좌표 환산, threshold 미달, template 과대, 누락·decode 실패 |
| `test_runtime_bridge.py` | stop idempotency, deadline, 명시 clock 완료 payload, bounded timeout, handoff queue rollback, adapter handoff 교체, 등록 전/후 recovery guard |
| `test_state_machine.py` | 모든 허용 전이, 금지 전이, 중복 start/stop, 600초 watchdog 단일 실행 |
| `test_title_transition.py` | town→Back→To Title→2프레임 title, 로딩 무입력, unknown 무입력, 3회 Back 제한 |
| `test_return_to_town.py` | combat/chest 우선순위, 전리품 `dialogueNext` 연속 처리, map Back, ReturnText, RTT, ACTIVE_REST 무관, town 2프레임 |
| `test_stop_orchestrator.py` | town→title 연결, 이미 title, fallback/local/error 종료 사유 매핑, recovery suppression 폴백, callback 미호출 |
| `test_login_transition.py` | 실행 중 READY, 앱 start, title tap, retry, 2회 180초 실패 |
| `test_config.py` | 기본 비활성, token/chat 검증, task-specific merge, 명시 config 오류, secret 제거 |
| `test_fallback.py` | adapter/외부 ADB 강제 종료, pidof 검증, 단일 owner, 검증 실패 ERROR |
| `test_worker.py` | callback 정확히 한 번, 예외 종료, 등록된 SystemExit handoff, 미등록 SystemExit 오류, stop/handoff 경쟁, worker 종료 확인 순서 |
| `test_i18n.py` | Babel로 세 `.po`를 읽어 필수 msgid·fuzzy·빈 번역 검사, 한국어·영어 중국어 폴백 없음, `write_mo(BytesIO)` 결과와 추적 `.mo` byte 일치 |
| `test_integration_hooks.py` | `src`에 필수 import·체크포인트·queue event가 있고 구현 본체가 들어가지 않음 |

`test_integration_hooks.py`는 `ast` 또는 소스 구간 검색으로 다음을 보장한다.

- `CONFIG_VAR_LIST` 확장이 정확히 한 번
- `StateCombat`, `StateChest` 내부에 `RemoteStopSignal` 발생 코드가 없음
- `StateDungeon`의 remote checkpoint가 이동 입력보다 앞
- title transition에서 `IdentifyState`, `HandleBlockingOverlay`, 중앙 임의 탭 호출이 없음
- Telegram 시작에서만 `ensure_game_ready` 호출
- `_FORCESTOPING`이 원격 정지 접수 직후 설정되지 않음
- terminal 완료 알림이 `AT_TITLE`과 worker 종료 확인 뒤 생성됨
- `turn_to_7000G` 분기에서 stop checkpoint → handoff 등록 → run ID queue 입력 순서가 유지됨
- `CheckAndRecoverDevice`의 모든 장기 대기와 retry 경로가 worker force-stop event를 확인함
- `ResetDevice`와 `restartGame`의 부작용 전에 remote recovery guard가 호출됨

#### 실행 순서

```powershell
python -m babel.messages.frontend compile -d locale -D messages
python -m babel.messages.frontend compile `
  -d mod/telegram_remote_control/locale `
  -D telegram_remote_control
python -m unittest discover -s mod/telegram_remote_control/tests -p "test_*.py" -v

$failedTests = @()
Get-ChildItem -LiteralPath tools -Filter 'test_*.py' | Sort-Object Name | ForEach-Object {
    & python $_.FullName
    if ($LASTEXITCODE -ne 0) { $failedTests += $_.Name }
}
if ($failedTests.Count -gt 0) {
    throw "기존 테스트 실패: $($failedTests -join ', ')"
}
```

저장소에 pytest가 없으므로 pytest 전용 fixture나 plugin을 추가하지 않는다. 테스트 도중 실제 네트워크나 에뮬레이터가 필요한 경우는 단위 테스트 실패가 아니라 설계 위반이며 반드시 fake adapter/client로 바꾼다.

### 19.16 빌드 변경과 스모크 테스트

추적되는 `.github/workflows/build-executable.yml`의 빌드 앞에 모듈 테스트와 모듈 번역 컴파일을 추가한다. PyInstaller 명령은 아래 옵션을 포함한다.

```powershell
pyinstaller --onedir --paths "." `
  --add-data "resources;resources/" `
  --add-data "locale;locale/" `
  --add-data "mod/telegram_remote_control/locale;mod/telegram_remote_control/locale/" `
  src/main.py -n wvd
```

빌드 후 다음 명령 또는 동등한 unittest로 확인한다.

- `dist/wvd/_internal/resources/images` 아래 `startupDisclaimer`, `titlelogo`, `tabtostart` 템플릿 존재
- 모듈 locale 아래 각 언어의 `telegram_remote_control.mo` 존재
- `dist/wvd/wvd.exe --help`가 import 오류 없이 종료 코드 0
- 토큰이 없는 기본 config에서 EXE가 Telegram 오류로 종료되지 않음

로컬에서 사용하는 ignored spec/bat는 개발 편의를 위해 같은 옵션으로 갱신할 수 있지만, PR의 재현 가능한 기준은 추적되는 workflow다.

### 19.17 구현 순서와 단계별 종료 조건

Luna 구현자는 다음 순서를 바꾸지 않는다.

구현 시작 전에 `git status --short`를 기록한다. 이미 존재하는 `src/smart_disarm.py`, `tools/test_smart_disarm_state.py` 등의 사용자 변경은 읽기만 하고 수정·되돌림·stage하지 않는다. 텔레그램 구현 파일과 의도한 연결 파일만 명시적으로 stage한다.

1. 패키지·`constants.py`·`models.py`·`config.py` 작성 → config 테스트 통과
2. `bot_api.py` 작성 → HTTP 오류·토큰 마스킹 테스트 통과
3. `command_service.py` 작성 → 명령·offset·재시도 테스트 통과
4. `adapters.py`·`runtime_bridge.py`·`worker.py` 작성 → adapter·runtime·정확히 한 번 완료 테스트 통과
5. `fallback.py` 작성 → 단일 owner·process 검증 테스트 통과
6. `return_to_town.py` 작성 → fake adapter 테스트 통과
7. 타이틀 실제 이미지 확보 → `title_transition.py` 테스트 통과
8. `login_transition.py` 작성 → 앱 종료/타이틀/READY 테스트 통과
9. `stop_orchestrator.py` 작성 → 모든 종료 사유 매핑 테스트 통과
10. `feature.py` 작성 → start/stop/status/watchdog 테스트 통과
11. `src/script.py` 체크포인트와 adapter 연결 → 기존 runtime 테스트 통과
12. `src/main.py` 큐와 worker 생명주기 연결 → 중복 실행·종료 순서 테스트 통과
13. `settings_ui.py`와 `src/gui.py` 연결 → 저장·재구성 수동 확인
14. 모듈 locale 작성·컴파일 → 3개 언어 테스트 통과
15. PyInstaller workflow 갱신 → onedir 스모크 테스트 통과
16. 실제 에뮬레이터에서 16.4의 10개 시나리오 수행
17. `README.md`에 설정법·명령·WvDAS 상주 제한을 추가하고 `CHANGES_LOG.md`에 새 기능과 보안 제한을 기록
18. `src/main.py` 버전을 `2.5.4-momo.6`로 올리고 UI·업데이트 표시를 확인
19. 텔레그램 관련 파일만 명시적으로 stage·commit하고 저장소 규칙에 따라 origin PR을 갱신

각 단계에서 실패한 테스트를 건너뛰고 다음 단계로 진행하지 않는다.

Git 단계에서는 `upstream`에 절대 push하지 않는다. 먼저 `git remote get-url origin`으로 방식만 확인한다. origin이 HTTPS라면 사용자가 금지한 `git-remote-https.exe`를 실행하지 말고 로컬 커밋을 보존한 채 push·PR 미완료를 보고한다. 허용된 비-HTTPS origin으로 push할 수 있을 때만 기존 열린 PR을 갱신하거나 base `master`의 새 PR을 만든다.

### 19.18 구현 금지 사항

- Bot Token을 URL, logger, 예외, 테스트 fixture, 스크린샷 파일명에 기록하지 않는다.
- Telegram background thread에서 Tk 위젯이나 `AppController` 메서드를 직접 호출하지 않는다.
- 원격 정지 접수 시 `_FORCESTOPING`을 설정하지 않는다.
- 전투·상자 함수 내부에서 안전 정지 예외를 발생시키지 않는다.
- 타이틀 정지 경로에서 `IdentifyState`, `HandleSessionExpiry`, `HandleBlockingOverlay`를 호출하지 않는다.
- 알 수 없는 타이틀 전환 화면에서 중앙, `[1,1]`, generic `OK`, generic `Close`를 누르지 않는다.
- 기존 `quit.png`를 게임 종료 메뉴용으로 재사용하지 않는다.
- `src` 코드를 `mod`로 복사하거나 monkey patch하지 않는다.
- 기존 스마트 개봉, 전투, 복구 로직을 텔레그램 기능과 함께 리팩터링하지 않는다.
- remote stop 접수와 adapter 등록 뒤에는 기존 `restartGame`, ADB 재시작, 에뮬레이터 재시작을 실행하지 않는다. guard 예외를 단일 package force-stop 폴백으로 바꾼다.
- `config.json`, runtime log, 실제 Bot Token, 분석 스크린샷을 커밋하지 않는다.
- 구현 시작 전부터 존재한 사용자 변경을 되돌리거나 텔레그램 기능 커밋에 포함하지 않는다.

### 19.19 구현 완료 보고 형식

구현 완료 보고에는 다음을 빠짐없이 포함한다.

1. 생성한 `mod/telegram_remote_control` 파일 목록
2. 기존 `src`에 추가한 연결 지점 요약
3. 실행한 모든 unittest와 결과
4. 번역 컴파일 결과
5. PyInstaller 빌드 및 EXE 스모크 결과
6. 실제 Telegram/에뮬레이터에서 검증한 시나리오와 미검증 시나리오
7. 토큰·로그·개인 설정이 변경 목록에 없다는 확인
8. 남은 제한 사항, 특히 WvDAS 종료 시 명령을 받을 수 없다는 점

## 20. 공식 외부 계약 참고

2026-08-13 기준으로 아래 공식 문서와 19.5~19.6의 HTTP 계약을 대조했다.

- [Telegram Bot API — getUpdates](https://core.telegram.org/bots/api#getupdates): 음수 offset, update 확인 방식, long polling timeout, webhook과의 상호 배타성
- [Telegram Bot API — Making requests](https://core.telegram.org/bots/api#making-requests): `ok`, `result`, `error_code`, `description`, `parameters.retry_after` 응답 구조
- [Telegram Bots FAQ — Getting Updates](https://core.telegram.org/bots/faq#getting-updates): `last_update_id + 1` offset으로 중복 update를 확인 처리하는 규칙

외부 API가 변경되면 이 절과 `test_bot_api.py`, `test_service.py`를 함께 갱신한다. 공식 문서와 충돌하는 동작을 추측으로 유지하지 않는다.
