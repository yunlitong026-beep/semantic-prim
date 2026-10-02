# 招牌案例：御剑 / 离剑式（离体飞剑）

## 痛点

自然语言提示词写「男一号施展御剑 / 独孤九剑离剑式：手不握剑，真气丝线牵引长剑悬空，随意念变换轨迹攻击」。

普通视频生成 AI 读这段文字，靠自由脑补，优先匹配训练里最常见的剑斗画面——**人握剑劈砍，当当当像打铁**。因为它不理解「离剑式」的核心边界：**剑不在手里**。

这就是"十抽九不中"的来源：自然语言模糊，AI 用最熟悉的画面兜底。

## 本体系怎么解决

歧义在**人→编码这一步就确认**，编码把「是否握剑」写死进 `film.shot` 的 weapon 槽位（weapon / weapon.holder / weapon.drive / motion），AI 之间传确定参数，不靠阅读理解猜画面。

## 运行

```bash
# 检测歧义
python clarify.py --detect "黄昏柳树下，两名剑客对决，男一号施展御剑，手不握剑，真气丝线牵引长剑悬空"

# 正向解析（人话→编码）+ 回询（选"剑离体"=序号1，并补 ID/DUR）
python text2code.py --clarify "黄昏柳树下，男一号施展御剑，手不握剑，真气丝线牵引长剑悬空"

# 闭环测试
python tests/crosscheck.py
python demo/roundtrip.py
```

## 完整流程

**Step 1 — 检测歧义（clarify.detect）：**

```json
[
  {
    "word": "御剑",
    "candidates": ["手持剑柄挥剑", "剑离体，真气丝牵引、意念操控飞行"],
    "codes": ["weapon.mode.hand", "weapon.mode.fly"],
    "confidence": 0.5
  }
]
```

「御剑」置信度 0.5 < 0.7 → 回询。

**Step 2 — 回询，用户选"剑离体"：**

> 【语义确认】"御剑" 有两种表现形式，请选择：
> 1. 手持剑柄挥剑
> 2. 剑离体，真气丝牵引、意念操控飞行

**Step 3 — text2code 把消歧槽位填进 film.shot 编码：**

消歧结果（clarify.resolve）输出对齐 schema 的槽位：

```json
{
  "resolved": {
    "御剑": {
      "meaning": "剑离体，真气丝牵引、意念操控飞行",
      "code": "weapon.mode.fly",
      "confidence": 1.0,
      "slots": { "weapon": "sword", "weapon.holder": "null", "weapon.drive": "qi-thread", "motion": "fly-guided" }
    }
  }
}
```

`text2code.text2code` 把这些 slots 并入 film.shot 编码：

```text
film.shot@1 { T:T02, P:P00, CAM:C0, SIZE:S00, Q:常速, LIT:[L0], SEQ:独立, ID:I02, DUR:3s, weapon:sword, weapon.holder:null, weapon.drive:qi-thread, motion:fly-guided }
```

**Step 4 — 渲染读到武器约束（render）：**

> 黄昏，男子在未指定场景，固定机位未指定景别，自然光，3s，独立镜头（御剑：剑离体、真气丝牵引、意念操控飞行）

## 关键差异

- `weapon.holder = null`：**人物不握剑**，硬性约束，渲染端不会再画成手持劈砍
- `weapon.drive = qi-thread`：真气丝牵引
- `motion = fly-guided`：意念引导飞行

渲染 Agent 读到的是结构化槽位，不是一段模糊文字；「打铁式挥剑」这个错误画面在编码层就被排除。

## 闭环验证

`tests/crosscheck.py` 的 `weapon_closed_loop` 验证全链路：
1. 消歧结果落地进 slots（weapon.holder / weapon.drive / motion 断言）
2. 编码过 parser.validate（schema 合法性）
3. render 输出含「剑离体 / 真气丝牵引 / 意念引导飞行」（下游可读）

V1 之前的断链（消歧产物落不了地）已修复：weapon 槽位正式并入 `film.shot` schema 的 optional 槽位，不再游离于外层命名空间。
