import json
import unittest
import httpx
from unittest.mock import patch

from infrastructure.retrieval.world_bank_json_extractor import parse_world_bank_population_json
from infrastructure.retrieval.http_source_retriever import HttpSourceRetriever
from domain.sources.source_candidate import SourceCandidate


class WorldBankJsonExtractorTests(unittest.TestCase):
    URL = "https://api.worldbank.org/v2/country/UKR/indicator/SP.POP.TOTL?date=2015:2021&format=json"

    def test_real_saved_response_produces_bounded_structured_rows(self):
        data = json.dumps([{"page": 1}, [
            {"countryiso3code": "UKR", "indicator": {"id": "SP.POP.TOTL"}, "date": str(year), "value": value}
            for year, value in ((2015, 45154000), (2016, 44982000), (2017, 44828000), (2018, 44623000), (2019, 44385000), (2020, 44135000), (2021, 43810000))
        ]]).encode()
        result = parse_world_bank_population_json(data, url=self.URL)
        self.assertEqual(result["records"], 7)
        self.assertEqual(result["indicator_id"], "SP.POP.TOTL")
        self.assertEqual(result["rows"][0]["world_bank_provenance"]["record_index"], 0)
        self.assertEqual(result["rows"][0]["cells"][3]["value"], "Ukraine")

    def test_http_retriever_dispatches_the_bounded_world_bank_adapter(self):
        data = json.dumps([{"page": 1}, [{"countryiso3code": "UKR", "indicator": {"id": "SP.POP.TOTL"}, "date": "2021", "value": 43810000}]]).encode()
        def handler(request):
            return httpx.Response(200, headers={"content-type": "application/json"}, content=data, request=request)
        client = httpx.Client(transport=httpx.MockTransport(handler))
        try:
            response = httpx.Response(200, headers={"content-type": "application/json"}, content=data, request=httpx.Request("GET", self.URL))
            with patch("infrastructure.retrieval.http_source_retriever.fetch_with_validated_redirects", return_value=response):
                source = HttpSourceRetriever(http_client=client).retrieve(SourceCandidate(
                    provider="test", url=self.URL, title="World Bank", snippet="", query_id="q", rank=1,
                ))
        finally:
            client.close()
        self.assertEqual(source.metadata["world_bank_indicator"], "SP.POP.TOTL")
        self.assertEqual(source.metadata["structured_tables_v2"][0]["world_bank_provenance"]["record_index"], 0)

    def test_wrong_indicator_and_unbounded_shape_fail_closed(self):
        payload = [{"page": 1}, [{"countryiso3code": "UKR", "indicator": {"id": "OTHER"}, "date": "2021", "value": 1}]]
        with self.assertRaises(ValueError):
            parse_world_bank_population_json(json.dumps(payload).encode(), url=self.URL)
        with self.assertRaises(ValueError):
            parse_world_bank_population_json(b"{}", url=self.URL)
        for malformed in (None, [], "text"):
            payload = [{"page": 1}, [{"countryiso3code": "UKR", "indicator": malformed, "date": "2021", "value": 1}]]
            with self.assertRaises(ValueError):
                parse_world_bank_population_json(json.dumps(payload).encode(), url=self.URL)
        for value in (float("nan"), float("inf"), float("-inf"), 1e16):
            payload = [{"page": 1}, [{"countryiso3code": "UKR", "indicator": {"id": "SP.POP.TOTL"}, "date": "2021", "value": value}]]
            with self.assertRaises(ValueError):
                parse_world_bank_population_json(json.dumps(payload, allow_nan=True).encode(), url=self.URL)
