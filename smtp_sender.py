"""
smtp_sender.py — SMTP sending engine with throttling, fail-fast, and auto-reconnect.

Features:
- Single SMTP connection reused across all sends
- Auto-reconnect if connection drops
- Random delay between sends to mimic human patterns
- Fail-fast: stops after N consecutive failures
- Per-email error capture with detailed reasons
- Supports stop/abort via callback
"""

import smtplib
import time
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from config import SMTP_TIMEOUT, SMTP_RETRY_ATTEMPTS, CONSECUTIVE_FAIL_THRESHOLD


class SMTPSender:
    """Handles SMTP connection and email sending with safety mechanisms."""

    def __init__(self, smtp_server: str, smtp_port: int, use_tls: bool,
                 sender_email: str, app_password: str):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.use_tls = use_tls
        self.sender_email = sender_email
        self.app_password = app_password
        self.connection = None

    def test_connection(self) -> tuple[bool, str]:
        """
        Test SMTP connection and login credentials.
        Returns (success: bool, message: str)
        """
        try:
            server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=SMTP_TIMEOUT)
            if self.use_tls:
                server.starttls()
            server.login(self.sender_email, self.app_password)
            server.quit()
            return True, "✅ Connection successful! Credentials are valid."
        except smtplib.SMTPAuthenticationError:
            return False, "❌ Authentication failed. Check your email and App Password."
        except smtplib.SMTPConnectError:
            return False, f"❌ Could not connect to {self.smtp_server}:{self.smtp_port}. Check server settings."
        except smtplib.SMTPServerDisconnected:
            return False, "❌ Server disconnected unexpectedly. Check server settings."
        except TimeoutError:
            return False, f"❌ Connection timed out after {SMTP_TIMEOUT}s. Check your network/firewall."
        except Exception as e:
            return False, f"❌ Unexpected error: {str(e)}"

    def _connect(self) -> smtplib.SMTP:
        """Establish and authenticate SMTP connection."""
        server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=SMTP_TIMEOUT)
        if self.use_tls:
            server.starttls()
        server.login(self.sender_email, self.app_password)
        return server

    def _ensure_connection(self):
        """Ensure we have a live connection, reconnect if needed."""
        if self.connection is None:
            self.connection = self._connect()
            return

        try:
            # Test if connection is still alive
            status = self.connection.noop()
            if status[0] != 250:
                raise smtplib.SMTPServerDisconnected("NOOP failed")
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPResponseException, OSError):
            # Reconnect
            try:
                self.connection.quit()
            except Exception:
                pass
            self.connection = self._connect()

    def _send_single(self, to_email: str, subject: str, body: str) -> tuple[bool, str]:
        """
        Send a single email.
        Returns (success: bool, error_message: str|None)
        """
        msg = MIMEMultipart()
        msg["From"] = self.sender_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain", "utf-8"))

        for attempt in range(SMTP_RETRY_ATTEMPTS + 1):
            try:
                self._ensure_connection()
                self.connection.sendmail(self.sender_email, to_email, msg.as_string())
                return True, None
            except smtplib.SMTPRecipientsRefused as e:
                return False, f"Recipient refused: {str(e)}"
            except smtplib.SMTPSenderRefused as e:
                return False, f"Sender refused (account may be blocked): {str(e)}"
            except smtplib.SMTPDataError as e:
                return False, f"Data error (message rejected): {str(e)}"
            except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError,
                    ConnectionResetError, OSError) as e:
                if attempt < SMTP_RETRY_ATTEMPTS:
                    # Force reconnect on next attempt
                    self.connection = None
                    time.sleep(2)
                    continue
                return False, f"Connection lost: {str(e)}"
            except Exception as e:
                return False, f"Unexpected error: {str(e)}"

        return False, "Max retry attempts exceeded"

    def send_batch(
        self,
        recipients: list[dict],
        subject: str | None,
        get_body_callback: callable,
        delay_range: tuple[int, int],
        progress_callback: callable = None,
        should_stop_callback: callable = None
    ) -> dict:
        """
        Send emails to a batch of recipients with throttling and fail-fast.

        Args:
            recipients: List of dicts with at least {"email": str} and optional
                       {"name": str, "company": str} for template placeholders.
            subject: Email subject line. If None, subject is taken from
                     get_body_callback._last_subject after each call (per-email subjects).
            get_body_callback: callable(recipient_dict) -> (body: str, template_label: str)
                              Called for each recipient to get the rendered email body.
            delay_range: (min_seconds, max_seconds) random delay between sends.
            progress_callback: Optional callable(status_dict) called after each send.
            should_stop_callback: Optional callable() -> bool, returns True to abort.

        Returns:
            dict: {
                "sent": [{"email": str, "template": str, "timestamp": str}, ...],
                "failed": [{"email": str, "error": str, "timestamp": str}, ...],
                "total": int,
                "stopped_early": bool,
                "stop_reason": str|None
            }
        """
        sent = []
        failed = []
        consecutive_failures = 0
        stopped_early = False
        stop_reason = None
        start_time = time.time()

        for i, recipient in enumerate(recipients):
            # ── Check stop signal ──
            if should_stop_callback and should_stop_callback():
                stopped_early = True
                stop_reason = "Manually stopped by user"
                break

            email = recipient.get("email", recipient.get("normalized", ""))
            timestamp = datetime.now().strftime("%H:%M:%S")

            # ── Get rendered body ──
            try:
                body, template_label = get_body_callback(recipient)
            except Exception as e:
                failed.append({
                    "email": email,
                    "error": f"Template error: {str(e)}",
                    "timestamp": timestamp
                })
                consecutive_failures += 1
                if consecutive_failures >= CONSECUTIVE_FAIL_THRESHOLD:
                    stopped_early = True
                    stop_reason = f"Stopped: {CONSECUTIVE_FAIL_THRESHOLD} consecutive failures"
                    break
                continue

            # ── Send ──
            # If subject is None, pull the per-email subject from the callback
            email_subject = subject if subject is not None else getattr(get_body_callback, '_last_subject', 'No Subject')
            success, error = self._send_single(email, email_subject, body)

            if success:
                sent.append({
                    "email": email,
                    "template": template_label,
                    "timestamp": timestamp
                })
                consecutive_failures = 0  # Reset on success
            else:
                failed.append({
                    "email": email,
                    "error": error,
                    "timestamp": timestamp
                })
                consecutive_failures += 1

                # ── Fail-fast check ──
                if consecutive_failures >= CONSECUTIVE_FAIL_THRESHOLD:
                    stopped_early = True
                    stop_reason = (
                        f"⚠️ Auto-stopped after {CONSECUTIVE_FAIL_THRESHOLD} consecutive failures. "
                        "Your email provider may have blocked sending. "
                        "Wait a few hours before trying again."
                    )
                    break

            # ── Progress callback ──
            if progress_callback:
                elapsed = time.time() - start_time
                progress_callback({
                    "current": i + 1,
                    "total": len(recipients),
                    "email": email,
                    "success": success,
                    "error": error,
                    "template": template_label if success else None,
                    "sent_count": len(sent),
                    "failed_count": len(failed),
                    "elapsed_seconds": elapsed,
                    "timestamp": timestamp
                })

            # ── Throttle delay (skip after last email) ──
            if i < len(recipients) - 1 and not stopped_early:
                delay = random.uniform(delay_range[0], delay_range[1])
                time.sleep(delay)

        # ── Cleanup ──
        try:
            if self.connection:
                self.connection.quit()
        except Exception:
            pass
        self.connection = None

        elapsed_total = time.time() - start_time

        return {
            "sent": sent,
            "failed": failed,
            "total": len(recipients),
            "sent_count": len(sent),
            "failed_count": len(failed),
            "success_rate": (len(sent) / len(recipients) * 100) if recipients else 0,
            "elapsed_seconds": elapsed_total,
            "stopped_early": stopped_early,
            "stop_reason": stop_reason
        }
