"""E4.7 independently authored adversarial tests; invented data only."""

from copy import deepcopy
import json
from decimal import localcontext
import unittest
from iat.intelligence.paper_account import PaperAccount, validate_paper_journal
from iat.intelligence.protected_paper import (
    ProtectedPaperAccount,
    validate_protected_journal,
)
from iat.intelligence.paper_contracts import SyntheticQuote, SyntheticQuoteTape
from protection_fixtures import setup, open_position, quote, observe
from risk_fixtures import START


class E47PaperReview(unittest.TestCase):
    def test_numeric_false_cannot_authenticate_as_boolean_in_either_journal(self):
        for cls, validate in (
            (PaperAccount, validate_paper_journal),
            (ProtectedPaperAccount, validate_protected_journal),
        ):
            with self.subTest(model=cls.__name__):
                account = cls(started_at=START)
                original = account.journal()
                self.assertTrue(
                    validate(json.loads(json.dumps(original)), source=account)
                )
                for location in ((), ("account",)):
                    forged = deepcopy(original)
                    target = forged if not location else forged["account"]
                    target["execution_allowed"] = 0
                    # Unchanged digest must not hide Python's False == 0 equality.
                    with self.assertRaises(ValueError):
                        validate(forged, source=account)
                self.assertEqual(original, account.journal())

    def test_quotation_closed_row_cannot_bypass_original_history_binding(self):
        k, _, _ = setup()
        open_position(k)
        original = k["account"].journal()
        row = quote(k, quotation=False, opening=False)
        replacement = SyntheticQuoteTape(
            k["tape"].symbol, k["tape"].feed, k["tape"].dataset_sha256
        )
        replacement_row = replacement.append(SyntheticQuote(**row["quote"]))
        with self.assertRaisesRegex(ValueError, "QUOTE_SOURCE_HISTORY_MISMATCH"):
            k["account"].observe(
                k["risk"],
                risk_inputs=k["risk_inputs"],
                tape=replacement,
                quote=replacement_row,
                as_of=row["quote"]["available_at_utc"],
            )
        self.assertEqual(original, k["account"].journal())
        result = observe(k, row)
        self.assertEqual(result["status"], "UNRESOLVED")
        self.assertIn("SESSION_QUOTATIONS_UNAVAILABLE", result["reason_codes"])

    def test_failed_protected_commit_rolls_back_private_history_and_costs(self):
        k, _, _ = setup()
        open_position(k)
        before = k["account"].journal()
        history = deepcopy(k["account"]._quote_history)
        row = quote(k, bid="2097.7", ask="2097.9")
        budget = k["account"]._max_events
        k["account"]._max_events = len(before["events"])
        try:
            with self.assertRaisesRegex(ValueError, "ACCOUNT_RESOURCE_LIMIT"):
                observe(k, row)
        finally:
            k["account"]._max_events = budget
        self.assertEqual(before, k["account"].journal())
        self.assertEqual(history, k["account"]._quote_history)
        self.assertIsNone(k["account"]._proposal)
        self.assertEqual(observe(k, row)["status"], "HYPOTHETICALLY_CLOSED")
        self.assertEqual(len(k["account"].snapshot()["closed_positions"]), 1)

    def test_corrected_old_quote_prefix_rejects_without_losing_position(self):
        k, _, _ = setup()
        open_position(k)
        row = quote(k)
        original = k["account"].journal()
        replacement = SyntheticQuoteTape(
            k["tape"].symbol, k["tape"].feed, k["tape"].dataset_sha256
        )
        for item in k["tape"].rows():
            values = dict(item["quote"])
            if values["sequence"] == 0:
                values["bid"] = "2099.8"
            last = replacement.append(SyntheticQuote(**values))
        with self.assertRaisesRegex(ValueError, "QUOTE_SOURCE_HISTORY_MISMATCH"):
            k["account"].observe(
                k["risk"],
                risk_inputs=k["risk_inputs"],
                tape=replacement,
                quote=last,
                as_of=row["quote"]["available_at_utc"],
            )
        self.assertEqual(original, k["account"].journal())
        self.assertEqual(observe(k, row)["status"], "MONITORING")

    def test_journal_serialization_is_independent_of_callers_decimal_precision(self):
        k, _, _ = setup()
        open_position(k)
        observe(k, quote(k, bid="2097.74", ask="2097.94"))
        expected = k["account"].journal()
        with localcontext() as context:
            context.prec = 2
            self.assertEqual(expected, k["account"].journal())


if __name__ == "__main__":
    unittest.main()
