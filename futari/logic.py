"""日付まわりと、家事・予定の「その日に当たるか」の判定。"""
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

JST = ZoneInfo("Asia/Tokyo")
WEEKDAYS_JA = ["月", "火", "水", "木", "金", "土", "日"]

COLORS = {
    "anzu": ("あんず", "#E39A6B"),
    "fuji": ("ふじ", "#9A8CC2"),
    "wakaba": ("わかば", "#7FA66F"),
    "sora": ("そら", "#6FA3C4"),
    "momo": ("もも", "#DD8FA0"),
    "karashi": ("からし", "#C9A23C"),
}

SHOP_CATEGORIES = [
    ("veg", "野菜・果物"),
    ("meat", "肉・魚"),
    ("dairy", "卵・乳製品"),
    ("staple", "主食・乾物"),
    ("seasoning", "調味料"),
    ("drink", "飲み物"),
    ("daily", "日用品"),
    ("other", "その他"),
]
SHOP_CATEGORY_LABEL = dict(SHOP_CATEGORIES)

MEAL_SLOTS = [("breakfast", "朝"), ("lunch", "昼"), ("dinner", "夜")]
NOTE_CATEGORIES = [("appliance", "家電・保証"), ("contract", "契約"), ("home", "住まい"), ("other", "その他")]

# 品名からカテゴリを推測するための手がかり（当たらなければ「その他」）
_CATEGORY_HINTS = {
    "veg": "玉ねぎ たまねぎ にんじん 人参 じゃがいも キャベツ レタス トマト きゅうり なす ピーマン ねぎ ネギ 大根 白菜 ほうれん草 小松菜 もやし きのこ しめじ えのき にんにく 生姜 しょうが バナナ りんご みかん レモン ブロッコリー かぼちゃ ごぼう 野菜 果物 アボカド",
    "meat": "肉 豚 牛 鶏 ひき肉 ミンチ ベーコン ハム ウインナー ソーセージ 魚 鮭 さば サバ まぐろ えび エビ いか あさり 刺身 ささみ",
    "dairy": "卵 たまご 牛乳 チーズ ヨーグルト バター 生クリーム 豆乳",
    "staple": "米 パン 食パン うどん そば パスタ 麺 小麦粉 片栗粉 パン粉 豆腐 納豆 油揚げ のり 海苔 わかめ 乾物 シリアル もち",
    "seasoning": "醤油 しょうゆ 味噌 みそ 塩 砂糖 酢 みりん 料理酒 油 ごま油 オリーブオイル マヨネーズ ケチャップ ソース だし コンソメ 胡椒 こしょう カレールー ドレッシング ポン酢 めんつゆ",
    "drink": "水 お茶 茶 コーヒー ジュース ビール ワイン 酒 炭酸 牛乳パック",
    "daily": "ティッシュ トイレットペーパー 洗剤 シャンプー リンス コンディショナー ボディソープ 歯磨き 歯ブラシ ゴミ袋 ごみ袋 ラップ アルミホイル スポンジ 電池 マスク 柔軟剤 ハンドソープ キッチンペーパー 綿棒",
}


def guess_category(name):
    for cat, words in _CATEGORY_HINTS.items():
        for w in words.split():
            if w in name:
                return cat
    return "other"


def today():
    return datetime.now(JST).date()


def parse_date(s, default=None):
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return default


def week_start(d):
    return d - timedelta(days=d.weekday())


def fmt_day(d, with_year=False):
    if isinstance(d, str):
        d = parse_date(d)
    if d is None:
        return ""
    head = f"{d.year}年" if with_year else ""
    return f"{head}{d.month}月{d.day}日（{WEEKDAYS_JA[d.weekday()]}）"


def fmt_relative(d):
    """期限などを「今日」「明日」「3日後」「2日前」で表す。"""
    if isinstance(d, str):
        d = parse_date(d)
    if d is None:
        return ""
    diff = (d - today()).days
    if diff == 0:
        return "今日"
    if diff == 1:
        return "明日"
    if diff == -1:
        return "昨日"
    if diff > 1:
        return f"{diff}日後" if diff < 7 else f"{d.month}/{d.day}"
    return f"{-diff}日前"


def parse_weekdays(s):
    return [int(x) for x in (s or "").split(",") if x.strip().isdigit() and 0 <= int(x) <= 6]


def chore_due_on(chore, d):
    start = parse_date(chore["start_date"]) or d
    if d < start:
        return False
    ft = chore["freq_type"]
    if ft == "daily":
        return True
    if ft == "weekly":
        return d.weekday() in parse_weekdays(chore["weekdays"])
    if ft == "interval":
        return (d - start).days % max(1, int(chore["interval_days"] or 1)) == 0
    return False


def chore_freq_label(chore):
    ft = chore["freq_type"]
    if ft == "daily":
        return "毎日"
    if ft == "weekly":
        days = "・".join(WEEKDAYS_JA[i] for i in parse_weekdays(chore["weekdays"]))
        return f"毎週 {days}" if days else "曜日未設定"
    n = int(chore["interval_days"] or 1)
    return f"{n}日ごと"


def event_occurs_on(ev, d):
    start = parse_date(ev["day"])
    if start is None:
        return False
    rt = ev["repeat_type"]
    if rt == "none":
        return d == start
    if d < start:
        return False
    if rt == "weekly":
        days = parse_weekdays(ev["weekdays"]) or [start.weekday()]
        return d.weekday() in days
    if rt == "monthly":
        return d.day == start.day
    if rt == "yearly":
        return (d.month, d.day) == (start.month, start.day)
    return False


def event_repeat_label(ev):
    rt = ev["repeat_type"]
    if rt == "weekly":
        start = parse_date(ev["day"])
        days = parse_weekdays(ev["weekdays"]) or ([start.weekday()] if start else [])
        return "毎週 " + "・".join(WEEKDAYS_JA[i] for i in days)
    return {"monthly": "毎月", "yearly": "毎年"}.get(rt, "")


def visible_event(ev, viewer_id, names):
    """閲覧者から見た予定を返す。見せない予定は None。

    世帯の予定（owner_id なし）と自分の予定はそのまま。
    相手の予定は公開範囲に従う: private=見せない / busy=時間だけ / full=内容も。
    """
    owner = ev["owner_id"]
    out = dict(ev)
    out["mine"] = owner == viewer_id
    out["shared"] = owner is None
    out["owner_name"] = names.get(owner, "") if owner else ""
    out["masked"] = False
    if owner is None or owner == viewer_id:
        return out
    if ev["visibility"] == "private":
        return None
    if ev["visibility"] == "busy":
        out["title"] = "予定あり"
        out["memo"] = ""
        out["masked"] = True
    return out


def events_on(events, d, viewer_id, names):
    out = []
    for ev in events:
        if event_occurs_on(ev, d):
            v = visible_event(ev, viewer_id, names)
            if v:
                out.append(v)
    out.sort(key=lambda e: (e["start_time"] or "", e["title"]))
    return out
