"""CPU input replay contracts, not assertions about rendered MV quality."""
import unittest

from core.emd import parse_emd
from tools.debug_prop_pipeline import prepare, contract_run, remove_transport_markers, semantic


SOURCE = '''# サブジェクト
* `画像1` 白い盾と日本刀を持つ人物。
# 共通プロンプト
## モーション
* 人物の動きは各Shotの演技に従う。
> `シーン` 1
# シーン 00:00.000 --> 00:01.000
* `H3長` 22
## ショット 00:00.000
* `演技` 外側の固定演技。
* `カメラ` 外側の固定画角。
## 音響
* `リップシンク` `Context Loop` `サブジェクト1`
> `シーン` 2
# シーン 00:01.000 --> 00:06.000 継続
* `H3長` 158
> `口元` `サブジェクト1` 00:01.000 --> 00:06.000 `歌唱`
> `セクション` VERSE
> `歌詞開始` 00:01.000
> `歌詞終了` 00:03.000
> `歌詞` 変わらぬ願い
## ショット 00:01.000
* `演技` 境界の固定演技。
* `演技` 境界の補完演技。
* `カメラ` 時計回りのArc Shot。
## ショット 00:03.000
* `演技` 再生成する演技。
* `カメラ` 再生成する画角。
> `シーン` 3
# シーン 00:06.000 --> 00:11.000 継続
* `H3長` 158
## ショット 00:06.000
* `演出` 葉が舞う。
* `演技` 古い演技。
* `カメラ` 古い画角。
> `シーン` 4
# シーン 00:11.000 --> 00:16.000 継続
* `H3長` 158
## ショット 00:11.000
* `演出` なし
* `演技` 古い演技。
* `演技` 古い補完。
* `カメラ` 古い画角。
'''


class PropPipelinePrepareTests(unittest.TestCase):
    def test_only_selected_fields_reopen_and_context_survives(self):
        inputs = prepare(SOURCE, (2, 3, 4))
        self.assertEqual(inputs['reopened_shots'], [[2, 2], [3, 1], [4, 1]])
        self.assertEqual(inputs['no_event_transport_markers'], [[2, 2]])
        result, calls = contract_run(inputs)
        before, after = parse_emd(SOURCE), parse_emd(result.emd.text)
        self.assertEqual(semantic(before.scenes[0].shots), semantic(after.scenes[0].shots))
        self.assertEqual(before.scenes[1].shots[0].body, after.scenes[1].shots[0].body)
        self.assertEqual(semantic(before.scenes[1].mouth_performances),
                         semantic(after.scenes[1].mouth_performances))
        self.assertNotIn('scene-author-event', [c['task'] for c in calls])
        self.assertEqual(sum(c['task'] == 'subject-prop-inventory' for c in calls), 1)

    def test_composition_stays_after_camera_and_author_boundary_skips(self):
        inputs = prepare(SOURCE, (2, 3, 4))
        result, calls = contract_run(inputs)
        scene17 = [c for c in calls if c['payload'].get('scene_number', c['payload'].get('scene')) == 4]
        self.assertEqual([c['task'] for c in scene17], ['scene-author-prop-decision',
                         'scene-author-performance', 'scene-author-camera', 'scene-author-composition-choice'])
        self.assertEqual({row[0] for row in result.content.motion_compositions}, {3, 4})
        for c in calls:
            if c['task'] == 'scene-author-performance':
                self.assertNotIn('scheduled_motion_composition', c['payload'])

    def test_marker_removal_does_not_remove_author_none_event(self):
        inputs = prepare(SOURCE, (2, 3, 4))
        result, _ = contract_run(inputs)
        cleaned = remove_transport_markers(result.emd.text, inputs['no_event_transport_markers'])
        document = parse_emd(cleaned)
        self.assertFalse(any(d.kind == '演出' for d in document.scenes[1].shots[1].directives))
        self.assertTrue(any(d.kind == '演出' and d.text == 'なし'
                            for d in document.scenes[3].shots[0].directives))
        with self.assertRaises(ValueError):
            remove_transport_markers(cleaned, inputs['no_event_transport_markers'])

    def test_nonexistent_scene_is_not_silently_selected(self):
        with self.assertRaises(ValueError):
            prepare(SOURCE, (18,))


if __name__ == '__main__':
    unittest.main()
