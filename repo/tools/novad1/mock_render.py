import sys
sys.path.insert(0, 'RPCortex-repo/repo/packages/novad1')
import novacanvas, display, novagui, novainput as ev, novamods
OUT='./out/'
STATE={'wifi':True,'battery':70,'time':'19:42'}
def shot(mk,n,l): mk.render_png(OUT+n,scale=5,label=l); print('rendered',n)
def newui(style=None):
    cv=novacanvas.Canvas(128,64); mk=display.MockDisplay(128,64)
    return novagui.NovaUI(mk,cv,ev.ScriptedSource(),STATE,novagui.build_home({},style)),mk

# pixel-op counter to confirm the gallery is lighter than the old filled cards
orig=novacanvas.Canvas.pixel
def counted(self,*a,**k):
    counted.n+=1; return orig(self,*a,**k)
counted.n=0; novacanvas.Canvas.pixel=counted

ui,mk=newui(); counted.n=0; ui.render(); print('gallery home pixel-ops:',counted.n)
shot(mk,'g_home.png','Icon gallery home (font8x8)')
ui.handle(ev.ROT_CW); ui.handle(ev.ROT_CW); ui.handle(ev.ROT_CW)
ui.stack[-1].tick(60); ui.render(); shot(mk,'g_slide.png','Gallery mid-slide')
ui.stack[-1].tick(200); ui.render(); shot(mk,'g_set.png','Settled (Sub-GHz)')
ui.handle(ev.ROT_CW); ui.handle(ev.ROT_CW); ui.stack[-1].tick(300); ui.render(); shot(mk,'g_bt.png','Bluetooth icon')

# menu-style home (fallback) for comparison
um,mm=newui('menu'); um.render(); shot(mm,'g_menu.png','Menu-style home (fallback)')

# a module test screen with a sample result
ts=novagui.ModuleTestScreen('gps','GPS'); ts.ok=True
ts.lines=['GPS RX ok','bytes 412','sats 7','no fix yet 6s']
ui.stack.append(ts); ui.render(); shot(mk,'g_test.png','Module test (GPS RX status)')

# --- cancel-anything driver test (fake long generator with cleanup) ---
import types
closed={'fin':False}
def fake(key,cancel):
    try:
        for i in range(100):
            if cancel(): return
            yield (None,['working '+str(i)])
        yield (True,['done'])
    finally:
        closed['fin']=True
novamods.run_test=fake
scr=novagui.ModuleTestScreen('x','Fake')
scr.on_event(ev.SELECT)               # start
for _ in range(3): scr.tick(40)       # advance a few progress steps
running_before=scr._running()
r=scr.on_event(ev.BACK)               # BACK while running -> cancel
print('cancel test: running_before=%s after_back_running=%s finally_ran=%s lines=%s'%(
    running_before, scr._running(), closed['fin'], scr.lines))
