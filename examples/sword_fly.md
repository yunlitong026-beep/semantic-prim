# 招牌案例：御剑 / 离剑式（离体飞剑）

## 痛点

自然语言提示词写「男一号施展御剑 / 独孤九剑离剑式：手不握剑，真气丝线牵引长剑悬空，随意念变换轨迹攻击」。

普通视频生成 AI 读这段文字，靠自由脑补，优先匹配训练里最常见的剑斗画面——**人握剑劈砍，当当当像打铁**。因为它不理解「离剑式」的核心边界：**剑不在手里**。

这就是“十抽九不中”的来源：自然语言模糊，AI 用最熟悉的画面兜底。

## 本体系怎么解决

歧义在**人→编码这一步就确认**，编码把「是否握剑」写死，AI 之间传确定参数，不靠阅读理解猜画面。

## 运行

```bash
# 检测歧义
python clarify.py --detect "黄昏柳树下，两名剑客对决，男一号施展御剑，手不握剑，真气丝线牵引长剑悬空"

# 交互式确认
python clarify.py
```

## 完整流程

**检测结果（detect）：**

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

**AI 提问：**

> 【语义确认】“御剑” 有两种表现形式，请选择：
> 1. 手持剑柄挥剑
> 2. 剑离体，真气丝牵引、意念操控飞行

**用户选 2 → 消歧结果（resolve）：**

```json
{
  "resolved": {
    "御剑": {
      "meaning": "剑离体，真气丝牵引、意念操控飞行",
      "code": "weapon.mode.fly",
      "confidence": 1.0,
      "slots": {
        "weapon": "sword",
        "weapon.holder": "null",
        "weapon.drive": "qi-thread",
        "motion": "fly-guided"
      }
    }
  },
  "slots": {
    "weapon": "sword",
    "weapon.holder": "null",
    "weapon.drive": "qi-thread",
    "motion": "fly-guided"
  }
}
```

## 关键差异

- `weapon.holder = null`：**人物不握剑**，硬性约束，渲染端不会再画成手持劈砍
- `weapon.drive = qi-thread`：真气丝牵引
- `motion = fly-guided`：意念引导飞行

渲染 Agent 读到的是结构化槽位，不是一段模糊文字；「打铁式挥剑」这个错误画面在编码层就被排除。

## 边界

- `weapon.*` / `motion` 是外层动作消歧的示意命名空间，未并入 `film.shot` 相机 schema；AI↔AI 底层规范（spec / schema / parser）不受影响。
- 本案例是 V1 演示版，展示“歧义在人机入口确认 → 结构化编码”的价值闭环。
