# 매일 아침 자동 실행되는 브리핑 파이프라인.
#
#   1) 뉴스 수집        (fetch_news.py)
#   2) 항목별 요약 작성  (claude -p, 구독에 포함 — API 비용 없음)
#   3) 버튼 메뉴 발송    (bot_server.py --send-menu)
#
# 직접 실행해서 시험해 볼 수도 있습니다:
#     powershell -ExecutionPolicy Bypass -File automation\daily_brief.ps1
#
# 작업 스케줄러 등록은 automation\install_tasks.ps1 이 합니다.

param(
    # 몇 시간 전까지의 기사를 모을지. 지정하지 않으면 요일에 따라 자동 결정합니다.
    [int]$Hours = 0
)

$ErrorActionPreference = 'Stop'
$env:PYTHONIOENCODING = 'utf-8'

# 작업 스케줄러가 실행할 때는 콘솔 인코딩이 한글 코드페이지(cp949)일 수 있습니다.
# 그러면 파이썬이 UTF-8 로 내보낸 한글이 로그에서 깨집니다.
# (이 스크립트 파일 자체도 반드시 'BOM 있는 UTF-8' 로 저장해야 합니다.
#  PowerShell 5.1 은 BOM 이 없으면 스크립트를 cp949 로 읽어서
#  안에 적힌 한글 문자열이 파싱 단계에서 이미 깨집니다.)
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch { }

# automation 폴더의 부모가 프로젝트 폴더입니다.
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

$today = Get-Date -Format 'yyyy-MM-dd'
$logDir = Join-Path $root 'logs'
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
$logFile = Join-Path $logDir "daily_$today.log"

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format 'HH:mm:ss'), $Level, $Message
    Write-Host $line
    Add-Content -Path $logFile -Value $line -Encoding utf8
}

# ---------------------------------------------------------------------------
# 실행하는 동안 노트북이 잠들지 않게 막기
# ---------------------------------------------------------------------------
# 2026-07-27 에 실제로 겪은 일입니다. 09:59 에 시작해서 브리핑 4개까지
# 정상으로 썼는데, 10:07 에 노트북이 절전(현대 대기)에 들어가면서 프로세스가
# 통째로 죽었습니다. 작업 스케줄러에는 종료코드 0xC000013A 만 남고, 마지막
# 단계인 '버튼 메뉴 발송'에 도달하지 못해 텔레그램이 조용했습니다.
#
# 작업 스케줄러에는 '실행하는 동안 깨워 두기' 옵션이 없습니다. WakeToRun 은
# 시작 시점에 한 번 깨울 뿐이라, 시작한 뒤에 잠드는 것은 막지 못합니다.
# 그래서 윈도우에게 직접 "지금 작업 중이니 재우지 마라"고 알립니다.
#
# 주의: 사용자가 노트북 덮개를 닫거나 직접 절전을 누르면 그건 못 막습니다.
# 막을 수 있는 것은 '가만히 있어서 저절로 잠드는' 경우입니다.
Add-Type -Namespace Win32 -Name Power -MemberDefinition @'
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern uint SetThreadExecutionState(uint esFlags);
'@ -ErrorAction SilentlyContinue

function Set-KeepAwake {
    param([switch]$Off)
    # 0x80000000 뒤의 L 을 빼면 안 됩니다. PowerShell 5.1 은 L 이 없으면 이 값을
    # 32비트 정수로 읽어서 -2147483648 이 되고, [uint32] 로 바꾸는 순간 예외가
    # 납니다. 아래 try/catch 에 걸려 조용히 무시되므로, 절전 차단이 안 걸린 채
    # 잘 도는 것처럼 보이게 됩니다.
    $ES_CONTINUOUS       = [uint32]0x80000000L
    $ES_SYSTEM_REQUIRED  = [uint32]0x00000001
    try {
        if ($Off) {
            # 평소 상태로 되돌립니다. (스크립트가 끝나면 윈도우가 알아서
            #  풀어주긴 하지만, 명시해 두는 편이 읽기에 분명합니다)
            [void][Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS)
        } else {
            [void][Win32.Power]::SetThreadExecutionState($ES_CONTINUOUS -bor $ES_SYSTEM_REQUIRED)
        }
    } catch { }
}

# ---------------------------------------------------------------------------
# claude 실행 파일 찾기
# ---------------------------------------------------------------------------
# VS Code 확장 안에 들어 있는데 경로에 버전 번호가 붙습니다
# (anthropic.claude-code-2.1.220-win32-x64). 확장이 업데이트되면 번호가 바뀌므로
# 경로를 고정해두면 어느 날 갑자기 깨집니다. 그래서 매번 찾습니다.
function Find-ClaudeExe {
    $found = Get-Command claude -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }

    $extRoot = Join-Path $env:USERPROFILE '.vscode\extensions'
    if (Test-Path $extRoot) {
        $dirs = Get-ChildItem $extRoot -Directory -Filter 'anthropic.claude-code-*' -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending
        foreach ($d in $dirs) {
            $exe = Join-Path $d.FullName 'resources\native-binary\claude.exe'
            if (Test-Path $exe) { return $exe }
        }
    }

    foreach ($p in @(
        (Join-Path $env:USERPROFILE '.claude\local\claude.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\claude\claude.exe')
    )) {
        if (Test-Path $p) { return $p }
    }
    return $null
}

