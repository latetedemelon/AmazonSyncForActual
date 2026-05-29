from datetime import date

from amazon_sync_for_actual.config import Config, load_config


def _write(tmp_path, text):
    p = tmp_path / "config.ini"
    p.write_text(text, encoding="utf-8")
    return str(p)


def test_legacy_default_keys(tmp_path):
    path = _write(
        tmp_path,
        "[DEFAULT]\n"
        "actualBaseUrl = https://example.com\n"
        "actualToken = tok\n"
        "otpSecret = sek\n"
        "userEmail = me@x.com\n"
        "userPassword = pw\n",
    )
    cfg = load_config(path)
    assert cfg.actual_url == "https://example.com"
    assert cfg.actual_token == "tok"
    assert cfg.amazon_otp_secret == "sek"
    assert cfg.amazon_email == "me@x.com"
    assert cfg.amazon_password == "pw"


def test_modern_sections(tmp_path):
    path = _write(
        tmp_path,
        "[actual]\nurl = http://localhost:5006\npassword = pw\nfile = My Budget\n"
        "[amazon]\nsource = csv\ncsv_path = /tmp/x.csv\n"
        "[matching]\ndays = 45\nstart_date = 2024-01-01\n"
        "[memo]\nmode = append\ninclude_quantity = false\nseparator = ||\n",
    )
    cfg = load_config(path)
    assert cfg.actual_url == "http://localhost:5006"
    assert cfg.actual_file == "My Budget"
    assert cfg.days == 45
    assert cfg.start_date == date(2024, 1, 1)
    assert cfg.note_mode == "append"
    assert cfg.include_quantity is False
    assert cfg.separator == "||"


def test_precedence_env_over_ini_and_override_over_env(tmp_path, monkeypatch):
    path = _write(tmp_path, "[matching]\ndays = 60\n")
    monkeypatch.setenv("ASFA_DAYS", "30")
    assert load_config(path).days == 30
    assert load_config(path, {"days": 10}).days == 10


def test_override_none_is_ignored(tmp_path):
    path = _write(tmp_path, "[matching]\ndays = 60\n")
    assert load_config(path, {"days": None}).days == 60


def test_validate_problems():
    assert any("csv" in p for p in Config(source="csv", csv_path=None).validate())
    assert any("note_mode" in p for p in Config(note_mode="bogus", csv_path="x").validate())


def test_memo_options_roundtrip():
    cfg = Config(max_words_per_item=3, separator=" / ", note_prefix="P:", max_items=2)
    opts = cfg.memo_options()
    assert opts.max_words_per_item == 3
    assert opts.separator == " / "
    assert opts.prefix == "P:"
    assert opts.max_items == 2
