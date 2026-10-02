# -*- coding: utf-8 -*-
"""
语义原语解析器：编码 <-> JSON，并做取值表校验。

职责：
1. parse(enc)             —— 把一段「语义原语编码」解析成结构化 JSON（dict）。
2. dump(obj)              —— 把结构化 JSON 反向序列化回编码字符串。
3. validate(obj, schema)  —— 按 schema.json 的取值表校验编码是否合法。

设计要点：
- 仅依赖 Python 标准库，无第三方依赖，可离线运行。
- 编码格式：`域前缀@版本 { 槽位:值, 槽位:值, ... }`
  例：`film.shot@1 { T:T01, P:P01, ID:I01[红], CAM:C1, SIZE:S4, Q:慢, LIT:[L0], DUR:2s, SEQ:接续 }`
- 槽位值支持三种形态：
  * 枚举字符串（如 T01、慢）
  * 列表（用 [] 包裹，如 [L0,L8]）
  * 带属性的实体（如 I01[红] → {"value":"I01","attr":"红"}）
"""
import json
import os
import re
import sys

# schema.json 的绝对路径：与 parser.py 同目录，保证任意工作目录下都能定位到取值表
_SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'schema.json')


def load_schema(path=_SCHEMA):
    """读取取值表 schema.json，返回 dict。"""
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def split_top(s, sep):
    """在「顶层」按 sep 切分字符串，忽略方括号 [] 内部的 sep。

    作用：编码主体里 LIT:[L0,L8] 这种列表值内部含逗号，
    不能简单按逗号切分，否则会把列表切成两半。
    这里用一个深度计数器，只有 depth==0（不在 [] 内）时才认作真正的分隔符。
    """
    parts, depth, cur = [], 0, ''
    for ch in s:
        if ch == '[':
            depth += 1
        elif ch == ']':
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    if cur.strip():
        parts.append(cur)
    return parts


def parse_value(v):
    """把单个槽位的「字符串值」解析成 Python 值。

    - `[a,b,c]`   → 列表 ['a','b','c']
    - `I01[红]`   → 实体 dict {'value':'I01','attr':'红'}
    - 其他         → 原样字符串
    """
    if v.startswith('[') and v.endswith(']'):
        inner = v[1:-1].strip()
        return [x.strip() for x in inner.split(',') if x.strip()]
    m = re.match(r'^([A-Za-z0-9_.]+)\[([^\]]+)\]$', v)
    if m:
        return {'value': m.group(1), 'attr': m.group(2)}
    return v


def dump_value(v):
    """parse_value 的逆操作：把 Python 值序列化回字符串。"""
    if isinstance(v, list):
        return '[' + ','.join(str(x) for x in v) + ']'
    if isinstance(v, dict) and 'attr' in v:
        return "%s[%s]" % (v['value'], v['attr'])
    return str(v)


def parse(enc):
    """解析一段编码，返回 {'domain','version','slots'}。

    编码头部正则：`域@版本 { ... }`，例如 `film.shot@1 { ... }`。
    主体按「顶层逗号」切分，逐条解析成「槽位:值」键值对。
    """
    enc = enc.strip()
    m = re.match(r'^([A-Za-z0-9_.]+)@(\d+)\s*\{(.*)\}$', enc, re.S)
    if not m:
        raise ValueError('无法解析头部: %r' % enc)
    domain, version, body = m.group(1), m.group(2), m.group(3)
    slots = {}
    for item in split_top(body, ','):
        item = item.strip()
        if not item:
            continue
        if ':' not in item:
            raise ValueError('槽位缺少冒号: %r' % item)
        k, v = item.split(':', 1)
        slots[k.strip()] = parse_value(v.strip())
    return {'domain': domain, 'version': int(version), 'slots': slots}


def dump(obj):
    """把结构化对象反向序列化成编码字符串。"""
    parts = ['%s:%s' % (k, dump_value(v)) for k, v in obj['slots'].items()]
    return "%s@%s { %s }" % (obj['domain'], obj['version'], ', '.join(parts))


def validate(obj, schema):
    """按取值表校验编码，返回错误列表（空列表 = 通过）。

    校验项：
    - 领域是否存在于 schema
    - 版本是否匹配
    - 是否出现未知槽位 / 缺少必填槽位
    - 各槽位取值类型与取值范围是否合法
    """
    ds = schema['domains'].get(obj['domain'])
    if not ds:
        return ['未知领域: %s' % obj['domain']]
    errors = []
    # 版本一致性检查
    if str(obj['version']) != str(ds.get('version', '1')):
        errors.append('版本不匹配: 编码 %s，表 %s' % (obj['version'], ds.get('version')))
    defs = ds.get('slots', {})
    optional = set(ds.get('optional', []))
    # 未知槽位检查
    for k in obj['slots']:
        if k not in defs:
            errors.append('未知槽位: %s' % k)
    # 必填槽位 + 取值校验
    # optional 槽位允许缺失；其余槽位缺失报错（编码要求槽位完整，spec §9）
    for k, d in defs.items():
        if k not in obj['slots']:
            if k in optional:
                continue
            errors.append('缺少槽位: %s' % k)
            continue
        v = obj['slots'][k]
        t = d['type']
        if t == 'enum':
            if v not in d['values']:
                errors.append('槽位 %s 值 %r 不在取值表' % (k, v))
        elif t == 'list':
            if not isinstance(v, list):
                errors.append('槽位 %s 应为列表' % k)
            else:
                for x in v:
                    if x not in d['values']:
                        errors.append('槽位 %s 列表项 %r 不在取值表' % (k, x))
        elif t == 'entity':
            if isinstance(v, dict):
                if 'value' not in v:
                    errors.append('槽位 %s 实体缺少 value' % k)
            elif not isinstance(v, str):
                errors.append('槽位 %s 实体类型错误' % k)
        elif t == 'quantity':
            if not re.match(r'^\d+(\.\d+)?\s*(ms|s|帧|%)?$', str(v)):
                errors.append('槽位 %s 数量格式错误: %r' % (k, v))
    return errors


if __name__ == '__main__':
    # 命令行入口：python parser.py parse <编码>  或  python parser.py validate <编码>
    if len(sys.argv) < 3:
        print('用法: python parser.py parse <编码>  或  python parser.py validate <编码>')
        sys.exit(1)
    cmd, enc = sys.argv[1], sys.argv[2]
    schema = load_schema()
    obj = parse(enc)
    if cmd == 'parse':
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    elif cmd == 'validate':
        errs = validate(obj, schema)
        if errs:
            print('校验失败:')
            for e in errs:
                print(' -', e)
            sys.exit(1)
        print('校验通过')
        print(json.dumps(obj, ensure_ascii=False, indent=2))
    else:
        print('未知命令:', cmd)
        sys.exit(1)
