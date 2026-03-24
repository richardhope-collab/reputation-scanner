import os
import json
import re
import time
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import urllib.request
import urllib.error

COMPANIES = [
    "Ameriprise Financial / Columbia Threadneedle Investments",
    "BNY Mellon", "Brown-Forman Corporation", "McKinsey & Company",
    "Meta (Facebook)", "Morgan Stanley", "Royal Bank of Canada (RBC)",
    "Salesforce", "ServiceNow", "The Vanguard Group", "Western Union",
    "Viatris Healthcare", "Yahoo", "Ally Financial", "AON", "Bread Financial",
    "Citizens Bank", "Credit One Bank", "Edward Jones / Jones Financial",
    "Fair Isaac / FICO", "KeyBank", "Moody's Corporation",
    "Northwestern Mutual", "Progressive", "SoFi", "Apple", "Box",
    "Cognizant", "Lam Research", "Lime", "Roblox", "Samsara",
    "SharkNinja", "Veeva Systems", "Avantor", "Biogen", "Lululemon",
    "Paramount Global", "Ulta Beauty", "Chobani", "Performance Food Group",
    "Sazerac", "US Foods", "GlobalFoundries", "Halliburton",
    "Koch Industries", "Marathon Petroleum", "CHS", "Toast"
]

SEVERITY_GUIDE = """
Threat Severity Scale (apply to each account):
- CRITICAL (9-10): Active crisis requiring immediate comms response. Breaking news, viral negative story, regulatory action with sanctions, C-suite scandal, data breach affecting customers.
- HIGH (7-8): Significant reputational risk developing rapidly. Multiple outlets picking up a negative story, litigation filed, material financial miss with negative analyst reaction, ESG controversy gaining momentum.
- ELEVATED (5-6): Emerging risk worth monitoring closely. Single outlet negative coverage, internal leak, minor regulatory inquiry, activist investor building a position.
- MODERATE (3-4): Background noise. Industry-wide negative narrative that includes this company, minor criticism, low-engagement social controversy.
- LOW (1-2): Minimal risk. Tangential coverage, opinion pieces with little reach, issues unlikely to escalate.
"""

SEVERITY_ICONS = {
    "CRITICAL": "🔴",
    "HIGH":     "🟠",
    "ELEVATED": "🟡",
    "MODERATE": "🔵",
    "LOW":      "⚪"
}


