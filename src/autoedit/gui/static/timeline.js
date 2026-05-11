/**
 * AutoEdit Timeline Editor
 * ========================
 * Interactive Canvas-based timeline for editing Twitch clip EditDecisions.
 *
 * Tracks:
 *   - Trim    : draggable in/out handles define the rendered clip range
 *   - Zooms   : ZoomEvent blocks (duration + intensity)
 *   - Memes   : MemeOverlay blocks (asset + duration)
 *   - SFX     : SfxCue vertical pins
 *   - Narración: NarrationCue blocks (text)
 *
 * Communication:
 *   Python → JS : window.timelineAPI.setData(data)
 *   JS → Python : fetch('/api/gui/timeline/update', { method:'POST', body:JSON.stringify(data) })
 *                 fetch('/api/gui/timeline/select', { method:'POST', body:JSON.stringify(sel) })
 */

// ── Constants ───────────────────────────────────────────────────────────────

const LABEL_W   = 118;   // px — left label column width
const RULER_H   = 32;    // px — ruler height
const TRACK_H   = 46;    // px — each track height
const TRACK_GAP = 3;     // px — gap between tracks
const HANDLE_R  = 5;     // px — trim handle circle radius

const TRACK_DEFS = [
  { key: 'trim',      label: 'Trim',      color: '#60a5fa', type: 'trim'  },
  { key: 'zoom',      label: 'Zooms',     color: '#34d399', type: 'block' },
  { key: 'meme',      label: 'Memes',     color: '#f472b6', type: 'block' },
  { key: 'sfx',       label: 'SFX',       color: '#fb923c', type: 'pin'   },
  { key: 'narration', label: 'Narración', color: '#a78bfa', type: 'block' },
];

const DARK = {
  bg:          '#0f172a',
  trackBg:     '#1e293b',
  trackBgAlt:  '#1a2540',
  labelBg:     '#0d1526',
  rulerBg:     '#111827',
  gridLine:    '#1f2d40',
  gridLineMaj: '#2d3f56',
  text:        '#94a3b8',
  textBright:  '#e2e8f0',
  selected:    '#ffffffff',
  dimOverlay:  'rgba(0,0,0,0.55)',
};

// ── TimelineEditor class ─────────────────────────────────────────────────────

