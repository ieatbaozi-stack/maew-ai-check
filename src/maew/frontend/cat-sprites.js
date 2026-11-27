/* Clean lineless 8-bit chubby cat sprite renderer.
 * 5 skins (Ginger, Taupe, Shadow, Mochi, Cocoa), 4 quota moods, petting hearts,
 * and floating sleep Zzz — pure integer-pixel canvas rendering.
 */

const CAT_SKINS = {
  orange: {
    name: "Ginger",
    body: "#f2993f",
    shade: "#d87924",
    stripe: "#b95d18",
    highlight: "#f9bd74",
    belly: "#fde7c6",
    paw: "#fff8ec",
    muzzle: "#fde7c6",
    nose: "#f4729b",
    blush: "#f89eb6",
    eye: "#1a1423",
    shadow: "#0c0c0f",
  },
  greige: {
    name: "Taupe",
    body: "#b29c84",
    shade: "#927c66",
    stripe: "#635140",
    highlight: "#cfc0ad",
    belly: "#ede5d8",
    paw: "#f8f4ec",
    muzzle: "#f2eadf",
    nose: "#f2789b",
    blush: "#f59eb6",
    eye: "#1c1614",
    shadow: "#0c0c0f",
  },
  black_yellow: {
    name: "Shadow",
    body: "#343746",
    shade: "#252836",
    stripe: "#1c1f2b",
    highlight: "#4b4f64",
    belly: "#424658",
    paw: "#4a4e61",
    muzzle: "#424658",
    nose: "#f2789b",
    blush: "#f28aa8",
    eye: "#facc15",
    shadow: "#09090b",
  },
  white: {
    name: "Mochi",
    body: "#f1f3f8",
    shade: "#d8deea",
    stripe: "#c3cce0",
    highlight: "#ffffff",
    belly: "#ffffff",
    paw: "#ffffff",
    muzzle: "#ffffff",
    nose: "#f4729b",
    blush: "#f9a4bc",
    eye: "#1e2438",
    shadow: "#0c0c0f",
  },
  choco: {
    name: "Cocoa",
    body: "#8a5233",
    shade: "#6e3e24",
    stripe: "#4f2a17",
    highlight: "#a66c49",
    belly: "#d7b497",
    paw: "#f7efe6",
    muzzle: "#c79a76",
    nose: "#f4729b",
    blush: "#f498b2",
    eye: "#1a1210",
    shadow: "#0c0c0f",
  },
};

const SIT_FRAME_A = [
  "....B....B..........",
  "...BHB..BHB.........",
  "...BTBHHBTB.........",
  "..BBBBBBBBB.........",
  "..BBBBBBBBB.........",
  "..NMBBBBBBB.........",
  "..MMKBBBBB..........",
  "....BHHHHHB.........",
  "....BBBBBBBB........",
  "...BCCBBBBTBB.......",
  "...BCCBBBBBBB.......",
  "...BCCBBBBTBB...T...",
  "...BBBBBBBBBB...B...",
  "...BBBBBBBTBB...B...",
  "...PPSSPPPBBBBBBB...",
  "..DDDDDDDDDDDDD.....",
];

const SIT_FRAME_B = [
  "....B....B..........",
  "...BHB..BHB.........",
  "...BTBHHBTB.........",
  "..BBBBBBBBB.........",
  "..BBBBBBBBB.........",
  "..NMBBBBBBB.........",
  "..MMKBBBBB..........",
  "....BHHHHHB.........",
  "....BBBBBBBB........",
  "...BCCBBBBTBB.......",
  "...BCCBBBBBBB....T..",
  "...BCCBBBBTBB....B..",
  "...BBBBBBBBBB....B..",
  "...BBBBBBBTBB...BB..",
  "...PPSSPPPBBBBBBB...",
  "..DDDDDDDDDDDDD.....",
];

function makeSittingGrid(mood, frame) {
  const base = (frame % 2 === 0 ? SIT_FRAME_A : SIT_FRAME_B).map((r) => r.split(""));
  if (mood === "happy") {
    base[4][5] = "E";
    base[5][4] = "E";
    base[5][6] = "E";
  } else if (mood === "watch") {
    const blink = frame === 3;
    if (blink) {
      base[5][4] = "E";
      base[5][5] = "E";
    } else {
      base[4][4] = "E";
      base[5][4] = "E";
    }
  } else if (mood === "stressed") {
    base[4][5] = "E";
    base[4][7] = "E";
    base[5][5] = "E";
    base[5][7] = "E";
    const dropY = frame % 2 === 0 ? 2 : 3;
    base[dropY][11] = "W";
    base[dropY + 1][11] = "W";
  }
  return base;
}

