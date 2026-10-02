# -*- coding: utf-8 -*-
"""V2 双 AI 对测：接两个真 LLM 走 llm_text2code，测真指标③（双AI一致性）。

与 V1 dual_ai_run.py 的本质区别：
- V1 用同一套 text2code 规则版跑一遍，指标③必然全 1.0（同款跑两遍，无意义）。
- V2 接两个不同 LLM（如 DeepSeek + 智谱），指标③ = 两模型「原始填槽」的一致率，
  这才是原子正交性的真实证据：两 AI 对同一句话填出不同槽，说明该槽位组合有歧义。

四指标：
  ① 编码合法性：过 parser.validate 且不缺语义必填
  ② 还原保真度：render(编码) 保留原文关键语义的比例
  ③ 双AI一致性：LLM-A 原始 slots vs LLM-B 原始 slots 一致率（核心，V2 才有效）
  ④ 歧义定位率：clarify 捕获歧义词 / 语料标注歧义词

关键设计：
- 指标③比的是「原始填槽」（LLM 直接吐的 slots，未过 clarify/overrides），
  因此不依赖 act.* 是否已并入 schema —— 两 AI 对「拥抱」填 act.hug.front / act.hug.carry
  即使都进不了编码，也算不一致，不会被假一致掩盖。

用法：
  # 离线 mock（无 API key，验证执行脚本骨架）
  python tests/dual_ai_run_v2.py --mock
  # 真双 LLM（从环境变量读两个端点，key 不进仓库）
  python tests/dual_ai_run_v2.py --real

真 LLM 环境变量：
  LLM_A_API_BASE / LLM_A_API_KEY / LLM_A_MODEL
  LLM_B_API_BASE / LLM_B_API_KEY / LLM_B_MODEL
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'demo'))
sys.path.insert(0, HERE)

import clarify  # noqa: E402
import parser   # noqa: E402
import text2code  # noqa: E402
import llm_text2code as ltc  # noqa: E402
from roundtrip import render  # noqa: E402

SCHEMA = parser.load_schema()


def load_cases():
    with open(os.path.join(HERE, 'dual_ai_corpus.json'), encoding='utf-8') as f:
        return json.load(f)['cases']


def _norm(v):
    """值归一化，便于跨 LLM 比较（list/dict 用稳定 JSON 串比较）。"""
    if isinstance(v, (dict, list)):
        return json.dumps(v, sort_keys=True, ensure_ascii=False)
    return v


def slot_agreement(slots_a, slots_b):
    """指标③：两个原始填槽 dict 的一致率 + 不一致的槽位名。"""
    keys = set(slots_a) | set(slots_b)
    if not keys:
        return 1.0, []
    disagree = [k for k in keys
                if k not in slots_a or k not in slots_b
                or _norm(slots_a[k]) != _norm(slots_b[k])]
    return 1.0 - len(disagree) / len(keys), disagree


def fidelity(rendered, keywords):
    if not keywords:
        return 1.0, []
    miss = [k for k in keywords if k not in rendered]
    return 1.0 - len(miss) / len(keywords), miss


def run_case(case, client_a, client_b):
    """跑一条语料：两个 LLM 原始填槽 → 指标③；再经 clarify/overrides → ①②④。"""
    text = case['text']
    picks = case.get('picks') or {}
    overrides = case.get('overrides') or {}
    amb = case.get('ambiguous', [])
    keywords = case.get('keywords', [])

    # 两个 LLM 的原始填槽（只取 slots，不落 clarify/overrides）
    raw_a = {'slots': {}, 'error': None}
    raw_b = {'slots': {}, 'error': None}
    for tag, cli, holder in (('A', client_a, raw_a), ('B', client_b, raw_b)):
        try:
            out = ltc.parse_llm_json(cli(ltc.build_prompt(text, SCHEMA)), SCHEMA)
            holder['slots'] = out.get('slots', {})
        except Exception as e:  # noqa: BLE001 —— LLM 输出异常要显式记录，不中断整批
            holder['error'] = '%s: %s' % (type(e).__name__, e)

    agree, disagree = slot_agreement(raw_a['slots'], raw_b['slots'])

    # 用 A 路原始填槽 + clarify + overrides 生成参考编码，算 ①②④
    ref = ltc.build_code(raw_a['slots'], text, picks, overrides, SCHEMA)
    valid = not ref['errors'] and not ref['missing']
    f = None
    miss_kw = []
    if not ref['missing'] and not ref['errors']:
        f, miss_kw = fidelity(render(ref['obj']), keywords)

    found = {x['word'] for x in clarify.detect(text)}
    hit_amb = [w for w in amb if w in found]
    miss_amb = [w for w in amb if w not in found]
    d = len(hit_amb) / len(amb) if amb else None

    return {
        'id': case['id'], 'agree': agree, 'disagree': disagree,
        'valid': valid, 'missing': ref['missing'], 'errors': ref['errors'],
        'fidelity': f, 'miss_kw': miss_kw, 'detection': d, 'miss_amb': miss_amb,
        'err_a': raw_a['error'], 'err_b': raw_b['error'],
        'encoding': ref['encoding'],
    }


def color(r):
    # LLM 调用失败优先标红（无法测量）
    if r['err_a'] or r['err_b']:
        return 'red'
    if r['missing'] or r['errors']:
        return 'red'
    checks = [r['agree']]
    if r['fidelity'] is not None:
        checks.append(r['fidelity'])
    if r['detection'] is not None:
        checks.append(r['detection'])
    if any(c < 0.4 for c in checks):
        return 'red'
    if any(c < 0.8 for c in checks):
        return 'yellow'
    return 'green'


ICON = {'green': '🟢', 'yellow': '🟡', 'red': '🔴'}


def _mock_a(prompt):
    """mock LLM-A：贴近规则版 text2code 的抽槽（覆盖矩阵槽位）。"""
    m = re.search(r'镜头描述：(.+)', prompt, re.S)
    text = m.group(1).strip() if m else ''
    slots = text2code.extract(text)
    return json.dumps({'slots': slots}, ensure_ascii=False)


def _mock_b(prompt):
    """mock LLM-B：故意弱一点，漏 DUR / 漏主体颜色，制造可控分歧证明指标③能测出。"""
    m = re.search(r'镜头描述：(.+)', prompt, re.S)
    text = m.group(1).strip() if m else ''
    slots = text2code.extract(text)
    # 模拟弱抽取器：丢掉时长（口语时长抽不到），丢掉实体颜色属性
    slots.pop('DUR', None)
    if isinstance(slots.get('ID'), dict):
        slots['ID'] = slots['ID'].get('value')
    return json.dumps({'slots': slots}, ensure_ascii=False)


def _clients_from_env():
    a = (os.environ.get('LLM_A_API_BASE'), os.environ.get('LLM_A_API_KEY'), os.environ.get('LLM_A_MODEL'))
    b = (os.environ.get('LLM_B_API_BASE'), os.environ.get('LLM_B_API_KEY'), os.environ.get('LLM_B_MODEL'))
    if not all(a) or not all(b):
        raise SystemExit('缺 LLM 端点配置：需设置 LLM_A_* 与 LLM_B_* 三组环境变量')

    def mk(base, key, model):
        return lambda prompt: ltc.call_llm(prompt, base, key, model)

    return mk(*a), mk(*b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mock', action='store_true', help='离线 mock 模式（默认）')
    ap.add_argument('--real', action='store_true', help='接真双 LLM（读环境变量）')
    args = ap.parse_args()

    if args.real:
        ca, cb = _clients_from_env()
        mode = 'REAL'
    else:
        ca, cb = _mock_a, _mock_b
        mode = 'MOCK（仅验证脚本骨架，指标③非真实测量）'

    cases = load_cases()
    results = [run_case(c, ca, cb) for c in cases]

    print('V2 双 AI 对测 —— 指标③为真双 LLM 一致率（mode=%s）\n' % mode)
    header = '%-4s %-7s %-7s %-7s %-5s  %s' % ('ID', '③一致', '②保真', '④歧义', '颜色', '原文')
    print(header)
    print('-' * 100)
    for r, c in zip(results, cases):
        a = '%.2f' % r['agree']
        f = '%.2f' % r['fidelity'] if r['fidelity'] is not None else '-'
        d = '%.2f' % r['detection'] if r['detection'] is not None else '-'
        flag = 'ERR' if (r['err_a'] or r['err_b']) else ('缺%s' % '/'.join(r['missing']) if r['missing'] else ('FAIL' if r['errors'] else 'OK'))
        print('%-4s %-7s %-7s %-7s %-5s  %s' % (r['id'], a, f, d, ICON[color(r)], c['text']))

    n = len(results)
    green = sum(1 for r in results if color(r) == 'green')
    yellow = sum(1 for r in results if color(r) == 'yellow')
    red = sum(1 for r in results if color(r) == 'red')
    agrees = [r['agree'] for r in results]
    print('\n汇总：%d 条 | 🟢%d  🟡%d  🔴%d' % (n, green, yellow, red))
    print('平均双AI一致性③: %.2f' % (sum(agrees) / len(agrees)))

    print('\n不一致槽位定位（指标③<1 的具体槽位 = 两 AI 填槽分歧点，V2 回炉依据）：')
    for r in results:
        if r['disagree']:
            print('  案例 %d: %s' % (r['id'], '/'.join(r['disagree'])))


if __name__ == '__main__':
    main()
