/*
 * Hikvision Bridge recordings: sidebar panel <hikvision-bridge-panel> and dashboard card
 * <hikvision-bridge-card>. Plain custom elements, no build step; colours come from the
 * Home Assistant theme.
 */

const DOMAIN = "hikvision_bridge";
const BASE = new URL(".", import.meta.url).pathname;
const HOUR = 3600e3;
const DAY = 24 * HOUR;
const ZOOMS = [DAY, 12 * HOUR, 6 * HOUR, 2 * HOUR, HOUR, 15 * 60e3];
const HEVC = 'video/mp4; codecs="hvc1.1.6.L153.B0"';

// English texts; translations come from the integration (selector "ui").
const TEXT = {
  live: "Live",
  playback: "Playback",
  quality: "Quality",
  auto: "Auto",
  low: "Low (fast)",
  high: "High",
  original: "Original",
  compatible: "Compatible (H.264)",
  cameras: "Cameras",
  no_cameras: "No cameras found.",
  no_recordings: "No recordings on this day.",
  no_recording: "No recording from this time on.",
  playback_encrypted: "The device encrypts its recordings; they cannot be played here.",
  playback_busy: "The camera is already playing a recording elsewhere. Try again in a moment.",
  playback_auth: "The device rejected the login.",
  playback_failed: "Playback failed.",
  no_ffmpeg: "ffmpeg is not available in Home Assistant.",
  live_unavailable: "No live stream for this camera.",
  hevc_hint: "This browser cannot play H.265 recordings; 'Compatible' converts them (slow on small machines).",
  today: "Today",
  previous_event: "Previous event",
  next_event: "Next event",
  back: "10 seconds back",
  forward: "10 seconds forward",
  play: "Play",
  pause: "Pause",
  download: "Download this recording",
  fullscreen: "Full screen",
  zoom_in: "Zoom in",
  zoom_out: "Zoom out",
  previous_day: "Previous day",
  next_day: "Next day",
  source: "Source",
  recorder: "Recorder",
  card: "Memory card",
  select_camera: "Select a camera.",
};

const KIND_COLORS = {
  continuous: "#4f8fdb",
  motion: "#f5a524",
  alarm: "#e5484d",
  event: "#a855f7",
  manual: "#22b8cf",
  other: "#8b8d98",
};
const EVENT_COLORS = {
  motion: "#f5a524",
  intrusion: "#e5484d",
  line_crossing: "#ec4899",
  region_entrance: "#a855f7",
  region_exiting: "#8b5cf6",
  tamper: "#ef4444",
  video_loss: "#71717a",
  scene_change: "#14b8a6",
  pir: "#f97316",
  target_person: "#22c55e",
  target_vehicle: "#06b6d4",
};

let hlsLoader;
function loadHls() {
  if (window.Hls) return Promise.resolve(window.Hls);
  if (!hlsLoader) {
    hlsLoader = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = `${BASE}hls.light.min.js`;
      script.onload = () => resolve(window.Hls);
      script.onerror = reject;
      document.head.appendChild(script);
    });
  }
  return hlsLoader;
}

const translations = new Map();
async function loadTexts(hass) {
  const language = hass.language || "en";
  if (!translations.has(language)) {
    translations.set(
      language,
      Promise.all(
        ["selector", "entity"].map((category) =>
          hass
            .callWS({ type: "frontend/get_translations", language, category, integration: [DOMAIN] })
            .then((r) => r.resources)
            .catch(() => ({})),
        ),
      ).then(([selector, entity]) => ({ ...selector, ...entity })),
    );
  }
  return translations.get(language);
}

function makeTranslator(resources) {
  const prefix = `component.${DOMAIN}.`;
  return {
    ui: (key) => resources[`${prefix}selector.ui.options.${key}`] || TEXT[key] || key,
    kind: (key) => resources[`${prefix}selector.recording_kind.options.${key}`] || key,
    event: (key) => resources[`${prefix}entity.binary_sensor.${key}.name`] || key.replace(/_/g, " "),
    source: (key) => resources[`${prefix}selector.recording_source.options.${key}`] || TEXT[key] || key,
  };
}

const pad = (n) => String(n).padStart(2, "0");
const clock = (date, seconds = true) =>
  `${pad(date.getHours())}:${pad(date.getMinutes())}${seconds ? `:${pad(date.getSeconds())}` : ""}`;
