# 등록한 자동 실행을 모두 해제합니다.
#
# 사용법:
#     powershell -ExecutionPolicy Bypass -File automation\uninstall_tasks.ps1
#
# 파일은 지우지 않습니다. 자동 실행만 멈춥니다.
# 다시 켜려면 install_tasks.ps1 을 실행하세요.

$ErrorActionPreference = 'Continue'

foreach ($name in @('DailyBrief-Generate', 'DailyBrief-BotServer')) {
    $task = Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    if ($task) {
        if ($task.State -eq 'Running') {
            Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
            Write-Host "[중지] $name"
        }
        Unregister-ScheduledTask -TaskName $name -Confirm:$false
        Write-Host "[해제] $name" -ForegroundColor Green
    } else {
        Write-Host "[없음] $name — 등록돼 있지 않습니다"
    }
}

Write-Host ""
Write-Host "해제 완료. 브리핑 파일과 설정은 그대로 남아 있습니다." -ForegroundColor Cyan
Write-Host "수동으로 쓰려면 Claude Code 에서 /brief 를 실행하세요."
