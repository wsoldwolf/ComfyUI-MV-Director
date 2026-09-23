# Scene出来事・身体演技の二責務設計：8Bオフライン検証

2026-09-22

> 後続の[対象・出来事の意味一致検証](scene-target-event-alignment-validation-2026-09-22.md)で解釈を訂正した。「手から狐火が生まれる」はそれ自体が異常ではない。以下の「外部自律」「手からの発生を避ける」という評価は当時の仮契約に対する結果であり、作品上の必須条件ではない。狐火がEVENT.CHANGE内で可視の出来事となるかを判定する。

## 判定

[設計案](scene-event-performance-dual-contract-design-2026-09-22.md)を保存済みScene 11（社）とScene 14（狐火）、seed 42/43で小範囲に試した。**一回のLLM応答にEVENTとBODYを二行で書かせるだけの案は採用しない。** 候補文がEVENT側まで汚染し、4件とも形式検証には通ったが対象・接触先の意味が崩れた。一回の再要求でも安定しない。

候補を伏せてEVENTを先に作り、原文を固定入力としてBODYを別推論する案は、狐火では両seedで外部自律の出来事を保った。二レーンのScene Spineへ渡すと、狐火をShot 1、人物の顔反応をShot 2へ分けられた。ただし社は両seedで対象から足音へ逸れた。監査8Bは既知の異常を見逃し、単純な対象語チェックにも偽陽性がある。**現時点で全曲、既定profile、H3へ昇格させない。** 本番Planner、EMD、Compiler、ワークフローは変更していない。

## 比較条件

同じ[全編保存trace](../assets/research/choreography-full-run-v4-2026-09-22/evidence.json)からScene 11/14の原歌詞・Direction motion・場面情報を取り出し、[モーション候補2件](../assets/research/motion-template-input-probe-2026-09-22/motion_templates.emd.md)を使用した。モデルはQwen3-8B-Abliterated Q4_K_M、`n_ctx=16384`、seed 42/43。生成には行形式だけの有限文法を使用し、自然文の中身をPythonで補作・置換していない。GPUは短いオフライン推論だけに使い、動画生成はしていない。

| 条件 | 概要 | 証跡 |
| --- | --- | --- |
| 一回二行 | 同じLLM呼出しでEVENT/BODYと同期点を生成し、別呼出しで監査 | [応答](../assets/research/scene-event-performance-dual-probe-2026-09-22/evidence.json) |
| 項目別監査 | 対象の作用先、接触点、外部自律性、同期を別々にPASS/FAIL判定 | [監査結果](../assets/research/scene-event-performance-audit-matrix-2026-09-22/evidence.json) |
| 一回再要求 | FAIL理由を返し、EVENT/BODY二行を8Bに再生成させる | [再要求結果](../assets/research/scene-event-performance-repair-2026-09-22/evidence.json) |
| 二段階 | 候補を見せずEVENTを生成し、そのEVENTを固定してBODYのみ別生成 | [応答](../assets/research/scene-event-performance-two-stage-2026-09-22/evidence.json) |
| Shot分配 | 狐火Sceneだけ、EVENT_STEP/BODY_STEPを別にして二Shotを生成 | [初回](../assets/research/scene-event-performance-two-lane-spine-2026-09-22/evidence.json)・[状態主語を明示した再比較](../assets/research/scene-event-performance-two-lane-spine-v2-2026-09-22/evidence.json) |
| 対象語の必要条件 | EVENT.CHANGEにTARGET文字列を要求し、欠落時だけ一回再要求 | [追加試験](../assets/research/scene-event-performance-two-stage-retry-2026-09-22/evidence.json) |

## 観察

### 一回二行と意味監査

EVENT/BODYの二行形式は4/4件で成立した。しかし社の両seedは`TARGET=社`としながら`MODE=contact`、接触先は石畳、出来事は足音だった。狐火の両seedも`MODE=contact`として神社建物を接触先にした。身体側は一件目の候補を長く再掲し、出来事と独自の演技を調停できなかった。生成4件を監査した一語の`OK/REJECT`版はすべて`OK`を返し、意図的に壊した社・狐火の対照例も両方見逃した。

