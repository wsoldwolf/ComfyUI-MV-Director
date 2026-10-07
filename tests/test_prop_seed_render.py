import unittest

from tools.debug_prop_seed_render import seed_plan


class SeedPlanTests(unittest.TestCase):
    def test_only_selected_seed_changes_without_mutating_baseline(self):
        baseline = {'shots': [{'seed': 2, 'prompt': 'first'},
                              {'seed': 17507335375349101561, 'prompt': 'second', 'length': 260}],
                    'subjects': ['identity']}
        new = seed_plan(baseline, 2, 17507335375349101562)
        self.assertEqual(baseline['shots'][1]['seed'], 17507335375349101561)
        self.assertEqual(new['shots'][1]['seed'], 17507335375349101562)
        new['shots'][1]['seed'] = baseline['shots'][1]['seed']
        self.assertEqual(new, baseline)

    def test_invalid_or_unchanged_seed_fails(self):
        for seed in (-1, 2**64, 4):
            with self.assertRaises(ValueError):
                seed_plan({'shots': [{'seed': 4}]}, 1, seed)
        with self.assertRaises(ValueError):
            seed_plan({'shots': [{'seed': 4}]}, 0, 5)


if __name__ == '__main__':
    unittest.main()
