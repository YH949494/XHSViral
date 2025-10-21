#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, os, math, random, datetime, urllib.request, urllib.error, time, re
from collections import defaultdict

# ---------- 基本参数 ----------
TODAY = datetime.date.today()
WEEK_OF = TODAY.isoformat()

# 每类最多保留的热词数量
MAX_PER_CATEGORY = 12
# 权重边界
MIN_W, MAX_W = 0.78, 0.96

# 敏感词安全替换（可自行扩展）
SENSITIVE_MAP = {
    "减脂": "健康餐",
    "减肥": "塑形",
    "抽奖": "福利",
    "丰胸": "改善身材",
    "投资": "理财思路"
}

# 路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRENDS_PATH = os.path.join(ROOT, "xhs_trends.json")
CANDI_PATH  = os.path.join(ROOT, "candidates.json")

# OpenHot（仅取小红书热榜）
OPENHOT_XHS = "https://open-hot-api.vercel.app/api/getlist?type=xiaohongshu"


# ---------- 工具函数 ----------
def clamp(x, lo, hi): 
    return max(lo, min(hi, x))

def strip_json_comments(s: str) -> str:
    s = re.sub(r'//.*', '', s)
    s = re.sub(r'/\*[\s\S]*?\*/', '', s)
    return s

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
            if not raw:
                return default
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                cleaned = strip_json_comments(raw)
                return json.loads(cleaned)
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
    # 若标注敏感且有安全替换 → 用替换词；否则保留原词（也可选择丢弃）
    if item.get("sensitive_hint") and item.get("safe_replacement"):
        item["keyword"] = item["safe_replacement"]
        item["sensitive_hint"] = False
        item.pop("safe_replacement", None)
    return item

# 关键词 → 类目（简单启发式，可按需扩展）
def categorize(kw: str) -> str:
    m = kw.lower()
    if any(t in m for t in ["穿搭","ootd","发色","口红","粉底","底妆","精华","护肤","修护","眼影","腮红","妆"]):
        # 穿搭/美妆混合判断
        if "穿搭" in kw or "ootd" in m:
            return "fashion"
        return "beauty"
    if any(t in m for t in ["咖啡","料理","早餐","宵夜","餐","食","美食","食谱"]):
        return "food"
    if any(t in m for t in ["跑步","健身","瑜伽","运动","打卡"]):
        return "fitness"
    if any(t in m for t in ["旅行","vlog","露营","出行","攻略","机票","酒店","游"]):
        return "travel"
    if any(t in m for t in ["猫","狗","宠物","毛孩子"]):
        return "pet"
    if any(t in m for t in ["双十一","大促","清单","攻略"]):
        return "shopping"
    return "mixed"

def http_get_json(url, retries=2, timeout=10):
    ua = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36"
    for i in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": ua})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            if i < retries:
                time.sleep(1.5 * (i + 1))
                continue
            print(f"[WARN] GET {url} failed: {e}")
            return None

def fetch_openhot_xhs():
    """从 OpenHot 拉小红书热榜，转为候选 items"""
    data = http_get_json(OPENHOT_XHS)
    items = []
    if isinstance(data, dict):
        arr = data.get("data", [])
        for d in arr:
            title = (d.get("title") or "").strip()
            if not title:
                continue
            items.append({
                "keyword": title,
                # 给个基础权重，带一点轻微扰动（避免全相同）
                "weight": round(0.84 + random.uniform(0.0, 0.08), 2),
                "category": categorize(title),
                "decay_days": 7,
                "priority": 2  # 热榜来源，优先级给高一点
            })
    return items


# ---------- 主流程 ----------
def main():
    # 1) 读 candidates（你日常维护它）
    candi = load_json(CANDI_PATH, {"items": []})
    candidates = [ensure_fields(x) for x in candi.get("items", [])]

    # 2) 拉 OpenHot（小红书热榜）
    oh_items = fetch_openhot_xhs()
    if oh_items:
        candidates.extend(oh_items)

    # 3) 读旧 trends（用于衰减）
    old = load_json(TRENDS_PATH, {"week_of": WEEK_OF, "region": "GLOBAL", "items": []})
    old_items = old.get("items", [])

    # 旧词衰减 & 过滤过期
    kept = []
    for it in old_items:
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

    # 去重集合（以 keyword 为准）
    existing = set(x["keyword"] for x in kept)

    # 候选排序（权重 + 优先级 + 轻微扰动）
    def sort_key(x):
        return (x.get("weight", 0.85)
                + 0.03 * x.get("priority", 1)
                + random.uniform(-0.02, 0.02))

    candidates.sort(key=sort_key, reverse=True)

    # 分桶
    buckets = defaultdict(list)
    for it in kept:
        buckets[it.get("category", "misc")].append(it)

    # 逐个补充到各类，控制上限
    for item in candidates:
        item = normalize_keyword(ensure_fields(item))
        kw = item["keyword"]
        if kw in existing:
            continue
        cat = item.get("category", "misc")
        # 规范权重
        item["weight"] = clamp(item.get("weight", 0.85), MIN_W, MAX_W)
        item["weight"] = round(item["weight"], 2)

        if len(buckets[cat]) < MAX_PER_CATEGORY:
            buckets[cat].append(item)
            existing.add(kw)

    # 组装输出 & 类内排序
    new_items = []
    for cat, arr in buckets.items():
        arr.sort(key=lambda x: (x.get("weight", 0.85), x.get("priority", 1)), reverse=True)
        new_items.extend(arr[:MAX_PER_CATEGORY])

    out = {
        "week_of": WEEK_OF,
        "region": old.get("region", "GLOBAL"),
        "items": new_items
    }

    with open(TRENDS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"[OK] Updated xhs_trends.json with {len(new_items)} items on {WEEK_OF}")

if __name__ == "__main__":
    main()
