import sys
sys.path.insert(0, 'RPCortex-repo/repo/packages/novad1')
import novacanvas, display, novagui, novainput as ev
OUT='./out/'
STATE={'wifi':True,'battery':70,'time':'19:42'}
def shot(mock,n,l): mock.render_png(OUT+n,scale=5,label=l); print('rendered',n)
def ui_for(modules=None):
    cv=novacanvas.Canvas(128,64); mk=display.MockDisplay(128,64); src=ev.ScriptedSource()
    return novagui.NovaUI(mk,cv,src,STATE,novagui.build_home(modules)),mk
# 1) home (module list)
ui,mk=ui_for(); ui.render(); shot(mk,'d1_home.png','Home — test app per module')
# 2) scroll down a few
for _ in range(3): ui.handle(ev.ROT_CW)
ui.render(); shot(mk,'d1_home2.png','Home — scrolled')
# 3) a module test screen with a sample result (DHT11)
scr=novagui.ModuleTestScreen('dht11','DHT11 Temp'); scr.ok=True; scr.lines=['DHT11','Temp: 24 C','Humidity: 46 %']
ui.stack.append(scr); ui.render(); shot(mk,'d1_dht.png','DHT11 test app (sample result)')
# 4) a GPS test screen sample
ui2,mk2=ui_for(); g=novagui.ModuleTestScreen('gps','GPS'); g.ok=True; g.lines=['GPS','FIX  sats: 8','lat 4042.123','lon 07401.45']
ui2.stack.append(g); ui2.render(); shot(mk2,'d1_gps.png','GPS test app (sample fix)')
# 5) graceful degradation
ui3,mk3=ui_for({'cc1101':False,'sx1276':False,'pn532':False}); ui3.render(); shot(mk3,'d1_home_partial.png','Absent modules greyed')
print('done')
