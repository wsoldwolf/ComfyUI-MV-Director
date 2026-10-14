import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.generate_workflows import build_plan_workflow, sync_subject_inputs, validate_workflow, write_workflows


ROOT = Path(__file__).resolve().parents[1]


class SubjectWorkflowTests(unittest.TestCase):
    def legacy(self):
        workflow = json.loads((ROOT / 'workflows/01_plan_compiler_context_loop.json').read_text(encoding='utf-8'))
        # Manufacture the previous shared-Vision route even after fixtures migrate.
        from tools.generate_workflows import _connect, _disconnect_input
        _disconnect_input(workflow, 9, 'concept_emd')
        _connect(workflow, 3, 0, 9, 'concept_emd', 'STRING')
        for node in workflow['nodes']:
            if node['type'] in {'MVDirectorDirectionEnhancer', 'MVDirectorTimelinePlanner'}:
                node['inputs'] = [p for p in node['inputs'] if p['name'] not in {'concept_emd_2', 'concept_emd_3', 'concept_emd_4'}]
            if node['type'] == 'MVDirectorDirectionEnhancer':
                node['outputs'] = node['outputs'][:3]
        return workflow

    def test_migration_preserves_widgets_layout_and_source_data(self):
        workflow = self.legacy()
        before = copy.deepcopy(workflow)
        sync_subject_inputs(workflow)
        validate_workflow(workflow)
        for old, new in zip(before['nodes'], workflow['nodes']):
            for key in ('widgets_values', 'pos', 'size', 'color', 'bgcolor', 'properties'):
                self.assertEqual(old.get(key), new.get(key), (old['id'], key))
        planner = next(n for n in workflow['nodes'] if n['id'] == 9)
        port = next(p for p in planner['inputs'] if p['name'] == 'concept_emd')
        row = next(r for r in workflow['links'] if r[0] == port['link'])
        self.assertEqual(row[1:3], [8, 3])
        for node in workflow['nodes']:
            if node['id'] in (8, 9):
                for number in range(2, 5):
                    self.assertEqual(next(p for p in node['inputs'] if p['name'] == f'concept_emd_{number}'),
                                     {'name': f'concept_emd_{number}', 'type': 'STRING', 'link': None})

    def test_idempotent(self):
        workflow = self.legacy()
        sync_subject_inputs(workflow)
        before = copy.deepcopy(workflow)
        sync_subject_inputs(workflow)
        self.assertEqual(workflow, before)

    def test_custom_author_route_is_retained(self):
        from tools.generate_workflows import _connect, _disconnect_input
        workflow = self.legacy()
        _disconnect_input(workflow, 9, 'concept_emd')
        _connect(workflow, 15, 0, 9, 'concept_emd', 'STRING')
        links = copy.deepcopy(workflow['links'])
        sync_subject_inputs(workflow)
        self.assertEqual(workflow['links'], links)
        validate_workflow(workflow)

    def test_direct_planner_extra_subject_route_is_retained(self):
        from tools.generate_workflows import _connect
        workflow = self.legacy()
        planner = next(n for n in workflow['nodes'] if n['id'] == 9)
        planner['inputs'].append({'name': 'concept_emd_2', 'type': 'STRING', 'link': None})
        _connect(workflow, 15, 0, 9, 'concept_emd_2', 'STRING')
        links = copy.deepcopy(workflow['links'])
        sync_subject_inputs(workflow)
        self.assertEqual(workflow['links'], links)
        validate_workflow(workflow)

    def test_invalid_existing_output_fails(self):
        workflow = self.legacy()
        next(n for n in workflow['nodes'] if n['id'] == 8)['outputs'].append({'name': 'custom', 'type': 'STRING'})
        with self.assertRaises(ValueError):
            sync_subject_inputs(workflow)

    def test_all_generated_modes_route_merged_subjects(self):
        for mode in ('context_loop', 'audio_reference', 'lyrics'):
            workflow = build_plan_workflow(mode)
            validate_workflow(workflow)
            planner = next(n for n in workflow['nodes'] if n['id'] == 9)
            port = next(p for p in planner['inputs'] if p['name'] == 'concept_emd')
            self.assertEqual(next(r[1:3] for r in workflow['links'] if r[0] == port['link']), [8, 3])

    def test_writer_leaves_video_bytes_untouched(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'plan.json').write_text(json.dumps(self.legacy()), encoding='utf-8')
            video = (ROOT / 'workflows/02_video_context_loop.json').read_bytes()
            (root / 'video.json').write_bytes(video)
            write_workflows(Path('unused'), root, subject_inputs_only=True)
            self.assertEqual((root / 'video.json').read_bytes(), video)
            validate_workflow(json.loads((root / 'plan.json').read_text(encoding='utf-8')))
