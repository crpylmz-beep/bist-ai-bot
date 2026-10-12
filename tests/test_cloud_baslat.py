import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch

import cloud_baslat as cloud


class LauncherTests(unittest.TestCase):
    def child(self, running=True):
        child=Mock(pid=123, returncode=1)
        child.poll.return_value=None if running else 1
        return child

    def test_two_children_started_and_cleanup(self):
        worker,web=self.child(),self.child()
        stop=Mock();stop.wait.return_value=True
        launch=Mock(side_effect=[worker,web])
        with patch.object(cloud,'stop_children') as cleanup:
            self.assertEqual(cloud.supervise(launch,stop),0)
        self.assertEqual([c.args[0] for c in launch.call_args_list],['ana_motor.py','web_server.py'])
        self.assertEqual(set(cleanup.call_args.args[0]),{'worker','web'})

    def test_worker_exit_stops_service(self):
        launch=Mock(side_effect=[self.child(False),self.child()])
        stop=Mock();stop.wait.return_value=False
        with patch.object(cloud,'stop_children') as cleanup:
            self.assertEqual(cloud.supervise(launch,stop),1)
            cleanup.assert_called_once()

    def test_web_restart_preserves_worker(self):
        worker=self.child();launch=Mock(side_effect=[worker,self.child(False),self.child()])
        stop=Mock();stop.wait.side_effect=[False,True]
        with patch.object(cloud,'stop_children') as cleanup:
            self.assertEqual(cloud.supervise(launch,stop),0)
        self.assertEqual(launch.call_count,3)
        self.assertIs(cleanup.call_args.args[0]['worker'],worker)

    def test_failed_second_start_cleans_up_first_child(self):
        worker=self.child();stop=threading.Event()
        with patch.object(cloud,'stop_children') as cleanup:
            self.assertEqual(cloud.supervise(Mock(side_effect=[worker,OSError('redacted')]),stop),1)
        self.assertEqual(cleanup.call_args.args[0],{'worker':worker})

    def test_bounded_shutdown_terminates_both_then_kills_stuck_child(self):
        worker,web=self.child(),self.child()
        worker.wait.side_effect=[subprocess.TimeoutExpired('worker',0),0]
        cloud.stop_children({'worker':worker,'web':web},timeout=0)
        worker.terminate.assert_called_once();web.terminate.assert_called_once()
        worker.kill.assert_called_once();web.kill.assert_not_called()

    def test_default_launcher_inherits_port_and_volume(self):
        stop=Mock();stop.wait.return_value=True
        with patch.dict(os.environ,{'PORT':'19876','BIST_DATA_DIR':'/tmp/mock-volume'}),patch.object(cloud.subprocess,'Popen',side_effect=[self.child(),self.child()]) as popen,patch.object(cloud,'stop_children'):
            cloud.supervise(stop=stop)
        for call in popen.call_args_list:
            self.assertEqual(call.kwargs['env']['PORT'],'19876')
            self.assertEqual(call.kwargs['env']['BIST_DATA_DIR'],'/tmp/mock-volume')
            self.assertIn('-u',call.args[0])

    @unittest.skipUnless(os.name=='posix','Railway POSIX signals')
    def test_real_sigterm_and_sigint_shutdown_and_environment(self):
        source=Path(cloud.__file__).parent
        for signum in (signal.SIGTERM,signal.SIGINT):
            with self.subTest(signal=signum),tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                for name in ('cloud_baslat.py','veri_yollari.py','cloud_bootstrap.py','disk_koruma.py'):shutil.copyfile(source/name,root/name)
                child_script='''import os,json,signal,time
from pathlib import Path
name=Path(__file__).stem
root=Path(__file__).parent
def stop(*_):
 (root/(name+'.stopped')).write_text('ok')
 raise SystemExit(0)
signal.signal(signal.SIGTERM,stop)
signal.signal(signal.SIGINT,stop)
(root/(name+'.ready')).write_text(json.dumps({'PORT':os.environ['PORT'],'BIST_DATA_DIR':os.environ['BIST_DATA_DIR'],'pid':os.getpid()}))
while True: time.sleep(.05)
'''
                for name in ('web_server.py','ana_motor.py'):(root/name).write_text(child_script)
                environment={**os.environ,'PORT':'19876','BIST_DATA_DIR':str(root/'volume'),'PYTHONDONTWRITEBYTECODE':'1'}
                process=subprocess.Popen([sys.executable,'-u',str(root/'cloud_baslat.py')],env=environment,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                try:
                    deadline=time.monotonic()+8
                    while not all((root/(name+'.ready')).exists() for name in ('web_server','ana_motor')):
                        if time.monotonic()>deadline or process.poll() is not None:self.fail('Fake children did not start')
                        time.sleep(.03)
                    for name in ('web_server','ana_motor'):
                        values=json.loads((root/(name+'.ready')).read_text())
                        self.assertEqual(values['PORT'],'19876')
                        self.assertEqual(values['BIST_DATA_DIR'],str(root/'volume'))
                    process.send_signal(signum)
                    _,logs=process.communicate(timeout=8)
                    self.assertEqual(process.returncode,0)
                    for name in ('web_server','ana_motor'):self.assertTrue((root/(name+'.stopped')).exists())
                    for value in ('[CLOUD] web pid=','[CLOUD] worker pid='):self.assertIn(value,logs)
                finally:
                    if process.poll() is None:process.kill();process.communicate()


if __name__=='__main__':unittest.main()
