# MV Director 実装仕様

更新日: 2026-09-27<br>
対象: Gemma4 31B、現行Scene Authorのみ

## 1. 目的

本書は機能仕様をPython module、公開関数、例外、依存方向及びテストへ落とす。EMD文法の正本は`docs/spec/emd-spec.md`、artifactと行通信の正本は`docs/spec/protocol-spec.md`とし、本書はそれらの意味を変更しない。

実装は次の順で行う。

1. 文書化したprotocolに対するfixtureを作る。
2. ComfyUIをimportしない`core/`を実装する。
3. Fake backendで純粋関数を検証する。
4. 最後に`nodes/node_*/`の薄いComfyUI wrapperを追加する。
5. Context Loop基準commitとの互換試験を行う。

## 2. Pythonと依存

- Python 3.10以上を対象とする。
- Phase 0とCompiler最小核は標準ライブラリだけで実行できるようにする。
- `core/`からComfyUI、Torch、Whisper又はllama.cppをimportしない。
- 外部runtimeはprotocolで定義した小さいinterfaceの実装として`core/inference/`又はnode wrapperから注入する。
- import時にmodel探索、file書込、GPU初期化又はnetwork accessを行わない。

## 3. package境界

```text
core/
├─ artifacts/       versioned artifactの型、検証、canonical JSON
├─ protocols/       LLM行protocolとVision行protocol
├─ emd/             EMD lexer、parser、AST、renderer
├─ compiler/        Ref2VA変換とPromptTranslator interface
├─ timing/          ms、H3 frame格子、Scene/Shot
├─ audio/           VAD境界とAudio Pad Pairの純粋処理
├─ inference/       GGUF探索、backend interface、lifecycle
└─ h3_contract/     Context Loop versioned adapter
nodes/
└─ node_*/          ComfyUI INPUT_TYPES、RETURN_TYPES、hidden graph adapter
```

依存方向は`nodes -> core`だけとする。`artifacts`と`protocols`は他のcore moduleをimportしない。`emd`は`artifacts`を使用できるが、`compiler`又はnode wrapperをimportしない。

## 4. 公開API

artifactとprotocolの入口は次を使用する。Plannerの入口は`core.planner.plan_timeline`とし、旧engineを公開しない。

```python
from core.artifacts import (
    ArtifactValidationError,
    DirectionArtifact,
    EMDTextArtifact,
    ProvenanceRecord,
    ReferenceBindingsArtifact,
    RequiredReferencesArtifact,
    TimelineArtifact,
    canonical_json,
)
from core.protocols import (
    LLMRecord,
    LLMRecordIssue,
    LLMRecordParseResult,
    parse_llm_records,
)
```

全artifactは`validate()`、`to_dict()`及び`to_json()`を持つ。`from_dict()`はschema IDを厳密に検証し、旧schemaを読み替えない。constructor後の値も`to_dict()`前に再検証する。

## 5. 値の扱い

- ms、frame、index、slotは`bool`を整数として受理しない。
- JSONへNaN、Infinity、tuple、set又は任意objectを出さない。
- 入力文字列の改行はprotocol入口でCRLF/CRをLFへ正規化する。
- 自由本文のtrim、Unicode正規化又は空白変更は、そのprotocolで明記された箇所以外では行わない。
- hashはUTF-8バイト列のSHA-256小文字hexとする。
- artifactのcanonical JSONはUTF-8、`ensure_ascii=False`、key昇順、余分な空白なしとする。

## 6. エラー

`ArtifactValidationError`はschema、field path、理由を持つ。行protocolは一行の破損で要求全体を例外終了せず、`LLMRecordIssue`として回収する。ただし呼出し型、NULを含む応答又はparser設定自体が不正な場合は`ProtocolError`を送出する。

意味品質、映像品質、英訳品質又はH3品質を例外にしない。model load、OOM、cancel及びbackend障害は成功artifactへ変換しない。

## 7. test構成

- `tests/fixtures/protocol/`: raw LLM/Vision応答
- `tests/fixtures/artifacts/`: canonical JSON
- `tests/fixtures/emd/`: valid/invalid EMD
- `tests/test_artifacts.py`: schemaとcanonical JSON
- `tests/test_llm_records.py`: 部分回収、重複、欠落slot

Phase 0は`python -m unittest discover -s tests -v`だけで実行できることを完了条件とする。fixtureのcanonical JSONは改行やkey順の偶然に依存せず、再直列化結果の完全一致を検証する。

## 8. ComfyUI wrapper

wrapperは入力型変換、core呼出し、進捗、中断、表示用status及び出力tupleだけを担当する。parser修復、意味判断、retry policy又は別schema変換をwrapperへ追加しない。

公開node IDは`MVDirector...`、custom socketは`MV_DIRECTOR_...`、表示categoryは`MV Director/...`とする。旧`CL...` aliasを登録しない。

## 9. cacheとdebug

cache keyは入力artifactのcanonical JSON、model識別子、runtime調整値、seed、system prompt版及びalgorithm版から作る。成功結果だけを保存する。

通常statusへ本文又はraw promptを含めない。`save_debug_output=true`の場合だけraw応答、拒否行、side table及びtoken内訳を保存する。provenanceはchain-of-thoughtではなく、protocol上確認できる入力・採用・機械的破棄の履歴だけを持つ。

## 10. 変更手順

現行の配置と更新順序は[部品と変更手順](components-and-order.md)を参照する。
EMDとartifactを暗黙変更しない。旧経路専用テストは撤去し、現行契約のCPU試験と実映像の人間評価を区別する。
