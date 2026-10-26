"""Confirmed recurring-error guard. Python 3.12 standard library only.

Local ownership is the trust boundary: this is not protection against a user
rewriting all checkpoints, disabling hooks, or replacing the Python runtime.
"""
import argparse
import contextlib
import datetime
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

VERSION = '1.0.0'
SELF = Path(__file__).resolve()


class Blocked(Exception):
    pass


def require(condition, reason):
    if not condition:
        raise Blocked(reason)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8'))
    except (OSError, ValueError) as exc:
        raise Blocked('Missing or damaged JSON: ' + str(path)) from exc


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Same-directory rename; an interrupted ledger/checkpoint pair fails closed.
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as f:
        f.write(canonical(value) + b'\n')
        f.flush()
        os.fsync(f.fileno())
        temp = Path(f.name)
    temp.replace(path)


@contextlib.contextmanager
def lock(home):
    path = home / 'write.lock'
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise Blocked('Ledger/installation lock exists; inspect the owning process before recovery') from exc
    try:
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        yield
    finally:
        path.unlink()


def ledger(home):
    try:
        rows = [json.loads(line) for line in (home / 'ledger.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    except (OSError, ValueError) as exc:
        raise Blocked('Missing/damaged incident ledger; restore from retained evidence') from exc
    previous = None
    reports, confirmations, occurrences, floors, counts = {}, {}, set(), {}, {}
    for seq, row in enumerate(rows, 1):
        payload = {k: v for k, v in row.items() if k != 'hash'}
        require(row.get('seq') == seq and row.get('previous_hash') == previous and
                row.get('hash') == sha(canonical(payload)), 'Ledger chain mismatch')
        previous = row['hash']
        kind = row.get('kind')
        event = row.get('event_id')
        if kind == 'report':
            occurrence = row.get('occurrence', event)
            require(event and event not in reports and occurrence not in occurrences, 'Duplicate incident')
            require(row.get('project'), 'Incident project missing')
            reports[event] = row
            occurrences.add(occurrence)
        elif kind in ('confirm', 'correct'):
            require(event in reports and row.get('owner') and row.get('source'), 'Confirmation provenance missing')
            cls = row.get('class_id')
            require(isinstance(cls, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,100}', cls), 'Invalid stable class ID')
            if kind == 'confirm':
                require(event not in confirmations, 'Incident already confirmed; append a correction instead')
            else:
                require(event in confirmations and row.get('reason'), 'Correction must preserve prior confirmation and reason')
            confirmations[event] = cls
        elif kind == 'note':
            require(event in reports and row.get('text'), 'Invalid incident note')
        else:
            raise Blocked('Unknown ledger operation')
        # Once crossed, retain that class/project requirement even after correction.
        counts = {}
        affected = {}
        for eid, cls in confirmations.items():
            counts[cls] = counts.get(cls, 0) + 1
            affected.setdefault(cls, set()).add(reports[eid]['project'])
        for cls, count in counts.items():
            historical = max((required.get(cls, 0) for required in floors.values()), default=0)
            if max(count, historical) >= 3:
                for project in affected[cls]:
                    floors.setdefault(project, {})[cls] = max(count, historical)
    require(read_json(home / 'ledger-head.json') == {'seq': len(rows), 'hash': previous},
            'Ledger truncation/checkpoint mismatch')
    return rows, reports, confirmations, counts, floors


def append(home, row):
    with lock(home):
        rows, *_ = ledger(home)
        row = dict(row, seq=len(rows) + 1, previous_hash=rows[-1]['hash'] if rows else None,
                   recorded_at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        row['hash'] = sha(canonical(row))
        # Validate the proposed operation in isolation before touching the ledger.
        with tempfile.TemporaryDirectory(prefix='guard-ledger-') as tmp:
            test = Path(tmp)
            (test / 'ledger.jsonl').write_bytes(b''.join(canonical(x) + b'\n' for x in rows + [row]))
            write_json(test / 'ledger-head.json', {'seq': row['seq'], 'hash': row['hash']})
            ledger(test)
        with (home / 'ledger.jsonl').open('ab') as f:
            f.write(canonical(row) + b'\n'); f.flush(); os.fsync(f.fileno())
        write_json(home / 'ledger-head.json', {'seq': row['seq'], 'hash': row['hash']})
    render(home)


def render(home):
    rows, reports, confirmed, counts, floors = ledger(home)
    lines = ['# 错误记录', '', '由结构化台账生成；不手工维护计数。', '',
             f'事件 {len(reports)} 条；经确认 {len(confirmed)} 条。', '',
             '本地文件拥有者可绕过 hooks；本工具不能保证识别未编码的错误。', '']
    for event, report in reports.items():
        cls = confirmed.get(event)
        lines += ['## ' + event + '：' + report['title'], '',
                  '- 项目：' + report['project'],
                  '- 正式分类：' + (cls or '待用户确认，不计数'),
                  '- 本类别累计：' + (str(counts.get(cls, 0)) if cls else '未计数'),
                  '- 源码：' + str(report.get('source_commit') or '本地诊断，无源码提交'), '']
        for label in ('verified_facts', 'unverified_facts'):
            lines += ['### ' + ('已验证事实' if label == 'verified_facts' else '待验证'), '']
            lines += ['- ' + x for x in report.get(label, [])]
        lines += ['', '### 证据 SHA256', '']
        lines += ['- ' + k + ': `' + v + '`' for k, v in report.get('evidence_sha256', {}).items()]
        lines += ['']
    lines += ['## 永久防护要求', '', '```json', json.dumps(floors, ensure_ascii=False, indent=2), '```', '']
    (home / '错误记录.md').write_text('\n'.join(lines), encoding='utf-8')


def git(repo, *args, input=None, allow_failure=False):
    result = subprocess.run(['git', '-C', str(repo), *args], input=input, capture_output=True, timeout=40)
    require(allow_failure or result.returncode == 0, 'Git operation failed: ' + ' '.join(args[:2]))
    return result


def git_text(repo, *args):
    return git(repo, *args).stdout.decode('utf-8').strip()


def identity(repo):
    common = Path(git_text(repo, 'rev-parse', '--path-format=absolute', '--git-common-dir')).resolve()
    st = common.stat()
    # Same physical common-dir across linked worktrees and Windows path aliases.
    key = sha(f'{st.st_dev}:{st.st_ino}'.encode())[:24]
    return key, common


def registered(home, repo):
    key, common = identity(repo)
    registry = read_json(home / 'registry.json')
    require(key in registry, 'Repository not enrolled; no enforcement claim')
    config = read_json(home / 'repos' / (key + '.json'))
    require(sha(canonical(config)) == registry[key], 'Enrollment policy changed without verified reinstallation')
    require(config['checker_sha256'] == sha(SELF.read_bytes()), 'Checker version/hash mismatch')
    require(config['policy']['checker_version'] == VERSION, 'Rule/checker version mismatch')
    return key, config


def clean_environment():
    return {k: v for k, v in os.environ.items() if not k.startswith('GIT_') and
            k not in ('PYTHONPATH', 'PYTHONHOME', 'NODE_OPTIONS')}


def source_file(repo, tree, path):
    require(not Path(path).is_absolute() and '..' not in Path(path).parts, 'Unsafe source path')
    return git(repo, 'show', tree + ':' + path).stdout


def lifecycle(repo, tree, branch, policy, pr=None):
    rules = policy.get('lifecycle', {})
    if not rules.get('required'):
        return 'local-only: Issue/PR lifecycle unavailable'
    grandfather = rules.get('grandfathered', {}).get(branch)
    if grandfather and (pr is None or pr.get('created_at', 'z') < rules['effective_at']):
        require(grandfather.get('created_at', 'z') < rules['effective_at'] and grandfather.get('url'),
                'Invalid grandfathered PR receipt')
        return 'existing PR predates effective_at'
    match = re.fullmatch(r'(?:issue/|claude/issue-)([1-9][0-9]*)-[a-z0-9-]+', branch)
    require(match, 'Branch must identify the approved Issue')
    number = match.group(1)
    approved = rules.get('issues', {}).get(number)
    require(approved and approved.get('url') and approved.get('approval_source'), 'Issue/owner approval receipt missing')
    plan = source_file(repo, tree, approved['plan']).decode('utf-8')
    require(re.search(r'^status: accepted\s*$', plan, re.M) and
            ('issue: ' + approved['url']) in plan and re.search(r'^base: [0-9a-f]{40}\s*$', plan, re.M),
            'Issue/accepted plan/base mismatch')
    if approved.get('plan_sha256'):
        require(sha(plan.encode()) == approved['plan_sha256'], 'Approved plan content changed')
    if approved.get('adr'):
        adr = source_file(repo, tree, approved['adr']).decode('utf-8')
        require(re.search(r'^status: accepted\s*$', adr, re.M) and ('issue: ' + approved['url']) in adr,
                'Required ADR not accepted for this Issue')
        if approved.get('adr_sha256'):
            require(sha(adr.encode()) == approved['adr_sha256'], 'Accepted ADR changed')
    else:
        require('adr: not-required' in plan, 'ADR decision missing')
    if pr and pr.get('created_at', 'z') >= rules['effective_at']:
        require(re.search(r'(?i)\bcloses\s+#' + number + r'\b', pr.get('body') or ''), 'PR must close the same Issue')
    return 'accepted lifecycle receipts verified'


def run_protection(repo, tree, cls, rule, receipts):
    command = rule.get('command')
    require(isinstance(command, list) and command and all(isinstance(x, str) and x for x in command),
            'Executable regression command missing for ' + cls)
    timeout = rule.get('timeout')
    require(isinstance(timeout, (int, float)) and 0 < timeout <= 300, 'Invalid regression timeout')
    mutation = rule.get('red', {})
    require(mutation.get('before') and mutation.get('after') != mutation.get('before') and
            isinstance(mutation.get('exit'), int) and 0 < mutation['exit'] < 126,
            'Deliberate failing-input proof missing for ' + cls)
    path = Path(mutation.get('path', ''))
    require(str(path) != '.' and not path.is_absolute() and '..' not in path.parts, 'Unsafe mutation path')
    with tempfile.TemporaryDirectory(prefix='engineering-guard-source-') as directory:
        snapshot = Path(directory)
        archive = git(repo, 'archive', '--format=tar', tree).stdout
        with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
            require(all(x.isdir() or x.isfile() for x in tar.getmembers()), 'Links/special files require explicit safe snapshot support')
            tar.extractall(snapshot, filter='data')
        target = snapshot / path
        require(target.is_file(), 'Mutation target missing from staged/pushed source')
        original = target.read_bytes()
        before, after = mutation['before'].encode(), mutation['after'].encode()
        require(original.count(before) == 1, 'Mutation must match exactly once')
        argv = [sys.executable if x == '{python}' else x for x in command]
        executable = shutil.which(argv[0]) or argv[0]
        require(Path(executable).is_file(), 'Regression executable unavailable')
        results = []
        for name, data, expected in [('green', original, 0), ('red', original.replace(before, after), mutation['exit']), ('restored', original, 0)]:
            target.write_bytes(data)
            try:
                p = subprocess.run(argv, cwd=snapshot, env=clean_environment(), capture_output=True, timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                raise Blocked('Regression timed out for ' + cls) from exc
            results.append({'phase': name, 'exit': p.returncode, 'stdout_sha256': sha(p.stdout), 'stderr_sha256': sha(p.stderr)})
            require(p.returncode == expected, f'{cls}: {name} returned {p.returncode}, expected {expected}')
        receipts.append({'class_id': cls, 'tree': tree, 'rule_sha256': sha(canonical(rule)),
                         'executable_sha256': sha(Path(executable).read_bytes()), 'runs': results})


def check_tree(home, repo, tree, branch, config, pr=None):
    _, _, _, _, floors = ledger(home)
    policy = config['policy']
    require(policy.get('schema') == 1 and policy.get('checker_version') == VERSION, 'Invalid rules schema/version')
    required = dict(floors.get(policy['project'], {}))
    for cls, rule in policy.get('classes', {}).items():
        require(isinstance(rule.get('count'), int) and rule['count'] >= 0, 'Invalid public class count')
        if rule['count'] >= 3:
            required[cls] = max(required.get(cls, 0), rule['count'])
    receipt = {'tree': tree, 'branch': branch, 'checker_sha256': sha(SELF.read_bytes()),
               'policy_sha256': sha(canonical(policy)), 'python': sys.version,
               'platform': platform.platform(), 'architecture': platform.machine(),
               'environment_sha256': sha(canonical(clean_environment())), 'protections': [],
               'workflow': lifecycle(repo, tree, branch, policy, pr)}
    for cls, count in sorted(required.items()):
        rule = policy.get('classes', {}).get(cls)
        require(rule and rule.get('count', 0) >= count, 'Required protection/snapshot missing: ' + cls)
        require(config.get('entry_points', {}).get('git'), 'Git entry configuration missing: ' + cls)
        if not policy.get('lifecycle', {}).get('required') and policy.get('local_only_exception'):
            receipt['ci_gap'] = 'owner-approved local-only exception; remote lifecycle/CI not enforced'
        else:
            require(config.get('entry_points', {}).get('ci'), 'Required CI entry configuration missing: ' + cls)
            ci_source = source_file(repo, tree, policy['ci_entry']).decode('utf-8')
            require(re.search(r'(?m)^\s*(?:-\s*)?run:.*engineering_guard\.py ci\b', ci_source),
                    'CI must invoke the shared checker')
        run_protection(repo, tree, cls, rule, receipt['protections'])
    folder = home / 'receipts'
    filename = sha(canonical(receipt)) + '.json'
    write_json(folder / filename, receipt)
    return receipt


def check(home, repo, stage=False, commit=None, branch=None):
    _, config = registered(home, repo)
    branch = branch or git_text(repo, 'branch', '--show-current')
    tree = git_text(repo, 'write-tree') if stage else git_text(repo, 'rev-parse', (commit or 'HEAD') + '^{tree}')
    return check_tree(home, repo, tree, branch, config)


def push(home, repo, data):
    require(data.strip(), 'No push ref updates supplied')
    for line in data.decode('utf-8').splitlines():
        fields = line.split()
        require(len(fields) == 4, 'Malformed pre-push input')
        local_ref, local_sha, remote_ref, remote_sha = fields
        require(remote_ref not in ('refs/heads/main', 'refs/heads/master'), 'Direct push/delete of main/master is prohibited')
        require(re.fullmatch('[0-9a-f]{40,64}', local_sha) and re.fullmatch('[0-9a-f]{40,64}', remote_sha), 'Invalid push object ID')
        if set(local_sha) == {'0'}:
            continue
        require(remote_ref.startswith('refs/heads/'), 'Non-branch publication needs separate review')
        args = ['rev-list', '--reverse', local_sha]
        if set(remote_sha) != {'0'}:
            args.append('^' + remote_sha)
        else:
            base = git(repo, 'rev-parse', '--verify', 'origin/main', allow_failure=True)
            if base.returncode == 0:
                args.append('^' + base.stdout.decode().strip())
        commits = git_text(repo, *args).splitlines()
        for commit in commits or [local_sha]:
            check(home, repo, commit=commit, branch=remote_ref.removeprefix('refs/heads/'))


def init(home):
    home.mkdir(parents=True, exist_ok=True)
    if (home / 'ledger.jsonl').exists() or (home / 'ledger-head.json').exists():
        ledger(home)
    else:
        (home / 'ledger.jsonl').write_bytes(b'')
        write_json(home / 'ledger-head.json', {'seq': 0, 'hash': None})
    if not (home / 'registry.json').exists():
        write_json(home / 'registry.json', {})
    if not (home / 'settings.json').exists():
        write_json(home / 'settings.json', {'effective_at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'version': VERSION})
    render(home)


def install(home, repo, policy_path):
    ledger(home)
    policy = read_json(policy_path)
    require(policy.get('schema') == 1 and policy.get('checker_version') == VERSION and policy.get('project'), 'Invalid enrollment policy')
    key, common = identity(repo)
    registry = read_json(home / 'registry.json')
    require(key not in registry, 'Already enrolled; uninstall using the retained backup before changing installation')
    require(git(repo, 'config', '--worktree', '--get', 'extensions.worktreeConfig', allow_failure=True).returncode != 0,
            'Per-worktree configuration requires manual review')
    configured = git(repo, 'config', '--local', '--get', 'core.hooksPath', allow_failure=True)
    original = configured.stdout.decode('utf-8').strip() if configured.returncode == 0 else None
    old_dir = Path(git_text(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks'))
    hooks, backup = home / 'hooks' / key, home / 'backups' / key
    require(not hooks.exists() and not backup.exists(), 'Previous installation artifacts require review')
    originals = [x for x in old_dir.glob('*') if not x.name.endswith('.sample')]
    require(all(x.is_file() and not x.is_symlink() for x in originals), 'Custom hook structure cannot be safely chained automatically')
    hooks.mkdir(parents=True); backup.mkdir(parents=True)
    for path in originals:
        shutil.copy2(path, backup / path.name)
    installed = home / 'engineering_guard.py'
    if installed.exists():
        require(installed.read_bytes() == SELF.read_bytes(), 'Installed checker differs; explicit version migration required')
    else:
        shutil.copy2(SELF, installed)
    digest = sha(installed.read_bytes())
    bootstrap = ('import hashlib,pathlib,runpy,sys; p=pathlib.Path(sys.argv.pop(1)); '
                 f'assert hashlib.sha256(p.read_bytes()).hexdigest()=="{digest}","guard checker changed"; '
                 'runpy.run_path(str(p),run_name="__main__")')
    names = {'pre-commit', 'pre-push'} | {p.name for p in originals}
    for name in sorted(names):
        if name in ('pre-commit', 'pre-push'):
            command = ' '.join(shlex.quote(str(x).replace('\\', '/')) for x in [sys.executable, '-c', bootstrap, installed,
                                 'hook', '--home', home, '--key', key, '--name', name, '--'])
        else:
            command = 'sh ' + shlex.quote(str(backup / name).replace('\\', '/'))
        (hooks / name).write_text('#!/bin/sh\nexec ' + command + ' "$@"\n', encoding='utf-8', newline='\n')
        # DrvFS can expose an already executable file while rejecting chmod.
        # Do not require a redundant permission write; still require execution.
        if not os.access(hooks / name, os.X_OK):
            (hooks / name).chmod(0o755)
        require(os.access(hooks / name, os.X_OK), 'Installed hook is not executable')
    config = {'policy': policy, 'checker_sha256': digest, 'common_dir': str(common),
              'original_hooks_path': original, 'original_hook_directory': str(old_dir),
              'backup': str(backup), 'entry_points': {'git': True, 'ci': policy.get('ci_entry', False)},
              'hook_hashes': {p.name: sha(p.read_bytes()) for p in hooks.iterdir()}}
    with lock(home):
        write_json(home / 'repos' / (key + '.json'), config)
        registry[key] = sha(canonical(config))
        write_json(home / 'registry.json', registry)
        git(repo, 'config', '--local', 'core.hooksPath', str(hooks).replace('\\', '/'))
    return {'key': key, 'installed': True, 'entry_verified': False, 'remote_ci': 'not deployed'}


def uninstall(home, repo):
    key, config = registered(home, repo)
    active = Path(git_text(repo, 'rev-parse', '--path-format=absolute', '--git-path', 'hooks'))
    require(active.resolve() == (home / 'hooks' / key).resolve(), 'Hook configuration changed; refusing to overwrite')
    for name, digest in config['hook_hashes'].items():
        require(sha((active / name).read_bytes()) == digest, 'Installed hook modified; manual recovery required')
    with lock(home):
        if config['original_hooks_path'] is None:
            git(repo, 'config', '--local', '--unset', 'core.hooksPath')
        else:
            git(repo, 'config', '--local', 'core.hooksPath', config['original_hooks_path'])
        registry = read_json(home / 'registry.json'); del registry[key]
        write_json(home / 'registry.json', registry)
        write_json(home / 'uninstalled' / (key + '.json'), {'state': 'unprotected', 'backup_retained': config['backup']})


def update(home, repo, policy_path):
    key, config = registered(home, repo)
    policy = read_json(policy_path)
    old = config['policy']
    require(policy.get('project') == old['project'], 'Project identity cannot be renamed to evade counts')
    require(policy.get('lifecycle', {}).get('effective_at') == old.get('lifecycle', {}).get('effective_at'), 'effective_at is frozen')
    require(not old.get('lifecycle', {}).get('required') or policy.get('lifecycle', {}).get('required'), 'Cannot disable existing lifecycle gate')
    for cls, rule in old.get('classes', {}).items():
        if rule.get('count', 0) >= 3:
            require(policy.get('classes', {}).get(cls, {}).get('count', 0) >= rule['count'], 'Cannot remove permanent protection')
    config['policy'] = policy
    config['entry_points']['ci'] = policy.get('ci_entry', False)
    check_tree(home, repo, git_text(repo, 'write-tree'), git_text(repo, 'branch', '--show-current'), config)
    with lock(home):
        registry = read_json(home / 'registry.json')
        write_json(home / 'repos' / (key + '.json'), config)
        registry[key] = sha(canonical(config))
        write_json(home / 'registry.json', registry)


def hook(home, key, name, args, data):
    repo = Path.cwd()
    actual_key, config = registered(home, repo)
    require(actual_key == key, 'Hook invoked for a different repository')
    if name == 'pre-commit':
        check(home, repo, stage=True)
    elif name == 'pre-push':
        push(home, repo, data)
    previous = Path(config['backup']) / name
    if previous.exists():
        result = subprocess.run(['sh', str(previous), *args], input=data, timeout=300)
        return result.returncode
    return 0


def agent(home, payload):
    data = payload.get('tool_input', {})
    command = str(data.get('command', data.get('cmd', '')))
    # Recognize a direct shell command and its Git verb, not unrelated words
    # anywhere later in a diagnostic script. Git hooks remain authoritative
    # for indirect invocations (scripts, aliases and wrappers).
    argument = r'(?:"[^"\n]*"|\'[^\'\n]*\'|[^\s;|&]+)'
    operations = list(re.finditer(
        r'(?:^|[;|&\n])\s*git(?:\.exe)?\s+'
        r'(?P<options>(?:(?:-C|-c|--git-dir|--work-tree)\s+' + argument + r'\s+)*)'
        r'(?P<verb>commit|push)\b', command))
    if not operations:
        return {}
    try:
        for operation in operations:
            repo = Path(data.get('workdir') or data.get('cwd') or payload.get('cwd') or Path.cwd())
            match = re.search(r'-C\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))', operation['options'])
            if match:
                repo = Path(next(x for x in match.groups() if x))
            key, _ = identity(repo)
            if key not in read_json(home / 'registry.json'):
                continue
            require(not re.search(r'--no-verify|core\.hooksPath|HUSKY\s*=\s*0', command), 'Explicit hook bypass needs owner review')
            if operation['verb'] == 'push':
                # Git pre-push receives authoritative remote refs; do not invent them here.
                check(home, repo, commit='HEAD')
            else:
                check(home, repo, stage=True)
        return {}
    except (Blocked, OSError, ValueError, subprocess.SubprocessError) as exc:
        return {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                      'permissionDecisionReason': 'Engineering guard: ' + str(exc)}}


def ci(policy_file, event_file):
    policy = read_json(policy_file)
    require(policy.get('checker_sha256') == sha(SELF.read_bytes()), 'CI checker hash differs from reviewed snapshot')
    event = read_json(event_file)
    pr = event.get('pull_request')
    require(pr, 'PR context required for lifecycle verification')
    repo = Path.cwd()
    head = pr['head']['sha']
    base = pr['base']['sha']
    previous = git(repo, 'show', base + ':.engineering-guard/policy.json', allow_failure=True)
    if previous.returncode == 0:
        old = json.loads(previous.stdout)
        require(old['lifecycle']['effective_at'] == policy['lifecycle']['effective_at'], 'effective_at cannot move')
        for cls, rule in old.get('classes', {}).items():
            if rule.get('count', 0) >= 3:
                require(policy.get('classes', {}).get(cls, {}).get('count', 0) >= rule['count'], 'Permanent protection removed from CI snapshot')
    with tempfile.TemporaryDirectory(prefix='guard-ci-') as tmp:
        home = Path(tmp); init(home)
        check_tree(home, repo, git_text(repo, 'rev-parse', head + '^{tree}'), pr['head']['ref'],
                   {'policy': policy, 'entry_points': {'git': True, 'ci': True}}, pr)


def export_record(home, project, output):
    _, reports, confirmed, counts, floors = ledger(home)
    lines = ['# 项目错误记录', '', '由私有结构化台账生成的脱敏视图；不包含其他项目身份。', '']
    for event, report in reports.items():
        if report['project'] != project:
            continue
        cls = confirmed.get(event)
        lines += ['## ' + event, '', '- 状态：' + ('根因已确认' if cls else '待所有者确认；未计数'),
                  '- 分类：' + (cls or '未确认'),
                  '- 来源提交：`' + str(report.get('source_commit') or '未绑定提交') + '`']
        if cls:
            lines.append('- 同类累计（不披露其他项目）：' + str(counts.get(cls, 0)))
        lines += ['']
    if not any(r['project'] == project for r in reports.values()):
        lines += ['暂无已登记事件；这不构成无错误证明。', '']
    lines += ['## 必须持续执行的防护', '', '```json', json.dumps(floors.get(project, {}), indent=2), '```', '',
              '远端 CI 状态以实际发布和运行记录为准。本文件不能代替可执行检查。', '']
    Path(output).write_text('\n'.join(lines), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['init', 'report', 'confirm', 'correct', 'note', 'render', 'export', 'install', 'update', 'uninstall', 'check', 'hook', 'agent', 'ci'])
    parser.add_argument('--home', type=Path, default=Path.home() / '.codex/engineering-guard')
    parser.add_argument('--repo', type=Path, default=Path.cwd())
    for name in ['file', 'event', 'class-id', 'owner', 'source', 'reason', 'text', 'policy', 'key', 'name', 'commit', 'project', 'output']:
        parser.add_argument('--' + name)
    parser.add_argument('--stage', action='store_true')
    args, trailing = parser.parse_known_args()
    require(sys.version_info[:2] == (3, 12), 'Python 3.12 is required')
    home = args.home.resolve()
    if args.action == 'init':
        init(home)
    elif args.action == 'report':
        report = read_json(args.file)
        require(report.get('evidence_sha256') and report.get('title'), 'Incident evidence/title required')
        require(all(re.fullmatch('[a-f0-9]{64}', v) for v in report['evidence_sha256'].values()), 'Invalid evidence digest')
        append(home, dict(report, kind='report'))
    elif args.action in ('confirm', 'correct'):
        append(home, {'kind': args.action, 'event_id': args.event, 'class_id': args.class_id,
                      'owner': args.owner, 'source': args.source, 'reason': args.reason})
    elif args.action == 'note':
        append(home, {'kind': 'note', 'event_id': args.event, 'text': args.text})
    elif args.action == 'render':
        render(home)
    elif args.action == 'export':
        require(args.project and args.output, 'Project/output required')
        export_record(home, args.project, args.output)
    elif args.action == 'install':
        print(json.dumps(install(home, args.repo, args.policy)))
    elif args.action == 'uninstall':
        uninstall(home, args.repo)
    elif args.action == 'update':
        update(home, args.repo, args.policy)
    elif args.action == 'check':
        result = check(home, args.repo, stage=args.stage, commit=args.commit)
        print(json.dumps({'tree': result['tree'], 'checks': len(result['protections']), 'exit': 0}))
    elif args.action == 'hook':
        return hook(home, args.key, args.name, trailing[1:] if trailing[:1] == ['--'] else trailing, sys.stdin.buffer.read() if args.name == 'pre-push' else b'')
    elif args.action == 'agent':
        print(json.dumps(agent(home, json.loads(sys.stdin.buffer.read()))))
    elif args.action == 'ci':
        ci(args.policy, args.file)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (Blocked, OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('Engineering guard blocked: ' + str(error), file=sys.stderr)
        sys.exit(2)
