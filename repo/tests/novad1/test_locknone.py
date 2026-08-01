# Lock type None, and the alert LED on Pico W-class boards.
#
# Two separate reports, both the same shape: a setting that claimed one thing while
# the hardware did another.
#
#   * "Lock type" only offered pin/password, so the only way to have no lock was a
#     separate Clear button — and the type kept its old value afterwards, so the
#     screen went on saying PIN for a device with nothing set.
#   * Every notification blinked GPIO 2, because the pico2w profile gave 'led' that
#     default. Nothing is wired there. The real onboard LED hangs off the CYW43
#     module and is addressed as Pin('LED'), which the fallback would have found if
#     the profile had not shadowed it.
import sys
import inspect
import _shims
_shims.install()
from _shims import T

t = T('test_locknone')

# ------------------------------------------------------------------ lock type
import novagui

REG = {}
_real_reg = novagui._reg
_real_save = novagui._save_reg
novagui._reg = lambda k, d=None: REG.get(k, d)
novagui._save_reg = lambda k, v: REG.__setitem__(k, v)
try:
    rows = novagui._rows_security()
    kinds = None
    labels = []
    for r in rows:
        labels.append(r[1])
        if r[1] == 'Lock type':
            kinds = list(r[3])
            apply_fn = r[5]
    t.eq(kinds, ['pin', 'password', 'none'],
         'Lock type offers Pin, Password and None')
    t.ok('Clear lock' not in labels,
         'the separate Clear lock row is gone -- None does that job now')
    t.ok(apply_fn is not None, 'Lock type has an apply callback to do the clearing')

    # Setting None clears BOTH stored codes. Clearing only the one matching the
    # previous type would mean flipping the type back re-locked a device the user
    # had just unlocked.
    REG['Apps.NovaD1_PIN'] = '000000'
    REG['Apps.NovaD1_Pass'] = 'hunter2'
    apply_fn('none')
    t.eq(REG.get('Apps.NovaD1_PIN'), '', 'switching to None clears the PIN')
    t.eq(REG.get('Apps.NovaD1_Pass'), '', 'and the password too')

    # Any other value must not clear anything.
    REG['Apps.NovaD1_PIN'] = '1234'
    apply_fn('pin')
    t.eq(REG.get('Apps.NovaD1_PIN'), '1234', 'switching to pin clears nothing')
    apply_fn('password')
    t.eq(REG.get('Apps.NovaD1_PIN'), '1234', 'nor does switching to password')

    # lock_is_set must honour the type, not just the stored code. A leftover PIN
    # with the type on None must NOT lock the device.
    REG.clear()
    REG['Apps.NovaD1_Lock_Kind'] = 'none'
    REG['Apps.NovaD1_PIN'] = '000000'
    t.ok(not novagui.lock_is_set(),
         'type None means unlocked even if a stale code is still stored')
    t.eq(novagui._lock_status(), 'None', 'and the readout says None')

    REG['Apps.NovaD1_Lock_Kind'] = 'pin'
    t.ok(novagui.lock_is_set(), 'type pin with a PIN stored is locked')
    t.eq(novagui._lock_status(), 'PIN', 'and reads as PIN')

    REG['Apps.NovaD1_Lock_Kind'] = 'password'
    REG['Apps.NovaD1_Pass'] = ''
    t.ok(not novagui.lock_is_set(),
         'type password with no password stored is not locked')
    t.eq(novagui._lock_status(), 'None',
         'the readout reports the truth, not the preference')

    # 'Change code' with the type on None has nothing to edit, so it must not open
    # an editor whose result would be discarded.
    REG['Apps.NovaD1_Lock_Kind'] = 'none'
    scr = novagui._lock_editor()
    t.eq(scr.__class__.__name__, 'TextScreen',
         'Change code explains itself instead of opening a dead editor')
finally:
    novagui._reg = _real_reg
    novagui._save_reg = _real_save

# ------------------------------------------------------------------- alert LED
import novaboard

for bid in ('pico2w', 'picoplus2w'):
    pins = novaboard.profile(bid)['pins']
    t.ok('led' not in pins,
         "{} must not give 'led' a GPIO default -- it would shadow the onboard "
         "CYW43 LED, which is addressed as Pin('LED') and has no GPIO number"
         .format(bid))

# The ESP32-S3 default is a real onboard LED and must stay.
t.ok('led' in novaboard.profile('esp32s3')['pins'],
     'esp32s3 keeps its led default -- that board really does have one on a GPIO')

# And the fallback that now does the work must still be there.
import novanotify
src = inspect.getsource(novanotify._led_alert)
t.ok("Pin('LED'" in src or 'Pin("LED"' in src,
     "the notification LED falls back to Pin('LED') when no GPIO is configured")

sys.exit(t.done())
