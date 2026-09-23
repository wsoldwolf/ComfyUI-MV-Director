# Timeline Planner

## 次期Scene author経路（オプトイン）

Motion profile [anime_scene_author_mv](../../profiles/motion/anime_scene_author_mv.md)を
選ぶと、従来のVisual Beat→Layout→Action Audit経路とは別に、一Sceneの
出来事→人物の演技→Cameraの三段で生成します。元TemplateのShot境界と
継続指定を保持し、人物の最終演技文を撮影担当にそのまま渡します。作者が
`演出`、`演技`、`カメラ`をShotへ書いた場合はその項目を生成しません。
未指定の項目だけを補います。`# 演出候補`は出来事担当だけに渡す任意の着想で、
共通H3 promptや後段の担当には配布しません。

完成済み`# サブジェクト`全文を`template_emd`へ入力すれば、Plannerは構文検証後に
モデル選択・推論を省略してそのまま返します。入力不正は自動修復しません。
この経路のCPU契約試験は通過しています。8B短区間は形式上完成したものの、
身体演技と歌詞対象の発現時刻は[第一次判定](../research/scene-author-pilot-2026-09-23.md)で
不合格であり、H3比較は未実施です。
従来profileの挙動は変更しません。実装順と未検証項目は
[実行計画](../implementation/scene-choreography-execution-2026-09-23.md)に記録しています。

現行Planner v80は、歌詞Cue発見の後、Directionに保持された`# 演出候補`からScene単位で出来事候補を選び、必要なら別の身体候補も選びます。Visual Beat、Song Direction、Shot Layoutの後、有効Cueを持つ`dance_phrase` SceneではScene spineがShot間の一回の出来事を計画します。外部現象を扱う場合は単一Shotも対象となり、人物の終端姿勢とは別に現象の`EFFECT_TO`を継続Sceneへ渡します。Actionの身体accentと現象の動きは、Cameraの`lyric_target_and_body` coverageで同時に可視化できます。開発用`anime_emotional_mv`では長尺・単一ShotのPRE-CHORUSにも選択的に一回の身体accentを割り当てます。いずれも歌詞や候補の意味をPythonが補作する機能ではなく、実際のH3映像での成立は別途確認が必要です。

以下のv48～v60等の記述は導入時の経緯と、その後も残る個別契約を説明します。最新の全体順序と責務は[Direction / Planner処理フロー](../architecture/direction-planner-flow.md)を参照してください。

v60ではMotionの`performance_mode=dance_phrase`に演技phase・前Cue終端の受け渡しと4秒以上の
内部境界候補を追加しました。emotionalの有限Cameraでは前終端から画角・視点を接続します。
有限値の構造処理は、下記の自由文Cameraに関するAS IS説明とは区別してください。
Motion/Cameraの計画本文とEMD描画文は任意`render_prompt`で分離できます。
[profile仕様](../../profiles/README.md)と[実装・検証結果](../research/planner-v60-scope-phrase-camera-validation-2026-09-20.md)を参照してください。

Planner v60は、v54で導入した`anime_emotional_mv`の歌詞Cue Discoveryを引き継ぎます。プロファイル内の
`lyric_interpretation=bounded`と`lyric_cue_mode=automatic`で歌詞行Discoveryを
有効にします。同じ原文行は一回だけ、16行ずつ最大768出力tokenで具体対象候補を
抽出します。Scene内の原文順で最後の非body候補を選び、対象・根拠をVisual Beatへ
結び付けます。候補と選択はINFOへ出ます。新しいUI・EMD項目・Vision実行はありません。
詳しくは[Direction / Planner処理フロー](../architecture/direction-planner-flow.md)、[プロファイル設定](../../profiles/README.md)と
[実装・実8B検証](../research/planner-v54-lyric-cue-discovery-2026-09-20.md)を参照してください。

boundedでは以前のBeat/Action自然文履歴を生成requestへ再掲せず、監査と反復検査に
保持します。現在の修復候補・違反理由とDirectionの明示制約は残します。
Motionの`performance_mode=dance_phrase`では既存Action段階のpromptを短い振付向け版へ
切り替えます。Cue Cardの`身体主導`と`終端`から、支持・重心・体幹・腕・表情が
つながるScene内の演技を作ります。Cameraだけのemotional選択では有効になりません。
生成段階や出力項目は増やさず、監査最大二回・修復一回の上限も増やしません。
他のMotionは通常Action promptのままです。適用modeはINFOで確認できます。
以下の一般的な履歴説明は、このbounded例外を除く通常経路についての説明です。

