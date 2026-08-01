// spectrum_waterfall.js -- real audio-spectrum waterfall, alongside (not
// replacing) the decode-based one in waterfall.js. Fed by audio_spectrum.py's
// spectrum_4hz/spectrum_1hz broadcasts (200 Hz-3 kHz @ 4 Hz/bin). Uses a
// classic scroll-the-existing-image-down-by-one-row technique rather than
// redrawing full history every frame (what waterfall.js does, fine for its
// handful of sparse rows, but not for a dense continuous spectrogram that
// can be updating 4x/sec) -- each new row is drawn once, cheaply.
function createSpectrumWaterfall(canvas) {
  const ctx = canvas.getContext('2d');
  const ROW_H = 1;
  let numBins = 0;

  // Duration shown is configured in seconds rather than rows, since the two
  // spectrum modes push rows at different rates (4/sec vs ~1/sec) -- the
  // pixel height needed for e.g. "20 seconds" differs between them, so the
  // caller tells us the active mode's rate via setRate() (also applied on
  // mode switch) and we recompute canvas.height from seconds * rate.
  const MIN_SEC = 2, MAX_SEC = 120;
  let seconds = 20;
  let rate = 4;

  // Fixed dB range for the color ramp -- tuned against real captured
  // levels this session (typical floor ~-30dB, strong signal peaks
  // ~+20dB); may need further live tuning once watched for a while.
  const DB_LO = -35, DB_HI = 15;

  function dbColor(db) {
    const t = Math.max(0, Math.min(1, (db - DB_LO) / (DB_HI - DB_LO)));
    const stops = [
      [0.0, [10, 20, 90]], [0.35, [20, 90, 200]], [0.6, [80, 220, 220]],
      [0.8, [255, 230, 40]], [1.0, [230, 30, 20]],
    ];
    for (let i = 0; i < stops.length - 1; i++) {
      const [t0, c0] = stops[i], [t1, c1] = stops[i + 1];
      if (t <= t1 || i === stops.length - 2) {
        const f = Math.max(0, Math.min(1, (t - t0) / (t1 - t0 || 1)));
        const c = c0.map((v, k) => Math.round(v + (c1[k] - v) * f));
        return `rgb(${c[0]},${c[1]},${c[2]})`;
      }
    }
    return 'rgb(230,30,20)';
  }

  function clear() {
    ctx.fillStyle = '#07143a';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  function ensureWidth(n) {
    if (numBins !== n) {
      numBins = n;
      canvas.width = n; // one canvas pixel per bin -- CSS scales it to fit
      clear();
    }
  }

  function pushRow(bins) {
    ensureWidth(bins.length);
    // Shift the existing image down by one row, then draw the new row at
    // the top -- newest at top, matches waterfall.js's convention.
    ctx.drawImage(canvas, 0, 0, canvas.width, canvas.height - ROW_H, 0, ROW_H, canvas.width, canvas.height - ROW_H);
    for (let x = 0; x < bins.length; x++) {
      ctx.fillStyle = dbColor(bins[x]);
      ctx.fillRect(x, 0, 1, ROW_H);
    }
  }

  function applyHeight() {
    canvas.height = Math.max(2, Math.round(seconds * rate)); // resizing a canvas clears it -- accepted, simplest
    clear();
  }

  function setRate(rowsPerSec) {
    rate = rowsPerSec;
    applyHeight();
  }

  function setSeconds(newSeconds) {
    seconds = Math.max(MIN_SEC, Math.min(MAX_SEC, newSeconds || seconds));
    applyHeight();
    return seconds;
  }

  clear();
  return { pushRow, clear, setRate, setSeconds, get seconds() { return seconds; } };
}
