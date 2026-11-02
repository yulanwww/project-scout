"""Conservative bidirectional Git sync. No force, reset, clean, rebase or deletions."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

from config import configured_branch, configured_remote, git_executable, project_path


class SyncError(RuntimeError):
    pass


def allowed(path):
    p = Path(path)
    if p.is_absolute() or '..' in p.parts or any(x.startswith('.') for x in p.parts[:-1]):
        return False
    if p.name in ('.gitkeep', '.gitignore', '.gitattributes'):
        return True
    if p.name.startswith('.'):
        return False
    return p.suffix.lower() in ('.md', '.base') or (p.parts[0] == 'Attachments' and p.suffix.lower() in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.svg', '.pdf'))


def check_content(path, data):
    if len(data) > 20_000_000:
        raise SyncError('文件超过 20 MB，暂不自动上传：' + path)
    if Path(path).suffix.lower() not in ('.png', '.jpg', '.jpeg', '.webp', '.gif', '.pdf'):
        text = data.decode('utf-8-sig')
        if re.search(r'(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_-]{30,}|-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----|(?im:^\s*(?:password|api_key|access_token|secret)\s*[:=]\s*["\x27]?[A-Za-z0-9_+/=-]{12,}))', text):
            raise SyncError('检测到疑似凭据，停止上传：' + path)


class GitSync:
    def __init__(self, vault=None, state=None, git=None, guard=None, remote=None, branch=None):
        self.vault = Path(vault) if vault else project_path('PROJECT_SCOUT_VAULT_PATH', 'Vault')
        self.vault = self.vault.resolve()
        self.state = Path(state) if state else project_path('PROJECT_SCOUT_STATE_DIR', '.local') / 'sync'
        self.git = git or git_executable()
        self.remote = remote or configured_remote()
        self.branch = branch or configured_branch()
        self.guard = guard or self.private_guard

    def run_git(self, *args, check=True, input=None):
        env = {**os.environ, 'GIT_TERMINAL_PROMPT':'0', 'GCM_INTERACTIVE':'Never'}
        try:
            r = subprocess.run([self.git, '-C', str(self.vault), *args], input=input if input is not None else b"", capture_output=True, timeout=90, env=env)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise SyncError('Git 请求失败或超时；本地修改保留') from e
        if check and r.returncode:
            raise SyncError('Git ' + args[0] + ' 失败；本地内容与提交保留（退出码 ' + str(r.returncode) + '）')
        return r

    def text(self, *args):
        return self.run_git(*args).stdout.decode('utf-8').strip()

    def private_guard(self):
        from github_library import GitHubStore
        GitHubStore().metadata()

    @contextmanager
    def lock(self):
        self.state.mkdir(parents=True, exist_ok=True)
        f = open(self.state/'run.lock', 'a+b')
        acquired = False
        try:
            f.seek(0, 2)
            if f.tell() == 0: f.write(b'0'); f.flush()
            f.seek(0)
            if os.name == 'nt':
                import msvcrt
                try: msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                except OSError: raise SyncError('已有同步正在运行')
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
            yield
        finally:
            if acquired:
                f.seek(0)
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
            f.close()

    def paths(self, *args):
        return [p.decode('utf-8') for p in self.run_git(*args).stdout.split(b'\0') if p]

    def inspect_tree(self, ref):
        for path in self.paths('ls-tree', '-r', '--name-only', '-z', ref):
            if not allowed(path):
                raise SyncError('远端/已提交文件超出同步白名单：' + path)
            mode = self.text('ls-tree', ref, '--', path).split()[0]
            if mode not in ('100644', '100755'):
                raise SyncError('不自动同步符号链接或子模块：' + path)
            check_content(path, self.run_git('show', ref+':'+path).stdout)

    def backups(self, local, remote):
        key = hashlib.sha256((local + remote).encode()).hexdigest()[:24]
        dest = self.state/'conflicts'/key
        dest.mkdir(parents=True, exist_ok=True)
        if (dest/'index.json').exists():
            return str(dest)
        paths = self.paths('diff', '--name-only', '-z', local, remote)
        index = []
        for path in paths:
            name = hashlib.sha256(path.encode()).hexdigest()[:16]
            for side, ref in [('local',local),('remote',remote)]:
                r = self.run_git('show', ref+':'+path, check=False)
                if r.returncode == 0: (dest/(name+'.'+side+Path(path).suffix)).write_bytes(r.stdout)
            index.append({'path':path,'backup_prefix':name})
        (dest/'index.json').write_text(json.dumps({'local':local,'remote':remote,'files':index},ensure_ascii=False,indent=2),encoding='utf-8')
        return str(dest)

    def sync(self):
        with self.lock():
            if Path(self.text('rev-parse','--show-toplevel')).resolve() != self.vault:
                raise SyncError('Vault 不是独立 Git 仓库根目录')
            if self.text('remote','get-url','origin') != self.remote:
                raise SyncError('origin 与已配置的 GitHub 仓库不符')
            if self.text('branch','--show-current') != self.branch:
                raise SyncError('当前分支与 PROJECT_SCOUT_BRANCH 配置不符')
            if self.paths('diff','--name-only','--diff-filter=U','-z'):
                raise SyncError('存在未解决冲突，停止自动同步')
            for marker in ('MERGE_HEAD','CHERRY_PICK_HEAD','REVERT_HEAD'):
                if Path(self.text('rev-parse','--git-path',marker)).is_absolute():
                    exists = Path(self.text('rev-parse','--git-path',marker)).exists()
                else: exists = (self.vault/self.text('rev-parse','--git-path',marker)).exists()
                if exists: raise SyncError('存在未完成的 Git 操作，停止同步')
            self.guard()
            if self.paths('ls-files','--deleted','-z') or self.paths('diff','--cached','--name-only','--diff-filter=D','-z'):
                raise SyncError('检测到删除操作；未经确认不自动提交或传播删除')
            changed = set(self.paths('diff','--name-only','-z')) | set(self.paths('diff','--cached','--name-only','-z')) | set(self.paths('ls-files','--others','--exclude-standard','-z'))
            for path in changed:
                if not allowed(path): raise SyncError('不允许自动上传的文件：'+path)
                file = self.vault/path
                if file.is_symlink() or not file.resolve().is_relative_to(self.vault):
                    raise SyncError('路径包含符号链接：'+path)
                check_content(path,file.read_bytes())
            # Only explicitly allowlisted files, never git add -A or the parent project.
            if changed:
                for path in sorted(changed): self.run_git('add','--',path)
                if self.run_git('diff','--cached','--quiet',check=False).returncode == 1:
                    self.run_git('commit','-m','Project Scout: sync Obsidian notes '+datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC'))
            self.run_git('fetch','origin',self.branch)
            local = self.text('rev-parse','HEAD')
            remote = self.text('rev-parse','origin/'+self.branch)
            self.inspect_tree('HEAD')
            self.inspect_tree('origin/'+self.branch)
            if local != remote:
                base = self.text('merge-base',local,remote)
                if self.paths('diff','--name-only','--diff-filter=D','-z',base,remote):
                    backup = self.backups(local,remote)
                    raise SyncError('远端包含删除；未改动工作区。双方备份：'+backup)
                if self.text('status','--porcelain'):
                    raise SyncError('同步期间笔记仍在编辑，下次再试；本地修改保留')
                if base == local:
                    self.run_git('merge','--ff-only','origin/'+self.branch)
                elif base != remote:
                    merged = self.run_git('merge-tree','--write-tree',local,remote,check=False)
                    if merged.returncode:
                        backup = self.backups(local,remote)
                        raise SyncError('双方有冲突，未改动工作区。双方备份：'+backup)
                    tree = merged.stdout.decode().splitlines()[0]
                    commit = self.run_git('commit-tree',tree,'-p',local,'-p',remote,'-m','Project Scout: merge non-conflicting Obsidian updates').stdout.decode().strip()
                    self.run_git('merge','--ff-only',commit)
                self.guard()
                self.run_git('push','origin','HEAD:refs/heads/'+self.branch)
            self.run_git('fetch','origin',self.branch)
            if self.text('rev-parse','HEAD') != self.text('rev-parse','origin/'+self.branch):
                raise SyncError('远端在同步中发生变化，下次重试；未强推')
            self.guard()
            return {'state':'synced','commit':self.text('rev-parse','HEAD'),'dirty':bool(self.text('status','--porcelain')),'private':True}


def main():
    parser=argparse.ArgumentParser()
    args=parser.parse_args()
    sync=GitSync()
    try:
        result=sync.sync()
        code=0
    except Exception as exc:
        result={'state':'attention_or_offline','message':str(exc)}
        code=1
    result['checked_at']=datetime.now().isoformat(timespec='seconds')
    sync.state.mkdir(parents=True,exist_ok=True)
    (sync.state/'status.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    if getattr(__import__('sys'),'stdout',None): print(json.dumps(result,ensure_ascii=False))
    return code


if __name__=='__main__':
    raise SystemExit(main())
