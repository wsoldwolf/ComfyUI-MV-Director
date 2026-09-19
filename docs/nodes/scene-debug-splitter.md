# Scene Debug Splitter

長いContext Loop Planから連続する一部のSceneだけを取り出し、同じ時間範囲のvocal stemとfull mixを生成します。全曲を再生成せず、問題のあるScene群だけを動画生成へ渡すためのデバッグ用ノードです。

## 入力

| 入力 | 既定 | 説明 |
|---|---|---|
| `plan_json` | 必須 | EMD Compilerが出力したContext Loop Plan JSON |
| `vocal_audio` | 必須 | Plan先頭と同じ時刻原点を持つボーカルステムPCM |
| `full_mix_audio` | 必須 | Plan先頭と同じ時刻原点を持つフルミックスPCM |
| `enable` | `true` | `false`では検証、切出し、paddingをせず三入力をそのまま返す |
| `scene_start` | `1` | 出力を開始するScene番号。UIは1ベースで、JSONの`shots[scene_start - 1]`に対応する |
| `scene_length` | `1` | `scene_start`から連続して出力するScene数 |

## 出力

| 出力 | 説明 |
|---|---|
| `plan_json` | 元Planの他fieldを保持し、`shots`だけを選択範囲へ置換したJSON |
| `vocal_audio` | 選択Scene範囲へ切り出し、必要な末尾だけPCM無音で補完したvocal |
| `full_mix_audio` | 同じframe範囲へ切り出したfull mix |

## 時間計算

`scene_start=N`のPCM開始位置は、JSON index `0`から`N - 2`まで、つまり選択Sceneより前にある全Sceneのdelivered frame数を加算して求めます。`scene_start=1`ならスキップは0です。

Context Loopの`length`には継続用のvisual contextが含まれます。同じ音声区間を重複させないため、各SceneのPCM時間は次の値を正本にします。

```text
delivered_frames = length - context_length
```

選択範囲も同じ方法で合計し、24fpsの厳密な有理数時間から各入力sample rateの開始sampleと終了sampleを算出します。入力PCMが選択範囲の終端より短い場合だけ、不足sampleを出力末尾へゼロで追加します。resample、mix、先頭padding又は音声内容の補間は行いません。

`scene_start + scene_length - 1`がPlanのScene数を超える場合、暗黙に短縮せずエラーにします。選択した`shots`内の`id`、`length`、`context_length`、prompt及びcontinuity指定は変更しません。

## 接続例

同梱動画WFでは`Audio Pad Pair`の直後に本ノードを接続済みです。Plan JSONは`Compiled Plan JSON (.txt handoff)`から、二つのPCMは整列・末尾padding済みのAudio Pad出力から受けます。本ノードのPlan出力は`Production Plan`へ、PCM出力は`H3 Audio Tracks`と選択中のlip-sync経路へ接続されます。Audio Reference方式では、Scene位置へ整列済みの`reference_audio_b`を`vocal_audio`へ渡してから選択範囲を切り出します。

同梱WF上の既定値は`enable=false`です。通常生成ではそのままpass-throughし、部分生成時だけ`enable=true`へ切り替えてください。ノード単体を新規追加した場合のComfyUI既定値は`true`です。
