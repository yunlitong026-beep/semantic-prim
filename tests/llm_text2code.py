# -*- coding: utf-8 -*-
"""V2 LLM 版 text2code：人话 → 编码 的提示词 + 输出回编码解析器。

定位（与 V1 规则版 text2code.py 平行，不替代）：
- V1 text2code.py 是规则模板，词表外的主体/时长/场景抽不到（基线已证明）。
- 本模块是 V2：让 LLM 负责「填槽」，但编码合法性仍由 parser.validate 兜底，
  不让 LLM 背 schema 语法。

设计要点：
1. 提示词由 schema.json 动态生成 —— 槽位、可选值都来自取值表，不硬编码，
   以后 Claude 给 schema 加 act.* 槽位时，提示词自动带上，无需改本文件。
2. LLM 只吐结构化 JSON（slots + 识别到的歧义词），不直接吐编码字符串。
3. 歧义回询仍复用 clarify.py：LLM 抽槽 + clarify 消歧 + parser 校验，三层分离。
4. LLM 客户端仅标准库 urllib，可插拔；没配 API key 也能离线自测。

仅标准库，可离线自测：
  python tests/llm_text2code.py
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import clarify  # noqa: E402
import parser   # noqa: E402
import text2code  # noqa: E402  仅复用其 实体/场景/时刻 映射表当提示词参考

DOMAIN = 'film.shot'


def _slot_desc(name, d):
    """把一个 schema 槽位定义转成提示词里的一行说明。"""
    t = d.get('type')
    label = d.get('label', name)
    if t == 'enum':
        vals = '、'.join(d.get('values', []))
        return '- %s（%s）：枚举，只能取 [%s]；取不到填 null' % (name, label, vals)
    if t == 'list':
        vals = '、'.join(d.get('values', []))
        return '- %s（%s）：列表，元素只能取 [%s]；取不到填 null' % (name, label, vals)
    if t == 'entity':
        return '- %s（%s）：主体编码，取不到填 null' % (name, label)
    if t == 'quantity':
        return '- %s（%s）：如 "3s"，取不到填 null' % (name, label)
    return '- %s（%s）：取不到填 null' % (name, label)


def _ref_map_lines():
    """提示词里的参考映射：实体/时刻/场景的取值目前硬编码在 text2code，不在 schema。

    这是已知缺口：ID 的取值表（I01=女子 …）尚未并入 schema.json。提示词先把它们
    当「参考映射」喂给模型，等 schema 补全后可删除。
    """
    ent = '、'.join('%s=%s' % (w, c) for w, c in text2code.ENTITY_MAP)
    tm = '、'.join('%s=%s' % (w, c) for w, c in text2code.T_MAP)
    pm = '、'.join('%s=%s' % (w, c) for w, c in text2code.P_MAP)
    return [
        '参考映射（临时，schema 补全后可删）：',
        '  主体 ID：' + ent,
        '  时刻 T：' + tm,
        '  场景 P：' + pm,
    ]


def build_prompt(text, schema=None):
    """由 schema.json 动态生成 LLM 填槽提示词。

    只让模型填槽 + 报歧义词，不让它背编码语法；输出必须是纯 JSON。
    """
    schema = schema or parser.load_schema()
    ds = schema['domains'][DOMAIN]
    slot_lines = [_slot_desc(k, v) for k, v in ds.get('slots', {}).items()]
    refs = _ref_map_lines()
    body = '\n'.join(slot_lines)
    ref = '\n'.join(refs)
    return (
        '你是一个短剧镜头描述的结构化抽取器。把下面的中文镜头描述解析成槽位取值。\n'
        '\n'
        '槽位定义（名称:类型，取值约束）：\n'
        + body + '\n'
        '\n'
        + ref + '\n'
        '\n'
        '规则：\n'
        '1. 只输出一个 JSON 对象，不要任何解释、不要 markdown 代码块围栏。\n'
        '2. JSON 只有两个键：\n'
        '   - "slots": 对象，只放你能确定取值的槽位；取不到或不确定的槽位直接不写。\n'
        '   - "ambiguous": 数组，列出你识别到、但存在多种理解的词，每项形如\n'
        '     {"word":"御剑","candidates":["手持剑柄挥剑","剑离体，真气丝牵引飞行"]}。\n'
        '3. 禁止脑补：不确定就是不确定，宁可漏槽也不要猜一个具体值。\n'
        '4. 时长抽数字，如 "大概三秒" → "3s"；口语主体要映射到参考映射里的编码。\n'
        '\n'
        '镜头描述：' + text + '\n'
    )


def parse_llm_json(raw, schema=None):
    """把 LLM 输出（可能带 markdown 围栏）解析成 {"slots":..., "ambiguous":...}。

    只做清洗，不做语义判断；坏 JSON 直接抛 ValueError，让上层决定重试或回询。
    """
    s = raw.strip()
    # 去掉可能的 ```json ... ``` 围栏
    m = re.search(r'```(?:json)?\s*(.*?)\s*```', s, re.S)
    if m:
        s = m.group(1).strip()
    obj = json.loads(s)
    if not isinstance(obj, dict):
        raise ValueError('LLM 输出不是 JSON 对象')
    obj.setdefault('slots', {})
    obj.setdefault('ambiguous', [])
    return obj


def build_code(slots, text, picks=None, overrides=None, schema=None):
    """把（LLM 抽出的）slots + clarify 消歧 + overrides 合并成 film.shot@1 编码对象。

    返回结构同 text2code.text2code：{obj, encoding, needs_clarify, unresolved, missing, errors}
    """
    schema = schema or parser.load_schema()
    ds = schema['domains'][DOMAIN]
    merged = dict(slots)

    # 1) schema defaults 兜底（T/P/CAM/SIZE/Q/LIT/SEQ 这些非语义必填）
    for k, v in ds.get('defaults', {}).items():
        merged.setdefault(k, v)

    # 2) clarify 消歧：低置信度歧义词，用户给了 picks 才落槽，否则标记 unresolved
    need = [x for x in clarify.detect(text) if x['confidence'] < clarify.ACCEPT]
    unresolved = []
    if need and picks:
        resolved = clarify.resolve(text, picks)
        merged.update(resolved['slots'])
        unresolved = resolved['unresolved']
    elif need:
        unresolved = [{'word': x['word'], 'candidates': x['candidates']} for x in need]

    # 3) 用户显式覆盖（最高优先级）
    if overrides:
        merged.update(overrides)

    obj = {'domain': DOMAIN, 'version': int(ds.get('version', 1)), 'slots': merged}
    errors = parser.validate(obj, schema)
    # 语义必填：schema required 字段里没被 defaults 兜底的，必须由 LLM/overrides 提供
    required = set(ds.get('required', []))
    missing = [k for k in required if k not in merged]
    return {
        'obj': obj,
        'encoding': parser.dump(obj),
        'needs_clarify': need,
        'unresolved': unresolved,
        'missing': missing,
        'errors': errors,
    }


def call_llm(prompt, api_base, api_key, model, timeout=60):
    """最小 OpenAI 兼容 chat 客户端（stdlib urllib）。

    DeepSeek: api_base=https://api.deepseek.com/v1  model=deepseek-chat
    智谱:     api_base=https://open.bigmodel.cn/api/paas/v4  model=glm-4
    返回 message.content 字符串；网络/鉴权错误原样上抛，不在本层吞掉。
    """
    url = api_base.rstrip('/') + '/chat/completions'
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': '你是结构化抽取器，只输出 JSON。'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + api_key,
        },
        method='POST',
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode('utf-8'))
    return data['choices'][0]['message']['content']


def llm_text2code(text, client=None, picks=None, overrides=None,
                  api_base=None, api_key=None, model=None):
    """全链路：LLM 抽槽 → parse_llm_json → build_code（clarify + validate）。

    client 优先级最高（可传 callable(prompt)->str，便于注入 mock 做离线测试）。
    否则用 api_base/api_key/model 走真实 LLM。
    """
    schema = parser.load_schema()
    prompt = build_prompt(text, schema)
    if client is not None:
        raw = client(prompt)
    else:
        if not (api_base and api_key and model):
            raise ValueError('未配置 LLM：传 client 或 (api_base, api_key, model)')
        raw = call_llm(prompt, api_base, api_key, model)
    llm_out = parse_llm_json(raw, schema)
    return build_code(llm_out.get('slots', {}), text, picks, overrides, schema)


def _self_test():
    """离线自测：mock 一个「完美 LLM 输出」，验证填槽 → 消歧 → 校验全链路。"""
    schema = parser.load_schema()

    def mock_client(prompt):
        # 模拟 LLM 对御剑例子的抽取结果（不含 weapon.*，因为 weapon 是消歧产物）
        return json.dumps({
            'slots': {
                'T': 'T02', 'P': 'P00', 'ID': 'I02', 'CAM': 'C0',
                'SIZE': 'S00', 'Q': '常速', 'LIT': ['L0'], 'DUR': '3s', 'SEQ': '独立',
            },
            'ambiguous': [
                {'word': '御剑', 'candidates': ['手持剑柄挥剑', '剑离体，真气丝牵引、意念操控飞行']},
            ],
        }, ensure_ascii=False)

    text = '黄昏柳树下，男一号施展御剑，手不握剑，真气丝线牵引长剑悬空'
    res = llm_text2code(text, client=mock_client, picks={'御剑': 1}, overrides={'ID': 'I02', 'DUR': '3s'})
    print('编码:', res['encoding'])
    print('校验:', '通过' if not res['errors'] else res['errors'])
    print('缺必填:', res['missing'])
    print('weapon.holder =', res['obj']['slots'].get('weapon.holder'))

    # 断言：闭环成立（武器离体约束进编码）
    assert not res['errors'], res['errors']
    assert not res['missing'], res['missing']
    assert res['obj']['slots'].get('weapon.holder') == 'null'

    # 正向再测一条拥抱：验证 act.* 目前不进编码（Claude 的 Route B 待修）
    def mock_act(prompt):
        return json.dumps({
            'slots': {'T': 'T02', 'P': 'P02', 'ID': 'I02', 'DUR': '2s'},
            'ambiguous': [{'word': '拥抱', 'candidates': ['普通正面拥抱', '公主抱']}],
        }, ensure_ascii=False)
    r2 = llm_text2code('黄昏，街市，男子上前拥抱女子，2秒', client=mock_act, picks={'拥抱': 0})
    print('\n拥抱例编码:', r2['encoding'])
    print('act 是否进编码:', 'act' in r2['obj']['slots'] or any(
        k.startswith('act') for k in r2['obj']['slots']))
    print('（预期 False：act.* 尚未并入 schema，属 Route B 待修）')
    print('\n离线自测通过。')


if __name__ == '__main__':
    _self_test()
