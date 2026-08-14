from __future__ import annotations

import unittest

from application.evidence.content_chunking import split_normalized_source_content
from application.evidence.exceptions import UngroundedEvidenceError
from application.evidence.grounding import (
    canonicalize_grounding_text,
    verify_grounding,
)


class CanonicalGroundingRepresentationAlignmentTests(unittest.TestCase):
    def assertGrounded(self, source: str, excerpt: str) -> None:  # noqa: N802
        locator = verify_grounding(source_text=source, excerpt=excerpt)
        canonical_source = canonicalize_grounding_text(source)
        self.assertEqual(
            canonical_source[locator.normalized_start : locator.normalized_end],
            canonicalize_grounding_text(excerpt),
        )

    def assertUngrounded(self, source: str, excerpt: str) -> None:  # noqa: N802
        with self.assertRaises(UngroundedEvidenceError):
            verify_grounding(source_text=source, excerpt=excerpt)

    def test_named_amp_entity_matches_rendered_excerpt(self) -> None:
        self.assertGrounded("pizza &amp; delivery", "pizza & delivery")

    def test_decimal_apostrophe_entity_matches_rendered_excerpt(self) -> None:
        self.assertGrounded("John&#39;s Pizza", "John's Pizza")

    def test_hex_apostrophe_entity_matches_rendered_excerpt(self) -> None:
        self.assertGrounded("John&#x27;s Pizza", "John's Pizza")

    def test_named_quote_entity_matches_rendered_excerpt(self) -> None:
        self.assertGrounded('&quot;value tier&quot;', '"value tier"')

    def test_nbsp_entity_and_unicode_nbsp_match_canonical_space(self) -> None:
        self.assertGrounded("A&nbsp;B", "A B")
        self.assertGrounded("A\u00a0B", "A B")

    def test_multiple_entities_match_one_rendered_excerpt(self) -> None:
        self.assertGrounded(
            "John&#39;s Pizza &amp; Delivery&nbsp;&quot;Value&quot;",
            'John\'s Pizza & Delivery "Value"',
        )

    def test_numeric_unicode_entity_matches_rendered_character(self) -> None:
        self.assertGrounded("Forecast 2026&#8211;2028", "Forecast 2026–2028")

    def test_unicode_canonical_equivalence_uses_nfc(self) -> None:
        self.assertGrounded("Caf&#233; demand", "Cafe\u0301 demand")

    def test_existing_exact_text_behavior_is_unchanged(self) -> None:
        self.assertGrounded("Exact acquired source text.", "acquired source text.")

    def test_case_remains_significant(self) -> None:
        self.assertUngrounded("Company A entered Ukraine.", "company A entered Ukraine.")

    def test_changed_number_remains_rejected(self) -> None:
        self.assertUngrounded("Revenue increased by 20%.", "Revenue increased by 25%.")

    def test_changed_company_remains_rejected(self) -> None:
        self.assertUngrounded(
            "Company A entered Ukraine.",
            "Company B entered Ukraine.",
        )

    def test_changed_negation_remains_rejected(self) -> None:
        self.assertUngrounded("Demand did not decline.", "Demand declined.")

    def test_paraphrase_remains_rejected(self) -> None:
        self.assertUngrounded(
            "Industrial electricity prices increased in 2024.",
            "Power became more expensive during 2024.",
        )

    def test_non_contiguous_assembly_remains_rejected(self) -> None:
        self.assertUngrounded(
            "Pizza demand increased. Delivery remained stable.",
            "Pizza demand increased and delivery remained stable.",
        )

    def test_pro_consulting_entity_fixture_now_grounds(self) -> None:
        self.assertGrounded(
            "Forecast Indicators for Market Development in 2026&ndash;2028. "
            "Calculation under KVED 56.10 &ldquo;Restaurant Activities and Mobile "
            "Food Services&rdquo; in Ukraine for 2023&ndash;2025.",
            "Forecast Indicators for Market Development in 2026–2028. "
            "Calculation under KVED 56.10 “Restaurant Activities and Mobile "
            "Food Services” in Ukraine for 2023–2025.",
        )

    def test_pro_consulting_unsupported_changed_period_remains_rejected(self) -> None:
        self.assertUngrounded(
            "Forecast Indicators for Market Development in 2026&ndash;2028.",
            "Forecast Indicators for Market Development in 2025–2028.",
        )

    def test_uba_nbsp_fixture_now_grounds(self) -> None:
        self.assertGrounded(
            "Ukrainian Business Award:&nbsp;ТОП-10 мереж піцерій в Україні 2025",
            "Ukrainian Business Award: ТОП-10 мереж піцерій в Україні 2025",
        )

    def test_pizzahouse_entity_fixture_now_grounds(self) -> None:
        self.assertGrounded(
            "Four Cheese &amp; Quattro di Carne &mdash; 30&nbsp;cm",
            "Four Cheese & Quattro di Carne — 30 cm",
        )

    def test_cross_domain_heat_pump_fixture(self) -> None:
        self.assertGrounded(
            "New Zealand heat pumps &amp; household efficiency",
            "New Zealand heat pumps & household efficiency",
        )

    def test_cross_domain_upi_fixture(self) -> None:
        self.assertGrounded(
            "India&#39;s UPI merchant payments",
            "India's UPI merchant payments",
        )

    def test_cross_domain_industrial_electricity_fixture(self) -> None:
        self.assertGrounded(
            "Germany&nbsp;industrial electricity &euro;120/MWh",
            "Germany industrial electricity €120/MWh",
        )

    def test_chunk_offsets_reference_the_same_canonical_representation(self) -> None:
        source = "prefix &amp;  A&nbsp;B Cafe\u0301 suffix"
        chunks = split_normalized_source_content(
            source,
            chunk_chars=12,
            overlap_chars=3,
        )
        canonical = canonicalize_grounding_text(source)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertEqual(
                chunk.text,
                canonical[
                    chunk.original_normalized_start : chunk.original_normalized_end
                ],
            )

    def test_canonicalization_is_deterministic_and_idempotent(self) -> None:
        source = "A&nbsp;&amp;&nbsp;Cafe\u0301"
        once = canonicalize_grounding_text(source)
        self.assertEqual(canonicalize_grounding_text(once), once)


if __name__ == "__main__":
    unittest.main()
