# meeting-translater

会議・配信の音声（システム音声 / マイク / ファイル）をローカルでリアルタイムに文字起こしし、翻訳して原文＋訳文をフローティング字幕で表示する。クラウド送信なし（Apple Silicon / MLX）。

```
音声 (マイク / BlackHole / --file)
  └→ silero-vad（発話区間検出）
       └→ STT（Haas-ja = 日本語 / mlx-whisper = その他・言語判定）
            └→ PLaMo 3 Translate（MLX 4bit, 直近の文を文脈に）
                 └→ 字幕ウィンドウ（原文＋訳文）
```

スレッド構成: キャプチャ → VAD → MLX（STT + 翻訳）→ UI。MLX はスレッドを跨げないため、モデルのロードと推論は MLX スレッドで完結させている。

## Macアプリで使う

インストール済みなら、Finder のホームフォルダ内の「アプリケーション」にある
**Meeting Translater.app** をダブルクリックする。Dock に追加してもよい。

1. 初回は「初回準備・モデルを取得」を押す（約3.6GB。取得済みなら省略可能）。
2. 翻訳方向と音声入力を選ぶ。自分の声は「Macの既定のマイク」、会議や動画の再生音は「BlackHole 2ch」。
3. 「翻訳を開始」を押す。字幕ウィンドウが開き、モデルの読み込みが終わると音声に合わせて原文と訳文が表示される。
4. 「停止」で翻訳を止める。設定画面を閉じた場合も翻訳処理は終了する。

翻訳方向・音声入力・文字サイズは次回も引き継ぐ。
BlackHole を使う場合は、下記「システム音声の取り込み」の複数出力装置の設定も必要。
マイクの権限を求められたら許可する。音声認識・翻訳はローカルで行い、モデル取得時のみインターネットに接続する。

アプリを作成・再インストールするには、このプロジェクトで次を実行する。

```sh
uv sync
uv run python scripts/build_macos_app.py --install
```

作成先は `dist/Meeting Translater.app`、インストール先は `~/Applications/Meeting Translater.app`。
ビルドには Xcode Command Line Tools（`swiftc`）が必要。
これはこのMac向けの起動アプリであり、実体はこのプロジェクトと `.venv` にある。
プロジェクトを移動した場合は移動先で再作成する。他のMacに `.app` だけをコピーしても動作しない。
アプリ起動時の診断ログは `~/Library/Logs/Meeting Translater/app.log` に保存する。

設定画面だけを起動する場合は `uv run python desktop.py`。

## 動作環境

- Apple Silicon Mac / macOS
- Python 3.12（`uv` が自動取得）
- ffmpeg（`--file` で音声/動画ファイルを読むときのみ）: `brew install ffmpeg`

## セットアップ

```sh
uv sync
# 初回のみ: モデルを取得（1行目で Haas + PLaMo 0.8B、2行目で whisper）
HF_HUB_OFFLINE=0 uv run translater.py --file samples/ja.wav --no-ui
HF_HUB_OFFLINE=0 uv run translater.py --file samples/en.wav --no-ui --direction en-ja
```

既定は `HF_HUB_OFFLINE=1`（キャッシュ済みモデルのみ使用し、Hugging Face へ問い合わせない = ローカル完結のため）。未取得だと読み込みに失敗するので、初回だけ `HF_HUB_OFFLINE=0` を付ける。

取得されるモデル（`~/.cache/huggingface/hub/`、実測サイズ）:

| モデル | 用途 | サイズ |
|---|---|---|
| `mrjnzzz/Haas-ja-v1.0-mlx` | STT（日本語） | 約 1.2GB |
| `mlx-community/whisper-large-v3-turbo` | STT（多言語・言語判定） | 約 1.5GB |
| `pfnet/plamo-3-translate-0.8b-MLX-4bit` | 翻訳（既定） | 約 0.9GB |
| `pfnet/plamo-3-translate-2b-MLX-4bit` | 翻訳（`--mt-model` で指定時のみ） | 約 2.3GB |

