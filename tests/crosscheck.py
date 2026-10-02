# -*- coding: utf-8 -*-
"""交叉验证：反向（编码->人话）确定性检查 + 正向（候选编码 vs 参考编码）比对。"""
import json
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

import parser  # noqa: E402
import text2code  # noqa: E402
from demo import roundtrip as rt  # noqa: E402


def load_samples(path):
    with open(path, encoding='utf-8') as f:
        return json.load(f)['samples']


def reverse_check(samples, schema):
    print('反向检查（编码 -> 人话，确定性/骨架一致）\n')
    ok = 0
    for s in samples:
        obj = parser.parse(s['ref'])
        errs = parser.validate(obj, schema)
        if errs:
            print('[%d] 校验失败: %s' % (s['id'], errs))
            continue
        text = rt.render(obj)
        text2 = rt.render(parser.parse(parser.dump(obj)))
        stable = (text == text2)
        if stable:
            ok += 1
        print('[%d] %s' % (s['id'], text))
        print('    稳定: %s' % ('OK' if stable else 'FAIL'))
    print('\n%d/%d 反向通过' % (ok, len(samples)))


def forward_check(samples):
    print('\n正向解析（人话 -> 编码，逐槽与参考编码比对）\n')
    ok = 0
    for s in samples:
        res = text2code.text2code(s['text'])
        if res['needs_clarify']:
            print('[%d] 需要回询: %s' % (s['id'], [x['word'] for x in res['needs_clarify']]))
            continue
        if res['missing']:
            print('[%d] 缺少语义必填: %s' % (s['id'], res['missing']))
            continue
        cand = res['obj']['slots']
        ref = parser.parse(s['ref'])['slots']
        if cand == ref:
            ok += 1
            print('[%d] 一致' % s['id'])
        else:
            print('[%d] 不一致' % s['id'])
            for k in ref:
                if cand.get(k) != ref[k]:
                    print('    槽位 %s: 参考 %r / 候选 %r' % (k, ref[k], cand.get(k)))
    print('\n%d/%d 正向解析一致' % (ok, len(samples)))


def weapon_closed_loop(schema):
    print('\n御剑消歧落地（消歧 slots -> film.shot 编码，校验通过即闭环）\n')
    text = '黄昏柳树下，男一号施展御剑，手不握剑，真气丝线牵引长剑悬空'
    res = text2code.text2code(text, picks={'御剑': 1}, overrides={'ID': 'I02', 'DUR': '3s'})
    obj = res['obj']
    errs = parser.validate(obj, schema)
    holder = obj['slots'].get('weapon.holder')
    ok = (not errs) and holder == 'null'
    print(res['encoding'])
    print('weapon.holder =', holder)
    print('校验:', '通过' if not errs else errs)
    print('闭环:', 'OK（御剑离体约束已进入渲染编码）' if ok else 'FAIL')


def compare(candidates, samples):
    print('\n正向比对（候选编码 vs 参考编码）\n')
    agree = 0
    total = 0
    for s in samples:
        ref = parser.parse(s['ref'])['slots']
        cand = candidates.get(str(s['id']))
        total += 1
        if not cand:
            print('[%d] 无候选' % s['id'])
            continue
        try:
            c = parser.parse(cand)['slots']
        except Exception as e:
            print('[%d] 解析失败: %s' % (s['id'], e))
            continue
        same = (c == ref)
        if same:
            agree += 1
            print('[%d] 一致' % s['id'])
        else:
            print('[%d] 不一致' % s['id'])
            for k in ref:
                if c.get(k) != ref[k]:
                    print('    槽位 %s: 参考 %r / 候选 %r' % (k, ref[k], c.get(k)))
    print('\n%d/%d 正向一致' % (agree, total))


if __name__ == '__main__':
    schema = parser.load_schema()
    base = os.path.dirname(os.path.abspath(__file__))
    samples = load_samples(os.path.join(base, 'samples.json'))
    reverse_check(samples, schema)
    forward_check(samples)
    weapon_closed_loop(schema)
    if len(sys.argv) > 1:
        with open(sys.argv[1], encoding='utf-8') as f:
            candidates = json.load(f)
        compare(candidates, samples)
