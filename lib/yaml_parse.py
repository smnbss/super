#!/usr/bin/env python3
"""Minimal YAML parser using only Python stdlib.

Handles the flat/2-level config format used by super.config.yaml.
Supports comment/uncomment based enable/disable for skills/plugins/MCPs.
No external dependencies (no PyYAML/ruamel needed).

Usage:
  python3 yaml_parse.py read  <file> <section>          # list items (detects enabled from comments)
  python3 yaml_parse.py get   <file> <dotted.path>      # get value
  python3 yaml_parse.py set   <file> <dotted.path> <val> # set value
  python3 yaml_parse.py args  <file> <section> <name>   # get args as JSON
  python3 yaml_parse.py item  <file> <section> <name>   # get full item config as JSON
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

def read_section_items(filepath, section):
    """Read items from a section, detecting enabled state from comments.
    
    Returns list of tuples: (name, source_or_command, description, is_enabled)
    """
    items = []
    in_section = False
    section_indent = 0
    current_item = None
    
    with open(filepath) as f:
        lines = f.readlines()
    
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        
        # Check if we're entering the target section
        if stripped.startswith(section + ':'):
            in_section = True
            section_indent = indent
            i += 1
            continue
        
        # Check if we're leaving the section (same indent as section header, new key)
        if in_section and indent == section_indent and stripped and not stripped.startswith('#'):
            in_section = False
            i += 1
            continue

        # Also exit on section separator comments (# ───, # ===, etc.)
        if in_section and indent == section_indent and stripped.startswith('#') and ('───' in stripped or '===' in stripped):
            in_section = False
            i += 1
            continue
        
        if not in_section:
            i += 1
            continue
        
        # Look for item entries at indent level 2 (2 spaces under section)
        # Format: "  name:" or "#  name:" or "###  name:"
        is_commented = stripped.startswith('#')
        
        # Skip sub-keys (indent > section + 2)
        if indent > section_indent + 2:
            i += 1
            continue
        
        # Check if this is an item line (has colon, at the right indent)
        if ':' not in stripped:
            i += 1
            continue
        
        # Get the content after any comment markers
        content = stripped
        while content.startswith('#'):
            content = content[1:]
        content = content.lstrip()
        
        if not content or not content[0].isalnum():
            i += 1
            continue
        
        key, _, rest = content.partition(':')
        key = key.strip()
        
        # Skip common sub-keys - they're not item names
        if key in ('source', 'description', 'enabled', 'command', 'args'):
            i += 1
            continue
        
        # Found an item - now collect its properties from following lines
        source = rest.strip().strip('"').strip("'") if rest else ''
        desc = source
        enabled_field = None  # Track explicit enabled: true/false

        # Look ahead for source/description/enabled (for both enabled and commented items)
        j = i + 1
        while j < len(lines):
            next_line = lines[j]
            next_stripped = next_line.lstrip()
            next_indent = len(next_line) - len(next_stripped)

            # Stop if we hit another item at same level or leave section
            if not next_stripped:
                j += 1
                continue
            if next_indent <= section_indent + 2 and (next_stripped[0].isalnum() or next_stripped.startswith('#')):
                if ':' in next_stripped:
                    # Check if this is a sub-key or new item
                    test_content = next_stripped
                    while test_content.startswith('#'):
                        test_content = test_content[1:]
                    test_content = test_content.lstrip()
                    if test_content.split(':')[0].strip() not in ('source', 'description', 'enabled', 'command', 'args', 'type', 'url', 'env', 'setup'):
                        break

            # Stop at next section
            if next_indent <= section_indent and not next_stripped.startswith('#'):
                break

            # Stop at section separator comments (# ───, # ===)
            if next_stripped.startswith('#') and ('───' in next_stripped or '===' in next_stripped):
                break

            # Get clean content (strip comment markers)
            clean = next_stripped
            while clean.startswith('#'):
                clean = clean[1:]
            clean = clean.lstrip()

            # Look for source/command/description/enabled in sub-keys
            if clean.startswith('source:') or clean.startswith('command:'):
                source = clean.split(':', 1)[1].strip().strip('"').strip("'")
                if not desc or desc == '':
                    desc = source
            elif clean.startswith('description:'):
                desc = clean.split(':', 1)[1].strip().strip('"').strip("'")
            elif clean.startswith('enabled:'):
                val = clean.split(':', 1)[1].strip().strip('"').strip("'").lower()
                enabled_field = val in ('true', 'yes')

            j += 1

        # Determine enabled: explicit field wins, else fall back to comment state
        if enabled_field is not None:
            is_enabled = enabled_field and not is_commented
        else:
            is_enabled = not is_commented

        items.append((key, source, desc, is_enabled))
        i = j
    
    return items

def cmd_read(filepath, section):
    """List items in a section as name|source|desc|enabled."""
    if not os.path.exists(filepath):
        return
    
    # Use the new comment-aware reader for skills/plugins/mcps
    if section in ('skills', 'plugins', 'mcps'):
        items = read_section_items(filepath, section)
        for name, source, desc, enabled in items:
            print(f'{name}|{source}|{desc}|{"true" if enabled else "false"}')
    else:
        # Fallback to old behavior for other sections
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

def cmd_item(filepath, section, name):
    """Get full item config as JSON (all fields)."""
    with open(filepath) as f:
        d = parse_yaml(f.read())
    item = d.get(section, {}).get(name, {})
    print(json.dumps(item))

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
    elif action == 'item' and len(sys.argv) >= 5:
        cmd_item(filepath, sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
        sys.exit(1)
