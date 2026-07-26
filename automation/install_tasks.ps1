# Windows 작업 스케줄러에 자동 실행을 등록합니다. 관리자 권한이 필요 없습니다.
#
# 등록되는 작업 두 개:
#   DailyBrief-Generate    매일 정해진 시각에 브리핑 생성 + 버튼 메뉴 발송
#   DailyBrief-BotServer   로그온할 때마다 버튼 응답 서버 실행
#
# 사용법:
#     powershell -ExecutionPolicy Bypass -File automation\install_tasks.ps1
#     powershell -ExecutionPolicy Bypass -File automation\install_tasks.ps1 -At 07:30
#
# 되돌리려면 automation\uninstall_tasks.ps1 을 실행하세요.

param(
    # 브리핑을 받을 시각 (24시간 표기)
    [string]$At = '09:00',
    # 버튼 서버 자동 실행을 등록하지 않으려면 -NoBotServer
    [switch]$NoBotServer
)

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$dailyScript = Join-Path $PSScriptRoot 'daily_brief.ps1'
$serverScript = Join-Path $PSScriptRoot 'run_bot_server.ps1'

foreach ($p in @($dailyScript, $serverScript)) {
    if (-not (Test-Path $p)) { throw "스크립트를 찾을 수 없습니다: $p" }
}

# 설정 파일이 없으면 자동화해도 발송이 안 됩니다. 미리 알려줍니다.
if (-not (Test-Path (Join-Path $root 'config.json'))) {
    Write-Host "경고: config.json 이 없습니다." -ForegroundColor Yellow
    Write-Host "      먼저 'python setup_telegram.py <봇토큰>' 을 실행하세요." -ForegroundColor Yellow
    Write-Host ""
}

try {
    $when = [datetime]::ParseExact($At, 'HH:mm', $null)
} catch {
    throw "시각 형식이 잘못됐습니다: '$At'. 09:00 처럼 적어 주세요."
}

Write-Host "프로젝트 폴더: $root"
Write-Host ""

# 실행 주체를 '현재 사용자'로 못박습니다.
# 이걸 생략하면 로그온 트리거가 '모든 사용자의 로그온'으로 해석돼서
# 관리자 권한을 요구하고 'Access is denied' 로 실패합니다.
$me = "$env:USERDOMAIN\$env:USERNAME"
$principal = New-ScheduledTaskPrincipal -UserId $me -LogonType Interactive -RunLevel Limited

# ---------------------------------------------------------------------------
# 1) 매일 브리핑 생성 + 메뉴 발송
# ---------------------------------------------------------------------------
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$dailyScript`"" `
    -WorkingDirectory $root

$trigger = New-ScheduledTaskTrigger -Daily -At $when

# StartWhenAvailable : 그 시각에 PC가 꺼져 있었다면 켠 뒤에 실행합니다.
# WakeToRun          : 절전 상태라면 깨워서 실행합니다. (완전히 종료된 상태는 못 깨웁니다)
$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -WakeToRun `
    -DontStopIfGoingOnBatteries `
    -AllowStartIfOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName 'DailyBrief-Generate' `
    -Action $action -Trigger $trigger -Settings $settings -Principal $principal `
    -Description '경제뉴스 브리핑을 생성하고 텔레그램 버튼 메뉴를 보냅니다.' `
    -Force | Out-Null

Write-Host "[등록] DailyBrief-Generate — 매일 $At 브리핑 생성 + 메뉴 발송" -ForegroundColor Green

# ---------------------------------------------------------------------------
# 2) 버튼 응답 서버 (로그온 시 상시 실행)
# ---------------------------------------------------------------------------
if (-not $NoBotServer) {
    $action2 = New-ScheduledTaskAction -Execute 'powershell.exe' `
        -Argument "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$serverScript`"" `
        -WorkingDirectory $root

    # -User 를 반드시 지정합니다. 생략하면 '모든 사용자의 로그온' 트리거가 되어
    # 관리자 권한을 요구하고 등록이 실패합니다.
    $trigger2 = New-ScheduledTaskTrigger -AtLogOn -User $me

    # ExecutionTimeLimit 0 = 시간 제한 없음. 계속 켜져 있어야 하는 프로그램입니다.
    $settings2 = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -RestartCount 3 `
        -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit ([TimeSpan]::Zero)

    Register-ScheduledTask -TaskName 'DailyBrief-BotServer' `
        -Action $action2 -Trigger $trigger2 -Settings $settings2 -Principal $principal `
        -Description '텔레그램 버튼 클릭에 응답하는 상주 프로그램입니다.' `
        -Force | Out-Null

    Write-Host "[등록] DailyBrief-BotServer — 로그온 시 버튼 응답 서버 실행" -ForegroundColor Green
}

Write-Host ""
Write-Host "등록 완료. 확인 방법:" -ForegroundColor Cyan
Write-Host "  Get-ScheduledTask -TaskName 'DailyBrief-*' | Select-Object TaskName, State"
Write-Host ""
Write-Host "지금 바로 시험해 보려면:" -ForegroundColor Cyan
Write-Host "  Start-ScheduledTask -TaskName 'DailyBrief-Generate'"
Write-Host "  (로그: logs\daily_<날짜>.log)"
Write-Host ""
Write-Host "주의: 버튼 서버는 지금 로그온 상태에서는 아직 안 켜져 있습니다." -ForegroundColor Yellow
Write-Host "      바로 켜려면:  Start-ScheduledTask -TaskName 'DailyBrief-BotServer'" -ForegroundColor Yellow
Write-Host "      또는 다음 로그온 때 자동으로 켜집니다." -ForegroundColor Yellow
