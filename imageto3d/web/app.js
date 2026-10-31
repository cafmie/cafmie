const fileInput = document.querySelector("#file");
const drop = document.querySelector("#drop");
const preview = document.querySelector("#preview");
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
  volume: "表に写真の凹凸、裏になめらかな厚みを付けた立体です。",
  relief: "片面だけの厚みです。平らな面が背面になり、印刷向きです。",
};

let currentFile = null;
let ready = false;
let objectUrl = null;

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
  hideError();
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

sample.addEventListener("click", async () => {
  hideError();
  const response = await fetch("/sample.png");
  if (!response.ok) {
    showError("サンプル画像を読み込めませんでした。");
    return;
  }
  const blob = await response.blob();
  setFile(new File([blob], "sample.png", { type: "image/png" }));
});

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
  const body = new FormData();
  body.append("image", currentFile, currentFile.name || "image.png");
  body.append("mode", selectedMode());
  body.append("cutout", document.querySelector("#cutout").checked ? "true" : "false");
  body.append("resolution", document.querySelector("#resolution").value);
  body.append("depth_scale", document.querySelector("#depth").value);
  body.append("inflate", document.querySelector("#inflate").value);
  body.append("thickness", document.querySelector("#thickness").value);
  body.append("smooth", document.querySelector("#smooth").value);

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
  installButton.textContent = data.installed ? "インストールし直す" : "このPCにインストール";
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
