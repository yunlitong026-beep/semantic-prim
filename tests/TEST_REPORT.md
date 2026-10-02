# V1 验证测试报告

## 结论

V1 原型已从「半链路」补成「真闭环」：
- 编码 ↔ 人话互转稳定（编码结构确定性）
- 新增人话 → 编码正向解析器 `text2code.py`，10/10 样本与参考编码逐槽一致
- 御剑 / 离剑式消歧结果（`weapon.holder=null` 等）已并入 `film.shot` 可选槽位，校验通过，真正落地到渲染编码

## 1. 编码结构稳定性（编码 → 人话 → 编码）

- 方法：`python demo/roundtrip.py`
- 结果：**11/11 条确定性还原**（含御剑 weapon 槽位样例）。
- 说明：本项验证「编码结构互转稳定」，不是「人话 → 编码」的完整双向翻译；真往返见第 2 项。

## 2. 正向解析（人话 → 编码）

- 方法：`python tests/crosscheck.py`（forward_check，走 `text2code.py`）
- 结果：**10/10 样本与参考编码逐槽一致**。

## 3. 反向检查（编码 → 人话，骨架一致）

- 方法：`python tests/crosscheck.py`（reverse_check）
- 结果：**10/10 反向通过**。

## 4. 御剑歧义检测（人 → 编码）

- 方法：`python clarify.py --detect "黄昏柳树下，两名剑客对决，男一号施展御剑，手不握剑，真气丝线牵引长剑悬空"`
- 结果：命中「御剑」，置信度 **0.5 < 0.7**，触发回询。

## 5. 御剑消歧落地（闭环）

- 方法：`python text2code.py --clarify "...御剑..."`（选「剑离体」，补 ID/DUR）
- 结果：
  - `weapon.holder = null`（人物不握剑）
  - `weapon.drive = qi-thread`（真气丝牵引）
  - `motion = fly-guided`（意念引导飞行）
  - 校验：**通过**（weapon.* / motion 已并入 film.shot 可选槽位）

## 边界说明

- 人 → 编码链路 V1 采用规则模板 + 回询确认（`text2code.py` 复用 `clarify.py` 的 detect / resolve）。
- 语义必填槽位 ID / DUR 无法用默认值兜底，缺失时返回 `missing`，禁止脑补。
- `act.*`（拥抱 / 拉 / 拍 / 看等外层动作消歧）仍为示意命名空间，未并入 film.shot 相机 schema；`weapon.*` / `motion` 已并入。
