"""Create the first login (or reset a password) from the server shell.

    python -m app.users create owner@ohdelhi.in "Aneesh"        # prompts for the password
    python -m app.users reset owner@ohdelhi.in
"""
import getpass
import sys

from sqlalchemy import func, select

from .auth import hash_password
from .db import SessionLocal
from .models import User


def main() -> None:
    if len(sys.argv) < 3 or sys.argv[1] not in ("create", "reset"):
        print(__doc__)
        sys.exit(1)
    cmd, email = sys.argv[1], sys.argv[2].strip().lower()
    pw = getpass.getpass("Password (min 8 characters): ")
    if len(pw) < 8 or pw != getpass.getpass("Repeat password: "):
        sys.exit("Passwords must match and be at least 8 characters.")
    with SessionLocal() as db:
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if cmd == "create":
            if user:
                sys.exit(f"{email} already exists. Use reset.")
            db.add(User(email=email, name=sys.argv[3] if len(sys.argv) > 3 else email, password_hash=hash_password(pw)))
        else:
            if not user:
                sys.exit(f"No user {email}.")
            user.password_hash, user.active = hash_password(pw), True
            user.token_version += 1
        db.commit()
    print(f"{'Created' if cmd == 'create' else 'Reset'} {email}.")


if __name__ == "__main__":
    main()
