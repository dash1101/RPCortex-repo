# Desc: Nova D1 App Store — fetch the app index + install apps over HTTPS.
# File: /Packages/NovaD1/novaappstore.py
#
# The device side of repo/novad1-apps/. Fetches the browse index.json, and installs
# an app by downloading its entry file into the scripts store — where it appears on
# the home as an auto-categorised app (see novagui._script_apps). Uses the OS HTTP
# client (net.curl); DEVICE-PENDING for the actual network (needs WiFi). The parse/
# install logic is CPython-testable with a fake net.
#
# MicroPython-safe: no f-strings, positional split, .format() only.

BASE = ('https://raw.githubusercontent.com/dash1101/RPCortex-repo/main/'
        'repo/novad1-apps/')


def _get(url):
    import net
    return net.curl(url)


def fetch_index():
    """Fetch index.json over HTTPS -> list of app dicts, or None on failure. Blocking
    (the caller shows a 'fetching' status first — HTTPS on the D1 takes a few s)."""
    try:
        import json
        return json.loads(_get(BASE + 'index.json')).get('apps', [])
    except Exception:
        return None


def install(app):
    """Download an app's entry file into the scripts store so it lands on the home
    (auto-categorised). `app` is an index entry (needs 'dir'). Returns the installed
    file name, or None."""
    try:
        import novaappcfg
        import novastore
        d = app.get('dir')
        if not d:
            return None
        cfg = novaappcfg.parse(_get(BASE + d + '/app.cfg'))
        entry = cfg.get('entry')
        if not entry:
            return None
        content = _get(BASE + d + '/' + entry)
        if not content:
            return None
        cat = 'pyapps' if cfg.get('kind') == 'py' else 'scripts'
        novastore.save_code(cat, entry, content)     # button grids -> scripts, full apps -> pyapps
        return entry
    except Exception:
        return None


def installed_names():
    """Entry file names already installed (to show 'installed' state) — button-grid apps
    live in the scripts store, kind:py apps in the pyapps store."""
    try:
        import novastore
        return set(novastore.list_codes('scripts')) | set(novastore.list_codes('pyapps'))
    except Exception:
        return set()
