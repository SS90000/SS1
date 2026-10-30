"""Daily collector for the Salish Seven Drug Tracker.

Downloads the regulators' own bulk files and pages, then writes:
  sources/proposals.json  - ready-made records for new approvals, read straight from the
                            regulator's file (EU, UK, Taiwan, Brazil), for the update agent to check and add
  sources/pages/*         - pages for the update agent to read itself (Japan, Switzerland, India)
  sources/log.txt         - what was downloaded or failed
Nothing here edits data.json.

Usage:  python3 .github/collect.py            (download from the regulators)
        python3 .github/collect.py --raw DIR  (use files saved earlier in DIR, for testing)
"""
import csv, io, json, os, re, sys, time, urllib.parse, urllib.request, zipfile, datetime

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 SalishSevenTracker/1.0"
OUT = "sources"
RAW = sys.argv[sys.argv.index("--raw") + 1] if "--raw" in sys.argv else None
YEAR = str(datetime.date.today().year) if not os.environ.get("TRACKER_YEAR") else os.environ["TRACKER_YEAR"]
TODAY = datetime.date.today().isoformat()
log = []

# ---------- names: same rules as data.json ----------
SALTS = r"\s+(hydrochloride|dihydrochloride|sodium|disodium|calcium|potassium|phosphate|hydrobromide|tosylate|adipate|camsylate|mesylate|mesilate|besylate|besilate|hydrate|monohydrate|dihydrate|sesquihydrate|meglumine|hemifumarate|hemicalcium|fumarate|maleate|succinate|tartrate|citrate|sulfate|sulphate|acetate|bromide|chloride|malate|lactate)$"
def key(inn):
    inn = (inn or "").lower().strip()
    p = inn.split("-")
    if len(p) > 1 and len(p[-1]) == 4 and p[-1].isalpha(): inn = "-".join(p[:-1])
    prev = None
    while prev != inn:
        prev = inn; inn = re.sub(SALTS, "", inn).strip()
    return inn
OLD = {"denosumab","ranibizumab","pegfilgrastim","filgrastim","ustekinumab","aflibercept","pertuzumab","trastuzumab","bevacizumab","omalizumab","etanercept","tocilizumab","teriparatide","insulin lispro","insulin aspart","eculizumab","secukinumab","golimumab","nivolumab","levodopa and carbidopa","semaglutide","minoxidil","leuprorelin","human normal immunoglobulin","diazepam","dalteparin","nirmatrelvir and ritonavir","flurbiprofen","icatibant","lanadelumab","risdiplam","selpercatinib","sotorasib","pancreas powder","tranylcypromine","bcg (intravesical)","indocyanine green","luspatercept","alpelisib","onasemnogene abeparvovec","lurbinectedin","estetrol","influenza vaccine","tdap vaccine","pirtobrutinib","vosoritide","anifrolumab","belantamab mafodotin","zolbetuximab","teprotumumab","ivosidenib","odevixibat","motixafortide","mirogabalin"}
def innovative(x):
    if x["inn"] in OLD: return False
    for r in x["records"]:
        t = (r.get("type") or "").lower()
        if r["country"] == "US" and "novel" in t: return True
        if r["country"] == "CA" and "new active substance" in t: return True
        if r["country"] in ("CH", "JP", "CN", "KR"): return True
        if r["country"] == "EU" and "biosimilar" not in t: return True
        if r["country"] == "AU" and ("new chemical" in t or "new biological" in t or "nce" in t or "nbe" in t): return True
        if r["country"] == "US" and r["status"] == "Under review" and "new indication" not in t: return True
    return False

data = json.load(open("data.json"))
DRUGS = {x["inn"]: x for x in data["drugs"]}
INNO = {k for k, x in DRUGS.items() if innovative(x)}
SKIP = {(x["country"], key(x["inn"])) for x in data.get("skipped", [])}
def has(k, country): return (country, k) in SKIP or (k in DRUGS and any(r["country"] == country for r in DRUGS[k]["records"]))
dmy = lambda s: f"{s[6:10]}-{s[3:5]}-{s[0:2]}"
title = lambda s: " ".join(w.capitalize() if w.isupper() and len(w) > 2 else w for w in (s or "").split())
proposals = []
def propose(country, inn, brand, sponsor, rec, action="add", note=None):
    if action == "add" and (country, key(inn)) in SKIP: return
    for f in ("submitted", "decision", "opinion", "expected", "indication"): rec.setdefault(f, None)
    rec.update(country=country, checked=TODAY)
    proposals.append({"action": action, "inn": key(inn), "brand": brand, "sponsor": sponsor, "record": rec, "note": note})

