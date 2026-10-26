"""Listing definitions shared with JavaScript through generated page JSON."""
from __future__ import annotations

from typing import Any
import re
import unicodedata


KANTO_PREFECTURES = ("東京都", "神奈川県", "埼玉県", "千葉県", "茨城県", "栃木県", "群馬県")
REGIONS = {
    "kanto": {
        "name": "関東", "eyebrow": "KANTO KEIKO", "path": "/area/kanto/", "key": "area/kanto/index.html",
        "prefectures": list(KANTO_PREFECTURES),
        "title": "関東の剣道稽古会・錬成会｜日程を比較｜剣道稽古ナビ",
        "description": "関東1都6県のオープン・合同・連盟稽古会と、大人向け錬成会・練習試合の予定。都県・日付・参加条件で絞り込み、月間カレンダーや土日比較から次の稽古先を探せます。",
        "guidance": "関東ページでは、東京都・神奈川県・埼玉県・千葉県・茨城県・栃木県・群馬県の開催予定をまとめています。近隣の都県まで範囲を広げ、同じ土日でも移動できる会場と開始時刻を比べてみてください。",
    },
    "tokyo": {
        "name": "東京都", "eyebrow": "TOKYO KEIKO", "path": "/area/tokyo/", "key": "area/tokyo/index.html",
        "prefectures": ["東京都"],
        "title": "東京都の剣道稽古会・錬成会｜開催日から探す｜剣道稽古ナビ",
        "description": "東京都内のオープン・合同・連盟稽古会と、大人向け錬成会・練習試合の予定。会場・日付・団体・参加条件から絞り込み、一覧とカレンダーで公式案内を確認できます。",
        "guidance": "東京都内でも開催場所・開始時刻・参加対象は会ごとに異なります。都内の予定を日付と会場から確認し、通える時間帯の候補を探せます。近隣の県も含めて比較したい場合は、関東ページをご覧ください。",
    },
}


def event_prefecture(event: dict[str, Any]) -> str:
    """Use the venue's area only; reject ambiguous or non-prefecture values."""
    value = event.get("area")
    if not isinstance(value, str):
        return ""
    area = unicodedata.normalize("NFKC", value).strip()
    # Checking all prefectural suffixes also rejects Tokyo/Osaka combinations.
    names = re.findall(r"東京都|北海道|(?:京都|大阪)府|[^\s、,・/／]+?県", area)
    matched = [name for name in KANTO_PREFECTURES if area.startswith(name)]
    return matched[0] if len(matched) == 1 and names == matched else ""


def select_region_events(events: list[dict[str, Any]], region: str) -> list[dict[str, Any]]:
    prefectures = REGIONS[region]["prefectures"]
    return [event for event in events if event_prefecture(event) in prefectures]


def listing_page_keys() -> tuple[str, ...]:
    """Leaf pages precede the homepage that links to them."""
    return tuple(page["key"] for page in REGIONS.values()) + ("keiko/index.html", "renseikai/index.html", "index.html")

CATEGORIES = {
    "all": {"label": "すべて", "types": None},
    "keiko": {"label": "稽古会", "types": ["open_keiko", "federation_keiko"]},
    "renseikai": {"label": "錬成会・練習試合", "types": ["adult_renseikai"]},
}
TYPE_LABELS = {
    "open_keiko": "オープン・合同稽古会",
    "federation_keiko": "連盟稽古会",
    "adult_renseikai": "錬成会・練習試合",
}
UNKNOWN_TYPE_LABEL = "種別未分類"
PAGES = {
    "all": {
        "path": "/", "key": "index.html", "heading": "稽古会・錬成会を探す",
        "title": "剣道稽古ナビ｜稽古会・錬成会・練習試合を地域と日付から検索",
        "description": "参加できる剣道のオープン稽古会・合同稽古会・連盟稽古会と、大人向け錬成会・練習試合を開催日順に掲載。地域・日付・参加条件から探せます。",
    },
    "keiko": {
        "path": "/keiko/", "key": "keiko/index.html", "heading": "稽古会を探す",
        "title": "稽古会一覧｜オープン・合同・連盟稽古会｜剣道稽古ナビ",
        "description": "剣道のオープン稽古会・合同稽古会・連盟稽古会の開催予定。地域・日付・団体・参加条件で絞り込み、公式情報から参加方法を確認できます。",
    },
    "renseikai": {
        "path": "/renseikai/", "key": "renseikai/index.html", "heading": "大人向け錬成会・練習試合を探す",
        "title": "大人向け錬成会・練習試合一覧｜剣道稽古ナビ",
        "description": "大人が外部から参加できる剣道の錬成会・練習試合の開催予定。地域・日付・参加条件で探し、申込方法や参加資格は主催者の公式情報をご確認ください。",
    },
}


def select_events(events: list[dict[str, Any]], category: str) -> list[dict[str, Any]]:
    types = CATEGORIES[category]["types"]
    return [event for event in events if types is None or event.get("event_type") in types]


def type_label(event: dict[str, Any]) -> str:
    value = event.get("event_type")
    return TYPE_LABELS.get(value, UNKNOWN_TYPE_LABEL) if isinstance(value, str) else UNKNOWN_TYPE_LABEL