※ 2B は `--mt-model pfnet/plamo-3-translate-2b-MLX-4bit` を付けて初回起動するときに取得（`HF_HUB_OFFLINE=0` が必要）。silero-vad は pip パッケージに同梱。

## システム音声の取り込み（BlackHole）

1. `brew install blackhole-2ch`（インストール後、再起動が必要な場合あり）
2. 「Audio MIDI設定」で「複数出力装置」を作成し、スピーカー（またはヘッドホン）と BlackHole 2ch の両方にチェックを入れる
3. システムの出力をその複数出力装置に切り替える（自分にも音が聞こえ、同時に BlackHole へ流れる）
4. `uv run translater.py --device BlackHole`

Zoom / Meet などはアプリ側のスピーカー出力先を複数出力装置にしてもよい（そのアプリの音だけを取り込める）。

注意: ターミナルアプリ（Terminal / iTerm / Ghostty など、実行元）に「マイク」権限が必要。システム設定 > プライバシーとセキュリティ > マイク で許可する。BlackHole も入力デバイスとして扱われるため同じ権限が要る。

## 使い方

```sh
uv run translater.py                                   # 既定マイク, 日本語→英語
uv run translater.py --device BlackHole                # システム音声（BlackHole 経由）
uv run translater.py --direction en-ja                 # 英語→日本語
uv run translater.py --direction auto                  # 言語を自動検出（ja⇄en）
uv run translater.py --mt-model pfnet/plamo-3-translate-2b-MLX-4bit   # 2B モデル
uv run translater.py --file samples/ja.wav --no-ui     # ファイルを実時間で流して検証（ログのみ）
uv run translater.py --list-devices                    # 入力デバイス一覧
```

`--device` はデバイス名の一部または番号。

## オプション

| オプション | 既定値 | 説明 |
|---|---|---|
| `--device DEVICE` | 既定マイク | 入力デバイス名の一部 or 番号（例: BlackHole） |
| `--file FILE` | - | マイクの代わりに音声/動画ファイルを実時間で流す（検証用、ffmpeg 必須） |
| `--direction {ja-en,en-ja,auto}` | `ja-en` | 言語方向 |
| `--stt {haas,whisper}` | 自動 | 省略時: 原文が日本語なら haas、それ以外は whisper |
| `--whisper-model` | `mlx-community/whisper-large-v3-turbo` | whisper のモデル |
| `--mt-model` | `pfnet/plamo-3-translate-0.8b-MLX-4bit` | 翻訳モデル（例: `pfnet/plamo-3-translate-2b-MLX-4bit`） |
| `--history` | `3` | 翻訳時に文脈として渡す直近の文数 |
| `--silence-ms` | `500` | この長さの無音で発話を確定 |
| `--max-sec` | `15.0` | 連続発話をこの秒数で強制分割 |
| `--partial-sec` | `1.0` | 発話中の途中表示の間隔（0 で無効） |
| `--no-ui` | off | 字幕ウィンドウを出さずログのみ |
| `--font-size` | `26` | 訳文のフォントサイズ（原文は 0.7 倍） |
| `--lines` | `3` | 字幕ウィンドウの初期の高さ（発話数） |
| `--opacity` | `0.8` | 字幕背景の不透明度 0〜1 |
| `--list-devices` | off | 入力デバイス一覧を表示して終了 |

## 字幕ウィンドウの操作

- 話している最中も約1秒ごとに途中経過を薄い色で表示し、発話が終わると確定版（通常の色）に置き換える。途中の訳は翻訳の文脈履歴に入れない
- どこを掴んでもドラッグで移動、右下のグリップでリサイズ。位置とサイズは次回起動時に復元
- ホイール / トラックパッドで履歴を遡れる（最大 500 発話）。最下部にいる時だけ新しい字幕に自動追従
- 右クリックメニュー: 言語方向の切替（実行中に反映）/ 字幕をクリア / 終了
- Ctrl+C でも終了（位置は保存される）

