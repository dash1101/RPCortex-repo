# Desc: Nova D1 app loader — load installed kind:py apps (full Nova-UI apps).
# File: /Packages/NovaD1/novaapps.py
#
# A kind:py app is a downloaded .py that builds a real Nova UI screen (not just a
# button grid). It binds to the STABLE surface — novaui (Screen/Menu/tokens/ev) + the
# nova scripting API — which the loader injects into its namespace, so an app never
# imports novagui internals. Contract: the file defines `def app():` returning a Screen;
# optional module-level `TITLE` (home label) and `CATEGORY` (home folder).
#
# SECURITY: loading an app RUNS its code (exec), exactly like nova.run_py. Apps come
# from the user's own repo, and MicroPython cannot meaningfully sandbox exec — so this
# is by design, not a hole. Installing an app is trusting its author. Documented, honest.
#
# MicroPython-safe: no f-strings, positional str.split(), .format() only.


def load_py_app(source):
    """Exec a kind:py app's source with the stable Nova API in scope. Returns
    (factory, meta) where factory() -> a Screen and meta = {'title', 'category'}, or
    (None, None) if it doesn't compile / doesn't define app()."""
    import novaui
    ns = {'ui': novaui, 'ev': novaui.ev}
    try:
        import nova
        ns['nova'] = nova
    except Exception:
        pass
    try:
        exec(source, ns)
    except Exception:
        return None, None
    fac = ns.get('app')
    if not callable(fac):
        return None, None
    cat = ns.get('CATEGORY')
    meta = {'title': ns.get('TITLE'), 'category': cat if cat in _CATS else 'Tools'}
    return fac, meta


_CATS = ('Wireless', 'Sensors', 'Tools', 'System')


def make_screen(source):
    """Convenience: source -> a fresh Screen instance (or None). Used to launch an app."""
    fac, _meta = load_py_app(source)
    try:
        return fac() if fac else None
    except Exception:
        return None
