const fileInput = document.querySelector("#file");
const drop = document.querySelector("#drop");
const frame = document.querySelector("#frame");
const preview = document.querySelector("#preview");
const objectLayer = document.querySelector("#objectLayer");
const objectsEl = document.querySelector("#objects");
const objectsText = document.querySelector("#objectsText");
const objectChoices = document.querySelector("#objectChoices");
const replaceButton = document.querySelector("#replace");
const go = document.querySelector("#go");
const sample = document.querySelector("#sample");
const statusEl = document.querySelector("#status");
const errorEl = document.querySelector("#error");
const resultEl = document.querySelector("#result");
const statsEl = document.querySelector("#stats");
const noticeEl = document.querySelector("#notice");
const working = document.querySelector("#working");
const workingText = document.querySelector("#workingText");
const empty = document.querySelector("#empty");
const viewer = document.querySelector("#viewer");
const modeHint = document.querySelector("#modeHint");
const thicknessField = document.querySelector("#thicknessField");
const installText = document.querySelector("#installText");
const installButton = document.querySelector("#installButton");

const hints = {
  volume: "表に写真の凹凸と細部、裏になめらかな厚みを付けた立体です。",
  relief: "片面だけの厚みです。平らな面が背面になり、印刷向きです。",
};

const OBJECT_COLORS = [
  [216, 74, 36],
  [36, 110, 168],
  [44, 130, 78],
  [168, 120, 32],
  [120, 64, 160],
  [20, 140, 150],
];

let currentFile = null;
let ready = false;
let objectUrl = null;
let objectCatalog = [];
let selectedObjects = new Set();
let labelCanvas = null;
let overlayCanvas = null;
let detectToken = 0;
let detectPromise = Promise.resolve();

function bindSlider(id, outputId, digits = 2) {
  const input = document.querySelector(id);
  const output = document.querySelector(outputId);
  const paint = () => {
    const value = Number(input.value);
    output.textContent = digits === 0 ? String(value) : value.toFixed(digits);
  };
  input.addEventListener("input", paint);
  paint();
}

bindSlider("#depth", "#depthValue");
bindSlider("#inflate", "#inflateValue");
bindSlider("#thickness", "#thicknessValue");
bindSlider("#smooth", "#smoothValue", 1);
bindSlider("#resolution", "#resolutionValue", 0);
bindSlider("#detail", "#detailValue");

function selectedMode() {
  return document.querySelector('input[name="mode"]:checked').value;
}

function refreshMode() {
  const mode = selectedMode();
  modeHint.textContent = hints[mode];
  thicknessField.hidden = mode !== "relief";
}

document.querySelectorAll('input[name="mode"]').forEach((input) => {
  input.addEventListener("change", refreshMode);
});
refreshMode();

function setFile(file) {
  if (!file || !file.type.startsWith("image/")) {
    showError("PNG、JPEG、WebP の画像を選んでください。");
    return;
  }
  currentFile = file;
  if (objectUrl) URL.revokeObjectURL(objectUrl);
  objectUrl = URL.createObjectURL(file);
  preview.src = objectUrl;
  preview.alt = file.name || "選択した画像";
  drop.classList.add("has-image");
  frame.hidden = false;
  replaceButton.hidden = false;
  hideError();
  clearObjects();
  detectPromise = detectObjects();
}

fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) setFile(fileInput.files[0]);
});

drop.addEventListener("dragover", (event) => {
  event.preventDefault();
});
drop.addEventListener("drop", (event) => {
  event.preventDefault();
  const file = event.dataTransfer.files[0];
  if (file) setFile(file);
});

window.addEventListener("paste", (event) => {
  const file = [...event.clipboardData.files].find((item) => item.type.startsWith("image/"));
  if (file) setFile(file);
});

replaceButton.addEventListener("click", () => fileInput.click());

sample.addEventListener("click", async () => {
  hideError();
  const response = await fetch("/sample.jpg");
  if (!response.ok) {
    showError("サンプル画像を読み込めませんでした。");
    return;
  }
  const blob = await response.blob();
  setFile(new File([blob], "sample.jpg", { type: "image/jpeg" }));
});

document.querySelector("#cutout").addEventListener("change", () => {
  if (!currentFile) return;
  clearObjects();
  detectPromise = detectObjects();
});

function clearObjects() {
  detectToken += 1;
  objectCatalog = [];
  selectedObjects = new Set();
  labelCanvas = null;
  overlayCanvas = null;
  objectsEl.hidden = true;
  objectsText.textContent = "";
  objectChoices.innerHTML = "";
  objectLayer.hidden = true;
}

