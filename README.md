# 画像から3D

写真を1枚渡すと、このPCの中だけで立体の3Dモデルにします。ブラウザでプレビューして、GLB・STL・OBJ で保存できます。深度の推定と背景の切り抜きは、NVIDIA GPU があるときは CUDA で計算します。

処理はローカルです。画像を外部のAPIには送りません。初回起動時だけ、深度推定と背景切り抜きのモデル（合計およそ140MB）をダウンロードします。

## 準備

Python 3.10 以上が必要です。

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-gpu.txt
python -m imageto3d download-models
```

GPU 用のパッケージは `onnxruntime-gpu` です。さきに CPU 版の `onnxruntime` を入れているときは、先に外してから入れ直します。

```bash
pip uninstall -y onnxruntime
pip install -r requirements-gpu.txt
```

NVIDIA ドライバが入っている必要があります。CUDA のライブラリは `onnxruntime-gpu` の依存として入ります。GPU が無い PC では `pip install -r requirements.txt` で CPU のまま動きます。使う装置を固定するときは `--device cuda` または `--device cpu` を付けます。`--device cuda` で GPU が無いときは起動時に失敗します。

モデルは `models/` に保存されます。置き場所を変えるときは環境変数 `IMAGETO3D_MODELS` を指定します。

## ブラウザで使う

```bash
python -m imageto3d serve
```

http://127.0.0.1:7860 を開きます。`--open` を付けるとブラウザも開きます。待受先を変えるときは `--host` と `--port` を使います。

1. 画像をドロップする（貼り付けもできます）。「サンプルのリンゴで試す」でも始められます。
2. 形を選ぶ。**立体**は表に写真の凹凸、裏になめらかな厚みを付けます。**レリーフ**は片面だけで、背面が平らです。
3. 「3Dモデルを作る」を押す。右側でドラッグして回せます。
4. GLB（テクスチャ付き）、STL（形状のみ）、OBJ（zip）を保存する。

背景が透明なPNGは、その透明部分を輪郭に使います。

## コマンドで変換する

```bash
python -m imageto3d convert photo.png -o photo.glb
python -m imageto3d convert photo.png -o relief.stl --mode relief --thickness 0.12
python -m imageto3d convert photo.png -o photo.zip
```

出力の拡張子は `.glb` `.stl` `.obj` `.zip` です。`--no-cutout` で背景の切り抜きを省略できます。

## スライダー

数値は、被写体の大きさに対する割合です。

| 名前 | 役割 |
| --- | --- |
| 奥行き | 写真から推定した凹凸の強さ |
| ふくらみ | 輪郭から作るドーム状の厚み |
| 台の厚み | レリーフ背面の土台（立体では使いません） |
| なめらかさ | 深度と輪郭のぼかし |
| 密度 | メッシュの細かさ。上げると輪郭の階段が減ります |

被写体が一つで、背景と色が分かれている写真が向いています。

## しくみと限界

1. 背景を切り抜く（silueta / U²-Net 系のONNX）
2. 奥行きを推定する（Depth Anything V2 Small）
3. 輪郭をドーム状にふくらませ、手前に奥行きを足して閉じたメッシュにする

見えていない裏側の形は推定しません。裏側は輪郭から作ったなめらかな殻で、色は被写体の代表色です。複数視点からの計測や、生成モデルによる完全な立体復元ではありません。

画面右上に「GPUで処理します」と出ているときは、深度と切り抜きが CUDA 上です。メッシュを組む処理は CPU のままです。GPU が使えないときは「CPUで処理します」になり、同じ結果を CPU で計算します。

生成ファイルは `outputs/` に置かれ、24時間より古いものは起動時に消します。`IMAGETO3D_OUTPUTS` で場所を変えられます。

## テスト

```bash
pip install pytest httpx
pytest
```

## 同梱しているもの

- 3Dプレビューは [model-viewer](https://github.com/google/model-viewer)（BSD-3-Clause）です。`imageto3d/web/vendor/model-viewer.min.js`
- 深度モデルは [Depth Anything V2 Small](https://github.com/DepthAnything/Depth-Anything-V2)（Apache-2.0）の ONNX 版を、初回に Hugging Face から取得します
- 切り抜きモデル silueta は [rembg](https://github.com/danielgatis/rembg) の配布物を初回に取得します
