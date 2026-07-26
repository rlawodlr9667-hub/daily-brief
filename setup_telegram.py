# -*- coding: utf-8 -*-
"""
텔레그램 최초 설정 도우미. 딱 한 번만 실행하면 됩니다.

하는 일:
  1. 봇 토큰이 진짜 쓸 수 있는 것인지 확인 (봇 이름을 확인해 줍니다)
  2. 브리핑을 받을 chat_id 를 자동으로 찾아 줍니다
  3. config.json 에 저장합니다

사용법:
    python setup_telegram.py 8123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxxxx

토큰 만드는 방법은 README.md 를 보세요.
"""

import json
import os
import sys

import send_telegram as tg

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def check_token(token):
    """토큰이 유효한지 확인하고 봇 정보를 돌려줍니다."""
    result = tg.api_request(token, "getMe", {})
    if not result.get("ok"):
        print("\n[실패] 이 토큰으로는 접속할 수 없습니다.")
        print(f"       텔레그램 응답: {result.get('description')}")
        print("\n  - 토큰을 복사할 때 앞뒤 공백이 섞이지 않았는지 확인하세요.")
        print("  - BotFather 에서 /mybots -> 봇 선택 -> API Token 으로 다시 확인할 수 있습니다.")
        return None
    return result["result"]


def find_chat_id(token):
    """봇에게 온 메시지에서 chat_id 를 찾습니다."""
    result = tg.api_request(token, "getUpdates", {"limit": 100})
    if not result.get("ok"):
        print(f"\n[실패] 메시지 목록을 가져오지 못했습니다: {result.get('description')}")
        return None

    updates = result.get("result", [])
    found = {}   # chat_id -> 표시 이름

    for upd in updates:
        msg = (upd.get("message") or upd.get("edited_message")
               or upd.get("channel_post") or {})
        chat = msg.get("chat") or {}
        cid = chat.get("id")
        if cid is None:
            continue
        name = (chat.get("title")
                or " ".join(filter(None, [chat.get("first_name"), chat.get("last_name")]))
                or chat.get("username")
                or "이름 없음")
        found[cid] = f"{name} ({chat.get('type', '?')})"

    if not found:
        print("\n[대기] 봇에게 온 메시지가 없습니다.")
        print("\n  다음 순서로 해 주세요:")
        print("  1) 텔레그램 앱을 엽니다")
        print("  2) 위에 표시된 봇 이름을 검색해서 대화방에 들어갑니다")
        print("  3) 아무 메시지나 하나 보냅니다 (예: 안녕)")
        print("  4) 이 명령을 다시 실행합니다")
        return None

    if len(found) == 1:
        cid = next(iter(found))
        print(f"\nchat_id 를 찾았습니다: {cid}  ->  {found[cid]}")
        return cid

    # 대화방이 여러 개면 가장 최근 것을 씁니다.
    print("\n대화방이 여러 개 발견되었습니다:")
    for cid, name in found.items():
        print(f"  - {cid}  {name}")
    latest = list(found)[-1]
    print(f"\n가장 최근 대화방을 사용합니다: {latest}")
    print("다른 곳으로 받고 싶으면 config.json 의 chat_id 를 직접 고치세요.")
    return latest


def save_config(token, chat_id):
    data = {
        "bot_token": token,
        "chat_id": str(chat_id),
    }
    # 이미 다른 설정이 들어 있으면 지우지 않고 합칩니다.
    if os.path.exists(tg.CONFIG_PATH):
        try:
            with open(tg.CONFIG_PATH, "r", encoding="utf-8") as fp:
                existing = json.load(fp)
            existing.update(data)
            data = existing
        except (json.JSONDecodeError, OSError):
            pass

    with open(tg.CONFIG_PATH, "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {tg.CONFIG_PATH}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("봇 토큰을 함께 적어 주세요.")
        print("예: python setup_telegram.py 8123456789:AAxxxxxxxxxxxxxxxxxxxxxxxxx")
        return 1

    token = sys.argv[1].strip()

    print("1단계: 토큰을 확인합니다...")
    bot = check_token(token)
    if bot is None:
        return 1
    print(f"       OK — 봇 이름: {bot.get('first_name')} (@{bot.get('username')})")

    print("\n2단계: 브리핑을 받을 대화방을 찾습니다...")
    chat_id = find_chat_id(token)
    if chat_id is None:
        return 1

    save_config(token, chat_id)

    print("\n3단계: 테스트 메시지를 보냅니다...")
    ok, err = tg.send_message(token, str(chat_id),
                              "<b>설정 완료</b>\n\n경제뉴스 브리핑 봇 연결에 성공했습니다.")
    if not ok:
        print(f"       발송 실패: {err}")
        return 1

    print("       OK — 텔레그램을 확인해 보세요.")
    print("\n설정이 모두 끝났습니다. 이제 Claude Code 에서 /brief 를 실행하세요.")
    print("주의: config.json 에는 봇 토큰이 들어 있습니다. 다른 사람에게 공유하지 마세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
