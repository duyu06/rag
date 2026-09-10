from pathlib import Path

path = Path("frontend/src/app/page.tsx")
text = path.read_text(encoding="utf-8")
old = '          {view === "chat" && <ChatPanel selectedKb={selectedKb} bases={bases} />}'
new = '          <div hidden={view !== "chat"}>\n            <ChatPanel selectedKb={selectedKb} bases={bases} />\n          </div>'
if old not in text:
    raise SystemExit("expected ChatPanel conditional mount was not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
print("patched ChatPanel to stay mounted across view switches")
