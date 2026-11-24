"""Definition-level diff of Loom programs across pristine upstream, Facthhorium and a candidate.

    python3 tools/defdiff.py PRISTINE_DIR OURS_DIR CANDIDATE_DIR

Each DIR holds control.loom and llm.loom. For every definition Facthhorium changed or added relative to
pristine, reports whether the candidate (e.g. v0.3) still carries Facthhorium's exact version, a different
version (merged: review by hand), or lacks it. Used to prove v0.3 kept every v0.2.1 change.
"""
import re
import sys

TOP = re.compile(r'^(kernel\.def|func\.def|command\.def|func\.decl|template\.(?:def|decl)|global\.[a-z.]+def)\b', re.M)
NAME = re.compile(r'@([A-Za-z0-9_.$]+)\s*[\(\[=]')


def defs(path):
    s = open(path).read()
    out, ms = {}, list(TOP.finditer(s))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(s)
        head = s[m.start():s.find('\n', m.start())]
        names = [n for n in NAME.findall(head) if n not in ('device', 'rdna3', 'rdna4')]
        out[names[0] if names else head[:60]] = s[m.start():end]
    return out


def main(pristine, ours, cand):
    missing = 0
    for f in ('control.loom', 'llm.loom'):
        a, b, c = (defs(f'{d}/{f}') for d in (pristine, ours, cand))
        print(f'== {f}')
        # Added definitions can move blank lines between their neighbors.
        a, b, c = ({k: v.rstrip() for k, v in source.items()} for source in (a, b, c))
        for k in b:
            if k in a and a[k] == b[k]:
                continue
            kind = 'new' if k not in a else 'changed'
            state = 'IDENTICAL' if c.get(k) == b[k] else ('MISSING' if k not in c else 'DIFFERENT (check merge)')
            missing += state == 'MISSING'
            print(f'  {kind:7} {k:32} {state}')
    print('missing:', missing)
    return 1 if missing else 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:4]))
