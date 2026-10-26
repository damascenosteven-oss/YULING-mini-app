"""Owner-operated, one-time setup. Never run automatically by a deployment workflow."""
import argparse
import getpass
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import stat
import subprocess
import sys
import urllib.request

ROOT = Path("/opt/yuling-ppt-test")
CONF = Path("/etc/yuling-ppt-test")
HOME = Path("/var/lib/yuling-ppt-deploy")
HELPER = Path("/usr/local/libexec/yuling-ppt-release.py")
USER = "yuling-ppt-deploy"


def require(value, message):
    if not value:
        raise RuntimeError(message)


def call(*args, data=None):
    result = subprocess.run([str(arg) for arg in args], input=data, capture_output=True, timeout=90)
    require(result.returncode == 0, "Command failed: " + " ".join(map(str, args[:2])))
    return result.stdout


def digest(data):
    return hashlib.sha256(data).hexdigest()


def create_only(path, data, mode=0o600):
    require(not path.is_symlink(), "Refusing symlink: " + str(path))
    if path.exists():
        require(path.read_bytes() == data and path.stat().st_uid == 0
                and stat.S_IMODE(path.stat().st_mode) == mode,
                "Existing file differs; no overwrite: " + str(path))
        return
    with path.open("xb") as file:
        os.fchmod(file.fileno(), mode)
        file.write(data)
        file.flush()
        os.fsync(file.fileno())


def replace_in_place(path, before, after, reload):
    require(not path.is_symlink() and path.read_bytes() == before,
            "Configuration changed since inspection; stop and inspect")
    identity = (path.stat().st_dev, path.stat().st_ino)
    with path.open("r+b") as file:
        file.write(after)
        file.truncate()
        file.flush()
        os.fsync(file.fileno())
    require((path.stat().st_dev, path.stat().st_ino) == identity, "File identity changed")
    try:
        reload(after)
    except Exception as error:
        require(path.read_bytes() == after, "Reload failed with concurrent edit; owner recovery required")
        with path.open("r+b") as file:
            file.write(before)
            file.truncate()
            file.flush()
            os.fsync(file.fileno())
        reload(before)
        raise RuntimeError("Caddy update failed; original configuration restored") from error


def inspect_caddy(container, network):
    for value in (container, network):
        require(re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,62}", value), "Invalid Docker identifier")
    detail = json.loads(call("/usr/bin/docker", "inspect", container))[0]
    require(detail["State"]["Running"], "Existing Caddy is not running")
    require(network in detail["NetworkSettings"]["Networks"], "Caddy is not attached to selected network")
    gateway = detail["NetworkSettings"]["Networks"][network]["Gateway"]
    mounts = [m for m in detail["Mounts"] if m["Destination"] == "/etc/caddy/Caddyfile"]
    require(len(mounts) == 1 and mounts[0]["Type"] == "bind", "Expected existing single-file Caddy bind mount")
    path = Path(mounts[0]["Source"])
    require(path.is_absolute() and path.is_file() and not path.is_symlink(), "Caddy bind source is not a regular file")
    local = path.read_bytes()
    actual = call("/usr/bin/docker", "exec", container, "cat", "/etc/caddy/Caddyfile")
    require(local == actual, "Container and host Caddy configuration differ")
    return {"gateway": gateway, "caddy_container": container, "caddy_network": network}, path


def check_account(account, primary_group, supplemental):
    require(account.pw_uid != 0 and account.pw_dir == str(HOME) and account.pw_shell == "/bin/sh",
            "Existing deployment account differs; owner must inspect")
    require(primary_group == USER and not supplemental,
            "Deployment account has shared or supplementary privileges; stop")


