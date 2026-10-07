import unittest
from copy import deepcopy

from tools.debug_prop_continuation import build_inputs


class ContinuationTests(unittest.TestCase):
    def test_planned_state_replaces_old_state_without_changing_inputs(self):
        tasks = ('scene-author-prop-decision', 'scene-author-performance', 'scene-author-camera')
        calls = [{'task': task, 'payload': {'scene_number': 17, 'previous_scene_state': 'old',
                  'previous_prop_state': {'P1': 'old'}, 'fixed_event': 'event', 'mouth': 'sing'}} for task in tasks]
        original = deepcopy(calls)
        handoff = {'performance_end_state': 'shield forward',
                   'accepted_prop_decision': {'end_state': {'P1': 'right', 'P2': 'left'}},
                   'camera_from_same_joint_proposal': 'camera prose'}
        values = build_inputs(calls, handoff)
        self.assertEqual(calls, original)
        self.assertEqual(values[tasks[0]]['previous_prop_state'], {'P1': 'right', 'P2': 'left'})
        self.assertEqual(values[tasks[1]]['previous_scene_state'], 'shield forward')
        self.assertEqual(values[tasks[2]]['previous_scene_state'], 'camera prose')
        for payload in values.values():
            self.assertEqual(payload['fixed_event'], 'event')
            self.assertEqual(payload['mouth'], 'sing')

    def test_ambiguous_source_fails(self):
        with self.assertRaises(ValueError):
            build_inputs([], {})


if __name__ == '__main__':
    unittest.main()
