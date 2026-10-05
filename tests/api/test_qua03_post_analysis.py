from tests.api.helpers import ApiTestCase
from infrastructure.qualitative.analysis_provider import DeterministicQualitativeAnalysisProvider


class Qua03PostAnalysisTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.owner=self.container.authentication_service.authenticate_api_key(self.container._test_api_key_plaintext).principal_id
        self.project=self.container.project_service.create_project("QUA-03",owner_principal_id=self.owner,selected_methods=("QUALITATIVE",))
        self.run=self.client.post(f"/projects/{self.project.id}/qualitative/runs").json()["run_id"]
        transcripts=[]
        for pseudonym,text in (("P01","Setup guidance was confusing"),("P02","Peer advice felt more trustworthy"),("P03","Automation saved time but reduced control")):
            participant=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/participants",json={"pseudonym":pseudonym}).json()["participant_id"]
            self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/consents",json={"participant_id":participant,"state":"eligible","context":"attested","researcher_attested":True})
            session=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/sessions",json={"participant_id":participant}).json()["session_id"]
            transcripts.append(self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/sessions/{session}/artifacts",
                files={"artifact":(f"{pseudonym}.txt",f"{pseudonym}: {text}".encode(),"text/plain")}).json()["result_id"])
        corpus=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/corpora",json={"transcript_ids":transcripts}).json()
        codebook=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/codebooks",json={"codes":[
            {"code_id":"guidance","label":"Guidance","definition":"Guidance experience"},
            {"code_id":"trust","label":"Trust","definition":"Trust in advice"},
            {"code_id":"control","label":"Control","definition":"Automation tension"}],"status":"accepted"}).json()
        detail=self.client.get(f"/projects/{self.project.id}/qualitative/{self.run}").json()["records"]
        by_id={x["id"]:x["payload"] for x in detail if x["type"]=="transcript"}; apps=[]
        for i,(transcript_id,code_id) in enumerate(zip(transcripts,("guidance","trust","control")),1):
            segment=by_id[transcript_id]["segments"][0]
            apps.append({"application_id":f"a{i}","code_id":code_id,"transcript_version_id":transcript_id,
                "transcript_checksum":by_id[transcript_id]["checksum"],"segment_id":segment["segment_id"],
                "start":0,"end":len(segment["text"])})
        coding=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/codings",json={
            "corpus_id":corpus["corpus_id"],"codebook_id":codebook["codebook_revision_id"],"applications":apps}).json()
        self.thematic=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/themes",json={
            "coding_id":coding["coding_revision_id"],"categories":[],"themes":[
                {"theme_id":"onboarding","title":"Guidance and trust","description":"Participants contrasted official and peer guidance",
                 "code_ids":["guidance","trust"],"category_ids":[],"supporting_application_ids":["a1","a2"],"contradictory_application_ids":[]},
                {"theme_id":"automation","title":"Automation tension","description":"Time savings coexisted with reduced control",
                 "code_ids":["control"],"category_ids":[],"supporting_application_ids":["a3"],"contradictory_application_ids":["a3"]}],"status":"accepted"}).json()

    def finding(self,title,theme_ids,status="accepted"):
        return self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/findings",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":title,
            "statement":f"A recurring pattern in the interview corpus was {title.lower()}.",
            "explanation":"The accepted Themes preserve supporting and deviant evidence.","theme_ids":theme_ids,"status":status}).json()

    def test_manual_findings_insight_review_changes_and_approval(self):
        f1=self.finding("Guidance trust",["onboarding"]); f2=self.finding("Automation tension",["automation"])
        insight=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/insights",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":"Interpretation gap",
            "statement":"The Findings indicate a tension between convenience and trusted interpretation.",
            "implication":"Guidance should preserve user agency.","finding_ids":[f1["finding_id"],f2["finding_id"]],"status":"accepted"}).json()
        revision=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions",json={
            "thematic_id":self.thematic["thematic_revision_id"],"finding_ids":[f1["finding_id"],f2["finding_id"]],
            "insight_ids":[insight["insight_id"]]}).json()
        changes=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions/{revision['revision_id']}/review",
            json={"decision":"changes_required","comments":"Clarify the tension"}).json()
        self.assertIsNone(changes["approved_revision"])
        blocked=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions/{revision['revision_id']}/review",
            json={"decision":"approved","comments":"Unchanged"})
        self.assertEqual(blocked.status_code,422)
        revised_f1=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/findings",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":"Guidance trust clarified",
            "statement":"Several participants described a guidance trust gap.",
            "explanation":"The successor preserves exact accepted Theme authority.","theme_ids":["onboarding"],
            "status":"accepted","parent_id":f1["finding_id"]}).json()
        revised_insight=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/insights",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":"Interpretation gap clarified",
            "statement":"The accepted Findings preserve both guidance and automation tension.",
            "implication":"Guidance should preserve user agency.","finding_ids":[revised_f1["finding_id"],f2["finding_id"]],
            "status":"accepted","parent_id":insight["insight_id"]}).json()
        successor=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions",json={
            "thematic_id":self.thematic["thematic_revision_id"],"finding_ids":[revised_f1["finding_id"],f2["finding_id"]],
            "insight_ids":[revised_insight["insight_id"]],"parent_id":revision["revision_id"]}).json()
        approved=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions/{successor['revision_id']}/review",
            json={"decision":"approved","comments":"Grounded and approved"}).json()
        self.assertEqual(approved["readiness"],"ready_for_deliverables")
        self.assertEqual(approved["approved_revision"]["finding_ids"],[revised_f1["finding_id"],f2["finding_id"]])
        replay=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/revisions/{successor['revision_id']}/review",
            json={"decision":"approved"}).json()
        self.assertEqual(replay["approved_revision"]["approved_revision_id"],approved["approved_revision"]["approved_revision_id"])
        outputs=self.client.get(f"/ui/projects/{self.project.id}/outputs")
        for marker in ("Прийняті якісні висновки","Прийняті якісні інсайти","Затверджена якісна версія"):
            self.assertIn(marker,outputs.text)

    def test_deterministic_ai_finding_and_insight_proposals_canonicalize_once(self):
        service=self.container.qualitative_post_analysis_service
        service.provider=DeterministicQualitativeAnalysisProvider({"finding-batch":{"findings":[{
            "title":"Guidance trust","statement":"Participants frequently described a guidance trust gap.",
            "explanation":"Accepted Theme evidence supports this pattern.","theme_ids":["onboarding"]}]}})
        self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/ai-jobs",json={
            "thematic_id":self.thematic["thematic_revision_id"],"batch_key":"finding-batch","kind":"finding"})
        self.assertTrue(service.process_next_job())
        proposal=service._records(self.project.id,self.run,"qualitative_post_analysis_proposal")[0]
        accepted=self.client.post(f"/projects/{self.project.id}/qualitative/post-analysis/ai-proposals/{proposal.record_id}/review",
            json={"decision":"accepted"}).json()
        replay=self.client.post(f"/projects/{self.project.id}/qualitative/post-analysis/ai-proposals/{proposal.record_id}/review",
            json={"decision":"accepted"}).json()
        self.assertEqual(accepted["canonical_ids"],replay["canonical_ids"])
        finding_id=accepted["canonical_ids"][0]
        service.provider=DeterministicQualitativeAnalysisProvider({"insight-batch":{"insights":[{
            "title":"Trust implication","statement":"The accepted Finding indicates an interpretation gap.",
            "implication":"Improve official guidance credibility.","finding_ids":[finding_id]}]}})
        self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/ai-jobs",json={
            "thematic_id":self.thematic["thematic_revision_id"],"batch_key":"insight-batch","kind":"insight","finding_ids":[finding_id]})
        self.assertTrue(service.process_next_job())
        proposal=next(x for x in service._records(self.project.id,self.run,"qualitative_post_analysis_proposal") if x.payload["kind"]=="insight")
        accepted=self.client.post(f"/projects/{self.project.id}/qualitative/post-analysis/ai-proposals/{proposal.record_id}/review",
            json={"decision":"accepted"}).json()
        self.assertEqual(service._get(self.project.id,accepted["canonical_ids"][0]).payload["finding_ids"],[finding_id])

    def test_adversarial_authority_and_language_fail_closed(self):
        no_theme=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/findings",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":"Unsupported","statement":"This proves the market believes it",
            "explanation":"Unsupported","theme_ids":[],"status":"accepted"})
        self.assertEqual(no_theme.status_code,422)
        draft=self.finding("Draft",["onboarding"],status="draft")
        insight=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/insights",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":"Bad","statement":"Unsupported synthesis",
            "implication":"None","finding_ids":[draft["finding_id"]],"status":"accepted"})
        self.assertEqual(insight.status_code,422)
        missing_theme=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/findings",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":"Foreign","statement":"A recurring pattern was observed.",
            "explanation":"Unsupported Theme reference.","theme_ids":["does-not-exist"],"status":"accepted"})
        self.assertEqual(missing_theme.status_code,422)
        zero=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/insights",json={
            "thematic_id":self.thematic["thematic_revision_id"],"title":"Empty","statement":"No authority.",
            "implication":"None","finding_ids":[],"status":"accepted"})
        self.assertEqual(zero.status_code,422)
        service=self.container.qualitative_post_analysis_service
        service.provider=DeterministicQualitativeAnalysisProvider({"bad-theme":{"findings":[{
            "title":"Bad","statement":"A recurring pattern was observed.","explanation":"Unsupported.",
            "theme_ids":["does-not-exist"]}]}})
        self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/post-analysis/ai-jobs",json={
            "thematic_id":self.thematic["thematic_revision_id"],"batch_key":"bad-theme","kind":"finding"})
        with self.assertRaises(ValueError): service.process_next_job()

    def test_browser_exposes_post_analysis_workspaces(self):
        response=self.client.get(f"/ui/projects/{self.project.id}/qualitative/{self.run}")
        for marker in ("Findings workspace","Insights workspace","Revision / Review","Supporting evidence","Deviant evidence"):
            self.assertIn(marker,response.text)
