# 빌드 및 배포 재발 방지 절차

## 검증된 빌드 환경

Windows 실행 파일은 저장소에 포함된 Python 3.14 빌드 환경만 사용한다. 빌드 전에 버전과 `tkinter`를 직접 확인한다.

```powershell
build\wvd_py314_venv\Scripts\python.exe --version
build\wvd_py314_venv\Scripts\python.exe -c "import tkinter; print(tkinter.TkVersion)"
build\wvd_py314_venv\Scripts\pyinstaller.exe --version
```

2026-08-18에 성공한 기준 환경은 Python 3.14.6, Tcl/Tk 8.6, PyInstaller 6.22.0이다. Python 3.11 전역 환경의 PyInstaller는 Tcl/Tk 탐지에 실패할 수 있으므로 사용하지 않는다.

## 사용자 데이터 보호와 사전 확인

기존 `dist\wvd`에는 교체 가능한 프로그램 파일과 사용자 데이터가 함께 있다. 다음 항목은 배포 파일 교체 대상이 아니다.

- `dist\wvd\config.json`
- `dist\wvd\logs`
- `dist\wvd\audit`

빌드 전에 다음을 수행한다.

1. `git status --short --branch`와 빌드할 커밋을 기록한다.
2. 실행 중인 `wvd.exe`의 실제 경로를 확인한다.
3. 교체 대상인 `dist\wvd\wvd.exe`가 실행 중일 때만 해당 PID를 종료하고 종료 여부를 확인한다. 이름만 보고 다른 위치의 프로세스를 종료하지 않는다.
4. `config.json`의 SHA-256과 로그 파일 수·전체 크기를 기록한다.

기존 `dist\wvd`가 있는 상태에서 아래 기본 명령을 그대로 실행하면 `--clean` 또는 COLLECT 단계에서 사용자 데이터를 잃을 수 있다.

```powershell
build\wvd_py314_venv\Scripts\pyinstaller.exe --clean --noconfirm wvd.spec
```

따라서 실제 빌드는 반드시 별도 스테이징 경로를 사용한다.

## 스테이징 빌드

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

다음 파일을 확인한다.

- `wvd.exe`, `_internal`, `CHANGES_LOG.md`
- `_internal\_tkinter.pyd`, `_internal\tcl86t.dll`, `_internal\tk86t.dll`
- `_internal\_tcl_data\init.tcl`, `_internal\_tk_data`
- `_internal\resources\images\next.png`
- `_internal\resources\images\FFXI\org_position.png`
- `_internal\locale\ko_KR\LC_MESSAGES\messages.mo`

## 사용자 데이터를 격리한 스모크 테스트

스모크 테스트는 5초 이상 실행해야 하며, 현재 검증 기준은 10초이다. 실제 `config.json`을 직접 지정하거나 `dist\wvd`를 작업 디렉터리로 사용하면 첫 실행 시 `LAST_VERSION`과 로그가 갱신된다. 다음과 같이 설정 복사본과 별도 작업 디렉터리를 사용한다.

```powershell
$smokeRoot = Join-Path $stageRoot 'smoke'
New-Item -ItemType Directory -Path $smokeRoot | Out-Null
$configSource = if (Test-Path -LiteralPath 'dist\wvd\config.json') {
    'dist\wvd\config.json'
} else {
    'config.json'
}
Copy-Item -LiteralPath $configSource -Destination (Join-Path $smokeRoot 'config.json')
```

일반 Windows 세션에서는 아래와 동일한 `ProcessStartInfo` 절차에서 exe를 `$stagedDeploy\wvd.exe`, 작업 디렉터리를 `$smokeRoot`로 지정하면 된다. 제한된 자동화 환경에서는 Python이 파일을 읽어도 Tcl의 네이티브 파일 조회가 `C:\Users\...` 아래를 보지 못해 다음 오류가 날 수 있다.

```text
_tkinter.TclError: Can't find a usable init.tcl
```

파일 존재 여부와 해시가 정상인데 이 오류가 발생하면 배포본 손상으로 단정하지 않는다. 비어 있는 드라이브 문자를 저장소에 임시 매핑하고, exe·작업 디렉터리·설정 복사본을 모두 매핑된 경로로 지정한다.

```powershell
$driveName = @('W', 'X', 'Y', 'Z') |
    Where-Object { -not (Get-PSDrive -Name $_ -ErrorAction SilentlyContinue) } |
    Select-Object -First 1
if (-not $driveName) { throw '스모크 테스트용 드라이브 문자가 없습니다.' }

$drive = "$driveName`:"
subst.exe $drive $repoRoot
if ($LASTEXITCODE -ne 0) { throw "subst 실패: $LASTEXITCODE" }

