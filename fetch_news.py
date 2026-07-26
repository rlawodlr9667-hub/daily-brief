# -*- coding: utf-8 -*-
"""
경제뉴스 수집기.

여러 언론사 RSS를 모아서 -> 최근 기사만 남기고 -> 중복을 묶고 ->
중요한 것만 골라서 data/raw_YYYY-MM-DD.md 파일로 저장합니다.

요약과 결론은 이 스크립트가 하지 않습니다. Claude Code가 위 파일을 읽고 작성합니다.

사용법:
    python fetch_news.py           # 최근 24시간
    python fetch_news.py --hours 48
"""

import argparse
import html
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feeds as cfg

# Windows 터미널에서 한글이 깨지지 않도록
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

KST = timezone(timedelta(hours=9))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) DailyBrief/1.0"


# ---------------------------------------------------------------------------
# 1단계: RSS 가져오기
# ---------------------------------------------------------------------------
def fetch_feed(url):
    """RSS 하나를 받아서 XML 트리로 돌려줍니다. 실패하면 예외를 냅니다."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=cfg.FEED_TIMEOUT) as resp:
        raw = resp.read()

    # 일부 언론사(이데일리)는 파일 맨 앞에 BOM을 붙여 보내는데
    # 그대로 두면 XML 파서가 거부합니다.
    raw = raw.lstrip(b"\xef\xbb\xbf").lstrip()
    return ET.fromstring(raw)


def extract_items(root):
    """RSS든 Atom이든 기사 목록을 뽑아냅니다."""
    items = root.findall(".//item")
    if items:
        return items, False
    # Atom 형식 대비 (지금 등록된 피드에는 없지만 나중에 추가할 수도 있음)
    entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    return entries, True


def get_text(item, *names):
    """태그 이름 후보들을 순서대로 찾아 첫 번째 값을 돌려줍니다."""
    for name in names:
        value = item.findtext(name)
        if value:
            return value.strip()
        # Atom 네임스페이스도 시도
        value = item.findtext("{http://www.w3.org/2005/Atom}" + name)
        if value:
            return value.strip()
    return ""


def get_link(item):
    link = get_text(item, "link")
    if link:
        return link
    # Atom은 <link href="..."/> 형태
    node = item.find("{http://www.w3.org/2005/Atom}link")
    if node is not None:
        return node.get("href", "")
    return ""


# 표준(RFC 2822)을 안 지키는 피드가 꽤 있어서 형식별로 시도합니다.
#   Investing.com  ->  "2026-07-26 05:03:42"
#   Investing 분석  ->  "Jul 25, 2026 10:24 GMT"
DATE_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%b %d, %Y %H:%M %Z",
    "%b %d, %Y %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
]


def parse_date(value):
    """pubDate 문자열을 한국시간 datetime으로. 실패하면 None."""
    if not value:
        return None
    value = value.strip()

    dt = None
    try:
        dt = parsedate_to_datetime(value)      # 대부분의 피드
    except (TypeError, ValueError):
        pass

    if dt is None:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass

    if dt is None:
        for fmt in DATE_FORMATS:
            try:
                dt = datetime.strptime(value, fmt)
                break
            except ValueError:
                continue

    if dt is None:
        return None

    if dt.tzinfo is None:
        # 시간대 표기가 없는 피드는 대부분 UTC 기준입니다.
        # (국내 매체는 모두 +0900 을 명시하므로 여기 걸리지 않습니다)
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(KST)


# ---------------------------------------------------------------------------
# 2단계: 본문 정리
# ---------------------------------------------------------------------------
TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")


def clean_text(value, limit=220):
    """RSS 요약문에서 HTML 태그와 특수문자 코드를 걷어냅니다."""
    if not value:
        return ""
    text = html.unescape(value)
    text = TAG_RE.sub(" ", text)
    text = html.unescape(text)  # 태그 제거 후 남은 &nbsp; 등 한 번 더
    text = text.replace("​", "").replace("\xa0", " ")
    text = SPACE_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text


# ---------------------------------------------------------------------------
# 3단계: 카테고리 재분류
# ---------------------------------------------------------------------------
def classify(title, default_category):
    """제목 키워드를 보고 어느 항목에 넣을지 정합니다.

    가장 많이 걸린 항목으로 배정하고, 같은 수면 KEYWORDS 에 먼저 적힌 항목이
    이깁니다. 하나도 걸리지 않으면 피드의 기본 항목을 씁니다.

    기본 항목이 None(종합 경제 피드)이고 키워드도 안 걸리면 None 을 돌려줍니다.
    이 기사는 버려집니다. 5개 항목에 안 맞는 기사를 억지로 끼워넣지 않기 위함입니다.
    """
    lowered = title.lower()

    best_key = None
    best_hits = 0
    for key, words in cfg.KEYWORDS.items():
        hits = 0
        for word in words:
            # 영문 키워드는 대소문자를 무시하고 찾습니다.
            if word.isascii():
                if word in lowered:
                    hits += 1
            elif word in title:
                hits += 1
        if hits > best_hits:
            best_key, best_hits = key, hits

    if best_key:
        return best_key
    return default_category


# ---------------------------------------------------------------------------
# 4단계: 중복 묶기
# ---------------------------------------------------------------------------
NON_WORD_RE = re.compile(r"[^0-9A-Za-z가-힣]+")
HANGUL_RE = re.compile(r"[가-힣]")
EN_WORD_RE = re.compile(r"[a-z0-9]+")

# 영어 제목에서 흔해서 변별력이 없는 단어들
EN_STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "will", "has", "have",
    "are", "was", "were", "its", "his", "her", "their", "about", "after", "before",
    "into", "over", "under", "more", "most", "than", "then", "but", "not", "you",
    "your", "our", "why", "how", "what", "who", "when", "where", "can", "could",
    "would", "should", "may", "might", "one", "two", "new", "says", "said", "get",
}


def normalize_title(title):
    """비교용으로 제목에서 기호와 공백을 걷어냅니다."""
    text = re.sub(r"\[[^\]]*\]", " ", title)   # [속보], [단독] 등 말머리 제거
    text = re.sub(r"<[^>]*>", " ", text)
    text = NON_WORD_RE.sub("", text)
    return text.lower()


def bigrams(text):
    """글자 2개씩 잘라 집합으로."""
    if len(text) < 2:
        return {text} if text else set()
    return {text[i:i + 2] for i in range(len(text) - 1)}


def signature(title):
    """제목을 비교용 (언어, 조각집합)으로 바꿉니다.

    한국어는 조사가 붙어 단어가 계속 변하므로 글자 2개 단위가 잘 맞습니다.
    ("이재용, 오픈AI 본사서 만났다" vs "이재용·올트먼, 오픈AI 본사서 회동")

    영어는 반대입니다. 알파벳이 26자뿐이라 전혀 무관한 두 기사도
    th, in, er 같은 조각을 잔뜩 공유해서 글자 단위 비교가 무의미합니다.
    그래서 흔한 단어를 뺀 단어 집합으로 비교합니다.
    """
    if HANGUL_RE.search(title):
        return "ko", bigrams(normalize_title(title))
    words = {w for w in EN_WORD_RE.findall(title.lower())
             if len(w) >= 3 and w not in EN_STOPWORDS}
    return "en", words


def similarity(a, b):
    """겹침 계수. 제목 길이가 서로 달라도 공정하게 비교됩니다.

    (자카드 계수를 쓰면 짧은 제목과 긴 제목이 같은 사건이어도 점수가 낮게 나옵니다)
    """
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def is_same_story(sig_a, sig_b):
    lang_a, set_a = sig_a
    lang_b, set_b = sig_b
    if lang_a != lang_b:
        return False   # 한글 기사와 영문 기사는 묶지 않습니다

    smaller = min(len(set_a), len(set_b))
    if lang_a == "ko":
        if smaller < 6:      # 제목이 너무 짧으면 우연히 겹칠 수 있음
            return False
        return similarity(set_a, set_b) >= cfg.DEDUP_THRESHOLD_KO

    if smaller < 3 or len(set_a & set_b) < 2:
        return False
    return similarity(set_a, set_b) >= cfg.DEDUP_THRESHOLD_EN


def dedupe(articles):
    """같은 사건을 다룬 기사를 하나로 묶습니다.

    묶으면서 몇 개 언론사가 보도했는지(covered_by)를 세는데,
    이게 곧 '얼마나 중요한 뉴스인가'의 가장 강한 신호가 됩니다.
    """
    clusters = []  # {"rep": 대표기사, "sig": 기준 서명, "sources": set, "titles": list}

    for art in articles:
        sig = art["_sig"]
        matched = None
        for cluster in clusters:
            if is_same_story(sig, cluster["sig"]):
                matched = cluster
                break

        if matched is None:
            clusters.append({
                "rep": art,
                "sig": sig,
                "sources": {art["source"]},
                "titles": [art["title"]],
            })
        else:
            matched["sources"].add(art["source"])
            matched["titles"].append(art["title"])
            # 더 최신 기사를 대표로 삼습니다. (묶음 기준 서명은 그대로 둡니다)
            if art["date"] and matched["rep"]["date"] and art["date"] > matched["rep"]["date"]:
                matched["rep"] = art

    result = []
    for cluster in clusters:
        rep = dict(cluster["rep"])
        rep["covered_by"] = len(cluster["sources"])
        rep["sources"] = sorted(cluster["sources"])
        rep["other_titles"] = [t for t in cluster["titles"] if t != rep["title"]]
        result.append(rep)
    return result


# ---------------------------------------------------------------------------
# 5단계: 중요도 점수
# ---------------------------------------------------------------------------
def score(article, now):
    """높을수록 브리핑에 들어갈 확률이 높습니다."""
    points = 0.0

    # (1) 여러 언론사가 동시에 다뤘다 = 중요하다. 가장 강한 신호.
    points += (article["covered_by"] - 1) * 3.0

    # (2) 핵심 경제 키워드가 제목에 있는가
    title = article["title"]
    if HANGUL_RE.search(title):
        hits = sum(1 for word in cfg.IMPORTANT_WORDS if word in title)
    else:
        words = set(EN_WORD_RE.findall(title.lower()))
        hits = sum(1 for word in cfg.IMPORTANT_WORDS_EN if word in words)
    points += min(hits, 4) * 1.5

    # (3) 최신일수록 조금 유리하게
    if article["date"]:
        hours_old = (now - article["date"]).total_seconds() / 3600
        points += max(0.0, 3.0 - hours_old / 6.0)

    # (4) 요약문이 아예 없는 기사는 살짝 감점 (Claude가 읽을 내용이 적음)
    if not article["summary"]:
        points -= 1.0

    # (5) 보도자료·재난·지역 기사 감점. 브리핑 잡음의 대부분이 여기서 걸립니다.
    if HANGUL_RE.search(title):
        penalties = sum(1 for word in cfg.NEGATIVE_WORDS if word in title)
    else:
        lowered = title.lower()
        penalties = sum(1 for word in cfg.NEGATIVE_WORDS_EN if word in lowered)
    points -= min(penalties, 2) * cfg.NEGATIVE_PENALTY

    return points


def select(articles, limit, per_source):
    """점수 순으로 뽑되, 한 언론사가 항목을 독점하지 못하게 막습니다.

    상한에 걸린 매체의 기사는 일단 건너뛰고, 다른 매체로 자리를 채운 뒤
    그래도 자리가 남으면 다시 채웁니다. (뉴스가 적은 날 빈칸이 생기지 않게)
    """
    ranked = sorted(articles, key=lambda a: a["score"], reverse=True)

    picked = []
    used = {}
    leftovers = []

    for art in ranked:
        if len(picked) >= limit:
            break
        source = art["source"]
        if used.get(source, 0) >= per_source:
            leftovers.append(art)
            continue
        picked.append(art)
        used[source] = used.get(source, 0) + 1

    for art in leftovers:
        if len(picked) >= limit:
            break
        picked.append(art)

    picked.sort(key=lambda a: a["score"], reverse=True)
    return picked


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------
def collect(hours):
    now = datetime.now(KST)
    cutoff = now - timedelta(hours=hours)

    articles = []
    seen_links = set()
    ok_count = 0
    fail_list = []
    dropped = 0        # 5개 항목에 해당하지 않아 버린 기사 수

    for default_category, source, url in cfg.FEEDS:
        try:
            root = fetch_feed(url)
        except (urllib.error.URLError, urllib.error.HTTPError, ET.ParseError,
                OSError, ValueError) as exc:
            # 한 곳이 죽어도 브리핑은 나와야 합니다.
            fail_list.append((source, url, type(exc).__name__))
            continue

        items, _is_atom = extract_items(root)
        taken = 0
        for item in items:
            title = clean_text(get_text(item, "title"), limit=200)
            if not title:
                continue
            if any(word in title for word in cfg.EXCLUDE_WORDS):
                continue

            link = get_link(item)
            if link in seen_links:
                continue

            published = parse_date(get_text(item, "pubDate", "published", "updated", "date"))
            if published is None or published < cutoff:
                continue
            if published > now + timedelta(hours=1):
                continue  # 미래 날짜는 오류로 간주

            category = classify(title, default_category)
            if category is None:
                # 종합 경제 피드에서 왔지만 5개 항목 어디에도 맞지 않는 기사
                dropped += 1
                continue

            if link:
                seen_links.add(link)

            articles.append({
                "title": title,
                "link": link,
                "source": source,
                "date": published,
                "summary": clean_text(get_text(item, "description", "summary", "content")),
                "category": category,
                "_sig": signature(title),
            })
            taken += 1

        ok_count += 1
        print(f"  [수집] {source:12s} {taken:3d}건  ({url.split('/')[2]})")

    return articles, ok_count, fail_list, dropped, now


def build_markdown(by_category, now, stats):
    lines = []
    lines.append(f"# 경제뉴스 원본 수집 — {now.strftime('%Y-%m-%d %H:%M')} KST")
    lines.append("")
    lines.append(f"수집 범위: 최근 {stats['hours']}시간 / "
                 f"피드 {stats['ok']}개 성공, {stats['fail']}개 실패 / "
                 f"채택 {stats['total']}건 (항목 불일치로 버림 {stats['dropped']}건) → "
                 f"중복 정리 {stats['unique']}건 → 선별 {stats['selected']}건")
    lines.append("")
    lines.append("> 이 파일은 자동 생성된 **원본 자료**입니다. 요약·결론은 들어 있지 않습니다.")
    lines.append("")

    for key, label, emoji in cfg.CATEGORIES:
        group = by_category.get(key, [])
        by_source = {}
        for art in group:
            by_source[art["source"]] = by_source.get(art["source"], 0) + 1
        mix = ", ".join(f"{s} {n}" for s, n in
                        sorted(by_source.items(), key=lambda kv: -kv[1]))

        lines.append(f"## {emoji} [{key}] {label}  ({len(group)}건)")
        lines.append("")
        if not group:
            lines.append("_해당 기간에 선별된 기사가 없습니다._")
            lines.append("")
            continue
        lines.append(f"매체 구성: {mix}")
        lines.append("")

        for idx, art in enumerate(group, 1):
            when = art["date"].strftime("%m-%d %H:%M") if art["date"] else "시각미상"
            lines.append(f"### {idx}. {art['title']}")
            meta = f"- 출처: {art['source']} | {when}"
            if art["covered_by"] > 1:
                meta += f" | **{art['covered_by']}개 매체 동시 보도** ({', '.join(art['sources'])})"
            lines.append(meta)
            if art["summary"]:
                lines.append(f"- 내용: {art['summary']}")
            for other in art.get("other_titles", [])[:3]:
                lines.append(f"- 관련 제목: {other}")
            if art["link"]:
                lines.append(f"- 링크: {art['link']}")
            lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="경제뉴스 RSS 수집기")
    parser.add_argument("--hours", type=int, default=24,
                        help="몇 시간 전까지의 기사를 모을지 (기본 24)")
    args = parser.parse_args()

    print(f"경제뉴스를 모으는 중입니다... (최근 {args.hours}시간)\n")

    articles, ok_count, fail_list, dropped, now = collect(args.hours)

    if fail_list:
        print()
        for source, url, err in fail_list:
            print(f"  [실패] {source} — {err} ({url})")

    if not articles:
        print("\n기사를 한 건도 가져오지 못했습니다. 인터넷 연결을 확인해 주세요.")
        return 1

    total = len(articles)
    unique = dedupe(articles)

    for art in unique:
        art["score"] = score(art, now)

    by_category = {}
    for key, _label, _emoji in cfg.CATEGORIES:
        group = [a for a in unique
                 if a["category"] == key and a["score"] >= cfg.MIN_SCORE]
        by_category[key] = select(group, cfg.MAX_PER_CATEGORY, cfg.MAX_PER_SOURCE)

    selected = sum(len(v) for v in by_category.values())

    stats = {
        "hours": args.hours,
        "ok": ok_count,
        "fail": len(fail_list),
        "total": total,
        "dropped": dropped,
        "unique": len(unique),
        "selected": selected,
    }

    os.makedirs(DATA_DIR, exist_ok=True)
    out_path = os.path.join(DATA_DIR, f"raw_{now.strftime('%Y-%m-%d')}.md")
    with open(out_path, "w", encoding="utf-8") as fp:
        fp.write(build_markdown(by_category, now, stats))

    print(f"\n채택 {total}건 (항목 불일치 {dropped}건 버림) "
          f"→ 중복 정리 {len(unique)}건 → 선별 {selected}건")
    for key, label, _emoji in cfg.CATEGORIES:
        group = by_category[key]
        sources = sorted({a["source"] for a in group})
        print(f"  {label:10s} {len(group):2d}건  (매체 {len(sources)}곳: {', '.join(sources)})")
    print(f"\n저장 완료: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
