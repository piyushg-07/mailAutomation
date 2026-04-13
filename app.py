"""
app.py — Email Automation Engine with API-based mailbox verification.
"""

import streamlit as st
from config import SMTP_SERVER, SMTP_PORT, SMTP_USE_TLS, DAILY_SEND_LIMIT, VERIFY_API_KEYS
from engine import (
    validate_email_list, load_templates, get_random_template,
    parse_csv, parse_manual_emails, get_sample_csv_bytes,
    export_report_csv, format_duration
)
from smtp_sender import SMTPSender

st.set_page_config(page_title="Email Sender", page_icon="📧", layout="centered")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; max-width: 800px; }
    .stButton>button {
        background-color: #667eea; color: white;
        font-weight: bold; border-radius: 8px; padding: 0.5rem 0;
    }
</style>
""", unsafe_allow_html=True)

st.title("📧 Automatic Email Sender")
st.markdown("Send batch emails via Zoho Mail with real email verification.")

st.divider()

# ── 1. Credentials ──
col1, col2 = st.columns(2)
with col1:
    sender_email = st.text_input("Sender Email", value="piyush@aprhubtech.com")
with col2:
    app_password = st.text_input("App Password", value="szjf2Dp%", type="password")
sender_name = st.text_input("Your Name (for templates)", value="TruBench")

st.divider()

# API keys loaded silently from config.py
api_keys = [k.strip() for k in VERIFY_API_KEYS if k and k.strip()]

# ── 3. Recipients ──
st.subheader("1. Add Recipients")
input_method = st.radio("How?", ["Paste Emails", "Upload CSV"], horizontal=True, label_visibility="collapsed")

recipients = []
if input_method == "Paste Emails":
    manual_input = st.text_area("Paste emails (one per line or comma separated)", height=150)
    if manual_input:
        recipients = parse_manual_emails(manual_input)
else:
    # Sample CSV download
    st.download_button(
        "📥 Download Sample CSV Template",
        get_sample_csv_bytes(),
        "email_template.csv",
        "text/csv",
        help="Download this, fill it with your data, then upload below"
    )
    uploaded = st.file_uploader("Upload your CSV (columns: email, name, company)", type=["csv"])
    if uploaded:
        res = parse_csv(uploaded.read())
        if res["success"]:
            recipients = res["recipients"]
            st.success(f"✅ Loaded {len(recipients)} emails from CSV.")
            with st.expander("Preview"):
                st.dataframe(res["preview_df"])
        else:
            st.error(res["error"])

if recipients:
    st.info(f"**{len(recipients)}** recipients ready.")

st.divider()

# ── 4. Email Details ──
st.subheader("2. Email Details")
subject = st.text_input("Subject Line", placeholder="e.g. Quick question about your workflow")

st.divider()

# ── 5. Delay ──
st.subheader("3. Delay Between Emails")
st.caption("Random delay to avoid spam detection.")
col_d1, col_d2 = st.columns(2)
with col_d1:
    min_delay = st.number_input("Min (seconds)", min_value=1, max_value=120, value=5)
with col_d2:
    max_delay = st.number_input("Max (seconds)", min_value=1, max_value=120, value=12)
if min_delay > max_delay:
    min_delay, max_delay = max_delay, min_delay

st.divider()

# ── 6. Send ──
if st.button("🚀 Validate & Send", use_container_width=True):
    if not recipients:
        st.error("Add recipients first.")
        st.stop()
    if not subject:
        st.error("Add a subject line.")
        st.stop()

    # Validation
    label = "Syntax + Domain + Mailbox" if api_keys else "Syntax + Domain"
    with st.spinner(f"Validating ({label})..."):
        valid_results, invalid_results, _ = validate_email_list(
            [r["email"] for r in recipients], api_keys=api_keys
        )

    # Categorise
    confirmed = [v for v in valid_results if v.get("api_status") == "valid"]
    catch_all = [v for v in valid_results if v.get("api_status") == "catch_all"]
    uncertain = [v for v in valid_results if v.get("api_status") in ("unknown", "skipped", None)]

    st.markdown(
        f"**Results:** `{len(confirmed)} Confirmed ✅` · "
        f"`{len(catch_all)} Catch-All ⚠️` · "
        f"`{len(uncertain)} Unverified ❓` · "
        f"`{len(invalid_results)} Rejected ❌`"
    )

    if confirmed:
        with st.expander(f"✅ Confirmed ({len(confirmed)})"):
            for v in confirmed:
                st.write(f"✅ {v['email']}")

    if catch_all:
        with st.expander(f"⚠️ Catch-all ({len(catch_all)}) — will send"):
            st.caption("Domain accepts everything. Address might not exist.")
            for v in catch_all:
                st.write(f"⚠️ {v['email']}")

    if uncertain:
        with st.expander(f"❓ Unverified ({len(uncertain)}) — will send"):
            st.caption("Passed syntax + domain. No API key or API couldn't check.")
            for v in uncertain:
                st.write(f"❓ {v['email']}")

    if invalid_results:
        with st.expander(f"❌ Rejected ({len(invalid_results)}) — skipped", expanded=True):
            for inv in invalid_results:
                st.write(f"❌ {inv['email']} — {inv['reason']}")

    if not valid_results:
        st.error("No valid emails to send to.")
        st.stop()

    # Cap
    valid_set = {v["normalized"] for v in valid_results}
    send_list = [r for r in recipients if r["email"].strip().lower() in valid_set]
    if len(send_list) > DAILY_SEND_LIMIT:
        st.warning(f"Capping at {DAILY_SEND_LIMIT} (Zoho limit).")
        send_list = send_list[:DAILY_SEND_LIMIT]

    # Send
    st.markdown("### 📤 Sending")
    bar = st.progress(0, text="Connecting...")

    try:
        smtp = SMTPSender(SMTP_SERVER, SMTP_PORT, SMTP_USE_TLS, sender_email, app_password)
        templates = load_templates()
    except Exception as e:
        st.error(f"Init failed: {str(e)}")
        st.stop()

    def get_body(r):
        return get_random_template(templates, {
            "name": r.get("name", ""), "company": r.get("company", ""), "sender_name": sender_name
        })

    def on_progress(s):
        bar.progress(s["current"] / s["total"],
                     text=f"{s['current']}/{s['total']} · ✅ {s['sent_count']} · ❌ {s['failed_count']}")

    results = smtp.send_batch(
        recipients=send_list, subject=subject, get_body_callback=get_body,
        delay_range=(min_delay, max_delay), progress_callback=on_progress
    )

    bar.empty()
    elapsed = format_duration(results.get("elapsed_seconds", 0))
    st.success(f"**Done!** ✅ {results['sent_count']} sent · ❌ {results['failed_count']} failed · ⏱ {elapsed}")

    if results.get("stopped_early"):
        st.warning(results["stop_reason"])

    if results["failed"]:
        with st.expander("Failed sends", expanded=True):
            for f in results["failed"]:
                st.write(f"❌ {f['email']} — {f['error']}")

    st.download_button("📥 Download Report", export_report_csv(results), "report.csv", "text/csv")