Lyric Segmentationが確定したScene/Shot枠へ、歌詞解釈、人物動作、カメラ、リップシンクdirectiveを展開して完成EMDを作ります。人物動作とカメラは別のLLMタスクで生成し、Pythonが同じShotへ合成します。

長尺曲でも全Sceneを一度にLLMへ渡しません。視覚beat、Shot layout、人物動作及びカメラは`scenes_per_batch`件ずつ処理し、各Sceneへ直前Sceneの歌詞と視覚beatだけを境界文脈として添えます。これにより曲長に比例して一回のcontextが増え続けることを防ぎます。反復回避用には直近12 SceneのVisual Beat、直近18 ShotのAction及び直近12 ShotのCameraだけを生成requestへ渡します。一方、生成後の完全一致・高類似度検査はその段階の全採用履歴に対して行うため、数Scene離れて再出現した定型動作も該当slotだけのLLM再要求へ送ります。

## 主な入力

| 入力 | 既定 | 説明 |
|---|---|---|
| `template_emd` | 必須 | Lyric Segmentationの出力 |
| `concept_emd` | 任意 | Subject等の概念EMD。Picture参照なしでもよい |
| `scene_emd` | 任意 | scene-only Visionの`# シーン設定`。完成EMDへAS ISで構造統合する |
| `direction` | 任意 | Direction Enhancerのtyped出力 |
| `lip_sync_mode` | `lyrics` | `off` / `context_loop` / `audio_reference` / `lyrics` |
| `lip_sync_target` | `サブジェクト1` | リップシンク対象。`サブジェクト1..4` |
| `lip_sync_audio_slot` | `1` | Audio参照時の1～3 |
| `model_name` | 自動列挙 | Text GGUF。8B級推奨 |
| `model_name_override` | 空 | 外部STRINGでmodel選択を上書き |
| `scenes_per_batch` | `3` | 一回に計画するScene数 |
| `cache_mode` | `reuse` | 成功結果の再利用方針 |
| `save_debug_output` | `false` | 一時ディレクトリへLLM traceを保存 |

ユーザーのScene演出候補は新しいPlanner入力ソケットではなく、Direction Enhancerの`user_request`に`# 演出候補`と箇条書きで記述します。Plannerは現在Sceneの原歌詞を見て、まず出来事候補一件又は不採用をLLMで選びます。対象と配置を伴う候補はVisual Beatへ渡し、LLMが記した空間関係をCue Cardの`配置`に保持して接触Shotにも同じ配置を要求します。この場合、別の身体演技候補一件を追加でLLM選択し、Scene SpineとActionへ着想として渡せます。選択は追加の小さな推論一段を要し、形式違反時は一度再要求した後、なお無効なら身体候補のみを不採用にします。空間関係が欠落すれば一回再要求し、なお欠落すれば不完全なEMDを出しません。具体的な出来事の候補は一度使った後のScene選択肢から外し、身体演技だけの候補は再選択可能です。Pythonは候補の意味選択や自然文の書換えを行いません。候補行そのものは完成EMDへ残りません。

対象付き候補のanchorは、候補本文と現在Sceneの歌詞の両方に同じ対象名がある場合だけ採用します。身体演技だけの候補はVisual Beatの空間配置へ渡さず、Scene SpineとActionの演技候補へ渡します。bounded profileのVisual Beatは九fieldを維持したまま、`配置=対象位置:...；人物位置:...`として対象の支持面と人物の足場を分けます。選択済みanchorは`対象位置`側へ完全一致で残し、人物位置はLLMが現在のSceneに合わせて記します。Pythonは自然文を修復せず、構造と対象の出典だけを検証します。

既定の`max_tokens=4096`、`temperature=0.1`、`n_ctx=16384`等は[GGUF共通設定](gguf-settings.md)を参照してください。

人物振付のScene一括実験はMotion profile `anime_scene_phrase_mv`を選んだ時だけ有効です。対象のないSceneでは専用の短いScene Spine promptで一度の身体転換点を作り、CameraはそのShotを全身画角で撮ります。対象への接触・外部effectは別の出来事として残し、生成済みAction本文をPythonで書き換えません。現時点の8B短区間試験ではScene Spine単独の改善は見られましたが、完成EMDのActionでは維持できていないため、既定`anime_emotional_mv`からの切替を推奨する段階ではありません。検証記録は[Scene身体フレーズP0–P3](../research/scene-phrase-p0-p3-2026-09-23.md)を参照してください。

## コンテキスト超過時の自動調整

