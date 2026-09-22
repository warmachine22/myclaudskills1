#!/usr/bin/env python3
"""Read downloaded investor PDFs — including the pages text extraction can't see.

Investor and roadshow decks are text-native. Keynote decks (GTC, CES, AGM) are
exported with type baked into images, so `get_text()` returns nothing for
roughly half their pages while the slide is dense with information. This tool
finds those pages and renders them so they can actually be looked at.

    decks.py audit  DIR|PDF...            which pages have no extractable text
    decks.py text   DIR|PDF... -o OUT     extract text, one .txt per PDF
    decks.py sheets DIR|PDF... -o OUT     6-up contact sheets for visual scanning
    decks.py page   PDF N [N...] -o OUT   single pages at full resolution

Requires PyMuPDF (rendering) and Pillow (contact sheets only); the rest of this
skill is stdlib-only. `pip install pymupdf pillow`
"""

import argparse
import os
import sys

THIN = 60          # chars below which a page is treated as text-invisible
THUMB_W = 820      # px per page in a contact sheet
FULL_W = 1700      # px for a full-resolution single page
COLS, ROWS = 3, 2  # contact sheet grid


def _need(mod):
    """Import a module by name, or exit with an actionable message."""
    try:
        return __import__(mod, fromlist=["_"]) if "." in mod else __import__(mod)
    except ImportError:
        pkg = {"fitz": "pymupdf", "PIL": "pillow"}.get(mod.split(".")[0], mod)
        sys.exit(f"error: {mod} not available. `pip install {pkg}`")


def collect(paths):
    """Expand directories to the PDFs inside them; keep explicit files as given."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            out += [os.path.join(p, f) for f in sorted(os.listdir(p))
                    if f.lower().endswith(".pdf")]
        elif p.lower().endswith(".pdf"):
            out.append(p)
    if not out:
        sys.exit("error: no PDFs found in " + ", ".join(paths))
    return out


def cmd_audit(files):
    fitz = _need("fitz")
    worst = []
    for f in files:
        doc = fitz.open(f)
        thin = [i + 1 for i, pg in enumerate(doc) if len(pg.get_text().strip()) < THIN]
        pct = 100 * len(thin) // doc.page_count if doc.page_count else 0
        worst.append((pct, os.path.basename(f)))
        shown = ", ".join(map(str, thin[:24])) + (" …" if len(thin) > 24 else "")
        print(f"{os.path.basename(f)[:52]:54s} {doc.page_count:3d}pp  "
              f"invisible {len(thin):3d} ({pct:2d}%)  {shown}")
        doc.close()
    hi = [n for p, n in worst if p >= 30]
    if hi:
        print(f"\n{len(hi)} deck(s) over 30% invisible to text — render and view these:")
        for n in hi:
            print("  " + n)
    else:
        print("\nAll decks scrape cleanly; text extraction is sufficient.")


def cmd_text(files, out):
    fitz = _need("fitz")
    os.makedirs(out, exist_ok=True)
    for f in files:
        doc = fitz.open(f)
        body = "\n\n".join(f"--- page {i} ---\n{pg.get_text().strip()}"
                           for i, pg in enumerate(doc, 1))
        dest = os.path.join(out, os.path.basename(f)[:-4] + ".txt")
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(body)
        print(f"{os.path.basename(f)[:52]:54s} {doc.page_count:3d}pp -> {dest}")
        doc.close()


def _render(page, width):
    fitz = _need("fitz")
    z = width / page.rect.width
    return page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)


def cmd_sheets(files, out):
    fitz, Image = _need("fitz"), _need("PIL.Image")
    os.makedirs(out, exist_ok=True)
    per = COLS * ROWS
    for f in files:
        doc = fitz.open(f)
        imgs = []
        for pg in doc:
            px = _render(pg, THUMB_W)
            imgs.append(Image.frombytes("RGB", (px.width, px.height), px.samples))
        doc.close()
        if not imgs:
            continue
        tw, th = max(i.width for i in imgs), max(i.height for i in imgs)
        pad = 10
        slug = os.path.basename(f)[:-4]
        n = (len(imgs) + per - 1) // per
        for s in range(n):
            chunk = imgs[s * per:(s + 1) * per]
            cols = min(COLS, len(chunk))
            rows = (len(chunk) + COLS - 1) // COLS
            sheet = Image.new("RGB", (cols * tw + (cols + 1) * pad,
                                      rows * th + (rows + 1) * pad), (26, 26, 28))
            for i, im in enumerate(chunk):
                r, c = divmod(i, COLS)
                sheet.paste(im, (pad + c * (tw + pad), pad + r * (th + pad)))
            lo, hi = s * per + 1, min((s + 1) * per, len(imgs))
            sheet.save(os.path.join(out, f"{slug}_sheet{s+1:02d}_p{lo}-{hi}.png"),
                       optimize=True)
        print(f"{slug[:52]:54s} {len(imgs):3d}pp -> {n} sheets in {out}")


def cmd_page(pdf, nums, out):
    fitz = _need("fitz")
    os.makedirs(out, exist_ok=True)
    doc = fitz.open(pdf)
    slug = os.path.basename(pdf)[:-4]
    for n in nums:
        if not 1 <= n <= doc.page_count:
            print(f"skip p{n}: out of range (1-{doc.page_count})")
            continue
        dest = os.path.join(out, f"{slug}_p{n}.png")
        _render(doc[n - 1], FULL_W).save(dest)
        print(dest)
    doc.close()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("audit", "text", "sheets"):
        s = sub.add_parser(name)
        s.add_argument("paths", nargs="+", help="PDF files or a directory of them")
        if name != "audit":
            s.add_argument("-o", "--out", default="deck-" + name)

    s = sub.add_parser("page")
    s.add_argument("pdf")
    s.add_argument("nums", nargs="+", type=int)
    s.add_argument("-o", "--out", default="deck-page")

    a = ap.parse_args()
    if a.cmd == "audit":
        cmd_audit(collect(a.paths))
    elif a.cmd == "text":
        cmd_text(collect(a.paths), a.out)
    elif a.cmd == "sheets":
        cmd_sheets(collect(a.paths), a.out)
    else:
        cmd_page(a.pdf, a.nums, a.out)


if __name__ == "__main__":
    main()
