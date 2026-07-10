"""Optional LDAP / Active Directory authentication provider.

When configured (Administration → Directory), users sign in with their AD
credentials: FMS binds to the directory to verify the password, reads the
user's groups, maps them to an FMS role, and auto-provisions a local user
record on first successful login (no password stored locally for AD users).

When NOT configured, this module is inert and the built-in local accounts are
used exactly as before — AD is purely additive.

Config (bank_config['directory']):
  enabled: bool
  server_uri: "ldap://dc.example.com:389" or "ldaps://..."
  start_tls: bool
  bind_user_template: "{username}@example.com"  (or "EXAMPLE\\{username}")
  base_dn: "DC=example,DC=com"           (for the group lookup)
  user_search: "(sAMAccountName={username})"
  group_role_map: {"FMS-Admins": "admin", "FMS-Analysts": "analyst", ...}
  default_role: "viewer"
"""
import logging

from backend.config import bank_config

log = logging.getLogger(__name__)


def config() -> dict:
    return bank_config.get("directory", {}) or {}


def is_enabled() -> bool:
    cfg = config()
    return bool(cfg.get("enabled") and cfg.get("server_uri") and cfg.get("bind_user_template"))


def _role_from_groups(groups: list[str], cfg: dict) -> str:
    mapping = cfg.get("group_role_map", {}) or {}
    # Normalize group CNs for comparison.
    got = {g.lower() for g in groups}
    # admin wins over analyst wins over viewer if a user is in several.
    order = {"admin": 0, "analyst": 1, "viewer": 2}
    best = None
    for group_name, role in mapping.items():
        if group_name.lower() in got and role in order:
            if best is None or order[role] < order[best]:
                best = role
    return best or cfg.get("default_role", "viewer")


def authenticate(username: str, password: str) -> dict | None:
    """Verify credentials against the directory. Returns
    {"username", "email", "full_name", "role"} on success, else None.
    Raises RuntimeError only for configuration/connection problems."""
    cfg = config()
    try:
        import ldap3
    except ImportError:
        raise RuntimeError("ldap3 package not installed on the server")

    uri = cfg["server_uri"]
    bind_dn = cfg["bind_user_template"].replace("{username}", username)

    server = ldap3.Server(uri, get_info=ldap3.NONE, use_ssl=uri.lower().startswith("ldaps"))
    conn = None
    try:
        conn = ldap3.Connection(server, user=bind_dn, password=password, authentication=ldap3.SIMPLE)
        if cfg.get("start_tls") and not uri.lower().startswith("ldaps"):
            conn.start_tls()
        if not conn.bind():
            log.info(f"LDAP bind failed for {username!r}")
            return None  # bad credentials

        # Look up the user's groups + attributes for role mapping and provisioning.
        groups: list[str] = []
        email = f"{username}@{cfg.get('email_domain', '')}".rstrip("@")
        full_name = username
        base_dn = cfg.get("base_dn")
        if base_dn:
            search_filter = cfg.get("user_search", "(sAMAccountName={username})").replace("{username}", username)
            conn.search(base_dn, search_filter,
                        attributes=["memberOf", "mail", "displayName", "cn"])
            if conn.entries:
                e = conn.entries[0]
                if "memberOf" in e:
                    for dn in e.memberOf.values:
                        # extract CN=<group> from the DN
                        cn = dn.split(",")[0].split("=", 1)[-1]
                        groups.append(cn)
                if "mail" in e and e.mail.value:
                    email = str(e.mail.value)
                if "displayName" in e and e.displayName.value:
                    full_name = str(e.displayName.value)
                elif "cn" in e and e.cn.value:
                    full_name = str(e.cn.value)

        return {
            "username": username.lower(),
            "email": email.lower() if email else None,
            "full_name": full_name,
            "role": _role_from_groups(groups, cfg),
        }
    except Exception as e:
        raise RuntimeError(f"LDAP error: {e}")
    finally:
        if conn:
            try:
                conn.unbind()
            except Exception:
                pass


def test_connection() -> tuple[bool, str]:
    """Verify the server is reachable and accepts an anonymous or configured
    service bind — for the 'Test' button. Does not validate a specific user."""
    cfg = config()
    if not cfg.get("server_uri"):
        return False, "No server URI configured"
    try:
        import ldap3
    except ImportError:
        return False, "ldap3 package not installed on the server"
    try:
        uri = cfg["server_uri"]
        server = ldap3.Server(uri, get_info=ldap3.NONE, use_ssl=uri.lower().startswith("ldaps"),
                              connect_timeout=8)
        conn = ldap3.Connection(server)
        if conn.bind():
            conn.unbind()
            return True, "Directory server reachable."
        return True, "Server reachable (anonymous bind refused, which is normal)."
    except Exception as e:
        return False, f"Could not reach directory: {e}"