初回生成、品質修復、欠落slot再要求及び単独slot再要求の全てで、推論前に予算を確認します。
小さな超過では安全余白を維持して、その呼出しの`max_tokens`だけを調整します。
例えば入力13563・要求出力1536・安全余白1311・context 16384なら、実出力上限は1510です。
設定値自体は変更しません。調整結果は`context output fitted`としてINFOへ出ます。

出力枠を十分に残せない場合は`context request split`を記録し、要求をslot順に二分します。
元のslot番号を保持するため、欠番を含む再要求でも別Shotへ誤って割り当てません。
単独slotでも収まらない場合は、任意の過去出力履歴から古い半分を順に除いて再計測し、
`context history reduced`へ削減数を出します。Direction、現在歌詞、採用済みAction、
違反理由、必須fragment及びArc方向の引継ぎは保持します。
分割時は呼出し数が増える場合がありますが、完了済みのSceneや推論はやり直しません。

必須内容だけでも収まらない場合は、task・retry種別・slot番号を含むエラーで停止します。
この場合はprofileや入力文を短くするか、利用環境に合わせて`n_ctx`を増やしてください。
v58適用にはComfyUIを再起動し、Planner以降を再生成します。

## 出力

v55以降は、LLM生成Action/Cameraの末尾に空白で区切られた単独の`\`がある場合だけ、
不要なMarkdown行継続記号として直前の空白と一緒に除去し、INFOへ記録します。
監査へ渡す前と、古い生成内容をEMDへ再描画する境界で適用します。
本文中の記号、パス、台詞、二重のバックスラッシュ、作者本文とDirectionは変更しません。
これはユーザー指定による狭い書式正規化であり、演技内容の生成・言い換えは行いません。

| 出力 | 用途 |
|---|---|
| `emd_text` | 編集可能な完成EMD。Compilerへ接続する |
| `emd` | 内部typed EMD artifact |
| `status` | Scene/Shot数、cut/continuation数、issue、retry、fallback、cache等 |

## 計画方針

### 自動歌詞Cue

Camera profileはUIを増やさず`lyric_cue_mode` metadataを持てます。
`automatic`ではVisual Beatが現在Sceneの歌詞又は作者本文から、物理的に
表示できる最も具体的な名詞句又は独立effectを一つ選び、Visual Beat、Action
及びAction Auditへ渡します。`御神木`のような複合語は`木`へ短縮しません。
scene EMD、Direction及び履歴にだけ存在する語は対象にできません。

`anime_emotional_mv`は`automatic`を既定とし、苔、花、狐火等の固定辞書を
持ちません。Cue Cardが選んだ原文中の正確な対象と、その配置・可視展開を
Action保持検査へ渡します。各Shotへ`establish`、`relation`、
`reaction`、`release`又はその複合位相を割り当て、対象の確立、人物との関係、
感情反応及び解放を一Scene内へ分配します。全Shotへ同じ対象名や接触を反復せず、
後続Sceneで新しい歌詞triggerがなければ再利用しません。

- `object`: Scene内の位置と人物との関係を確立する。
- `symbolic_motif`: 可視の時間変化と人物反応を作り、保持物にしない。
- `external_effect`: 自律的に現れるか人物の手元を起点とし、対象自身が空間を移動する。人物の手振りだけで代用しない。

Cue CardとAction groundingのINFOログから、Sceneごとに選ばれた対象、配置、
可視展開及び割当slotを追跡できます。Action Auditの
`MISSING_GROUNDED_CUE`は対象欠落やScene位相欠落を対象にします。

Planner v47では優先Cueの実tokenを全Stage共通contractへ入れません。優先Cueを
持つSceneだけをVisual Beat及びAction/Auditの単独requestとして処理し、その
Visual BeatとAction本文を後続Sceneのrecent historyへ積みません。profile設定
tokenが現在Sceneの許可Cueに無いActionへ出た場合は
`unexpected_priority_cue`として該当slotだけを再要求します。この再要求では
不採用本文をpromptへ再掲せず、禁止対象そのものを小型LLMが模倣する経路を
閉じます。Pythonはprofile metadata由来の有限token scopeだけを検証し、採用
Action本文を変更しません。

`anime_emotional_mv`の通常Cameraは自由文ではなく、Motion Type、開始/終了scale、開始/終了view、path及びcoverageからなる有限fieldを返します。Pythonは選択値を対象語や人物動作を追加しない固定H3 Camera文へ直列化します。短尺Arc、未割当Arc、Motion/PATH矛盾、顔Zoomの目・眉・鼻・口可視範囲及び顔Arc handoffを構造検証し、不正slotだけを一度再要求します。再応答も不正なら、同じslot roleとShot尺から決定論的fallbackを選びます。他profileは従来のCamera自由文を維持します。 同一の七field Camera計画は同一batch及び直近12 Shotで一回だけ許し、重複時は該当slotだけを再要求します。fallbackもScene番号とShot番号から複数のArc方向、開始・終了scale及びviewを選び、直近と同じ固定軌道を避けます。

`anime_emotional_mv`のVisual Beatは`感情｜根拠｜対象｜接触｜現象｜身体主導｜終端`の固定Cue Cardを使います。`根拠`は現在Sceneの歌詞又は作者本文からの完全一致引用、`対象`はその引用内の語だけです。無効なCue Cardは後段の対象・接触・effect sourceから隔離され、WARNINGへSceneと理由が出ます。 Cue Card検証時は有効数、無効数及び有効な対象をINFOへ出し、実行結果から苔、狐火等の歌詞triggerがどこで失われたか追跡できます。scene EMDはVisual Beatだけへ空間supportとして渡し、歌詞で既に認可された対象を大樹の根元、参道脇又は奥行き層等へ配置するために使います。scene EMD単独では対象、接触又はeffectを活性化できません。ActionとCameraへscene EMD本文を渡さず、背景Picture及びEnvironment inventoryは最終EMDへ独立合成します。

Planner v48では上記七field Cue Cardを
`感情｜根拠｜対象｜接触｜現象｜配置｜可視展開｜身体主導｜終端`の九fieldへ
置換します。`配置`はscene EMDから選んだ対象の具体的な空間anchor、
`可視展開`は対象自身の材質状態、時間変化、空間軌道又は環境への可視結果です。
対象がある時は両fieldを必須とし、対象がない時は両方を`なし`にします。
Action Auditは裸の対象名への縮退、身体テンプレートの左右差だけの反復及び
`ACTION 14`等の内部protocol labelを再生成対象にします。採用Action本文はAS ISです。

Planner v49では、`anime_emotional_mv`のprofile優先Cueに限り、Cue Cardで生成済み
の`配置`と`可視展開`を別々のAction slotへ完全一致で引き継ぎます。一つの
ActionしかないSceneでは両方を同じslotへ引き継ぎます。このため
`苔 + 汎用ポーズ`のように単語だけを置いた候補は合格せず、Visual Beatが定めた
大樹の根元等の位置と、対象自身の状態・軌道・環境結果がActionへ残ります。
再試行後も欠落する場合は曖昧なEMDを出さず`ACTION_GROUNDING`で停止します。
本文へ混入した裸のslot番号、`TAB`、`タブ`及び内部record labelも
`ACTION_PROTOCOL`で停止します。Pythonは採用Action文を合成・修正しません。

Planner v50ではこの完全一致転送を`lyric_cue_mode=automatic`で検証済みの
すべてのCue Card対象へ一般化します。対象選択は既存Visual Beat推論内で行うため
追加のLLM呼び出しはありません。原文中の最も具体的な可視名詞句を選び、
`御神木`等の複合語、`配置`及び`可視展開`をActionへ完全一致で転送します。
`priority_lyric_cues`は独自profileの回帰固定用overrideとしてだけ残ります。

Plannerは現在Sceneの元歌詞又は作者指示だけから具体物、場所、感情又は外部effectをvisual beatへ活性化します。scene EMD、共通Direction及び過去Sceneは存在と配置の拘束でありAction sourceではありません。単なる歩行、正面立ち、両手を広げる、手を上げる、前を見る又は背景物へ触る動作を既定にしません。対象名だけでは接触を許可せず、歌詞に物理的な操作意味が無い場合は、まぶた、視線、頭、肩、胴体、骨盤、腕、手、支持脚、遊脚、重心及び身体レベルを連動した非接触の全身演技へ変換します。外部effectは既定で人物から独立して空間内を移動し、人物は視線、姿勢、回避又は一回の感情反応だけを返します。一つの歌詞triggerで使った対象は原則として一Sceneで消費し、後続Sceneでの再利用には新しい歌詞triggerを必要とします。 `anime_emotional_mv`では有効Cue Cardが具体対象を持つSceneについて、全Shotへ対象を反復させず、役割上最も適した一Shot以上がその完全一致対象名と認可済みの空間関係又は自律現象を含むことを検査します。欠落時は`missing_grounded_cue_target`としてそのslotだけを再要求します。

各Shotには自然文と別に`performance_role`を付けます。複数ShotのSceneでは、顔と上半身のaccent、腕・手が主役の演技、環境との相互作用又は振り返り、異なる終端silhouetteへ役割を分散します。Scene-level visual beatが移動であっても、全Shotを同じ歩行cycleへせず、歩行は必要なShotの接続動作に限定します。 「手を上げる／下げる」の後ろへ頭、肩、胸郭又は左右非対称silhouetteを付加しただけの複合文も単純な手の上下として検出します。`face_and_upper_body_accent`はまぶた、視線、眉、口又は表情変化を必須とし、手、頭の向き又は胸郭だけの候補を`face_performance_missing`として再要求します。Cameraにも`editorial_role`を付けます。ただし、リップシンク有効かつ歌詞sectionが初登場するCUT Sceneでは、section名を持つ最初の歌詞annotationが実際に属するShotだけを有限個の構造的な顔インサートとし、ActionとCameraをLLM要求から外してRenderer所有の固定文を割り当てます。Scene開始と歌詞開始が異なる場合も、無音のScene先頭へ顔歌唱を置きません。Actionは歩行や全身移動を禁止して両目、眉及び完全な口による歌唱演技だけを要求します。Cameraは`Zoom In with large amplitude at fast speed`で正面又は斜め正面の頭肩構図から極端な顔close-upへ進み、両目、両眉、鼻、完全な歌唱口及び顔輪郭を全行程で同時に表示します。EMDではこのRenderer所有文を日本語で表示し、Compilerが翻訳LLMを介さず正規のH3英語文へ決定的に置換します。それ以外のAction及びCameraは、合格したLLMのTEXTをAS ISで使います。これによりEMDの可読性を保ちながら固定phraseの翻訳揺れ、通常Shotへの漏洩及び顔Cameraへの歩行Action競合を防ぎます。

固定顔インサートのActionは、Subjectで既に記述された眉の個数、compactness、形、配置及び色を顔演技中も維持します。特殊な眉markを通常の長い線状、湾曲又は弓状の眉へ置換しません。この契約は丸眉だけの固有例外ではなく、点、楕円又は豆形等の局所的な識別形状を表情演技で通常形へ正規化しないための共通契約です。

固定顔インサートには、同一Scene内の隣接する通常Shot一個を構造的に対応付けます。顔インサートがScene先頭なら次Shotを`arc_out_of_previous_face_cut`として顔のスケールから30～60度のArc半径を広げ、上半身、全身又は環境を開示します。顔インサートが後方なら直前Shotを`arc_into_next_face_cut`として身体・環境coverageから顔へArcで入り、次の固定顔アップへ接続します。このCamera slotが`Arc Shot`以外を返した場合、本文をPythonで変更せず該当slotだけを一度品質再要求します。

Visual Beats及びActionsへはSubjectの`concept_id`と`<Subject N>`だけからなる構造的rosterを渡し、Concept EMDの詳細な外見、身体構造、衣装構造、履物、色、材質及び参照保持文は創作sourceとして渡しません。Concept EMD本文は最終EMDへAS ISで保持され、Compiler/H3のSubject定義としてだけ機能します。これにより破綻防止用の局所detailが全Sceneの動作や撮影主題へ昇格することを防ぎます。Visual Beats及びActionsへはDirectionのStyle、Time/Lighting、Motion、Otherだけを渡し、Environment inventoryとCamera profileを除外します。Visual Beatだけは別経路のscene contextを位置情報として受け取ります。これにより`Arc Shot`等の撮影語や背景に存在するだけの固定物が人物動作へ混入することを防ぎます。各段階へ渡されたDirectionは生成済みvisual beat、履歴及びLLMの演出補完より上位です。採用した行をPythonの単語表や正規表現で書き換えず、最終`ACTION`及び`CAMERA`本文をAS ISでEMDへ渡します。

Visual Beat、Action又はCameraの長い出力が、同一batch若しくは直近履歴と完全一致又は高い表層類似度を持つ場合、Pythonは文章を変更せず、そのslotだけを該当Scene単位で最大二回再生成します。再要求には元の`rejected_output`、衝突した`must_differ_from`及び直近と同一batchの採用候補をまとめた`forbidden_recent_outputs`を渡し、主動詞、対象、可視結果、終端silhouette又はCamera目的を実質的に変えるようLLMへ要求します。左右交換、同義語又は語順変更だけでは修復とみなしません。通常profileでは、二回の再試行後も残る類似を`repetition_warnings=total(beat=B,action=A,camera=C)`へ記録してAS ISで採用できます。`anime_emotional_mv`のActionとCameraもbounded retry後は最小違反のLLM候補をAS IS採用し、理由をログへ残します。

`anime_emotional_mv`のAction生成後には、同じLLMを生成役とは別の`action-audit`分類taskとして呼び出します。監査は各candidate Actionを現在歌詞、作者本文、Direction、visual beat、role、同一batch及び直近履歴と照合し、`PASS`又は`SEMANTIC_REPETITION`、`PROFILE_CONFLICT`、`INCIDENTAL_FIXTURE`、`UNREQUESTED_LOWER_BODY`、`UNREQUESTED_CONTACT`、`REFERENCE_POSE`の有限理由codeだけを返します。相互反復では先行する妥当slotをPASSとし、後方の重複だけをrejectします。Pythonは意味を判定せず、監査reject、構造品質違反及び表層反復を同じ有限修復loopへ集約し、該当slotだけを一回Action LLMへ再要求した後、最終auditを一回行います。初回と最終を合わせてauditは最大二回です。各roundでslotごとの最小違反候補を保持し、予算枯渇、audit protocol欠落又はrepair response欠落時には既存候補を失わず、最良のLLM生成文を一文字も変更せずAS IS採用してWARNINGへ理由を残します。監査は品質改善器であって創作全体の停止ゲートではありません。

UIの固定seedは実行全体の再現性を所有しますが、各LLM呼び出しではtask、call番号及びpayloadから決定的に異なる`call_seed`を派生します。同じ固定seedと同じ入力は同じ結果になりますが、複数batchとdiversity retryが毎回同じ乱数列の先頭を再利用して同じ定型句へ収束することを防ぎます。

`anime_story_mv`では静かな溜めと、明確な加速、重心移動、方向転換、鋭い停止及び大きく異なる終端ポーズを対比させ、均一に緩慢な補間を避けます。二コマ・三コマ打ちは静止hold、表情の溜め及び末端追従へ限定し、主要な身体動作、関節軌道、接地及び重心移動は時間方向に連続させ、pose飛び、瞬間移動、四肢の往復反転及び痙攣状motionを要求しません。通常歩行は遊脚を地面から持ち上げ、前へ運び、踵又は足裏を接地して重心を移し、作者指定なしの摺り足、引き摺り及び滑走を生成しません。Camera行はMiniMax H3の正式名称から必ず開始します。`anime_story_mv`のCamera batchでは適格な通常Shotのおよそ3分の1を構造的な長尺Arcへ指定し、利用可能なShotのうち長いものを優先して60～120度の経路をShot尺の70～90%にわたり連続させます。固定顔インサートは頭肩構図から極端な顔アップへ進む`Zoom In with large amplitude at fast speed`とし、両目、両眉、鼻、完全な歌唱口及び顔輪郭を全行程で残します。固定顔インサートが無いリップシンクbatchでは、長尺Arcと競合しない表情結果又は上半身coverage一件へ同じ顔Zoom契約を追加します。隣接Arcは身体・環境から顔Zoomへ入るか、顔Zoomから上半身・全身・環境へ抜けるため、Arcと顔拡大が一連のCamera展開になります。別の移動Shotは`Tracking Shot`で追従します。Pythonは通常Camera自然文を書き換えず、LLMへ構造契約を渡して採用行をAS ISで使用します。従来の穏やかで映画的な動作・カメラ設計は`cinema_mv`として選択できます。

`anime_emotional_mv`は27Bプロトタイプで有効だった一体的な演技とCamera展開を、現行の分割Plannerへ構造契約として移します。Visual Beatは`感情｜根拠｜対象｜接触｜現象｜身体主導｜終端`のScene Cue Cardを作り、歩行は意味のある二状態をつなぐ補助動作に限定します。現在Sceneの元歌詞又は作者指示だけが具体物、場所要素又は外部effectをAction対象として活性化します。scene EMD、共通Direction及び過去Sceneは存在と配置の拘束でありAction sourceではありません。歌詞に見える名詞又は外部effectが動詞なしで現れた場合も無視せず、そのScene内で対象固有の状態、動き、変化、空間関係又は人物の非接触反応へ変換します。対象名だけでは接触を許可せず、現在歌詞に物理的な操作意味が無い時は、まぶた、視線、頭、肩、胴体、骨盤、腕、手、支持脚、遊脚、重心及び身体レベルを連動した誇張された非接触の全身演技を使います。一つの歌詞triggerで使った対象は原則として一Sceneで消費し、後続Sceneでの再利用には新しい歌詞triggerを必要とします。 `anime_emotional_mv`では有効Cue Cardが具体対象を持つSceneについて、全Shotへ対象を反復させず、役割上最も適した一Shot以上がその完全一致対象名と認可済みの空間関係又は自律現象を含むことを検査します。欠落時は`missing_grounded_cue_target`としてそのslotだけを再要求します。外部effectは既定で人物から独立して空間内を移動し、歌詞が操作を明示しない限り人物に保持又は誘導させません。Song Directionは感情曲線、section energy、静止と加速及び編集連続性だけを所有し、具体物又は接触を認可しません。ActionへはCamera profileとSong Directionを渡さず、CameraへはMotion profileとSong Directionを渡しません。Cameraでは2.5秒以上の適格な非顔slotのおよそ半数を長尺Arc候補とし、未割当slotではArcを禁止します。長尺Arcは`Arc Shot with large amplitude at fast speed`、60～120度、Shot尺の70～90%を品質契約として再試行します。顔Zoomは曲全体の疎な予算と既存section face cutから選び、35～55%で顔へ到達して短い表情accentだけを保持します。同一Scene内で可能ならArcから顔へ入る又は顔からArcで抜ける関係を与えます。後続Sceneの少なくとも4分の3をCONTINUE可能にし、すべてCONTINUEの計画も許します。通常profileの同一mode最大3連続及びCUT最小比率は、このpolicyへ適用しません。

`anime_emotional_mv`の構造的な顔インサートはActionを固定文にせず、現在歌詞、直近Action履歴及び`face_and_upper_body_accent` roleを持つ通常ACTION要求としてLLMへ渡します。閉眼、半開き、伏し目、細め又は再開眼を含む歌詞固有の顔演技をAS ISで採用します。Cameraだけは専用の短い固定文を使い、35～55%で読み取れる顔scaleへ到達して短い表情accentだけを保持します。他profileの固定顔Action及びCameraは変更しません。

この最適化はCamera profile EMDの`planner_policy` metadataから選ばれ、別のUI入力又はprofile IDのPython直書きでは切り替えません。Pythonが所有するのはslot役割、境界比率、Arc/顔Zoomの必要数及び遷移関係だけです。LLMが返したActionとCameraの自然文は従来通りAS ISでEMDへ渡します。

歌詞又は作者が走行を明示しない限り、走る、駆ける、疾走する又は逃げるActionを生成しません。特に間奏では走行をMVの勢いの代用にせず、胴体の旋回、振り返り、高低差、腕の演技、環境相互作用、鋭い停止、異なる終端pose及び独立したCamera運動で強度を作ります。未指定の走行がActionへ出た場合は本文を書き換えず、そのslotだけを品質再要求します。

Shot layoutは通常一Sceneあたり2～3 Shotを選び、4 Shotは8秒以上かつ4つの異なる視覚目的を各2秒以上確保できる場合だけに限定します。Cameraはlocked Actionに必要な身体部位と接触対象を画面内に残し、全身動作へ極端な顔cropを組み合わせません。MiniMax H3 Motion Typeと後続説明の物理動作も一致させ、`Static Shot`で接近する、`Tilt Down`で上昇する、`Pan`で平行移動する等の矛盾を禁止します。

`anime_story_mv`の髪、体毛、動物耳、耳内部、尾、皮膚及び衣装は非発光素材として扱います。作者が発光を明示しない限り、ActionとCameraはこれらを「輝く」「光る」「glow」等の演技又は撮影目的にせず、月光、逆光及び灯火は通常の反射光へ限定します。耳内部の局所的なglow、bloom、halo、強い透過光及び白飛びも要求しません。この制約はPlanner出力を後段で書き換えるfilterではなく、固定Styleと各LLM taskの生成条件です。

Scene境界ごとに`CUT`又は`CONTINUE`も選びます。新しい画角、detail、逆方向又は場所を編集点で提示する時は完成EMDのScene見出しから`継続`を外し、直前の画像状態とカメラ経路を引き継ぐ時だけ`継続`を残します。歌詞が記憶、問い、恐れ、孤独、涙、別れ、自己認識又は決意へ移るSceneでは、新しい編集点を選べます。実行可能な範囲で新section初出SceneをCUTとして保持し、極端な顔インサートはそのScene内で新sectionの歌詞を実際に持つ最初のShotへ置きます。通常coverageでは正面又は斜め正面のmedium、medium close-up又はhead-and-shoulders Shotを必要に応じて使い、手、髪、小物、後頭部又は完全な横顔で目や唇を隠しません。局所detailと顔を一つのCamera行へ同時要求せず、歌詞上必要なdetailは別Shotへ分離します。Concept EMDが1 Subjectだけなら、人物動作とカメラへ単独instance policyを渡し、各Camera行で画面内にその人物一体だけを置きます。参照設定画の左右panel、別角度、鏡像又は背景の似た人物を二人目として再現させません。候補数超過、区切り、重複又は未知候補だけのLAYOUT差異は、既知候補の時系列順整列、重複除去及び最大4 Shotへの切り詰めで機械修復します。各Sceneには直前の歌詞とVisual Beatも渡します。通常policyでは4 Scene以上のmode列に後続境界の4分の1以上のCUT、半数以上のCONTINUE、同一mode最大3連続及びmode遷移数上限を要求しますが、`anime_emotional_mv`は後続の4分の3以上をCONTINUEとする専用契約へ置換し、全後続SceneのCONTINUEも許します。契約を満たさない場合は隣接関係を比較する境界mix再計画を一度だけ実行します。再応答も構造契約を満たさない場合は、PythonがCUT/CONTINUE列だけを元の選択から最小変更で修復します。Action、Camera及び候補Shot本文は変更せず、変更したScene番号を`layout_repaired_scenes`へ記録します。実行有無は`layout_mix_retry=yes/no`へ出します。境界mode自体を認識できない場合だけ`CUT,B0`へfallbackします。境界mode変更時はPlannerが`H3長`とPlan上のScene/Shot時刻をH3格子へ再配分します。Scene内の`## ショット`は一回のH3生成内の時刻付きprompt変化であり、hard cutを保証しません。