def prepare(args):
    import grp
    import pwd
    config, _ = inspect_caddy(args.caddy_container, args.caddy_network)
    public_key = args.public_key.read_text().strip()
    require(re.fullmatch(r"ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]*)?", public_key),
            "Supply a single deployment-only ed25519 public key")
    call("/usr/bin/ssh-keygen", "-l", "-f", args.public_key)
    for path in (ROOT, CONF, HOME, HOME / ".ssh", HELPER.parent):
        require(not path.is_symlink(), "Unsafe setup path")
        path.mkdir(parents=True, exist_ok=True)
        require(path.stat().st_uid == 0, "Setup paths must be root-owned")
        if path == HELPER.parent:
            require(not path.stat().st_mode & 0o022, "Receiver parent directory is writable by others")
    os.chmod(ROOT, 0o700)
    os.chmod(CONF, 0o700)
    os.chmod(HOME, 0o755)
    os.chmod(HOME / ".ssh", 0o755)
    try:
        account = pwd.getpwnam(USER)
        check_account(account, grp.getgrgid(account.pw_gid).gr_name,
                      [group.gr_name for group in grp.getgrall() if USER in group.gr_mem])
    except KeyError:
        call("/usr/sbin/useradd", "--system", "--user-group", "--home-dir", HOME, "--shell", "/bin/sh", USER)
    receiver = Path(__file__).with_name("release.py").read_bytes()
    create_only(HELPER, receiver, 0o755)
    command = "/usr/bin/python3 -I " + str(HELPER)
    sudoers = (USER + " ALL=(root) NOPASSWD: " + command + "\n").encode()
    staged = CONF / "sudoers.check"
    create_only(staged, sudoers, 0o440)
    call("/usr/sbin/visudo", "-cf", staged)
    create_only(Path("/etc/sudoers.d/yuling-ppt-test"), sudoers, 0o440)
    key_line = ('restrict,command="sudo -n ' + command + '" ' + public_key + "\n").encode()
    create_only(HOME / ".ssh/authorized_keys", key_line, 0o644)
    create_only(CONF / "config.json", json.dumps(config, sort_keys=True, indent=2).encode())
    print("Restricted deployment receiver installed. SHA256 " + digest(receiver))
    print("No application secrets, website configuration or running applications changed.")
    print("Verify the host ed25519 public key through this trusted terminal before adding GitHub SSH_KNOWN_HOSTS:")
    print(call("/usr/bin/ssh-keygen", "-lf", "/etc/ssh/ssh_host_ed25519_key.pub").decode().strip())
    print(Path("/etc/ssh/ssh_host_ed25519_key.pub").read_text().strip())


def store_secrets():
    path = CONF / "app.env"
    require(CONF.is_dir() and not path.exists(), "Initialize first; existing secrets are never overwritten")
    require(sys.stdin.isatty(), "Enter secrets in an interactive terminal, never chat or a pipeline")
    fields = ["DEEPSEEK_API_KEY", "COS_SECRET_ID", "COS_SECRET_KEY", "COS_BUCKET", "COS_REGION",
              "PPT_INVITE_PASSWORD"]
    values = {}
    for name in fields:
        value = getpass.getpass(name + " (hidden): ")
        require(value and not any(c in value for c in "\r\n\x00"), "Empty or multiline setting: " + name)
        require(value == value.strip(), "Leading/trailing spaces are not allowed: " + name)
        if name == "PPT_INVITE_PASSWORD":
            require(len(value) >= 12, "Use an invitation password of at least 12 characters")
        values[name] = value
    require(re.fullmatch(r"[a-z0-9-]+-\d+", values["COS_BUCKET"]), "Invalid COS bucket name")
    require(re.fullmatch(r"[a-z]+-[a-z]+(?:-\d+)?", values["COS_REGION"]), "Invalid COS region")
    values["PPT_SESSION_SECRET"] = secrets.token_urlsafe(48)
    create_only(path, "".join(k + "=" + v + "\n" for k, v in values.items()).encode())
    print("Server-only secrets stored with root ownership and mode 0600; no values printed.")


