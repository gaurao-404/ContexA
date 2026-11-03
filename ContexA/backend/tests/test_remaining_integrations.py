from __future__ import annotations


def test_smtp_starttls_delivery_uses_encrypted_connection(monkeypatch):
    import app.main as main_module

    calls = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            calls.append(("connect", host, port, timeout))
        def __enter__(self): return self
        def __exit__(self, *args): calls.append(("close",))
        def ehlo(self): calls.append(("ehlo",))
        def has_extn(self, name): return name == "starttls"
        def starttls(self): calls.append(("starttls",))
        def login(self, username, password): calls.append(("login", username, password))
        def send_message(self, message): calls.append(("send", message["To"], message["Subject"]))

    monkeypatch.setattr(main_module.smtplib, "SMTP", FakeSMTP)
    monkeypatch.setattr(main_module, "APP_ENV", "test")
    monkeypatch.setattr(main_module, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(main_module, "SMTP_PORT", 587)
    monkeypatch.setattr(main_module, "SMTP_USERNAME", "contexa")
    monkeypatch.setattr(main_module, "SMTP_PASSWORD", "not-logged")
    monkeypatch.setattr(main_module, "SMTP_FROM_EMAIL", "no-reply@example.test")
    monkeypatch.setattr(main_module, "SMTP_FROM_NAME", "ContexA")
    monkeypatch.setattr(main_module, "SMTP_USE_TLS", True)
    monkeypatch.setattr(main_module, "SMTP_USE_SSL", False)
    monkeypatch.setattr(main_module, "PUBLIC_APP_URL", "https://contexa.example.test")

    result = main_module._send_account_link("person@example.test", "Verify account", "verify-email", "one-time-token")
    assert result is None
    assert ("starttls",) in calls
    assert ("login", "contexa", "not-logged") in calls
    assert ("send", "person@example.test", "Verify account") in calls


def test_smtp_implicit_ssl_delivery_uses_ssl_transport(monkeypatch):
    import app.main as main_module

    calls = []

    class FakeSMTPSSL:
        def __init__(self, host, port, timeout):
            calls.append(("connect-ssl", host, port, timeout))
        def __enter__(self): return self
        def __exit__(self, *args): calls.append(("close",))
        def login(self, username, password): calls.append(("login", username, password))
        def send_message(self, message): calls.append(("send", message["To"]))

    monkeypatch.setattr(main_module.smtplib, "SMTP_SSL", FakeSMTPSSL)
    monkeypatch.setattr(main_module, "APP_ENV", "test")
    monkeypatch.setattr(main_module, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(main_module, "SMTP_PORT", 465)
    monkeypatch.setattr(main_module, "SMTP_USERNAME", "contexa")
    monkeypatch.setattr(main_module, "SMTP_PASSWORD", "not-logged")
    monkeypatch.setattr(main_module, "SMTP_FROM_EMAIL", "no-reply@example.test")
    monkeypatch.setattr(main_module, "SMTP_FROM_NAME", "ContexA")
    monkeypatch.setattr(main_module, "SMTP_USE_TLS", False)
    monkeypatch.setattr(main_module, "SMTP_USE_SSL", True)

    result = main_module._send_account_link("person@example.test", "Reset account", "password-reset", "one-time-token")
    assert result is None
    assert ("connect-ssl", "smtp.example.test", 465, 12) in calls
    assert ("send", "person@example.test") in calls
