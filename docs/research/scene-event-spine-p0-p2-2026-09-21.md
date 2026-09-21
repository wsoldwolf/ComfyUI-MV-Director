# Scene内進行：P0〜P2の実装とオフライン評価

作成日: 2026-09-21
状態: devでP0〜P2を実装・短い実8B検証済み。全曲・H3映像の採用判定は未了。

## 結論

Sceneの全Shotを先に一括して読み、一度だけ起こる出来事とShot間の開始・終了状態をLLMに提示させた。その原文をActionとCameraの既存taskに渡す。Pythonは生成文を補作・改変しない。Cameraには「対象と手」「対象」「目と歌唱口」等の有限coverageを追加し、接触の転換Shotが対象と手を隠す候補を採用しない。

三Scene診断の二seedはEMD・Compilerまで完了し、両seedでScene進行が6/6 Shotに採用された。seed 3は苔への接近と一回の接触がShot 1→2に分かれ、Cameraも接触Shotで対象と手を指定した。一方seed 2ではsetupの終わりに既に苔へ触れ、eventでも撫でる。**構造上一回のeventと、映像上の一回性はまだ同義ではない。** 抽象歌詞「想い」をCueが接触対象として扱う既存問題も残る。このため全曲への品質合格やP3の実映像着手条件を満たしたとは判定しない。

## P0：比較基準

- モデルはローカルのQwen3 8B Q4_K_M、n_ctx=16384、temperature=0.2、max_tokens=4096、Compiler steps=8。三Sceneの固定診断は「想い」「苔」「狐火」、Sceneごとに2 Shot。元の音源・歌詞そのものではない。
- 追加taskを外した基準を保存した。seed 2はPlanner 53.62秒、LLM 30呼出し、EMD・Compiler完了。苔はShot 1と2の両方で接触し、Cameraは接触対象と手の同時可視を明示しなかった。
- 比較証跡: C:/Users/owner/AppData/Local/Temp/mvd-scene-spine-p0-baseline-20260921。同じCLI seedでもtaskの入力が変わると呼出し別seedが変わるため、厳密に同じ乱数列の比較ではない。
- 実曲については完成動画に埋め込まれた元のCompiler Planを抽出し、下記P3候補を固定した。ただし、その実曲の新Planner全曲推論と間奏対照の同定は今回行っていない。

## P1：Scene一括の進行

レイアウト確定後、Cueが有効で2 Shot以上のSceneだけを対象にscene-spine taskを呼ぶ。現在Sceneの歌詞・作者指示・Cue・Shot長だけを送り、PHASE / FROM / ADVANCE / TO / SHOWを全Shot一括で受け取る。phaseはsetup→event→responseの一回のevent、接触許可Sceneのlyric_target_handsはeventのみ、非接触Sceneでは使用不可、顔カットはface_eyes_mouthとする有限文法を使う。不整合の意味的修正は一回までで、それでも不正なら当該Sceneのみ従来のAction/Camera経路へ戻してWARNINGを出す。

Actionには同じslotの進行と前Shotの終了状態を渡す。旧Cueのvisible_developmentを別Shotへ逐語的に重ねて強制していた経路は、進行を採用したSceneでは解除した。Cueの空間anchorは維持する。既存EMDとCompilerの契約は変更していない。

追記（2026-09-22）: 外部自律effectに限り、Scene進行を採用した場合もCueのLLM原文による可視展開をevent Shotへ必須転送するよう変更した。映像で狐火が欠落した実例では、対象名だけが残り現象自身の移動がActionから消えていたためである。人物の物理接触を重複させない上記の通常対象ルールは維持する。詳細は[統合レポート](planner-scene-spine-motion-effect-integration-2026-09-22.md)を参照。

## P2：Camera coverage

CameraはAction確定後の既存一段のまま。Scene進行のSHOWと確定Actionを同時に読み、必要coverageとズーム・画角の整合を検査する。接触eventの顔だけの寄り、対象を隠す極端な画角は不適合。対象のない顔表情は目・眉・歌唱口が読めるcoverageを使う。Cameraの新しい推論taskはない。

| 条件 | Planner | LLM呼出し | Scene進行採用 | 苔の評価 |
|---|---:|---:|---:|---|
| 基準 seed 2 | 53.62秒 | 30 | なし | 二Shotとも接触。対象＋手のcoverage不在 |
| 最終P1/P2 seed 2 | 50.29秒 | 32 | 6/6 Shot | setupで接触開始、eventで撫でる。対象＋手はeventのみ指定。意味上の一回性は未達 |
| 最終P1/P2 seed 3 | 50.02秒 | 32 | 6/6 Shot | Shot 1が準備、Shot 2が一回の接触。対象＋手もShot 2に指定 |

結果の証跡はそれぞれ C:/Users/owner/AppData/Local/Temp/mvd-scene-spine-p2-grammar-seed2-20260921 と C:/Users/owner/AppData/Local/Temp/mvd-scene-spine-p2-grammar-seed3-20260921 に evidence.json、generated.emd.md、plan.json として保存した。途中段階ではseed 3がevent重複でScene進行を不採用にした。有限文法の導入後は両seedで構造採用できた。実行時間はQwenの出力・再試行の差を含むため、短い二回だけで速度向上とは判定しない。約6分の全曲やRTX 5060へ外挿もしない。

## P3用PlanとScene

完成動画 C:/Software/ComfyUI/output/h3_chains/mv_director_context_loop/final/t2v_normal_2026-09-21.mp4 のComfyUI prompt metadataに埋め込まれた元のCompiler Planを、そのまま C:/Users/owner/AppData/Local/Temp/mvd-scene-spine-p3-waterfall-20260921/plan.json に抽出した。SHA-256は 4f7651c8ff2085bc6813e846d6fe776cf08f755cc2203f2967021c50daa3f473。30 SceneのPlanで、Scene Debug Splitterが読み取れることを確認した。

**比較候補はScene 9（1ベース、scene_start=9、scene_length=1）。** 元Planの二Shotがどちらも紅葉を取って葉脈をなぞるため、同じ動作の再開始を比較できる。Splitterのスキップは1761 frame、選択は238 frame（24 fpsで約73.375〜83.292秒）。元動画で実行されたScene seedは1945693048366462725、steps=8。人物参照・背景参照・フルミックス・ボーカルステムの四アセットはComfyUI inputに現存する。Scene 22は苔の描写だが**1 Shotだけ**なのでScene内のShot進行比較には使わない。

これは既存完成動画の**A側Plan**であり、新実装による同曲C側Planではない。P3のA/C映像比較をする前に、同じ実曲入力で新Planner/Compilerを実行し、Scene 9のActionとCameraがEMD・H3 promptの両方で改善したことを確認する必要がある。P3のH3レンダリングは今回行っていない。

## 残る課題・次の判定

1. Cueが抽象的な「想い」を物理的な対象として誤認する場合、今回の接触event契約だけでは防げない。Scene進行を全曲標準採用する前に、Cue側の「実在する接触対象」判断を評価する。
2. seed 2のsetup接触のように、有限PHASE/SHOWと自由文の意味が食い違う場合がある。Pythonで語句を置換して見かけ上の成功にせず、Action原文・Camera原文とH3 promptを採点する。
3. Scene 9を同条件で再生成したC側Planが一回の落葉動作と対象＋手の可視性を満たし、計算費が許容範囲ならP3の一Sceneだけを同じ参照・音源・H3モデル・steps・seedでレンダリングする。全編生成はその後に判断する。

関連: [元のP0〜P3計画](scene-event-spine-validation-plan-2026-09-21.md)。
