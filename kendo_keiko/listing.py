"""Listing definitions shared with JavaScript through generated page JSON."""
from __future__ import annotations

from typing import Any

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
