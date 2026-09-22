"""
Unit tests for skyway_batch, in particular for releasing the instance as soon
as the job script finishes instead of letting it run to the end of the
walltime.  All cloud API calls are mocked — no credentials or live instances
needed.
"""
import importlib.machinery
import importlib.util
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

# skyway_batch imports every backend; the SDKs that are not installed here are
# stubbed out, as none of them is exercised by these tests
for _name in ['boto3', 'botocore', 'botocore.exceptions', 'oci',
              'azure', 'azure.identity', 'azure.mgmt', 'azure.mgmt.compute',
              'azure.mgmt.compute.models', 'azure.mgmt.network',
              'azure.mgmt.network.models', 'azure.mgmt.resource']:
    try:
        importlib.import_module(_name)
    except ImportError:
        sys.modules[_name] = MagicMock()

_BATCH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'skyway_batch')
_loader = importlib.machinery.SourceFileLoader('skyway_batch', _BATCH)
_spec = importlib.util.spec_from_loader('skyway_batch', _loader)
skyway_batch = importlib.util.module_from_spec(_spec)
_loader.exec_module(skyway_batch)

from skyway.cloud.core import Cloud
from skyway.cloud.slurm import SLURMCluster


def _make_descriptor(vendor_name='aws', script_status=0):
    """An InstanceDescriptor whose account is a mock cloud backend."""
    descriptor = skyway_batch.InstanceDescriptor.__new__(
        skyway_batch.InstanceDescriptor)
    descriptor.jobname = 'my-run'
    descriptor.account_name = f'rcc-{vendor_name}'
    descriptor.node_type = 't1'
    descriptor.walltime = '06:00:00'
    descriptor.vendor_name = vendor_name
    descriptor.user = 'testuser'

    account = MagicMock()
    account.create_nodes.return_value = {'my-run': ['t1', 'now', '1.2.3.4']}
    account.get_instance_ID.return_value = 'i-0123456789'
    account.get_host_ip.return_value = 'midway3-0001'
    account.execute_script.return_value = script_status
    descriptor.account = account
    return descriptor


class TestSubmitJob(unittest.TestCase):

    def test_releases_the_instance_after_the_script_finishes(self):
        descriptor = _make_descriptor()

        descriptor.submitJob(script_name='job_script.sh')

        descriptor.account.execute_script.assert_called_once_with(
            'i-0123456789', 'job_script.sh')
        descriptor.account.release_node.assert_called_once_with('my-run')

    def test_releases_only_after_the_script_has_run(self):
        """A release before the script finishes would kill the job."""
        descriptor = _make_descriptor()
        descriptor.account.execute_script.side_effect = \
            lambda *a, **kw: descriptor.account.release_node.assert_not_called()

        descriptor.submitJob(script_name='job_script.sh')

        descriptor.account.release_node.assert_called_once_with('my-run')

    def test_no_auto_stop_leaves_the_instance_running(self):
        descriptor = _make_descriptor()

        descriptor.submitJob(script_name='job_script.sh', auto_stop=False)

        descriptor.account.execute_script.assert_called_once()
        descriptor.account.release_node.assert_not_called()

    def test_releases_the_instance_when_the_script_fails(self):
        descriptor = _make_descriptor(script_status=17)

        descriptor.submitJob(script_name='job_script.sh')

        descriptor.account.release_node.assert_called_once_with('my-run')

    def test_releases_the_instance_when_the_submission_is_interrupted(self):
        """Ctrl-C at the terminal must not leave the instance billing."""
        descriptor = _make_descriptor()
        descriptor.account.execute_script.side_effect = KeyboardInterrupt

        with self.assertRaises(KeyboardInterrupt):
            descriptor.submitJob(script_name='job_script.sh')

        descriptor.account.release_node.assert_called_once_with('my-run')

    def test_nothing_is_run_or_released_when_no_instance_was_allocated(self):
        """create_nodes returns None when the budget check fails."""
        descriptor = _make_descriptor()
        descriptor.account.create_nodes.return_value = None

        nodes = descriptor.submitJob(script_name='job_script.sh')

        self.assertIsNone(nodes)
        descriptor.account.execute_script.assert_not_called()
        descriptor.account.release_node.assert_not_called()

    def test_instance_is_released_even_if_it_cannot_be_found(self):
        """The node is up (create_nodes succeeded) but its ID does not resolve."""
        descriptor = _make_descriptor()
        descriptor.account.get_instance_ID.return_value = ''

        descriptor.submitJob(script_name='job_script.sh')

        descriptor.account.execute_script.assert_not_called()
        descriptor.account.release_node.assert_called_once_with('my-run')

    def test_pre_execute_commands_run_before_the_script(self):
        descriptor = _make_descriptor()

        with patch.object(skyway_batch.os, 'system') as mock_system:
            descriptor.submitJob(script_name='job_script.sh',
                                 pre_execute=['skyway_transfer training.py'])

        mock_system.assert_called_once_with(
            'skyway_transfer training.py --account=rcc-aws -Jmy-run')
        descriptor.account.release_node.assert_called_once_with('my-run')

    def test_on_premises_job_is_addressed_by_host_name(self):
        descriptor = _make_descriptor(vendor_name='rcc-midway3')

        descriptor.submitJob(script_name='job_script.sh')

        descriptor.account.get_instance_ID.assert_not_called()
        descriptor.account.execute_script.assert_called_once_with(
            'midway3-0001', 'job_script.sh')
        descriptor.account.release_node.assert_called_once_with('my-run')

    def test_backend_without_an_exit_status_is_reported_as_success(self):
        descriptor = _make_descriptor(script_status=None)

        with patch('builtins.print') as mock_print:
            descriptor.submitJob(script_name='job_script.sh')

        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn('completed', printed)


