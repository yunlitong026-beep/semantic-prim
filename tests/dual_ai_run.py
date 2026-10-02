# -*- coding: utf-8 -*-
"""双 AI 对测 —— V1 规则版基线（本地模拟）。

说明：
- V1 的「双 AI」是同一套 text2code 规则版跑一遍，因此「双AI一致性(指标③)」无意义，
  本脚本只验证 ①②④：
    ① 编码合法性：过 parser.validate 且不缺必填
    ② 还原保真度：render(编码) 保留原文关键语义的比例
    ④ 歧义定位率：clarify 捕获到的歧义词 / 标注歧义词总数
- 目标不是打分，是定位「规则版还覆盖不了的槽位 / 歧义」，给 V2（接真 LLM）当基线。

用法：python tests/dual_ai_run.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'demo'))

import clarify  # noqa: E402
import parser  # noqa: E402
import text2code  # noqa: E402
from roundtrip import render  # noqa: E402

SCHEMA = parser.load_schema()


def load_cases():
    path = os.path.join(HERE, 'dual_ai_corpus.json')
    with open(path, encoding='utf-8') as f:
        return json.load(f)['cases']


def fidelity(rendered, keywords):
    if not keywords:
        return 1.0, []
    hit = [k for k in keywords if k in rendered]
    miss = [k for k in keywords if k not in rendered]
    return len(hit) / len(keywords), miss


def run_case(case):
    text = case['text']
    res = text2code.text2code(text, picks=case.get('picks'), overrides=case.get('overrides'))
    obj = res['obj']
    errs = parser.validate(obj, SCHEMA)
    missing = res['missing']
    valid = (not errs)

    rendered = None
    f = None
    miss_kw = []
    if not missing:
        rendered = render(obj)
        f, miss_kw = fidelity(rendered, case.get('keywords', []))

    amb = case.get('ambiguous', [])
    found = {x['word'] for x in clarify.detect(text)}
    hit_amb = [w for w in amb if w in found]
    miss_amb = [w for w in amb if w not in found]
    d = len(hit_amb) / len(amb) if amb else None

    return {
        'id': case['id'], 'valid': valid, 'missing': missing,
        'fidelity': f, 'miss_kw': miss_kw,
        'detection': d, 'miss_amb': miss_amb,
        'encoding': res['encoding'],
    }


def color(r):
    if r['missing']:
        return 'red'  # 缺必填，无法形成完整编码
    f, d = r['fidelity'], r['detection']
    if (f is not None and f < 0.4) or (d is not None and d < 0.4):
        return 'red'
    if (f is not None and f < 0.8) or (d is not None and d < 0.8):
        return 'yellow'
    return 'green'


ICON = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}


def main():
    cases = load_cases()
    results = [run_case(c) for c in cases]

    print('双 AI 对测 —— V1 规则版基线（指标③在 V1 无意义，只跑 ①②④）\n')
    header = '%-4s %-8s %-7s %-7s %-5s  %s' % ('ID', '①合法', '②保真', '④歧义', '颜色', '原文')
    print(header)
    print('-' * 96)
    for r, c in zip(results, cases):
        v = 'OK' if (r['valid'] and not r['missing']) else ('缺%s' % '/'.join(r['missing']) if r['missing'] else 'FAIL')
        f = '%.2f' % r['fidelity'] if r['fidelity'] is not None else '-'
        d = '%.2f' % r['detection'] if r['detection'] is not None else '-'
        print('%-4s %-8s %-7s %-7s %-5s  %s' % (r['id'], v, f, d, ICON[color(r)], c['text']))

    # 汇总
    n = len(results)
    green = sum(1 for r in results if color(r) == 'green')
    yellow = sum(1 for r in results if color(r) == 'yellow')
    red = sum(1 for r in results if color(r) == 'red')
    fs = [r['fidelity'] for r in results if r['fidelity'] is not None]
    ds = [r['detection'] for r in results if r['detection'] is not None]
    print('\n汇总：%d 条 | 🟢%d  🟡%d  🔴%d' % (n, green, yellow, red))
    print('平均保真度②: %.2f (%d条可渲染)' % ((sum(fs) / len(fs)) if fs else 0.0, len(fs)))
    print('平均歧义定位率④: %.2f (%d条含歧义)' % ((sum(ds) / len(ds)) if ds else 0.0, len(ds)))

    # 缺口报告
    print('\n缺口报告（规则版还覆盖不了的地方，V2 接 LLM 时优先补）')
    miss_req = [(r['id'], r['missing']) for r in results if r['missing']]
    if miss_req:
        print('1) 缺语义必填（ID/DUR 无法从人话抽取）：')
        for i, m in miss_req:
            print('   案例 %d 缺 %s' % (i, '/'.join(m)))
    miss_kw = [(r['id'], r['miss_kw']) for r in results if r['miss_kw']]
    if miss_kw:
        print('2) 保真度丢失关键词（抽取词表外/句式未覆盖）：')
        for i, kw in miss_kw:
            print('   案例 %d 丢失 %s' % (i, '/'.join(kw)))
    miss_amb = [(r['id'], r['miss_amb']) for r in results if r['miss_amb']]
    if miss_amb:
        print('3) 歧义漏检（clarify 词表未覆盖）：')
        for i, w in miss_amb:
            print('   案例 %d 漏检 %s' % (i, '/'.join(w)))
    print('4) act 已并入 film.shot（单槽），动作消歧结果进入编码；更细的动作层级仍需 schema 扩充。')


if __name__ == '__main__':
    main()
