/* ═══════════════════════════════════════════════════════════════
   globalmap.js — 国际版的雷达 / 卫星 / 降水 / 海陆温底图

   中国城市仍然用气象局那几张图（image.nmc.cn，见 weather.js / wxui.js 的原有逻辑）；
   国际城市没有中国气象局的图，这里换成国际源：

     · 雷达回波 —— RainViewer 的全球雷达拼图（过去 2 小时 + 未来 30 分钟临近预报）。
       https://www.rainviewer.com/api.html  免费、免 key、CORS 开放。
     · 卫星云图 —— NASA GIBS 的 VIIRS 真彩（逐日，全球，CORS 开放）。
     · 降水     —— NASA GIBS 的 IMERG 卫星降水估算（逐日，实况）。
     · 海陆温   —— GIBS 的 MODIS 地表温度 + GHRSST 海表温度（逐日）。

   这些图层都是 XYZ 瓦片，浏览器里用 Leaflet 叠在 CARTO 的深色底图上。
   为什么用 Leaflet 而不是 ECharts：ECharts 的 geo/map 只能画矢量边界，
   叠不了别人的 XYZ 瓦片；而 RainViewer / GIBS 只提供瓦片。

   所有请求都带 `Access-Control-Allow-Origin: *`，所以 GitHub Pages 上可以直连，
   不需要 Actions 预抓。GIBS 的日期用 UTC，图例已经烘进瓦片里。
   ═══════════════════════════════════════════════════════════════ */
