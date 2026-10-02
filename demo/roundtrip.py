# -*- coding: utf-8 -*-
"""编码结构稳定性 Demo：编码 -> 人话 -> 编码，确定性还原。仅演示，不依赖外部模型。

说明：这里验证的是「编码结构互转稳定」，不是「人话 -> 编码」的完整双向翻译。
人话 -> 编码的正向解析见 text2code.py，真往返比对见 tests/crosscheck.py。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import parser  # noqa: E402

T_MAP = {'T00': '未指定时刻', 'T01': '清晨', 'T02': '黄昏', 'T03': '正午', 'T04': '夜'}
P_MAP = {'P00': '未指定场景', 'P01': '古寺长廊', 'P02': '街市', 'P03': '室内', 'P04': '荒野'}
ID_MAP = {'I01': '女子', 'I02': '男子', 'I03': '孩童', 'I04': '老人'}
ATTR_MAP = {'红': '红衣', '白': '白衣', '黑': '黑衣'}
CAM_MAP = {'C0': '静止', 'C1': '推', 'C2': '拉', 'C3': '摇', 'C4': '移', 'C5': '跟',
           'C6': '升', 'C7': '降', 'C8': '环绕', 'C9': '手持'}
SIZE_MAP = {'S00': '未指定景别', 'S0': '远景', 'S1': '全景', 'S2': '中景', 'S3': '近景', 'S4': '特写', 'S5': '大特写'}
LIT_MAP = {'L0': '自然光', 'L1': '顺光', 'L2': '侧光', 'L3': '逆光', 'L4': '顶光',
           'L5': '底光', 'L6': '柔光', 'L7': '硬光', 'L8': '丁达尔', 'L9': '暗调'}
Q_MAP = {'停': '静止', '慢': '缓慢', '常速': '常速', '快': '快速', '急': '急促'}
SEQ_MAP = {'独立': '独立镜头', '接续': '接上一镜', '平行': '与上一镜平行', '闪回': '闪回', '闪前': '闪前'}
ACT_MAP = {'hug.front': '正面拥抱', 'hug.carry': '公主抱', 'hug.back': '背后环抱', 'hug.side': '侧身拥抱',
           'hold.hand': '拉手', 'pull.embrace': '拉入怀中', 'grab': '拽住对方',
           'pat.shoulder': '拍肩', 'pat.head': '拍头', 'pat.back': '拍背',
           'look.eye': '对视', 'look.gaze': '凝视', 'look.glance': '瞥一眼'}


def render(obj):
    s = obj['slots']
    t = T_MAP[s['T']]
    p = P_MAP[s['P']]
    idv = s['ID']
    if isinstance(idv, dict):
        base = ID_MAP.get(idv['value'], idv['value'])
        attr = idv.get('attr')
    else:
        base = ID_MAP.get(idv, idv)
        attr = None
    subject = (ATTR_MAP.get(attr, attr) + base) if attr else base
    size = SIZE_MAP[s['SIZE']]
    if s['CAM'] == 'C0':
        action = '固定机位%s' % size
    else:
        action = '%s%s至%s' % (Q_MAP[s['Q']], CAM_MAP[s['CAM']], size)
    lit = '、'.join(LIT_MAP[x] for x in s['LIT'])
    base = '%s，%s在%s，%s，%s，%s，%s' % (t, subject, p, action, lit, s['DUR'], SEQ_MAP[s['SEQ']])
    # 武器槽位（可选，缺省=无武器，不渲染）
    extra = []
    if s.get('weapon.holder') == 'null' and s.get('motion') == 'fly-guided':
        extra.append('御剑：剑离体、真气丝牵引、意念操控飞行')
    elif s.get('weapon') == 'sword':
        extra.append('持剑')
    act = s.get('act')
    if act:
        extra.append('动作：%s' % ACT_MAP.get(act, act))
    if extra:
        base += '（' + '；'.join(extra) + '）'
    return base


ENCODINGS = [
    'film.shot@1 { T:T01, P:P01, ID:I01[红], CAM:C1, SIZE:S4, Q:慢, LIT:[L0], DUR:2s, SEQ:接续 }',
    'film.shot@1 { T:T02, P:P02, ID:I02, CAM:C2, SIZE:S1, Q:慢, LIT:[L2], DUR:3s, SEQ:独立 }',
    'film.shot@1 { T:T03, P:P03, ID:I03, CAM:C3, SIZE:S2, Q:常速, LIT:[L4], DUR:5s, SEQ:接续 }',
    'film.shot@1 { T:T04, P:P04, ID:I04, CAM:C8, SIZE:S5, Q:快, LIT:[L9], DUR:4s, SEQ:闪回 }',
    'film.shot@1 { T:T01, P:P03, ID:I01[白], CAM:C4, SIZE:S3, Q:常速, LIT:[L6], DUR:6s, SEQ:平行 }',
    'film.shot@1 { T:T02, P:P01, ID:I02, CAM:C6, SIZE:S0, Q:慢, LIT:[L0,L8], DUR:8s, SEQ:独立 }',
    'film.shot@1 { T:T03, P:P02, ID:I03[黑], CAM:C5, SIZE:S2, Q:快, LIT:[L3], DUR:3s, SEQ:接续 }',
    'film.shot@1 { T:T04, P:P04, ID:I04, CAM:C9, SIZE:S3, Q:急, LIT:[L7], DUR:2s, SEQ:平行 }',
    'film.shot@1 { T:T01, P:P02, ID:I01, CAM:C7, SIZE:S1, Q:常速, LIT:[L1], DUR:4s, SEQ:闪前 }',
    'film.shot@1 { T:T02, P:P04, ID:I02[红], CAM:C0, SIZE:S4, Q:停, LIT:[L5], DUR:1s, SEQ:独立 }',
    # 招牌案例：御剑离剑式（weapon 槽位闭环）
    'film.shot@1 { T:T02, P:P04, ID:I02, CAM:C5, SIZE:S2, Q:慢, LIT:[L0,L8], DUR:6s, SEQ:独立, weapon:sword, weapon.holder:null, weapon.drive:qi-thread, motion:fly-guided }',
]


def main():
    schema = parser.load_schema()
    print('编码结构稳定性演示（编码 -> 人话 -> 编码）\n')
    ok = 0
    for i, enc in enumerate(ENCODINGS, 1):
        obj = parser.parse(enc)
        errs = parser.validate(obj, schema)
        if errs:
            print('[%d] 校验失败: %s' % (i, errs))
            continue
        text = render(obj)
        enc2 = parser.dump(parser.parse(enc))
        text2 = render(parser.parse(enc2))
        stable = (enc2 == enc) and (text2 == text)
        if stable:
            ok += 1
        mark = 'OK' if stable else 'FAIL'
        print('[%d] %s' % (i, text))
        print('    %s' % enc)
        print('    -> %s  [%s]' % (text2, mark))
        print()
    print('%d/%d 条全部确定性还原（编码结构稳定）。' % (ok, len(ENCODINGS)))


if __name__ == '__main__':
    main()