$process = $null
$previousConfigPath = $env:WVDAS_CONFIG_PATH
try {
    $mappedExe = "$drive\build\$stageName\dist\wvd\wvd.exe"
    $mappedSmoke = "$drive\build\$stageName\smoke"
    $env:WVDAS_CONFIG_PATH = Join-Path $mappedSmoke 'config.json'

    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $mappedExe
    $startInfo.WorkingDirectory = $mappedSmoke
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true

    $process = [Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) { throw 'exe를 시작하지 못했습니다.' }

    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()
    Start-Sleep -Seconds 10

    if ($process.HasExited) {
        $stderrText = $stderrTask.GetAwaiter().GetResult()
        throw "exe가 조기 종료되었습니다: $($process.ExitCode)`n$stderrText"
    }

    $process.Kill()
    if (-not $process.WaitForExit(5000)) {
        throw '스모크 테스트 프로세스를 종료하지 못했습니다.'
    }

    $stdoutText = $stdoutTask.GetAwaiter().GetResult()
    $stderrText = $stderrTask.GetAwaiter().GetResult()
    if (($stdoutText + "`n" + $stderrText) -match 'Traceback|ModuleNotFoundError|TclError') {
        throw "시작 오류가 검출되었습니다.`n$stderrText"
    }
}
finally {
    if ($process -and -not $process.HasExited) {
        $process.Kill()
        $process.WaitForExit(5000) | Out-Null
    }
    $env:WVDAS_CONFIG_PATH = $previousConfigPath
    subst.exe $drive /D
}

if (Get-PSDrive -Name $driveName -ErrorAction SilentlyContinue) {
    throw "임시 드라이브 매핑이 남아 있습니다: $drive"
}
```

스모크 테스트 전후에 실제 `dist\wvd\config.json` 해시와 `dist\wvd\logs` 목록이 동일한지 확인한다. 격리된 `smoke\logs`에 새 테스트 로그가 생기는 것은 정상이다. `script.py:140`의 `RuntimeWarning: non-string key ... FarmConfig`는 2026-08-18 검증에서 확인된 비치명 경고이며, `Traceback`, `ModuleNotFoundError`, `TclError` 또는 조기 종료는 실패로 처리한다.

## 배포

스테이징 스모크가 성공한 경우에만 배포한다.

1. 배포 경로와 이동 대상의 절대 경로가 저장소의 `dist\wvd` 및 해당 스테이징 폴더 안인지 확인한다.
2. 기존 `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 `$stageRoot\previous-deploy`로 이동한다.
3. 새 `_internal`, `wvd.exe`, `CHANGES_LOG.md`만 `dist\wvd`로 이동한다.
4. 중간 단계가 실패하면 새 항목을 스테이징으로 되돌리고 `previous-deploy`의 기존 항목을 복구한다. 부분 복사본을 둔 채 계속하지 않는다.
5. `config.json`, `logs`, `audit`의 전후 상태가 동일한지 확인한다.
6. 최종 `dist\wvd\wvd.exe`도 같은 격리 방식으로 5초 이상 다시 실행한다. 이때 매핑된 exe 경로만 `$drive\dist\wvd\wvd.exe`로 바꾸고 설정 복사본과 격리 작업 디렉터리는 그대로 사용한다.
7. 테스트 프로세스와 임시 드라이브 매핑을 종료하고 실제 설정·로그가 바뀌지 않았는지 다시 확인한다.
8. 모든 스모크 테스트가 끝나면 실제 설정 경로를 다시 확인한 뒤 격리 복사본인 `$smokeRoot\config.json`만 삭제한다. 사용자 토큰이 포함될 수 있는 설정 복사본을 빌드 산출물에 남기지 않는다.

기존 배포 백업은 새 실행 파일의 실제 사용 확인이 끝날 때까지 유지한다.

## 완료 기준과 기록

다음 조건을 모두 만족해야 빌드 성공으로 보고한다.

1. 최종 경로에 `dist\wvd\wvd.exe`가 존재한다.
2. Tcl/Tk 및 필수 리소스가 모두 존재한다.
3. 최종 exe가 5초 이상 유지되고 시작 오류 없이 종료된다.
4. 테스트 PID와 임시 `subst` 매핑이 남아 있지 않다.
5. 사용자 설정·기존 로그·감사 데이터가 배포 교체로 삭제되지 않았다.
6. 최종 exe의 절대 경로, 크기, SHA-256, 빌드 커밋, 스모크 실행 시간을 기록한다.

2026-08-18 기준 성공 사례는 `2.5.11-momo.1`, 커밋 `e9cc45184ebcea1c7857fc31bc3054512fbd1353`, 10초 스모크 테스트이며 최종 exe SHA-256은 `E927F339735D2EE60EEACF08C9F190FE446BE764556AB6FE7BC09CC85EC649DC`였다. 이 해시는 해당 커밋의 기준값이며 소스 또는 빌드 환경이 바뀌면 새 값을 기록한다.
