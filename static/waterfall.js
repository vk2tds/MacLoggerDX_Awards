// waterfall.js -- decode-based waterfall renderer, shared by the embedded
// panel on the Remote tab and the standalone Waterfall tab. WSJT-X's UDP
// API carries no spectrum/noise-floor data, so this only plots what
// WSJT-X actually decoded (colored by SNR), one row per decode cycle --
// not a true spectrogram.
function createWaterfall(canvas, opts) {
  const ctx = canvas.getContext('2d');
  const WF_W = canvas.width;
  const ROW_H = 22;
  const RULER_H = 16;
  const FREQ_MAX = 3000;
  const MAX_ROWS = 120;
  const MIN_ROWS = 2;
  let rows = Math.max(MIN_ROWS, Math.min(MAX_ROWS, (opts && opts.rows) || 16));
  let data = [];

  function freqToX(hz) {
    return Math.max(0, Math.min(WF_W, (hz / FREQ_MAX) * WF_W));
  }

  function snrColor(snr) {
    const s = Math.max(-24, Math.min(6, (snr === null || snr === undefined) ? -24 : snr));
    const stops = [
      [-24, [10, 20, 90]], [-15, [20, 90, 200]], [-6, [80, 220, 220]],
      [0, [255, 230, 40]], [6, [230, 30, 20]],
    ];
    for (let i = 0; i < stops.length - 1; i++) {
      const [t0, c0] = stops[i], [t1, c1] = stops[i + 1];
      if (s <= t1 || i === stops.length - 2) {
        const f = Math.max(0, Math.min(1, (s - t0) / (t1 - t0 || 1)));
        const c = c0.map((v, k) => Math.round(v + (c1[k] - v) * f));
        return `rgb(${c[0]},${c[1]},${c[2]})`;
      }
    }
    return 'rgb(230,30,20)';
  }

  function fmtTime(ms) {
    if (ms === null || ms === undefined) return '';
    const totalSec = Math.floor(ms / 1000);
    const h = String(Math.floor(totalSec / 3600) % 24).padStart(2, '0');
    const m = String(Math.floor(totalSec / 60) % 60).padStart(2, '0');
    const s = String(totalSec % 60).padStart(2, '0');
    return `${h}:${m}:${s}`;
  }

  function draw() {
    ctx.fillStyle = '#07143a';
    ctx.fillRect(0, 0, WF_W, canvas.height);

    ctx.strokeStyle = 'rgba(255,255,255,0.08)';
    ctx.lineWidth = 1;
    for (let hz = 0; hz <= FREQ_MAX; hz += 500) {
      const x = Math.round(freqToX(hz)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(x, RULER_H);
      ctx.lineTo(x, canvas.height);
      ctx.stroke();
    }

    data.forEach((row, i) => {
      const y = RULER_H + i * ROW_H;
      row.decodes.forEach(d => {
        if (d.freq === null || d.freq === undefined) return;
        ctx.fillStyle = snrColor(d.snr);
        ctx.fillRect(Math.max(0, freqToX(d.freq) - 3), y + 1, 7, ROW_H - 2);
      });
      ctx.fillStyle = 'rgba(255,255,255,0.85)';
      ctx.font = '10px ui-monospace, Menlo, monospace';
      ctx.textBaseline = 'top';
      ctx.fillText(fmtTime(row.timeMs), 4, y + 5);
    });

    ctx.fillStyle = '#1a2a5a';
    ctx.fillRect(0, 0, WF_W, RULER_H);
    ctx.fillStyle = '#cfe0ff';
    ctx.font = '10px ui-monospace, Menlo, monospace';
    ctx.textBaseline = 'top';
    for (let hz = 0; hz <= FREQ_MAX; hz += 500) {
      ctx.fillText(String(hz), Math.min(freqToX(hz) + 2, WF_W - 32), 3);
    }
  }

  function onDecode(ev) {
    if (ev.delta_freq_hz === null || ev.delta_freq_hz === undefined) return;
    if (!data.length || data[0].timeMs !== ev.time_ms) {
      data.unshift({ timeMs: ev.time_ms, decodes: [] });
      if (data.length > rows) data.length = rows;
    }
    data[0].decodes.push({ freq: ev.delta_freq_hz, snr: ev.snr });
    draw();
  }

  function clear() {
    data = [];
    draw();
  }

  function resize(newRows) {
    rows = Math.max(MIN_ROWS, Math.min(MAX_ROWS, newRows || rows));
    canvas.height = RULER_H + rows * ROW_H;
    if (data.length > rows) data.length = rows;
    draw();
    return rows;
  }

  resize(rows);
  return { onDecode, clear, resize, get rows() { return rows; } };
}
