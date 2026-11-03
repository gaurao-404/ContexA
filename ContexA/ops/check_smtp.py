#!/usr/bin/env python3
"""Verify SMTP configuration without printing credentials; optionally send a test email."""
from __future__ import annotations

import argparse
import os
import smtplib
import ssl
from email.message import EmailMessage


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--to", help="Optional recipient; sends a real test message when supplied")
    args = parser.parse_args()

    host = os.getenv("SMTP_HOST", "").strip()
    port = int(os.getenv("SMTP_PORT", "587"))
    username = os.getenv("SMTP_USERNAME", "")
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM_EMAIL", "").strip()
    sender_name = os.getenv("SMTP_FROM_NAME", "ContexA Studio")
    use_ssl = os.getenv("SMTP_USE_SSL", "false").lower() in {"1", "true", "yes"}
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}

    if not host or not sender:
        parser.error("SMTP_HOST and SMTP_FROM_EMAIL must be configured")
    if bool(username) != bool(password):
        parser.error("Set both SMTP_USERNAME and SMTP_PASSWORD, or neither")
    if use_ssl and use_tls:
        parser.error("Choose SMTP_USE_SSL=true or SMTP_USE_TLS=true, not both")
    if not use_ssl and not use_tls:
        parser.error("Refusing to test plaintext SMTP; enable TLS or SSL")

    context = ssl.create_default_context()
    if use_ssl:
        server = smtplib.SMTP_SSL(host, port, timeout=15, context=context)
    else:
        server = smtplib.SMTP(host, port, timeout=15)

    with server:
        server.ehlo()
        if use_tls:
            if not server.has_extn("starttls"):
                raise RuntimeError("SMTP server does not advertise STARTTLS")
            server.starttls(context=context)
            server.ehlo()
        if username:
            server.login(username, password)
        print(f"SMTP connection and security negotiation passed: {host}:{port}")
        if args.to:
            message = EmailMessage()
            message["Subject"] = "ContexA SMTP delivery test"
            message["From"] = f"{sender_name} <{sender}>"
            message["To"] = args.to
            message.set_content("This is a configuration test from ContexA. No action is required.")
            server.send_message(message)
            print(f"Test message submitted to SMTP relay for: {args.to}")
        else:
            print("No email was sent. Re-run with --to recipient@example.com to test delivery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
