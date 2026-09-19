# Timeline Planner

Lyric Segmentationが確定したScene/Shot枠へ、歌詞解釈、人物動作、カメラ、リップシンクdirectiveを展開して完成EMDを作ります。人物動作とカメラは別のLLMタスクで生成し、Pythonが同じShotへ合成します。

長尺曲でも全Sceneを一度にLLMへ渡しません。視覚beat、Shot layout、人物動作及びカメラは`scenes_per_batch`件ずつ処理し、各Sceneへ直前Sceneの歌詞と視覚beatだけを境界文脈として添えます。これにより曲長に比例して一回のcontextが増え続けることを防ぎます。反復回避用には直近12 SceneのVisual Beat、直近18 ShotのAction及び直近12 ShotのCameraだけを生成requestへ渡します。一方、生成後の完全一致・高類似度検査はその段階の全採用履歴に対して行うため、数Scene離れて再出現した定型動作も該当slotだけのLLM再要求へ送ります。

## 主な入力

| 入力 | 既定 | 説明 |
|---|---|---|
| `template_emd` | 必須 | Lyric Segmentationの出力 |
| `concept_emd` | 任意 | Subject等の概念EMD。Picture参照なしでもよい |
| `direction` | 任意 | Direction Enhancerのtyped出力 |
| `lip_sync_mode` | `lyrics` | `off` / `context_loop` / `audio_reference` / `lyrics` |
| `lip_sync_target` | `サブジェクト1` | リップシンク対象。`サブジェクト1..4` |
| `lip_sync_audio_slot` | `1` | Audio参照時の1～3 |
| `model_name` | 自動列挙 | Text GGUF。8B級推奨 |
| `model_name_override` | 空 | 外部STRINGでmodel選択を上書き |
| `scenes_per_batch` | `3` | 一回に計画するScene数 |
| `cache_mode` | `reuse` | 成功結果の再利用方針 |
| `save_debug_output` | `false` | 一時ディレクトリへLLM traceを保存 |

既定の`max_tokens=4096`、`temperature=0.1`、`n_ctx=16384`等は[GGUF共通設定](gguf-settings.md)を参照してください。

## 出力

| 出力 | 用途 |
|---|---|
| `emd_text` | 編集可能な完成EMD。Compilerへ接続する |
| `emd` | 内部typed EMD artifact |
| `status` | Scene/Shot数、cut/continuation数、issue、retry、fallback、cache等 |

## 計画方針

Plannerは歌詞内の具体物、場所、感情をvisual beatへ変換し、触れる、振り返る、視線を移す、環境へ反応する等の動作候補を作ります。単なる歩行、正面立ち、両手を広げる、手を上げる又は前を見る動作を既定にせず、歌詞ごとに場所の状態、具体物又は象徴的な環境モチーフ、人物の意図的反応及び可視結果を組み合わせます。Directionが許す時は、遠い鈴に反応する紙垂、風に動く鳥居周辺、狐火又は霊的な粒子等を選択的な節転換モチーフとして使えます。効果だけを装飾的に浮かべず、人物の接近、回避、誘導、接触又は解放へ結び付けます。同じ効果を全Sceneへ配置せず、再登場時は状態を変化させます。

各Shotには自然文と別に`performance_role`を付けます。複数ShotのSceneでは、顔と上半身のaccent、腕・手が主役の演技、環境との相互作用又は振り返り、異なる終端silhouetteへ役割を分散します。Scene-level visual beatが移動であっても、全Shotを同じ歩行cycleへせず、歩行は必要なShotの接続動作に限定します。Cameraにも`editorial_role`を付けます。ただし、リップシンク有効かつ歌詞sectionが初登場するCUT Sceneでは、section名を持つ最初の歌詞annotationが実際に属するShotだけを有限個の構造的な顔インサートとし、ActionとCameraをLLM要求から外してRenderer所有の固定文を割り当てます。Scene開始と歌詞開始が異なる場合も、無音のScene先頭へ顔歌唱を置きません。Actionは歩行や全身移動を禁止して両目、眉及び完全な口による歌唱演技だけを要求します。Cameraは`Zoom In with large amplitude at fast speed`で正面又は斜め正面の頭肩構図から極端な顔close-upへ進み、両目、両眉、鼻、完全な歌唱口及び顔輪郭を全行程で同時に表示します。Compilerはこの二つの英語文を翻訳LLMへ渡さず、そのままH3 promptへ保持します。それ以外のAction及びCameraは、合格したLLMのTEXTをAS ISで使います。これにより固定phraseが通常Shotへ漏れることと、顔Cameraへ歩行Actionが競合することを防ぎます。

固定顔インサートのActionは、Subjectで既に記述された眉の個数、compactness、形、配置及び色を顔演技中も維持します。特殊な眉markを通常の長い線状、湾曲又は弓状の眉へ置換しません。この契約は丸眉だけの固有例外ではなく、点、楕円又は豆形等の局所的な識別形状を表情演技で通常形へ正規化しないための共通契約です。

