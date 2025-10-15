#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json, os, math, random, datetime
from collections import defaultdict

TODAY = datetime.date.today()
WEEK_OF = TODAY.isoformat()

# 每类最多保留多少个热词（可调）
MAX_PER_CATEGORY = 12
# 权重上下限
MIN_W, MAX_W = 0.78, 0.96

# 某些敏感词/功效词的安全替换（可按需扩展）
SENSITIVE_MAP = {
    "减脂": "健康餐",
    "减肥": "塑形",
    "抽奖": "福利",
    "丰胸": "改善身材",
    "投资": "理财思路"
}

# 文件路径
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRENDS_PATH = os.path.join(ROOT, "xhs_trends.json")
CANDI_PATH  = os.path.join(ROOT, "candidates.json")

def clamp(x, lo, hi): return max(lo, min(hi, x))

def load_json(path, default):
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return default

def decay_weight(w, days=7, half_life=10):
    """
    按“半衰期”方式衰减：w * 0.5 ** (days/half_life)
    默认每 10 天衰减一半，可按需调整
    """
    factor = 0.5 ** (days / half_life)
    return clamp(round(w * factor, 4), MIN_W - 0.2, 0.99)

def ensure_fields(item):
    # 统一字段，避免缺漏
    item.setdefault("decay_days", 10)
    item.setdefault("priority", 1)
    item.setdefault("sensitive_hint", False)
    # 自动映射敏感替换
    for k, v in SENSITIVE_MAP.items():
        if k in item["keyword"]:
            item["sensitive_hint"] = True
            item["safe_replacement"] = v
    return item

def normalize_keyword(item):
    # 若标注敏感且有安全替换，则替换，否则丢弃（可选策略：这里是替换）
    if item.get("sensitive_hint") and item.get("safe_replacement"):
        item["keyword"] = item["safe_replacement"]
        item["sensitive_hint"] = False
        item.pop("safe_replacement", None)
    return item

def main():
    # 读取 candidates（你每周维护这份）
    candi = load_json(CANDI_PATH, {"items": []})
    candidates = [ensure_fields(x) for x in candi.get("items", [])]

    # 读取旧 trends
    old = load_json(TRENDS_PATH, {"week_of": WEEK_OF, "region": "GLOBAL", "items": []})
    old_items = old.get("items", [])

    # 1) 先对旧词做衰减 & 过滤过期
    kept = []
    for it in old_items:
        it = ensure_fields(it)
        # 若有 expires_at 且已过期，丢弃
        exp = it.get("expires_at")
        if exp:
            try:
                if TODAY > datetime.date.fromisoformat(exp):
                    continue
            except Exception:
                pass
        # 简单地按固定天数衰减：这里设为 7 天
        it["weight"] = decay_weight(it.get("weight", 0.85), days=7, half_life=it.get("decay_days", 10))
        kept.append(it)

    # 2) 补充新词：按类别集合
    # 先把已存在的关键词放入集合，避免重复
    existing = set([x["keyword"] for x in kept])

    # 打散候选，随机性+优先级（priority）加权
    def sort_key(x):
        base = x.get("weight", 0.85)
        pri  = x.get("priority", 1)
        return base + 0.03 * pri + random.uniform(-0.02, 0.02)

    candidates.sort(key=sort_key, reverse=True)

    # 分类分桶
    buckets = defaultdict(list)
    for it in kept:
        buckets[it.get("category", "misc")].append(it)

    # 将候选加入，直至每类达到 MAX_PER_CATEGORY
    for item in candidates:
        kw = item["keyword"]
        cat = item.get("category", "misc")
        if kw in existing:
            continue
        # 规范化字段 & 处理敏感替换
        item = normalize_keyword(ensure_fields(item))
        kw2 = item["keyword"]
        if kw2 in existing:
            continue

        # 初始化权重区间
        w = clamp(item.get("weight", 0.85), MIN_W, MAX_W)
        item["weight"] = round(w, 2)

        if len(buckets[cat]) < MAX_PER_CATEGORY:
            buckets[cat].append(item)
            existing.add(kw2)

    # 3) 重新拼装 items，并在每类内做一次排序（权重 & 优先级）
    new_items = []
    for cat, arr in buckets.items():
        arr.sort(key=lambda x: (x.get("weight", 0.85), x.get("priority", 1)), reverse=True)
        # 保底裁剪
        new_items.extend(arr[:MAX_PER_CATEGORY])

    # 4) 输出文件
    out = {
        "week_of": WEEK_OF,
        "region": old.get("region", "GLOBAL"),
        "items": new_items
    }

    with open(TRENDS_PATH, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(f"Updated {TRENDS_PATH} with {len(new_items)} items on {WEEK_OF}")

if __name__ == "__main__":
    main()
