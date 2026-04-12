#!/usr/bin/env python3
"""Minimal YAML parser using only Python stdlib.

Handles the flat/2-level config format used by super.config.yaml.
No external dependencies (no PyYAML/ruamel needed).

Usage:
  python3 yaml_parse.py read  <file> <section>          # list items
  python3 yaml_parse.py get   <file> <dotted.path>      # get value
  python3 yaml_parse.py set   <file> <dotted.path> <val> # set value
  python3 yaml_parse.py args  <file> <section> <name>   # get args as JSON
"""

import sys, json, re, os

def parse_yaml(text):
    """Parse simple YAML into nested dicts. Handles 2-level nesting."""
    result = {}
    stack = [result]
    indent_stack = [-1]

    for line in text.split('\n'):
        stripped = line.lstrip()
        if not stripped or stripped.startswith('#'):
            continue
        indent = len(line) - len(stripped)

        while indent <= indent_stack[-1]:
            stack.pop()
            indent_stack.pop()

        if ':' in stripped:
            key, _, val = stripped.partition(':')
            key = key.strip()
            val = val.strip()

            # Remove inline comments
            if val and '#' in val:
                # Don't strip # inside quotes
                if not (val.startswith('"') or val.startswith("'")):
                    val = val[:val.index('#')].strip()

            if val == '' or (val.startswith('#')):
                new_dict = {}
                stack[-1][key] = new_dict
                stack.append(new_dict)
                indent_stack.append(indent)
            else:
                val = val.strip('"').strip("'")
                if val.lower() == 'true': val = True
                elif val.lower() == 'false': val = False
                elif val.isdigit(): val = int(val)
                elif val.startswith('['):
                    try: val = json.loads(val)
                    except: pass
                stack[-1][key] = val

    return result

def dump_yaml(d, indent=0):
    """Dump dict back to YAML string."""
    lines = []
    prefix = '  ' * indent
    for k, v in d.items():
        if isinstance(v, dict):
            lines.append(f'{prefix}{k}:')
            lines.append(dump_yaml(v, indent + 1))
        elif isinstance(v, bool):
            lines.append(f'{prefix}{k}: {"true" if v else "false"}')
        elif isinstance(v, list):
            lines.append(f'{prefix}{k}: {json.dumps(v)}')
        elif isinstance(v, int):
            lines.append(f'{prefix}{k}: {v}')
        elif v == '':
            lines.append(f'{prefix}{k}: ""')
        else:
            lines.append(f'{prefix}{k}: {v}')
    return '\n'.join(lines)

def get_nested(d, path):
    """Get value at dotted path like 'security.yoloMode'."""
    keys = path.split('.')
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, '')
        else:
            return ''
    return d

def set_nested(d, path, value):
    """Set value at dotted path."""
    keys = path.split('.')
    for k in keys[:-1]:
        if k not in d or not isinstance(d[k], dict):
            d[k] = {}
        d = d[k]
    # Parse value type
    if isinstance(value, str):
        if value.lower() == 'true': value = True
        elif value.lower() == 'false': value = False
        elif value.isdigit(): value = int(value)
    d[keys[-1]] = value

def cmd_read(filepath, section):
    """List items in a section as name|source|desc|enabled."""
    with open(filepath) as f:
        d = parse_yaml(f.read())
    items = d.get(section, {})
    if not isinstance(items, dict):
        return
    for name, val in items.items():
        if not isinstance(val, dict):
            continue
        source = val.get('source', val.get('command', ''))
        enabled = str(val.get('enabled', False)).lower() == 'true'
        desc = val.get('description', source)
        print(f'{name}|{source}|{desc}|{"true" if enabled else "false"}')

def cmd_get(filepath, path):
    """Get single value."""
    with open(filepath) as f:
        d = parse_yaml(f.read())
    val = get_nested(d, path)
    if isinstance(val, bool):
        print('true' if val else 'false')
    else:
        print(val)

def cmd_set(filepath, path, value):
    """Set single value and rewrite file."""
    with open(filepath) as f:
        text = f.read()
    d = parse_yaml(text)
    set_nested(d, path, value)
    # Rewrite — preserve comments by doing line-level replacement if possible
    with open(filepath, 'w') as f:
        f.write(dump_yaml(d))
        f.write('\n')

def cmd_args(filepath, section, name):
    """Get args array for an MCP as JSON string."""
    with open(filepath) as f:
        d = parse_yaml(f.read())
    item = d.get(section, {}).get(name, {})
    args = item.get('args', [])
    print(json.dumps(args))

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    action = sys.argv[1]
    filepath = sys.argv[2]

    if not os.path.exists(filepath):
        sys.exit(0)

    if action == 'read' and len(sys.argv) >= 4:
        cmd_read(filepath, sys.argv[3])
    elif action == 'get' and len(sys.argv) >= 4:
        cmd_get(filepath, sys.argv[3])
    elif action == 'set' and len(sys.argv) >= 5:
        cmd_set(filepath, sys.argv[3], sys.argv[4])
    elif action == 'args' and len(sys.argv) >= 5:
        cmd_args(filepath, sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
        sys.exit(1)
