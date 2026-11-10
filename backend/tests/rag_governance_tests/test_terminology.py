
import unittest

from app.rag_governance.terminology import (
    GLOSSARY,
    get_term,
    search_terms,
    list_terms,
)


class TestTerminology(unittest.TestCase):

    def test_exact_term_lookup(self):
        result = get_term("Stock")

        self.assertIsNotNone(result)
        self.assertEqual(result.term, "Stock")

    def test_alias_lookup(self):
        result = get_term("ETFs")

        self.assertIsNotNone(result)
        self.assertEqual(result.term, "Exchange-Traded Fund (ETF)")

    def test_case_and_punctuation_normalization(self):
        result = get_term("EXPENSE-RATIO")

        self.assertIsNotNone(result)
        self.assertEqual(result.term, "Expense Ratio")

    def test_unknown_term_returns_none(self):
        result = get_term("Cryptocurrency mining")

        self.assertIsNone(result)

    def test_empty_or_invalid_lookup(self):
        self.assertIsNone(get_term(""))
        self.assertIsNone(get_term("   "))
        self.assertIsNone(get_term(None))

    def test_search_multiple_terms(self):
        results = search_terms("Explain ETFs and mutual funds")

        terms = [entry.term for entry in results]

        self.assertEqual(
            terms,
            ["Exchange-Traded Fund (ETF)", "Mutual Fund"]
        )

    def test_search_does_not_duplicate_entries(self):
        results = search_terms("Explain ETF investing and ETFs")

        terms = [entry.term for entry in results]

        self.assertEqual(
            terms.count("Exchange-Traded Fund (ETF)"),
            1
        )

    def test_search_unknown_term_returns_empty_list(self):
        results = search_terms("Explain blockchain mining")

        self.assertEqual(results, [])

    def test_list_all_glossary_entries(self):
        results = list_terms()

        self.assertEqual(len(results), len(GLOSSARY))
        self.assertGreater(len(results), 0)

    def test_category_filter(self):
        results = list_terms("risk_management")

        terms = [entry.term for entry in results]

        self.assertIn("Diversification", terms)
        self.assertIn("Risk Tolerance", terms)
        self.assertIn("Asset Allocation", terms)

        self.assertTrue(
            all(entry.category == "risk_management" for entry in results)
        )

    def test_list_entries_are_alphabetically_sorted(self):
        results = list_terms()

        terms = [entry.term.casefold() for entry in results]

        self.assertEqual(terms, sorted(terms))

    def test_search_limit(self):
        results = search_terms(
            "Explain stocks, bonds, ETFs, mutual funds and dividends",
            limit=2
        )

        self.assertEqual(len(results), 2)

    def test_invalid_search_limit(self):
        with self.assertRaises(ValueError):
            search_terms("Explain ETFs", limit=0)

        with self.assertRaises(ValueError):
            search_terms("Explain ETFs", limit=-1)

    def test_glossary_entries_include_source_metadata(self):
        entry = get_term("ETF")

        self.assertTrue(entry.source_title)
        self.assertTrue(entry.source_publisher)
        self.assertTrue(entry.source_url.startswith("https://"))


if __name__ == "__main__":
    unittest.main()
