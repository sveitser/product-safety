// Shared browser-side query embedding for photo.html and dev-parity.html.
//
// This module MUST mirror scripts/embed_lib.py for the active spec
// (siglip2-b16-256): same resize (PIL antialiased bilinear), same
// normalization, same pooling (vision tower pooler_output), same L2 norm.
// Parity is verified by scripts/check_parity.py against dev-parity.html;
// expected cosine vs Python is >= 0.999 with the fp16 weights.

export const MODEL_VERSION = 'siglip2-b16-256';
export const EMBED_DIM = 768;
export const MODEL_DOWNLOAD_MB = 177;

const ONNX_MODEL = 'onnx-community/siglip2-base-patch16-256-ONNX';
const CDN = 'https://cdn.jsdelivr.net/npm/@huggingface/transformers@4.2.0';
const SIZE = 256;

let _model = null;
let _RawImage = null;
let _Tensor = null;

export function modelFileRegex() {
  // matches the weights file in Cache Storage (used to skip the download prompt)
  return /siglip2-base-patch16-256-ONNX.*vision_model_fp16\.onnx/;
}

export async function loadModel(progress_callback) {
  const { SiglipVisionModel, RawImage, Tensor, env } = await import(CDN);
  env.allowLocalModels = false;
  _RawImage = RawImage;
  _Tensor = Tensor;
  _model = await SiglipVisionModel.from_pretrained(ONNX_MODEL, {
    dtype: 'fp16',
    // onnxruntime's extended-level SimplifiedLayerNormFusion corrupts this
    // fp16 graph; 'basic' avoids the broken fusion and loads correctly.
    session_options: { graphOptimizationLevel: 'basic' },
    progress_callback,
  });
}

// ---- PIL-compatible antialiased bilinear resize (triangle filter) ----
// Pillow applies the triangle filter with support scaled by the downscale
// ratio (i.e. antialiased), in separable horizontal/vertical passes. Browser
// canvas resampling differs per-engine, so we resize deterministically here.

function _coeffs(inSize, outSize) {
  const scale = inSize / outSize;
  const fscale = Math.max(scale, 1);
  const support = fscale; // triangle filter support = 1.0 * fscale
  const ksize = Math.ceil(support) * 2 + 1;
  const bounds = new Int32Array(outSize * 2);
  const kk = new Float64Array(outSize * ksize);
  for (let xx = 0; xx < outSize; xx++) {
    const center = (xx + 0.5) * scale;
    const xmin = Math.max(0, Math.floor(center - support));
    const xmax = Math.min(inSize, Math.ceil(center + support));
    let ww = 0;
    const k = [];
    for (let x = xmin; x < xmax; x++) {
      const t = Math.abs((x + 0.5 - center) / fscale);
      const w = t < 1 ? 1 - t : 0;
      k.push(w);
      ww += w;
    }
    for (let i = 0; i < k.length; i++) kk[xx * ksize + i] = k[i] / ww;
    bounds[xx * 2] = xmin;
    bounds[xx * 2 + 1] = xmax - xmin;
  }
  return { bounds, kk, ksize };
}

function resizeBilinearAA(src, sw, sh, channels, dw, dh) {
  const horiz = new Float32Array(dw * sh * 3);
  {
    const { bounds, kk, ksize } = _coeffs(sw, dw);
    for (let y = 0; y < sh; y++)
      for (let x = 0; x < dw; x++) {
        const xmin = bounds[x * 2], n = bounds[x * 2 + 1];
        let r = 0, g = 0, b = 0;
        for (let i = 0; i < n; i++) {
          const w = kk[x * ksize + i], o = (y * sw + xmin + i) * channels;
          r += src[o] * w; g += src[o + 1] * w; b += src[o + 2] * w;
        }
        const d = (y * dw + x) * 3;
        horiz[d] = r; horiz[d + 1] = g; horiz[d + 2] = b;
      }
  }
  const out = new Float32Array(dw * dh * 3);
  {
    const { bounds, kk, ksize } = _coeffs(sh, dh);
    for (let y = 0; y < dh; y++) {
      const ymin = bounds[y * 2], n = bounds[y * 2 + 1];
      for (let x = 0; x < dw; x++) {
        let r = 0, g = 0, b = 0;
        for (let i = 0; i < n; i++) {
          const w = kk[y * ksize + i], o = ((ymin + i) * dw + x) * 3;
          r += horiz[o] * w; g += horiz[o + 1] * w; b += horiz[o + 2] * w;
        }
        const d = (y * dw + x) * 3;
        out[d] = r; out[d + 1] = g; out[d + 2] = b;
      }
    }
  }
  return out;
}

export function l2normalize(arr) {
  let norm = 0;
  for (const v of arr) norm += v * v;
  norm = Math.sqrt(norm);
  if (norm < 1e-12) return arr;
  const out = new Float32Array(arr.length);
  for (let i = 0; i < arr.length; i++) out[i] = arr[i] / norm;
  return out;
}

async function _forward(pixels, sw, sh, channels) {
  const px = resizeBilinearAA(pixels, sw, sh, channels, SIZE, SIZE);
  // round to uint8 like PIL's resize output, then (x/255 - 0.5) / 0.5
  const chw = new Float32Array(3 * SIZE * SIZE);
  const plane = SIZE * SIZE;
  for (let i = 0; i < plane; i++)
    for (let c = 0; c < 3; c++) {
      const v = Math.min(255, Math.max(0, Math.round(px[i * 3 + c])));
      chw[c * plane + i] = (v / 255 - 0.5) / 0.5;
    }
  const out = await _model({
    pixel_values: new _Tensor('float32', chw, [1, 3, SIZE, SIZE]),
  });
  const raw = out.pooler_output ?? out.image_embeds;
  return l2normalize(Float32Array.from(raw.data));
}

// Embed an image as-is. Mirrors embed_lib.Encoder(siglip2-b16-256).encode().
// Used by dev-parity.html for the exact Python parity check.
export async function embedImage(blob) {
  if (!_model) throw new Error('model not loaded');
  const img = (await _RawImage.fromBlob(blob)).rgb();
  return _forward(img.data, img.width, img.height, img.channels);
}

function _centerCrop(img, frac) {
  const cw = Math.floor(img.width * frac), ch = Math.floor(img.height * frac);
  const x0 = Math.floor((img.width - cw) / 2), y0 = Math.floor((img.height - ch) / 2);
  const out = new Uint8ClampedArray(cw * ch * 3);
  for (let y = 0; y < ch; y++)
    for (let x = 0; x < cw; x++) {
      const s = ((y0 + y) * img.width + x0 + x) * img.channels, d = (y * cw + x) * 3;
      out[d] = img.data[s]; out[d + 1] = img.data[s + 1]; out[d + 2] = img.data[s + 2];
    }
  return { data: out, width: cw, height: ch, channels: 3 };
}

// Embed a query photo with center-crop TTA: average of the full image and an
// 80% center crop, renormalized. Mirrors eval_retrieval.py --tta center-crop,
// which improved augmented recall@5 by +1.6 pts (see docs/EVAL.md).
export async function embedQuery(blob) {
  if (!_model) throw new Error('model not loaded');
  const img = (await _RawImage.fromBlob(blob)).rgb();
  const full = await _forward(img.data, img.width, img.height, img.channels);
  const crop = _centerCrop(img, 0.8);
  const cc = await _forward(crop.data, crop.width, crop.height, crop.channels);
  const avg = new Float32Array(full.length);
  for (let i = 0; i < full.length; i++) avg[i] = (full[i] + cc[i]) / 2;
  return l2normalize(avg);
}
