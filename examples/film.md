# 影视领域示例（film.shot@1）

## 1. 清晨红衣女子缓慢推至特写

人话：清晨，红衣女子在古寺长廊，缓慢推至特写，自然光，2 秒，接续。

```
film.shot@1 { T:T01, P:P01, ID:I01[红], CAM:C1, SIZE:S4, Q:慢, LIT:[L0], DUR:2s, SEQ:接续 }
```

## 2. 黄昏男子拉至全景

```
film.shot@1 { T:T02, P:P02, ID:I02, CAM:C2, SIZE:S1, Q:慢, LIT:[L2], DUR:3s, SEQ:独立 }
```

## 3. 环绕老人暗调大特写

```
film.shot@1 { T:T04, P:P04, ID:I04, CAM:C8, SIZE:S5, Q:快, LIT:[L9], DUR:4s, SEQ:闪回 }
```

> 取值表见 `schema.json`；解析/校验见 `parser.py`。
