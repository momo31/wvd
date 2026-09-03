# 빌드 및 배포 절차

## 원칙

- 기능·회귀·실기기 테스트는 개발 단계에서 완료된 것으로 간주한다.
- 사용자가 빌드만 요청하면 스테이징 산출물 생성에서 끝낸다. 실행 중인 배포본과 `dist\wvd`는 건드리지 않는다.
- 빌드 단계에서는 테스트 스위트, exe 실행, 스모크 테스트, Tcl/Tk·리소스·해시 검증을 수행하지 않는다.
- 배포는 사용자가 명시적으로 요청한 경우에만 수행하며, 유일한 검증은 사용자 데이터 보존 확인이다.

## 빌드

Windows 실행 파일은 저장소의 Python 3.14 빌드 환경과 `wvd.spec`을 사용한다. 사용자 데이터가 있는 `dist\wvd`를 PyInstaller의 `--clean` 대상으로 사용하지 않는다.

```powershell
$repoRoot = [IO.Path]::GetFullPath((Get-Location).Path)
$stageName = "release-stage-{0}" -f (Get-Date -Format 'yyyyMMdd-HHmmss')
$stageRoot = Join-Path $repoRoot "build\$stageName"

if (Test-Path -LiteralPath $stageRoot) {
    throw "기존 스테이징 경로를 재사용하지 않습니다: $stageRoot"
}

New-Item -ItemType Directory -Path $stageRoot | Out-Null
build\wvd_py314_venv\Scripts\pyinstaller.exe `
    --clean `
    --noconfirm `
    --distpath (Join-Path $stageRoot 'dist') `
    --workpath (Join-Path $stageRoot 'work') `
    wvd.spec

if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller 실패: $LASTEXITCODE"
}

$stagedDeploy = Join-Path $stageRoot 'dist\wvd'
Copy-Item -LiteralPath 'CHANGES_LOG.md' -Destination $stagedDeploy
```

빌드 요청은 여기서 종료한다. 산출물을 실행하거나 `dist\wvd`에 복사하지 않는다.

## 배포

다음 사용자 데이터는 교체 대상이 아니다.

- `dist\wvd\config.json`
- `dist\wvd\logs`
- `dist\wvd\audit`

1. 실행 중인 `wvd.exe`의 실제 경로를 확인하고, `dist\wvd\wvd.exe`인 경우에만 해당 PID를 종료한다.
2. 보호 대상 파일의 상대 경로, 크기, SHA-256을 기록한다.
3. 배포 경로와 이동 대상의 절대 경로가 저장소의 `dist\wvd`와 해당 스테이징 폴더 안인지 확인한다.
4. 기존 `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 `$stageRoot\previous-deploy`로 이동한다.
5. 새 `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 `dist\wvd`로 이동한다.
6. 중간 단계가 실패하면 프로그램 파일 교체를 롤백한다.
7. 보호 대상의 상대 경로, 크기, SHA-256이 배포 전과 동일한지 확인한다.

배포된 exe는 실행하거나 테스트하지 않는다. 기존 프로그램 파일 백업은 사용자가 새 실행 파일을 확인할 때까지 유지한다.
