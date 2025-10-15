import smtplib
import random
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Dict, Optional
from email.mime.application import MIMEApplication
import os

class EmailService:
    """
    Simple email helper that can:
    - generate & verify OTPs (in-memory)
    - send plain OTP emails
    - send emails with attachments (PDF)
    """

    def __init__(self, smtp_email: str, smtp_password: str, smtp_server: str, smtp_port: int):
        self.smtp_email = smtp_email
        self.smtp_password = smtp_password
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.otp_storage: Dict[str, str] = {}  # In production, use Redis or DB

    # OTP helpers
    def generate_otp(self, email: str) -> str:
        otp = str(random.randint(100000, 999999))
        self.otp_storage[email] = otp
        return otp

    def verify_otp(self, email: str, otp: str) -> bool:
        stored = self.otp_storage.get(email)
        if stored and stored == otp:
            del self.otp_storage[email]
            return True
        return False

    # send simple OTP email
    def send_otp_email(self, to_email: str, otp: str) -> bool:
        try:
            subject = "Your Vit Healthcare OTP"
            body = f"""Dear User,

Your One-Time Password (OTP) for Vit Healthcare verification is: {otp}

This OTP is valid for 10 minutes. Please do not share this OTP with anyone.

If you did not request this OTP, please ignore this email.

Best regards,
Vit Healthcare Team
"""
            self._send_plain_email(to_email, subject, body)
            return True
        except Exception as e:
            print("Email error (OTP):", e)
            return False

    # send plain text email
    def _send_plain_email(self, to_email: str, subject: str, body: str):
        msg = MIMEMultipart()
        msg["From"] = self.smtp_email
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        # connect and send
        server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
        server.starttls()
        server.login(self.smtp_email, self.smtp_password)
        server.sendmail(self.smtp_email, to_email, msg.as_string())
        server.quit()

    # send prescription/attachment email
    def send_email_with_attachment(self, to_email: str, subject: str, body: str, filename: str, file_bytes: bytes) -> bool:
        """
        Sends an email with a binary attachment (for PDF).
        """
        try:
            msg = MIMEMultipart()
            msg["From"] = self.smtp_email
            msg["To"] = to_email
            msg["Subject"] = subject
            msg.attach(MIMEText(body, "plain"))

            part = MIMEApplication(file_bytes, Name=filename)
            part['Content-Disposition'] = f'attachment; filename="{filename}"'
            msg.attach(part)

            server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
            server.starttls()
            server.login(self.smtp_email, self.smtp_password)
            server.sendmail(self.smtp_email, to_email, msg.as_string())
            server.quit()
            return True
        except Exception as e:
            print("Email attachment send error:", e)
            return False

    # appointment confirmation convenience helper (text-only)
    def send_appointment_confirmation(self, to_email: str, doctor: str, appointment_time: str, appointment_type: str, pincode: str) -> bool:
        try:
            if appointment_type.lower() == "virtual":
                meeting_link = f"https://webex.example.com/meet/{doctor.replace(' ','')}-{appointment_time.replace(' ','T')}"
                location_info = f"Virtual appointment. Join link: {meeting_link}"
            else:
                meeting_link = ""
                location_info = f"Vit Healthcare Center, Pincode: {pincode}"

            body = f"""Hello,

Your appointment with {doctor} is confirmed.
Type: {appointment_type.title()}
When: {appointment_time}
Location: {location_info}

Best regards,
Vit Healthcare
"""
            self._send_plain_email(to_email, f"Appointment Confirmation - Vit Healthcare", body)
            return True
        except Exception as e:
            print("Appointment email error:", e)
            return False
