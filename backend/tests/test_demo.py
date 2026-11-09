from leavedesk.demo import main


def test_demo_runs_and_every_edge_case_passes(capsys):
    assert main([]) == 0

    output = capsys.readouterr().out
    assert "FAIL" not in output
    assert output.count("PASS") == 5
    assert "all 5 edge cases raised the right exception" in output
