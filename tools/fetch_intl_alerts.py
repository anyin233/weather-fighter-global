# -*- coding: utf-8 -*-
"""
抓国际预警 -> web/data/intl/alerts.json

为什么要在 Actions 里抓、而不是浏览器直连：
  · MeteoAlarm（欧洲 30 多国气象局联合预警）的 feeds.meteoalarm.org **不返回
    Access-Control-Allow-Origin**，GitHub Pages 上的 fetch 会被浏览器挡下来；
  · GDACS（联合国/欧盟的全球灾害预警）的 RSS 同样没有 CORS 头。
  NWS（美国国家气象局）有 CORS，浏览器能直连，所以**不在**这里抓 ——
  前端 `Weather.warnings()` 直接请求 api.weather.gov，拿到的永远是最新的。

产出结构（尽量小）:
  {
    "updated": 1730000000000,
    "eu": [{ "t": "...", "e": "Moderate rain-flood warning", "sev": "Severe",
             "area": "Var", "src": "MeteoAlarm · FR", "web": "..." }, ...],
    "gdacs": [{ "t": "...", "title": "...", "lvl": "Orange", "type": "TC",
                "lat": 12.3, "lon": 134.5, "src": "GDACS", "web": "..." }, ...]
  }

筛选口径：
  · MeteoAlarm 只留 **orange / red**（awareness_level 以 2 或 3 开头，或 severity
    为 Severe / Extreme）。绿色/黄色一天几百条，全存下来既没用又拖慢面板。
  · GDACS 只留 alertlevel 为 Orange / Red 的（green 占 300/309）。
  · 同一事件按 (event + 区域) 去重。
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(ROOT, "web", "data", "intl", "alerts.json")
STORM_OUT = os.path.join(ROOT, "web", "data", "intl", "storms.json")
UA = "weather-fighter-global/1.0 (https://github.com/anyin233)"

# MeteoAlarm 的 feed 用英文国家名做 slug；这 35 个都实测 200。
# （bosnia-and-herzegovina / north-macedonia / albania 的 slug 不是这个，
#  试过 republic-of-albania 等也 404，先不收 —— 宁可少一个国家，不编一个 URL。）
EU = [
    ("united-kingdom", "英国"), ("ireland", "爱尔兰"), ("france", "法国"),
    ("spain", "西班牙"), ("portugal", "葡萄牙"), ("germany", "德国"),
    ("belgium", "比利时"), ("netherlands", "荷兰"), ("luxembourg", "卢森堡"),
    ("switzerland", "瑞士"), ("austria", "奥地利"), ("italy", "意大利"),
    ("denmark", "丹麦"), ("sweden", "瑞典"), ("norway", "挪威"),
    ("finland", "芬兰"), ("iceland", "冰岛"), ("poland", "波兰"),
    ("czechia", "捷克"), ("slovakia", "斯洛伐克"), ("hungary", "匈牙利"),
    ("slovenia", "斯洛文尼亚"), ("croatia", "克罗地亚"), ("serbia", "塞尔维亚"),
    ("montenegro", "黑山"), ("greece", "希腊"), ("bulgaria", "保加利亚"),
    ("romania", "罗马尼亚"), ("moldova", "摩尔多瓦"), ("ukraine", "乌克兰"),
    ("estonia", "爱沙尼亚"), ("latvia", "拉脱维亚"), ("lithuania", "立陶宛"),
    ("malta", "马耳他"), ("cyprus", "塞浦路斯"),
]


def get(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def level_of(info):
    """MeteoAlarm 的等级藏在 parameter: "2; orange; Severe"。"""
    for p in info.get("parameter") or []:
        if p.get("valueName") == "awareness_level":
            m = re.match(r"(\d+)", str(p.get("value") or ""))
            if m:
                return int(m.group(1))
    sev = str(info.get("severity") or "")
    return {"Extreme": 3, "Severe": 2}.get(sev, 0)


def fetch_eu():
    out, seen = [], set()
    for slug, zh in EU:
        url = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-" + slug
        try:
            doc = json.loads(get(url))
        except Exception as e:
            print("  跳过 %s: %s" % (slug, e), file=sys.stderr)
            continue
        for w in doc.get("warnings") or []:
            alert = w.get("alert") or {}
            infos = alert.get("info") or []
            # 同一份预警有 fr/en 两种语言，取英文那条展示（中文用户至少能看懂 event）
            info = next((x for x in infos if str(x.get("language", "")).startswith("en")), infos[0] if infos else None)
            if not info:
                continue
            lv = level_of(info)
            if lv < 2:
                continue
            areas = [a.get("areaDesc") for a in (info.get("area") or []) if a.get("areaDesc")]
            area = "、".join(areas[:3]) + ("…" if len(areas) > 3 else "")
            ev = str(info.get("event") or info.get("headline") or "")
            key = (ev, area)
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "t": str(info.get("onset") or info.get("effective") or alert.get("sent") or ""),
                "exp": str(info.get("expires") or ""),
                "e": ev,
                "sev": str(info.get("severity") or ("Severe" if lv >= 2 else "Minor")),
                "lvl": lv,
                "area": area,
                "ctry": zh,
                "src": "MeteoAlarm · " + zh,
                "web": str(info.get("web") or "https://www.meteoalarm.org/"),
                "x": str(info.get("description") or info.get("instruction") or "")[:400],
            })
    # 只留还没过期的
    now = time.time()
    def alive(w):
        if not w["exp"]:
            return True
        try:
            from datetime import datetime
            return datetime.fromisoformat(w["exp"].replace("Z", "+00:00")).timestamp() > now - 3600
        except Exception:
            return True
    out = [w for w in out if alive(w)]
    out.sort(key=lambda w: (-w["lvl"], w["t"]))
    return out[:200]


def fetch_gdacs():
    try:
        raw = get("https://www.gdacs.org/xml/rss.xml", 60)
    except Exception as e:
        print("  GDACS 失败: %s" % e, file=sys.stderr)
        return []
    root = ET.fromstring(raw)
    ns = {
        "geo": "http://www.w3.org/2003/01/geo/wgs84_pos#",
        "gdacs": "http://www.gdacs.org",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    out = []
    for it in root.iter("item"):
        lvl = (it.findtext("gdacs:alertlevel", default="", namespaces=ns) or "").strip()
        if lvl not in ("Orange", "Red"):
            continue
        lat = it.findtext("geo:Point/geo:lat", default="", namespaces=ns)
        lon = it.findtext("geo:Point/geo:long", default="", namespaces=ns)
        title = it.findtext("title", default="") or ""
        desc = it.findtext("description", default="") or ""
        link = it.findtext("link", default="") or ""
        pub = it.findtext("pubDate", default="") or ""
        subj = it.findtext("dc:subject", default="") or ""
        # 地震交给「🌋 地震」那页（CENC + JMA + USGS 三路合并），这里不重复一遍。
        if subj.startswith("EQ") or "earthquake" in title.lower():
            continue
        out.append({
            "t": pub, "title": title.strip(), "lvl": lvl,
            "type": subj[:2], "lat": float(lat) if lat else None,
            "lon": float(lon) if lon else None,
            "src": "GDACS", "web": link, "x": desc[:400],
        })
    return out


def fetch_nhc():
    """NHC 的 CurrentStorms.json 没有 CORS 头，浏览器直连不了，所以也在这里预抓。"""
    try:
        doc = json.loads(get("https://www.nhc.noaa.gov/CurrentStorms.json", 60))
    except Exception as e:
        print("  NHC 失败: %s" % e, file=sys.stderr)
        return []
    out = []
    for s in doc.get("activeStorms") or []:
        lat, lon = s.get("latitudeNumeric"), s.get("longitudeNumeric")
        if lat is None or lon is None:
            continue
        out.append({
            "id": s.get("id") or s.get("binNumber") or s.get("name"),
            "name": s.get("name") or "",
            "bin": s.get("binNumber") or "",
            "cls": s.get("classification") or "",
            "wind": float(s.get("intensity") or 0),       # knots
            "pres": float(s.get("pressure") or 0),
            "lat": float(lat), "lon": float(lon),
            "dir": s.get("movementDir"), "spd": s.get("movementSpeed"),
            "t": s.get("lastUpdate") or "",
            "url": ((s.get("publicAdvisory") or {}).get("url") or ""),
        })
    return out


def write_json(path, obj):
    body = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    old = None
    if os.path.exists(path):
        old = open(path, encoding="utf-8").read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if old != body:
        open(path, "w", encoding="utf-8").write(body)
        print("写出 %s · %.1f KB" % (path, len(body.encode()) / 1024), file=sys.stderr)
    else:
        print("无变化：%s" % path, file=sys.stderr)


def main():
    print("抓取 MeteoAlarm（欧洲 %d 国）…" % len(EU), file=sys.stderr)
    eu = fetch_eu()
    print("  保留 %d 条橙色/红色预警" % len(eu), file=sys.stderr)
    print("抓取 GDACS（全球橙/红）…", file=sys.stderr)
    gd = fetch_gdacs()
    print("  保留 %d 条" % len(gd), file=sys.stderr)
    write_json(OUT, {"updated": int(time.time() * 1000), "eu": eu, "gdacs": gd})
    print("抓取 NHC 活跃热带气旋…", file=sys.stderr)
    storms = fetch_nhc()
    print("  活跃 %d 个" % len(storms), file=sys.stderr)
    write_json(STORM_OUT, {"updated": int(time.time() * 1000), "storms": storms})


if __name__ == "__main__":
    main()
