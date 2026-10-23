"""Build managers, the clients they work with, and invitations between them.

Two ideas, deliberately separate:

* `projects.manager_id` — this person runs this build. Decided per project.
* `manager_links` — this manager works with this client, so every project that
  client owns is theirs to open, including ones created after the link.

The link is what makes an invitation possible before a client has created
anything, and it is still scoped: it only ever grants the client's own builds.

Invitations cover the case where the person has no account yet. The token is the
only thing that travels, and accepting it requires being signed in as the
invited address.
"""

import secrets

from flask import url_for

from db import execute, new_id, now_iso, query

PENDING = "pending"
ACCEPTED = "accepted"
REVOKED = "revoked"

INVITE_NOTE = "The link works once, for the address it was sent to."


def invite_url(token: str) -> str:
    return url_for("team.invite_landing", token=token, _external=True)


def email_invitation(invitation, client, project=None) -> bool:
    """Email the accept link when SMTP is configured; the link is always shown."""
    from notifications import send_email_async

    where = f" for {project['name']}" if project else ""
    body = (
        f"{client['name']} invited you to run their builds{where} on YaVaKa.\n\n"
        f"Accept the invitation: {invite_url(invitation['token'])}\n\n"
        "Sign in, or create an account with this email address, to accept.\n"
        f"{INVITE_NOTE}"
    )
    return send_email_async(
        invitation["email"],
        f"{client['name']} invited you to YaVaKa",
        body,
    )


