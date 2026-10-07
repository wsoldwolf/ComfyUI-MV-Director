from copy import deepcopy
import json

import unittest

from tools.debug_prop_full_render import full_graph


def fixture_graph():
    plan = {'shots': [{'length': 243, 'seed': 5}]}
    graph = {node: {'class_type': 'test', 'inputs': {'plan_json': json.dumps(plan)}} for node in ('24', '37', '48')}
    graph['48']['inputs']['enable'] = False
    graph.update({node: {'class_type': 'test', 'inputs': values} for node, values in {
        '21': {'filename': 'previous'}, '7': {'start_clip': 17, 'scene_range': '17'},
        '29': {'start_clip': 17, 'scene_range': '17'}, '47': {'megapixels': 0.9},
        '28': {'enabled': False}, '40': {'voice': ['48', 1]},
    }.items()})
    return graph, plan


class FullRenderTests(unittest.TestCase):
    def test_full_graph_preserves_plan_and_does_not_mutate_source(self):
        graph, plan = fixture_graph()
        before = deepcopy(graph)
        result = full_graph(graph, plan, 'full-test')
        self.assertEqual(graph, before)
        for node in ('24', '37', '48'):
            self.assertEqual(json.loads(result[node]['inputs']['plan_json']), plan)
        for node in ('7', '29'):
            self.assertEqual(result[node]['inputs']['start_clip'], 1)
            self.assertEqual(result[node]['inputs']['scene_range'], '')
            self.assertIs(result[node]['inputs']['verify_resume_history'], True)
        self.assertEqual(result['24']['inputs']['default_steps'], 20)


    def test_full_graph_rejects_changed_conditions(self):
        for change in ('splitter', 'resolution', 'spectrum', 'lora', 'review', 'lipsync', 'steps', 'plan'):
            with self.subTest(change=change):
                graph, plan = fixture_graph()
                if change == 'splitter':
                    graph['48']['inputs']['enable'] = True
                elif change == 'resolution':
                    graph['47']['inputs']['megapixels'] = 0.4
                elif change in ('spectrum', 'lora'):
                    graph['99'] = {'class_type': change, 'inputs': {}}
                elif change == 'review':
                    graph['28']['inputs']['enabled'] = True
                elif change == 'lipsync':
                    graph['40']['inputs']['voice'] = ['33', 0]
                elif change == 'steps':
                    plan['shots'][0]['steps'] = 8
                    for node in ('24', '37', '48'):
                        graph[node]['inputs']['plan_json'] = json.dumps(plan)
                else:
                    graph['37']['inputs']['plan_json'] = '{}'
                with self.assertRaises(ValueError):
                    full_graph(graph, plan, 'full-test')
