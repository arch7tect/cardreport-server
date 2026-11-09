"""Real threads and SIGTERM must wake a worker configured with a long poll."""

import json
import os
import subprocess
from uuid import uuid4

import pytest

from cardreport_server.settings import Settings

pytestmark = pytest.mark.container


def test_slots_completion_and_sigterm_wake_without_poll_delay(
    integration_settings: Settings,
) -> None:
    project = os.environ["COMPOSE_PROJECT_NAME"]
    assert project.startswith("cardreport-test-")
    name = project + "-wakeup-" + uuid4().hex[:8]
    code = """import json,os,signal,threading,time
from types import SimpleNamespace
from queue import SimpleQueue
from uuid import uuid4
from cardreport_server import jobs,maintenance
from cardreport_server.settings import Settings
from cardreport_server.worker import Worker
settings=Settings(database_url='postgresql://test:test@localhost/test',s3_endpoint='http://localhost:8333',s3_access_key='test',s3_secret_key='test',s3_bucket='unit-test',poll_seconds=30)
worker=Worker(settings)
worker.db.open=lambda: None
worker.db.close=lambda: None
worker.storage.check=lambda: None
jobs.reap=lambda *args: 0
jobs.heartbeat=lambda db,settings,attempts: {a.token for a in attempts}
maintenance.cleanup=lambda *args: None
attempts=[SimpleNamespace(token=uuid4(),index=i) for i in range(3)]
queued=iter(attempts)
claims=[]
def claim(*args):
 claims.append(time.monotonic())
 return next(queued,None)
jobs.claim=claim
started=[threading.Event() for _ in attempts]
release=[threading.Event() for _ in attempts]
errors=[]
stop_at=[]
waiting_after_third=threading.Event()
signal_woke=threading.Event()
class ObservedQueue(SimpleQueue):
 def __init__(self):
  super().__init__()
  self.notifications=0
 def put(self,item):
  self.notifications+=1
  super().put(item)
 def get(self,block=True,timeout=None):
  # Maintenance and first attempt notifications are consumed before this wait.
  if started[2].is_set() and self.notifications==2 and self.empty() and timeout>5:
   waiting_after_third.set()
  result=super().get(block,timeout)
  if worker.stopping.is_set(): signal_woke.set()
  return result
worker._wakeups=ObservedQueue()
def execute(running):
 i=running.attempt.index
 started[i].set()
 assert release[i].wait(20), 'Attempt did not get released'
worker.execute=execute
def control():
 try:
  assert started[0].wait(20), 'Worker never started'
  assert started[1].wait(5), 'Second slot waited for poll interval'
  assert len(claims)==2, 'Worker overclaimed while full'
  assert claims[1]-claims[0]<5
  release[0].set()
  assert started[2].wait(5), 'Completion did not wake next claim'
  assert waiting_after_third.wait(5), 'Supervisor did not reach idle wait'
  stop_at.append(time.monotonic())
  os.kill(os.getpid(),signal.SIGTERM)
  assert signal_woke.wait(5), 'SIGTERM did not wake supervisor'
 except BaseException as error:
  errors.append(str(error))
  worker.stop()
 finally:
  for event in release: event.set()
controller=threading.Thread(target=control,daemon=True)
controller.start()
result=worker.run()
controller.join(timeout=1)
assert not errors, errors
assert result==0 and len(claims)==3
assert time.monotonic()-stop_at[0]<5, 'SIGTERM drain waited for poll interval'
print(json.dumps({'claims':len(claims),'initial_gap':claims[1]-claims[0],'stop_delay':time.monotonic()-stop_at[0]}))
"""
    try:
        result = subprocess.run(
            [
                "docker",
                "run",
                "--rm",
                "--name",
                name,
                "--label",
                f"cardreport-test={project}",
                "cardreport-server:local",
                "/app/.venv/bin/python",
                "-c",
                code,
            ],
            capture_output=True,
            text=True,
            timeout=45,
        )
        assert result.returncode == 0, (result.stdout, result.stderr)
        assert json.loads(result.stdout)["claims"] == 3
    finally:
        subprocess.run(
            ["docker", "rm", "--force", name],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