def call_gemini(prompt, max_retries=3):
    api_key = os.environ["GEMINI_API_KEY"]
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"maxOutputTokens": 12000, "temperature": 0.3}
    }

    data = json.dumps(payload).encode("utf-8")

    for attempt in range(max_retries):
        try:
            req = urllib.request.Request(
                url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                candidates = result.get("candidates", [])
                if not candidates:
                    raise ValueError("No candidates returned from Gemini.")
                parts = candidates[0].get("content", {}).get("parts", [])
                return "".join(p.get("text", "") for p in parts)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8")
            if e.code == 429 and attempt < max_retries - 1:
                wait = 60 * (attempt + 1)
                print(f"Rate limit hit, waiting {wait}s before retry {attempt + 2}/{max_retries}...")
                time.sleep(wait)
            else:
                raise RuntimeError(f"Gemini API error {e.code}: {body}")

    raise RuntimeError("All retries exhausted.")


def run_scan():
    today = datetime.now().strftime("%A, %B %d, %Y")

    prompt = f"""You are a senior media intelligence analyst at Signal AI, an enterprise AI-powered reputation risk and media monitoring platform.

Today's date: {today}

Use Google Search to find news from the past 24 hours about the companies listed below. Identify the TOP 10 companies facing the highest velocity of negative or reputational risk coverage right now.

Focus areas: regulatory enforcement actions, lawsuits and litigation, leadership scandals or departures, layoffs and restructuring, data breaches or security incidents, product failures or recalls, financial distress signals, ESG controversies, negative analyst coverage, activist investor activity, earnings misses, supply chain failures, or any story a communications team would need to respond to.

{SEVERITY_GUIDE}

For each company, produce TWO versions of an outreach email:

FULL EMAIL: 3-4 short paragraphs. Open by referencing the specific news story. Include a short bulleted list of 4-5 concrete Signal AI use cases directly relevant to the situation, for example real-time coverage alerts, share of voice tracking, narrative shift detection, competitor benchmarking, crisis escalation monitoring, journalist and outlet identification, sentiment trend analysis. Use commas instead of em dashes throughout. Professional and empathetic tone, not opportunistic. Close with a soft CTA for a brief call. Sign off: Rich, Enterprise Account Executive, Signal AI.

MOBILE EMAIL: Maximum 6 lines total. One sentence on the news. One sentence on the reputational risk. Two bullet points on the most relevant Signal AI capabilities. One CTA line. Sign off: Rich, Signal AI. Written to be read in 30 seconds on a phone.

Return ONLY a valid JSON object, no markdown, no preamble, no explanation, using EXACTLY this structure:

{{"scan_date":"{datetime.now().strftime('%Y-%m-%d')}","top_10":[{{"rank":1,"company":"Company Name","severity_label":"CRITICAL","severity_score":9,"coverage_velocity":"High","key_stories":[{{"headline":"Story headline","source":"Publication","summary":"One sentence summary."}}],"risk_summary":"2-3 sentences on the reputational situation and why it matters to a comms team.","outreach_email":{{"to_role":"Chief Communications Officer","subject":"Email subject line","body":"Full email body with bullet points for Signal AI use cases. No em dashes, use commas instead.\\n\\nBest,\\n\\nRich\\nEnterprise Account Executive, Signal AI"}},"mobile_email":{{"subject":"Short subject line","body":"Mobile-optimised email body, maximum 6 lines.\\n\\nRich, Signal AI"}}}}]}}

Companies to scan:
{', '.join(COMPANIES)}"""

    raw = call_gemini(prompt)
    match = re.search(r'\{[\s\S]*\}', raw)
    if not match:
        raise ValueError("Could not parse JSON from Gemini response.")
    return json.loads(match.group(0))


def format_email_body(data):
    lines = []
    lines.append("SIGNAL AI DAILY REPUTATION SCAN")
    lines.append(f"Date: {data['scan_date']}")
    lines.append("Top 10 accounts by negative coverage velocity")
    lines.append("=" * 62)
    lines.append("")
    lines.append("THREAT SEVERITY SCALE")
    lines.append("🔴 CRITICAL (9-10)  🟠 HIGH (7-8)  🟡 ELEVATED (5-6)  🔵 MODERATE (3-4)  ⚪ LOW (1-2)")
    lines.append("=" * 62)
    lines.append("")

    for co in data["top_10"]:
        icon = SEVERITY_ICONS.get(co.get("severity_label", ""), "")
        lines.append(f"{co['rank']}. {co.get('company', 'Unknown').upper()}")
        lines.append(f"   {icon} {co.get('severity_label', 'N/A')} | Score: {co.get('severity_score', 'N/A')}/10 | Velocity: {co.get('coverage_velocity', 'N/A')}")
        lines.append("")
        stories = co.get("key_stories", [])
        if stories:
            lines.append("   KEY STORIES:")
            for s in stories:
                lines.append(f"   * {s.get('headline', 'N/A')} ({s.get('source', 'N/A')})")
                lines.append(f"     {s.get('summary', '')}")
        lines.append("")
        lines.append("   SITUATION SUMMARY:")
        lines.append(f"   {co.get('risk_summary', 'N/A')}")
        lines.append("")
        email = co.get("outreach_email", {})
        lines.append(f"   --- FULL EMAIL TO {email.get('to_role', 'HEAD OF COMMS').upper()} ---")
        lines.append(f"   Subject: {email.get('subject', 'N/A')}")
        lines.append("")
        for line in email.get("body", "").split("\n"):
            lines.append(f"   {line}")
        lines.append("")
        mobile = co.get("mobile_email", {})
        lines.append("   --- MOBILE EMAIL ---")
        lines.append(f"   Subject: {mobile.get('subject', 'N/A')}")
        lines.append("")
        for line in mobile.get("body", "").split("\n"):
            lines.append(f"   {line}")
        lines.append("")
        lines.append("-" * 62)
        lines.append("")

    lines.append("Generated by Signal AI Daily Reputation Scanner")
    return "\n".join(lines)


def send_email(subject, body):
    to_email = os.environ["TO_EMAIL"]
    from_email = os.environ["FROM_EMAIL"]
    app_password = os.environ["GMAIL_APP_PASSWORD"]

    msg = MIMEMultipart()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(from_email, app_password)
        server.send_message(msg)
    print(f"Email sent to {to_email}")


if __name__ == "__main__":
    print(f"Starting reputation scan, {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    data = run_scan()
    top = data["top_10"][0]
    icon = SEVERITY_ICONS.get(top.get("severity_label", ""), "")
    print(f"Scan complete. Top account: {top.get('company', 'Unknown')} {icon} {top.get('severity_label', '')}")

    body = format_email_body(data)
    subject = f"Signal AI Scan {data['scan_date']} | {icon} {top.get('company', 'Unknown')} ({top.get('severity_label', '')})"
    send_email(subject, body)
    print("Done.")
