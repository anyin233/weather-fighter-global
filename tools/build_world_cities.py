# -*- coding: utf-8 -*-
"""
生成 web/data/world-cities.json —— 国际版的城市目录。

数据源（都可复现）:
  · GeoNames cities15000.txt        http://download.geonames.org/export/dump/cities15000.zip
      —— 城市中心点经纬度、人口、所在国家、IANA 时区
  · Wikidata (P1566 = GeoNames ID)  —— 简体中文名（zh-hans / zh 标签）
      查不到中文标签时，退回 GeoNames alternatenames 里的汉字名。
  · Wikidata (P297 = ISO 3166-1)    —— 国家/地区中文名
  · countryInfo.txt                 —— 大洲代码（AF/AS/EU/NA/OC/SA）

输出结构（尽量短，文件要能塞进一次请求）:
  {
    "updated": "YYYY-MM-DD", "source": "...", "count": 5657,
    "countries": {"US": "美国", ...},
    "cities": [
      ["w5128581", "纽约", "New York City", "US", 40.71427, -74.00597,
       "America/New_York", 8804190, 1, "niuyue", "NA"],
      ...
    ]
  }
  下标含义见 FIELDS。数组而不是对象：5657 条能省下近 100 KB 的键名。

用法:
  python3 tools/build_world_cities.py             # 有缓存就直接用
  python3 tools/build_world_cities.py --refresh   # 重新下载/查询
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import zipfile

try:
    from opencc import OpenCC
    _cc = OpenCC("t2s")
    def t2s(s):
        return _cc.convert(s) if s else s
except Exception:  # pragma: no cover - 没有 opencc 也能跑，只是中文名不转简
    def t2s(s):
        return s

try:
    from pypinyin import lazy_pinyin
    def py(s):
        return "".join(lazy_pinyin(s)) if s else ""
except Exception:  # pragma: no cover
    def py(s):
        return ""

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "web", "data", "world-cities.json")
CACHE = os.path.join(HERE, ".cache")
GEONAMES_ZIP = os.path.join(CACHE, "cities15000.zip")
GEONAMES_TXT = os.path.join(CACHE, "cities15000.txt")
COUNTRY_TXT = os.path.join(CACHE, "countryInfo.txt")
ADMIN1_TXT = os.path.join(CACHE, "admin1.txt")
WD_LABELS = os.path.join(CACHE, "wd_labels.json")
WD_COUNTRIES = os.path.join(CACHE, "wd_countries.json")

MIN_POP = 100000          # 人口门槛；首都无论人口都收
UA = "weather-fighter-global/1.0 (https://github.com/anyin233)"

FIELDS = ["id", "name", "en", "cc", "lat", "lon", "tz", "pop", "cap", "py", "reg", "admin1"]

# 大洲代码 -> 中文
CONT = {"AF": "非洲", "AS": "亚洲", "EU": "欧洲", "NA": "北美洲",
        "SA": "南美洲", "OC": "大洋洲", "AN": "南极洲"}

# Wikidata 的正式国名太长了，界面上用常用简称
SHORT = {
    "中华人民共和国": "中国", "中华民国": "台湾", "大韩民国": "韩国",
    "朝鲜民主主义人民共和国": "朝鲜", "俄罗斯联邦": "俄罗斯",
    "越南社会主义共和国": "越南", "老挝人民民主共和国": "老挝",
    "伊朗伊斯兰共和国": "伊朗", "阿拉伯叙利亚共和国": "叙利亚",
    "阿拉伯联合酋长国": "阿联酋", "沙特阿拉伯王国": "沙特阿拉伯",
    "缅甸联邦共和国": "缅甸", "斯里兰卡民主社会主义共和国": "斯里兰卡",
    "孟加拉人民共和国": "孟加拉国", "菲律宾共和国": "菲律宾",
    "印度尼西亚共和国": "印度尼西亚", "马来西亚": "马来西亚",
    "泰王国": "泰国", "柬埔寨王国": "柬埔寨", "尼泊尔联邦民主共和国": "尼泊尔",
    "巴基斯坦伊斯兰共和国": "巴基斯坦", "阿富汗伊斯兰共和国": "阿富汗",
    "哈萨克斯坦共和国": "哈萨克斯坦", "乌兹别克斯坦共和国": "乌兹别克斯坦",
    "蒙古国": "蒙古", "大不列颠及北爱尔兰联合王国": "英国",
    "法兰西共和国": "法国", "德意志联邦共和国": "德国", "意大利共和国": "意大利",
    "西班牙王国": "西班牙", "葡萄牙共和国": "葡萄牙", "荷兰王国": "荷兰",
    "比利时王国": "比利时", "瑞士联邦": "瑞士", "奥地利共和国": "奥地利",
    "瑞典王国": "瑞典", "挪威王国": "挪威", "丹麦王国": "丹麦",
    "芬兰共和国": "芬兰", "冰岛": "冰岛", "爱尔兰": "爱尔兰",
    "波兰共和国": "波兰", "捷克共和国": "捷克", "斯洛伐克共和国": "斯洛伐克",
    "匈牙利": "匈牙利", "罗马尼亚": "罗马尼亚", "保加利亚共和国": "保加利亚",
    "希腊共和国": "希腊", "土耳其共和国": "土耳其", "乌克兰": "乌克兰",
    "白俄罗斯共和国": "白俄罗斯", "塞尔维亚共和国": "塞尔维亚",
    "克罗地亚共和国": "克罗地亚", "斯洛文尼亚共和国": "斯洛文尼亚",
    "波斯尼亚和黑塞哥维那": "波黑", "阿尔巴尼亚共和国": "阿尔巴尼亚",
    "北马其顿共和国": "北马其顿", "黑山": "黑山", "摩尔多瓦共和国": "摩尔多瓦",
    "立陶宛共和国": "立陶宛", "拉脱维亚共和国": "拉脱维亚",
    "爱沙尼亚共和国": "爱沙尼亚", "卢森堡大公国": "卢森堡",
    "马耳他共和国": "马耳他", "塞浦路斯共和国": "塞浦路斯",
    "美利坚合众国": "美国", "加拿大": "加拿大", "墨西哥合众国": "墨西哥",
    "巴西联邦共和国": "巴西", "阿根廷共和国": "阿根廷", "智利共和国": "智利",
    "秘鲁共和国": "秘鲁", "哥伦比亚共和国": "哥伦比亚", "委内瑞拉玻利瓦尔共和国": "委内瑞拉",
    "厄瓜多尔共和国": "厄瓜多尔", "玻利维亚多民族国": "玻利维亚",
    "巴拉圭共和国": "巴拉圭", "乌拉圭东岸共和国": "乌拉圭",
    "古巴共和国": "古巴", "海地共和国": "海地", "多米尼加共和国": "多米尼加",
    "牙买加": "牙买加", "巴拿马共和国": "巴拿马", "哥斯达黎加共和国": "哥斯达黎加",
    "危地马拉共和国": "危地马拉", "洪都拉斯共和国": "洪都拉斯",
    "萨尔瓦多共和国": "萨尔瓦多", "尼加拉瓜共和国": "尼加拉瓜",
    "伯利兹": "伯利兹", "澳大利亚联邦": "澳大利亚", "新西兰": "新西兰",
    "巴布亚新几内亚独立国": "巴布亚新几内亚", "斐济共和国": "斐济",
    "阿拉伯埃及共和国": "埃及", "南非共和国": "南非", "尼日利亚联邦共和国": "尼日利亚",
    "埃塞俄比亚联邦民主共和国": "埃塞俄比亚", "肯尼亚共和国": "肯尼亚",
    "坦桑尼亚联合共和国": "坦桑尼亚", "摩洛哥王国": "摩洛哥",
    "阿尔及利亚民主人民共和国": "阿尔及利亚", "突尼斯共和国": "突尼斯",
    "利比亚国": "利比亚", "苏丹共和国": "苏丹", "南苏丹共和国": "南苏丹",
    "加纳共和国": "加纳", "科特迪瓦共和国": "科特迪瓦", "塞内加尔共和国": "塞内加尔",
    "喀麦隆共和国": "喀麦隆", "刚果民主共和国": "刚果（金）", "刚果共和国": "刚果（布）",
    "安哥拉共和国": "安哥拉", "莫桑比克共和国": "莫桑比克", "津巴布韦共和国": "津巴布韦",
    "赞比亚共和国": "赞比亚", "博茨瓦纳共和国": "博茨瓦纳", "纳米比亚共和国": "纳米比亚",
    "马达加斯加共和国": "马达加斯加", "乌干达共和国": "乌干达", "卢旺达共和国": "卢旺达",
    "以色列国": "以色列", "约旦哈希姆王国": "约旦", "黎巴嫩共和国": "黎巴嫩",
    "伊拉克共和国": "伊拉克", "科威特国": "科威特", "卡塔尔国": "卡塔尔",
    "阿曼苏丹国": "阿曼", "巴林王国": "巴林", "也门共和国": "也门",
    "格鲁吉亚": "格鲁吉亚", "亚美尼亚共和国": "亚美尼亚", "阿塞拜疆共和国": "阿塞拜疆",
    "新加坡共和国": "新加坡", "文莱达鲁萨兰国": "文莱", "东帝汶民主共和国": "东帝汶",
}


def fetch(url, path, refresh=False):
    os.makedirs(CACHE, exist_ok=True)
    if os.path.exists(path) and not refresh and os.path.getsize(path) > 0:
        return path
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=180) as r, open(path, "wb") as f:
        f.write(r.read())
    return path


def sparql(query, timeout=120):
    data = urllib.parse.urlencode({"query": query}).encode()
    req = urllib.request.Request(
        "https://query.wikidata.org/sparql", data=data,
        headers={"Accept": "application/sparql-results+json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def geonames(refresh):
    fetch("https://download.geonames.org/export/dump/cities15000.zip", GEONAMES_ZIP, refresh)
    if refresh or not os.path.exists(GEONAMES_TXT):
        with zipfile.ZipFile(GEONAMES_ZIP) as z:
            z.extract("cities15000.txt", CACHE)
    rows = []
    with open(GEONAMES_TXT, encoding="utf-8") as f:
        for line in f:
            r = line.rstrip("\n").split("\t")
            if len(r) < 19:
                continue
            rows.append(r)
    return rows


def admin1_meta():
    out = {}
    if not os.path.exists(ADMIN1_TXT):
        return out
    with open(ADMIN1_TXT, encoding="utf-8") as f:
        for line in f:
            r = line.rstrip("\n").split("\t")
            if len(r) >= 2 and "." in r[0]:
                out[r[0]] = r[1]
    return out


def country_meta():
    # countryInfo: 0 ISO, 4 name, 8 continent
    rows = {}
    with open(COUNTRY_TXT, encoding="utf-8") as f:
        for line in f:
            if line.startswith("#"):
                continue
            r = line.rstrip("\n").split("\t")
            if len(r) > 8 and r[0]:
                rows[r[0]] = {"en": r[4], "cont": r[8]}
    return rows


def cjk(s):
    m = re.findall(r"[\u3400-\u9fff]{2,}", s or "")
    return t2s(m[0]) if m else ""


def wikidata_labels(ids, refresh):
    if os.path.exists(WD_LABELS) and not refresh:
        return json.load(open(WD_LABELS, encoding="utf-8"))
    out = {}
    for i in range(0, len(ids), 350):
        vals = " ".join('"%s"' % x for x in ids[i:i + 350])
        q = ('SELECT ?gnid ?itemLabel WHERE { VALUES ?gnid { %s } '
             '?item wdt:P1566 ?gnid . SERVICE wikibase:label '
             '{ bd:serviceParam wikibase:language "zh-hans,zh,en". } }') % vals
        try:
            d = sparql(q)
        except Exception as e:
            print("  Wikidata 批次 %d 失败: %s" % (i, e), file=sys.stderr)
            continue
        for b in d["results"]["bindings"]:
            v = b.get("itemLabel", {}).get("value", "")
            if v and not re.fullmatch(r"Q\d+", v):
                out[b["gnid"]["value"]] = v
        print("  Wikidata %d/%d" % (min(i + 350, len(ids)), len(ids)), file=sys.stderr)
        time.sleep(0.6)
    json.dump(out, open(WD_LABELS, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def wikidata_countries(refresh):
    if os.path.exists(WD_COUNTRIES) and not refresh:
        return json.load(open(WD_COUNTRIES, encoding="utf-8"))
    q = ('SELECT ?iso ?itemLabel WHERE { ?item wdt:P297 ?iso . SERVICE wikibase:label '
         '{ bd:serviceParam wikibase:language "zh-hans,zh,en". } }')
    out = {}
    for b in sparql(q, 180)["results"]["bindings"]:
        out[b["iso"]["value"]] = b.get("itemLabel", {}).get("value", "")
    json.dump(out, open(WD_COUNTRIES, "w", encoding="utf-8"), ensure_ascii=False)
    return out


def main():
    refresh = "--refresh" in sys.argv
    os.makedirs(CACHE, exist_ok=True)
    fetch("https://download.geonames.org/export/dump/countryInfo.txt", COUNTRY_TXT, refresh)
    fetch("https://download.geonames.org/export/dump/admin1CodesASCII.txt", ADMIN1_TXT, refresh)
    rows = geonames(refresh)
    cm = country_meta()
    adm = admin1_meta()

    picked = []
    for r in rows:
        # geonameid, name, asciiname, alternatenames, lat, lon, fclass, fcode,
        # country, cc2, admin1, admin2, admin3, admin4, population, elevation,
        # dem, timezone, modification
        gid, name, ascii_name, alts = r[0], r[1], r[2], r[3]
        lat, lon = float(r[4]), float(r[5])
        fcode, cc = r[7], r[8]
        pop = int(r[14] or 0)
        tz = r[17]
        if cc == "CN":            # 中国城市走 cities.json / places.json，不重复
            continue
        if not tz or not cm.get(cc):
            continue
        if pop < MIN_POP and fcode != "PPLC":
            continue
        picked.append({
            "gid": gid, "name": name, "en": ascii_name, "alts": alts,
            "lat": round(lat, 4), "lon": round(lon, 4), "tz": tz, "pop": pop,
            "cc": cc, "cap": 1 if fcode == "PPLC" else 0,
            "admin1": adm.get(cc + "." + (r[10] or ""), r[10] or ""),
        })

    picked.sort(key=lambda x: (-x["pop"], x["name"]))
    print("候选 %d 座" % len(picked), file=sys.stderr)

    labels = wikidata_labels([x["gid"] for x in picked], refresh)
    wd_countries = wikidata_countries(refresh)
    countries = {}
    for cc, meta in cm.items():
        zh = SHORT.get(wd_countries.get(cc, ""), wd_countries.get(cc, ""))
        countries[cc] = zh or meta["en"]

    cities = []
    for x in picked:
        lab = t2s(labels.get(x["gid"], ""))
        name = cjk(lab) or cjk(x["alts"]) or x["en"]
        # 日文地名常带行政后缀（东京都 / 大阪市），界面上按城市名显示更自然。
        # 只动含有汉字的短名，别把「墨西哥城」这种真名改掉。
        if cjk(name):
            if x["cc"] == "JP" and name.endswith("都"):
                name = name[:-1]
            elif len(name) > 2 and name.endswith("市"):
                name = name[:-1]
        pinyin = py(name) if re.search(r"[\u3400-\u9fff]", name) else ""
        cities.append([
            "w" + x["gid"], name, x["en"], x["cc"], x["lat"], x["lon"],
            x["tz"], x["pop"], x["cap"], pinyin, cm[x["cc"]]["cont"], x["admin1"],
        ])

    doc = {
        "updated": time.strftime("%Y-%m-%d"),
        "source": "GeoNames cities15000 + Wikidata labels",
        "count": len(cities),
        "fields": FIELDS,
        "continents": CONT,
        "countries": countries,
        "cities": cities,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    body = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    open(OUT, "w", encoding="utf-8").write(body)
    print("写出 %s · %d 座城市 · %.1f KB" % (OUT, len(cities), len(body.encode()) / 1024))


if __name__ == "__main__":
    main()
