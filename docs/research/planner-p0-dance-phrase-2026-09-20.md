# Planner v56：P0・連動する身体演技の実装と8B検証

## 結論

P0の実装と構造検証を完了した。ただし、**8B出力の演技品質はまだ目標未達**。
脚を含む動作や閉眼は戻ったが、手振り偏重と同じScene内の動作再実行が残る。
この結果を「プロトタイプ相当のダンスが実現した」と評価してはいけない。
動画は今回レンダリングしていない。P1のCamera同期仕様も実装していない。

## 実装範囲

- `profiles/motion/anime_emotional_mv.md`に`performance_mode=dance_phrase`を追加。
  Motionファイルで選択し、新UIは追加しない。省略時は`event_based`。
- 既存Cue Cardの九項目を維持し、`身体主導`と`終端`を連続した演技の設計へ使用。
  支持・重心、胴体、腕、表情のつながりを具体的な動詞で要求する。
- Actionは同じ既存段階で、短い日本語の専用promptへ切り替える。
  Scene内の準備・アクセント・解放をShotへ分配し、顔Shotは表情のaccentとして扱う。
- 有効な歌詞対象の配置・可視展開の必須fragment、外部effectの自律性、
  走行・内部protocol混入等の検査を維持。Pythonによる演技文の補作は加えない。
- `左足`等の語だけで下半身主役と判定する検査を、選択modeで解除。
  全身の踏み替えと足先・履物の細部主役化の区別は既存の意味監査へ委ねる。
  意味監査は品質保証ではなく、足の生成崩壊を解決する処理でもない。
- 監査最大二回・間の修復一回、新しいLLM段階ゼロを維持。
  v54の歌詞Discoveryは元からある一段であり、今回の追加ではない。
- Planner v56のcache分離とmetadataのcache identityを実装。modeをINFO出力する。

他のMotionは通常Action promptのまま。Camera側だけ`anime_emotional_mv`でも有効にならない。
外部callerが専用promptを供給しない場合は従来Action promptへ戻る。

## 実8Bの試験条件

GPUを解放いただいた後、RTX 5090でローカル推論を実行した。ComfyUIを停止したり、
他のモデルを強制解放したりする処理は行っていない。試験終了時に試験用モデルを解放した。

- GGUF：`qwen3-8b-abliterated-Q4_K_M.gguf`
- SHA256：`8625e48da4c4be9bcba2414fd8cad4095ff3a538d5b0111c2b26b5f6209538b9`
- ComfyUI venvのllama-cpp-python、全GPU層、`n_ctx=16384`、`n_batch=512`、Q8 KV、Flash Attention。
- `max_tokens=1536`、temperature 0.2、top_p 0.9、repetition_penalty 1.05、base seed 1。
- 合成した四Scene・約40秒の小規模fixture。原文は「想いを届けたい」「苔に残る記憶」
  「参道に咲く花」「宙を舞う狐火」。全てCHORUS、各10秒・既存Shot開始0/3/6秒。
  PlannerがH3境界とlayoutを処理し、採用結果は各版とも四Scene・16Shot。
- Motion/Cameraをemotional、夜間、単一Subject、`scenes_per_batch=1`、lip_sync off。
  Directionは試験内で構築した。Vision、Enhancer、Compiler、音源解析、H3は実行していない。
- baselineは`cfe8ca2`のBeat/Action/Audit promptとMotion本文を読み、現在のtransportで
  `event_based`として実行した比較用経路。旧checkout全体の再現ではない。
  call seedはtask・payload等から派生するため、base seedが同じでも候補間の乱数列は異なる。
  別seedや本番歌詞全体での品質改善を証明するA/Bではない。

