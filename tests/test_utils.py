"""
Unit tests for the SSH helpers in skyway.utils.
Nothing here talks to a cloud provider: the SSH command line is swapped for a
local shell, so the tests run anywhere with no credentials and no instances.
"""
import os
import signal
import subprocess
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from skyway import utils


class TestSSHCmdline(unittest.TestCase):
    """The options that keep a remote command from blocking on the terminal."""

    def setUp(self):
        self.cmd = utils.ssh_cmdline('1.2.3.4', 'testuser', '/path/key.pem', 'hostname')

    def test_no_tty_is_allocated(self):
        """A tty puts the local terminal in raw mode, so Ctrl+C goes to the
        remote side instead of interrupting skyway."""
        self.assertNotIn('-t', self.cmd)

    def test_stdin_is_detached(self):
        """-n: a remote command must never sit waiting on the user's terminal."""
        self.assertIn('-n', self.cmd)

    def test_batch_mode_and_connect_timeout(self):
        self.assertIn('BatchMode=yes', self.cmd)
        self.assertIn('ConnectTimeout=10', self.cmd)

    def test_host_and_remote_command_come_last(self):
        self.assertEqual(self.cmd[-2:], ['testuser@1.2.3.4', 'hostname'])


class TestRunSSHTimeout(unittest.TestCase):

    def test_timeout_is_reported_as_a_failed_run_not_an_exception(self):
        """Callers such as ssh_until_success branch on returncode; a hung
        session must come back as a failure they can retry, not a traceback."""
        with patch('skyway.utils.ssh_cmdline', return_value=['sleep', '10']):
            start = time.time()
            r = utils.run_ssh('1.2.3.4', 'testuser', '/path/key.pem', 'hostname',
                              run_timeout=1)
            elapsed = time.time() - start

        self.assertEqual(r.returncode, 124)
        self.assertIn('timed out', r.stderr)
        self.assertLess(elapsed, 15)

    def test_ssh_until_success_retries_after_a_timeout(self):
        calls = {'n': 0}

        def fake_run_ssh(*args, **kwargs):
            calls['n'] += 1
            if calls['n'] == 1:
                return subprocess.CompletedProcess([], 124, stdout='', stderr='timed out')
            return subprocess.CompletedProcess([], 0, stdout='', stderr='')

        with patch('skyway.utils.run_ssh', side_effect=fake_run_ssh), \
             patch('skyway.utils.time.sleep'):
            r = utils.ssh_until_success('1.2.3.4', 'testuser', '/key', 'true')

        self.assertEqual(r.returncode, 0)
        self.assertEqual(calls['n'], 2)


class TestRunPostBootScript(unittest.TestCase):
    """
    The regression these guard: a post boot script that starts a daemon
    (gcsfuse on every group GCP account) leaves that daemon holding the SSH
    session's stdout/stderr. ssh will not close a session while any remote
    process still holds them, so skyway hung at "Preparing the instance..."
    with the script's output captured and thrown away.

    The ssh command line is replaced with `bash -c`, which runs the very same
    remote command string locally and inherits the same descriptors, so the
    behaviour under test is the real one.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='skyway_post_boot_test_')
        self.pidfile = os.path.join(self.tmpdir, 'daemon.pid')
        self.log = os.path.join(self.tmpdir, 'post_boot.log')
        # Stands in for gcsfuse: prints, then leaves a daemon behind that keeps
        # whatever stdout/stderr it inherited open for far longer than the test.
        self.script_cmd = f'echo "mounting bucket"; sleep 20 & echo $! > {self.pidfile}; '

        patcher = patch('skyway.utils.POST_BOOT_LOG', self.log)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        if os.path.isfile(self.pidfile):
            with open(self.pidfile) as f:
                pid = f.read().strip()
            if pid.isdigit():
                try:
                    os.kill(int(pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        for path in (self.pidfile, self.log):
            if os.path.isfile(path):
                os.remove(path)
        os.rmdir(self.tmpdir)

    def _run_locally(self, **kwargs):
        def local_cmdline(host, user, key, remote_cmd, timeout=10):
            return ['bash', '-c', remote_cmd]

        with patch('skyway.utils.ssh_cmdline', side_effect=local_cmdline):
            start = time.time()
            p = utils.run_post_boot_script(
                '1.2.3.4', 'testuser', '/path/key.pem', self.script_cmd, **kwargs)
            return p, time.time() - start

    def test_a_daemon_left_behind_does_not_block_the_session(self):
        p, elapsed = self._run_locally(run_timeout=10)

        self.assertIsNotNone(p, 'the post boot script timed out: the session hung')
        self.assertEqual(p.returncode, 0)
        self.assertLess(elapsed, 5, 'the daemon kept the session open')

    def test_script_output_is_reported_not_swallowed(self):
        with patch('builtins.print') as mock_print:
            p, _ = self._run_locally(run_timeout=10)

        self.assertIn('mounting bucket', p.stdout)
        printed = ' '.join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        self.assertIn('mounting bucket', printed)

    def test_without_the_redirection_the_session_would_hang(self):
        """Characterises the bug itself: with the script's streams left
        attached to the session, the daemon holds them open and the output
        never arrives -- even though the shell it was started from has exited."""
        with subprocess.Popen(['bash', '-c', self.script_cmd],
                              stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              text=True) as p:
            with self.assertRaises(subprocess.TimeoutExpired):
                p.communicate(timeout=3)
            p.kill()

    def test_failing_script_reports_its_status_and_output(self):
        self.script_cmd = 'echo "bucket not found" >&2; exit 7; '

        with patch('builtins.print') as mock_print:
            p, _ = self._run_locally(run_timeout=10)

        self.assertEqual(p.returncode, 7)
        printed = ' '.join(str(c[0][0]) for c in mock_print.call_args_list if c[0])
        self.assertIn('bucket not found', printed)
        self.assertIn('status 7', printed)

    def test_timeout_returns_none_instead_of_raising(self):
        self.script_cmd = 'sleep 5; '

        with patch('builtins.print'):
            p, elapsed = self._run_locally(run_timeout=1)

        self.assertIsNone(p)
        self.assertLess(elapsed, 15)


if __name__ == '__main__':
    unittest.main()