項目別監査は生成4件の接触先不一致をすべて`FAIL`と判定し、一語版より有益だった。一方で、既知の「人物の手から狐火を発生させる」異常例は`EXTERNAL_EFFECT=PASS`と誤判定し、社の`TARGET_ACTION`も誤って`PASS`にした。正常対照2件は通したが、異常対照2件のうち一件は見逃している。**この監査のPASSを本番の安全保証には使えない。**

検出理由を返した一回再要求では、社の2件が二行形式を保ち`contact`を`observe`へ変えたものの、出来事は依然足音中心だった。狐火の2件は`autonomous`へ直す方向を示したが、BODY欄に候補を反復複写して出力上限へ達し、二行契約を完成できなかった。構造検証は社2/2、狐火0/2。出力文をPythonで直して採用することはしていない。

### 候補からEVENTを隔離した二段階

二段階試験のEVENT/BODYは4/4件で形式成立した。狐火2件は`MODE=autonomous`、`CONTACT_POINT=なし`、狐火が自ら空へ舞う／散る出来事となり、人物の手からの発生を避けられた。これは候補をEVENTへ見せない責務分離が、少なくともこの対象で有効だったことを示す。

しかし社2件は`MODE=observe`へ改善しても、EVENT.CHANGEが「足音」又は「足音が石畳を伝う」だけで、社自体の可視描写がない。項目別監査は両件とも全項目`PASS`を返し、見逃した。BODYも候補の荷重・胸郭・手の弧を断片的に採ったが、Scene固有の感情的な身体演技へ十分に変えていない。候補全文のコピーより短くはなったが、プロトタイプに近い振付が成立したとは言えない。二段階の4 Scene試験はEVENT約7.27秒、BODY約9.49秒、項目別監査約1.89秒、計約18.65秒（モデル読込を除く）。一回二行の生成4件約26.49秒よりこの小標本では短かったが、全曲の計算費には外挿できない。

EVENT.CHANGEへTARGETの文字列を含める汎用必要条件も試した。社の欠落に対する一回再要求は一seedでは依然欠落、もう一seedでは「神社へ向かう」にTARGET=`社`の一文字が含まれるため表面上通過したが、実際は足音の文のままだった。**部分文字列検査は単語境界のない日本語で意味一致を保証できない。** この条件を本番の合格判定に使わない。

### 二レーンScene Spine

正しく外部自律になった狐火だけを二Shotへ渡した。初回は両seedでShot 1の`EVENT_STEP=狐火が空に舞い上がる`と`SHOW=lyric_target`、Shot 2の`EVENT_STEP=なし`と`SHOW=face_eyes_mouth`を得たが、`FROM/TO`が「夜空」「狐火」等の環境・対象状態になり人物の姿勢をつながなかった。実験プロンプトで`FROM/TO`の主語を人物に限定して同じseedで再比較すると、両seedで身体状態の継承が成立した。狐火の一回の出現と顔反応も残った。ただしBODY_STEPは低い腕・視線程度で、豊かな振付にはまだ足りない。Action、Camera、EMD、H3への実際の受け渡しは未試験である。

## 次の判断

責務分離には**局所的な効果がある**が、独立EVENT生成も監査もまだ信頼できない。従って次の焦点は候補を増やすことではなく、原歌詞から選んだ対象とEVENT.CHANGEの意味的な一致を測ること。少なくとも社のように「接触も発光も歌詞にない」Scene、狐火のような自律現象、作者が接触を明示したSceneを含む手採点の短い対照集合で、8B監査の見逃しと誤拒否を定量化する。検査器が壊れたEVENTを通す限り、二レーンShotの成功を全体品質の成功と呼ばない。

次に監査を改善する場合も、語彙辞書で自然文を修復しない。LLMの原文をAS ISで保持し、対象と変化の関係を明示する契約、独立監査の信頼性、追加呼出し費を先に検証する。5060での実行可能性、Action/Cameraでの同期、H3での映像品質は未評価。本番系への組込みと既定profile切替えは保留する。

研究用スクリプトと行形式のCPUテストを追加した。リポジトリの`unittest`全467件が通過した。
