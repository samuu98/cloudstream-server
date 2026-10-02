"""Add the bridge startup hook to MainActivity, failing if the upstream ABI changes."""
import pathlib
import re
import sys

root = pathlib.Path(sys.argv[1])
matches = list(root.glob("smali*/com/lagradost/cloudstream3/MainActivity.smali"))
if len(matches) != 1:
    raise SystemExit("Expected exactly one CloudStream MainActivity")
path = matches[0]
source = path.read_text()
pattern = r"(?ms)(^\.method [^\n]* onCreate\(Landroid/os/Bundle;\)V\n)(.*?)(^\.end method)"
match = re.search(pattern, source)
if not match or "return-void" not in match[2]:
    raise SystemExit("MainActivity.onCreate ABI changed")
hook = "invoke-static/range {p0 .. p0}, Lit/zerotituli/server/ServerBridge;->start(Landroid/app/Activity;)V\n\n    return-void"
body = match[2].replace("return-void", hook)
source = source[:match.start()] + match[1] + body + match[3] + source[match.end():]
path.write_text(source)
print("Patched", path)
