from __future__ import annotations

import inspect
import unittest
from dataclasses import replace
from decimal import Decimal

from application.quantitative.comparison_statistics import ComparisonStatisticsService, MEAN_METHOD, PROPORTION_METHOD
from application.quantitative.cross_tab_statistics import CrossTabStatisticsService
from application.quantitative.dataset_import_service import QuantitativeDatasetImportService, VariableOverride
from application.quantitative.fingerprints import canonical_digest
from application.quantitative.numeric_statistics import NumericStatisticsService
from application.quantitative.weighting import build_analytical_view
from domain.quantitative.analysis import ComparisonSpecification, CrossTabAnalysisSpecification, NumericAnalysisSpecification
from domain.quantitative.dataset import DatasetFormat, PiiClassification, VariableRole, VariableType
from domain.quantitative.quality import DatasetQualityAssessment, DatasetQualityState
from domain.quantitative.weighting import WeightingMode
from infrastructure.quantitative.importers import XlsxOpenpyxlAdapter
from infrastructure.quantitative.storage import InMemoryDatasetStorage
from infrastructure.security.sha256_digest_provider import Sha256DigestProvider
from tests.application.quantitative.test_property_qd_cross_tab_statistical_result_provenance import workbook_bytes


class PropertyQGDeterministicComparisonProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.storage = InMemoryDatasetStorage(); self.digest = Sha256DigestProvider()
        rows = []
        for i in range(20): rows.append([f"a{i}", "A", "YES" if i < 18 else "NO", "YES" if i < 11 else "NO", i, i, 100+i])
        for i in range(20): rows.append([f"b{i}", "B", "YES" if i < 2 else "NO", "YES" if i < 10 else "NO", 30+i, i, 200+i])
        importer = QuantitativeDatasetImportService(importers=(XlsxOpenpyxlAdapter(),), storage=self.storage, digest_provider=self.digest)
        self.imported = importer.import_bytes(workbook_bytes(["id","group","response_sig","response_ns","score_sig","score_ns","secret"], rows), filename="qg.xlsx", dataset_format=DatasetFormat.XLSX, dataset_id="qg", project_id="p", run_id="r", data_sheet="Data", overrides={"id": VariableOverride(role=VariableRole.TECHNICAL_ID), "group": VariableOverride(variable_type=VariableType.DEMOGRAPHIC), "response_sig": VariableOverride(variable_type=VariableType.CATEGORICAL), "response_ns": VariableOverride(variable_type=VariableType.CATEGORICAL), "score_sig": VariableOverride(variable_type=VariableType.NUMERIC), "score_ns": VariableOverride(variable_type=VariableType.NUMERIC), "secret": VariableOverride(variable_type=VariableType.NUMERIC, role=VariableRole.PII, pii_classification=PiiClassification.PII_RESTRICTED)})
        self.cross = CrossTabStatisticsService(storage=self.storage, digest_provider=self.digest); self.numeric = NumericStatisticsService(storage=self.storage, digest_provider=self.digest); self.compare = ComparisonStatisticsService(storage=self.storage, digest_provider=self.digest)
    def var(self, name): return next(item for item in self.imported.codebook.variables if item.name == name)
    def quality(self):
        d=self.imported.dataset_version; fp=canonical_digest({"d":d.dataset_fingerprint,"q":"ok"},digest_provider=self.digest); return DatasetQualityAssessment(d.version_id,d.dataset_fingerprint,"qc",DatasetQualityState.QC_APPROVED,"a",True,fp)
    def view(self,spec,refs): return build_analytical_view(dataset=self.imported.dataset_version,quality=self.quality(),specification=spec,mode=WeightingMode.UNWEIGHTED,respondent_refs=refs,digest_provider=self.digest)
    def proportion_inputs(self, variable="response_sig"):
        spec=CrossTabAnalysisSpecification("tab",self.var(variable).variable_id,column_variable_id=self.var("group").variable_id); refs=self.cross.eligible_respondent_refs(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=spec); view=self.view(spec,refs); _,results=self.cross.compute(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=spec,view=view)
        pick=lambda g: next(x for x in results if x.statistic_type=="CROSS_TAB_COLUMN_PERCENTAGE" and x.row_category_value=="YES" and x.column_category_value==g)
        return pick("A"),pick("B"),view
    def mean_inputs(self, variable="score_sig"):
        output=[]
        for group in ("A","B"):
            gid=self.var("group").variable_id; spec=NumericAnalysisSpecification(f"mean-{group}",self.var(variable).variable_id,filter_definition=CrossTabStatisticsService.filter_definition(gid,group),filter_variable_id=gid,filter_category_value=group); refs=self.numeric.eligible_respondent_refs(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=spec); view=self.view(spec,refs); results=self.numeric.compute(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=spec,view=view); output.append((next(x for x in results if x.statistic_type=="NUMERIC_MEAN"),view))
        return output[0][0],output[1][0],output[0][1],output[1][1]
    def spec(self,method,variable,alpha="0.05",minimum=5): return ComparisonSpecification("cmp",method,self.var(variable).variable_id,self.var("group").variable_id,"A","B",outcome_category="YES" if method==PROPORTION_METHOD else None,alpha=Decimal(alpha),minimum_group_base=minimum)

    def test_significant_and_non_significant_proportions(self):
        a,b,v=self.proportion_inputs(); significant=self.compare.compare_proportions(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=self.spec(PROPORTION_METHOD,"response_sig"),group_a_result=a,group_b_result=b,view=v); self.assertTrue(significant.significant); self.assertTrue(significant.supports_significance_wording)
        a,b,v=self.proportion_inputs("response_ns"); nonsig=self.compare.compare_proportions(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=self.spec(PROPORTION_METHOD,"response_ns"),group_a_result=a,group_b_result=b,view=v); self.assertFalse(nonsig.significant)
    def test_significant_and_non_significant_welch_means(self):
        a,b,va,vb=self.mean_inputs(); sig=self.compare.compare_means(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=self.spec(MEAN_METHOD,"score_sig"),group_a_result=a,group_b_result=b,view_a=va,view_b=vb); self.assertTrue(sig.significant)
        a,b,va,vb=self.mean_inputs("score_ns"); ns=self.compare.compare_means(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=self.spec(MEAN_METHOD,"score_ns"),group_a_result=a,group_b_result=b,view_a=va,view_b=vb); self.assertFalse(ns.significant)
    def test_alpha_minimum_base_and_fingerprint_authority(self):
        a,b,v=self.proportion_inputs(); first=self.compare.compare_proportions(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=self.spec(PROPORTION_METHOD,"response_sig"),group_a_result=a,group_b_result=b,view=v); replay=self.compare.compare_proportions(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=self.spec(PROPORTION_METHOD,"response_sig"),group_a_result=a,group_b_result=b,view=v); changed=self.compare.compare_proportions(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=self.spec(PROPORTION_METHOD,"response_sig","0.01"),group_a_result=a,group_b_result=b,view=v); self.assertEqual(first,replay); self.assertNotEqual(first.reproducibility_fingerprint,changed.reproducibility_fingerprint)
        with self.assertRaisesRegex(ValueError,"minimum base"): self.compare.compare_proportions(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=self.spec(PROPORTION_METHOD,"response_sig",minimum=21),group_a_result=a,group_b_result=b,view=v)
    def test_changed_result_weighted_and_stale_inputs_fail_closed(self):
        a,b,v=self.proportion_inputs(); spec=self.spec(PROPORTION_METHOD,"response_sig")
        with self.assertRaisesRegex(ValueError,"stale|mismatched"): self.compare.compare_proportions(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=spec,group_a_result=replace(a,value=Decimal(1)),group_b_result=b,view=v)
        with self.assertRaisesRegex(ValueError,"unweighted"): self.compare.compare_proportions(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=spec,group_a_result=replace(a,weighting_status="WEIGHTED",weight_set_id="w"),group_b_result=b,view=v)
        with self.assertRaisesRegex(ValueError,"stale"): self.compare.compare_proportions(dataset=replace(self.imported.dataset_version,dataset_fingerprint="stale"),codebook=self.imported.codebook,specification=spec,group_a_result=a,group_b_result=b,view=v)
    def test_invalid_spec_overlap_and_pii_fail_closed(self):
        a,b,v=self.proportion_inputs(); spec=replace(self.spec(PROPORTION_METHOD,"response_sig"),group_b_category="A")
        with self.assertRaisesRegex(ValueError,"invalid"): self.compare.compare_proportions(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=spec,group_a_result=a,group_b_result=b,view=v)
        pii=replace(self.spec(MEAN_METHOD,"score_sig"),variable_id=self.var("secret").variable_id); ma,mb,va,vb=self.mean_inputs()
        with self.assertRaisesRegex(ValueError,"eligible"): self.compare.compare_means(dataset=self.imported.dataset_version,codebook=self.imported.codebook,specification=pii,group_a_result=ma,group_b_result=mb,view_a=va,view_b=vb)
    def test_no_desk_or_external_dependency(self):
        import application.quantitative.comparison_statistics as module
        source=inspect.getsource(module)
        for forbidden in ("InformationNeed","EvidenceExpectation","domain.sources","openai","tavily","llm_client"): self.assertNotIn(forbidden,source)


if __name__=="__main__": unittest.main()
