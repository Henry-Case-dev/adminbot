"""Tests for tools/cookies_export.py (T-584, Epic 79, Section 80, D293/D294).

Конвертер Playwright→Netscape (табы, session=0, dot-domain→TRUE, заголовок),
chmod 600 после записи, CLI argparse/ошибки, режим A — команда subprocess
(мок). Сеть НЕ трогается: playwright-путь тестируется через конвертер.
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from tools import cookies_export as ce


def _cookie(domain=".youtube.com", path="/", secure=True,
            expires=1756000000, name="PREF", value="v1"):
    return {
        "domain": domain,
        "path": path,
        "secure": secure,
        "expires": expires,
        "name": name,
        "value": value,
    }


class TestNetscapeConverter:
    def test_seven_tab_fields(self):
        """80.2 #1: ровно 7 таб-полей в строке."""
        line = ce.cookie_to_netscape(_cookie())
        fields = line.split("\t")
        assert len(fields) == 7
        assert line.split("\t") == [
            ".youtube.com", "TRUE", "/", "TRUE", "1756000000", "PREF", "v1",
        ]

    def test_session_cookie_expires_zero(self):
        """80.2 #2: expires=-1 (session) → поле `0`."""
        line = ce.cookie_to_netscape(_cookie(expires=-1))
        assert line.split("\t")[4] == "0"

    def test_dot_domain_true(self):
        """80.2 #1: domain с ведущей точкой → include_subdomains TRUE."""
        assert ce.cookie_to_netscape(
            _cookie(domain=".youtube.com")).split("\t")[1] == "TRUE"

    def test_no_dot_domain_false(self):
        """80.2 #3: domain без ведущей точки → include_subdomains FALSE."""
        line = ce.cookie_to_netscape(_cookie(domain="youtube.com"))
        assert line.split("\t")[1] == "FALSE"

    def test_secure_flag_false(self):
        line = ce.cookie_to_netscape(_cookie(secure=False))
        assert line.split("\t")[3] == "FALSE"

    def test_header_first_line(self):
        """80.2 #4: первая строка файла — заголовок Netscape."""
        lines = ce.convert_cookies([_cookie(), _cookie(name="SID")])
        assert lines[0] == "# Netscape HTTP Cookie File"
        assert len(lines) == 3
        for line in lines[1:]:
            assert len(line.split("\t")) == 7

    def test_empty_cookies_only_header(self):
        assert ce.convert_cookies([]) == ["# Netscape HTTP Cookie File"]


class TestWriteOut:
    def test_chmod_600_after_write(self, tmp_path, monkeypatch):
        """80.2 #5: chmod(out, 0o600) вызван; запись не падает на Windows."""
        out = str(tmp_path / "cookies.txt")
        calls = []
        monkeypatch.setattr(ce.os, "chmod", lambda p, m: calls.append((p, m)))
        ce._write_out(out, [_cookie()])
        assert calls and calls[0][1] == 0o600
        with open(out, encoding="utf-8") as f:
            first_line = f.readline().strip()
        assert first_line == "# Netscape HTTP Cookie File"

    def test_real_write_and_chmod_no_crash(self, tmp_path):
        """На CI/Windows chmod но-op — но не падает."""
        out = str(tmp_path / "cookies.txt")
        ce._write_out(out, [_cookie(expires=-1)])
        content = open(out, encoding="utf-8").read()
        assert "\t0\t" in content.splitlines()[1]