Action batchにはslow表現上限、単純な手の上下0件及び作者未指定の足元主体0件という構造予算を渡します。違反を検出した場合、PythonはAction本文を変更せず該当slotだけを`action_quality_budget`として一度再要求します。Camera batchは通常`Arc Shot`最大1件、`anime_story_mv`では適格な通常slotのおよそ3分の1、`Tracking Shot`最大1件、その他の同一Motion Type最大2件、slow表現上限及び作者未指定の足元detail 0件という構造予算を持ちます。`anime_emotional_mv`では2.5秒以上の適格な非顔slotのおよそ半数を長尺Arc候補にし、各slotへ`arc_permission=required|forbidden`を渡します。長尺Arcは`Arc Shot with large amplitude at fast speed`で始まり、速度を打ち消す日本語表現を含めません。顔Zoomはbatchごとの下限を持たず、曲全体の予算から既存section face cutを差し引いて追加します。正式Motion Type欠落、未割当Arc、profile固有の`long_arc_emphasis`、顔遷移、顔Zoom又は速度競合を検出した場合は、該当slotだけを`camera_quality_budget`として一度再要求します。PythonはCamera本文を機械生成又は書換えしません。再応答にも違反が残る場合、初回候補と再生成候補から必須Motion Type違反数と全違反数が少ない方を選び、AS IS採用してINFOへ理由を残します。必須Camera slotそのものの欠落又はprotocol回復失敗だけは停止条件です。