class TimelineEditor {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container) {
      console.error('[timeline] Container not found:', containerId);
      return;
    }

    this.data = null;      // EditDecision-like object
    this.pps  = 12;        // pixels per second (recomputed on resize)
    this.scroll = 0;       // horizontal scroll offset (future)

    // Interaction state
    this.selected  = null; // { track, index } | { track:'trim', handle:'start'|'end' }
    this.dragging  = null;
    this.dragStartX = 0;
    this.dragStartVal = 0;
    this.hovered   = null;

    this._buildCanvas();
    this._bindEvents();
    window.addEventListener('resize', () => this._onResize());
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  setData(data) {
    this.data = JSON.parse(JSON.stringify(data)); // deep copy
    this._recomputePPS();
    this._draw();
  }

  getData() {
    return this.data ? JSON.parse(JSON.stringify(this.data)) : null;
  }

  selectEffect(track, index) {
    this.selected = { track, index };
    this._draw();
  }

  clearSelection() {
    this.selected = null;
    this._draw();
  }

  // ── Build ───────────────────────────────────────────────────────────────────

  _buildCanvas() {
    this.canvas = document.createElement('canvas');
    this.canvas.style.cssText = 'width:100%;display:block;cursor:default;border-radius:8px;';
    this.container.appendChild(this.canvas);
    this.ctx = this.canvas.getContext('2d');
    this._onResize();
  }

  _onResize() {
    this._recomputeLayout();
    if (this.data) this._draw();
  }

  _recomputeLayout() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.container.getBoundingClientRect();
    this.cssW = Math.max(rect.width || 600, 400);
    this.cssH = RULER_H + TRACK_DEFS.length * (TRACK_H + TRACK_GAP) + 16;

    this.canvas.style.height = this.cssH + 'px';
    this.canvas.width  = this.cssW * dpr;
    this.canvas.height = this.cssH * dpr;
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    if (this.data) this._recomputePPS();
  }

  _recomputePPS() {
    if (!this.data) return;
    const dur = this.data.duration || 60;
    const availW = this.cssW - LABEL_W - 16;
    this.pps = Math.max(6, availW / dur);
  }

  // ── Draw ────────────────────────────────────────────────────────────────────

  _draw() {
    if (!this.data) return;
    const ctx = this.ctx;
    ctx.clearRect(0, 0, this.cssW, this.cssH);

    // Base background
    ctx.fillStyle = DARK.bg;
    ctx.fillRect(0, 0, this.cssW, this.cssH);

    this._drawRuler();

    TRACK_DEFS.forEach((td, i) => {
      const y = RULER_H + i * (TRACK_H + TRACK_GAP);
      this._drawTrack(td, i, y);
    });
  }

  _drawRuler() {
    const ctx = this.ctx;
    const dur = this.data.duration || 60;

    // Ruler background
    ctx.fillStyle = DARK.rulerBg;
    ctx.fillRect(0, 0, this.cssW, RULER_H);
    ctx.fillStyle = DARK.trackBg;
    ctx.fillRect(LABEL_W, 0, this.cssW - LABEL_W, RULER_H);

    // AutoEdit label in ruler left column
    ctx.fillStyle = '#334155';
    ctx.font = 'bold 11px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText('TIMELINE', LABEL_W / 2, RULER_H / 2 + 4);

    // Tick interval — adapt to pps so labels don't overlap
    let tick = 1;
    if (this.pps < 12) tick = 5;
    if (this.pps < 4)  tick = 10;
    if (this.pps > 60) tick = 0.5;

    ctx.textAlign = 'center';
    ctx.font = '11px monospace';

    for (let t = 0; t <= dur + tick; t += tick) {
      const x = this._tx(t);
      if (x > this.cssW + 2) break;

      const major = Number.isInteger(t) && t % (tick * 5 === 0 ? tick * 5 : tick * 2) === 0;

      // Grid line through all tracks
      ctx.strokeStyle = major ? DARK.gridLineMaj : DARK.gridLine;
      ctx.lineWidth = major ? 1.5 : 0.5;
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, this.cssH);
      ctx.stroke();

      // Tick label
      ctx.fillStyle = major ? DARK.textBright : DARK.text;
      ctx.fillText(this._fmt(t), x, RULER_H - 6);

      // Tick mark
      ctx.strokeStyle = major ? '#475569' : '#2d3f56';
      ctx.lineWidth = major ? 2 : 1;
      ctx.beginPath();
      ctx.moveTo(x, RULER_H - 5);
      ctx.lineTo(x, RULER_H);
      ctx.stroke();
    }

    // Ruler bottom border
    ctx.strokeStyle = '#334155';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, RULER_H);
    ctx.lineTo(this.cssW, RULER_H);
    ctx.stroke();
  }

  _drawTrack(td, idx, y) {
    const ctx = this.ctx;
    const isEven = idx % 2 === 0;

    // Track body background
    ctx.fillStyle = isEven ? DARK.trackBg : DARK.trackBgAlt;
    ctx.fillRect(LABEL_W, y, this.cssW - LABEL_W, TRACK_H);

    // Label column
    ctx.fillStyle = DARK.labelBg;
    ctx.fillRect(0, y, LABEL_W, TRACK_H);

    // Colored left accent bar
    ctx.fillStyle = td.color;
    ctx.fillRect(0, y, 4, TRACK_H);

    // Track label
    ctx.fillStyle = td.color;
    ctx.font = 'bold 12px system-ui';
    ctx.textAlign = 'left';
    ctx.fillText(td.label, 12, y + TRACK_H / 2 + 4);

    // Track content
    if (td.type === 'trim') {
      this._drawTrimTrack(td, y);
    } else if (td.type === 'block') {
      const effects = this._getEffects(td.key);
      effects.forEach((eff, i) => this._drawBlock(td, eff, i, y));
    } else if (td.type === 'pin') {
      const effects = this._getEffects(td.key);
      effects.forEach((eff, i) => this._drawPin(td, eff, i, y));
    }

    // Bottom border
    ctx.strokeStyle = '#1a2a3a';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, y + TRACK_H);
    ctx.lineTo(this.cssW, y + TRACK_H);
    ctx.stroke();
  }

  _drawTrimTrack(td, y) {
    const ctx = this.ctx;
    const { start_sec, end_sec } = this.data.trim;
    const x1 = this._tx(start_sec);
    const x2 = this._tx(end_sec);

    // Dim regions outside trim
    ctx.fillStyle = DARK.dimOverlay;
    ctx.fillRect(LABEL_W, y, x1 - LABEL_W, TRACK_H);
    ctx.fillRect(x2, y, this.cssW - x2, TRACK_H);

    // Active trim region
    ctx.fillStyle = 'rgba(96,165,250,0.18)';
    ctx.fillRect(x1, y, x2 - x1, TRACK_H);

    // Active region border
    ctx.strokeStyle = 'rgba(96,165,250,0.5)';
    ctx.lineWidth = 1;
    ctx.strokeRect(x1, y + 1, x2 - x1, TRACK_H - 2);

    // Duration label
    const dur = end_sec - start_sec;
    if (x2 - x1 > 80) {
      ctx.fillStyle = '#93c5fd';
      ctx.font = '11px monospace';
      ctx.textAlign = 'center';
      ctx.fillText(`${start_sec.toFixed(1)}s → ${end_sec.toFixed(1)}s  (${dur.toFixed(1)}s)`,
        (x1 + x2) / 2, y + TRACK_H / 2 + 4);
    }

    // Trim handles
    const selStart = this.selected?.handle === 'start';
    const selEnd   = this.selected?.handle === 'end';
    this._drawTrimHandle(x1, y, td.color, selStart, '◀');
    this._drawTrimHandle(x2, y, td.color, selEnd,   '▶');
  }

  _drawTrimHandle(x, y, color, selected, arrow) {
    const ctx = this.ctx;
    // Vertical bar
    ctx.fillStyle = selected ? '#ffffff' : color;
    ctx.fillRect(x - 3, y, 6, TRACK_H);

    // Circle handle
    ctx.beginPath();
    ctx.arc(x, y + TRACK_H / 2, HANDLE_R + 2, 0, Math.PI * 2);
    ctx.fillStyle = selected ? '#ffffff' : color;
    ctx.fill();
    ctx.strokeStyle = '#0f172a';
    ctx.lineWidth = 1.5;
    ctx.stroke();

    // Arrow text
    ctx.fillStyle = '#0f172a';
    ctx.font = 'bold 9px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText(arrow, x, y + TRACK_H / 2 + 3);
  }

  _drawBlock(td, eff, idx, y) {
    const ctx = this.ctx;
    const x = this._tx(eff.at_sec);
    const dur = eff.duration_sec ?? 1.5;
    const w = Math.max(dur * this.pps, 24);
    const sel = this._isSelected(td.key, idx);

    const rx = 4; // border-radius

    // Block fill
    ctx.fillStyle = sel ? '#ffffff' : td.color + 'cc';
    this._roundRect(ctx, x, y + 6, w, TRACK_H - 12, rx);
    ctx.fill();

    if (sel) {
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      this._roundRect(ctx, x, y + 6, w, TRACK_H - 12, rx);
      ctx.stroke();
    }

    // Label inside block
    const label = this._blockLabel(td.key, eff);
    ctx.fillStyle = sel ? '#1e293b' : '#0f172a';
    ctx.font = '11px system-ui';
    ctx.textAlign = 'left';
    // Clip text to block width
    ctx.save();
    ctx.rect(x + 4, y, w - 8, TRACK_H);
    ctx.clip();
    ctx.fillText(label, x + 6, y + TRACK_H / 2 + 4);
    ctx.restore();

    // at_sec time label above block
    ctx.fillStyle = DARK.text;
    ctx.font = '9px monospace';
    ctx.textAlign = 'center';
    ctx.fillText(eff.at_sec.toFixed(1) + 's', x + w / 2, y + 5);
  }

  _drawPin(td, eff, idx, y) {
    const ctx = this.ctx;
    const x = this._tx(eff.at_sec);
    const sel = this._isSelected(td.key, idx);
    const color = sel ? '#ffffff' : td.color;

    // Vertical line
    ctx.strokeStyle = color;
    ctx.lineWidth = sel ? 3 : 2;
    ctx.beginPath();
    ctx.moveTo(x, y + 8);
    ctx.lineTo(x, y + TRACK_H - 8);
    ctx.stroke();

    // Diamond head
    ctx.fillStyle = color;
    ctx.beginPath();
    const hy = y + 14;
    ctx.moveTo(x,     hy - 6);
    ctx.lineTo(x + 5, hy);
    ctx.lineTo(x,     hy + 6);
    ctx.lineTo(x - 5, hy);
    ctx.closePath();
    ctx.fill();

    // Short label below
    const label = this._blockLabel(td.key, eff);
    ctx.fillStyle = sel ? '#ffffff' : DARK.text;
    ctx.font = '9px system-ui';
    ctx.textAlign = 'center';
    ctx.fillText(label, x, y + TRACK_H - 4);

    // Time above
    ctx.fillStyle = DARK.text;
    ctx.font = '9px monospace';
    ctx.fillText(eff.at_sec.toFixed(1) + 's', x, y + 5);
  }

  // ── Helpers ─────────────────────────────────────────────────────────────────

  _tx(t) { return LABEL_W + t * this.pps; }
  _xt(x) { return (x - LABEL_W) / this.pps; }

  _fmt(sec) {
    const m = Math.floor(sec / 60);
    const s = (sec % 60).toFixed(0).padStart(2, '0');
    return m > 0 ? `${m}:${s}` : `${sec.toFixed(sec % 1 ? 1 : 0)}s`;
  }

  _roundRect(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.quadraticCurveTo(x + w, y, x + w, y + r);
    ctx.lineTo(x + w, y + h - r);
    ctx.quadraticCurveTo(x + w, y + h, x + w - r, y + h);
    ctx.lineTo(x + r, y + h);
    ctx.quadraticCurveTo(x, y + h, x, y + h - r);
    ctx.lineTo(x, y + r);
    ctx.quadraticCurveTo(x, y, x + r, y);
    ctx.closePath();
  }

  _getEffects(key) {
    if (!this.data) return [];
    const map = {
      zoom:      this.data.zoom_events     || [],
      meme:      this.data.meme_overlays   || [],
      sfx:       this.data.sfx_cues        || [],
      narration: this.data.narration_cues  || [],
    };
    return map[key] || [];
  }

  _blockLabel(key, eff) {
    switch (key) {
      case 'zoom':
        return `${(eff.intensity || 1.5).toFixed(1)}× · ${(eff.duration_sec || 1).toFixed(1)}s`;
      case 'meme':
        return (eff.asset_id || '?').slice(0, 14);
      case 'sfx':
        return (eff.asset_id || '?').slice(0, 12);
      case 'narration':
        const txt = eff.text || '';
        return txt.length > 22 ? txt.slice(0, 22) + '…' : txt;
      default:
        return '';
    }
  }

  _isSelected(track, index) {
    return this.selected &&
           this.selected.track === track &&
           this.selected.index === index;
  }

  // ── Hit testing ─────────────────────────────────────────────────────────────

  _hitTest(mx, my) {
    // Which track row?
    let trackIdx = -1;
    let trackY = RULER_H;
    for (let i = 0; i < TRACK_DEFS.length; i++) {
      if (my >= trackY && my < trackY + TRACK_H) { trackIdx = i; break; }
      trackY += TRACK_H + TRACK_GAP;
    }
    if (trackIdx < 0) return null;

    const td = TRACK_DEFS[trackIdx];
    const t  = this._xt(mx);

    // Trim handles
    if (td.type === 'trim') {
      const sx = this._tx(this.data.trim.start_sec);
      const ex = this._tx(this.data.trim.end_sec);
      if (Math.abs(mx - sx) <= 10) return { track: 'trim', handle: 'start' };
      if (Math.abs(mx - ex) <= 10) return { track: 'trim', handle: 'end'   };
      return null;
    }

    // Effect blocks / pins
    const effects = this._getEffects(td.key);
    for (let i = 0; i < effects.length; i++) {
      const eff = effects[i];
      const ex  = this._tx(eff.at_sec);
      const ew  = Math.max((eff.duration_sec || 1.5) * this.pps, 24);
      if (td.type === 'pin') {
        if (Math.abs(mx - ex) <= 8) return { track: td.key, index: i };
      } else {
        if (mx >= ex - 2 && mx <= ex + ew + 2) return { track: td.key, index: i };
      }
    }
    return null;
  }

  // ── Mouse events ─────────────────────────────────────────────────────────────

  _bindEvents() {
    this.canvas.addEventListener('mousedown',  e => this._onMouseDown(e));
    this.canvas.addEventListener('mousemove',  e => this._onMouseMove(e));
    this.canvas.addEventListener('mouseup',    e => this._onMouseUp(e));
    this.canvas.addEventListener('mouseleave', () => { this.dragging = null; });
    this.canvas.addEventListener('dblclick',   e => this._onDblClick(e));
    this.canvas.addEventListener('contextmenu',e => this._onContextMenu(e));
  }

  _canvasPos(e) {
    const r = this.canvas.getBoundingClientRect();
    return { x: e.clientX - r.left, y: e.clientY - r.top };
  }

  _onMouseDown(e) {
    if (!this.data) return;
    const { x, y } = this._canvasPos(e);
    const hit = this._hitTest(x, y);
    if (!hit) {
      this.selected = null;
      this._draw();
      this._notifySelect(null);
      return;
    }

    this.dragging = hit;
    this.dragStartX = x;

    if (hit.handle) {
      this.dragStartVal = this.data.trim[hit.handle === 'start' ? 'start_sec' : 'end_sec'];
    } else if (hit.index !== undefined) {
      this.dragStartVal = this._getEffects(hit.track)[hit.index].at_sec;
    }

    this.selected = hit;
    this._draw();
    this._notifySelect(hit);
  }

  _onMouseMove(e) {
    if (!this.data) return;
    const { x, y } = this._canvasPos(e);
    const hit = this._hitTest(x, y);

    // Update cursor
    if (hit && (hit.handle || hit.index !== undefined)) {
      this.canvas.style.cursor = 'ew-resize';
    } else if (x < LABEL_W) {
      this.canvas.style.cursor = 'default';
    } else {
      this.canvas.style.cursor = hit ? 'grab' : 'crosshair';
    }

    if (!this.dragging) return;

    const dx  = x - this.dragStartX;
    const dt  = dx / this.pps;
    const dur = this.data.duration || 60;
    const raw = this.dragStartVal + dt;
    const clamped = Math.max(0, Math.min(dur, Math.round(raw * 10) / 10));

    if (this.dragging.handle === 'start') {
      this.data.trim.start_sec = Math.min(clamped, this.data.trim.end_sec - 0.5);
    } else if (this.dragging.handle === 'end') {
      this.data.trim.end_sec = Math.max(clamped, this.data.trim.start_sec + 0.5);
    } else if (this.dragging.index !== undefined) {
      const effs = this._getEffects(this.dragging.track);
      effs[this.dragging.index].at_sec = clamped;
    }

    this._draw();
  }

  _onMouseUp(e) {
    if (this.dragging && this.data) {
      this._sendUpdate();
    }
    this.dragging = null;
  }

  _onDblClick(e) {
    if (!this.data) return;
    const { x, y } = this._canvasPos(e);
    const hit = this._hitTest(x, y);
    if (hit && window._timelineCallbacks?.onDblClick) {
      window._timelineCallbacks.onDblClick(hit);
    }
  }

  _onContextMenu(e) {
    e.preventDefault();
    if (!this.data) return;
    const { x, y } = this._canvasPos(e);
    const hit = this._hitTest(x, y);
    if (hit && window._timelineCallbacks?.onDelete) {
      window._timelineCallbacks.onDelete(hit);
    }
  }

  // ── Server communication ─────────────────────────────────────────────────────

  _sendUpdate() {
    fetch('/api/gui/timeline/update', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(this.data),
    }).catch(err => console.error('[timeline] update failed:', err));
  }

  _notifySelect(hit) {
    const payload = hit ? {
      track: hit.track,
      handle: hit.handle ?? null,
      index: hit.index ?? null,
      effect: this._getSelectedEffect(hit),
    } : null;

    fetch('/api/gui/timeline/select', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).catch(err => console.error('[timeline] select failed:', err));
  }

  _getSelectedEffect(hit) {
    if (!hit || !this.data) return null;
    if (hit.handle) return { ...this.data.trim, _type: 'trim' };
    const effs = this._getEffects(hit.track);
    return hit.index !== undefined ? effs[hit.index] : null;
  }
}

// ── Global API ───────────────────────────────────────────────────────────────

window.timelineAPI = {
  editor: null,

  init(containerId, data) {
    this.editor = new TimelineEditor(containerId);
    if (data) this.editor.setData(data);
    return this.editor;
  },

  setData(data) {
    if (this.editor) this.editor.setData(data);
  },

  getData() {
    return this.editor ? this.editor.getData() : null;
  },

  registerCallbacks(callbacks) {
    window._timelineCallbacks = callbacks;
  },
};