# ---------- downloading ----------
def get(url, name=None):
    """Return bytes for url (or the saved copy named `name` under --raw)."""
    if RAW:
        p = os.path.join(RAW, name or "")
        if name and os.path.exists(p):
            return open(p, "rb").read()
        raise FileNotFoundError(f"not in --raw folder: {name}")
    last = None
    for attempt in range(2):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except Exception as ex:
            last = ex; time.sleep(5)
    raise last
def save_page(name, url, raw_name=None):
    os.makedirs(os.path.join(OUT, "pages"), exist_ok=True)
    try:
        b = get(url, raw_name)
        open(os.path.join(OUT, "pages", name), "wb").write(b)
        log.append(f"OK   page {name} ({len(b)} bytes) <- {url}")
        return b
    except Exception as ex:
        log.append(f"FAIL page {name} <- {url}: {ex}")
def step(label, fn):
    try:
        n0 = len(proposals); fn(); log.append(f"OK   {label}: {len(proposals) - n0} proposals")
    except Exception as ex:
        log.append(f"FAIL {label}: {type(ex).__name__}: {ex}")

# ---------- EU: EMA medicines spreadsheet ----------
def eu():
    import openpyxl
    b = get("https://www.ema.europa.eu/en/documents/report/medicines-output-medicines-report_en.xlsx", "ema/medicines-output-medicines-report_en.xlsx")
    ws = openpyxl.load_workbook(io.BytesIO(b), read_only=True).active
    rows = list(ws.iter_rows(values_only=True))
    hi = next(i for i, r in enumerate(rows) if r and r[0] == "Category")
    h = [str(c).strip() if c else "" for c in rows[hi]]
    by_url = {r["source"]: (x, r) for x in data["drugs"] for r in x["records"] if r["country"] == "EU"}
    for row in rows[hi + 1:]:
        r = dict(zip(h, ["" if v is None else str(v).strip() for v in row]))
        if r.get("Category") != "Human" or r.get("Generic") == "Yes": continue
        st, op, ma, url = r["Medicine status"], r["Opinion adopted date"], r["Marketing authorisation date"], r["Medicine URL"]
        if st == "Authorised" and not ma.endswith(YEAR): continue
        if st == "Opinion" and not op.endswith(YEAR): continue
        if st not in ("Authorised", "Opinion"): continue
        inn = (r["International non-proprietary name (INN) / common name"] or r["Active substance"]).replace(";", " and ")
        tags = [t for t, c in (("orphan", "Orphan medicine"), ("biosimilar", "Biosimilar"), ("conditional", "Conditional approval"),
                ("exceptional circumstances", "Exceptional circumstances"), ("PRIME", "PRIME: priority medicine"),
                ("accelerated assessment", "Accelerated assessment"), ("advanced therapy", "Advanced therapy")) if r.get(c) == "Yes"]
        rec = {"regulator": "EMA / European Commission", "status": "Approved" if st == "Authorised" else "Recommended",
               "opinion": dmy(op) if op else None, "decision": dmy(ma) if st == "Authorised" else None,
               "type": ("European Commission marketing authorisation" if st == "Authorised" else "CHMP positive opinion · European Commission decision pending") + "".join(" · " + t for t in tags),
               "indication": (r["Therapeutic area (MeSH)"] or "").replace(";", "; ") or None,
               "source": url, "sourceName": f"EMA medicine page: {r['Name of medicine']}", "confidence": "regulator"}
        if url in by_url:
            x, old = by_url[url]
            if old["status"] == "Recommended" and st == "Authorised":
                propose("EU", x["inn"], None, None, {"status": "Approved", "decision": rec["decision"], "type": rec["type"], "source": url},
                        action="update", note="EU: Commission decision now issued; change this existing EU record to Approved with this decision date")
            continue
        propose("EU", inn, r["Name of medicine"], r["Marketing authorisation developer / applicant / holder"] or None, rec,
                note="EU: new in EMA's medicines data" + ("" if "biosimilar" not in tags else " (biosimilar: skip unless the reference product is tracked)"))

