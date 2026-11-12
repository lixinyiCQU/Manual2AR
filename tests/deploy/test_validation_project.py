"""A mistyped validation path must never delete a colleague's Unity project."""
import pytest
from tools.build.validate_desktop import claim_project


def test_unowned_unity_project_is_untouched(tmp_path):
    source = tmp_path/'source'; source.mkdir()
    project = tmp_path/'colleague'; asset = project/'Assets'/'untracked.txt'
    asset.parent.mkdir(parents=True); asset.write_text('irreplaceable')
    with pytest.raises(ValueError, match='unowned'):
        claim_project(project, source)
    assert asset.read_text() == 'irreplaceable'
    assert not (project/'.manual2ar-validation.json').exists()


def test_private_validation_project_can_only_be_reused_by_its_owner(tmp_path):
    source = tmp_path/'source'; source.mkdir()
    project = claim_project(tmp_path/'validation', source)
    (project/'Assets').mkdir()
    assert claim_project(project, source) == project
    with pytest.raises(ValueError, match='unowned'):
        claim_project(project, tmp_path/'other-source')


def test_source_and_linked_targets_are_rejected(tmp_path):
    source = tmp_path/'source'; source.mkdir()
    with pytest.raises(ValueError, match='outside'):
        claim_project(source/'validation', source)
    link = tmp_path/'link'; link.symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        claim_project(link, source)
    project = claim_project(tmp_path/'validation', source)
    (project/'Assets').symlink_to(source, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        claim_project(project, source)