async function detectObjects() {
  if (!currentFile || !document.querySelector("#cutout").checked) return;
  const token = detectToken;
  objectsEl.hidden = false;
  objectsText.textContent = "物体を探しています";
  const body = new FormData();
  body.append("image", currentFile, currentFile.name || "image.png");
  body.append("cutout", "true");
  try {
    const response = await fetch("/api/objects", { method: "POST", body });
    const data = await response.json().catch(() => ({}));
    if (token !== detectToken) return;
    if (!response.ok || !data.objects || data.objects.length < 2) {
      clearObjects();
      return;
    }
    objectCatalog = data.objects;
    selectedObjects = new Set([data.objects[0].id]);
    await loadLabel(data.label);
    if (token !== detectToken) return;
    objectsText.textContent = `${data.objects.length}個の物体を見つけました。写真の上を押すと、その物体だけを立体にします。`;
    renderChoices();
    objectLayer.hidden = false;
    paintLayer();
  } catch {
    if (token === detectToken) clearObjects();
  }
}

function loadLabel(encoded) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      labelCanvas = document.createElement("canvas");
      labelCanvas.width = image.width;
      labelCanvas.height = image.height;
      labelCanvas.getContext("2d").drawImage(image, 0, 0);
      resolve();
    };
    image.onerror = () => reject(new Error("label"));
    image.src = `data:image/png;base64,${encoded}`;
  });
}

function renderChoices() {
  objectChoices.innerHTML = "";
  const allSelected = selectedObjects.size === objectCatalog.length;
  for (const item of objectCatalog) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item.label;
    button.setAttribute("aria-pressed", !allSelected && selectedObjects.has(item.id) ? "true" : "false");
    button.addEventListener("click", () => chooseOnly(item.id));
    objectChoices.appendChild(button);
  }
  const all = document.createElement("button");
  all.type = "button";
  all.textContent = "全部まとめる";
  all.setAttribute("aria-pressed", allSelected ? "true" : "false");
  all.addEventListener("click", chooseAll);
  objectChoices.appendChild(all);
  buildOverlay();
}

function chooseOnly(id) {
  selectedObjects = new Set([id]);
  renderChoices();
  paintLayer();
}

function chooseAll() {
  selectedObjects = new Set(objectCatalog.map((item) => item.id));
  renderChoices();
  paintLayer();
}

function buildOverlay() {
  if (!labelCanvas) {
    overlayCanvas = null;
    return;
  }
  const width = labelCanvas.width;
  const height = labelCanvas.height;
  const source = labelCanvas.getContext("2d").getImageData(0, 0, width, height).data;
  const image = new ImageData(width, height);
  const allSelected = selectedObjects.size === objectCatalog.length;
  for (let index = 0; index < width * height; index += 1) {
    const id = source[index * 4];
    if (!id) continue;
    const color = OBJECT_COLORS[(id - 1) % OBJECT_COLORS.length];
    const on = selectedObjects.has(id);
    image.data[index * 4] = color[0];
    image.data[index * 4 + 1] = color[1];
    image.data[index * 4 + 2] = color[2];
    image.data[index * 4 + 3] = on ? (allSelected ? 70 : 120) : 36;
  }
  overlayCanvas = document.createElement("canvas");
  overlayCanvas.width = width;
  overlayCanvas.height = height;
  overlayCanvas.getContext("2d").putImageData(image, 0, 0);
}

function containBox() {
  const rect = preview.getBoundingClientRect();
  const naturalW = preview.naturalWidth || 1;
  const naturalH = preview.naturalHeight || 1;
  const scale = Math.min(rect.width / naturalW, rect.height / naturalH);
  const drawnW = naturalW * scale;
  const drawnH = naturalH * scale;
  return {
    rect,
    left: (rect.width - drawnW) / 2,
    top: (rect.height - drawnH) / 2,
    width: drawnW,
    height: drawnH,
  };
}

function paintLayer() {
  if (objectLayer.hidden || !overlayCanvas || !preview.naturalWidth) return;
  const box = containBox();
  const ratio = window.devicePixelRatio || 1;
  objectLayer.width = Math.max(1, Math.round(box.rect.width * ratio));
  objectLayer.height = Math.max(1, Math.round(box.rect.height * ratio));
  const ctx = objectLayer.getContext("2d");
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, box.rect.width, box.rect.height);
  ctx.drawImage(overlayCanvas, box.left, box.top, box.width, box.height);
  ctx.font = "600 13px sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  const allSelected = selectedObjects.size === objectCatalog.length;
  for (const item of objectCatalog) {
    const x = box.left + item.cx * box.width;
    const y = box.top + item.cy * box.height;
    const on = selectedObjects.has(item.id);
    ctx.beginPath();
    ctx.fillStyle = on && !allSelected ? "#241c16" : "rgba(255,255,255,0.92)";
    ctx.arc(x, y, 12, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = on && !allSelected ? "#fff7f3" : "#241c16";
    ctx.fillText(String(item.id), x, y + 0.5);
  }
}

