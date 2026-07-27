# -*- coding: utf-8 -*-
"""
버튼 클릭을 받아서 미리 작성된 브리핑을 보내주는 상주 프로그램.

사용법:
    python bot_server.py --send-menu     # 오늘의 버튼 메뉴 톡 발송
    python bot_server.py                 # 버튼 클릭 대기 (계속 켜 둠)
    python bot_server.py --once          # 대기 중인 클릭만 처리하고 종료

왜 상주해야 하나요?
    텔레그램은 봇에게 "누가 버튼을 눌렀다"고 알려줄 때, 봇이 직접 물어보러
    오거나(폴링) 공개된 웹서버 주소를 알려주기(웹훅)를 요구합니다.
    개인 PC에는 공개 주소가 없으니 폴링 방식을 씁니다. 그래서 프로그램이
    켜져 있어야 클릭에 답할 수 있습니다.

    다만 PC가 꺼져 있을 때 누른 버튼도 사라지지 않습니다. 텔레그램이 24시간
    보관하므로, PC를 켜고 이 프로그램을 실행하면 그때 답장이 갑니다.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta, timezone

import feeds as cfg
import send_telegram as tg

# pythonw.exe 로 실행하면 sys.stdout 이 None 이 됩니다. 그대로 두면
# 첫 print() 에서 죽어버리므로 빈 출력으로 바꿔 둡니다.
if sys.stdout is None:
    import io
    sys.stdout = io.StringIO()
if sys.stderr is None:
    import io
    sys.stderr = io.StringIO()

try:
    # line_buffering: 상주 프로그램이라 한 줄씩 바로 내보내야 합니다.
    # 이게 없으면 출력이 버퍼에 쌓여서, 로그 파일로 넘길 때 아무것도 안 보입니다.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
except Exception:
    pass

KST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BRIEFS_DIR = os.path.join(BASE_DIR, "briefs")
OFFSET_PATH = os.path.join(BASE_DIR, "data", "bot_offset.txt")

WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"]


# ---------------------------------------------------------------------------
# 브리핑 파일 찾기
# ---------------------------------------------------------------------------
def brief_dir(date_str):
    return os.path.join(BRIEFS_DIR, date_str)


def brief_path(date_str, key):
    return os.path.join(brief_dir(date_str), f"{key}.md")


def available_categories(date_str):
    """해당 날짜에 준비된 항목만 CATEGORIES 순서대로 돌려줍니다."""
    return [(key, label, emoji) for key, label, emoji in cfg.CATEGORIES
            if os.path.exists(brief_path(date_str, key))]


def today_str():
    return datetime.now(KST).strftime("%Y-%m-%d")


def pretty_date(date_str):
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return date_str
    return f"{d.year}년 {d.month}월 {d.day}일 ({WEEKDAYS[d.weekday()]})"


# ---------------------------------------------------------------------------
# 버튼 메뉴
# ---------------------------------------------------------------------------
def build_keyboard(date_str, cats):
    """2열 배치의 인라인 버튼을 만듭니다."""
    buttons = [
        {"text": f"{emoji} {label}", "callback_data": f"b|{key}|{date_str}"}
        for key, label, emoji in cats
    ]
    # 항목 버튼만 둡니다. '전체 받기'는 일부러 뺐습니다. 아침에 긴 글이
    # 한꺼번에 쏟아지지 않고, 읽고 싶은 것만 골라 받는 것이 이 봇의 방식입니다.
    # (되살리려면 아래 한 줄의 주석을 풀면 됩니다. handle_callback 의
    #  __all__ 처리는 그대로 남겨 두었습니다)
    # rows.append([{"text": "📚 전체 받기", "callback_data": f"b|__all__|{date_str}"}])
    return {"inline_keyboard": [buttons[i:i + 2]
                                for i in range(0, len(buttons), 2)]}


def menu_text(date_str):
    """알림 메시지 본문.

    기사 내용은 여기에 넣지 않습니다. 아침에는 "요약해 뒀다"는 사실만 알리고,
    실제 기사는 버튼을 눌렀을 때만 보냅니다. 안 그러면 아침마다 긴 글 5개가
    한꺼번에 쏟아져서, 정작 읽고 싶은 항목을 찾기가 더 번거로워집니다.
    """
    return (f"<b>📊 오늘의 경제 동향을 요약했습니다</b>\n"
            f"<i>{pretty_date(date_str)}</i>\n\n"
            f"보고 싶은 항목을 눌러 주세요.")


def send_menu(date_str=None):
    """버튼 메뉴 톡을 보냅니다."""
    date_str = date_str or today_str()
    cats = available_categories(date_str)

    if not cats:
        print(f"{date_str} 브리핑이 아직 없습니다. 먼저 Claude Code 에서 /brief 를 실행하세요.")
        print(f"  (찾은 위치: {brief_dir(date_str)})")
        return 1

    token, chat_id = tg.load_config()
    ok, err = tg.send_message(token, chat_id, menu_text(date_str),
                              reply_markup=build_keyboard(date_str, cats))
    if not ok:
        print(f"메뉴 발송 실패: {err}")
        return 1

    print(f"메뉴를 보냈습니다. 항목 {len(cats)}개: "
          f"{', '.join(label for _k, label, _e in cats)}")
    print("\n버튼에 응답하려면 이 프로그램을 실행해 두세요:")
    print("    python bot_server.py")
    return 0


# ---------------------------------------------------------------------------
# 버튼 클릭 처리
# ---------------------------------------------------------------------------
def answer_callback(token, callback_id, text=""):
    """버튼의 '로딩 중' 표시를 멈춥니다. 10초 안에 응답해야 합니다."""
    tg.api_request(token, "answerCallbackQuery",
                   {"callback_query_id": callback_id, "text": text[:200]})


def deliver_brief(token, chat_id, date_str, key):
    """브리핑 하나를 (필요하면 여러 건으로 나눠) 보냅니다."""
    path = brief_path(date_str, key)
    if not os.path.exists(path):
        tg.send_message(token, chat_id,
                        f"<b>{date_str}</b> 의 해당 항목 브리핑을 찾을 수 없습니다.\n"
                        f"오래된 메뉴라면 Claude Code 에서 <code>/brief</code> 를 다시 실행해 주세요.")
        return False

    with open(path, "r", encoding="utf-8") as fp:
        md_text = fp.read()

    messages = tg.pack_messages(md_text)
    total = len(messages)
    for idx, msg in enumerate(messages, 1):
        body = tg.markdown_to_html(msg)
        if total > 1:
            body = f"<b>[{idx}/{total}]</b>\n{body}"
        ok, err = tg.send_message(token, chat_id, body)
        if not ok:
            print(f"    발송 실패 ({idx}/{total}): {err}")
            return False
        if idx < total:
            time.sleep(1.2)
    return True


def label_of(key):
    for k, label, _emoji in cfg.CATEGORIES:
        if k == key:
            return label
    return key


def handle_callback(token, cb):
    data = cb.get("data") or ""
    cb_id = cb.get("id")
    chat_id = (((cb.get("message") or {}).get("chat")) or {}).get("id")

    parts = data.split("|")
    if len(parts) != 3 or parts[0] != "b":
        answer_callback(token, cb_id, "알 수 없는 버튼입니다.")
        return

    _, key, date_str = parts

    if key == "__all__":
        cats = available_categories(date_str)
        answer_callback(token, cb_id, f"전체 {len(cats)}개 항목을 보냅니다...")
        print(f"  [클릭] 전체 받기 ({date_str}) -> {len(cats)}개 항목")
        for k, label, _emoji in cats:
            print(f"    - {label}")
            deliver_brief(token, chat_id, date_str, k)
            time.sleep(1.2)
        return

    answer_callback(token, cb_id, f"{label_of(key)} 브리핑을 보냅니다...")
    print(f"  [클릭] {label_of(key)} ({date_str})")
    deliver_brief(token, chat_id, date_str, key)


def handle_message(token, msg):
    """/menu, /start 같은 문자 명령도 받아 줍니다."""
    text = (msg.get("text") or "").strip().lower()
    chat_id = ((msg.get("chat")) or {}).get("id")
    if not chat_id:
        return

    if text.startswith("/start") or text.startswith("/menu") or text in ("메뉴", "브리핑"):
        date_str = today_str()
        cats = available_categories(date_str)
        if not cats:
            tg.send_message(token, str(chat_id),
                            "오늘 브리핑이 아직 준비되지 않았습니다.\n"
                            "PC에서 Claude Code 를 열고 <code>/brief</code> 를 실행해 주세요.")
            return
        tg.send_message(token, str(chat_id), menu_text(date_str),
                        reply_markup=build_keyboard(date_str, cats))
        print(f"  [명령] {text or '(빈 메시지)'} -> 메뉴 전송")
    elif text.startswith("/help"):
        tg.send_message(token, str(chat_id),
                        "<b>사용법</b>\n\n"
                        "<code>/menu</code> — 오늘의 항목 버튼 보기\n\n"
                        "브리핑은 PC에서 Claude Code 로 <code>/brief</code> 를 "
                        "실행할 때 만들어집니다.")


# ---------------------------------------------------------------------------
# 폴링 루프
# ---------------------------------------------------------------------------
def load_offset():
    try:
        with open(OFFSET_PATH, "r", encoding="utf-8") as fp:
            return int(fp.read().strip())
    except (OSError, ValueError):
        return None


def save_offset(offset):
    os.makedirs(os.path.dirname(OFFSET_PATH), exist_ok=True)
    with open(OFFSET_PATH, "w", encoding="utf-8") as fp:
        fp.write(str(offset))


def process_updates(token, updates):
    for upd in updates:
        try:
            if "callback_query" in upd:
                handle_callback(token, upd["callback_query"])
            elif "message" in upd:
                handle_message(token, upd["message"])
        except Exception as exc:      # 한 건이 실패해도 루프는 계속 돌아야 합니다
            print(f"  [오류] 업데이트 처리 실패: {type(exc).__name__}: {exc}")


def poll(once=False):
    token, _chat_id = tg.load_config()
    offset = load_offset()

    if once:
        print("대기 중인 버튼 클릭을 확인합니다...")
    else:
        print("버튼 클릭을 기다립니다. 멈추려면 Ctrl+C 를 누르세요.\n")

    idle_notified = False

    while True:
        params = {
            "timeout": 0 if once else 50,      # 텔레그램이 붙잡고 기다려 줍니다
            "allowed_updates": '["message","callback_query"]',
        }
        if offset is not None:
            params["offset"] = offset

        # 폴링 대기시간보다 넉넉하게 기다립니다.
        result = tg.api_request(token, "getUpdates", params,
                                timeout=(20 if once else 70))

        if not result.get("ok"):
            desc = result.get("description", "알 수 없는 오류")
            print(f"  [오류] 업데이트 수신 실패: {desc}")
            if once:
                return 1
            time.sleep(10)
            continue

        updates = result.get("result", [])
        if updates:
            idle_notified = False
            process_updates(token, updates)
            offset = updates[-1]["update_id"] + 1
            save_offset(offset)
        elif once:
            if not idle_notified:
                print("대기 중인 클릭이 없습니다.")
            return 0

        if once:
            return 0


class Tee:
    """화면과 로그 파일에 동시에 씁니다.

    PowerShell 의 `*>>` 리다이렉트를 쓰지 않는 이유가 두 가지 있습니다.
      1) Windows PowerShell 5.1 은 `>>` 를 UTF-16LE 로 씁니다. 파이썬의
         UTF-8 출력과 섞이면서 한글이 깨집니다.
      2) 리다이렉트가 파일을 독점해서, 서버가 도는 동안 로그를 열어볼 수조차
         없습니다. 문제가 생겼을 때 정작 확인이 안 되는 셈입니다.
    파이썬이 직접 쓰면 두 문제가 모두 없어집니다.
    """

    def __init__(self, stream, path):
        self.stream = stream
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.file = open(path, "a", encoding="utf-8", buffering=1)

    def write(self, text):
        try:
            self.stream.write(text)
        except Exception:
            pass
        self.file.write(text)
        return len(text)

    def flush(self):
        for target in (self.stream, self.file):
            try:
                target.flush()
            except Exception:
                pass


def main():
    parser = argparse.ArgumentParser(description="브리핑 버튼 봇")
    parser.add_argument("--send-menu", action="store_true",
                        help="오늘의 버튼 메뉴 톡을 발송")
    parser.add_argument("--date", help="날짜 지정 (예: 2026-07-26)")
    parser.add_argument("--once", action="store_true",
                        help="대기 중인 클릭만 처리하고 종료")
    parser.add_argument("--log", help="화면과 함께 이 파일에도 기록")
    args = parser.parse_args()

    if args.log:
        sys.stdout = Tee(sys.stdout, os.path.abspath(args.log))
        stamp = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        print(f"\n===== {stamp} 버튼 서버 시작 =====")

    if args.send_menu:
        return send_menu(args.date)

    try:
        return poll(once=args.once)
    except KeyboardInterrupt:
        print("\n중지했습니다.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
