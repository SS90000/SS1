"""Download regulator source files listed in .github/fetch-list.json into raw/ (one-off backfill helper).
Each entry: {"name": folder, "url": page or file, "follow": optional regex of linked files to also download, "max": optional max linked files}."""
import json, os, re, sys, time, urllib.parse, urllib.request
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 SalishSevenTracker/1.0"
MAXB = 80 * 1024 * 1024
log = []
def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=90) as r:
        data = r.read(MAXB + 1)
        return data, r.headers.get("Content-Type", ""), r.geturl()
def save(folder, url, data):
    os.makedirs(folder, exist_ok=True)
    fn = re.sub(r"[^A-Za-z0-9._-]+", "_", urllib.parse.unquote(urllib.parse.urlparse(url).path.split("/")[-1] or "index"))[:120]
    q = urllib.parse.urlparse(url).query
    if q: fn = fn + "_" + re.sub(r"[^A-Za-z0-9]+", "_", q)[:60]
    if "." not in fn[-6:]: fn += ".html"
    p = os.path.join(folder, fn)
    open(p, "wb").write(data)
    return p
for e in json.load(open(".github/fetch-list.json")):
    folder = os.path.join("raw", e["name"])
    try:
        data, ctype, final = get(e["url"])
        if len(data) > MAXB: log.append(f"SKIP too large {e['url']}"); continue
        p = save(folder, e["url"], data); log.append(f"OK {len(data):>9} {p} <- {e['url']}")
        if e.get("follow"):
            html = data.decode("utf-8", "ignore")
            links = []
            for h in re.findall(r'href=["\']([^"\']+)["\']', html, re.I):
                u = urllib.parse.urljoin(final, h.replace("&amp;", "&"))
                if re.search(e["follow"], u, re.I) and u not in links: links.append(u)
            for u in links[: e.get("max", 40)]:
                time.sleep(1)
                try:
                    d2, _, _ = get(u)
                    if len(d2) > MAXB: log.append(f"SKIP too large {u}"); continue
                    p2 = save(folder, u, d2); log.append(f"OK {len(d2):>9} {p2} <- {u}")
                except Exception as ex:
                    log.append(f"FAIL {u}: {ex}")
    except Exception as ex:
        log.append(f"FAIL {e['url']}: {ex}")
    time.sleep(1)
os.makedirs("raw", exist_ok=True)
open("raw/_log.txt", "w").write("\n".join(log) + "\n")
print("\n".join(log))