# ---------- UK: MHRA fortnightly lists of licences granted ----------
def uk():
    import pdfplumber
    page_url = f"https://www.gov.uk/government/publications/marketing-authorisations-granted-in-{YEAR}"
    html = get(page_url, f"mhra/marketing-authorisations-granted-in-{YEAR}.html").decode("utf-8", "ignore")
    pdfs = []
    for hft in re.findall(r'href="([^"]+\.pdf)"', html):
        u = urllib.parse.urljoin(page_url, hft)
        if u not in pdfs: pdfs.append(u)
    best = {}
    for u in pdfs:
        fn = urllib.parse.unquote(u.split("/")[-1])
        try: b = get(u, "mhra/" + fn)
        except Exception as ex: log.append(f"FAIL UK pdf {fn}: {ex}"); continue
        with pdfplumber.open(io.BytesIO(b)) as pdf:
            for pg in pdf.pages:
                for t in pg.extract_tables():
                    for row in t:
                        if not row or not row[0] or not row[0].startswith(("PL", "PLGB", "PLNI")) or len(row) < 5: continue
                        pl, date, holder, name, ing = (c or "" for c in row[:5])
                        if not re.match(r"\d\d/\d\d/\d{4}", date): continue
                        k = key(ing.replace("\n", " "))
                        if k in INNO and not has(k, "UK") and (k not in best or dmy(date) < dmy(best[k][1])):
                            best[k] = (pl, date, holder, name, fn)
    for k, (pl, date, holder, name, fn) in best.items():
        propose("UK", k, title(re.split(r"\s\d", name)[0]), title(holder),
                {"regulator": "MHRA", "status": "Approved", "decision": dmy(date), "type": f"UK marketing authorisation granted ({pl})",
                 "source": page_url, "sourceName": f"MHRA: Marketing authorisations granted in {YEAR} (" + fn.replace("Marketing_authorisations_granted_", "").replace(".pdf", "").replace("_", " ") + ")",
                 "confidence": "regulator"}, note="UK: first licence this year for a drug already tracked as new elsewhere")

# ---------- Taiwan: TFDA open data (all drug licences) ----------
def tw():
    b = get("https://data.fda.gov.tw/data/opendata/export/36/csv", "tw/csv.html")
    if b[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(b)); b = z.read([n for n in z.namelist() if n.endswith(".csv")][0])
    best = {}
    for r in csv.DictReader(io.StringIO(b.decode("utf-8-sig"))):
        if not r["發證日期"].startswith(YEAR): continue
        for p in re.split(r";;|;|,", r["主成分略述"]):
            k = key(re.sub(r"\(.*?\)", "", p))
            if k in INNO and not has(k, "TW") and (k not in best or r["發證日期"] < best[k]["發證日期"]): best[k] = r
    for k, r in best.items():
        propose("TW", k, re.split(r"\s\d|\s(solution|film|powder|tablet|concentrate|injection|capsule)", r["英文品名"], flags=re.I)[0].strip().title(), None,
                {"regulator": "Taiwan FDA", "status": "Approved", "decision": r["發證日期"].replace("/", "-"),
                 "type": f"Drug licence issued ({r['許可證字號']})", "source": "https://data.gov.tw/en/datasets/9122",
                 "sourceName": "Taiwan FDA open data: all drug product approvals", "confidence": "regulator"},
                note="TW: first licence this year for a drug already tracked as new elsewhere")

# ---------- Brazil: ANVISA open data (registered medicines) ----------
def pt2en(s):
    s = s.lower().strip()
    s = re.sub(r"^(cloridrato|mesilato|maleato|fumarato|succinato|tosilato|besilato|dicloridrato|bromidrato|sulfato|fosfato|citrato|acetato) de ", "", s)
    s = re.sub(r"\s+(sódica|sódico|dissódico|potássica|potássico|cálcica|cálcico|hidratad[oa]|monoidratad[oa]|di-?hidratad[oa])$", "", s)
    for a, b2 in (("mabe$", "mab"), ("ibe$", "ib"), ("ina$", "in"), ("ana$", "an"), ("cepte$", "cept"), ("ida$", "ide"), ("ato$", "at")):
        s = re.sub(a, b2, s)
    return s
