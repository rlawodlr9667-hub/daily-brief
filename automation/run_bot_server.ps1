# 버튼 응답 서버를 로그와 함께 계속 실행합니다.
# 작업 스케줄러가 로그온 시 이 스크립트를 창 없이 실행합니다.
#
# 직접 확인하고 싶으면:
#     powershell -ExecutionPolicy Bypass -File automation\run_bot_server.ps1

$ErrorActionPreference = 'Continue'
$env:PYTHONIOENCODING = 'utf-8'

# 이 파일은 'BOM 있는 UTF-8' 로 저장해야 합니다. PowerShell 5.1 은 BOM 이 없으면
# 스크립트를 cp949 로 읽어서 안에 적힌 한글이 파싱 단계에서 깨집니다.
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir 'bot_server.log'

# 로그가 무한정 커지지 않게 5MB 넘으면 한 번 갈아둡니다.
if ((Test-Path $logFile) -and ((Get-Item $logFile).Length -gt 5MB)) {
    Move-Item $logFile "$logFile.old" -Force
}

# 로그는 파이썬이 직접 씁니다 (--log).
# PowerShell 의 *>> 리다이렉트를 쓰면 두 가지 문제가 생깁니다.
#   1) PS 5.1 은 UTF-16LE 로 써서 한글이 깨집니다.
#   2) 파일을 독점해서 서버가 도는 동안 로그를 열어볼 수 없습니다.
# -u : 파이썬 출력을 버퍼에 모으지 않고 바로 내보냅니다.
& python -u bot_server.py --log $logFile
