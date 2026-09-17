# Prototype camera and motion baseline (2026-09-17)

`ref2v_2026-09-12-8b.mp4`に埋め込まれたComfyUI metadataと映像を、現行`anime_mv` profile及びTimeline Plannerの比較基準として調査した記録です。この動画ファイルはrepository又は実行時の依存物にはしません。

## 確認できたmetadata

- 映像は1280×736、24 fps、約139.04秒、3337 frameです。
- containerには`prompt`、`workflow`、`h3_plan`、`h3_manifest`が残っています。
- `h3_plan`は13 Sceneです。Scene 1はcontextなし、Scene 2～13は`context_length=22`及び`audio_context_length=22`で、映像状態をScene間で継続します。
- Camera記述では13 Scene中6 Sceneに被写体側面を通るarc系移動があり、他に前進、後退、横方向追従、垂直移動を分散して使っています。

## 映像とPlanで共通していた特徴

- extreme face close-up、medium、full body、very wide establishingを交互に使い、同一scaleを連続させません。
- 低い斜め前方からの接近、鳥居や樹木を前景へ通す横追従、被写体側面を抜けるwide arc、後方三分の四又はover-shoulder追従、下方から顔へ抜ける垂直移動、社殿から鳥居方向へ空間を開く後退があります。
- Camera移動には開始視点、経路、終了視点及び前景・中景・背景の視差があり、単なるzoomの反復ではありません。
- 人物は前進、振り返り、腕を伸ばす、胴体をひねる、画面を横切る、鳥居や石段へ接触する等を組み合わせ、予備動作、主動作、反動、収束を持ちます。

## 現行実装への反映

- `profiles/camera/anime_mv.md`はMiniMax H3正式Motion TypeをCamera行頭に要求し、上記のArc Shot、Tracking Shot、Pedestal Up及びPull Outの構図例を持ちます。
- `profiles/motion/anime_mv.md`は方向転換、環境接触、明確な加速・停止と通常歩行の足運びを定義し、明示のない摺り足を避けます。
- Scene境界の再計画は、後続境界の4分の1以上をCUT、半数以上をCONTINUE、同一mode最大3連続及びmode遷移数上限とする構造契約を検証します。完全なCUT/CONTINUE交互列も不合格です。違反した再応答はCUT/CONTINUE列だけを最小変更で修復し、自然文を変更しません。
- Compilerは正式Camera Motion Typeとamplitude/speed句を翻訳LLMから保護し、Planへ完全一致で復元します。

この基準は特定のCamera語を全Shotへ固定するものではありません。歌詞と身体動作に適格なShotへarc又はtrackingを割り当て、Scene継続によってH3の状態を保ちながら、意味のある編集点だけをCUTにするための比較基準です。
