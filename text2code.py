# -*- coding: utf-8 -*-
"""人话 -> 编码 正向解析器（V1 规则模板版）。

职责：把一条短剧镜头自然语言描述，解析成 `film.shot@1` 结构化编码。

设计要点：
- 规则模板抽取，不依赖外部模型：时刻 / 场景 / 主体 / 镜头运动 / 景别 / 速度 / 光影 / 时长 / 时序。
- 复用 clarify.py 的歧义检测：遇到低置信度歧义词（如「御剑」「离剑式」），
  若未提供用户选择，先返回「需要回询」，禁止私自脑补。
- 用户确认后，把消歧结果（weapon / weapon.holder / weapon.drive / motion）
  合并进 film.shot 编码，让渲染端拿到「剑不在手里」这类硬约束。

仅标准库，可离线运行：
  python text2code.py "黄昏，男子在荒野，缓慢推至全景，侧光，5秒，独立镜头"
  python text2code.py --clarify "黄昏柳树下，男一号施展御剑，手不握剑，真气丝线牵引长剑悬空"
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import clarify  # noqa: E402
import parser   # noqa: E402

DOMAIN = 'film.shot'
VERSION = 1

# 抽取映射表（中文 -> 编码值）
T_MAP = [('清晨', 'T01'), ('黄昏', 'T02'), ('正午', 'T03'), ('夜', 'T04')]
P_MAP = [('古寺长廊', 'P01'), ('街市', 'P02'), ('室内', 'P03'), ('荒野', 'P04')]
ENTITY_MAP = [('女子', 'I01'), ('男子', 'I02'), ('孩童', 'I03'), ('老人', 'I04')]
SPEED_MAP = {'缓慢': '慢', '快速': '快', '急促': '急', '常速': '常速'}
CAM_MAP = {'固定': 'C0', '推': 'C1', '拉': 'C2', '摇': 'C3', '移': 'C4', '跟': 'C5',
           '升': 'C6', '降': 'C7', '环绕': 'C8', '手持': 'C9'}
SIZE_MAP = {'大特写': 'S5', '特写': 'S4', '近景': 'S3', '中景': 'S2', '全景': 'S1', '远景': 'S0'}
LIT_MAP = [('自然光', 'L0'), ('顺光', 'L1'), ('侧光', 'L2'), ('逆光', 'L3'), ('顶光', 'L4'),
           ('底光', 'L5'), ('柔光', 'L6'), ('硬光', 'L7'), ('丁达尔', 'L8'), ('暗调', 'L9')]
SEQ_MAP = [('闪回', '闪回'), ('闪前', '闪前'), ('平行', '平行'), ('接', '接续'), ('独立', '独立')]

# 缺省值：人话没提到就填「自然默认」或「未指定」哨兵，禁止臆造具体语义
DEFAULTS = {
    'T': 'T00', 'P': 'P00', 'CAM': 'C0', 'SIZE': 'S00',
    'Q': '常速', 'LIT': ['L0'], 'SEQ': '独立',
}

# 语义必填：无法用默认值兜底，缺了必须回询（不能脑补）
REQUIRED = {'ID', 'DUR'}

ACTION_RE = re.compile(
    r'(?P<speed>缓慢|快速|急促|常速)?(?P<cam>推|拉|摇|移|跟|升|降|环绕|手持)至'
    r'(?P<size>大特写|特写|近景|中景|全景|远景)'
)
FIXED_RE = re.compile(r'固定机位(?P<size>大特写|特写|近景|中景|全景|远景)')
DUR_RE = re.compile(r'(\d+)\s*秒')


def _first(pairs, text):
    """按顺序返回第一个命中的编码值，未命中返回 None。"""
    for word, code in pairs:
        if word in text:
            return code
    return None


def _color(text):
    """抽取主体颜色属性：优先匹配「红衣 / 白衣 / 黑衣」，再匹配紧贴主体的裸色。"""
    m = re.search(r'(红衣|白衣|黑衣)', text)
    if m:
        return m.group(1)[0]
    m = re.search(r'(红|白|黑)(?=(女子|男子|孩童|老人))', text)
    if m:
        return m.group(1)
    return None


def extract(text):
    """抽取确定性槽位，返回 slots dict（缺的槽位不填，交给 DEFAULTS / 回询）。"""
    slots = {}
    t = _first(T_MAP, text)
    if t:
        slots['T'] = t
    p = _first(P_MAP, text)
    if p:
        slots['P'] = p

    # 主体 + 颜色属性
    entity = _first(ENTITY_MAP, text)
    if entity:
        color = _color(text)
        slots['ID'] = {'value': entity, 'attr': color} if color else entity

    # 镜头运动 + 景别 + 速度
    fm = FIXED_RE.search(text)
    am = ACTION_RE.search(text)
    if fm:
        slots['CAM'] = 'C0'
        slots['SIZE'] = SIZE_MAP[fm.group('size')]
        slots['Q'] = '停'
    elif am:
        slots['CAM'] = CAM_MAP[am.group('cam')]
        slots['SIZE'] = SIZE_MAP[am.group('size')]
        speed = am.group('speed')
        slots['Q'] = SPEED_MAP[speed] if speed else '常速'

    # 光影（可多个）
    lits = [code for word, code in LIT_MAP if word in text]
    if lits:
        slots['LIT'] = lits

    # 时长
    dm = DUR_RE.search(text)
    if dm:
        slots['DUR'] = '%ss' % dm.group(1)

    # 时序
    seq = _first(SEQ_MAP, text)
    if seq:
        slots['SEQ'] = seq
    return slots


def text2code(text, picks=None, overrides=None):
    """人话 -> film.shot 编码对象。

    picks: 消歧选择，形如 {"御剑": 1}（0-based 序号）或
           {"御剑": "剑离体，真气丝牵引、意念操控飞行"}
    overrides: 用户补充的槽位覆盖，形如 {"ID": "I02", "DUR": "3s"}
    """
    slots = extract(text)
    for k, v in DEFAULTS.items():
        slots.setdefault(k, v)
    if overrides:
        slots.update(overrides)

    found = clarify.detect(text)
    need = [x for x in found if x['confidence'] < clarify.ACCEPT]
    unresolved = []
    if need and picks:
        resolved = clarify.resolve(text, picks)
        slots.update(resolved['slots'])
        unresolved = resolved['unresolved']

    missing = [k for k in REQUIRED if k not in slots]
    obj = {'domain': DOMAIN, 'version': VERSION, 'slots': slots}
    return {
        'obj': obj,
        'encoding': parser.dump(obj),
        'needs_clarify': need,
        'unresolved': unresolved,
        'missing': missing,
    }


def main():
    args = sys.argv[1:]
    if not args:
        print('用法: python text2code.py <镜头描述>  或  python text2code.py --clarify <含歧义描述>')
        sys.exit(1)
    schema = parser.load_schema()
    if args[0] == '--clarify':
        text = args[1]
        res = text2code(text)
        print('歧义项（需回询）：')
        print(json.dumps(res['needs_clarify'], ensure_ascii=False, indent=2))
        print('\n回询后（选「剑离体」picks={"御剑":1}，并补 ID/DUR）：')
        res2 = text2code(text, picks={'御剑': 1}, overrides={'ID': 'I02', 'DUR': '3s'})
        print(res2['encoding'])
        errs = parser.validate(res2['obj'], schema)
        print('校验:', '通过' if not errs else errs)
    else:
        text = args[0]
        res = text2code(text)
        print(res['encoding'])
        errs = parser.validate(res['obj'], schema)
        print('校验:', '通过' if not errs else errs)
        if res['missing']:
            print('缺语义必填:', res['missing'])


if __name__ == '__main__':
    main()
