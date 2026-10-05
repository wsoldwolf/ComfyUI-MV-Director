# プロジェクトのコード規模

2026-10-05時点のdev、コミット`5372cd0`を基準に、Git管理対象の作業ツリーを集計しました。集計前の作業ツリーに変更はありませんでした。このTIPS自身と一覧への追記は集計に含めません。

通常動作するPython本体は17,397行、テストと開発ツールを含むPython全体は36,465行です。フロントエンドのJavaScriptを加えた本体は17,669行です。リポジトリ内の全テキスト53,840行を、そのままアプリケーションの実装規模と捉えるべきではありません。

## 集計方法と範囲

`git ls-files`にある332ファイルを対象としました。316ファイルがテキスト、残る16ファイルが画像・音声です。モデル、ComfyUI本体、Context Loop、Hybrid Loader、Spectrum等の外部依存、生成動画、キャッシュ、Git履歴、プロジェクト外へ退避したresearchは含めません。

行数はPowerShellの`[IO.File]::ReadAllLines()`で数えた物理行数です。非空行数は空白だけの行も除きますが、コメント、docstring、文字列、テストデータは残します。したがって、実行文だけの厳密なソース行数ではありません。末尾に改行がなくても、その行は1行として数えます。

## 用途別の規模

以下の分類は重複しません。プロファイルとWFのREADMEは文書へ、テスト用JSON・EMDはその他テキストへ分けています。

| 区分 | ファイル数 | 物理行数 | 非空行数 |
| --- | ---: | ---: | ---: |
| Python本体：`core/`、`nodes/`、ルートの登録処理 | 116 | 17,397 | 15,822 |
| Pythonテスト：`tests/` | 57 | 10,907 | 9,856 |
| Python開発・検証ツール：`tools/` | 34 | 8,161 | 7,616 |
| JavaScript：`web/` | 2 | 272 | 257 |
| システムプロンプト：`prompts/` | 7 | 236 | 224 |
| プロファイル定義：`profiles/`、READMEを除く | 20 | 121 | 111 |
| 配布・検証WFのJSON：`workflows/` | 10 | 10,850 | 10,850 |
| ツール補助：PowerShellと高速化JSONテンプレート | 4 | 864 | 851 |
| 文書：Markdownと`docs/`のSVG | 50 | 3,725 | 2,639 |
| その他：ライセンス、歌詞、テストデータ、gitignore | 16 | 1,307 | 1,149 |
| **テキスト全体** | **316** | **53,840** | **49,375** |

Python本体の内訳は`core/`が84ファイル・14,211行、`nodes/`が31ファイル・3,175行、ルートの`__init__.py`が1ファイル・11行です。登録されている本プロジェクト固有のComfyUIノードは12種類です。WF内にある外部ノードの数とは異なります。

## 本体の主な責務

| 領域 | Pythonファイル数 | 物理行数 |
| --- | ---: | ---: |
| 歌詞整列・回復：`core/lyrics/` | 10 | 2,617 |
| Scene計画：`core/planner/` | 15 | 1,998 |
| artifact・時刻構造：`core/artifacts/` | 8 | 1,670 |
| 英訳・H3向けコンパイル：`core/compiler/` | 6 | 1,634 |
| 画像解釈：`core/vision/` | 8 | 1,373 |
| Direction合成：`core/direction/` | 5 | 1,264 |
| EMD解析：`core/emd/` | 8 | 1,181 |
| LLMの入出力プロトコル：`core/protocols/` | 4 | 764 |
| 推論backend・予算・cache：`core/inference/` | 6 | 672 |
| 音声処理：`core/audio/` | 3 | 515 |
| H3接続契約：`core/h3_contract/` | 6 | 328 |
| utilities・namespace・core登録処理 | 5 | 195 |
| **core合計** | **84** | **14,211** |

大きい本体ファイルは次のとおりです。行数だけで問題の有無を判定する表ではなく、変更時に確認範囲が広くなる箇所の目安です。

| ファイル | 物理行数 |
| --- | ---: |
| [歌詞整列](../../core/lyrics/alignment.py) | 895 |
| [LLM英訳と回復処理](../../core/compiler/llama_translator.py) | 865 |
| [Timeline Plannerノード](../../nodes/node_timeline_planner/node.py) | 781 |
| [Direction Enhancer](../../core/direction/enhancer.py) | 752 |
| [歌詞整列の回復](../../core/lyrics/recovery.py) | 697 |
| [EMD parser](../../core/emd/parser.py) | 637 |