固定顔インサートには、同一Scene内の隣接する通常Shot一個を構造的に対応付けます。顔インサートがScene先頭なら次Shotを`arc_out_of_previous_face_cut`として顔のスケールから30～60度のArc半径を広げ、上半身、全身又は環境を開示します。顔インサートが後方なら直前Shotを`arc_into_next_face_cut`として身体・環境coverageから顔へArcで入り、次の固定顔アップへ接続します。このCamera slotが`Arc Shot`以外を返した場合、本文をPythonで変更せず該当slotだけを一度品質再要求します。

Visual Beats及びActionsへはSubjectの`concept_id`と`<Subject N>`だけからなる構造的rosterを渡し、Concept EMDの詳細な外見、身体構造、衣装構造、履物、色、材質及び参照保持文は創作sourceとして渡しません。Concept EMD本文は最終EMDへAS ISで保持され、Compiler/H3のSubject定義としてだけ機能します。これにより破綻防止用の局所detailが全Sceneの動作や撮影主題へ昇格することを防ぎます。Visual Beats及びActionsへはDirectionのStyle、Environment、Time/Lighting、Motion、Otherだけを渡し、Camera profileはCamerasだけへ渡します。これにより`Arc Shot`等の撮影語が人物動作へ混入することを防ぎます。各段階へ渡されたDirectionは生成済みvisual beat、履歴及びLLMの演出補完より上位です。採用した行をPythonの単語表や正規表現で書き換えず、最終`ACTION`及び`CAMERA`本文をAS ISでEMDへ渡します。

Visual Beat、Action又はCameraの長い出力が、同一batch若しくは直近履歴と完全一致又は高い表層類似度を持つ場合、Pythonは文章を変更せず、そのslotだけを該当Scene単位で最大二回再生成します。再要求には元の`rejected_output`、衝突した`must_differ_from`及び直近と同一batchの採用候補をまとめた`forbidden_recent_outputs`を渡し、主動詞、対象、可視結果、終端silhouette又はCamera目的を実質的に変えるようLLMへ要求します。左右交換、同義語又は語順変更だけでは修復とみなしません。二回の再試行後も類似する場合は再応答をAS ISで採用し、`repetition_warnings=total(beat=B,action=A,camera=C)`としてWARNINGログとstatusへ記録します。これは創作上の品質警告であり、Compilerを停止しません。この検査も生成文の置換・要約を行わないためAS IS原則を維持します。

UIの固定seedは実行全体の再現性を所有しますが、各LLM呼び出しではtask、call番号及びpayloadから決定的に異なる`call_seed`を派生します。同じ固定seedと同じ入力は同じ結果になりますが、複数batchとdiversity retryが毎回同じ乱数列の先頭を再利用して同じ定型句へ収束することを防ぎます。

`anime_story_mv`では静かな溜めと、明確な加速、重心移動、方向転換、鋭い停止及び大きく異なる終端ポーズを対比させ、均一に緩慢な補間を避けます。二コマ・三コマ打ちは静止hold、表情の溜め及び末端追従へ限定し、主要な身体動作、関節軌道、接地及び重心移動は時間方向に連続させ、pose飛び、瞬間移動、四肢の往復反転及び痙攣状motionを要求しません。通常歩行は遊脚を地面から持ち上げ、前へ運び、踵又は足裏を接地して重心を移し、作者指定なしの摺り足、引き摺り及び滑走を生成しません。Camera行はMiniMax H3の正式名称から必ず開始します。`anime_story_mv`のCamera batchでは離れた最大二Shotを構造的な長尺Arcへ指定し、利用可能なShotのうち長いものを優先して60～120度の経路をShot尺の70～90%にわたり連続させます。固定顔インサートは頭肩構図から極端な顔アップへ進む`Zoom In with large amplitude at fast speed`とし、両目、両眉、鼻、完全な歌唱口及び顔輪郭を全行程で残します。固定顔インサートが無いリップシンクbatchでは、長尺Arcと競合しない表情結果又は上半身coverage一件へ同じ顔Zoom契約を追加します。隣接Arcは身体・環境から顔Zoomへ入るか、顔Zoomから上半身・全身・環境へ抜けるため、Arcと顔拡大が一連のCamera展開になります。別の移動Shotは`Tracking Shot`で追従します。Pythonは通常Camera自然文を書き換えず、LLMへ構造契約を渡して採用行をAS ISで使用します。従来の穏やかで映画的な動作・カメラ設計は`cinema_mv`として選択できます。

歌詞又は作者が走行を明示しない限り、走る、駆ける、疾走する又は逃げるActionを生成しません。特に間奏では走行をMVの勢いの代用にせず、胴体の旋回、振り返り、高低差、腕の演技、環境相互作用、鋭い停止、異なる終端pose及び独立したCamera運動で強度を作ります。未指定の走行がActionへ出た場合は本文を書き換えず、そのslotだけを品質再要求します。

Shot layoutは通常一Sceneあたり2～3 Shotを選び、4 Shotは8秒以上かつ4つの異なる視覚目的を各2秒以上確保できる場合だけに限定します。Cameraはlocked Actionに必要な身体部位と接触対象を画面内に残し、全身動作へ極端な顔cropを組み合わせません。MiniMax H3 Motion Typeと後続説明の物理動作も一致させ、`Static Shot`で接近する、`Tilt Down`で上昇する、`Pan`で平行移動する等の矛盾を禁止します。

