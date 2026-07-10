"""Walnut menu bar app — ties together hotkeys, dashboard server, and menus."""

import threading
import webbrowser
from pathlib import Path

import rumps

import console_bridge
import core
import overlay
import permissions
import server
import store

STATIC = Path(__file__).resolve().parent / "static"
ICON_IDLE = str(STATIC / "squirrel.png")
ICON_REC = str(STATIC / "squirrel-rec.png")
ICON_BUSY = str(STATIC / "squirrel-busy.png")


def build_menu(trusted: bool, speak: str, dictate: str, command: str,
               handlers: dict) -> list:
    """The menu bar, as a plain list, assembled before rumps ever sees it.

    This used to be built by assigning `self.menu` and then calling
    `self.menu.insert(0, …)` when Accessibility was missing. `rumps.Menu` is an
    OrderedDict subclass with no `insert`, so that raised AttributeError inside
    __init__ — on first launch, for every user who hadn't granted the
    permission yet, i.e. all of them. launchd then respawned the corpse forever.

    Kept module-level and GUI-free so both branches are testable without a
    menu bar. `None` becomes a separator.
    """
    items = []
    # The hotkeys are dead without Accessibility, and pynput won't say so.
    # Put the truth where someone looks when nothing happens: the top of the menu.
    if not trusted:
        items += [rumps.MenuItem("⚠️  Grant Accessibility Permission",
                                 callback=handlers["fix_permissions"]),
                  None]
    items += [
        rumps.MenuItem("Open Walnut Dashboard",
                       callback=handlers["open_dashboard"]),
        None,
        rumps.MenuItem(f"Start/Stop Dictation   {pretty(dictate)}",
                       callback=handlers["menu_dictate"]),
        rumps.MenuItem(f"Narrate Selection   {pretty(speak)}",
                       callback=handlers["menu_speak"]),
        rumps.MenuItem(f"Console Command   {pretty(command)}",
                       callback=handlers["menu_command"]),
        rumps.MenuItem("Stop Narration", callback=handlers["menu_stop"]),
        None,
    ]
    return items


class WalnutApp(rumps.App):
    def __init__(self):
        super().__init__("Walnut", icon=ICON_IDLE, template=True,
                         quit_button="Quit Walnut")
        permissions.request_microphone()   # triggers TCC prompt for mic on first run
        store.init()
        # Apply the cap to whatever accumulated while an older build ran.
        pruned = store.prune_recordings()
        if pruned:
            core.log(f"Pruned {pruned} old recording(s); "
                     f"keeping the newest {store.get_valid('recordings_keep')}.")
        self.overlay = overlay.Overlay()
        self.core = core.Core()
        self.core.on_state = self.set_state
        self.core.on_level = self.overlay.set_level
        self.core.on_command = self.run_console_command
        self.hotkeys = core.HotkeyManager(self.core)
        server.CORE = self.core
        server.HOTKEYS = self.hotkeys
        self.port = int(store.get_valid("port"))

        # Two Walnuts fight over the port AND the hotkeys, and the loser's
        # symptoms are baffling. Refuse to be the second one.
        if server.port_in_use(self.port):
            core.log(f"Walnut is already running at http://127.0.0.1:{self.port}")
            webbrowser.open(f"http://127.0.0.1:{self.port}")
            raise SystemExit(0)

        speak = store.get_valid("hotkey_speak")
        dictate = store.get_valid("hotkey_dictate")
        command = store.get_valid("hotkey_command")
        trusted = permissions.accessibility_trusted()
        self.menu = build_menu(trusted, speak, dictate, command, {
            "fix_permissions": self.fix_permissions,
            "open_dashboard": self.open_dashboard,
            "menu_dictate": self.menu_dictate,
            "menu_speak": self.menu_speak,
            "menu_command": self.menu_command,
            "menu_stop": self.menu_stop,
        })
        if not trusted:
            core.log("Accessibility permission missing — hotkeys will not fire.")
            permissions.request_accessibility()   # shows the system dialog once

        threading.Thread(target=self._guarded, args=(self.core.warm_up,),
                         daemon=True).start()
        threading.Thread(target=self._guarded, args=(server.run, self.port),
                         daemon=True).start()
        self.hotkeys.start()   # never raises; falls back to defaults
        core.log(f"Walnut menu bar app running — dashboard at "
                 f"http://127.0.0.1:{self.port}")

    @staticmethod
    def _guarded(fn, *args) -> None:
        """Run a background task so its failure is logged, not swallowed.

        A daemon thread that raises just disappears; the model would fail to
        load or the dashboard would never bind and Walnut looked fine.
        """
        try:
            fn(*args)
        except Exception as e:
            core.log(f"{fn.__name__} failed: {type(e).__name__}: {e}")

    def set_state(self, state: str) -> None:
        try:
            self.icon = {"recording": ICON_REC, "busy": ICON_BUSY}.get(
                state, ICON_IDLE)
            if state == "recording":
                self.overlay.show()
            else:
                self.overlay.hide()
        except Exception:
            pass

    def open_dashboard(self, _):
        webbrowser.open(f"http://127.0.0.1:{self.port}")

    def fix_permissions(self, _):
        permissions.open_accessibility_settings()
        rumps.alert(
            title="Grant Accessibility to Walnut",
            message="Add Walnut (or the terminal you launched it from) under "
                    "Privacy & Security → Accessibility, then quit and reopen "
                    "Walnut.\n\nWithout it, the hotkeys register but never fire.")

    def menu_dictate(self, _):
        threading.Thread(target=self.core.toggle_dictate, daemon=True).start()

    def menu_speak(self, _):
        threading.Thread(target=self.core.toggle_speak, daemon=True).start()

    def menu_command(self, _):
        threading.Thread(target=self.core.toggle_command, daemon=True).start()

    def menu_stop(self, _):
        self.core.stop_all()   # narration and replayed recordings alike

    def run_console_command(self, text: str) -> None:
        console_bridge.handle(
            text, lambda t: self.core.speak(t, record_history=False))


def pretty(hotkey: str) -> str:
    return (hotkey.replace("<ctrl>", "⌃").replace("<alt>", "⌥")
            .replace("<cmd>", "⌘").replace("<shift>", "⇧")
            .replace("<space>", "␣").replace("+", "").upper())


if __name__ == "__main__":
    WalnutApp().run()
