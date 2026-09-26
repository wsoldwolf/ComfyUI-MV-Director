# 開発引継ぎ

更新日: 2026-09-27。現行devはGemma4 31Bを既定とし、VRAM 8 GBは対象外です。

## 現在の構成

Vision、Direction Enhancer、Timeline Planner、CompilerをGemma4 31B Q4_K_Sへ統一します。Visionは対応mmprojを併用します。モデル・基準commit・導入コマンドは[installation](installation.md)を参照してください。

PlannerはScene Author（Event → Performance → Camera）に一本化しました。旧小規模モデル向けのCue／Action監査／有限Camera／strategy selectorは撤去済みです。演出シスプロの本文はこの整理で最適化し直していません。

作者の確定Shot項目は保持し、演出候補は任意、モーション補完は明示合成として区別します。詳細は[Planner](nodes/timeline-planner.md)、[EMD](spec/emd-spec.md)、[profile](../profiles/README.md)を参照してください。

## 再現と配布WF

```cmd
python -m unittest discover -s tests -q
python tools/generate_workflows.py --sync-planner-schema
python tools/generate_runtime_flow_diagram.py
```

WF migrationは利用者の配置・色・素材・seed・保存Planを保持します。通常の全生成は新規配置を作るため、編集済みWFへ無条件に実行しないでください。SVGを変えた場合はPNGも再描画します。

必須protocol・音声整列・contextの不成立を空の成功出力へ変換しません。CPUで通信が通ることと映像の演技・同期が成立することは別に判断します。

## 研究記録

レポートと実験資産の出力先はプロジェクト外の `E:\ComfyUI\projects\ComfyUI-MV-Director-research` です。P0–P3の比較・退避manifestもここにあります。配布repositoryには研究用スクリプト・fixturesを含めません。TIPSにある旧8B実験は歴史的な知見であり、現行経路の利用説明ではありません。

P3は配布物／仕様整理とCPU検証です。P4の実31B推論と必要な短区間H3比較は別判定として行います。GPU使用前に利用者へ通知し、使用許可を確認します。