objectLayer.addEventListener("click", (event) => {
  if (!labelCanvas || !preview.naturalWidth) return;
  const box = containBox();
  const rect = preview.getBoundingClientRect();
  const x = event.clientX - rect.left - box.left;
  const y = event.clientY - rect.top - box.top;
  if (x < 0 || y < 0 || x > box.width || y > box.height) return;
  const lx = Math.min(labelCanvas.width - 1, Math.floor((x / box.width) * labelCanvas.width));
  const ly = Math.min(labelCanvas.height - 1, Math.floor((y / box.height) * labelCanvas.height));
  const id = labelCanvas.getContext("2d").getImageData(lx, ly, 1, 1).data[0];
  if (id) chooseOnly(id);
});

preview.addEventListener("load", () => paintLayer());
window.addEventListener("resize", () => paintLayer());

function showError(message) {
  errorEl.hidden = false;
  errorEl.textContent = message;
}

function hideError() {
  errorEl.hidden = true;
  errorEl.textContent = "";
}

async function refreshStatus() {
  try {
    const response = await fetch("/api/status");
    const data = await response.json();
    ready = Boolean(data.ready);
    statusEl.textContent = data.message && data.state === "error"
      ? `${data.label}: ${data.message}`
      : data.label;
    go.disabled = !ready;
    if (!ready && data.state !== "error") {
      window.setTimeout(refreshStatus, 800);
    }
    if (data.state === "error") {
      go.disabled = false;
      go.textContent = "モデルの取得をやり直す";
    } else {
      go.textContent = "3Dモデルを作る";
    }
  } catch {
    statusEl.textContent = "サーバーに接続できません";
    window.setTimeout(refreshStatus, 1500);
  }
}

go.addEventListener("click", async () => {
  hideError();
  if (!ready) {
    go.disabled = true;
    await fetch("/api/models/retry", { method: "POST" });
    refreshStatus();
    return;
  }
  if (!currentFile) {
    showError("先に画像を選んでください。");
    return;
  }
  await detectPromise;
  const body = new FormData();
  body.append("image", currentFile, currentFile.name || "image.png");
  body.append("mode", selectedMode());
  body.append("cutout", document.querySelector("#cutout").checked ? "true" : "false");
  body.append("resolution", document.querySelector("#resolution").value);
  body.append("depth_scale", document.querySelector("#depth").value);
  body.append("inflate", document.querySelector("#inflate").value);
  body.append("thickness", document.querySelector("#thickness").value);
  body.append("smooth", document.querySelector("#smooth").value);
  body.append("detail", document.querySelector("#detail").value);
  if (objectCatalog.length >= 2 && selectedObjects.size > 0) {
    body.append("objects", [...selectedObjects].join(","));
  }

  go.disabled = true;
  working.hidden = false;
  workingText.textContent = "立体にしています";
  const started = performance.now();
  const ticker = window.setInterval(() => {
    const seconds = Math.round((performance.now() - started) / 1000);
    workingText.textContent = `立体にしています（${seconds}秒）`;
  }, 500);

  try {
    const response = await fetch("/api/reconstruct", { method: "POST", body });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : "変換に失敗しました");
    }
    showModel(data);
  } catch (error) {
    showError(error.message || "変換に失敗しました");
  } finally {
    window.clearInterval(ticker);
    working.hidden = true;
    go.disabled = !ready;
  }
});

function showModel(data) {
  const stamp = Date.now();
  viewer.src = `${data.glb}?t=${stamp}`;
  viewer.hidden = false;
  empty.hidden = true;
  resultEl.hidden = false;
  statsEl.textContent = `頂点 ${data.vertices.toLocaleString("ja-JP")} · 面 ${data.faces.toLocaleString("ja-JP")} · ${data.elapsed_s.toLocaleString("ja-JP")}秒`;
  noticeEl.hidden = !data.notice;
  noticeEl.textContent = data.notice || "";
  document.querySelector("#glb").href = data.glb;
  document.querySelector("#stl").href = data.stl;
  document.querySelector("#zip").href = data.obj_zip;
  document.querySelector("#depthThumb").src = `${data.depth}?t=${stamp}`;
  document.querySelector("#maskThumb").src = `${data.mask}?t=${stamp}`;
}

function paintInstall(data) {
  installText.textContent = data.message;
  installButton.textContent = data.installed ? "上書きして更新" : "このPCにインストール";
}

async function refreshInstall() {
  try {
    const response = await fetch("/api/install");
    if (!response.ok) return;
    paintInstall(await response.json());
  } catch {
    installText.textContent = "インストール状態を確認できません";
  }
}

installButton.addEventListener("click", async () => {
  installButton.disabled = true;
  installText.textContent = "インストールしています";
  try {
    const response = await fetch("/api/install", { method: "POST" });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = data.detail;
      throw new Error(typeof detail === "string" ? detail : "インストールに失敗しました");
    }
    paintInstall(data);
  } catch (error) {
    installText.textContent = error.message || "インストールに失敗しました";
  } finally {
    installButton.disabled = false;
  }
});

refreshStatus();
refreshInstall();
