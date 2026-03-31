import os
import json
import smtplib
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import anthropic

# ── Accounts to monitor ──────────────────────────────────────────────────────

COMPANIES = [
    "Ameriprise Financial / Columbia Threadneedle Investments",
    "BNY Mellon", "Brown-Forman Corporation", "McKinsey & Company",
    "Meta (Facebook)", "Morgan Stanley", "Royal Bank of Canada (RBC)",
    "Salesforce", "ServiceNow", "The Vanguard Group", "Western Union",
    "Viatris Healthcare", "Yahoo", "Ally Financial", "AON", "Bread Financial",
    "Citizens Bank", "Credit One Bank", "Edward Jones / Jones Financial",
    "Fair Isaac / FICO", "KeyBank", "Moody's Corporation",
    "Northwestern Mutual", "Progressive", "SoFi", "Apple", "Box",
    "Cognizant", "Lam Research", "Roblox", "Samsara",
    "SharkNinja", "Veeva Systems", "Avantor", "Biogen", "Lululemon",
    "Paramount Global", "Ulta Beauty", "Chobani", "Performance Food Group",
    "Sazerac", "US Foods", "GlobalFoundries", "Halliburton",
    "Koch Industries", "Marathon Petroleum", "CHS", "Toast"
]

# ── Severity guide ────────────────────────────────────────────────────────────

SEVERITY_GUIDE = """
Threat Severity Scale:
- CRITICAL (9-10): Active crisis. Breaking news, viral negative story, regulatory sanctions, C-suite scandal, data breach.
- HIGH (7-8): Significant risk developing fast. Multiple outlets, litigation filed, major financial miss, ESG controversy gaining traction.
- ELEVATED (5-6): Emerging risk. Single outlet negative story, internal leak, minor regulatory inquiry, activist investor.
- MODERATE (3-4): Background noise. Industry-wide narrative including this company, minor criticism, low-engagement controversy.
- LOW (1-2): Minimal risk. Tangential coverage, opinion pieces with little reach.
"""

# ── Claude API call ──────────────────────────────────────────────────────────

def call_claude(prompt: str) -> str:
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    for attempt in range(3):
        try:
            message = client.messages.create(
                model="claude-opus-4-5",
                max_tokens=16000,
                messages=[{"role": "user", "content": prompt}]
            )
            return message.content[0].text
        except anthropic.RateLimitError:
            if attempt < 2:
                print(f"Rate limit hit, waiting 60s (attempt {attempt + 1}/3)...")
                time.sleep(60)
            else:
                raise

# ── Build prompt ──────────────────────────────────────────────────────────────

def build_prompt() -> str:
    today = datetime.utcnow().strftime("%B %d, %Y")
    companies_list = "\n".join(f"- {c}" for c in COMPANIES)
    return f"""Today is {today}. You are a senior reputation risk analyst.

Search for news published in the last 24-48 hours for each company below. Identify any reputational risks, negative press, regulatory issues, controversies, or crises. If nothing significant is found for a company, mark it LOW.

{SEVERITY_GUIDE}

Companies to scan:
{companies_list}

Return ONLY a valid JSON array. No preamble, no markdown, no explanation. Each element must have exactly these fields:
- "company": string
- "severity": string (CRITICAL / HIGH / ELEVATED / MODERATE / LOW)
- "score": integer 1-10
- "headline": string (one sentence summary of the key risk, or "No significant news" if clean)
- "detail": string (2-3 sentences of context, or empty string if clean)
- "source": string (publication name, or "N/A")

Return all {len(COMPANIES)} companies. Sort by score descending."""

# ── Parse response ────────────────────────────────────────────────────────────

def parse_response(raw: str) -> list:
    # Strip markdown fences if present
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())

# ── Format email ──────────────────────────────────────────────────────────────

SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "ELEVATED": "🟡",
    "MODERATE": "🔵",
    "LOW": "🟢",
}

def format_email(results: list, scan_date: str) -> tuple[str, str]:
    # Subject line based on top result
    top = results[0] if results else {}
    top_severity = top.get("severity", "LOW")
    top_company = top.get("company", "N/A")
    icon = SEVERITY_EMOJI.get(top_severity, "")
    subject = f"Reputation Scan {scan_date} | {icon} {top_company} ({top_severity})"

    # Group by severity
    groups = {}
    for r in results:
        sev = r.get("severity", "LOW")
        groups.setdefault(sev, []).append(r)

    lines = [
        f"SIGNAL AI REPUTATION SCAN",
        f"Generated: {scan_date} UTC",
        f"Accounts monitored: {len(results)}",
        "=" * 60,
        "",
    ]

    order = ["CRITICAL", "HIGH", "ELEVATED", "MODERATE", "LOW"]
    for sev in order:
        items = groups.get(sev, [])
        if not items:
            continue
        emoji = SEVERITY_EMOJI.get(sev, "")
        lines.append(f"{emoji} {sev} ({len(items)})")
        lines.append("-" * 40)
        for r in items:
            lines.append(f"  {r.get('company', '')}  [Score: {r.get('score', '')}]")
            lines.append(f"  {r.get('headline', '')}")
            if r.get("detail"):
                lines.append(f"  {r.get('detail', '')}")
            if r.get("source") and r.get("source") != "N/A":
                lines.append(f"  Source: {r.get('source', '')}")
            lines.append("")

    body = "\n".join(lines)
    return subject, body

# ── Send email ────────────────────────────────────────────────────────────────

def send_email(subject: str, body: str):
    to_email = os.environ["TO_EMAIL"]
    from_email = os.environ["FROM_EMAIL"]
    password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_email, password)
        server.sendmail(from_email, to_email, msg.as_string())

    print(f"Email sent to {to_email}")

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    scan_date = datetime.utcnow().strftime("%Y-%m-%d %H:%M")
    print(f"Starting reputation scan, {scan_date} UTC")

    prompt = build_prompt()
    print("Calling Claude API...")
    raw = call_claude(prompt)
    print("Response received, parsing...")

    results = parse_response(raw)
    print(f"Parsed {len(results)} company records")

    subject, body = format_email(results, scan_date)
    print(f"Subject: {subject}")

    send_email(subject, body)
    print("Done.")

if __name__ == "__main__":
    main()
