import re, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
t = open(os.path.join(ROOT, "report.tex"), encoding="utf-8").read()
lines = t.split("\n")

print("DOLLAR signs even:", t.count("$") % 2 == 0, f"({t.count(chr(36))})")

# raw % (literal, not escaped, not a comment line)
bad_pct = [i + 1 for i, l in enumerate(lines)
           if re.search(r"(?<!\\)%", l) and not l.lstrip().startswith("%")]
print("raw % (non-comment):", bad_pct or "NONE OK")

# raw underscore not escaped
us = [(i + 1, lines[i].strip()[:70]) for i in range(len(lines))
      if re.search(r"(?<!\\)_", lines[i])]
print("raw underscore lines:", us or "NONE OK")

# raw & outside tabular
intab = False
bad_amp = []
for i, l in enumerate(lines):
    if "begin{tabular}" in l:
        intab = True
    if not intab and re.search(r"(?<!\\)&", l):
        bad_amp.append(i + 1)
    if "end{tabular}" in l:
        intab = False
print("raw & outside tabular:", bad_amp or "NONE OK")

# raw # not escaped
hsh = [i + 1 for i, l in enumerate(lines) if re.search(r"(?<!\\)#", l)]
print("raw # :", hsh or "NONE OK")