class TestCli:
    def test_missing_required_args_exit_2(self, capsys):
        """80.2 #6: без обязательных --profile/--out → exit 2."""
        with pytest.raises(SystemExit) as exc:
            ce.main([])
        assert exc.value.code == 2

    def test_invalid_mode_exit_2(self, capsys):
        """80.2 #6: неверный mode → exit 2 (argparse choices)."""
        with pytest.raises(SystemExit) as exc:
            ce.main(["--mode", "a", "--profile", "p", "--out", "o"])
        assert exc.value.code == 2

    def test_profile_not_found_error(self, tmp_path, capsys):
        rc = ce.main(["--mode", "playwright", "--profile",
                      str(tmp_path / "nope"), "--out", "x.txt"])
        assert rc == 2
        assert "not found" in capsys.readouterr().err

    def test_default_mode_is_playwright(self, tmp_path):
        """Дефолт --mode = playwright (режим B основной, D293)."""
        profile = str(tmp_path / "prof")
        os.makedirs(profile)
        out = str(tmp_path / "out" / "cookies.txt")
        with patch.object(ce, "export_playwright", return_value=0) as mock_b:
            rc = ce.main(["--profile", profile, "--out", out])
        assert rc == 0
        mock_b.assert_called_once_with(profile, out)

    def test_mode_browser_dispatches_to_export_browser(self, monkeypatch):
        monkeypatch.setattr("os.path.isdir", lambda p: True)
        with patch.object(ce, "export_browser", return_value=0) as mock_a:
            rc = ce.main(["--mode", "browser", "--profile", "p", "--out", "o"])
        assert rc == 0
        mock_a.assert_called_once_with(os.path.abspath("p"), "o")


class TestModeACommand:
    def test_command_shape(self):
        """Режим A: корректная команда subprocess yt_dlp."""
        cmd = ce.build_mode_a_command("/abs/profile", "/tmp/out.txt")
        assert cmd[1:3] == ["-m", "yt_dlp"]
        assert "--cookies-from-browser" in cmd
        assert cmd[cmd.index("--cookies-from-browser") + 1] == \
            "chrome:/abs/profile"
        assert "--cookies" in cmd
        assert cmd[cmd.index("--cookies") + 1] == "/tmp/out.txt"
        assert "--skip-download" in cmd
        assert cmd[-1] == ce.YOUTUBE_ROBOTS_URL

    def test_export_browser_success_validates_file(self, tmp_path):
        out = str(tmp_path / "c.txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write("# Netscape HTTP Cookie File\n"
                    ".youtube.com\tTRUE\t/\tTRUE\t123\tSID\tx\n")

        proc = MagicMock(returncode=0)

        def fake_run(cmd, **kwargs):
            assert "-m" in cmd and "yt_dlp" in cmd
            return proc

        with patch.object(ce.subprocess, "run", side_effect=fake_run):
            rc = ce.export_browser("prof", out)
        assert rc == 0

    def test_export_browser_bad_file_suggests_playwright(self, tmp_path,
                                                         caplog):
        """80.2 #7: пустой/битый файл → exit ≠ 0 + подсказка --mode playwright."""
        out = str(tmp_path / "empty.txt")
        open(out, "w").close()   # только мусор без youtube/google-строк
        with open(out, "w", encoding="utf-8") as f:
            f.write("# only comment\n")
        with patch.object(ce.subprocess, "run",
                          return_value=MagicMock(returncode=0)):
            with caplog.at_level("ERROR"):
                rc = ce.export_browser("prof", out)
        assert rc != 0
        assert any("--mode playwright" in r.message for r in caplog.records)

    def test_export_browser_nonzero_rc_fails(self, tmp_path):
        out = str(tmp_path / "c.txt")
        with patch.object(ce.subprocess, "run",
                          return_value=MagicMock(returncode=1)):
            rc = ce.export_browser("prof", out)
        assert rc == 4

    def test_export_browser_missing_ytdlp(self):
        with patch.object(ce.subprocess, "run",
                          side_effect=FileNotFoundError()):
            rc = ce.export_browser("prof", "o.txt")
        assert rc == 2

    def test_export_browser_timeout(self):
        import subprocess as sp
        with patch.object(ce.subprocess, "run",
                          side_effect=sp.TimeoutExpired(cmd="x", timeout=1)):
            rc = ce.export_browser("prof", "o.txt")
        assert rc != 0


class TestValidateFile:
    def test_missing_file_invalid(self, tmp_path):
        assert not ce._validate_netscape_file(str(tmp_path / "nope.txt"))

    def test_google_domain_also_valid(self, tmp_path):
        out = str(tmp_path / "c.txt")
        with open(out, "w", encoding="utf-8") as f:
            f.write(".google.com\tTRUE\t/\tTRUE\t123\tNID\tx\n")
        assert ce._validate_netscape_file(out)
