from playwright.sync_api import sync_playwright
import sys

url, out = sys.argv[1], sys.argv[2]
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1100, "height": 1400})
    pg.goto(url, wait_until="networkidle")
    pg.screenshot(path=out, full_page=False)
    print("title:", pg.title())
    print("apply links:", pg.locator("a.apply").count())
    print("job cards:", pg.locator("article.job").count())
    print("body scrollWidth vs clientWidth:",
          pg.evaluate("[document.body.scrollWidth, document.body.clientWidth]"))
    b.close()