開発ツールでは[WFジェネレーター](../../tools/generate_workflows.py)が2,297行で、`tools/`のPython全体8,161行の約28%を占めます。WFを直接変更する場合も、ジェネレーターと派生WFの整合性確認が保守作業に含まれます。

## Python以外の規模の読み方

システムプロンプト7ファイルは236行・33,049 bytes、プロファイル定義20ファイルは121行・32,945 bytesです。長い日本語の指示を1行に置く形式なので、行数が少なくても推論への影響が小さいとは限りません。これらの値はtoken数ではありません。Python内部に埋め込まれた指示文はPythonの行数に、WF内のユーザー入力はWFの行数に含まれ、上記2区分へ重複計上していません。

プロファイル定義はCameraが6ファイル・27行、Motionが8ファイル・61行、Styleが6ファイル・33行です。`profiles/README.md`の72行は文書区分に含めました。

WFの10,850行は書式に強く依存します。01・02とモデル別01の4派生版は各1行のJSONですが、03〜06は整形済みJSONです。同じ内容を整形するだけで行数が大きく変わるため、WFは次の構造量も併せて見ます。

| WF | ノード数 | 接続数 |
| --- | ---: | ---: |
| 01 Context LoopのPlan生成 | 25 | 22 |
| 02 Context Loopの動画生成 | 49 | 73 |
| 03 Audio ReferenceのPlan生成 | 25 | 22 |
| 04 Audio Referenceの動画生成 | 51 | 77 |
| 05 歌詞方式のPlan生成 | 25 | 22 |
| 06 歌詞方式の動画生成 | 48 | 69 |
| モデル別01の4派生版：各ファイル | 25 | 22 |

上表はJSONの`nodes`配列と`links`配列の要素数です。バイパス・無効化されたノードも含み、実行されるノード数や推論回数ではありません。派生WFの複製も、新しい独立機能の実装量とは区別します。

## 保守負荷についての考察

規模から見ると、小さな補助ノード数個ではなく、歌詞整列、画像解釈、演出計画、EMD、英訳、音声・動画接続を持つ複数サブシステムのプロジェクトです。これは集計に基づく見立てであり、行数だけで品質・複雑度・必要人数を判定したものではありません。

テストPythonは本体Pythonの約63%に相当します。ただし、テスト行数や57ファイルという数はcoverageやテストケース数を示しません。fixture、mock、パラメータ化も含むためです。同様に、開発ツール8,161行の全てが通常WFで実行されるわけではありません。

本プロジェクトでは、Pythonだけでなく、システムプロンプト、プロファイル、作者の演出候補、WFの配線、外部モデル・ノードの版が映像結果を左右します。保守の単位は単純な行数ではなく、変更した責務とその前後の契約です。LLM出力とH3映像はCPUの契約テストだけで評価しきれないため、短区間の映像確認と人による判定を別途残す必要があります。

この集計は削除・統合すべきコードを特定する監査ではありません。削減を検討する場合は、行数の大きいファイルを一律に削るのではなく、通常経路、検証用ツール、重複した派生WF、維持すべき回復処理を分けて判断します。

## 再集計する方法

PowerShellでリポジトリのルートから次を実行すると、Python本体・テスト・ツールの物理行数を再確認できます。空行とコメントを含む数え方です。

```powershell
$taskRows = foreach ($taskPath in (git ls-files '*.py')) {
    $taskGroup = if ($taskPath.StartsWith('tests/')) { 'tests' }
                 elseif ($taskPath.StartsWith('tools/')) { 'tools' }
                 else { 'runtime' }
    [pscustomobject]@{
        Group = $taskGroup
        Lines = [IO.File]::ReadAllLines((Join-Path (Get-Location).Path $taskPath)).Length
    }
}
$taskRows | Group-Object Group | ForEach-Object {
    [pscustomobject]@{
        Group = $_.Name
        Files = $_.Count
        Lines = ($_.Group | Measure-Object Lines -Sum).Sum
    }
}
```

将来の再集計では、対象commit、未コミット変更の有無、集計日、除外対象、JSONの整形状態を併記してください。過去の研究ファイル込みの差分行数とは、今回の集計範囲が異なります。
