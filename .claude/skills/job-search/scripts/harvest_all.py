# -*- coding: utf-8 -*-
import json
from jobslib import collect, show

by = json.load(open("boards.json", encoding="utf-8"))
gh = [t for t, _ in by["greenhouse"]]
lv = [t for t, _ in by["lever"]]
ab = [t for t, _ in by["ashby"]]
print("querying %d greenhouse, %d lever, %d ashby boards" % (len(gh), len(lv), len(ab)))

rows = collect(gh=gh, lever=lv, ashby=ab)
json.dump(rows, open("raw_all.json", "w", encoding="utf-8"), indent=1)
show(rows)
