import sys
sys.path.insert(0, '../../packages/novad1')
import novacanvas, display, novagui, novainput as ev

import os; os.makedirs('renders', exist_ok=True); OUT = 'renders/'
STATE = {'wifi': True, 'battery': 50, 'time': '14:23'}

def new_ui(modules=None, state=None):
    cv = novacanvas.Canvas(128, 64)
    mock = display.MockDisplay(128, 64)
    src = ev.ScriptedSource()
    home = novagui.build_home(modules)
    return novagui.NovaUI(mock, cv, src, (state or STATE), home), mock

def shot(mock, name, label):
    mock.render_png(OUT + name, scale=5, label=label)
    print('rendered', name)

# 1) Home, all modules present
ui, mock = new_ui()
ui.render(); shot(mock, 'd1_home.png', 'Home (all modules)')

# 2) Home, navigated to Sub-GHz
ui.handle(ev.ROT_CW); ui.render(); shot(mock, 'd1_home_subghz.png', 'Home -> Sub-GHz selected')

# 3) Drill into Sub-GHz: a running scan ~40%
ui.handle(ev.SELECT)                 # push RunningScreen
ui.stack[-1].progress = 42
ui.render(); shot(mock, 'd1_scan.png', 'Sub-GHz scanning (cancel anytime)')

# 4) Cancel it (BACK) -> shows Cancelled
ui.handle(ev.BACK); ui.render(); shot(mock, 'd1_scan_cancel.png', 'Action cancelled mid-run')

# 5) A sub-menu (Settings)
ui2, mock2 = new_ui()
ui2.handle(ev.ROT_CCW)               # wrap up to Settings (last item)
ui2.handle(ev.SELECT)
ui2.render(); shot(mock2, 'd1_settings.png', 'Settings sub-menu')

# 6) Graceful degradation: only display+gps present, rest absent (greyed)
ui3, mock3 = new_ui(modules={'nfc': False, 'subghz': False, 'ir': False, 'lora': False, 'gps': True})
ui3.render(); shot(mock3, 'd1_home_partial.png', 'Home — absent modules greyed (x)')
print('done')
