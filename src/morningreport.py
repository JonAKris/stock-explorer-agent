#!/usr/bin/env python3
"""
morning_report.py — Build the overnight stock-research report and email it.

Mirrors the old morning-review bash script:
  * finds the newest findings/report_*.md
  * finds the newest findings/results_*.json and summarises it
  * converts the combined Markdown to HTML with pypandoc
  * emails the HTML (with a plain-text fallback) to a recipient list

Configuration is read from environment variables. A .env file in the working
directory is loaded automatically if python-dotenv is installed.

  FINDINGS_DIR   directory holding report_*.md / results_*.json
                 (default: ~/stock-explorer-agent/findings)
  SMTP_HOST      SMTP server hostname              (required to send)
  SMTP_PORT      SMTP server port                  (default: 587)
  SMTP_USER      SMTP username                     (optional)
  SMTP_PASSWORD  SMTP password / app password      (optional)
  SMTP_SECURITY  "starttls" | "ssl" | "none"       (default: starttls)
  MAIL_FROM      From: address                     (default: SMTP_USER)
  MAIL_TO        comma-separated recipient list    (or pass --to)

Usage:
  python morning_report.py                       # find, build, email
  python morning_report.py --to a@x.com,b@y.com  # override recipient list
  python morning_report.py --no-email            # just print to stdout
  python morning_report.py --out report.html     # also save the HTML

Dependencies:
  pip install pypandoc-binary python-dotenv
  (pypandoc-binary bundles the pandoc executable; plain pypandoc needs pandoc
   installed separately, in which case this script will fetch it on first run.)
"""

from __future__ import annotations

import argparse
import json
import logging
import smtplib
import sys
from dataclasses import dataclass, field
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import os

log = logging.getLogger("morning_report")


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass
class MailConfig:
    host: str | None
    port: int
    user: str | None
    password: str | None
    security: str
    mail_from: str
    recipients: list[str] = field(default_factory=list)

    @classmethod
    def from_env(cls, recipients_override: list[str] | None = None) -> "MailConfig":
        user = os.environ.get("SMTP_USER")
        recipients = recipients_override or _split_csv(os.environ.get("MAIL_TO", ""))
        return cls(
            host=os.environ.get("SMTP_HOST"),
            port=int(os.environ.get("SMTP_PORT", "587")),
            user=user,
            password=os.environ.get("SMTP_PASSWORD"),
            security=os.environ.get("SMTP_SECURITY", "starttls").lower(),
            mail_from=os.environ.get("MAIL_FROM") or user or "stock-agent@localhost",
            recipients=recipients,
        )

    def validate(self) -> None:
        if not self.host:
            raise SystemExit("SMTP_HOST is not set — cannot send email.")
        if not self.recipients:
            raise SystemExit("No recipients — set MAIL_TO or pass --to.")
        if self.security not in {"starttls", "ssl", "none"}:
            raise SystemExit(f"Invalid SMTP_SECURITY: {self.security!r}")


def _split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def findings_dir() -> Path:
    return Path(
        os.environ.get("FINDINGS_DIR", "~/stock-explorer-agent/findings")
    ).expanduser()


# --------------------------------------------------------------------------- #
# Report building
# --------------------------------------------------------------------------- #
def find_latest(directory: Path, pattern: str) -> Path | None:
    matches = sorted(
        directory.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True
    )
    return matches[0] if matches else None


def summarise_results(json_path: Path) -> str:
    """Return a Markdown 'Quick Stats' section, or a note if it can't be read."""
    try:
        data = json.loads(json_path.read_text())
    except Exception as exc:  # malformed JSON, permissions, etc.
        log.warning("Could not read stats from %s: %s", json_path, exc)
        return f"_Could not read quick stats from `{json_path.name}`: {exc}_\n"

    lines = [
        "## 📈 Quick Stats",
        "",
        f"- **Strategies executed:** {data.get('total_strategies_run', '?')}",
        f"- **Unique tickers found:** {data.get('total_tickers_found', '?')}",
    ]
    multi = data.get("multi_signal_stocks", {}) or {}
    lines.append(f"- **Multi-signal stocks:** {len(multi)}")

    if multi:
        lines += ["", "**🔥 Top conviction picks:**", ""]
        top = sorted(multi.items(), key=lambda kv: len(kv[1]), reverse=True)[:5]
        for ticker, signals in top:
            joined = ", ".join(signals)
            lines.append(f"- **{ticker}** ({len(signals)} signals: {joined})")

    return "\n".join(lines) + "\n"


