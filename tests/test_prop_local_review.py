import unittest

from tools.debug_prop_local_review import apply_review, eligible, parse_review, synthetic_case


class LocalHoldingReviewTests(unittest.TestCase):
    def setUp(self):
        self.case = synthetic_case('test', [{'id': 'P1', 'label': '小道具'}],
            {'right_hand': '保持'}, '作者固定Event', '元の本文', '元の状態')
        self.revise = {'status': 'REVISE', 'reason': '保持と矛盾',
                       'performance': '局所変更', 'end_state': '変更後の状態'}

    def test_only_target_fields_change(self):
        output = apply_review(self.case, self.revise)
        self.assertEqual(output['readonly'], self.case['input']['readonly'])
        self.assertEqual(output['target']['performance'], '局所変更')
        self.assertEqual(self.case['input']['target']['performance'], '元の本文')

    def test_author_fixed_never_changes(self):
        self.case['ownership'] = 'author'
        self.assertFalse(eligible(self.case))
        self.assertEqual(apply_review(self.case, self.revise), self.case['input'])

    def test_no_props_never_changes(self):
        self.case['input']['readonly']['prop_inventory'] = []
        self.assertFalse(eligible(self.case))
        self.assertEqual(apply_review(self.case, self.revise), self.case['input'])

    def test_failed_or_unresolved_review_retains_original(self):
        for verdict in (None, {'status': 'UNRESOLVED'}, {'status': 'KEEP'}):
            self.assertEqual(apply_review(self.case, verdict), self.case['input'])

    def test_protocol_is_exact_and_duplicate_keys_are_rejected(self):
        self.assertEqual(parse_review('HOLDING_REVIEW\t1\t{"status":"KEEP","reason":"両立","performance":"","end_state":""}')['status'], 'KEEP')
        self.assertIsNone(parse_review('HOLDING_REVIEW\t1\t{"status":"KEEP","status":"REVISE","reason":"両立","performance":"","end_state":""}'))
        self.assertIsNone(parse_review('HOLDING_REVIEW\t1\t{"status":"KEEP","reason":"両立","performance":"勝手な修正","end_state":""}'))
        self.assertIsNone(parse_review('HOLDING_REVIEW\t1\t{"status":"REVISE","reason":"矛盾","performance":"","end_state":""}'))


if __name__ == '__main__':
    unittest.main()