def link(client_id, manager_id, created_by=None) -> bool:
    """Attach a manager to a client. Idempotent; returns True when it was new."""
    if not client_id or not manager_id or client_id == manager_id:
        return False
    if query(
        "SELECT id FROM manager_links WHERE client_id = ? AND manager_id = ?",
        (client_id, manager_id),
        one=True,
    ):
        return False

    execute(
        """INSERT INTO manager_links (id, client_id, manager_id, created_by, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (new_id(), client_id, manager_id, created_by or client_id, now_iso()),
    )
    return True


def unlink(client_id, manager_id) -> bool:
    if not query(
        "SELECT id FROM manager_links WHERE client_id = ? AND manager_id = ?",
        (client_id, manager_id),
        one=True,
    ):
        return False
    execute(
        "DELETE FROM manager_links WHERE client_id = ? AND manager_id = ?",
        (client_id, manager_id),
    )
    return True


def is_linked(client_id, manager_id) -> bool:
    return bool(
        query(
            "SELECT id FROM manager_links WHERE client_id = ? AND manager_id = ?",
            (client_id, manager_id),
            one=True,
        )
    )


def managers_for(client_id):
    return query(
        """SELECT u.id, u.name, u.email, u.avatar_color, u.phone, l.created_at AS linked_at
           FROM manager_links l
           JOIN users u ON u.id = l.manager_id
           WHERE l.client_id = ?
           ORDER BY u.name""",
        (client_id,),
    )


def clients_for(manager_id):
    return query(
        """SELECT u.id, u.name, u.email, u.avatar_color,
                  (SELECT COUNT(*) FROM projects p
                    WHERE p.owner_id = u.id AND p.archived_at IS NULL) AS project_count
           FROM manager_links l
           JOIN users u ON u.id = l.client_id
           WHERE l.manager_id = ?
           ORDER BY u.name""",
        (manager_id,),
    )


def pending_for_client(client_id):
    return query(
        """SELECT i.*, p.name AS project_name
           FROM invitations i
           LEFT JOIN projects p ON p.id = i.project_id
           WHERE i.client_id = ? AND i.status = 'pending'
           ORDER BY i.created_at DESC""",
        (client_id,),
    )


def pending_for_project(project_id):
    return query(
        """SELECT * FROM invitations
           WHERE project_id = ? AND status = 'pending'
           ORDER BY created_at DESC""",
        (project_id,),
    )


def pending_for_email(email):
    return query(
        """SELECT i.*, c.name AS client_name, p.name AS project_name
           FROM invitations i
           JOIN users c ON c.id = i.client_id
           LEFT JOIN projects p ON p.id = i.project_id
           WHERE i.email = ? AND i.status = 'pending'
           ORDER BY i.created_at DESC""",
        ((email or "").strip().lower(),),
    )


def _find_user(email: str):
    return query("SELECT * FROM users WHERE email = ?", (email,), one=True)


def invite(inviter, email: str, project_id: str | None = None) -> dict:
    """Invite somebody to run this client's builds.

    An existing account is linked immediately — the client is sharing their own
    records, so no consent round-trip is needed. Anything else creates a pending
    invitation with a token to share.
    """
    email = (email or "").strip().lower()
    result = {"ok": False, "linked": None, "invitation": None, "created": False, "message": ""}

    if "@" not in email or "." not in email.split("@")[-1]:
        result["message"] = "Enter a valid email address."
        return result

    existing = _find_user(email)
    if existing:
        if existing["id"] == inviter["id"]:
            result["message"] = "That is your own email address."
            return result
        created = link(inviter["id"], existing["id"], created_by=inviter["id"])
        result.update(
            ok=True,
            linked=existing,
            created=created,
            message=(
                f"{existing['name']} now works on your builds."
                if created
                else f"{existing['name']} already works on your builds."
            ),
        )
        return result

    pending = query(
        """SELECT * FROM invitations
           WHERE client_id = ? AND email = ? AND status = 'pending'
           ORDER BY created_at DESC LIMIT 1""",
        (inviter["id"], email),
        one=True,
    )
    if pending and (pending["project_id"] == project_id or not project_id):
        result.update(
            ok=True,
            invitation=pending,
            message=f"An invitation is already waiting for {email}. Share the link below.",
        )
        return result

    token = secrets.token_urlsafe(24)
    invitation_id = new_id()
    execute(
        """INSERT INTO invitations
             (id, token, inviter_id, client_id, project_id, email, role, status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, 'manager', 'pending', ?)""",
        (invitation_id, token, inviter["id"], inviter["id"], project_id, email, now_iso()),
    )
    created = query("SELECT * FROM invitations WHERE id = ?", (invitation_id,), one=True)
    result.update(
        ok=True,
        invitation=created,
        created=True,
        message=f"Invitation ready for {email}. Share the link below.",
    )
    return result


def revoke(invitation_id: str, client_id: str) -> bool:
    invitation = query(
        "SELECT * FROM invitations WHERE id = ? AND client_id = ?",
        (invitation_id, client_id),
        one=True,
    )
    if not invitation or invitation["status"] != PENDING:
        return False
    execute(
        "UPDATE invitations SET status = ? WHERE id = ?",
        (REVOKED, invitation_id),
    )
    return True


def invitation_by_token(token: str):
    if not token:
        return None
    return query(
        """SELECT i.*, c.name AS client_name, p.name AS project_name
           FROM invitations i
           JOIN users c ON c.id = i.client_id
           LEFT JOIN projects p ON p.id = i.project_id
           WHERE i.token = ?""",
        (token,),
        one=True,
    )


def accept(token: str, user) -> dict:
    """Accept an invitation as the signed-in user. Never trusts the link alone."""
    invitation = invitation_by_token(token)
    result = {"ok": False, "message": "", "invitation": invitation}

    if not invitation:
        result["message"] = "That invitation link is not valid."
        return result
    if invitation["status"] != PENDING:
        result["message"] = "That invitation has already been used."
        return result
    if (user["email"] or "").strip().lower() != invitation["email"]:
        result["message"] = (
            "This invitation was sent to a different email address. "
            "Sign in with that address to accept it."
        )
        return result
    if user["id"] == invitation["client_id"]:
        result["message"] = "You cannot accept your own invitation."
        return result

    link(invitation["client_id"], user["id"], created_by=invitation["inviter_id"])
    execute(
        """UPDATE invitations
           SET status = ?, accepted_at = ?, accepted_by = ?
           WHERE id = ?""",
        (ACCEPTED, now_iso(), user["id"], invitation["id"]),
    )

    # An invitation raised from a project page also puts them on that build.
    if invitation["project_id"]:
        project = query(
            "SELECT * FROM projects WHERE id = ?",
            (invitation["project_id"],),
            one=True,
        )
        if project and project["owner_id"] == invitation["client_id"] and not project["manager_id"]:
            execute(
                "UPDATE projects SET manager_id = ?, updated_at = ? WHERE id = ?",
                (user["id"], now_iso(), project["id"]),
            )

    result.update(ok=True, message=f"You now work with {invitation['client_name']}.")
    return result


def accept_pending_for(user) -> int:
    """After sign-up: claim any invitations that were waiting for this address."""
    accepted = 0
    for invitation in pending_for_email(user["email"]):
        if invitation["client_id"] == user["id"]:
            continue
        link(invitation["client_id"], user["id"], created_by=invitation["inviter_id"])
        execute(
            """UPDATE invitations
               SET status = ?, accepted_at = ?, accepted_by = ?
               WHERE id = ?""",
            (ACCEPTED, now_iso(), user["id"], invitation["id"]),
        )
        if invitation["project_id"]:
            project = query(
                "SELECT * FROM projects WHERE id = ?",
                (invitation["project_id"],),
                one=True,
            )
            if project and project["owner_id"] == invitation["client_id"] and not project["manager_id"]:
                execute(
                    "UPDATE projects SET manager_id = ?, updated_at = ? WHERE id = ?",
                    (user["id"], now_iso(), project["id"]),
                )
        accepted += 1
    return accepted


def adopt_projects_for(user) -> int:
    """Projects a manager created for this client before they had an account.

    The manager recorded the client's email on the project, so the client takes
    ownership the moment they register and the manager stays on the build.
    """
    email = (user["email"] or "").strip().lower()
    if not email:
        return 0

    rows = query(
        """SELECT p.*, owner.role AS owner_role
           FROM projects p
           JOIN users owner ON owner.id = p.owner_id
           WHERE lower(p.client_email) = ?
             AND p.owner_id != ?
             AND owner.role IN ('manager', 'admin')""",
        (email, user["id"]),
    )

    adopted = 0
    for project in rows:
        manager_id = project["manager_id"]
        if not manager_id and project["owner_role"] == "manager":
            manager_id = project["owner_id"]

        execute(
            """UPDATE projects SET owner_id = ?, manager_id = ?, updated_at = ?
               WHERE id = ?""",
            (user["id"], manager_id, now_iso(), project["id"]),
        )
        if manager_id:
            link(user["id"], manager_id, created_by=user["id"])
        adopted += 1

    return adopted
