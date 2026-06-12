'''Tests for run_pipeline.py — stage selection and the human approval gate.'''
import run_pipeline
from run_pipeline import parse_args, stage_selection


def test_default_selects_all_stages():
    stages = stage_selection(parse_args([]))
    assert all(stages.values())


def test_single_only_flag_selects_one_stage():
    stages = stage_selection(parse_args(['--extract-only']))
    assert stages == {'seed': False, 'discover': False, 'extract': True,
                      'load': False, 'eval': False}


def test_multiple_only_flags_select_both_not_neither():
    stages = stage_selection(parse_args(['--load-only', '--eval-only']))
    assert stages['load'] and stages['eval']
    assert not stages['extract']


def test_extract_refuses_without_frozen_schema(tmp_path, capsys):
    missing = tmp_path / 'schema' / 'v001.yaml'
    rc = run_pipeline.run(['--extract-only', '--schema', str(missing)])
    assert rc == 2
    err = capsys.readouterr().err
    assert 'frozen schema' in err
    assert 'drafts/v001-draft.yaml' in err


def test_gate_is_soft_when_earlier_stages_ran(tmp_path, capsys):
    # seed runs, then the gate stops the run without an error exit code.
    missing = tmp_path / 'schema' / 'v001.yaml'
    rc = run_pipeline.run(['--seed-only', '--extract-only',
                           '--schema', str(missing)])
    assert rc == 0
    assert 'Approve the draft first' in capsys.readouterr().err
