import json
import unittest

from core.emd import parse_emd
from tools.debug_prop_shot_repair import parse_proposal, replace_fields

SOURCE = '''# サブジェクト
* `画像1` 刀と盾を持つ人物。
> `シーン` 1
# シーン 00:00.000 --> 00:03.000
* `H3長` 90
> `口元` `サブジェクト1` 00:00.000 --> 00:03.000 `歌唱`
## ショット 00:00.000
* `演技` 前半1。
* `カメラ` 前半Camera1。
## ショット 00:01.000
* `演技` 前半2。
* `カメラ` 前半Camera2。
> `歌詞` 掌へ
## ショット 00:02.000
* `演出` 人物が掌を前へ伸ばす。
* `演技` 古い本文。
* `演技` 固定の別行補完。
* `カメラ` 古いCamera。
> `シーン` 2
# シーン 00:03.000 --> 00:04.000 継続
* `H3長` 56
## ショット 00:03.000
* `演技` 次Sceneの固定演技。
* `カメラ` 次Sceneの固定Camera。
'''


def proposal():
    return {'status': 'REVISE', 'reason': '今回の映像評価に対する局所案',
            'performance': '生成された演技。', 'camera': '生成されたCamera。',
            'end_state': '右手刀・左手盾・視線前方',
            'holding_plan': {'prop_locations': {'P1': '右手', 'P2': '左手'},
                             'right_hand': '刀を保持', 'left_hand': '盾を保持',
                             'transition': 'なし', 'performance_scope': '体幹から腕を動かす',
                             'end_state': {'P1': '右手', 'P2': '左手'}}}


class ShotRepairTests(unittest.TestCase):
    def test_joint_transport_covers_every_prop(self):
        v = proposal()
        parsed = parse_proposal('SHOT_REPAIR\t1\t' + json.dumps(v), {'P1', 'P2'})
        self.assertEqual(parsed, v)
        del v['holding_plan']['end_state']['P2']
        self.assertIsNone(parse_proposal('SHOT_REPAIR\t1\t' + json.dumps(v), {'P1', 'P2'}))

    def test_only_last_shot_primary_fields_are_assigned(self):
        before = parse_emd(SOURCE)
        updated = replace_fields(SOURCE, proposal(), scene_number=1)
        after = parse_emd(updated)
        self.assertEqual(before.scenes[0].shots[:2], after.scenes[0].shots[:2])
        self.assertEqual(before.scenes[1], after.scenes[1])
        self.assertIn('人物が掌を前へ伸ばす。', updated)
        self.assertIn('固定の別行補完。', updated)
        self.assertIn('生成された演技。', updated)
        self.assertIn('生成されたCamera。', updated)
        self.assertEqual(before.scenes[0].mouth_performances, after.scenes[0].mouth_performances)

    def test_unresolved_produces_no_change(self):
        v = {'status': 'UNRESOLVED', 'reason': '固定Eventに判断が必要',
             'performance': '', 'camera': '', 'end_state': '', 'holding_plan': {}}
        self.assertEqual(parse_proposal('SHOT_REPAIR\t1\t' + json.dumps(v), {'P1', 'P2'}), v)
        self.assertEqual(replace_fields(SOURCE, v), SOURCE)
        v['performance'] = '禁止された修正'
        self.assertIsNone(parse_proposal('SHOT_REPAIR\t1\t' + json.dumps(v), {'P1', 'P2'}))


if __name__ == '__main__':
    unittest.main()
