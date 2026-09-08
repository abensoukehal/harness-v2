import os
import subprocess
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))
BIN = ROOT / "bin"


def run(cmd, *args, ws=None):
    env = dict(os.environ)
    if ws:
        env["HARNESS_WORKSPACE"] = str(ws)
    return subprocess.run([str(BIN / cmd), *map(str, args)], env=env, capture_output=True, text=True)


def sh(*args, cwd):
    return subprocess.run(args, cwd=str(cwd), check=True, capture_output=True, text=True).stdout.strip()


def make_repo(path):
    path.mkdir(parents=True)
    sh("git", "init", "-q", cwd=path)
    sh("git", "symbolic-ref", "HEAD", "refs/heads/main", cwd=path)
    sh("git", "config", "user.email", "t@example.com", cwd=path)
    sh("git", "config", "user.name", "t", cwd=path)
    (path / "README").write_text("x\n")
    sh("git", "add", ".", cwd=path)
    sh("git", "commit", "-q", "-m", "init", cwd=path)
    return path


def make_workspace(root, client="example-env"):
    done = run("init", client, "--root", root)
    assert done.returncode == 0, done.stderr
    return Path(done.stdout.strip())


TAIL = textwrap.dedent("""
    delivery:
      base_branch: main
      target_branch: main
      branch_prefix: feature/
      mode: pr
      commit_author:
        name: Example Dev
        email: dev@example.com
    notify:
      telegram:
        chat_id_ref: telegram_chat_id
      events: [plan_ready, run_finished, needs_answer]
    test_runner:
      %s
    budget:
      tokens_per_feature: 100000
    qa:
      max_fixes: 3
""")

WEB_DEV = ("python3 -c \"import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:'+os.environ['PORT_API']+'/')\""
           " && echo \"booting with $DB_PASSWORD\" && echo \"ready on ${PORT_WEB}\" && sleep 60")


def env_config(web_health='log: "ready on"', web_timeout=15, web_dev=WEB_DEV, api_seed="echo seeded > seed.marker"):
    return textwrap.dedent("""
        client: example-env
        stacks:
          api:
            repo: svc
            path: repos/svc
            commands:
              dev: python3 -m http.server ${PORT_API} --bind 127.0.0.1
            env_file: api.env
            health:
              http: http://127.0.0.1:${PORT_API}/
              expect_status: 200
            health_timeout_s: 15
            seed: %s
          web:
            repo: web
            path: repos/web
            commands:
              dev: %s
            env_file: web.env
            depends_on: [api]
            health:
              %s
            health_timeout_s: %d
    """ % (api_seed, web_dev, web_health, web_timeout)) + TAIL % "{api: pytest, web: playwright}"


MONO_CONFIG = textwrap.dedent("""
    client: example-mono
    stacks:
      a:
        repo: mono
        path: repos/mono/apps/a
        commands: {dev: sleep 60}
        health: {log: never}
      b:
        repo: mono
        path: repos/mono/apps/b
        commands: {dev: sleep 60}
        health: {log: never}
""") + TAIL % "{a: pytest, b: pytest}"


def env_workspace(root, slug="hello", config=None, repos=("svc", "web")):
    ws = make_workspace(root)
    (ws / "product" / "client.config.yaml").write_text(config or env_config())
    for repo in repos:
        make_repo(ws / "repos" / repo)
    (ws / "secrets" / "api.env").write_text("API_KEY=abcd1234\n")
    (ws / "secrets" / "web.env").write_text("DB_PASSWORD=hunter2-secret\n")
    assert run("new", slug, ws=ws).returncode == 0
    from harness.config import create_state
    create_state(ws, slug, "service")
    return ws