def br():
    b = get("https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv", "br/DADOS_ABERTOS_MEDICAMENTOS.csv")
    best = {}
    for r in csv.DictReader(io.StringIO(b.decode("latin1")), delimiter=";"):
        dt = r["DATA_FINALIZACAO_PROCESSO"]
        if not dt.endswith(YEAR) or r["CATEGORIA_REGULATORIA"] not in ("Novo", "Biológico"): continue
        k = pt2en(r["PRINCIPIO_ATIVO"])
        if k in INNO and not has(k, "BR") and (k not in best or dmy(dt) < dmy(best[k]["DATA_FINALIZACAO_PROCESSO"])): best[k] = r
    for k, r in best.items():
        propose("BR", k, r["NOME_PRODUTO"].replace("®", "").title(), title(r["EMPRESA_DETENTORA_REGISTRO"].split(" - ", 1)[-1]),
                {"regulator": "ANVISA", "status": "Approved", "decision": dmy(r["DATA_FINALIZACAO_PROCESSO"]),
                 "type": f"ANVISA registration ({'new drug' if r['CATEGORIA_REGULATORIA'] == 'Novo' else 'biological product'}; registration no. {r['NUMERO_REGISTRO_PRODUTO']}) · date the registration process was completed",
                 "source": "https://dados.anvisa.gov.br/dados/DADOS_ABERTOS_MEDICAMENTOS.csv", "sourceName": "ANVISA open data: registered medicines", "confidence": "regulator"},
                note="BR: first registration this year for a drug already tracked as new elsewhere")

# ---------- pages the update agent reads itself ----------
def pages():
    save_page("jp-pmda-new-drugs.html", "https://www.pmda.go.jp/english/review-services/reviews/approved-information/drugs/0002.html", "pmda/0002.html")
    save_page("jp-kegg-new-approvals.html", "https://www.kegg.jp/kegg/drug/br08328.html")
    save_page("ch-swissmedic-new-medicines.html", "https://www.swissmedic.ch/swissmedic/en/home/humanarzneimittel/authorisations/new-medicines.html")
    b = save_page("in-cdsco-new-drugs.html", "https://cdsco.gov.in/opencms/opencms/en/Approval_new/Approved-New-Drugs/")
    if b:  # this year's "List of New Drugs approved in year ..." file(s); links are download_file_division.jsp?num_id=...
        html = b.decode("utf-8", "ignore"); links = []
        for m in re.finditer(r'href=["\']([^"\']*download_file_division\.jsp\?num_id=[^"\']+)["\']', html, re.I):
            ctx = re.sub(r"<[^>]+>", " ", html[max(0, m.start() - 600):m.start()])
            if re.search(r"approved in (the )?year " + YEAR, ctx, re.I):
                u = urllib.parse.urljoin("https://cdsco.gov.in/opencms/opencms/en/Approval_new/Approved-New-Drugs/", m.group(1).replace("&amp;", "&"))
                if u not in links: links.append(u)
        for i, u in enumerate(links[:2]):
            save_page(f"in-cdsco-new-drugs-{YEAR}-{i + 1}.pdf", u)
        if not links: log.append(f"NOTE India: no 'approved in year {YEAR}' file found on the CDSCO page")

os.makedirs(OUT, exist_ok=True)
for label, fn in (("EU (EMA medicines data)", eu), ("UK (MHRA licences)", uk), ("Taiwan (TFDA open data)", tw), ("Brazil (ANVISA open data)", br), ("pages for JP/CH/IN", pages)):
    step(label, fn)
json.dump(proposals, open(os.path.join(OUT, "proposals.json"), "w"), indent=1, ensure_ascii=False)
open(os.path.join(OUT, "log.txt"), "w").write("\n".join(log) + "\n")
print("\n".join(log))
print(f"{len(proposals)} proposals written to {OUT}/proposals.json")
