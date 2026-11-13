# Hyperframes Composition Brief: Meeting Translater

## Objective
Create a short launch-style brag video for Meeting Translater.

## Output
- Composition directory: `brag-output/composition/`
- Rendered video: `brag-output/brag.mp4`
- Format: landscape — 1920x1080
- Duration: 21.28s

## Source Material
- Project root: meeting-translater
- Primary files read: README.md, translater.py（字幕色）, desktop.py
- Product name: Meeting Translater
- Tagline / strongest claim: クラウド送信なし（Apple Silicon / MLX）
- Key UI moment: フローティング字幕（原文小・グレー／訳文大・白、ドラフト #777/#aaa → 確定 #bbb/#fff）
- Copy that must appear verbatim:
  - クラウド送信なし
  - Apple Silicon / MLX
  - 音声 → silero-vad → STT → PLaMo 3 Translate → 字幕

## Creative Direction
- Tone preset: polished / quiet premium product film
- Angle / Hook / Outro: brag-plan.md 参照
- Avoid: 汎用SaaS文言、抽象フィラー

## Visual Identity
- Background #0b0d12 / Text #ffffff / Accent #5ee6c4
- Font: Hiragino Sans, SF Mono

## Storyboard
brag-plan.md が正。Scene 1 hook 3.82s / Scene 2 subtitles 9.29s / Scene 3 local 4.36s / Scene 4 outro 3.81s。

## Audio
- Music: assets/music/bed.mp3（vol-12、CC BY 4.0 Sascha Ende, ende.app）, volume 0.3
- Cue: 13.11s と 17.47s を strong cue にロック、字幕ペアは 4.39 / 7.09 / 9.83s
- Audio-reactive: subtle（背景グローのみ、ビルド時RMS）
- SFX: impactSoft_medium_000, drop_001, click_003, impactBell_heavy_000（sparse）

## Hyperframes Instructions
Run `hyperframes check` before render. Local only.