## 言語方向と STT の自動選択

| `--direction` | 原文 → 訳文 | STT |
|---|---|---|
| `ja-en` | ja → en | haas |
| `en-ja` | en → ja | whisper |
| `auto` | whisper が言語を判定し ja ⇄ en（ja なら en へ、それ以外は ja へ） | whisper |

- 原文が日本語なら Haas、それ以外は whisper。`--stt` で上書き可能。
- `--stt haas` は日本語専用のため、日本語以外の音声には使わないこと。
- 方向を切り替えると翻訳の文脈履歴は破棄される。

## テスト

```sh
uv run python test_translater.py
QT_QPA_PLATFORM=offscreen uv run python -m unittest test_desktop.py
```

VAD 分割の自己チェック（モデル不要・数秒。`samples/` と ffmpeg を使用）。
アプリ版のテストは開始・状態通知・停止・異常終了後の再開を、実際の子プロセスで確認する。

## 使用モデルとメモリ使用量

MacBook Pro M5 / 16GB で実測（2026-11-08、`--file` で実時間再生）。MLX は unified memory のため RSS より **MLX peak** が実態に近い。

| 構成 | MLX peak | STT / 発話 | 翻訳 / 文 | 発話終了→表示 |
|---|---|---|---|---|
| Haas + PLaMo 0.8B（既定 ja-en） | 2.4GB | 0.06〜0.10s | 約0.15s | 約0.7s |
| whisper + PLaMo 0.8B（en-ja / auto） | 3.2GB | 約0.35s | 約0.15s | 約1.0〜1.3s |
| Haas + PLaMo 2B | 3.9GB | 0.06〜0.10s | 約0.3〜0.5s | 約0.9s |
| 最悪ケース（Haas + whisper + 2B を全ロード） | 5.8GB | - | - | - |

- 目標（発話終了後 1〜3 秒・ピーク 6〜8GB 以内）はすべての構成で満たす
- 長時間: 約10分（95発話）連続で MLX peak は 2.46GB で頭打ち、RSS は +40MB 程度でほぼ横ばい。エラー・処理遅延の警告は 0 件
- 翻訳モデル: 0.8B は誤訳が少なく速いので既定とした。2B は訳が自然で、カタカナ社名の綴りにも強い（0.8B は「サクラテック」を "Sakuratec"、2B は "Sakura Tech"）。そのぶん約2.8倍遅く、メモリは約2.7倍使う。重要な会議では `--mt-model pfnet/plamo-3-translate-2b-MLX-4bit` を推奨
- STT: 日本語は Haas が whisper より約5倍速い。一方で英字語に弱い（「AWS」→ Haas `os` / whisper `Oz`、「Google Cloud」→ Haas `google cloud`）

## 既知の制限

- 強制分割（`--max-sec`）は語の途中で切れることがある
- 途中表示は毎回その時点までの音声を丸ごと認識し直す。そのため whisper（en-ja / auto）で長い発話を処理すると重くなる。処理が追いつかないときは古い途中経過を捨てるので、確定版の表示が遅れることはない。ただし更新間隔は粗くなる
- BlackHole 2ch はステレオを平均してモノラル化して処理する
- Parakeet・Core Audio Process Tap は未対応
- Haas は日本語専用で、フィラーを省きがち
- 用語集は未対応（PLaMo は対応しているので拡張可能）

## ライセンス注意

- PLaMo 3 Translate: PLaMo Community License（非商用は無料、商用利用は条件あり。利用前に確認すること）
- Haas-ja: Apache-2.0。MLX 移植の haas-mlx は非公式
- mlx-whisper / whisper-large-v3-turbo などその他のモデル・ライブラリは各ライセンスに従う