`anime_story_mv`の髪、体毛、動物耳、耳内部、尾、皮膚及び衣装は非発光素材として扱います。作者が発光を明示しない限り、ActionとCameraはこれらを「輝く」「光る」「glow」等の演技又は撮影目的にせず、月光、逆光及び灯火は通常の反射光へ限定します。耳内部の局所的なglow、bloom、halo、強い透過光及び白飛びも要求しません。この制約はPlanner出力を後段で書き換えるfilterではなく、固定Styleと各LLM taskの生成条件です。

Scene境界ごとに`CUT`又は`CONTINUE`も選びます。新しい画角、detail、逆方向又は場所を編集点で提示する時は完成EMDのScene見出しから`継続`を外し、直前の画像状態とカメラ経路を引き継ぐ時だけ`継続`を残します。歌詞が記憶、問い、恐れ、孤独、涙、別れ、自己認識又は決意へ移るSceneでは、新しい編集点を選べます。実行可能な範囲で新section初出SceneをCUTとして保持し、極端な顔インサートはそのScene内で新sectionの歌詞を実際に持つ最初のShotへ置きます。通常coverageでは正面又は斜め正面のmedium、medium close-up又はhead-and-shoulders Shotを必要に応じて使い、手、髪、小物、後頭部又は完全な横顔で目や唇を隠しません。局所detailと顔を一つのCamera行へ同時要求せず、歌詞上必要なdetailは別Shotへ分離します。Concept EMDが1 Subjectだけなら、人物動作とカメラへ単独instance policyを渡し、各Camera行で画面内にその人物一体だけを置きます。参照設定画の左右panel、別角度、鏡像又は背景の似た人物を二人目として再現させません。候補数超過、区切り、重複又は未知候補だけのLAYOUT差異は、既知候補の時系列順整列、重複除去及び最大4 Shotへの切り詰めで機械修復します。各Sceneには直前の歌詞とVisual Beatも渡し、4 Scene以上で最初のmode列が後続境界数の4分の1以上のCUT、半数以上のCONTINUE、同一mode最大3連続及びmode遷移数上限を満たさない場合は、隣接関係を比較する境界mix再計画を一度だけ実行します。CUT/CONTINUEの完全交互列は遷移数超過として不合格です。再応答も構造契約を満たさない場合は、PythonがCUT/CONTINUE列だけを元の選択から最小変更で修復します。Action、Camera及び候補Shot本文は変更せず、変更したScene番号を`layout_repaired_scenes`へ記録します。実行有無は`layout_mix_retry=yes/no`へ出します。境界mode自体を認識できない場合だけ`CUT,B0`へfallbackします。境界mode変更時はPlannerが`H3長`とPlan上のScene/Shot時刻をH3格子へ再配分します。Scene内の`## ショット`は一回のH3生成内の時刻付きprompt変化であり、hard cutを保証しません。

Action batchにはslow表現上限、単純な手の上下0件及び作者未指定の足元主体0件という構造予算を渡します。違反を検出した場合、PythonはAction本文を変更せず該当slotだけを`action_quality_budget`として一度再要求します。Camera batchは通常`Arc Shot`最大1件、`anime_story_mv`だけ最大2件、`Tracking Shot`最大1件、その他の同一Motion Type最大2件、slow表現上限及び作者未指定の足元detail 0件という構造予算を持ちます。`anime_story_mv`の`long_arc_emphasis`又は顔遷移がArc以外になった場合も、該当slotだけを`camera_quality_budget`として一度再要求します。PythonはCamera本文を機械生成又は書換えしません。再応答も違反する場合はAS ISで採用して品質警告へ数えます。

歌詞annotationは全modeでEMDへ残ります。mode変更は機械的なlip-sync directiveだけを変えるため、成功cacheがあれば人物動作とカメラを再生成しません。

必要なslotが欠落した場合、まず同じSceneの欠落slotだけを一度再要求します。それでも複数recordの一部が欠ける場合は、残ったslotを一件ずつ隔離して再要求します。隔離要求では対応先が一意なので、正規のwrapperを省略した単一の非空行もTEXTを変更せずside tableへ対応付けます。隔離後も欠落する時だけ不完全EMDをCompilerへ流さずExecutionBlockerで停止します。`save_debug_output=true`は問題調査時だけ使い、通常は無効にします。

LLMが本文を生成できていて行wrapperだけを壊した場合、全task共通のprotocol adapterを使います。まず正規の`TYPE<TAB>SLOT<TAB>TEXT`を厳密parseし、次にslot番号が明示された番号付き行を復元します。複数の未解決slotに対して非空物理行数が完全一致する場合だけ、request side tableの順序で行を割り当てます。除去するのはrecord type、slot、Markdown bullet等のwrapperだけで、`TEXT`は一文字も生成・要約・翻訳しません。単一の無番号行、余分な説明行又は行数不一致は推測しません。正常完了statusの`protocol_recovered=N`は、この機械復元で採用したrecord数です。
