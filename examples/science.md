# 科研领域示例（草案，取值表待补）

> 说明：本域仅作跨领域"领域包"思路演示，`schema.json` 尚未收录，`parser.py` 暂不可校验。

设想领域 `sci.param@1`：

- TEMP 温度 / VOLT 电压 / AMP 电流 / COUNT 放电次数 / POINT 采样点

示例编码（草案）：

```
sci.param@1 { TEMP:820, VOLT:35, AMP:12, COUNT:7, POINT:0 }
```

对应：温度 820，电压 35，电流 12，放电 7 次，采样点 0。