def reload_caddy(container, data):
    actual = call("/usr/bin/docker", "exec", container, "cat", "/etc/caddy/Caddyfile")
    require(actual == data, "Container did not see the in-place configuration update")
    call("/usr/bin/docker", "exec", container, "caddy", "validate",
         "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile")
    call("/usr/bin/docker", "exec", container, "caddy", "reload",
         "--config", "/etc/caddy/Caddyfile", "--adapter", "caddyfile")


def check_url(url):
    require(re.fullmatch(r"https://[a-z0-9.-]+(?::443)?/?", url), "Supply an HTTPS site root")
    with urllib.request.urlopen(url, timeout=20) as response:
        require(response.status == 200, "Existing website is not healthy before update")


def connect_site(args):
    config = json.loads((CONF / "config.json").read_text())
    fresh, path = inspect_caddy(config["caddy_container"], config["caddy_network"])
    require(fresh == config, "Network changed since initialization; inspect before continuing")
    require(re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}", args.domain),
            "Supply only the test hostname, without scheme or port")
    require(args.domain not in path.read_text(), "Test hostname already appears in existing configuration")
    check_url(args.existing_site)
    original = path.read_bytes()
    block = ("\n# BEGIN yuling-ppt-test\n" + args.domain + " {\n"
             "    encode zstd gzip\n"
             "    reverse_proxy " + config["gateway"] + ":5000\n"
             "}\n# END yuling-ppt-test\n").encode()
    candidate = original + block
    # Validate in the actual running Caddy environment before changing the bind-mounted file.
    call("/usr/bin/docker", "exec", "-i", config["caddy_container"], "caddy",
         "validate", "--config", "-", "--adapter", "caddyfile", data=candidate)
    create_only(CONF / "Caddyfile.before", original)
    receipt = {"path": str(path), "original_sha256": digest(original), "managed_sha256": digest(candidate),
               "domain": args.domain, "existing_site": args.existing_site}
    create_only(CONF / "caddy-receipt.json", json.dumps(receipt, indent=2).encode())
    def apply(data):
        reload_caddy(config["caddy_container"], data)
        check_url(args.existing_site)
    replace_in_place(path, original, candidate, apply)
    print("Test hostname appended, validated and hot-reloaded. Original site check passed.")
    print("First publish can now run. If it fails, use restore-site; do not restart Caddy.")


def restore_site():
    config = json.loads((CONF / "config.json").read_text())
    receipt = json.loads((CONF / "caddy-receipt.json").read_text())
    fresh, path = inspect_caddy(config["caddy_container"], config["caddy_network"])
    require(fresh == config and str(path) == receipt["path"], "Caddy mount or network changed")
    original = (CONF / "Caddyfile.before").read_bytes()
    require(digest(original) == receipt["original_sha256"], "Backup checksum mismatch")
    current = path.read_bytes()
    if current == original:
        print("Original site configuration already restored")
        return
    require(digest(current) == receipt["managed_sha256"], "Owner edited Caddy since setup; refusing overwrite")
    replace_in_place(path, current, original, lambda data: reload_caddy(config["caddy_container"], data))
    check_url(receipt["existing_site"])
    print("Only the appended test site was removed; original configuration restored and verified.")


def main():
    require(os.geteuid() == 0, "Run reviewed setup with sudo in your terminal")
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("prepare")
    setup.add_argument("--caddy-container", required=True)
    setup.add_argument("--caddy-network", required=True)
    setup.add_argument("--public-key", type=Path, required=True)
    commands.add_parser("secrets")
    site = commands.add_parser("connect-site")
    site.add_argument("--domain", required=True)
    site.add_argument("--existing-site", required=True)
    commands.add_parser("restore-site")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
    elif args.command == "secrets":
        store_secrets()
    elif args.command == "connect-site":
        connect_site(args)
    else:
        restore_site()


if __name__ == "__main__":
    try:
        main()
    except (RuntimeError, OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        print(str(error) if isinstance(error, RuntimeError) else "Setup failed; inspect host state before retry.",
              file=sys.stderr)
        sys.exit(1)

