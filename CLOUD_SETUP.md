# PC가 꺼져 있어도 브리핑 받기 (GitHub Actions)

브리핑 생성과 발송을 **GitHub 서버에서** 하도록 옮기는 방법입니다.
PC 전원과 무관하게 매일 아침 버튼 메뉴가 옵니다.

**비용은 0원입니다.**
- GitHub Actions 무료 사용량: 비공개 저장소 월 2,000분 → 이 프로젝트는 약 1,560분 사용
- 요약은 Claude Code 구독 인증(`setup-token`)을 쓰므로 API 사용료가 없습니다

## 미리 알아두실 것

| | 내 PC 방식 (현재) | 클라우드 방식 |
|---|---|---|
| PC 꺼져 있을 때 | 안 됨 (절전은 됨) | **됨** |
| 버튼 응답 속도 | 즉시 | 아침 시간대 최대 5분, 그 외 최대 1시간 |
| 준비물 | 없음 | GitHub 계정, Git 설치 |

버튼이 즉시 응답하지 않는 이유: 텔레그램은 봇에게 클릭 알림을 밀어주지 않고,
봇이 물어보러 가야 합니다. 상주 프로그램 없이 하려면 주기적으로 확인해야 합니다.
**클릭은 유실되지 않습니다.** 텔레그램이 24시간 보관하므로 늦게 도착할 뿐입니다.

---

## 1단계 — Git 설치

지금 PC에 Git이 없습니다. https://git-scm.com/download/win 에서 받아
기본 설정 그대로 설치하세요. 설치 후 VS Code를 다시 켜고 확인합니다.

```powershell
git --version
```

## 2단계 — GitHub 계정과 저장소 만들기

1. https://github.com 에서 계정을 만듭니다 (무료).
2. 로그인 후 오른쪽 위 **+** → **New repository**
3. 이름은 `daily-brief` 등 아무거나. **반드시 `Private`(비공개)로 선택**하세요.
4. 나머지는 건드리지 않고 **Create repository**

## 3단계 — Claude 인증 토큰 만들기

클라우드에서 구독으로 실행하려면 장기 토큰이 필요합니다. 터미널에서:

```powershell
& "$env:USERPROFILE\.vscode\extensions\anthropic.claude-code-*\resources\native-binary\claude.exe" setup-token
```

브라우저가 열리면 로그인하고 승인하세요. 터미널에 나오는 토큰 문자열을 복사해 둡니다.

> 이 토큰은 비밀번호와 같습니다. 다음 단계에서 GitHub Secrets에만 넣고,
> 코드나 채팅에 붙여넣지 마세요.

## 4단계 — GitHub에 비밀값 3개 등록

저장소 페이지에서 **Settings** → 왼쪽 **Secrets and variables** → **Actions**
→ **New repository secret** 을 눌러 아래 3개를 각각 등록합니다.

| Name (그대로 입력) | Secret (값) |
|---|---|
| `TELEGRAM_BOT_TOKEN` | `config.json` 의 `bot_token` 값 |
| `TELEGRAM_CHAT_ID` | `config.json` 의 `chat_id` 값 |
| `CLAUDE_CODE_OAUTH_TOKEN` | 3단계에서 복사한 토큰 |

`config.json` 값은 이렇게 확인할 수 있습니다.

```powershell
Get-Content config.json
```

## 5단계 — 코드 올리기

프로젝트 폴더에서 (아래 `<주소>` 는 저장소 페이지에 표시된 HTTPS 주소):

```powershell
git init
git add .
git commit -m "경제뉴스 브리핑 봇"
git branch -M main
git remote add origin <주소>
git push -u origin main
```

`config.json` 은 `.gitignore` 에 있으므로 **올라가지 않습니다.** 의도된 동작입니다.

올린 뒤 저장소 페이지에서 파일 목록에 `config.json` 이 **없는지** 꼭 확인하세요.

## 6단계 — 내 PC의 자동 실행 끄기

**이 단계를 빠뜨리면 버튼이 절반만 동작합니다.** 내 PC의 서버와 클라우드가
동시에 텔레그램 알림을 물어보면 서로 가로채기 때문입니다.

```powershell
powershell -ExecutionPolicy Bypass -File automation\uninstall_tasks.ps1
```

## 7단계 — 시험 실행

저장소 페이지 → **Actions** 탭 → 왼쪽 **아침 브리핑 생성** →
오른쪽 **Run workflow** → 초록 버튼

5~6분 뒤 텔레그램에 버튼 메뉴가 오면 성공입니다.
버튼을 누르면 최대 5분 안에 브리핑이 도착합니다.

---

## 확인하고 고치기

**진행 상황 보기**: 저장소 → Actions 탭. 초록 체크는 성공, 빨간 X는 실패입니다.
실패한 것을 눌러 보면 어느 단계에서 멈췄는지 나옵니다.

**실패하면 텔레그램으로 알려 줍니다.** 아침에 아무것도 오지 않으면
Actions 탭을 확인하세요.

**시간 바꾸기**: `.github/workflows/daily-brief.yml` 의 `cron: '50 23 * * *'` 를 고칩니다.
GitHub는 UTC를 쓰므로 **한국시간에서 9시간을 빼세요.**
예) 07:30 KST → 22:30 UTC 전날 → `'30 22 * * *'`

**버튼을 더 빨리 받고 싶으면**: `button-poll.yml` 의 `*/5` 를 `*/2` 로 줄일 수 있지만
무료 사용량을 넘길 수 있습니다. 사용량은 GitHub → Settings → Billing 에서 봅니다.

**GitHub가 예약 실행을 멈출 수 있습니다.** 저장소에 60일간 아무 활동이 없으면
GitHub가 cron을 자동으로 비활성화합니다. 매일 브리핑이 커밋되므로 정상 사용 중에는
문제가 없지만, 오래 쉬었다면 Actions 탭에서 다시 켜야 합니다.

**예약 실행은 정확하지 않습니다.** GitHub 사정에 따라 5~30분 늦을 수 있습니다.
정시에 받는 것이 중요하면 내 PC 방식이 더 정확합니다.

---

## 다시 내 PC 방식으로 돌아가려면

```powershell
powershell -ExecutionPolicy Bypass -File automation\install_tasks.ps1 -At 08:50
```

그리고 GitHub 저장소 → Actions 탭에서 두 워크플로를 **Disable** 하세요.
(둘을 함께 켜 두면 알림을 서로 가로챕니다)
