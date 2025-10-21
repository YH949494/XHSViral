#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, os, random, datetime, urllib.request, time, re
from collections import defaultdict

# ================== 基本设置 ==================
TODAY      = datetime.date.today()
WEEK_OF    = TODAY.isoformat()
REGION     = os.environ.get("REGION_HINT", "GLOBAL").upper()  # 可设 CN / MY / SG
OPENHOT_XHS = "https://open-hot-api.vercel.app/api/getlist?type=xiaohongshu"

ROOT        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRENDS_PATH = os.path.join(ROOT, "xhs_trends.json")
CANDI_PATH  = os.path.join(ROOT, "candidates.json")

MAX_PER_CATEGORY = 12   # 每类上限
MIN_W, MAX_W     = 0.78, 0.96

SENSITIVE_MAP = {
    "减脂": "健康餐",
    "减肥": "塑形",
    "抽奖": "福利",
    "丰胸": "改善身材",
    "投资": "理财思路"
}

# ================== 季节 & 节日加权 ==================
def season_boost(keyword: str) -> float:
    """按季节/节日给权重增益，范围建议 0.0~0.2"""
    k = keyword.lower()
    m = TODAY.month
    # Q4 通用加权
    boost = 0.0
    if m in (10, 11, 12):
        if any(t in k for t in ["秋冬", "秋季", "冬季", "年末", "清单"]):
            boost += 0.08
    # 双十一（10/20~11/15）
    start_1111 = datetime.date(TODAY.year, 10, 20)
    end_1111   = datetime.date(TODAY.year, 11, 15)
    if start_1111 <= TODAY <= end_1111:
        if any(t in keyword for t in ["双十一", "大促", "预售", "清单", "攻略"]):
            boost += 0.12
    # 圣诞/跨年（12/1~1/1）
    start_xmas = datetime.date(TODAY.year, 12, 1)
    end_xmas   = datetime.date(TODAY.year + 1, 1, 1)
    if start_xmas <= TODAY <= end_xmas:
        if any(t in k for t in ["圣诞", "跨年", "派对", "礼物"]):
            boost += 0.1
    # 开学季（8/15~9/30 & 2/10~3/10）
    if (datetime.date(TODAY.year, 8, 15) <= TODAY <= datetime.date(TODAY.year, 9, 30)) \
       or (datetime.date(TODAY.year, 2, 10) <= TODAY <= datetime.date(TODAY.year, 3, 10)):
        if any(t in keyword for t in ["开学季", "校园", "通勤", "收纳", "清单"]):
            boost += 0.08
    return min(boost, 0.2)

# 地区偏好（轻微加权）
def region_boost(category: str, keyword: str) -> float:
    k = keyword.lower()
    if REGION == "MY":
        # 大马偏好：咖啡、平价小家电、美食、一日游/短途
        if category in ("food", "home") or "咖啡" in k or "短途" in keyword or "周末" in keyword:
            return 0.04
    if REGION == "SG":
        # 新加坡偏好：效率/收纳/通勤/健身
        if category in ("fitness", "fashion") or "收纳" in keyword or "通勤" in keyword:
            return 0.04
    if REGION == "CN":
        # 中国偏好：大促/平替/清单/测评
        if "平替" in keyword or "清单" in keyword or "测评" in keyword:
            return 0.04
    return 0.0

# ================== 工具函数 ==================
def clamp(x, lo, hi): return max(lo, min(hi, x))

def strip_json_comments(s: str) -> str:
    s = re.sub(r'//.*', '', s)
    s = re.sub(r'/\*[\s\S]*?\*/', '', s)
    return s

def load_json(path, default):
    if os.path.exists(path):
        raw = open(path, "r", encoding="utf-8").read().strip()
        if not raw: return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return json.loads(strip_json_comments(raw))
    return default

def decay_weight(w, days=7, half_life=10):
    factor = 0.5 ** (days / half_life)
    return clamp(round(w * factor, 4), MIN_W - 0.2, 0.99)

def ensure_fields(item):
    item.setdefault("decay_days", 10)
    item.setdefault("priority", 1)
    item.setdefault("sensitive_hint", False)
    for k, v in SENSITIVE_MAP.items():
        if k in item["keyword"]:
            item["sensitive_hint"] = True
            item["safe_replacement"] = v
    return item

def normalize_keyword(item):
    if item.get("sensitive_hint") and item.get("safe_replacement"):
        item["keyword"] = item["safe_replacement"]
        item["sensitive_hint"] = False
        item.pop("safe_replacement", None)
    return item

