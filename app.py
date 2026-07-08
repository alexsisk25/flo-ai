"""Walnut menu bar app — ties together hotkeys, dashboard server, and menus."""

import threading
import webbrowser
from pathlib import Path

import rumps

import core
import overlay
import server
import store

STATIC = Path(__file__).resolve().parent / "static"
ICON_IDLE = str(STATIC / "squirrel.png")
ICON_REC = str(STATIC / "squirrel-rec.png")
ICON_BUSY = str(STATIC / "squirrel-busy.png")


class WalnutApp(rumps.App):
    def __init__(self):
        super().__init__("Walnut", icon=ICON_IDLE, template=True,
                         quit_button="Quit Walnut")
        store.init()
        self.overlay = overlay.Overlay()
        self.core = core.Core()
        self.core.on_state = self.set_state
        self.core.on_level = self.overlay.set_level
        self.hotkeys = core.HotkeyManager(self.core)
        server.CORE = self.core
        server.HOTKEYS = self.hotkeys
        self.port = int(store.get("port"))

        speak = store.get("hotkey_speak")
        dictate = store.get("hotkey_dictate")
        self.menu = [
            rumps.MenuItem("Open Walnut Dashboard", callback=self.open_dashboard),
            None,
            rumps.MenuItem(f"Start/Stop Dictation   {pretty(dictate)}",
                           callback=self.menu_dictate),
            rumps.MenuItem(f"Narrate Selection   {pretty(speak)}",
                           callback=self.menu_speak),
            rumps.MenuItem("Stop Narration", callback=self.menu_stop),
            None,
        ]

        threading.Thread(target=self.core.warm_up, daemon=True).start()
        threading.Thread(target=server.run, args=(self.port,),
                         daemon=True).start()
        self.hotkeys.start()
        core.log(f"Walnut menu bar app running — dashboard at "
                 f"http://127.0.0.1:{self.port}")

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

    def menu_dictate(self, _):
        threading.Thread(target=self.core.toggle_dictate, daemon=True).start()

    def menu_speak(self, _):
        threading.Thread(target=self.core.toggle_speak, daemon=True).start()

    def menu_stop(self, _):
        self.core.stop_speech()


def pretty(hotkey: str) -> str:
    return (hotkey.replace("<ctrl>", "⌃").replace("<alt>", "⌥")
            .replace("<cmd>", "⌘").replace("<shift>", "⇧")
            .replace("<space>", "␣").replace("+", "").upper())


if __name__ == "__main__":
    WalnutApp().run()
