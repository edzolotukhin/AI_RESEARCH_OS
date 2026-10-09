from pathlib import Path


TEMPLATE = Path("api/templates/projects/design.html")


def test_design_review_exposes_subject_block_and_safe_approval_gate():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "Предмет дослідження" in text
    assert "subject.lexical_representations" in text
    assert "subject.supporting_relations" in text
    assert "(not view.desk) or (subject and subject.resolution_status.value != 'unresolved')" in text


def test_legacy_subjectless_design_is_explained_not_silently_approved():
    text = TEMPLATE.read_text(encoding="utf-8")
    assert "застарілий дизайн без зафіксованого предмета" in text
    assert "сформуйте нову ревізію" in text
