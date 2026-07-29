# Renders the Nova D1 boot sequence (splash -> boot check -> home) to PNGs via the
# MockDisplay backend, so the UI can be reviewed with no hardware attached.
#   python3 boot_render.py [--out DIR]      (default: ./out/)
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, '..', '..', 'packages', 'novad1'))
import novacanvas, display, novagui, novainput as ev, novalog, novasplash

OUT = './out/'
if '--out' in sys.argv:
    OUT = sys.argv[sys.argv.index('--out') + 1]
if not OUT.endswith('/'):
    OUT += '/'
os.makedirs(OUT, exist_ok=True)
ST={'wifi':True,'battery':70,'time':'19:42'}
def newui(home=None):
    cv=novacanvas.Canvas(128,64); mk=display.MockDisplay(128,64)
    return novagui.NovaUI(mk,cv,ev.ScriptedSource(),ST,home or novagui.build_home({})),mk

# --- splash frames ---
for t,nm in [(0.30,'s_30'),(0.62,'s_62'),(0.92,'s_92')]:
    cv=novacanvas.Canvas(128,64); mk=display.MockDisplay(128,64)
    novasplash.draw(cv,t); mk.show(cv); mk.render_png(OUT+nm+'.png',scale=5,label='splash t=%.2f'%t)
print('splash rendered')

# --- full boot sequence: splash -> check -> home ---
ui,mk=newui()
ui.stack=novagui.make_boot_stack(ui.stack[0])
clk=[0]; ui._now=lambda: clk[0]; prev=0
ui.render()
boot_shot=False; depth_seen=[]
for i in range(400):
    clk[0]+=40
    prev,nap=ui._loop_once(prev,40)
    depth_seen.append(len(ui.stack))
    # grab a boot-check frame (fullscreen check, stack depth 2)
    if not boot_shot and len(ui.stack)==2 and ui.stack[-1].__class__.__name__=='BootCheckScreen':
        if ui.stack[-1].done>0:
            mk.render_png(OUT+'boot_check.png',scale=5,label='Boot check + loading bar'); boot_shot=True
print('boot seq settled to depth', len(ui.stack), '(1=home)  boot_check_shot=',boot_shot)

# --- System Check app (settled) ---
ui2,mk2=newui(); sc=novagui.SystemCheckScreen(); ui2.stack.append(sc)
for _ in range(30): sc.tick(40)
ui2.render(); mk2.render_png(OUT+'syscheck.png',scale=5,label='System Check app')

# --- Logs app ---
novalog._LOGF=OUT+'nova.log'
novalog.clear()
for m in ['Nova D1 GUI started','boot check: 5/6 present','test pn532 OK','GPS no fix']:
    novalog.log(m)
lg=novagui._logs_screen(); ui2.stack.append(lg); ui2.render(); mk2.render_png(OUT+'logs.png',scale=5,label='Logs app')

# --- text-wrap fix: long GPS result ---
ts=novagui.ModuleTestScreen('gps','GPS'); ts.ok=False
ts.lines=['GPS RX ok','no fix (needs sky)','bytes 2250','sats 00']
ui3,mk3=newui(); ui3.stack.append(ts); ui3.render(); mk3.render_png(OUT+'wrap.png',scale=5,label='Wrapped GPS result')
print('all rendered; logs tail:', novalog.tail(2))
