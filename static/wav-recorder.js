/* Records the microphone as the WAV Muse Voice accepts: RIFF/WAVE, mono, 16-bit PCM, 16 kHz.
   Done in the browser so the server needs no ffmpeg. Works on old Android Chrome (ScriptProcessor). */
(function () {
  const RATE = 16000;
  const MAX_SECONDS = 60;

  function downsample(chunks, inRate) {
    const length = chunks.reduce((n, c) => n + c.length, 0);
    const ratio = inRate / RATE;
    const out = new Int16Array(Math.floor(length / ratio));
    let pos = 0, idx = 0, chunk = 0, offset = 0;
    // Average the input samples that fall into each output sample (a cheap low-pass).
    for (let i = 0; i < out.length; i += 1) {
      const end = Math.floor((i + 1) * ratio);
      let sum = 0, n = 0;
      while (pos < end && chunk < chunks.length) {
        sum += chunks[chunk][offset]; n += 1; pos += 1; offset += 1;
        if (offset >= chunks[chunk].length) { chunk += 1; offset = 0; }
      }
      const s = Math.max(-1, Math.min(1, n ? sum / n : 0));
      out[idx++] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out;
  }

  function wav(samples) {
    const buf = new ArrayBuffer(44 + samples.length * 2);
    const v = new DataView(buf);
    const str = (o, s) => { for (let i = 0; i < s.length; i += 1) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + samples.length * 2, true); str(8, "WAVE");
    str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, RATE, true); v.setUint32(28, RATE * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, samples.length * 2, true);
    new Int16Array(buf, 44).set(samples);
    return new Blob([buf], { type: "audio/wav" });
  }

  async function start(onAutoStop) {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
    const Ctx = window.AudioContext || window.webkitAudioContext;
    const ctx = new Ctx();
    const src = ctx.createMediaStreamSource(stream);
    const proc = ctx.createScriptProcessor(4096, 1, 1);
    const chunks = [];
    let total = 0, stopped = false;
    proc.onaudioprocess = (e) => {
      if (stopped) return;
      chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
      total += e.inputBuffer.length;
      if (total / ctx.sampleRate >= MAX_SECONDS && onAutoStop) onAutoStop();
    };
    src.connect(proc); proc.connect(ctx.destination);
    return {
      async stop() {
        stopped = true;
        proc.disconnect(); src.disconnect();
        stream.getTracks().forEach((t) => t.stop());
        const rate = ctx.sampleRate;
        await ctx.close();
        return wav(downsample(chunks, rate));
      },
    };
  }

  window.WavRecorder = { start, supported: () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && (window.AudioContext || window.webkitAudioContext)) };
})();