class TestShutdownFallback(unittest.TestCase):
    """
    When the instance cannot be stopped through the cloud API, skyway_batch
    powers it off from inside the guest rather than leaving it running to the
    end of its walltime.
    """

    def setUp(self):
        self.descriptor = _make_descriptor()
        self.descriptor.account.release_node.side_effect = RuntimeError('API down')
        self.descriptor.account.get_node_connection_info.return_value = {
            'private_key': '/home/testuser/.my_aws_ssh_key.pem',
            'login': 'ubuntu@1.2.3.4',
        }

    def test_ssh_shutdown_is_armed_when_the_api_stop_fails(self):
        with patch.object(skyway_batch.utils, 'run_ssh',
                          return_value=MagicMock(returncode=0, stderr='')) as mock_ssh:
            self.descriptor.submitJob(script_name='job_script.sh')

        mock_ssh.assert_called_once_with(
            '1.2.3.4', 'ubuntu', '/home/testuser/.my_aws_ssh_key.pem',
            skyway_batch.InstanceDescriptor.SHUTDOWN_FALLBACK_CMD)

    def test_the_pending_walltime_shutdown_is_cancelled_first(self):
        """A shutdown already scheduled could otherwise win over the new one."""
        cmd = skyway_batch.InstanceDescriptor.SHUTDOWN_FALLBACK_CMD
        self.assertEqual(cmd, 'sudo shutdown -c; sudo shutdown -P +1')

    def test_no_ssh_when_the_api_stop_succeeds(self):
        self.descriptor.account.release_node.side_effect = None

        with patch.object(skyway_batch.utils, 'run_ssh') as mock_ssh:
            self.descriptor.submitJob(script_name='job_script.sh')

        mock_ssh.assert_not_called()

    def test_no_ssh_when_the_instance_is_already_gone(self):
        self.descriptor.account.get_instance_ID.return_value = ''

        with patch.object(skyway_batch.utils, 'run_ssh') as mock_ssh:
            self.descriptor.submitJob(script_name='job_script.sh')

        mock_ssh.assert_not_called()

    def test_a_failed_ssh_warns_instead_of_raising(self):
        """releaseJob runs in a finally block: it must not mask the job's own error."""
        with patch.object(skyway_batch.utils, 'run_ssh',
                          return_value=MagicMock(returncode=255, stderr='no route to host')), \
             patch('builtins.print') as mock_print:
            self.descriptor.submitJob(script_name='job_script.sh')

        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn('skyway_stop', printed)

    def test_unreachable_connection_info_warns_instead_of_raising(self):
        self.descriptor.account.get_node_connection_info.side_effect = \
            RuntimeError('no such instance')

        with patch('builtins.print') as mock_print:
            self.descriptor.submitJob(script_name='job_script.sh')

        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn('skyway_stop', printed)

    def test_on_premises_job_is_not_powered_off(self):
        """A shared Slurm node must never be shut down: cancel the job instead."""
        descriptor = _make_descriptor(vendor_name='rcc-midway3')
        descriptor.account.release_node.side_effect = RuntimeError('scancel failed')

        with patch.object(skyway_batch.utils, 'run_ssh') as mock_ssh, \
             patch('builtins.print') as mock_print:
            descriptor.submitJob(script_name='job_script.sh')

        mock_ssh.assert_not_called()
        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertIn('skyway_cancel', printed)


class TestReleaseNode(unittest.TestCase):
    """release_node() must map onto whatever ends a session on each backend."""

    def test_cloud_backends_stop_the_instance(self):
        cloud = Cloud.__new__(Cloud)
        cloud.stop_nodes = MagicMock()

        cloud.release_node('my-run')

        cloud.stop_nodes.assert_called_once_with(node_names=['my-run'],
                                                 need_confirmation=False)

    def test_slurm_cancels_the_allocation(self):
        """Slurm has no stopped state, so the job is cancelled instead."""
        cluster = SLURMCluster.__new__(SLURMCluster)
        cluster.get_instance_ID = MagicMock(return_value='4210983')
        cluster.destroy_nodes = MagicMock()

        cluster.release_node('my-run')

        cluster.destroy_nodes.assert_called_once_with(IDs=['4210983'],
                                                      need_confirmation=False)

    def test_slurm_release_of_an_unknown_job_is_a_no_op(self):
        cluster = SLURMCluster.__new__(SLURMCluster)
        cluster.get_instance_ID = MagicMock(return_value=None)
        cluster.destroy_nodes = MagicMock()

        cluster.release_node('my-run')

        cluster.destroy_nodes.assert_not_called()


if __name__ == '__main__':
    unittest.main()