def build_markdown(directory: Path) -> tuple[str, str]:
    """Return (subject, markdown_body) for the morning report."""
    today = datetime.now().strftime("%A, %B %d, %Y")
    report = find_latest(directory, "report_*.md")
    results = find_latest(directory, "results_*.json")

    parts = [
        "# 🌅 Good Morning — Overnight Stock Research Report",
        "",
        f"_{today}_",
        "",
    ]

    if report:
        log.info("Latest report: %s", report.name)
        parts += [f"**Latest report:** `{report.name}`", "", report.read_text()]
    else:
        log.info("No report files found in %s", directory)
        parts.append("⏳ No reports generated yet. The first run is scheduled for 2 AM.")

    if results:
        log.info("Latest data: %s", results.name)
        parts += ["", "---", "", summarise_results(results)]

    subject = f"Stock Research Report — {today}"
    return subject, "\n".join(parts)


# --------------------------------------------------------------------------- #
# HTML conversion
# --------------------------------------------------------------------------- #
HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  body {{
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    line-height: 1.55; color: #1a1a1a; max-width: 720px;
    margin: 0 auto; padding: 24px;
  }}
  h1 {{ font-size: 1.5rem; }}
  h2 {{ font-size: 1.2rem; margin-top: 1.6em; }}
  code {{ background: #f2f2f2; padding: 1px 5px; border-radius: 4px; font-size: 0.9em; }}
  pre {{ background: #f6f8fa; padding: 12px; border-radius: 6px; overflow-x: auto; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
  th, td {{ border: 1px solid #ddd; padding: 6px 10px; text-align: left; }}
  th {{ background: #f6f8fa; }}
  hr {{ border: none; border-top: 1px solid #e0e0e0; margin: 1.6em 0; }}
  blockquote {{ border-left: 3px solid #ccc; margin: 1em 0; padding-left: 12px; color: #555; }}
</style>
</head>
<body>
{body}
</body>
</html>"""


def to_html(markdown_text: str, title: str) -> str:
    try:
        import pypandoc
    except ImportError:
        raise SystemExit("pypandoc is required: pip install pypandoc-binary")

    try:
        body = pypandoc.convert_text(markdown_text, "html", format="gfm")
    except OSError:
        # No pandoc executable on PATH — fetch one (no-op with pypandoc-binary).
        log.info("pandoc not found; downloading via pypandoc...")
        pypandoc.download_pandoc()
        body = pypandoc.convert_text(markdown_text, "html", format="gfm")

    return HTML_TEMPLATE.format(title=title, body=body)


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #
def send_email(cfg: MailConfig, subject: str, html_body: str, text_body: str) -> None:
    cfg.validate()

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.mail_from
    msg["To"] = ", ".join(cfg.recipients)
    msg.set_content(text_body)  # plain-text fallback
    msg.add_alternative(html_body, subtype="html")

    log.info("Sending to %s via %s:%s", ", ".join(cfg.recipients), cfg.host, cfg.port)

    smtp_cls = smtplib.SMTP_SSL if cfg.security == "ssl" else smtplib.SMTP
    with smtp_cls(cfg.host, cfg.port, timeout=30) as smtp:
        smtp.ehlo()
        if cfg.security == "starttls":
            smtp.starttls()
            smtp.ehlo()
        if cfg.user and cfg.password:
            smtp.login(cfg.user, cfg.password)
        smtp.send_message(msg)

    log.info("Email sent.")


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build and email the morning report.")
    parser.add_argument("--to", help="Comma-separated recipients (overrides MAIL_TO).")
    parser.add_argument("--out", help="Also write the generated HTML to this path.")
    parser.add_argument(
        "--no-email", action="store_true", help="Build only; print to stdout, don't send."
    )
    parser.add_argument(
        "--findings-dir", help="Override FINDINGS_DIR for this run."
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = parse_args(argv)

    directory = (
        Path(args.findings_dir).expanduser() if args.findings_dir else findings_dir()
    )
    if not directory.is_dir():
        log.error("Findings directory not found: %s", directory)
        return 1

    subject, markdown_body = build_markdown(directory)
    html_body = to_html(markdown_body, subject)

    if args.out:
        Path(args.out).write_text(html_body, encoding="utf-8")
        log.info("Wrote HTML to %s", args.out)

    if args.no_email:
        print(html_body)
        return 0

    recipients = _split_csv(args.to) if args.to else None
    cfg = MailConfig.from_env(recipients)
    send_email(cfg, subject, html_body, markdown_body)
    return 0


if __name__ == "__main__":
    sys.exit(main())

