"""Create private local development credentials for official NudgeBee compose."""
import secrets
from pathlib import Path


def main():
    path = Path("mvp/evidence/nudgebee-compose.env")
    if path.exists():
        print("Preserved existing local NudgeBee credentials.")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    values = {
        "NUDGEBEE_ENCRYPTION_KEY": secrets.token_hex(32),
        "RELAY_SERVER_SECRET_KEY": secrets.token_urlsafe(32),
        "RELAY_WORKSPACE_JWT_SECRET": secrets.token_urlsafe(32),
        "ACTION_API_SERVER_TOKEN": secrets.token_urlsafe(32),
        "NEXTAUTH_SECRET": secrets.token_urlsafe(32),
        "NEXTAUTH_DUMMY_CREDS_ENABLED": "true",
        "NEXTAUTH_DUMMY_CREDS_PASSWORD": secrets.token_urlsafe(24),
        "NUDGEBEE_LOCAL_ADMIN_EMAIL": "admin@agent-mvp.local",
    }
    path.write_text("".join(f"{key}={value}\n" for key, value in values.items()))
    path.chmod(0o600)
    print(f"Created ignored private credentials at {path}; admin email is {values['NUDGEBEE_LOCAL_ADMIN_EMAIL']}.")


if __name__ == "__main__":
    main()

