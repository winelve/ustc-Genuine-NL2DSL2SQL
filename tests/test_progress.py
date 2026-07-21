"""Tests for the shared single-line progress bar."""

from archer_eval.progress import Progress


def test_bar_renders_and_ends_with_newline(capsys):
    bar = Progress(3, "generate")
    for _ in range(3):
        bar.step()
    out = capsys.readouterr().out
    assert "generate" in out
    assert "3/3" in out
    assert out.endswith("\n")  # 走完自动换行，不吃掉后续输出


def test_write_keeps_messages_on_their_own_line(capsys):
    bar = Progress(2, "generate")
    bar.step()
    bar.write("  sample 0 failed: boom")
    bar.step()
    out = capsys.readouterr().out
    assert "sample 0 failed: boom" in out
    assert "2/2" in out


def test_disabled_bar_is_silent(capsys):
    bar = Progress(5, "generate", enabled=False)
    for _ in range(5):
        bar.step()
    assert capsys.readouterr().out == ""
