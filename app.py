"""
app.py — Automation Hub (Email + LinkedIn)
"""

import streamlit as st
import importlib

# MUST be first Streamlit command
st.set_page_config(page_title="Automation Hub", page_icon="⚙️", layout="centered")

from config import SMTP_SERVER, SMTP_PORT, SMTP_USE_TLS, DAILY_SEND_LIMIT, VERIFY_API_KEYS
from engine import (
    validate_email_list, load_templates, get_random_template,
    parse_csv, parse_manual_emails, get_sample_csv_bytes,
    export_report_csv, format_duration, get_all_api_credits
)
from smtp_sender import SMTPSender


def email_app():
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
        sender_email = st.text_input("Sender Email", value="arun@aprhubtech.com")
    with col2:
        app_password = st.text_input("App Password", value="", type="password")

    st.divider()

    # API keys loaded silently from config.py
    api_keys = [k.strip() for k in VERIFY_API_KEYS if k and k.strip()]

    with st.expander("📊 API Quota & Limits", expanded=False):
        if not api_keys:
            st.warning("No API keys found in config.py")
        else:
            if st.button("🔄 Check Live Quotas"):
                with st.spinner("Fetching limits from MyEmailVerifier... (Can take ~60s due to free-tier waiting)"):
                    import engine, importlib
                    importlib.reload(engine)
                    st.session_state.quotas = engine.get_all_api_credits(api_keys)
            
            if "quotas" in st.session_state:
                total = 0
                for row in st.session_state.quotas:
                    short_key = row["key"][:8] + "..." + row["key"][-4:]
                    if row["valid"]:
                        st.write(f"✅ **{short_key}**: {row['credits']} credits left")
                        total += row["credits"]
                    else:
                        st.write(f"❌ **{short_key}**: Error - {row.get('error')}")
                st.info(f"**Total Available Credits Today**: {total}")

    st.divider()

    # ── Session State Init ──
    if "validation_done" not in st.session_state:
        st.session_state.validation_done = False
    if "valid_results" not in st.session_state:
        st.session_state.valid_results = []
    if "invalid_results" not in st.session_state:
        st.session_state.invalid_results = []
    if "send_list" not in st.session_state:
        st.session_state.send_list = []

    def reset_validation():
        st.session_state.validation_done = False
        st.session_state.valid_results = []
        st.session_state.invalid_results = []
        st.session_state.send_list = []

    # ── 2. Recipients ──
    st.subheader("1. Add Recipients")
    input_method = st.radio("How?", ["Paste Emails", "Upload CSV"], horizontal=True, label_visibility="collapsed", on_change=reset_validation)

    recipients = []
    if input_method == "Paste Emails":
        manual_input = st.text_area("Paste emails (one per line or comma separated)", height=150, on_change=reset_validation)
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
        uploaded = st.file_uploader("Upload your CSV (columns: email, name, company)", type=["csv"], on_change=reset_validation)
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
        
        st.subheader("2. Validate Emails")
        if st.button("🔍 Validate Emails", use_container_width=True):
            import config, importlib
            importlib.reload(config)
            api_keys_live = [k.strip() for k in config.VERIFY_API_KEYS if k and k.strip()]
            
            label = "Syntax + Domain + Mailbox" if api_keys_live else "Syntax + Domain"
            with st.spinner(f"Validating ({label})..."):
                valid_results, invalid_results, _ = validate_email_list(
                    [r["email"] for r in recipients], api_keys=api_keys_live
                )
                
                st.session_state.valid_results = valid_results
                st.session_state.invalid_results = invalid_results
                
                # Match recipients with validation results to keep names/companies
                valid_set = {v["normalized"] for v in valid_results}
                send_list = [r for r in recipients if r["email"].strip().lower() in valid_set]
                
                if len(send_list) > DAILY_SEND_LIMIT:
                    st.warning(f"Capping at {DAILY_SEND_LIMIT} (Zoho limit).")
                    send_list = send_list[:DAILY_SEND_LIMIT]
                    
                st.session_state.send_list = send_list
                st.session_state.validation_done = True

    # ── 3. Results & Sending ──
    if st.session_state.validation_done:
        valid_results = st.session_state.valid_results
        invalid_results = st.session_state.invalid_results
        send_list = st.session_state.send_list
        
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
            with st.expander(f"✅ Confirmed ({len(confirmed)})", expanded=False):
                for v in confirmed:
                    st.write(f"✅ {v['email']}")

        if catch_all:
            with st.expander(f"⚠️ Catch-all ({len(catch_all)}) — will send", expanded=False):
                st.caption("Domain accepts everything. Address might not exist.")
                for v in catch_all:
                    st.write(f"⚠️ {v['email']}")

        # Import dynamically so it always pulls the latest from config.py even without restart
        import config
        api_keys = [k.strip() for k in config.VERIFY_API_KEYS if k and k.strip()]

        if uncertain:
            with st.expander(f"❓ Unverified ({len(uncertain)}) — will send", expanded=False):
                st.caption("Passed syntax + domain but API check failed.")
                for v in uncertain:
                    # Show the exact reason the API failed!
                    exact_error = v.get("reason") or "No API key provided or network failure"
                    st.write(f"❓ {v['email']} — ({exact_error})")

        if invalid_results:
            with st.expander(f"❌ Rejected ({len(invalid_results)}) — skipped", expanded=True):
                for inv in invalid_results:
                    st.write(f"❌ {inv['email']} — {inv['reason']}")

        st.divider()

        if send_list:
            # ── 4. Email Details ──
            st.subheader("3. Email Details")
            subject = st.text_input("Subject Line", placeholder="e.g. Quick question about your workflow")

            st.divider()

            # ── 5. Delay ──
            st.subheader("4. Delay Between Emails")
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
            if st.button("🚀 Send to Valid Emails", use_container_width=True):
                if not subject:
                    st.error("Add a subject line.")
                    st.stop()

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
                        "name": r.get("name", ""), "company": r.get("company", "")
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
        else:
            st.error("No valid emails to send to.")


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar Navigation & Main Execution
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.title("🛠️ Tools Menu")
app_mode = st.sidebar.radio("Select an Automation:", ["Email Automation", "LinkedIn Automation"])

if app_mode == "Email Automation":
    email_app()
elif app_mode == "LinkedIn Automation":
    import linkedin_automation
    linkedin_automation.main()