def http_get_json(url, retries=2, timeout=10):
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36"
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if i < retries:
                time.sleep(1.2 * (i + 1))
                continue
            print(f"[WARN] GET {url} failed: {e}")
            return None

# 更细的分类映射
def categorize(kw: str) -> str:
    k = kw.lower()
    # 先精准
    if "ootd" in k or "穿搭" in kw or "搭配" in kw or "大衣" in kw or "靴" in kw or "羽绒" in kw: return "fashion"
    if any(t in kw for t in ["粉底", "底妆", "精华", "护肤", "口红", "眼影", "腮红", "修容", "发色", "护发", "防晒"]): return "beauty"
    if any(t in kw for t in ["咖啡", "料理", "早餐", "宵夜", "餐", "菜谱", "食谱", "烘焙", "美食", "奶茶"]): return "food"
    if any(t in kw for t in ["跑步", "健身", "力量", "瑜伽", "打卡", "HIIT", "普拉提", "马拉松"]): return "fitness"
    if any(t in kw for t in ["旅行", "vlog", "露营", "出行", "攻略", "机票", "酒店", "短途", "周末"]): return "travel"
    if any(t in kw for t in ["猫", "狗", "宠物", "毛孩子", "铲屎"]): return "pet"
    if any(t in kw for t in ["双十一", "大促", "预售", "清单", "好物", "必买"]): return "shopping"
    # 模糊回退
    if "清单" in kw or "攻略" in kw: return "shopping"
    return "mixed"

def fetch_openhot_xhs():
    data = http_get_json(OPENHOT_XHS)
    items = []
    if isinstance(data, dict):
        for d in data.get("data", []):
            title = (d.get("title") or "").strip()
            if not title:
                continue
            cat = categorize(title)
            base_w = 0.84 + random.uniform(0.0, 0.08)
            # 季节/节日/地区加权
            w = base_w + season_boost(title) + region_boost(cat, title)
            items.append({
                "keyword": title,
                "weight": round(clamp(w, MIN_W, MAX_W), 2),
                "category": cat,
                "decay_days": 7,
                "priority": 2
            })
    return items

# ================== 主流程 ==================
def main():
    # 1) 候选词：本地 + OpenHot
    candi = load_json(CANDI_PATH, {"items": []})
    candidates = [ensure_fields(x) for x in candi.get("items", [])]
    oh_items = fetch_openhot_xhs()
    if oh_items:
        candidates.extend(oh_items)

    # 2) 旧词衰减 & 过滤过期
    old = load_json(TRENDS_PATH, {"week_of": WEEK_OF, "region": REGION or "GLOBAL", "items": []})
    kept = []
    for it in old.get("items", []):
        it = ensure_fields(it)
        exp = it.get("expires_at")
        if exp:
            try:
                if TODAY > datetime.date.fromisoformat(exp):
                    continue
            except Exception:
                pass
        it["weight"] = decay_weight(it.get("weight", 0.85), days=7, half_life=it.get("decay_days", 10))
        kept.append(it)

    # 3) 去重 & 排序
    existing = set(x["keyword"] for x in kept)

    def sort_key(x):
        return (x.get("weight", 0.85)
                + 0.04 * x.get("priority", 1)
                + random.uniform(-0.015, 0.015))

    candidates.sort(key=sort_key, reverse=True)

    # 4) 分桶补齐
    buckets = defaultdict(list)
    for it in kept:
        buckets[it.get("category", "misc")].append(it)

    for item in candidates:
        item = normalize_keyword(ensure_fields(item))
        kw = item["keyword"]
        if kw in existing:
            continue
        cat = item.get("category", "misc")
        # 终端再加一次季节/地区轻微加权，保证更贴时令
        item["weight"] = clamp(item.get("weight", 0.85) + 0.02 * (1 if season_boost(kw) > 0 else 0) + 0.01, MIN_W, MAX_W)
        item["weight"] = round(item["weight"], 2)
        if len(buckets[cat]) < MAX_PER_CATEGORY:
            buckets[cat].append(item)
            existing.add(kw)

    # 5) 类内排序 & 裁剪
    new_items = []
    for cat, arr in buckets.items():
        arr.sort(key=lambda x: (x.get("weight", 0.85), x.get("priority", 1)), reverse=True)
        new_items.extend(arr[:MAX_PER_CATEGORY])

    out = {
        "week_of": WEEK_OF,
        "region": REGION or old.get("region", "GLOBAL"),
        "items": new_items
    }
    with open(TRENDS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[OK] Updated xhs_trends.json with {len(new_items)} items on {WEEK_OF} (REGION={REGION})")

if __name__ == "__main__":
    main()