(function (global) {
  'use strict';

  /* 底图用 Esri 的深灰画布：免 key、CORS 开放、颜色正好配终端主题。
     （CARTO 的 dark_all 现在会在瓦片里印 API KEY REQUIRED，不能再用。） */
  const BASEMAP = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}';
  const GIBS = 'https://gibs.earthdata.nasa.gov/wmts/epsg3857/best/';

  const pad2 = n => (n < 10 ? '0' : '') + n;
  const fmtDate = d => d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate());
  const fmtTime = (d, tz) => {
    if (!tz) return d.getUTCFullYear() + '-' + pad2(d.getUTCMonth() + 1) + '-' + pad2(d.getUTCDate()) +
      ' ' + pad2(d.getUTCHours()) + ':' + pad2(d.getUTCMinutes()) + ' UTC';
    try {
      return new Intl.DateTimeFormat('zh-CN', {
        timeZone: tz, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false
      }).format(d);
    } catch (e) {
      return d.toISOString().slice(5, 16).replace('T', ' ');
    }
  };

  const KINDS = {
    radar: {
      title: '全球雷达回波',
      note: '来源：RainViewer · 过去 2 小时 + 30 分钟临近预报'
    },
    sat: {
      title: '全球卫星云图',
      note: '来源：NASA GIBS · VIIRS 真彩（逐日）· 夜侧/极区为空是正常的'
    },
    precip: {
      title: '全球降水实况',
      note: '来源：NASA GIBS · IMERG 降水估算（逐日实况，不是预报）'
    },
    temp: {
      title: '全球海陆温度',
      note: '来源：NASA GIBS · MODIS 地表温度 + GHRSST 海温（逐日）'
    }
  };

  function el(tag, attrs, kids) {
    const n = document.createElement(tag);
    if (attrs) for (const k in attrs) {
      if (k === 'class') n.className = attrs[k];
      else if (k === 'text') n.textContent = attrs[k];
      else if (k === 'html') n.innerHTML = attrs[k];
      else n.setAttribute(k, attrs[k]);
    }
    (kids || []).forEach(c => n.appendChild(typeof c === 'string' ? document.createTextNode(c) : c));
    return n;
  }

  function jget(url, ttl) {
    return API.getJSON(url, { ttl: ttl || 600000, key: url });
  }

  const GlobalMap = {
    _map: null,
    _layer: null,
    _timer: null,
    _seq: 0,

    /** 打开一个全球图层页。kind ∈ radar|sat|precip|temp。
     *  返回 true 表示已经接管；调用方（wxui.js）就不用再画原来的中国图了。 */
    async open(kind, body, sub, city) {
      if (!global.L || !body) return false;
      const meta = KINDS[kind];
      if (!meta) return false;
      const seq = ++this._seq;
      this.stop();
      if (this._map) { try { this._map.remove(); } catch (e) { } this._map = null; }
      this._layer = null; this._layer2 = null;

      body.innerHTML = '<div class="wx-load">正在拉取全球 ' + (kind === 'radar' ? '雷达' : kind === 'sat' ? '卫星' : kind === 'precip' ? '降水' : '温度') + ' 图层…</div>';
      let frames = [];
      try {
        frames = await this._frames(kind);
      } catch (e) {
        body.innerHTML = '<div class="wx-load">全球图层获取失败：' + String(e.message || e) + '</div>';
        return true;
      }
      if (!frames.length) {
        body.innerHTML = '<div class="wx-load">暂时取不到全球图层</div>';
        return true;
      }
      if (seq !== this._seq) return true;          // 已经被另一次切换取代

      const lat = (city && isFinite(city.lat)) ? city.lat : 20;
      const lon = (city && isFinite(city.lon)) ? city.lon : 0;
      const zoom = (city && city.intl) ? 5 : 4;

      body.innerHTML =
        '<div class="gm-wrap">' +
          '<div class="wx-pbar">' +
            '<div class="wx-segs"><div class="wx-seg">' +
              '<button class="wx-segbtn on" data-k="' + kind + '">🌍 全球</button>' +
              '<button class="wx-segbtn" data-k="cn">🇨🇳 中国气象局</button>' +
            '</div></div>' +
            '<span class="wx-pt"></span>' +
            '<button class="wx-btn" data-act="play">▶ 播放</button>' +
          '</div>' +
          '<div class="gm-stage"><div class="gm-map"></div>' +
            '<div class="gm-badge">' + (city && city.name ? city.name + (city.country ? ' · ' + city.country : '') : '全球') + '</div>' +
          '</div>' +
          '<input type="range" class="wx-range" min="0" max="' + (frames.length - 1) + '" value="0" />' +
          '<div class="wx-pfoot"><span class="wx-pidx"></span><span class="wx-pnote">' + meta.note + '</span></div>' +
        '</div>';

      if (sub) sub.textContent = meta.title + ' · ' + (city && city.name ? city.name : '全球');

      /* 每个面板自己一个 .gm-map 容器。**不能**用固定 id：
         雷达/卫星/降水/温度四个抽屉的 body 都在 DOM 里，固定 id 会让
         L.map('gmMap') 永远命中第一个（往往是隐藏的雷达容器），
         当前打开的抽屉就只剩一张空白。 */
      const map = L.map(body.querySelector('.gm-map'), {
        center: [lat, lon], zoom: zoom, minZoom: 2, maxZoom: 9,
        worldCopyJump: true, zoomControl: true, attributionControl: true
      });
      this._map = map;
      L.tileLayer(BASEMAP, {
        maxZoom: 19, maxNativeZoom: 16,
        attribution: '&copy; Esri &copy; OpenStreetMap contributors'
      }).addTo(map);
      if (city && isFinite(city.lat) && isFinite(city.lon)) {
        L.circleMarker([lat, lon], {
          radius: 6, color: '#f0b90b', weight: 2, fillColor: '#f0b90b', fillOpacity: 0.9
        }).addTo(map).bindPopup(city.name + (city.country ? ' · ' + city.country : ''));
      }

      const rng = body.querySelector('.wx-range');
      const pt = body.querySelector('.wx-pt');
      const idx = body.querySelector('.wx-pidx');
      const btn = body.querySelector('[data-act="play"]');
      const self = this;
      let i = -1;

      const show = n => {
        i = Math.max(0, Math.min(frames.length - 1, n));
        const f = frames[i];
        if (self._layer) { map.removeLayer(self._layer); self._layer = null; }
        if (self._layer2) { map.removeLayer(self._layer2); self._layer2 = null; }
        self._layer = L.tileLayer(f.url, {
          opacity: f.opacity == null ? 0.9 : f.opacity,
          maxNativeZoom: f.maxNativeZoom || 9, maxZoom: 19,
          attribution: f.attribution || ''
        }).addTo(map);
        /* 第二层（海表温度）是可选的：同一帧里同时叠陆地和海洋。 */
        if (f.url2) {
          self._layer2 = L.tileLayer(f.url2, {
            opacity: f.opacity2 == null ? 0.65 : f.opacity2,
            maxNativeZoom: f.maxNativeZoom2 || 9, maxZoom: 19
          }).addTo(map);
        }
        rng.value = i;
        pt.textContent = fmtTime(f.t, city && city.tz);
        idx.textContent = (i + 1) + ' / ' + frames.length;
      };

      rng.addEventListener('input', e => show(+e.target.value));
      // 打开先看**最新**一帧；点播放才从最早那帧开始循环
      show(frames.length - 1);

      btn.addEventListener('click', () => {
        if (self._timer) { self.stop(); return; }
        btn.textContent = '⏸ 暂停';
        if (i >= frames.length - 1) show(0);
        self._timer = setInterval(() => {
          if (i >= frames.length - 1) show(0); else show(i + 1);
        }, kind === 'radar' ? 420 : 950);
      });

      body.querySelectorAll('.wx-segbtn').forEach(b => b.addEventListener('click', () => {
        if (b.dataset.k === 'cn') {
          self.stop();
          GlobalMap._seq++;                      // 作废正在飞的这次
          if (!global.WXUI) return;
          if (kind === 'radar') WXUI.openRadar(undefined, undefined, undefined, true);
          else if (kind === 'sat') WXUI.openSat(undefined, true);
          else if (kind === 'precip') WXUI.openPrecip(undefined, undefined, true);
          else WXUI.openSeaLandTemp(undefined, undefined, true);
        }
      }));

      // 抽屉关掉时停播放器
      const drawer = body.closest('.wx-drawer');
      if (drawer) {
        const obs = new MutationObserver(() => {
          if (drawer.hidden) self.stop();
        });
        obs.observe(drawer, { attributes: true, attributeFilter: ['hidden'] });
      }
      return true;
    },

    stop() {
      if (this._timer) { clearInterval(this._timer); this._timer = null; }
      const stage = document.querySelector('.gm-wrap');
      const btn = stage && stage.querySelector('[data-act="play"]');
      if (btn) btn.textContent = '▶ 播放';
    },

    /** 生成帧列表。每帧 {t: Date, url: 模板}。 */
    async _frames(kind) {
      if (kind === 'radar') {
        const d = await jget('https://api.rainviewer.com/public/weather-maps.json', 120000);
        const host = (d && d.host) || 'https://tilecache.rainviewer.com';
        const list = [].concat((d.radar && d.radar.past) || [], (d.radar && d.radar.nowcast) || []);
        return list.map(x => ({
          t: new Date(x.time * 1000),
          url: host + x.path + '/256/{z}/{x}/{y}/4/1_1.png',
          opacity: 0.9,
          maxNativeZoom: 8,
          attribution: 'RainViewer'
        }));
      }

      const today = new Date();
      if (kind === 'sat') {
        return [3, 2, 1, 0].map(k => {
          const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - k, 12, 0, 0));
          return {
            t: d,
            url: GIBS + 'VIIRS_SNPP_CorrectedReflectance_TrueColor/default/' + fmtDate(d) +
              '/GoogleMapsCompatible_Level9/{z}/{y}/{x}.jpg',
            opacity: 0.95, maxNativeZoom: 9, attribution: 'NASA GIBS · VIIRS'
          };
        });
      }
      if (kind === 'precip') {
        return [3, 2, 1, 0].map(k => {
          const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - k));
          return {
            t: d,
            url: GIBS + 'IMERG_Precipitation_Rate/default/' + fmtDate(d) +
              '/GoogleMapsCompatible_Level6/{z}/{y}/{x}.png',
            opacity: 0.8, maxNativeZoom: 6, attribution: 'NASA GIBS · IMERG'
          };
        });
      }
      if (kind === 'temp') {
        return [2, 1, 0].map(k => {
          const d = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate() - k));
          return {
            t: d,
            url: GIBS + 'MODIS_Terra_Land_Surface_Temp_Day/default/' + fmtDate(d) +
              '/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png',
            url2: GIBS + 'GHRSST_L4_MUR_Sea_Surface_Temperature/default/' + fmtDate(d) +
              '/GoogleMapsCompatible_Level7/{z}/{y}/{x}.png',
            opacity: 0.85, opacity2: 0.6, maxNativeZoom: 7, maxNativeZoom2: 7,
            attribution: 'NASA GIBS · MODIS LST + GHRSST'
          };
        });
      }
      return [];
    }
  };

  global.GlobalMap = GlobalMap;
})(window);
