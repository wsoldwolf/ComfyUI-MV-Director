import copy
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.generate_workflows import validate_workflow, _remove_nodes
from tools.workflow_reassembly import sync_reassembly_path

ROOT = Path(__file__).resolve().parents[1]


def saved():
    return json.loads((ROOT / 'workflows/02_video_generator.json').read_text(encoding='utf-8'))


class WorkflowReassemblyTests(unittest.TestCase):
    def test_saved_graph_has_disjoint_groups_and_safe_defaults(self):
        wf = saved()
        validate_workflow(wf)
        config = wf['extra']['mv_director']['execution_paths']
        nodes = {n['id']: n for n in wf['nodes']}
        self.assertTrue(set(config['generation_node_ids']).isdisjoint(config['reassembly_node_ids']))
        for role, mode in (('generation', 0), ('reassembly', 2)):
            group = next(g for g in wf['groups'] if g['title'].startswith(
                'EXECUTION 1' if role == 'generation' else 'EXECUTION 2'))
            x, y, width, height = group['bounding']
            # Only the managed nodes may overlap a toggled group.
            inside = {n['id'] for n in wf['nodes'] if
                      n['pos'][0] < x + width and n['pos'][0] + n['size'][0] > x and
                      n['pos'][1] < y + height and n['pos'][1] + n['size'][1] > y}
            self.assertEqual(inside, set(config[f'{role}_node_ids']))
            self.assertTrue(all(nodes[i]['mode'] == mode for i in inside))
        rg = nodes[config['rgthree_controller_id']]
        self.assertEqual(rg['properties']['toggleRestriction'], 'always one')
        self.assertEqual(rg['properties']['matchTitle'], '^EXECUTION [12] - ')
        self.assertEqual(nodes[config['controller_id']]['type'], 'MarkdownNote')

    def test_reassembly_dependencies_exclude_studio_sampler_and_models(self):
        wf = saved()
        config = wf['extra']['mv_director']['execution_paths']
        visited = set()

        def visit(i):
            if i in visited: return
            visited.add(i)
            for _, origin, _, target, _, _ in wf['links']:
                if target == i: visit(origin)

        visit(config['reassembly_output_ids'][0])
        types = {n['type'] for n in wf['nodes'] if n['id'] in visited}
        self.assertTrue({'MiniMaxH3ChainManifestLoad', 'MiniMaxH3ChainPlanModern',
                         'MiniMaxH3AudioTracks'}.issubset(types))
        self.assertTrue(types.isdisjoint({'MiniMaxH3ChainPlanStudio', 'SamplerCustomAdvanced',
            'MiniMaxH3HybridLoader', 'CLIPLoader', 'VAELoader', 'MiniMaxH3ChainSegmentSave',
            'MiniMaxH3ChainReview', 'MiniMaxH3ChainLoopEnd'}), types)
        asm = next(n for n in wf['nodes'] if n['id'] == config['reassembly_output_ids'][0])
        self.assertTrue(asm['widgets_values_named']['filename'].endswith('_reassembled'))
        self.assertFalse(asm['widgets_values_named']['delete_checkpoints_after_assembly'])

    def test_migration_is_idempotent_and_preserves_saved_reassembly_mode(self):
        wf = saved()
        config = wf['extra']['mv_director']['execution_paths']
        for n in wf['nodes']:
            if n['id'] in config['generation_node_ids']: n['mode'] = 2
            if n['id'] in config['reassembly_node_ids']: n['mode'] = 0
            n['pos'] = [n['pos'][0] + 100, n['pos'][1] + 250]
            n['size'] = [n['size'][0] + 20, n['size'][1] + 15]
        for group in wf['groups']:
            group['bounding'][0] += 100
            group['bounding'][1] += 250
        before = copy.deepcopy(wf)
        sync_reassembly_path(wf)
        self.assertEqual(wf, before)

    def test_normal_generator_preserves_reassembly_path_and_saved_modes(self):
        from tools.generate_4subject_workflows import write_workflows
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_workflows(ROOT/'workflows', Path(tmp))
            video = next(p for p in paths if p.name == '02_video_generator.json')
            self.assertEqual(json.loads(video.read_text(encoding='utf-8')), saved())

    def test_addition_preserves_media_model_widgets_and_old_wires(self):
        wf = saved()
        config = wf['extra']['mv_director'].pop('execution_paths')
        remove = set(config['reassembly_node_ids']) | {config['controller_id'], config['rgthree_controller_id']}
        remove.update(n['id'] for n in wf['nodes'] if n.get('title') == 'Execution mode / safety / frontend compatibility')
        _remove_nodes(wf, remove)
        wf['groups'] = [g for g in wf['groups'] if not g['title'].startswith('EXECUTION ')]
        before = copy.deepcopy(wf)
        sync_reassembly_path(wf)
        validate_workflow(wf)
        nodes = {n['id']: n for n in wf['nodes']}
        for n in before['nodes']:
            if n['type'] == 'MarkdownNote': continue
            self.assertEqual(nodes[n['id']].get('widgets_values'), n.get('widgets_values'))
            if n['id'] not in config['generation_node_ids']:
                self.assertEqual(nodes[n['id']]['mode'], n['mode'])
        for link in before['links']: self.assertIn(link, wf['links'])

    @unittest.skipUnless(shutil.which('node'), 'Node.js is required for frontend contract tests')
    def test_frontend_contracts_without_queueing_a_real_job(self):
        result = subprocess.run([shutil.which('node'), '--test', str(ROOT/'tests/test_execution_paths.mjs')],
            capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
