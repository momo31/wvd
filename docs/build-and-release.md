# 빌드 및 배포 재발 방지 절차

## Python/PyInstaller 환경

Windows 실행 파일은 저장소에 포함된 Python 3.14 빌드 환경을 사용한다.

```powershell
build\wvd_py314_venv\Scripts\pyinstaller.exe --clean --noconfirm wvd.spec
```

Python 3.11 전역 환경의 PyInstaller는 Tcl/Tk를 정상적으로 탐지하지 못할 수 있다. 이 환경으로 빌드하면 `tkinter`가 exe에서 누락되어 다음 오류가 발생할 수 있으므로 사용하지 않는다.

```text
ModuleNotFoundError: No module named 'tkinter'
```

## 빌드 후 필수 확인

1. `dist\wvd\wvd.exe`가 생성되었는지 확인한다.
2. 실행 파일을 직접 5초 이상 실행해 초기 오류가 없는지 확인한다.
3. 실행 여부 확인 후 테스트 프로세스를 종료한다.
4. `tkinter` 누락 오류가 있으면 배포하지 않고 Python 3.14 빌드 환경으로 다시 빌드한다.
5. 최종 exe의 SHA-256 해시와 배포 경로를 기록한다.

기존 실행 파일이 실행 중이면 먼저 종료한 뒤 빌드·교체한다. 사용자 설정 파일과 로그는 배포 파일 교체 대상에 포함하지 않는다.