const startOfDay = (date) => new Date(date.getFullYear(), date.getMonth(), date.getDate());
const isoDay = (date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`;

function icon(path) {
  return `<svg viewBox="0 0 24 24" aria-hidden="true"><path d="${path}"/></svg>`;
}
const ICONS = {
  play: icon("M8 5.14v14l11-7-11-7z"),
  pause: icon("M14 19h4V5h-4M6 19h4V5H6v14z"),
  back: icon("M12.5 3a9 9 0 1 0 9 9h-2a7 7 0 1 1-7-7v3l4-4-4-4v3z"),
  forward: icon("M11.5 3a9 9 0 1 1-9 9h2a7 7 0 1 0 7-7v3l-4-4 4-4v3z"),
  prev: icon("M6 6h2v12H6zm3.5 6 8.5 6V6z"),
  next: icon("M16 18h2V6h-2zM6 18l8.5-6L6 6z"),
  download: icon("M5 20h14v-2H5m14-9h-4V3H9v6H5l7 7 7-7z"),
  fullscreen: icon("M5 5h5v2H7v3H5V5m9 0h5v5h-2V7h-3V5m3 9h2v5h-5v-2h3v-3m-7 3v2H5v-5h2v3h3z"),
  menu: icon("M3 6h18v2H3V6m0 5h18v2H3v-2m0 5h18v2H3v-2z"),
  left: icon("M15.41 16.58 10.83 12l4.58-4.59L14 6l-6 6 6 6 1.41-1.42z"),
  right: icon("M8.59 16.58 13.17 12 8.59 7.41 10 6l6 6-6 6-1.41-1.42z"),
  plus: icon("M19 13h-6v6h-2v-6H5v-2h6V5h2v6h6v2z"),
  minus: icon("M19 13H5v-2h14v2z"),
  live: icon("M12 8a4 4 0 1 1 0 8 4 4 0 0 1 0-8m0-6a10 10 0 1 1 0 20 10 10 0 0 1 0-20m0 2a8 8 0 1 0 0 16 8 8 0 0 0 0-16z"),
};

const STYLE = `
  :host {
    --hb-bg: var(--primary-background-color, #111);
    --hb-surface: var(--card-background-color, var(--ha-card-background, #1c1c1c));
    --hb-text: var(--primary-text-color, #e1e1e1);
    --hb-muted: var(--secondary-text-color, #9b9b9b);
    --hb-line: var(--divider-color, rgba(127,127,127,.25));
    --hb-accent: var(--primary-color, #03a9f4);
    --hb-error: var(--error-color, #db4437);
    color: var(--hb-text);
    font-family: var(--paper-font-body1_-_font-family, var(--ha-font-family-body, Roboto, sans-serif));
  }
  button { font: inherit; color: inherit; }
  .icon-button {
    background: none; border: 0; border-radius: 50%; width: 40px; height: 40px; padding: 8px;
    cursor: pointer; display: inline-flex; align-items: center; justify-content: center; flex: none;
  }
  .icon-button:hover { background: color-mix(in srgb, var(--hb-text) 10%, transparent); }
  .icon-button:disabled { opacity: .35; cursor: default; background: none; }
  .icon-button svg { width: 24px; height: 24px; fill: currentColor; }
  select, input[type=date] {
    font: inherit; color: var(--hb-text); background: var(--hb-surface);
    border: 1px solid var(--hb-line); border-radius: 8px; padding: 6px 8px; min-height: 36px;
  }
  .segmented { display: inline-flex; border: 1px solid var(--hb-line); border-radius: 18px; overflow: hidden; }
  .segmented button { background: none; border: 0; padding: 6px 14px; cursor: pointer; min-height: 34px; }
  .segmented button.active { background: var(--hb-accent); color: var(--text-primary-color, #fff); }
  .stage { position: relative; background: #000; display: flex; align-items: center; justify-content: center; min-height: 0; overflow: hidden; }
  .stage video { width: 100%; height: 100%; object-fit: contain; display: block; background: #000; }
  .overlay { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; pointer-events: none; }
  .message { background: rgba(0,0,0,.7); color: #fff; padding: 10px 16px; border-radius: 8px; max-width: 80%; text-align: center; }
  .message.error { border-left: 4px solid var(--hb-error); }
  .spinner { width: 42px; height: 42px; border-radius: 50%; border: 4px solid rgba(255,255,255,.25); border-top-color: #fff; animation: spin .9s linear infinite; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .badges { position: absolute; top: 10px; left: 10px; display: flex; gap: 6px; pointer-events: none; }
  .badge { background: rgba(0,0,0,.6); color: #fff; font-size: 12px; padding: 3px 8px; border-radius: 10px; letter-spacing: .02em; }
  .badge.live { background: #e5484d; }
  .clock { position: absolute; top: 10px; right: 10px; background: rgba(0,0,0,.6); color: #fff; font-variant-numeric: tabular-nums; padding: 3px 10px; border-radius: 10px; font-size: 13px; pointer-events: none; }
  .controls { display: flex; align-items: center; gap: 2px; padding: 4px 8px; flex-wrap: wrap; }
  .controls .spacer { flex: 1; }
  .controls .live-button { display: inline-flex; gap: 6px; align-items: center; border: 1px solid var(--hb-line); background: none; border-radius: 18px; padding: 4px 12px 4px 8px; cursor: pointer; min-height: 34px; }
  .controls .live-button svg { width: 18px; height: 18px; fill: #e5484d; }
  .controls .live-button.active { background: #e5484d; color: #fff; border-color: #e5484d; }
  .controls .live-button.active svg { fill: #fff; }
  .timeline { position: relative; user-select: none; touch-action: none; }
  .timeline canvas { width: 100%; height: 100%; display: block; cursor: pointer; }
  .tooltip { position: absolute; top: 2px; transform: translateX(-50%); background: var(--hb-text); color: var(--hb-surface); font-size: 12px; padding: 2px 6px; border-radius: 4px; pointer-events: none; white-space: nowrap; font-variant-numeric: tabular-nums; }
  .legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 12px; color: var(--hb-muted); padding: 0 12px 6px; }
  .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: -1px; background: var(--c); }
  .hint { font-size: 12px; color: var(--hb-muted); padding: 0 12px 4px; }
`;

/* ------------------------------------------------------------------ timeline */

class Timeline {
  constructor(container, onSeek) {
    this.container = container;
    this.onSeek = onSeek;
    this.canvas = document.createElement("canvas");
    this.tip = document.createElement("div");
    this.tip.className = "tooltip";
    this.tip.hidden = true;
    container.append(this.canvas, this.tip);
    this.viewStart = startOfDay(new Date()).getTime();
    this.span = DAY;
    this.recordings = [];
    this.events = [];
    this.playhead = null;
    this.colors = {};
    this.kindName = (k) => k;
    this.eventName = (k) => k;
    this._bind();
    this._resize = new ResizeObserver(() => this.draw());
    this._resize.observe(container);
  }

  destroy() {
    this._resize.disconnect();
  }

  setDay(dayStart) {
    this.dayStart = dayStart.getTime();
    this.span = Math.min(this.span, DAY);
    this.viewStart = this.dayStart;
    if (this.span < DAY) this.center(this.playhead ?? Date.now());
    this.draw();
  }

  center(time) {
    const lo = this.dayStart;
    const hi = this.dayStart + DAY - this.span;
    this.viewStart = Math.max(lo, Math.min(hi, time - this.span / 2));
  }

  zoom(direction, at) {
    const index = ZOOMS.indexOf(this.span);
    const next = ZOOMS[Math.max(0, Math.min(ZOOMS.length - 1, (index < 0 ? 0 : index) + direction))];
    if (next === this.span) return;
    const anchor = at ?? this.playhead ?? this.viewStart + this.span / 2;
    const ratio = (anchor - this.viewStart) / this.span;
    this.span = next;
    this.viewStart = anchor - ratio * next;
    this.center(this.viewStart + next / 2);
    this.draw();
  }

  timeAt(x) {
    const width = this.canvas.clientWidth || 1;
    return this.viewStart + (x / width) * this.span;
  }

  _bind() {
    let drag = null;
    const point = (e) => e.clientX - this.canvas.getBoundingClientRect().left;
    this.canvas.addEventListener("pointerdown", (e) => {
      this.canvas.setPointerCapture(e.pointerId);
      drag = { x: point(e), start: this.viewStart, moved: false };
    });
    this.canvas.addEventListener("pointermove", (e) => {
      const x = point(e);
      if (drag) {
        const dx = x - drag.x;
        if (Math.abs(dx) > 4) drag.moved = true;
        if (drag.moved && this.span < DAY) {
          this.viewStart = drag.start - (dx / this.canvas.clientWidth) * this.span;
          this.center(this.viewStart + this.span / 2);
          this.draw();
        }
      }
      const time = new Date(this.timeAt(x));
      this.tip.hidden = false;
      this.tip.style.left = `${Math.max(30, Math.min(this.canvas.clientWidth - 30, x))}px`;
      this.tip.textContent = clock(time, this.span <= 2 * HOUR);
    });
    this.canvas.addEventListener("pointerup", (e) => {
      if (drag && !drag.moved) this.onSeek(new Date(this.timeAt(point(e))));
      drag = null;
    });
    this.canvas.addEventListener("pointerleave", () => {
      this.tip.hidden = true;
    });
    this.canvas.addEventListener(
      "wheel",
      (e) => {
        e.preventDefault();
        if (Math.abs(e.deltaX) > Math.abs(e.deltaY) && this.span < DAY) {
          this.viewStart += (e.deltaX / this.canvas.clientWidth) * this.span;
          this.center(this.viewStart + this.span / 2);
          this.draw();
        } else {
          this.zoom(e.deltaY < 0 ? 1 : -1, this.timeAt(point(e)));
        }
      },
      { passive: false },
    );
  }

  draw() {
    const canvas = this.canvas;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (!width || !height) return;
    const ratio = window.devicePixelRatio || 1;
    if (canvas.width !== Math.round(width * ratio) || canvas.height !== Math.round(height * ratio)) {
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
    }
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);
    const style = getComputedStyle(this.container);
    const text = style.getPropertyValue("--hb-text").trim() || "#ddd";
    const muted = style.getPropertyValue("--hb-muted").trim() || "#999";
    const line = style.getPropertyValue("--hb-line").trim() || "rgba(127,127,127,.3)";
    const accent = style.getPropertyValue("--hb-accent").trim() || "#03a9f4";
    const x = (t) => ((t - this.viewStart) / this.span) * width;
    const axisY = 22;
    const recY = 30;
    const recH = Math.max(14, Math.round((height - 40) * 0.45));
    const evY = recY + recH + 6;
    const evH = Math.max(10, height - evY - 6);

    // Hour ticks and labels.
    const steps = [5 * 60e3, 15 * 60e3, 30 * 60e3, HOUR, 2 * HOUR, 3 * HOUR, 6 * HOUR];
    const step = steps.find((s) => (s / this.span) * width >= 70) || 6 * HOUR;
    const tzOffset = new Date(this.viewStart).getTimezoneOffset() * 60e3;
    let tick = Math.ceil((this.viewStart - tzOffset) / step) * step + tzOffset;
    ctx.font = "11px sans-serif";
    ctx.textAlign = "center";
    for (; tick <= this.viewStart + this.span; tick += step) {
      const px = Math.round(x(tick)) + 0.5;
      ctx.strokeStyle = line;
      ctx.beginPath();
      ctx.moveTo(px, axisY - 6);
      ctx.lineTo(px, height);
      ctx.stroke();
      ctx.fillStyle = muted;
      ctx.fillText(clock(new Date(tick), false), px, 12);
    }

    // Recordings.
    ctx.fillStyle = line;
    ctx.fillRect(0, recY, width, recH);
    for (const rec of this.recordings) {
      const a = Math.max(0, x(rec.start));
      const b = Math.min(width, x(rec.end));
      if (b < 0 || a > width) continue;
      ctx.fillStyle = KIND_COLORS[rec.kind] || KIND_COLORS.other;
      ctx.fillRect(a, recY, Math.max(1.5, b - a), recH);
    }

    // Events, one marker per detection.
    for (const ev of this.events) {
      const a = x(ev.start);
      const b = x(ev.end);
      if (b < 0 || a > width) continue;
      ctx.fillStyle = EVENT_COLORS[ev.kind] || accent;
      ctx.fillRect(a, evY, Math.max(3, b - a), evH);
    }

    // Now and playhead.
    const now = Date.now();
    if (now > this.viewStart && now < this.viewStart + this.span) {
      ctx.strokeStyle = muted;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(x(now), axisY - 6);
      ctx.lineTo(x(now), height);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    if (this.playhead != null) {
      const px = x(this.playhead);
      if (px >= 0 && px <= width) {
        ctx.strokeStyle = "#e5484d";
        ctx.lineWidth = 2;
        ctx.beginPath();
        ctx.moveTo(px, axisY - 4);
        ctx.lineTo(px, height);
        ctx.stroke();
        ctx.lineWidth = 1;
        ctx.fillStyle = "#e5484d";
        ctx.beginPath();
        ctx.moveTo(px - 5, axisY - 8);
        ctx.lineTo(px + 5, axisY - 8);
        ctx.lineTo(px, axisY - 2);
        ctx.fill();
      }
    }
    ctx.fillStyle = text;
  }
}

/* -------------------------------------------------------------------- player */

/*
 * One camera's video: live (Home Assistant's camera stream) or recordings (a playback
 * session of the integration). Quality "auto" starts low and goes up while playback is
 * smooth and the connection fast; stalls bring it down again.
 */
class Player {
  constructor(host) {
    this.host = host;
    this.video = host.video;
    this.hls = null;
    this.session = null;
    this.mode = "live";
    this.quality = "auto";
    this.level = null; // quality actually playing: low/high (live), original/compatible (recordings)
    this.stalls = [];
    this.token = 0;
    this.video.addEventListener("waiting", () => this._stalled());
    this.video.addEventListener("playing", () => this._smooth());
    this.video.addEventListener("ended", () => this.host.onEnded());
    this._upgradeTimer = null;
    this._keepAlive = null;
  }

  get canHevc() {
    const media = window.MediaSource || window.ManagedMediaSource;
    return Boolean(
      (media && media.isTypeSupported && media.isTypeSupported(HEVC)) ||
        this.video.canPlayType('video/mp4; codecs="hvc1"'),
    );
  }

  async _attach(url, token) {
    this._detach();
    const video = this.video;
    const nativeHls = video.canPlayType("application/vnd.apple.mpegurl");
    if (nativeHls && !window.MediaSource) {
      video.src = url;
    } else {
      const Hls = await loadHls();
      if (token !== this.token) return;
      if (!Hls.isSupported()) {
        video.src = url;
      } else {
        this.hls = new Hls({
          lowLatencyMode: this.mode === "live",
          backBufferLength: 120,
          manifestLoadingMaxRetry: 6,
          levelLoadingMaxRetry: 6,
          fragLoadingMaxRetry: 6,
        });
        this.hls.on(Hls.Events.ERROR, (_e, data) => {
          if (data.fatal) {
            if (data.type === Hls.ErrorTypes.MEDIA_ERROR) this.hls.recoverMediaError();
            else this.host.showError("playback_failed");
          }
        });
        this.hls.loadSource(url);
        this.hls.attachMedia(video);
      }
    }
    video.muted = true;
    try {
      await video.play();
    } catch (_err) {
      /* autoplay may need a click */
    }
  }

  _detach() {
    clearTimeout(this._upgradeTimer);
    if (this.hls) {
      this.hls.destroy();
      this.hls = null;
    }
    this.video.removeAttribute("src");
    this.video.load();
  }

  async stop() {
    this.token += 1;
    this._detach();
    clearInterval(this._keepAlive);
    const session = this.session;
    this.session = null;
    if (session) {
      try {
        await this.host.hass.callWS({ type: `${DOMAIN}/playback/stop`, session_id: session.session_id });
      } catch (_err) {
        /* gone already */
      }
    }
  }

  // ---- live

  async live(camera, quality) {
    this.mode = "live";
    this.quality = quality;
    const level = quality === "auto" ? (camera.live.low ? "low" : "high") : quality;
    await this._live(camera, level);
  }

  async _live(camera, level) {
    const entity = camera.live[level] || camera.live.high || camera.live.low;
    const token = ++this.token;
    clearInterval(this._keepAlive);
    if (this.session) this.stop();
    this.token = token;
    if (!entity) {
      this._detach();
      this.host.showError("live_unavailable");
      return;
    }
    this.host.busy(true);
    try {
      const { url } = await this.host.hass.callWS({ type: "camera/stream", entity_id: entity, format: "hls" });
      if (token !== this.token) return;
      this.level = camera.live[level] ? level : camera.live.high ? "high" : "low";
      this.camera = camera;
      await this._attach(url, token);
      this.host.update();
    } catch (err) {
      if (token === this.token) this.host.showError(err.code === "start_stream_failed" ? "playback_encrypted" : "live_unavailable");
    }
  }

  // ---- recordings

  async play(camera, source, time, quality) {
    this.mode = "playback";
    this.quality = quality;
    this.camera = camera;
    this.source = source;
    let level = quality === "auto" ? "original" : quality;
    if (quality === "auto" && camera.codec && camera.codec.includes("265") && !this.canHevc) level = "compatible";
    await this._play(time, level);
  }

  async _play(time, level) {
    const token = ++this.token;
    this.host.busy(true);
    const previous = this.session;
    try {
      const session = await this.host.hass.callWS({
        type: `${DOMAIN}/playback/start`,
        entry_id: this.camera.entry_id,
        channel_id: this.camera.channel_id,
        source: this.source,
        time: new Date(time).toISOString(),
        quality: level,
        ...(previous ? { replace: previous.session_id } : {}),
      });
      if (token !== this.token) {
        this.host.hass.callWS({ type: `${DOMAIN}/playback/stop`, session_id: session.session_id }).catch(() => {});
        return;
      }
      this.session = { ...session, start: new Date(session.start).getTime(), end: new Date(session.end).getTime() };
      this.level = level;
      this.base = null;
      clearInterval(this._keepAlive);
      // Paused players stop asking for the playlist; keep the session alive meanwhile.
      this._keepAlive = setInterval(() => fetch(this.session ? this.session.url : "", { cache: "no-store" }).catch(() => {}), 20e3);
      await this._attach(session.url, token);
      this.host.update();
    } catch (err) {
      if (token !== this.token) return;
      if (previous && this.session === previous) this.session = null;
      this.host.showError(err.code || "playback_failed");
    }
  }

  // Recorded time now shown (ms), from the session start and the video position.
  get position() {
    if (this.mode === "live") return Date.now();
    if (!this.session) return null;
    const video = this.video;
    if (this.base == null && video.buffered.length) this.base = video.buffered.start(0);
    return this.session.start + (video.currentTime - (this.base ?? 0)) * 1000;
  }

  // Seek inside the running session if that part is loaded, else start a new one.
  async seek(time) {
    if (this.mode === "playback" && this.session && this.base != null) {
      const video = this.video;
      const offset = (time - this.session.start) / 1000 + this.base;
      for (let i = 0; i < video.buffered.length; i += 1) {
        if (offset >= video.buffered.start(i) && offset <= video.buffered.end(i) - 0.5) {
          video.currentTime = offset;
          return;
        }
      }
    }
    await this._play(time, this.level || "original");
  }

  // ---- automatic quality

  _stalled() {
    const now = Date.now();
    this.stalls = this.stalls.filter((t) => now - t < 20e3);
    this.stalls.push(now);
    this.host.busy(true);
    if (this.quality !== "auto" || this.mode !== "live" || this.level !== "high") return;
    if (this.stalls.length >= 2 && this.camera.live.low) {
      this.stalls = [];
      this._live(this.camera, "low");
    }
  }

  _smooth() {
    this.host.busy(false);
    clearTimeout(this._upgradeTimer);
    if (this.quality !== "auto" || this.mode !== "live" || this.level !== "low" || !this.camera.live.high) return;
    this._upgradeTimer = setTimeout(() => {
      const recent = this.stalls.filter((t) => Date.now() - t < 20e3).length;
      const bandwidth = this.hls ? this.hls.bandwidthEstimate : null;
      const connection = navigator.connection && navigator.connection.downlink;
      const fast = (bandwidth == null || bandwidth > 6e6) && (!connection || connection >= 5);
      if (!recent && fast && !this.video.paused) this._live(this.camera, "high");
    }, 6000);
  }
}

/* ------------------------------------------------------------------- viewer */

/*
 * Video, controls and timeline of one camera. Used by the card on its own and by the
 * panel next to its camera list.
 */
class Viewer {
  constructor(root, hass, options = {}) {
    this.root = root;
    this.hass = hass;
    this.compact = Boolean(options.compact);
    this.t = makeTranslator({});
    this.camera = null;
    this.source = null;
    this.mode = "live";
    this.quality = "auto";
    this.day = startOfDay(new Date());
    this.data = { recordings: [], events: [] };
    root.innerHTML = `
      <div class="viewer">
        <div class="stage">
          <video playsinline muted></video>
          <div class="badges"></div>
          <div class="clock" hidden></div>
          <div class="overlay"></div>
        </div>
        <div class="controls">
          <button class="icon-button" data-action="prev">${ICONS.prev}</button>
          <button class="icon-button" data-action="back">${ICONS.back}</button>
          <button class="icon-button" data-action="toggle">${ICONS.pause}</button>
          <button class="icon-button" data-action="forward">${ICONS.forward}</button>
          <button class="icon-button" data-action="next">${ICONS.next}</button>
          <button class="live-button" data-action="live">${ICONS.live}<span></span></button>
          <span class="spacer"></span>
          <select class="source" hidden></select>
          <select class="quality"></select>
          <button class="icon-button" data-action="download">${ICONS.download}</button>
          <button class="icon-button" data-action="fullscreen">${ICONS.fullscreen}</button>
        </div>
        <div class="day-bar">
          <button class="icon-button" data-action="day-prev">${ICONS.left}</button>
          <input type="date" class="day">
          <button class="icon-button" data-action="day-next">${ICONS.right}</button>
          <button class="today" data-action="today"></button>
          <span class="spacer"></span>
          <button class="icon-button" data-action="zoom-out">${ICONS.minus}</button>
          <button class="icon-button" data-action="zoom-in">${ICONS.plus}</button>
        </div>
        <div class="timeline"></div>
        <div class="legend"></div>
        <div class="hint" hidden></div>
      </div>`;
    this.video = root.querySelector("video");
    this.player = new Player(this);
    this.timeline = new Timeline(root.querySelector(".timeline"), (date) => this.seek(date));
    root.querySelector(".controls").addEventListener("click", (e) => this._click(e));
    root.querySelector(".day-bar").addEventListener("click", (e) => this._click(e));
    root.querySelector(".quality").addEventListener("change", (e) => this.setQuality(e.target.value));
    root.querySelector(".source").addEventListener("change", (e) => {
      this.source = e.target.value;
      this.loadTimeline();
      if (this.mode === "playback") this.seek(new Date(this.player.position ?? Date.now()));
    });
    root.querySelector(".day").addEventListener("change", (e) => {
      if (e.target.value) this.setDay(new Date(`${e.target.value}T00:00:00`));
    });
    this.video.addEventListener("pause", () => this.update());
    this.video.addEventListener("play", () => this.update());
    this._tick = setInterval(() => this._frame(), 250);
    this._refresh = setInterval(() => {
      if (isoDay(this.day) === isoDay(new Date())) this.loadTimeline();
    }, 60e3);
    loadTexts(hass).then((resources) => {
      this.t = makeTranslator(resources);
      this._label();
      this.update();
    });
    this._label();
  }

  destroy() {
    clearInterval(this._tick);
    clearInterval(this._refresh);
    this.timeline.destroy();
    this.player.stop();
  }

  _label() {
    const t = this.t.ui;
    const titles = {
      prev: "previous_event",
      back: "back",
      forward: "forward",
      next: "next_event",
      download: "download",
      fullscreen: "fullscreen",
      "day-prev": "previous_day",
      "day-next": "next_day",
      "zoom-in": "zoom_in",
      "zoom-out": "zoom_out",
    };
    for (const [action, key] of Object.entries(titles)) {
      const button = this.root.querySelector(`[data-action="${action}"]`);
      button.title = t(key);
      button.setAttribute("aria-label", t(key));
    }
    this.root.querySelector(".live-button span").textContent = t("live");
    this.root.querySelector(".today").textContent = t("today");
    this._qualityOptions();
    this._legend();
  }

  _qualityOptions() {
    const select = this.root.querySelector(".quality");
    const t = this.t.ui;
    const options = this.mode === "live" ? ["auto", "low", "high"] : ["auto", "original", "compatible"];
    if (!options.includes(this.quality)) this.quality = "auto";
    select.innerHTML = options.map((o) => `<option value="${o}">${t("quality")}: ${t(o)}</option>`).join("");
    select.value = this.quality;
  }

  _legend() {
    const kinds = [...new Set(this.data.recordings.map((r) => r.kind))];
    const events = [...new Set(this.data.events.map((e) => e.kind))];
    this.root.querySelector(".legend").innerHTML = [
      ...kinds.map((k) => `<span style="--c:${KIND_COLORS[k] || KIND_COLORS.other}">${this.t.kind(k)}</span>`),
      ...events.map((k) => `<span style="--c:${EVENT_COLORS[k] || "var(--hb-accent)"}">${this.t.event(k)}</span>`),
    ].join("");
  }

  setHass(hass) {
    this.hass = hass;
  }

  async setCamera(camera) {
    if (this.camera && camera && this.camera.entry_id === camera.entry_id && this.camera.channel_id === camera.channel_id) return;
    await this.player.stop();
    this.camera = camera;
    if (!camera) {
      this.showMessage(this.t.ui("select_camera"));
      return;
    }
    this.source = camera.sources[0] || null;
    const select = this.root.querySelector(".source");
    select.hidden = camera.sources.length < 2;
    select.innerHTML = camera.sources.map((s) => `<option value="${s}">${this.t.ui("source")}: ${this.t.source(s)}</option>`).join("");
    this.data = { recordings: [], events: [] };
    this.loadTimeline();
    this.goLive();
  }

  setDay(day) {
    this.day = startOfDay(day);
    this.root.querySelector(".day").value = isoDay(this.day);
    this.timeline.setDay(this.day);
    this.loadTimeline();
  }

  async loadTimeline() {
    const camera = this.camera;
    if (!camera) return;
    const day = this.day;
    if (this.timeline.dayStart !== day.getTime()) this.timeline.setDay(day);
    this.root.querySelector(".day").value = isoDay(day);
    try {
      const result = await this.hass.callWS({
        type: `${DOMAIN}/timeline`,
        entry_id: camera.entry_id,
        channel_id: camera.channel_id,
        source: this.source || "auto",
        start: day.toISOString(),
        end: new Date(day.getTime() + DAY).toISOString(),
      });
      if (camera !== this.camera || day !== this.day) return;
      const parse = (list) => list.map((i) => ({ ...i, start: new Date(i.start).getTime(), end: new Date(i.end).getTime() }));
      this.data = { recordings: parse(result.recordings), events: parse(result.events) };
    } catch (_err) {
      this.data = { recordings: [], events: [] };
    }
    this.timeline.recordings = this.data.recordings;
    this.timeline.events = this.data.events;
    this.timeline.draw();
    this._legend();
    this._hint();
  }

  _hint() {
    const hint = this.root.querySelector(".hint");
    let text = "";
    if (this.camera && !this.camera.sources.length) text = "";
    else if (this.camera && !this.data.recordings.length) text = this.t.ui("no_recordings");
    else if (this.mode === "playback" && this.player.level === "original" && this.camera?.codec?.includes("265") && !this.player.canHevc)
      text = this.t.ui("hevc_hint");
    hint.textContent = text;
    hint.hidden = !text;
  }

  async goLive() {
    this.mode = "live";
    this._qualityOptions();
    this.clearMessage();
    if (isoDay(this.day) !== isoDay(new Date())) this.setDay(new Date());
    await this.player.live(this.camera, this.quality);
    this.update();
  }

  async seek(date) {
    if (!this.camera || !this.camera.sources.length) return;
    if (date.getTime() > Date.now()) return this.goLive();
    const wasLive = this.mode === "live";
    this.mode = "playback";
    if (wasLive) {
      await this.player.stop();
      this._qualityOptions();
    }
    this.clearMessage();
    this.timeline.playhead = date.getTime();
    this.timeline.draw();
    if (wasLive || !this.player.session) await this.player.play(this.camera, this.source, date.getTime(), this.quality);
    else await this.player.seek(date.getTime());
    this.update();
  }

  setQuality(quality) {
    this.quality = quality;
    if (!this.camera) return;
    if (this.mode === "live") this.player.live(this.camera, quality);
    else this.player.play(this.camera, this.source, this.player.position ?? Date.now(), quality);
  }

  onEnded() {
    // End of a stretch of recordings: continue with the next one.
    if (this.mode !== "playback" || !this.player.session) return;
    const next = this.data.recordings.find((r) => r.start > this.player.session.end - 1000);
    if (next) this.player.play(this.camera, this.source, next.start, this.quality);
  }

  _click(e) {
    const action = e.target.closest("[data-action]")?.dataset.action;
    if (!action) return;
    const position = this.player.position ?? Date.now();
    const events = this.data.events.length ? this.data.events : this.data.recordings;
    switch (action) {
      case "toggle":
        if (this.video.paused) this.video.play().catch(() => {});
        else this.video.pause();
        break;
      case "back":
        this.seek(new Date(position - 10e3));
        break;
      case "forward":
        this.seek(new Date(position + 10e3));
        break;
      case "prev": {
        const prev = [...events].reverse().find((ev) => ev.start < position - 2000);
        if (prev) this.seek(new Date(prev.start));
        break;
      }
      case "next": {
        const next = events.find((ev) => ev.start > position + 1000);
        if (next) this.seek(new Date(next.start));
        break;
      }
      case "live":
        this.goLive();
        break;
      case "download":
        this._download(position);
        break;
      case "fullscreen": {
        const stage = this.root.querySelector(".stage");
        if (document.fullscreenElement) document.exitFullscreen();
        else if (stage.requestFullscreen) stage.requestFullscreen();
        else if (this.video.webkitEnterFullscreen) this.video.webkitEnterFullscreen();
        break;
      }
      case "day-prev":
        this.setDay(new Date(this.day.getTime() - DAY / 2));
        break;
      case "day-next":
        if (this.day.getTime() + DAY <= Date.now()) this.setDay(new Date(this.day.getTime() + DAY * 1.5));
        break;
      case "today":
        this.setDay(new Date());
        break;
      case "zoom-in":
        this.timeline.zoom(1);
        break;
      case "zoom-out":
        this.timeline.zoom(-1);
        break;
      default:
    }
  }

  async _download(position) {
    const recording =
      this.data.recordings.find((r) => r.start <= position && r.end > position) ||
      this.data.recordings.find((r) => r.start > position);
    if (!recording || !this.camera) return;
    const path = `/api/${DOMAIN}/recording/${this.camera.entry_id}/${this.camera.channel_id}/${this.source}/mp4/${recording.token}?download=1`;
    const signed = await this.hass.callWS({ type: "auth/sign_path", path, expires: 3600 });
    const link = document.createElement("a");
    link.href = signed.path;
    link.download = "";
    document.body.appendChild(link);
    link.click();
    link.remove();
  }

  // ---- state shown

  busy(on) {
    this._busy = on;
    this._overlay();
  }

  showError(code) {
    this._busy = false;
    this._error = this.t.ui(code);
    this._overlay();
  }

  showMessage(text) {
    this._error = null;
    this._message = text;
    this._overlay();
  }

  clearMessage() {
    this._error = null;
    this._message = null;
    this._overlay();
  }

  _overlay() {
    const overlay = this.root.querySelector(".overlay");
    if (this._error) overlay.innerHTML = `<div class="message error">${this._error}</div>`;
    else if (this._message) overlay.innerHTML = `<div class="message">${this._message}</div>`;
    else if (this._busy) overlay.innerHTML = `<div class="spinner"></div>`;
    else overlay.innerHTML = "";
  }

  update() {
    const live = this.mode === "live";
    const t = this.t.ui;
    this.root.querySelector(".live-button").classList.toggle("active", live);
    const toggle = this.root.querySelector('[data-action="toggle"]');
    toggle.innerHTML = this.video.paused ? ICONS.play : ICONS.pause;
    toggle.title = t(this.video.paused ? "play" : "pause");
    const recorded = Boolean(this.camera && this.camera.sources.length);
    for (const action of ["prev", "back", "next", "download"]) {
      this.root.querySelector(`[data-action="${action}"]`).disabled = !recorded;
    }
    this.root.querySelector('[data-action="forward"]').disabled = !recorded || live;
    const badges = [];
    if (live) badges.push(`<span class="badge live">${t("live")}</span>`);
    if (this.player.level) {
      const level = t(this.player.level === "low" ? "low" : this.player.level);
      badges.push(`<span class="badge">${this.quality === "auto" ? `${t("auto")} · ` : ""}${level}</span>`);
    }
    this.root.querySelector(".badges").innerHTML = badges.join("");
    this._hint();
  }

  _frame() {
    const position = this.player.position;
    const clockEl = this.root.querySelector(".clock");
    if (position != null && this.camera) {
      const date = new Date(position);
      clockEl.hidden = false;
      clockEl.textContent = `${isoDay(date) === isoDay(new Date()) ? "" : `${date.toLocaleDateString()} `}${clock(date)}`;
      if (this.mode === "playback" || isoDay(this.day) === isoDay(new Date())) {
        this.timeline.playhead = position;
        // Follow the playhead when zoomed in.
        if (this.timeline.span < DAY) {
          const { viewStart, span } = this.timeline;
          if (position < viewStart || position > viewStart + span * 0.9) this.timeline.center(position);
        }
        this.timeline.draw();
      }
      if (this.mode === "playback" && this.player.session && position >= this.player.session.end - 500 && !this.video.paused) {
        this.video.pause();
        this.onEnded();
      }
    } else {
      clockEl.hidden = true;
    }
  }
}

/* -------------------------------------------------------------------- panel */

class HikvisionBridgePanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this.cameras = [];
    this.selected = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._build();
    else if (this.viewer) this.viewer.setHass(hass);
    this._thumbs();
  }

  get hass() {
    return this._hass;
  }

  set narrow(value) {
    this._narrow = value;
    this.toggleAttribute("narrow", Boolean(value));
  }

  connectedCallback() {
    if (this._hass && !this.viewer) this._build();
  }

  disconnectedCallback() {
    if (this.viewer) this.viewer.destroy();
    this.viewer = null;
    clearInterval(this._thumbTimer);
  }

  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        ${STYLE}
        :host { display: block; height: 100%; background: var(--hb-bg); }
        .layout { display: grid; grid-template-columns: 280px 1fr; grid-template-rows: 56px 1fr; height: 100vh; height: 100dvh; }
        header { grid-column: 1 / -1; display: flex; align-items: center; gap: 8px; padding: 0 12px; background: var(--app-header-background-color, var(--hb-surface)); color: var(--app-header-text-color, var(--hb-text)); border-bottom: 1px solid var(--hb-line); }
        header h1 { font-size: 20px; font-weight: 400; margin: 0 0 0 4px; }
        header .menu { display: none; }
        :host([narrow]) header .menu { display: inline-flex; }
        aside { overflow-y: auto; border-right: 1px solid var(--hb-line); background: var(--hb-surface); }
        aside h2 { font-size: 12px; text-transform: uppercase; letter-spacing: .08em; color: var(--hb-muted); margin: 14px 16px 8px; font-weight: 500; }
        .cam { display: flex; gap: 10px; align-items: center; width: 100%; padding: 8px 12px; background: none; border: 0; border-left: 3px solid transparent; cursor: pointer; text-align: left; }
        .cam:hover { background: color-mix(in srgb, var(--hb-text) 6%, transparent); }
        .cam.active { border-left-color: var(--hb-accent); background: color-mix(in srgb, var(--hb-accent) 12%, transparent); }
        .cam img, .cam .noimg { width: 96px; height: 54px; object-fit: cover; border-radius: 6px; background: #000; flex: none; }
        .cam .name { font-size: 14px; }
        .cam .sub { font-size: 12px; color: var(--hb-muted); }
        .cam.offline { opacity: .5; }
        main { display: flex; flex-direction: column; min-height: 0; min-width: 0; }
        .viewer { display: flex; flex-direction: column; height: 100%; min-height: 0; }
        .stage { flex: 1; }
        .controls, .day-bar { background: var(--hb-surface); }
        .controls { border-top: 1px solid var(--hb-line); }
        .day-bar { display: flex; align-items: center; gap: 4px; padding: 0 8px; }
        .day-bar .spacer { flex: 1; }
        .today { background: none; border: 1px solid var(--hb-line); border-radius: 16px; padding: 4px 12px; cursor: pointer; margin-left: 4px; min-height: 32px; }
        .timeline { height: 96px; background: var(--hb-surface); padding: 0 12px; }
        .legend, .hint { background: var(--hb-surface); }
        .empty { padding: 24px; color: var(--hb-muted); }
        @media (max-width: 860px) {
          .layout { grid-template-columns: 1fr; grid-template-rows: 56px auto 1fr; }
          aside { border-right: 0; border-bottom: 1px solid var(--hb-line); display: flex; overflow-x: auto; overflow-y: hidden; }
          aside h2 { display: none; }
          .cam { flex-direction: column; width: auto; min-width: 112px; border-left: 0; border-bottom: 3px solid transparent; padding: 8px; text-align: center; }
          .cam.active { border-bottom-color: var(--hb-accent); }
          .cam .sub { display: none; }
          .timeline { height: 84px; }
        }
      </style>
      <div class="layout">
        <header>
          <button class="icon-button menu" title="Menu">${ICONS.menu}</button>
          <h1>Hikvision</h1>
        </header>
        <aside><h2></h2><div class="list"></div></aside>
        <main></main>
      </div>`;
    this.shadowRoot.querySelector(".menu").addEventListener("click", () => {
      this.dispatchEvent(new Event("hass-toggle-menu", { bubbles: true, composed: true }));
    });
    this.viewer = new Viewer(this.shadowRoot.querySelector("main"), this._hass);
    loadTexts(this._hass).then((r) => {
      this.shadowRoot.querySelector("aside h2").textContent = makeTranslator(r).ui("cameras");
    });
    this._load();
    this._thumbTimer = setInterval(() => this._thumbs(true), 10e3);
  }

  async _load() {
    let cameras = [];
    try {
      ({ cameras } = await this._hass.callWS({ type: `${DOMAIN}/cameras` }));
    } catch (_err) {
      /* integration not loaded */
    }
    this.cameras = cameras;
    const list = this.shadowRoot.querySelector(".list");
    if (!cameras.length) {
      list.innerHTML = `<div class="empty">${TEXT.no_cameras}</div>`;
      this.viewer.setCamera(null);
      return;
    }
    const devices = new Set(cameras.map((c) => c.entry_id)).size;
    list.innerHTML = cameras
      .map(
        (c, i) => `
        <button class="cam${c.online ? "" : " offline"}" data-index="${i}">
          <img alt="" loading="lazy">
          <span><div class="name"></div><div class="sub"></div></span>
        </button>`,
      )
      .join("");
    list.querySelectorAll(".cam").forEach((button, i) => {
      const camera = cameras[i];
      button.querySelector(".name").textContent = camera.name;
      button.querySelector(".sub").textContent = [devices > 1 ? camera.device : null, camera.resolution].filter(Boolean).join(" · ");
      button.addEventListener("click", () => this._select(i));
    });
    const saved = (() => {
      try {
        return localStorage.getItem("hikvision-bridge-camera");
      } catch (_err) {
        return null;
      }
    })();
    const index = Math.max(0, cameras.findIndex((c) => `${c.entry_id}/${c.channel_id}` === saved));
    this._select(index);
    this._thumbs(true);
  }

  _select(index) {
    const camera = this.cameras[index];
    this.shadowRoot.querySelectorAll(".cam").forEach((b, i) => b.classList.toggle("active", i === index));
    try {
      localStorage.setItem("hikvision-bridge-camera", `${camera.entry_id}/${camera.channel_id}`);
    } catch (_err) {
      /* private mode */
    }
    this.viewer.setCamera(camera);
  }

  _thumbs(refresh = false) {
    if (!this.shadowRoot || !this.cameras.length) return;
    this.shadowRoot.querySelectorAll(".cam").forEach((button, i) => {
      const camera = this.cameras[i];
      const entity = camera.live.low || camera.live.high;
      const state = entity && this._hass.states[entity];
      const img = button.querySelector("img");
      if (!state || !state.attributes.entity_picture) return;
      if (!img.src || refresh) img.src = `${state.attributes.entity_picture}&t=${Math.floor(Date.now() / 10e3)}`;
    });
  }
}

/* --------------------------------------------------------------------- card */

class HikvisionBridgeCard extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
  }

  static getStubConfig(hass) {
    const camera = Object.keys(hass.states).find(
      (id) => id.startsWith("camera.") && hass.entities?.[id]?.platform === DOMAIN,
    );
    return { camera_entity: camera || "" };
  }

  setConfig(config) {
    if (!config || !config.camera_entity) throw new Error("camera_entity is required");
    this.config = config;
    if (this.viewer) this._pick();
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 12, min_columns: 6, rows: 7, min_rows: 5 };
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first) this._build();
    else if (this.viewer) this.viewer.setHass(hass);
  }

  disconnectedCallback() {
    if (this.viewer) this.viewer.destroy();
    this.viewer = null;
  }

  connectedCallback() {
    if (this._hass && !this.viewer) this._build();
  }

  _build() {
    this.shadowRoot.innerHTML = `
      <style>
        ${STYLE}
        ha-card, .card { overflow: hidden; height: 100%; display: flex; flex-direction: column; }
        .viewer { display: flex; flex-direction: column; flex: 1; min-height: 0; }
        .stage { aspect-ratio: 16 / 9; flex: 1; }
        .day-bar { display: flex; align-items: center; gap: 2px; padding: 0 4px; }
        .day-bar .spacer { flex: 1; }
        .today { background: none; border: 1px solid var(--hb-line); border-radius: 16px; padding: 2px 10px; cursor: pointer; }
        .controls select { max-width: 46%; }
        .timeline { height: 72px; padding: 0 8px; }
      </style>
      <ha-card><div class="card"></div></ha-card>`;
    this.viewer = new Viewer(this.shadowRoot.querySelector(".card"), this._hass, { compact: true });
    this._pick();
  }

  async _pick() {
    let cameras = [];
    try {
      ({ cameras } = await this._hass.callWS({ type: `${DOMAIN}/cameras` }));
    } catch (_err) {
      /* integration not loaded */
    }
    const wanted = this.config.camera_entity;
    const camera = cameras.find((c) => c.live.high === wanted || c.live.low === wanted);
    if (camera) this.viewer.setCamera(camera);
    else this.viewer.showMessage(`${wanted}: ${TEXT.live_unavailable}`);
  }
}

if (!customElements.get("hikvision-bridge-panel")) customElements.define("hikvision-bridge-panel", HikvisionBridgePanel);
if (!customElements.get("hikvision-bridge-card")) {
  customElements.define("hikvision-bridge-card", HikvisionBridgeCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "hikvision-bridge-card",
    name: "Hikvision recordings",
    description: "Live view and recordings of a Hikvision Bridge camera with a timeline.",
    preview: false,
  });
}
