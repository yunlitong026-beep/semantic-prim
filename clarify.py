# -*- coding: utf-8 -*-
"""人→编码 置信度回询适配器（V1 演示版 / 外层，不改 AI↔AI 底层）。

原理：
- 自然语言描述 → 扫描歧义词表 → 对命中词评估置信度
- 置信度 >= ACCEPT(0.7)：直接接受，不回询
- 置信度 <  ACCEPT：回询，让用户在候选里选，禁止脑补
- 没有候选：无法确定，必须人工补充

仅标准库，可离线跑：
  python clarify.py --detect "黄昏柳树下，剑客看见对方，然后上前拥抱"
  python clarify.py
"""
import json
import re
import sys

ACCEPT = 0.7

# 歧义词表：词 -> [(候选中文, 示例原语码, 可选槽位dict), ...]
# weapon.* / motion 消歧槽位已并入 film.shot 可选槽位（schema.json optional）。
AMBIG = {
    "拥抱": [
        ("普通正面拥抱", "act.hug.front", {"act": "hug.front"}),
        ("公主抱", "act.hug.carry", {"act": "hug.carry"}),
        ("从背后环抱", "act.hug.back", {"act": "hug.back"}),
        ("侧身拥抱", "act.hug.side", {"act": "hug.side"}),
    ],
    "拉": [
        ("拉手", "act.hold.hand", {"act": "hold.hand"}),
        ("拉入怀中", "act.pull.embrace", {"act": "pull.embrace"}),
        ("拽住对方", "act.grab", {"act": "grab"}),
    ],
    "拍": [
        ("拍肩", "act.pat.shoulder", {"act": "pat.shoulder"}),
        ("拍头", "act.pat.head", {"act": "pat.head"}),
        ("拍背", "act.pat.back", {"act": "pat.back"}),
    ],
    "看": [
        ("对视", "act.look.eye", {"act": "look.eye"}),
        ("凝视", "act.look.gaze", {"act": "look.gaze"}),
        ("瞥一眼", "act.look.glance", {"act": "look.glance"}),
    ],
    "御剑": [
        ("手持剑柄挥剑", "weapon.mode.hand",
         {"weapon": "sword", "weapon.holder": "hand", "weapon.drive": "arm", "motion": "hand-swing"}),
        ("剑离体，真气丝牵引、意念操控飞行", "weapon.mode.fly",
         {"weapon": "sword", "weapon.holder": "null", "weapon.drive": "qi-thread", "motion": "fly-guided"}),
    ],
    "离剑式": [
        ("手持剑柄挥剑", "weapon.mode.hand",
         {"weapon": "sword", "weapon.holder": "hand", "weapon.drive": "arm", "motion": "hand-swing"}),
        ("剑离体，真气丝牵引、意念操控飞行", "weapon.mode.fly",
         {"weapon": "sword", "weapon.holder": "null", "weapon.drive": "qi-thread", "motion": "fly-guided"}),
    ],
}

# 命中守卫：避免把复合词误拆成歧义词。
# 例：不要从「看见」里误报「看」；不要把镜头运动「拉至远景」误报成手部动作「拉」。
GUARD = {
    "看": {"not_followed_by": "见到"},
    "拉": {"not_followed_by": "至"},
}


def confidence(candidates):
    """简单先验：候选越多越不确定。"""
    if not candidates:
        return 0.0
    return round(1.0 / len(candidates), 2)


def _hit(text, word):
    """是否命中歧义词（带守卫，避免复合词误拆）。"""
    guard = GUARD.get(word, {})
    if "not_followed_by" in guard:
        return re.search(word + r'(?![' + guard["not_followed_by"] + r'])', text) is not None
    return word in text


def detect(text):
    """返回文本中命中的歧义词及候选、置信度。"""
    found = []
    for word, cands in AMBIG.items():
        if _hit(text, word):
            found.append({
                "word": word,
                "candidates": [c[0] for c in cands],
                "codes": [c[1] for c in cands],
                "confidence": confidence(cands),
            })
    return found


def resolve(text, picks):
    """应用用户选择，返回消歧结果。

    picks: {词: 0-based 序号 或 候选中文}
    """
    result = {"text": text, "resolved": {}, "unresolved": [], "slots": {}}
    for word, cands in AMBIG.items():
        if not _hit(text, word):
            continue
        pick = picks.get(word)
        idx = None
        if isinstance(pick, int) and 0 <= pick < len(cands):
            idx = pick
        elif isinstance(pick, str):
            for j, c in enumerate(cands):
                if c[0] == pick:
                    idx = j
                    break
        if idx is not None:
            entry = cands[idx]
            meaning, code = entry[0], entry[1]
            slots = entry[2] if len(entry) >= 3 else None
            resolved = {"meaning": meaning, "code": code, "confidence": 1.0}
            if slots:
                resolved["slots"] = slots
                result["slots"].update(slots)
            result["resolved"][word] = resolved
        else:
            result["unresolved"].append({
                "word": word,
                "candidates": [c[0] for c in cands],
                "reason": "未选择" if pick is None else "选择不在候选中",
            })
    return result


def needs_clarify(text):
    """是否含低置信度歧义（需要回询）。"""
    return any(x["confidence"] < ACCEPT for x in detect(text))


def run_cli():
    text = input("输入镜头/动作描述：").strip()
    items = detect(text)
    if not items:
        print("未命中歧义词，直接接受（演示版）。")
        return
    picks = {}
    print("\n发现 %d 处歧义，逐个确认：\n" % len(items))
    for i, item in enumerate(items, 1):
        print("[%d] 「%s」 置信度 %.2f（<%.2f，需要回询）"
              % (i, item["word"], item["confidence"], ACCEPT))
        for j, c in enumerate(item["candidates"], 1):
            print("    %d. %s  (%s)" % (j, c, item["codes"][j - 1]))
        while True:
            ans = input("请选序号（回车=留空）：").strip()
            if ans == "":
                picks[item["word"]] = None
                break
            if ans.isdigit() and 1 <= int(ans) <= len(item["candidates"]):
                picks[item["word"]] = int(ans) - 1
                break
            print("输入无效，重试。")
    print("\n消歧结果：")
    print(json.dumps(resolve(text, picks), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--detect":
        t = sys.argv[2] if len(sys.argv) > 2 else input("输入描述：")
        print(json.dumps(detect(t), ensure_ascii=False, indent=2))
    else:
        run_cli()
