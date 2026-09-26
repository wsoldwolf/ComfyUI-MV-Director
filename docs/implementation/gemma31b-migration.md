# Gemma4 31B構成への移行

現行devはGemma4 31Bを既定とし、VRAM 8 GB対応と旧Planner経路を配布対象から外しました。新しい版番号・releaseタグの作成はこの整理に含みません。

## 変わる点

- PlannerはすべてのprofileでScene Author（Event → Performance → Camera）を使います。旧Cue、Song Direction、Shot Layout、Scene Spine、Action Audit、有限Cameraへ戻る経路はありません。
- `performance_mode`、`body_accent_policy`、`choreography_policy`、`planner_policy`、`arc_tilt_policy`、`camera_render_style`、`lyric_cue_mode`、`priority_lyric_cues`、`lyric_interpretation`は廃止しました。独自profileに残っている場合は明示エラーとなります。
- `scenes_per_batch`をnode UIとPython APIから削除しました。Scene AuthorはScene単位で要求し、context回復時だけslotを分割します。
- Planner成功cacheのalgorithm IDと内容schemaを変更しました。旧cacheを読み替えず、新しい入力で再生成します。保存済みEMD・Plan JSONを自動変換する変更ではありません。

## profile

芸術的な共通本文はそのまま保持できます。現行metadataは[profile仕様](../../profiles/README.md)を参照してください。Motionは明示補完、CameraはArc＋Rollや描画方針を指定し、生成strategyを選択しません。

ユーザーの確定Shot指示は保持します。演出候補は任意、モーション補完は明示合成です。旧監査を撤去したことを理由に、作者指示を再生成させません。

## WF

```cmd
python tools/generate_workflows.py --sync-planner-schema
```

前段3WFの廃止widgetだけを取り除きます。配置、色、素材、seed、入力本文、配線を保持します。動画3WFと保存Planは変更しません。外部接続された旧widgetは手動移行を要求します。

モデルruntimeを配布既定値へ更新する場合は`--sync-model-runtime`を別途使用します。全生成は配置を作り直すため、編集済みWFへの更新は限定syncを優先してください。更新後はComfyUIを再起動してWFを開き直してください。

## 検証と研究資産

製品のartifact・protocol・時間・参照・作者所有・補完・cache・WF試験は残します。旧経路専用試験とオフライン研究probeは配布から外しました。証跡は指定済みのプロジェクト外researchへ退避・ハッシュ照合済みです。

CPUでの契約検証は`python -m unittest discover -s tests -q`です。実31B推論とH3の演技・同期の確認は別判定とし、GPU利用を確認してから行います。歴史的なTIPSは現行機能の仕様ではありません。
