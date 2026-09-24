# Audio参照版：苔・花Sceneの簡潔な映像仕様A/B（2026-09-24）

## 問い

H3は同じ元Planとseedでも、Scene 3を独立開始した時には好評の苔と手の演技を生成し、Scene 2からGuideを引き継いだ時には手への寄りの後に足袋の指が崩れる足元接写へ逸れた。[前段の比較](audio-reference-scene3-4-comparison-2026-09-24.md)を受け、8BとPythonが細部を増やすより、H3へSceneの対象・人物との関係・見せる変化を簡潔に渡した方がよいかを小範囲で確認する。

## 条件

- 基準：保存済み`C:\Software\ComfyUI\output\mv_director\audio_reference_plan_00001.txt`を使用したScene 2–4連続生成。基準動画は`C:\Software\ComfyUI\output\h3_chains\audio_ref_body_s2_4_context_20260924\final\audio_ref_body_s2_4_context_20260924.mp4`。
- 比較：[生成スクリプト](../assets/research/audio-reference-body-isolation-2026-09-24/build_compact_scene3_4_plan.py)と[簡潔版Plan](../assets/research/audio-reference-body-isolation-2026-09-24/compact-visual-scene3-4-plan.json)。元PlanのSHA-256は`3dce5133ab8f42aa12e2762439793fb4ed08863c99ce48689f8d3eeb1035eda9`、比較Planは`5f90d9b0c0939a5a467298fbc7cf1713866be4d1e34c4f37865f2eafc97206f0`。
- 変更はScene 3・4それぞれの概要とShot固有文だけ。Scene 3は3行、Scene 4は4行を変更した。苔に触れる、花が開いて散る、Push In／Arc Shot／Tracking Shotの種類と各Shotの開始時刻は維持した。Scene 3本文は6,457→5,788文字、Scene 4は7,019→5,869文字。
- 人物・背景の参照説明、全域prompt、Scene 2、全Scene長、継続方式、seed、音声、H3グラフとモデルは変更しない。Scene 2から開始してScene 3・4へGuideを引き継ぎ、前段で足元への逸脱が見られた条件と比較する。
- 今回は手書きPlanによるH3実験であり、8BやPythonの本番パイプラインを変更したものではない。「短い文」と「対象・手・顔を同時に見せる肯定的coverage」を一緒に変えているため、もし改善してもどちらが効いたかはこの一実験では分離できない。

## 判定基準

映像を連続再生し、①苔を触れる手への勢いある寄りを残すか、②花の出現・開花・散華と人物反応を残すか、③足元だけの長い接写と足袋の五趾化が減るか、④Scene 3から4への接続が自然か、を人間の評価を主として比較する。静止画やSSIMは位置の確認・映像同一性の検査にだけ使い、演出の良し悪しを決めない。対象のない他Sceneへ規則を拡張しない。

## 結果

簡潔版は3クリップ・736フレーム、864×480、24 fpsを384.05秒で正常生成した。[連続動画](<C:/Software/ComfyUI/output/h3_chains/audio_ref_compact_s2_4_20260924/final/audio_ref_compact_s2_4_20260924.mp4>)のSHA-256は`147abfe43f1ac10114d0c681df700d265ad3dd6a469d193fd326f8c65f957b4a`。検証用ComfyUIはキューが空であることとプロセスの親子関係を確認して終了した。

変更していないScene 2は基準版と全277フレームが画素レベルで一致した（SSIM All 1.000）。したがってScene 3へ渡る直前の映像Guideは同一であり、以降の差は変更したScene 3・4の局所文に起因する条件として読める。

時系列の代表フレームでは、[簡潔版Scene 3](<C:/Software/ComfyUI/output/h3_chains/audio_ref_compact_s2_4_20260924/segments/clip_0002.c2dc65d4190746c09ef13168602751cb.mp4>)は人物が身体を沈めて大樹の苔へ近づき、手の寄りと歌唱する顔へつながる。基準のScene 2–4連続版で後半に生じた長い足元・下駄接写は見られず、足袋の五趾化もこの代表フレームには現れない。[簡潔版Scene 4](<C:/Software/ComfyUI/output/h3_chains/audio_ref_compact_s2_4_20260924/segments/clip_0003.5e91e98dc65045eb8a9023ec208c8ab6.mp4>)は苔の近くに蕾を映し、開花、花びらの散り、人物の手と顔の反応へ進む。ここも代表フレームに足元の接写はない。

ユーザーは簡潔版Scene 4の連続映像を見て、手前の花と奥に立つ人物を見上げるようなカメラ構図、花びらの散り方が持つメッセージ性、そして足元のアップが出ないことを明確に評価した。前段の詳細版にも花の動きの良さはあったが、今回はその良さを保ちながら、目立つ足袋破綻を誘う接写を避けられた。Scene 3の接触演技の最終評価は、この花Sceneの評価と混同しない。

**判定はScene 4について局所的に良好、本番導入は保留。** 同じ前Sceneの映像Guideから出発して足元への逸脱が減ったが、「文章を短くした効果」と「苔／花・手・顔の肯定的coverageを明示した効果」を今回の一条件では分離できない。H3の演出能力を確認する実験であり、8Bがこの簡潔な文を安定して生成できることや、全曲・他Sceneでも改善することは示していない。次に進むなら、同じSceneの保存済みPlanで二要因を分ける一クリップ単位の追加比較を検討する。本番profile、Planner、Compilerには変更を加えない。
