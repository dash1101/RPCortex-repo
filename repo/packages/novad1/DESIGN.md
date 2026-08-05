# Nova D1 — Interface Design System

The Nova D1 UI is a **128×64, 1-bit** OLED driven by **one rotary encoder + 3 buttons**.
That is the whole design budget: ~21 characters wide, ~6 rows tall, no colour, no
touch, one thumb. This document is the set of rules that make every screen feel like
part of one device instead of 50 separately-invented screens. It applies to every new
screen; a rule broken deliberately should say why in the code.

## Principles

1. **One thumb, four gestures.** Every interaction is turn / SELECT / HOME / BACK. If a
   screen needs more, it's too complex for the device — split it.
2. **The screen always says what the controls do.** A first-time user should never guess.
   The bottom row is a live control hint, not decoration.
3. **Legibility beats density.** At this size, one clear value beats four cramped ones.
   Prefer a big number + a label over a table.
4. **Motion is feedback, not flourish.** Animate to show a state change (selection, a
   value moving, boot). Never animate idle chrome.

## Layout tokens

Do not hard-code pixel positions. Use the shared constants (from `novafont` +
`novagui`) so a font change reflows every screen:

| Token     | Meaning                              |
|-----------|--------------------------------------|
| `_FH`     | glyph height (px)                    |
| `_ADV`    | glyph advance — px per character cell |
| `_BARH`   | status-bar height                    |
| `_TOP`    | `_BARH + 2` — where the body starts  |
| `_ROWH`   | `_FH + 2` — one list row              |

Derived rules: a list shows `(_TOP..h) / _ROWH` rows; **reserve one `_FH` row at the
bottom for the control hint**; text width in chars is `w // _ADV`. Truncate to fit —
never overflow the 128 px.

## The status bar

The top `_BARH` px is owned by `NovaUI`, not the screen — it shows WiFi / time / battery
/ notification / saving state globally. **Screens draw only from `_TOP` down.** Don't
paint over the bar.

## Interaction model — the four gestures

The event vocabulary is `novainput` (`ev.ROT_CW`, `ev.ROT_CCW`, `ev.SELECT`, `ev.HOME`,
`ev.BACK`). Meanings are **fixed across the whole UI** — consistency is how a user learns
the device:

| Gesture           | Universal meaning                                             |
|-------------------|--------------------------------------------------------------|
| **Turn** (CW/CCW) | Move selection / adjust the focused value. Never destructive. |
| **SELECT**        | Activate the thing under the cursor (open / toggle / confirm). |
| **HOME**          | Go to the home screen. In an editor/manager: grab-to-edit.    |
| **BACK**          | Up one level / cancel. Returns `'back'`/the event from `on_event`. |

Corollary: **BACK must always work and always mean "back."** A screen that traps the user
is a bug. HOME is the escape hatch to the app grid.

## The Screen protocol

Every screen implements three methods (see `novagui.Screen`):

- `draw(c)` — paint the body from `_TOP` down onto the canvas `c`.
- `tick(dt_ms) -> bool` — advance time; return `True` **only** when something changed and
  a redraw is needed (a still screen returns `False` — this is what keeps the shared
  event loop free for background services). Redraw on the *event you care about*, e.g. a
  clock redraws when the second changes, not every frame.
- `on_event(e) -> None | 'back' | e` — handle a gesture. Return `None` to stay,
  `'back'`/the event to pop.

## Screen archetypes

Reuse these — don't invent a new list widget:

- **Menu / list** (`Menu`) — a vertical list; turn moves a `>` cursor, SELECT activates.
  Use for choices and browsers.
- **Icon gallery** (`IconGallery`) — a ring of icons; the home style. Use for peer apps.
- **Folders** (`_build_folder_home`) — icons grouped by category; the default home.
- **Button grid** (`ButtonGridScreen`) — a labelled action grid for script-apps.
- **Full-screen app** — a live view (Clock, Battery, Environment): big value + a control
  hint, `tick` refreshes on change.
- **Panel / settings** (`SettingsScreen`) — labelled rows of toggles/values; turn to move,
  SELECT to change.
- **Confirm** — a yes/no gate before anything destructive (wipe, forget, factory).

## Visual conventions

- **Selection = inversion.** The focused row is a filled bar (`fill_rect`) with inverted
  (colour-0) text. One selection indicator only.
- **Cursor glyph `>`** on the selected row; **`=`** when that row is *grabbed* for editing
  (manager reorder). Same glyphs everywhere.
- **Scroll affordance.** When a list overflows, draw the up/down triangles (`_scroll_tri`)
  so the user knows there's more. If nothing is off-screen, draw nothing.
- **Control hint footer.** The bottom `_FH` row states the non-obvious controls for the
  current mode, e.g. `SEL on/off  HOME edit`. It changes with mode.
- **Big values** use the canvas text scale (`c.text(x, y, s, 1, 2)`), centred.

## Iconography

Icons are 1-bit bitmaps in `novaicons`, one per app/category, drawn at a fixed box. A new
app should reuse an existing icon that reads at 16-ish px before adding a new one — a
blurry custom glyph is worse than a clear shared one. Categories borrow an app icon
(`_CAT_ICON`) so folders look distinct.

## Motion

- **Boot:** the splash (`novasplash`) plays once per boot, over the real boot work, then
  pops to home — it must never *add* boot time.
- **In-app:** only the thing that changed redraws (see `tick`). No idle animation, no
  full-screen clears per frame (they flicker at speed) — redraw the row that changed.

## Writing a kind:py app (installable full-UI apps)

The app store carries two kinds: **`buttons`** (a button-grid remote — a `.txt` of
`Label = action` lines) and **`py`** (a full Nova-UI app). A kind:py app is a `.py` that
binds only to the **stable surface** — never to `novagui` internals — so it keeps working
as the UI is refactored. The loader (`novaapps.load_py_app`) injects into its namespace:

- `ui` — the `novaui` leaf: `ui.Screen`, `ui.Menu`, the layout tokens (`ui._TOP`,
  `ui._ROWH`, `ui._ADV`, `ui._FH`), `ui._wrap`, `ui._scroll_tri`.
- `ev` — input events (`ev.SELECT`, `ev.BACK`, …).
- `nova` — the scripting API (`nova.ir_send`, `nova.lora_send`, `nova.notify`, …).

Contract: define **`def app():`** returning a `Screen`; optional module-level **`TITLE`**
(home label) and **`CATEGORY`** (home folder). Minimal example:

```python
TITLE = 'Hello'
CATEGORY = 'Tools'

class Hello(ui.Screen):
    def draw(self, c):
        c.text(4, ui._TOP, 'Hello, Nova!', 1)
        c.text(4, c.h - ui._FH, 'BACK = exit', 1)
    def on_event(self, e):
        return e if e in (ev.BACK, ev.HOME) else None

def app():
    return Hello()
```

Installing puts it in the `pyapps` store; it then appears on the home in its `CATEGORY`.
See `repo/novad1-apps/dice/` for a working example. **Security:** installing an app RUNS
its code (it is `exec`'d) — the same trust posture as any script you install. MicroPython
cannot sandbox this; install apps you trust.

## Anti-patterns (the "vibe-coded" tells to avoid)

- Hard-coded pixel coordinates instead of the layout tokens.
- A screen with no control-hint footer.
- Re-implementing a list/menu instead of using `Menu`.
- Overloading a gesture to mean different things on different screens.
- Redrawing every frame when nothing changed (starves background services).
- Cramming four metrics where one clear value would do.