# ---------------------------------------------------------------------------
Set-KeepAwake
Write-Log "===== 브리핑 자동 생성 시작 ($today) ====="

# 수집 범위: 월요일은 주말 기사까지 담아야 하므로 넓게 잡습니다.
if ($Hours -le 0) {
    $Hours = if ((Get-Date).DayOfWeek -eq 'Monday') { 60 } else { 24 }
}

# --- 1단계: 뉴스 수집 ---
Write-Log "1/3 뉴스 수집 (최근 $Hours 시간)"
$fetchOut = & python fetch_news.py --hours $Hours 2>&1 | Out-String
Add-Content -Path $logFile -Value $fetchOut -Encoding utf8

if ($LASTEXITCODE -ne 0) {
    Write-Log "뉴스 수집 실패 (종료코드 $LASTEXITCODE). 중단합니다." 'ERROR'
    exit 1
}

$rawFile = Join-Path $root "data\raw_$today.md"
if (-not (Test-Path $rawFile)) {
    Write-Log "원본 파일이 만들어지지 않았습니다: $rawFile" 'ERROR'
    exit 1
}
Write-Log "원본 준비 완료: data\raw_$today.md"

# --- 2단계: 항목별 요약 작성 ---
$claude = Find-ClaudeExe
if (-not $claude) {
    Write-Log "claude 실행 파일을 찾지 못했습니다. VS Code 의 Claude Code 확장이 설치돼 있는지 확인하세요." 'ERROR'
    exit 1
}
Write-Log "2/3 요약 작성 (claude: $claude)"

# 프롬프트는 brief_prompt.txt 한 곳에만 둡니다.
# 클라우드 자동화(.github/workflows/daily-brief.yml)도 같은 파일을 읽으므로,
# 여기에 복사해 두면 한쪽만 고쳤을 때 로컬과 클라우드가 다른 브리핑을 만듭니다.
$promptFile = Join-Path $PSScriptRoot 'brief_prompt.txt'
if (-not (Test-Path $promptFile)) {
    Write-Log "프롬프트 파일이 없습니다: $promptFile" 'ERROR'
    exit 1
}
$prompt = (Get-Content $promptFile -Raw -Encoding utf8) -replace '\{DATE\}', $today

# 발송은 이 스크립트가 담당하므로, 요약 단계에는 파일 읽기/쓰기 권한만 줍니다.
# Bash 를 주지 않기 때문에 요약 단계가 임의로 메시지를 보낼 수 없습니다.

$claudeOut = & $claude -p $prompt --permission-mode acceptEdits --allowedTools Read Write Glob Grep 2>&1 | Out-String
Add-Content -Path $logFile -Value $claudeOut -Encoding utf8

if ($LASTEXITCODE -ne 0) {
    Write-Log "요약 작성이 실패했습니다 (종료코드 $LASTEXITCODE)." 'ERROR'
    exit 1
}

# 진짜로 파일이 만들어졌는지 확인합니다. claude 가 성공을 보고했어도
# 파일이 없으면 메뉴를 보내봐야 빈 메뉴가 됩니다.
$briefDir = Join-Path $root "briefs\$today"
$made = @()
if (Test-Path $briefDir) {
    $made = Get-ChildItem $briefDir -Filter '*.md' -ErrorAction SilentlyContinue |
            Where-Object { $_.BaseName -in @('kr_stock','us_stock','commodity','realestate','re_policy') }
}

if ($made.Count -eq 0) {
    Write-Log "브리핑 파일이 하나도 만들어지지 않았습니다. 메뉴를 보내지 않고 중단합니다." 'ERROR'
    exit 1
}
Write-Log "브리핑 $($made.Count)개 작성됨: $(($made | ForEach-Object { $_.BaseName }) -join ', ')"

# --- 3단계: 버튼 메뉴 발송 ---
Write-Log "3/3 버튼 메뉴 발송"
$menuOut = & python bot_server.py --send-menu 2>&1 | Out-String
Add-Content -Path $logFile -Value $menuOut -Encoding utf8

if ($LASTEXITCODE -ne 0) {
    Write-Log "메뉴 발송 실패 (종료코드 $LASTEXITCODE)." 'ERROR'
    exit 1
}

Write-Log "===== 완료. 텔레그램을 확인하세요. ====="
Set-KeepAwake -Off
exit 0
