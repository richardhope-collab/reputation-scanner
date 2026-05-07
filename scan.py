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

# ── Signal AI USPs for email drafting ────────────────────────────────────────

SIGNAL_AI_USPS = """
- Reputation Intelligence: tracks narrative shifts in real time across 4M+ sources so comms teams get ahead of coverage before it becomes a crisis.
- Risk Intelligence: surfaces emerging threats by entity, topic, and geography, giving teams an early warning system that PR monitoring tools miss.
- Memo: auto-generates executive-ready briefings from daily coverage, cutting hours of manual curation for comms teams.
- Competitive Intelligence: benchmarks share of voice and sentiment against competitors across global media, giving comms leaders the data to justify strategy.
- AI Citations: delivers sourced, verified intelligence so teams can act on AI-generated insights without the hallucination risk.
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

# ── Build scan prompt ─────────────────────────────────────────────────────────

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

# ── Build outreach drafting prompt ────────────────────────────────────────────

def build_drafts_prompt(top10: list) -> str:
    accounts_block = ""
    for r in top10:
        accounts_block += f"""
Company: {r['company']}
Severity: {r['severity']}
Headline: {r['headline']}
Detail: {r.get('detail', '')}
Source: {r.get('source', 'N/A')}
---"""

    return f"""You are Rich Hope, Enterprise Account Executive at Signal AI.

Signal AI is an AI-powered media intelligence platform. Its key capabilities are:
{SIGNAL_AI_USPS}

Below are 10 companies that appeared in today's reputation scan, with the news context that triggered the alert. For each company, draft a short cold outreach email to their Head of Communications.

Rules for every draft:
- Open with the specific news insight from today, not a generic opener.
- One sentence connecting their situation to the single most relevant Signal AI capability.
- Soft CTA for a 20-minute call to discuss how Signal AI can help.
- Max 100 words total.
- No em dashes. No "I hope this finds you well." No corporate filler. No pricing.
- Peer-level tone throughout.
- Sign off: Rich Hope, Enterprise Account Executive, Signal AI.

Accounts:
{accounts_block}

Return ONLY a valid JSON array. No preamble, no markdown. Each element must have exactly these fields:
- "company": string (match exactly to the company name above)
- "subject": string (max 8 words, news-anchored, no clickbait)
- "draft": string (the full email body)"""

# ── Parse response ────────────────────────────────────────────────────────────

def parse_response(raw: str) -> list:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0]
    return json.loads(text.strip())

# ── Generate outreach drafts ──────────────────────────────────────────────────

def generate_outreach_drafts(top10: list) -> dict:
    """Returns a dict of company name -> {subject, draft}."""
    print("Generating outreach drafts for top 10...")
    prompt = build_drafts_prompt(top10)
    raw = call_claude(prompt)
    drafts_list = parse_response(raw)
    return {d["company"]: d for d in drafts_list}

# ── Format email ──────────────────────────────────────────────────────────────

SEVERITY_EMOJI = {
    "CRITICAL": "🔴",
    "HIGH": "🟠",
    "ELEVATED": "🟡",
    "MODERATE": "🔵",
    "LOW": "🟢",
}

def format_email(results: list, drafts: dict, scan_date: str) -> tuple[str, str]:
    top = results[0] if results else {}
    top_severity = top.get("severity", "LOW")
    top_company = top.get("company", "N/A")
    icon = SEVERITY_EMOJI.get(top_severity, "")
    subject = f"Reputation Scan {scan_date} | {icon} {top_company} ({top_severity})"

    # Track which companies have a draft
    draft_companies = set(drafts.keys())

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
            company = r.get("company", "")
            lines.append(f"  {company}  [Score: {r.get('score', '')}]")
            lines.append(f"  {r.get('headline', '')}")
            if r.get("detail"):
                lines.append(f"  {r.get('detail', '')}")
            if r.get("source") and r.get("source") != "N/A":
                lines.append(f"  Source: {r.get('source', '')}")

            # Inject outreach draft if this company is in the top 10
            if company in draft_companies:
                d = drafts[company]
                lines.append("")
                lines.append("  DRAFT OUTREACH")
                lines.append("  " + "." * 36)
                lines.append(f"  Subject: {d.get('subject', '')}")
                lines.append("")
                # Indent each line of the draft body
                for draft_line in d.get("draft", "").splitlines():
                    lines.append(f"  {draft_line}")
                lines.append("  " + "." * 36)

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
    print("Calling Claude API for reputation scan...")
    raw = call_claude(prompt)
    print("Response received, parsing...")

    results = parse_response(raw)
    print(f"Parsed {len(results)} company records")

    # Top 10 by score for outreach drafts
    top10 = sorted(results, key=lambda x: x.get("score", 0), reverse=True)[:10]
    drafts = generate_outreach_drafts(top10)
    print(f"Drafts generated for {len(drafts)} accounts")

    subject, body = format_email(results, drafts, scan_date)
    print(f"Subject: {subject}")

    send_email(subject, body)
    print("Done.")

if __name__ == "__main__":
    main()
