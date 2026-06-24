import sys
sys.path.insert(0, 'RPCortex-repo/repo/packages/novad1')
import novacanvas, display, novagui, novainput as ev
OUT='./out/'
STATE={'wifi':True,'battery':70,'time':'19:42'}
def shot(mk,n,l): mk.render_png(OUT+n,scale=5,label=l); print('rendered',n)
def newui(home=None):
    cv=novacanvas.Canvas(128,64); mk=display.MockDisplay(128,64); src=ev.ScriptedSource()
    h=home or novagui.build_home({})
    return novagui.NovaUI(mk,cv,src,STATE,h),mk

# 1) shelf home (card 0 centered)
ui,mk=newui(); ui.render(); shot(mk,'d1_shelf.png','Rotating-shelf home (new 6x8 font)')
# 2) mid-slide animation frame: rotate, then tick a partial dt
ui.handle(ev.ROT_CW)            # sel 0->1, sel_f still 0
ui.stack[-1].tick(70)           # SLIDE_MS=140 -> sel_f ~0.5 (mid-slide)
ui.render(); shot(mk,'d1_shelf_slide.png','Mid-slide (smooth carousel)')
# 3) settled on card 1
ui.stack[-1].tick(140); ui.render(); shot(mk,'d1_shelf_2.png','Settled on next card')
# 4) module test screen w/ sample result
ts=novagui.ModuleTestScreen('pn532','NFC (PN532)'); ts.ok=True; ts.lines=['PN532 v1.6','Tag UID:','04 a2 5b 9c 31']
ui2,mk2=newui(); ui2.stack.append(ts); ui2.render(); shot(mk2,'d1_test.png','NFC test app (sample UID)')
# 5) WiFi app with sample scan
wf=novagui.WiFiScreen(); wf.nets=[('dash_',-41,True),('NETGEAR-5G',-58,False),('xfinitywifi',-72,False),('CafeGuest',-80,False)]
ui3,mk3=newui(); ui3.stack.append(wf); ui3.render(); shot(mk3,'d1_wifi.png','WiFi app (scan, * = saved)')
# 6) Manage Apps
allp=[(k,l) for k,l,_f in novagui._all_apps()]
ma=novagui.ManageAppsScreen(allp,[k for k,_l in allp])
ui4,mk4=newui(); ui4.stack.append(ma); ui4.render(); shot(mk4,'d1_apps.png','Manage Apps (homepage config)')
print('OK home items:', [it[0] for it in ui.stack[0].items])
