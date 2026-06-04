"""Quick static checks for report.tex (run before Overleaf compile)."""
import re, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
tex = open(os.path.join(ROOT, "report.tex"), encoding="utf-8").read()
bib = open(os.path.join(ROOT, "references.bib"), encoding="utf-8").read()

labels = set(re.findall(r"\\label\{([^}]+)\}", tex))
refs = set(re.findall(r"\\ref\{([^}]+)\}", tex))
print("REFS without LABEL (would be ??):", sorted(refs - labels) or "NONE -- OK")
print("LABELS never referenced:", sorted(labels - refs) or "none")

bibkeys = set(re.findall(r"@\w+\{([^,]+),", bib))
cites = set()
for grp in re.findall(r"\\cite\{([^}]+)\}", tex):
    for k in grp.split(","):
        cites.add(k.strip())
print("CITES without BIB entry (would be [?]):", sorted(cites - bibkeys) or "NONE -- OK")
print("BIB entries uncited (harmless):", sorted(bibkeys - cites) or "none")

imgs = re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", tex)
miss = [i for i in imgs if not os.path.exists(os.path.join(ROOT, "figures", os.path.basename(i)))]
print("IMAGES referenced:", len(imgs), "| MISSING:", miss or "NONE -- OK")

envs = collections.Counter()
for b in re.findall(r"\\begin\{([^}]+)\}", tex):
    envs[b] += 1
for e in re.findall(r"\\end\{([^}]+)\}", tex):
    envs[e] -= 1
unbal = {k: v for k, v in envs.items() if v != 0}
print("UNBALANCED environments:", unbal or "NONE -- OK")

print("BRACE balance (open-close, should be 0):", tex.count("{") - tex.count("}"))
print("has begin/end document:", r"\begin{document}" in tex, r"\end{document}" in tex)
print("figures:", tex.count(r"\begin{figure}"), "| tables:", tex.count(r"\begin{table}"))

# tabular column-count sanity: count & per row vs column spec
# (handles nested-brace column types like p{0.29\linewidth})
def _count_cols(spec):
    prev = None
    while prev != spec:                       # strip nested {...} arg groups
        prev = spec
        spec = re.sub(r"\{[^{}]*\}", "", spec)
    return len(re.findall(r"[lcrpmbX]", spec))

i = 0
while True:
    k = tex.find(r"\begin{tabular}", i)
    if k < 0:
        break
    b = tex.index("{", k + len(r"\begin{tabular}"))
    depth, p = 0, b
    while p < len(tex):                        # balance-match the spec braces
        if tex[p] == "{":
            depth += 1
        elif tex[p] == "}":
            depth -= 1
            if depth == 0:
                break
        p += 1
    spec = tex[b + 1:p]
    end = tex.find(r"\end{tabular}", p)
    body = tex[p + 1:end]
    ncol = _count_cols(spec)
    rows = [r for r in body.split(r"\\") if "&" in r]
    bad = [n for n, r in enumerate(rows) if r.count("&") + 1 != ncol]
    tag = "OK" if not bad else f"CHECK rows {bad} (spec={ncol} cols)"
    print(f"tabular cols={ncol}: {tag}  [{spec.strip()[:40]}]")
    i = end + 1
