# V1 验证测试报告

## 结论

V1 最小原型跑通：编码 ↔ 人话互转确定性稳定，往返零漂移；御剑 / 离剑式在人机入口完成消歧，输出 `weapon.holder=null`，不会被误解析成手持挥剑。

## 1. 往返零漂移（编码 → 人话 → 编码）

- 方法：`python demo/roundtrip.py`
- 结果：**10/10 条全部确定性还原，零漂移。**

## 2. 反向检查（编码 → 人话，骨架一致）

- 方法：`python tests/crosscheck.py`
- 结果：**10/10 反向通过。**

## 3. 御剑歧义检测（人 → 编码）

- 方法：`python clarify.py --detect "黄昏柳树下，两名剑客对决，男一号施展御剑，手不握剑，真气丝线牵引长剑悬空"`
- 结果：命中「御剑」，置信度 **0.5 < 0.7**，触发回询。

## 4. 御剑消歧（用户选「剑离体」）

- 结果：
  - `weapon.holder = null`（人物不握剑）
  - `weapon.drive = qi-thread`（真气丝牵引）
  - `motion = fly-guided`（意念引导飞行）

## 边界说明

- 人 → 编码链路 V1 采用回询确认路径（`clarify.py` 的 detect / resolve），尚未实现自然语言自动填槽器，这是 V1 既定边界。
- `weapon.*` / `motion` 是外层动作消歧的示意命名空间，未并入 `film.shot` 相机 schema；AI↔AI 底层规范（spec / schema / parser）不受影响。