[比較資料JSON](../assets/research/planner-p0-2026-09-20/comparison.json)に設定、
Cue応答、全採用Action、task別call数、最終promptのhashを残した。
詳細traceと試験EMDはローカルの
`C:\Users\owner\AppData\Local\Temp\mvd-p0-20260920\`に保存している。

## 試行結果

| 試行 | 完成 | 全call / Action / Audit | 秒（モデルload除外） | 判定 |
|---|---|---|---|---|
| baseline | yes | 46 / 14 / 8 | 67.5 | 対象だけが動き、身体主導が四Sceneとも「なし」 |
| 初回P0・通常promptへ追記 | yes | 46 / 12 / 8 | 88.4 | 身体動作は戻るが、手振り・接触の反復 |
| 専用Action promptへ短縮 | yes | 42 / 12 / 8 | 72.5 | 入力は短縮、演技欄は依然短い手の動作 |
| 振付の具体例＋記述量を明示 | yes | 47 / 13 / 8 | 110.1 | 例文を四Sceneへほぼコピー。**不採用** |
| 具体例撤去後・今回採用候補 | yes | 46 / 13 / 8 | 96.4 | 身体・表情は部分回復。反復と手振り偏重は残存 |

専用Action promptの採用で、このfixtureの初回Action入力は従来約7千tokenから約4千tokenへ
減った。一方で生成本文や修復によって総時間は増えた。**高速化したとは結論しない**。
5060の性能・VRAM使用量は測定していない。

### 回復したこと

最終候補のScene1は「手を伸ばしながら、足は軽く前へ踏み出す」から
「手を下ろしながら、目を開き、足を戻す」へ進む。Scene3にも支持を変える動作と
閉眼が現れた。対象だけを動かすbaselineに比べ、人物の演技が戻る方向は確認できた。
苔の配置、花の可視変化、上空の狐火も最終Actionへ転送されている。

### 未解決のこと

1. **つながるダンスとしては不足**。Scene2は依然右手を上げ、胸前へ手を置き、
   下げ、腰へ添えるという手振り中心。上体・重心の連動を十分には具体化できていない。
2. **Scene内の全フレーズ再実行**。Scene4は踏み出し、腕を伸ばし、腰へ手を添える
   同じ文をslot1〜4で繰り返す。Cueの終端を「戻す」にしてもAction側の分配が弱い。
   意味監査は警告したが、既存上限後は採用文をAS ISで残している。
3. **Discoveryの意味誤りは別に残る**。「想い」を物体的な対象として選び、
   「参道に咲く花」では花ではなく参道を選んだ。花は可視展開に残るが正しい選択とは言えない。
   そのため、この試験のScene1を厳密な「対象なし」試験として扱わない。
4. 苔が短時間で石段全体を覆う等の過剰な変化、花の発光、狐火へ手を伸ばす曖昧な
   関係も残った。固有名詞が残ったことと、物性・演出が適切なことは別である。
5. Cameraの既存品質fallbackも発生した。今回の結果からCamera同期の改善は主張しない。

具体的な振付例は、禁止文を添えても8Bがそのまま流用した。今回の製品promptからは撤去した。
Pythonで動作辞書を増やしたり、全Sceneへ別々の振付を機械注入したりして解決した扱いにしない。

## 検証と次の判断

ComfyUI venvで`python -m unittest discover -s tests -p "test_*.py"`を実行し、
**398件成功、失敗0、skip 0**。metadataのkind/値検査、旧Motionの既定値、cache分離、
専用promptの選択、既存stageへの伝達、採用文の不変性、走行・必須fragment検査を確認した。
これらは構造・回帰テストであり、映像の演技品質テストではない。

適用にはComfyUI再起動後、DirectionのMotionに`anime_emotional_mv`を選び、
Direction/Plannerを再生成する。既存の保存済みPlan/EMDは自動更新されない。
INFOの`performance_mode=dance_phrase`で適用を確認できる。WFの配線変更は不要。

P0は実装済みだが品質合格は保留とする。全編を再レンダリングする前に短い歌唱区間で
確認し、次はActionがScene単位の振付を毎Shotで再実行する理由を優先して絞る。
場当たり的な監査増加や完成振付例の追加ではなく、既存の順序・終端情報を使う
分配の改善を先に比較する。P1のCamera同期拡張へ進む前に、この反復を減らす必要がある。

関連：[元の分析・P0/P1計画](anime-emotional-mv-performance-camera-review-2026-09-20.md)、
[profile仕様](../../profiles/README.md)、[protocol仕様](../spec/protocol-spec.md)。