歌詞annotationは全modeでEMDへ残ります。mode変更は機械的なlip-sync directiveだけを変えるため、成功cacheがあれば人物動作とカメラを再生成しません。

必要なslotが欠落した場合、まず同じSceneの欠落slotだけを一度再要求します。それでも複数recordの一部が欠ける場合は、残ったslotを一件ずつ隔離して再要求します。隔離要求では対応先が一意なので、正規のwrapperを省略した単一の非空行もTEXTを変更せずside tableへ対応付けます。隔離後も欠落する時だけ不完全EMDをCompilerへ流さずExecutionBlockerで停止します。`save_debug_output=true`は問題調査時だけ使い、通常は無効にします。

LLMが本文を生成できていて行wrapperだけを壊した場合、全task共通のprotocol adapterを使います。まず正規の`TYPE<TAB>SLOT<TAB>TEXT`を厳密parseし、次にslot番号が明示された番号付き行を復元します。複数の未解決slotに対して非空物理行数が完全一致する場合だけ、request side tableの順序で行を割り当てます。除去するのはrecord type、slot、Markdown bullet等のwrapperだけで、`TEXT`は一文字も生成・要約・翻訳しません。単一の無番号行、余分な説明行又は行数不一致は推測しません。正常完了statusの`protocol_recovered=N`は、この機械復元で採用したrecord数です。
