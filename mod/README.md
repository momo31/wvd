# Mod source policy

`telegram-remote-control-design.md`에 따른 신규 기능은
`mod/telegram_remote_control/` 패키지 아래에 구현한다.

- 신규 기능 본체, 테스트, 이미지 및 번역 리소스는 모두 `mod` 아래에 둔다.
- 기존 `src`에는 import, 생명주기 훅, 안전 정지 체크포인트와 adapter 연결만 추가한다.
- 기존 로직을 복사하거나 `mod`에서 monkey patch 하지 않는다.
- 상세 구조와 인터페이스는 [`docs/telegram-remote-control-design.md`](../docs/telegram-remote-control-design.md)를 따른다.
