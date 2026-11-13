# Brag Plan: Meeting Translater

> **改訂（v2, 24.9s）**: 利用画面シーンが抽象的で伝わらなかったため作り直し。
> 1 フック「その会話、どこに送られてる？」→「クラウド送信なし」(0–3.82)
> 2 オンライン会議で：会議ウィンドウ＋「Meeting Translater の字幕」ラベル付き字幕窓、入力 BlackHole 2ch、英→日 2ペア (3.82–10.93)
> 3 対面の会話でも：左右2人が日本語/英語で交互に話す、入力 Macのマイク、日本語⇄英語を自動検出（README `--direction auto`）(10.93–17.47)
> 4 ローカルで文字起こし、翻訳 (17.47–21.84)
> 5 Meeting Translater「会議も会話も、ローカルでリアルタイムに翻訳。」(21.84–24.9)
> パイプラインチップは削除。以下は v1 の記録。

## What is this app?
会議・配信の音声をローカルでリアルタイムに文字起こし＆翻訳し、原文＋訳文をフローティング字幕で出す Mac アプリ。クラウド送信なし（Apple Silicon / MLX）。

## The angle
「その会議の音声、どこに送られてる？」→「クラウド送信なし」。翻訳字幕ツールの一番の売りは精度ではなくプライバシー。静かなプロダクトフィルムで、字幕が実際に流れる様子を見せる。

## Hook (first 2-3 seconds)
「その会議、どこに送られてる？」→ 暗転の間のあと「クラウド送信なし」が入る。

## Key moments (the middle)
- 字幕ウィンドウに原文（小・グレー）＋訳文（大・白）が、確定前のグレー→確定の白で流れる（アプリ実装どおり）
- パイプライン 音声 → silero-vad → STT → PLaMo 3 Translate → 字幕 が字幕に合わせて順に光る
- 「ローカルで文字起こし、翻訳」＋ `クラウド送信なし` / `Apple Silicon / MLX`

## Outro / punchline
「Meeting Translater」→「会議の音声を、ローカルでリアルタイムに翻訳。」

## User flow worth showing
音声が入る → 字幕ウィンドウに原文が出る（ドラフト）→ 確定して訳文が白で出る。

## Tone
- Preset: polished
- Creative direction: quiet premium product film（静かなプロダクトフィルム）
- Interpretation: 少ないシーン、長めの保持、音は控えめ。問いかけ→答えで構成。

## Format: landscape — 1920x1080
## Duration: 21.3s

## Visual identity (from the project)
- Background: #0b0d12（字幕は透過黒。プロジェクトに固有色なし → 暗色で統一）
- Accent: #5ee6c4（プロジェクトに無いため新規選定。「ローカル/安全」を示す1色のみ）
- Text: #ffffff / 原文 #bbbbbb / ドラフト #777777・#aaaaaa（translater.py の字幕色）
- Display font: Hiragino Sans（システム日本語）
- Body font: Hiragino Sans / SF Mono（パイプライン表記）
- Strongest visual element: フローティング字幕（原文小・訳文大）

## Share copy (draft)
会議の音声をクラウドに送らず、Macの中だけでリアルタイム翻訳。Meeting Translater。

## Audio direction
- Role: sparse professional accents
- Music: happy-beats-business-moves-vol-12（polished 向け）
- Music treatment: 0s開始、volume 0.3、最後の1sでフェードアウト
- Music cue guidance: bundled preset 使用（110 BPM）。strongCue 13.11s=シーン3頭、17.47s=ワードマーク。ビート 4.39 / 7.09 / 9.83 に字幕ペア。
- Audio-reactive treatment: subtle; 音楽RMSで背景グローの明るさのみ呼吸。波形/イコライザなし。
- SFX posture: sparse
- Audio-coupled moments: フック答え、字幕ペア出現、ワードマーク
- Restraint rule: 字幕の可読性を優先、SFXは4種のみ

## 使用する架空データ
字幕デモの文言（定例会議の例）は実音声ではなく架空の例文。製品の主張ではない。

## Storyboard

### Scene 1 — Hook — 3.82s
「その会議、どこに送られてる？」(0.3s〜、保持〜2.4s) → フェードアウト → 「クラウド送信なし」(2.5s、accent、保持)
Sequential/interaction: no
Audio intent: 静かな問い、答えで一拍
Audio-coupled idea: 答えの出現に soft impact
Transition mood: clean → Scene 2

### Scene 2 — Subtitles in motion — 9.29s
会議タイル風の暗い背景＋上部にパイプラインチップ、下部にフローティング字幕。3ペアが 4.39 / 7.09 / 9.83s に順に出る。各ペアはドラフト色→確定色へ。
Sequential/interaction: yes — 字幕3ペアを順に、各 ~2.7s 保持
Audio intent: 軽い手触り
Audio-coupled idea: 各ペア出現に drop
Transition mood: soft → Scene 3

### Scene 3 — Local — 4.36s
オフライン風アイコン＋「ローカルで文字起こし、翻訳」＋チップ `クラウド送信なし` `Apple Silicon / MLX`。13.11s（strong cue）で開始。
Sequential/interaction: yes — アイコン→見出し→チップ
Audio-coupled idea: アイコンの斜線に click
Transition mood: soft → Scene 4

### Scene 4 — Outro — 3.81s
「Meeting Translater」(17.47s strong cue) →「会議の音声を、ローカルでリアルタイムに翻訳。」
Sequential/interaction: no
Audio intent: 静かな着地
Audio-coupled idea: ワードマークに bell
Transition mood: fade out

**Music mood for this video:** polished, steady
**Audio summary:** 控えめなビートに乗せ、答えと着地だけに効果音。
