# 天气战士 · 全球版（weather-fighter-global）

把天气当股票看的终端。这是 [lolikonnn/weather-fighter](https://github.com/lolikonnn/weather-fighter)
的 1:1 前端复刻，**只换了数据源**：

- **中国城市**：保留原来的中国气象局（weather.cma.cn）与中国天气网（weather.com.cn），
  实况、预报、逐 3 小时、雷达、卫星、台风、预警都不动。
- **国际城市**：换成国际数据源，用来观察全球天气：
  - 实况 / 逐小时 / 历史 K 线 / 16 日预报 / 空气质量：**Open-Meteo**
  - 雷达回波 + 30 分钟临近预报：**RainViewer**
  - 真彩卫星 / IMERG 降水 / MODIS 地表温度 / GHRSST 海温：**NASA GIBS**
  - 预警：**NWS**（美国，实时） + **MeteoAlarm**（欧洲） + **GDACS**（全球）
  - 热带气旋：**NHC**（大西洋 / 东太平洋） + 中国气象局（西太平洋）
  - 地震：USGS / 中国地震台网 / 日本气象厅（原本就是全球）

## 在线地址

部署在 GitHub Pages：`https://<你的账号>.github.io/weather-fighter-global/`

## 城市目录

`web/data/world-cities.json`（约 600 KB）由 `tools/build_world_cities.py` 生成：

- GeoNames `cities15000`：经纬度、人口、IANA 时区、国家、一级行政区
- Wikidata：简体中文名（按 GeoNames ID `P1566` 精确匹配）
- 筛选口径：人口 ≥ 10 万 **或** 首都，排除中国（中国走 `cities.json` / `places.json`）
- 共 **5,657** 座，搜索支持中文名、英文名、拼音（如 `niuyue`）、GeoNames id

重新生成（需要联网；结果已提交，日常不需要跑）：

```bash
python3 tools/build_world_cities.py          # 用 tools/.cache 里的缓存
python3 tools/build_world_cities.py --refresh  # 重新下载/查询 Wikidata
```

## 时区

国际城市的「今天」、日 K 的 0 点 / 23 点、日出日落、`timezone=auto` 全部按**城市当地时区**算。
报价头会显示「当地 13:25」；中国城市仍然按 `Asia/Shanghai`。

## 数据的抓取

- **中国**：`tools/prefetch_official.py`（沿用原项目），GitHub Actions 每 30 分钟抓一次，
  写到 `web/data/official/`。
- **国际预警 / 热带气旋**：`tools/fetch_intl_alerts.py`，GitHub Actions 每 30 分钟抓一次，
  写到 `web/data/intl/alerts.json` 与 `storms.json`。
  MeteoAlarm / GDACS / NHC 不返回 CORS 头，浏览器直连不了；NWS 有 CORS，前端直接请求。
- 国际城市本身的天气（Open-Meteo / RainViewer / NASA GIBS）都带 `Access-Control-Allow-Origin: *`，
  浏览器直连，不经过 Actions。

## 本地调试

```bash
python3 -m http.server 8377 --directory web
# http://localhost:8377/?local=0
```

`?local=0` 强制走 GitHub Pages 的取数路径（不经过 `server/app.py` 代理）。
完整本地代理可以跑 `python3 server/app.py`，但国际数据不需要它。

## 部署

推送到 `main` 即触发 `.github/workflows/deploy.yml`：抓数据 → 提交 → 打包 `web/` → 部署 Pages。

首次需要在仓库 Settings → Pages 里把 Source 设为 **GitHub Actions**（工作流里的
`configure-pages` 带 `enablement: true`，通常会自动打开）。

## 目录

```
web/                 静态站（Pages 部署的就是这个目录）
  index.html
  css/ js/ img/ vendor/
  data/              城市目录、官方预抓数据、国际预警静态文件
tools/               城市目录生成、中国/国际数据预抓
server/app.py        本地代理（可选）
```

## 许可与免责

前端来自原项目；数据版权归各来源所有（Open-Meteo、中国气象局、NWS、MeteoAlarm、GDACS、
NASA GIBS、RainViewer、USGS 等）。本站不是官方气象服务，不发布自制预报。
