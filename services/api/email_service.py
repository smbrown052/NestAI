import os
import resend


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    api_key = os.environ.get("RESEND_API_KEY")

    if not api_key:
        raise RuntimeError("RESEND_API_KEY is not configured")

    resend.api_key = api_key

    resend.Emails.send(
        {
            "from": "NestAI <onboarding@resend.dev>",
            "to": [to_email],
            "subject": "Reset your NestAI password",
            "html": f"""
                <p>You requested a password reset for your NestAI account.</p>

                <p>
                    <a href="{reset_link}">
                        Reset your password
                    </a>
                </p>

                <p>If you didn't request this, you can ignore this email.</p>
            """,
        }
    )