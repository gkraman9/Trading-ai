"""E4.7 independently authored adversarial tests; invented data only."""
from copy import deepcopy
import json
import unittest
from iat.intelligence.paper_account import PaperAccount, validate_paper_journal
from iat.intelligence.protected_paper import ProtectedPaperAccount, validate_protected_journal
from iat.intelligence.paper_contracts import SyntheticQuote, SyntheticQuoteTape
from protection_fixtures import setup, open_position, quote, observe
from risk_fixtures import START


class E47PaperReview(unittest.TestCase):
    def test_numeric_false_cannot_authenticate_as_boolean_in_either_journal(self):
        for cls, validate in ((PaperAccount, validate_paper_journal),
                              (ProtectedPaperAccount, validate_protected_journal)):
            with self.subTest(model=cls.__name__):
                account = cls(started_at=START)
                original = account.journal()
                self.assertTrue(validate(json.loads(json.dumps(original)), source=account))
                for location in ((), ('account',)):
                    forged = deepcopy(original)
                    target = forged if not location else forged['account']
                    target['execution_allowed'] = 0
                    # Unchanged digest must not hide Python's False == 0 equality.
                    with self.assertRaises(ValueError):
                        validate(forged, source=account)
                self.assertEqual(original, account.journal())

    def test_quotation_closed_row_cannot_bypass_original_history_binding(self):
        k, _, _ = setup()
        open_position(k)
        original = k['account'].journal()
        row = quote(k, quotation=False, opening=False)
        replacement = SyntheticQuoteTape(k['tape'].symbol, k['tape'].feed, k['tape'].dataset_sha256)
        replacement_row = replacement.append(SyntheticQuote(**row['quote']))
        with self.assertRaisesRegex(ValueError, 'QUOTE_SOURCE_HISTORY_MISMATCH'):
            k['account'].observe(k['risk'], risk_inputs=k['risk_inputs'], tape=replacement,
                                 quote=replacement_row, as_of=row['quote']['available_at_utc'])
        self.assertEqual(original, k['account'].journal())
        result = observe(k, row)
        self.assertEqual(result['status'], 'UNRESOLVED')
        self.assertIn('SESSION_QUOTATIONS_UNAVAILABLE', result['reason_codes'])


if __name__ == '__main__':
    unittest.main()
