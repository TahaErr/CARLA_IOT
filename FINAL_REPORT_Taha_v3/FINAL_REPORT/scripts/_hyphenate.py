"""One-shot: make figure filenames hyphenated (underscores break \\includegraphics
on some TeX Live versions). Renames PNGs and updates report.tex + generators
consistently. Leaves .csv inputs untouched."""
import re, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIG = os.path.join(ROOT, "figures")

# 1. rename png files
for f in sorted(os.listdir(FIG)):
    if f.endswith(".png") and "_" in f:
        new = f.replace("_", "-")
        os.rename(os.path.join(FIG, f), os.path.join(FIG, new))
        print("renamed", f, "->", new)

# 2. report.tex : only inside \includegraphics{...}
texp = os.path.join(ROOT, "report.tex")
tex = open(texp, encoding="utf-8").read()
tex = re.sub(r"(\\includegraphics(?:\[[^\]]*\])?\{)([^}]+)(\})",
             lambda m: m.group(1) + m.group(2).replace("_", "-") + m.group(3), tex)
open(texp, "w", encoding="utf-8").write(tex)
print("patched report.tex includegraphics")

# 3. generators : only *.png string literals (keeps *.csv inputs intact)
for s in ("make_figures.py", "make_diagrams.py"):
    p = os.path.join(ROOT, "scripts", s)
    txt = open(p, encoding="utf-8").read()
    txt = re.sub(r"(['\"])([^'\"]*\.png)\1",
                 lambda m: m.group(1) + m.group(2).replace("_", "-") + m.group(1), txt)
    open(p, "w", encoding="utf-8").write(txt)
    print("patched", s)
