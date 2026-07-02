# Desc: Nova D1 app config — parse an app.cfg (RPCortex-package style) + auto-category.
# File: /Packages/NovaD1/novaappcfg.py
#
# Nova apps use the same shape as RPCortex packages (a `key: value` cfg), just with
# `app.*` keys instead of `pkg.*`:
#     app.name: BLE Pranks
#     app.ver: 1.0.0
#     app.category: auto        (or Wireless / Sensors / Tools / System)
#     app.kind: buttons         (buttons | py)
#     app.entry: ble-pranks.txt
#     app.desc: ...
# When app.category is 'auto' (or missing), the home category is derived from the
# app's content — a button-grid's dominant action verb picks the folder.
# MicroPython-safe: no f-strings, positional split, .format() only.

_CATEGORIES = ('Wireless', 'Sensors', 'Tools', 'System')
# action verb -> home category (for auto-categorising by content).
_VERB_CAT = {
    'ble': 'Wireless', 'lora': 'Wireless', 'subghz': 'Wireless', 'ir': 'Wireless',
    'nfc': 'Wireless', 'wifi': 'Wireless',
    'run': 'System',
    'notify': 'Tools', 'log': 'Tools', 'sleep': 'Tools',
}


def parse(text):
    """Parse an app.cfg -> dict of the app.* fields (without the 'app.' prefix)."""
    out = {}
    for line in text.split('\n'):
        line = line.strip()
        if not line or line[0] == '#' or ':' not in line:
            continue
        k, v = line.split(':', 1)
        k = k.strip()
        if k.startswith('app.'):
            out[k[4:]] = v.strip()
    return out


def auto_category(kind, content):
    """Pick a home category from an app's content. For a button grid, the most-used
    action verb's category wins; anything unrecognised -> Tools."""
    counts = {}
    if kind == 'buttons' and content:
        for line in content.split('\n'):
            line = line.strip()
            if not line or line[0] == '#' or '=' not in line:
                continue
            act = line.split('=', 1)[1].strip().split(None, 1)
            if act:
                cat = _VERB_CAT.get(act[0].lower())
                if cat:
                    counts[cat] = counts.get(cat, 0) + 1
    if not counts:
        return 'Tools'
    best = 'Tools'
    best_n = -1
    for cat in _CATEGORIES:                       # ties resolve by category order
        if counts.get(cat, 0) > best_n:
            best_n = counts.get(cat, 0)
            best = cat
    return best


def category(cfg, content=''):
    """The app's home category — explicit app.category, else auto from content."""
    c = cfg.get('category', 'auto')
    if c == 'auto' or c not in _CATEGORIES:
        return auto_category(cfg.get('kind', 'buttons'), content)
    return c