const SLEEP_LOAF_A = [
  "....................",
  "....................",
  "....................",
  "....................",
  "....................",
  "....................",
  "...B....B...........",
  "...BH..HB...........",
  "..BBHHHHBB..........",
  "..BBBBBBBBHHHHHH....",
  ".BBBBBBBBBBTBBTBBT..",
  ".BBEEBBBBBBBBBBBBBT.",
  ".NMKKBBBBBBBBBBBBBB.",
  "..MMBBBBBBCCCCCB..B.",
  "..PPPSSBBBBBBBBBBBB.",
  ".DDDDDDDDDDDDDDDD...",
];

const SLEEP_LOAF_B = [
  "....................",
  "....................",
  "....................",
  "....................",
  "....................",
  "....................",
  "...B....B...........",
  "...BH..HB...........",
  "..BBHHHHBB..........",
  "..BBBBBBBBHHHHHH....",
  ".BBBBBBBBBBTBBTBBT..",
  ".BBEEBBBBBBBBBBBBB.T",
  ".NMKKBBBBBBBBBBBBBB.",
  "..MMBBBBBBCCCCCB..B.",
  "..PPPSSBBBBBBBBBBBB.",
  ".DDDDDDDDDDDDDDDD...",
];

const HEAD_GRID = [
  ".B....B...",
  ".BH..HB...",
  "BBHHHHBB..",
  "BBBBBBBB..",
  "BBBBBEBB..",
  "BBBBBEBM..",
  ".BBKBBMN..",
  "..BBBBBB..",
];

const HEART_GRID = [
  ".RR.RR.",
  "RRRRRRR",
  "RRRRRRR",
  ".RRRRR.",
  "..RRR..",
  "...R...",
];

const Z_GRID = [
  "ZZZZ",
  "..Z.",
  ".Z..",
  "ZZZZ",
];

function paletteMap(skinId) {
  const s = CAT_SKINS[skinId] || CAT_SKINS.orange;
  return {
    B: s.body,
    S: s.shade,
    T: s.stripe,
    H: s.highlight,
    C: s.belly,
    P: s.paw,
    M: s.muzzle,
    N: s.nose,
    K: s.blush,
    E: s.eye,
    D: s.shadow,
    W: "#38bdf8",
    R: "#f4729b",
    Z: "#7dd3fc",
  };
}

function drawGrid(ctx, grid, colors, scale, offsetX = 0, offsetY = 0) {
  for (let y = 0; y < grid.length; y++) {
    const row = grid[y];
    for (let x = 0; x < row.length; x++) {
      const ch = row[x];
      if (ch === "." || ch === " ") continue;
      const color = colors[ch];
      if (!color) continue;
      ctx.fillStyle = color;
      ctx.fillRect(offsetX + x * scale, offsetY + y * scale, scale, scale);
    }
  }
}

function renderCatCanvas(canvas, { skin = "orange", mood = "happy", frame = 0, showHeart = false }) {
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const scale = Math.floor(canvas.width / 20);
  const colors = paletteMap(skin);

  if (mood === "sleep") {
    const grid = (frame % 2 === 0 ? SLEEP_LOAF_A : SLEEP_LOAF_B).map((r) => r.split(""));
    drawGrid(ctx, grid, colors, scale, 0, 0);
    const zFloat = frame % 4;
    const zY = Math.max(0, (3 - zFloat) * scale);
    const zX = (4 + (zFloat % 2)) * scale;
    drawGrid(ctx, Z_GRID, colors, Math.max(1, scale - 1), zX, zY);
  } else {
    const grid = makeSittingGrid(mood, frame);
    drawGrid(ctx, grid, colors, scale, 0, 0);
  }

  if (showHeart) {
    const heartScale = Math.max(1, Math.floor(scale * 0.72));
    drawGrid(ctx, HEART_GRID, colors, heartScale, 12 * scale, 1 * scale);
  }
}

function renderCatHead(canvas, skinId) {
  const ctx = canvas.getContext("2d");
  ctx.imageSmoothingEnabled = false;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  const scale = Math.max(1, Math.floor(canvas.width / 10));
  const colors = paletteMap(skinId);
  const offsetX = Math.floor((canvas.width - 10 * scale) / 2);
  const offsetY = Math.floor((canvas.height - 8 * scale) / 2);
  drawGrid(ctx, HEAD_GRID, colors, scale, offsetX, offsetY);
}

window.MaewSprites = {
  CAT_SKINS,
  renderCatCanvas,
  renderCatHead,
};
