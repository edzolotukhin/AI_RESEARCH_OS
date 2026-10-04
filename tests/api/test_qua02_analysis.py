from tests.api.helpers import ApiTestCase


class Qua02AnalysisTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.owner=self.container.authentication_service.authenticate_api_key(
            self.container._test_api_key_plaintext).principal_id
        self.project=self.container.project_service.create_project(
            "Qual thematic acceptance",owner_principal_id=self.owner,selected_methods=("QUALITATIVE",))
        self.run=self.client.post(f"/projects/{self.project.id}/qualitative/runs").json()["run_id"]

    def transcript(self,pseudonym,text):
        participant=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/participants",
            json={"pseudonym":pseudonym}).json()["participant_id"]
        self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/consents",json={
            "participant_id":participant,"state":"eligible","context":"attested","researcher_attested":True})
        session=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/sessions",json={
            "participant_id":participant,"context":"IDI"}).json()["session_id"]
        uploaded=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/sessions/{session}/artifacts",
            files={"artifact":(f"{pseudonym}.txt",f"{pseudonym}: {text}".encode(),"text/plain")}).json()
        return uploaded["result_id"]

    def test_multi_interview_manual_and_ai_analysis_reaches_ready_for_findings(self):
        t1=self.transcript("P01","Charging at home is convenient")
        t2=self.transcript("P02","Public charging is unreliable")
        t3=self.transcript("P03","I prefer petrol for long trips")
        corpus=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/corpora",json={
            "transcript_ids":[t1,t2,t3],"instructions":"Hybrid thematic analysis"}).json()
        self.assertEqual(len(corpus["members"]),3)
        codebook=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/codebooks",json={"codes":[
            {"code_id":"ease","label":"Convenience","definition":"Convenient charging","origin":"human"},
            {"code_id":"barrier","label":"Charging barrier","definition":"Charging concerns","origin":"ai_proposed"},
            {"code_id":"deviant","label":"ICE preference","definition":"Contrasting preference","origin":"human"}
        ],"status":"accepted"}).json()
        records=self.client.get(f"/projects/{self.project.id}/qualitative/{self.run}").json()["records"]
        transcripts={x["id"]:x["payload"] for x in records if x["type"]=="transcript"}
        codes=[("a1","ease",t1),("a2","barrier",t2),("a3","deviant",t3)]
        applications=[]
        for app_id,code_id,transcript_id in codes:
            segment=transcripts[transcript_id]["segments"][0]
            applications.append({"application_id":app_id,"code_id":code_id,"transcript_version_id":transcript_id,
                "transcript_checksum":transcripts[transcript_id]["checksum"],"segment_id":segment["segment_id"],
                "start":0,"end":len(segment["text"]),"origin":"human","review_state":"accepted"})
        coding=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/codings",json={
            "corpus_id":corpus["corpus_id"],"codebook_id":codebook["codebook_revision_id"],
            "applications":applications,"status":"accepted"}).json()
        proposal={"corpus_id":corpus["corpus_id"],"codebook_id":codebook["codebook_revision_id"],"batch_key":"batch-1",
            "payload":{"applications":[{**applications[1],"application_id":"ai-a2","origin":"ai_proposed","review_state":"proposed"}],
            "themes":[{"title":"Charging experience","description":"Corpus interpretation","supporting_application_ids":["ai-a2"]}]}}
        first=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/ai-proposals",json=proposal).json()
        second=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/ai-proposals",json=proposal).json()
        self.assertEqual(first["proposal_id"],second["proposal_id"])
        review=self.client.post(f"/projects/{self.project.id}/qualitative/analysis/ai-proposals/{first['proposal_id']}/review",
            json={"decision":"accepted"})
        self.assertEqual(review.status_code,200)
        thematic=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/themes",json={
            "coding_id":coding["coding_revision_id"],"categories":[{"category_id":"experience","title":"Experience","code_ids":["ease","barrier","deviant"]}],
            "themes":[{"theme_id":"theme-1","title":"Charging shapes adoption","description":"Different corpus experiences",
                "code_ids":["ease","barrier","deviant"],"category_ids":["experience"],
                "supporting_application_ids":["a1","a2"],"contradictory_application_ids":["a3"],"origin":"human"}],
            "status":"accepted"}).json()
        theme=thematic["themes"][0]
        self.assertEqual((theme["participant_count"],theme["session_count"],theme["span_count"]),(3,3,3))
        ready=self.client.get(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/readiness").json()
        self.assertEqual(ready["readiness"],"ready_for_findings")

    def test_closed_world_and_immutable_pins_fail_closed(self):
        transcript_id=self.transcript("P01","Canonical words")
        corpus=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/corpora",json={"transcript_ids":[transcript_id]}).json()
        codebook=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/codebooks",json={
            "codes":[{"code_id":"c1","label":"Code","definition":"Definition"}],"status":"accepted"}).json()
        invalid=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/codings",json={
            "corpus_id":corpus["corpus_id"],"codebook_id":codebook["codebook_revision_id"],"applications":[{
                "code_id":"c1","transcript_version_id":transcript_id,"transcript_checksum":"stale",
                "segment_id":"segment-0001","start":0,"end":4}]})
        self.assertEqual(invalid.status_code,422)
        bad_theme=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/ai-proposals",json={
            "corpus_id":corpus["corpus_id"],"codebook_id":codebook["codebook_revision_id"],"batch_key":"bad",
            "payload":{"themes":[{"description":"67% of customers believe this","supporting_application_ids":["missing"]}]}})
        self.assertEqual(bad_theme.status_code,422)

    def test_withdrawn_consent_cannot_enter_new_corpus(self):
        transcript_id=self.transcript("P01","Initially eligible")
        records=self.client.get(f"/projects/{self.project.id}/qualitative/{self.run}").json()["records"]
        participant=next(x for x in records if x["type"]=="participant")
        self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/consents",json={
            "participant_id":participant["id"],"state":"withdrawn","context":"withdrawn"})
        response=self.client.post(f"/projects/{self.project.id}/qualitative/{self.run}/analysis/corpora",json={"transcript_ids":[transcript_id]})
        self.assertEqual(response.status_code,422)
