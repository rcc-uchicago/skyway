"""
Unit tests for the GCP backend.
All cloud API calls are mocked — no credentials or live instances needed.
"""
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import libcloud.common.google
import pandas as pd
from skyway.cloud.gcp import GCP

# A fixed GCP-format timestamp accepted by datetime.strptime(..., '%Y-%m-%dT%H:%M:%S.%f%z')
_TS = '2024-01-01T00:00:00.000000+0000'


def _make_node(node_id='node-id-1', name='test-node', state='running',
               public_ips=None, user='testuser'):
    """Return a minimal mock libcloud node."""
    node = MagicMock()
    node.id = node_id
    node.name = name
    node.state = state
    node.size = 'n1-standard-2'
    node.public_ips = public_ips if public_ips is not None else ['1.2.3.4']
    node.extra = {
        'creationTimestamp': _TS,
        'labels': {'user': user, 'node_name': name},
    }
    return node


class GCPTestCase(unittest.TestCase):
    """Base fixture: GCP instance with mocked driver and minimal account config."""

    def setUp(self):
        with patch.object(GCP, '__init__', return_value=None):
            self.gcp = GCP.__new__(GCP)

        self.gcp.driver = MagicMock()
        self.gcp.account = {
            'service_account': 'ci@project.iam.gserviceaccount.com',
            'location': 'us-central1-b',
            'image_name': 'test-image',
            'key_name': 'test-key',
            'protected_nodes': [],
            'vpc_name': 'vpc1',
        }
        self.gcp.vendor = {
            'node-types': {
                't1': {
                    'name': 'n1-standard-2',
                    'cores': 2,
                    'memgb': 7.5,
                    'price': 0.1,
                    'preemptible': False,
                }
            }
        }
        self.gcp.account_name = 'test-gcp'
        self.gcp.tpu_client = None
        self.gcp.project_id = 'test-project'
        self.gcp.my_ssh_private_key = '~/.my_gcp_ssh_key.pem'
        self.gcp.usage_history = f'/tmp/skyway_ci_{os.getpid()}.pkl'
        self.gcp.post_boot_script = ''
        self.gcp.users = {'testuser': {'budget': 100.0}}

        # An auto-mode VPC: GCE derives the subnet itself, so resolve_subnetwork
        # is allowed to come back empty-handed.
        mock_network = MagicMock()
        mock_network.name = 'vpc1'
        mock_network.mode = 'auto'
        self.gcp.driver.ex_list_networks.return_value = [mock_network]
        self.gcp.driver.ex_list_subnetworks.return_value = []

    def _stub_finances(self):
        self.gcp.get_budget = MagicMock(return_value=100.0)
        self.gcp.get_cost_and_usage_from_db = MagicMock(return_value=(0.0, 100.0))
        self.gcp.get_running_cost = MagicMock(return_value=0.0)
        self.gcp.get_unit_price_instance = MagicMock(return_value=0.1)

    def tearDown(self):
        if os.path.exists(self.gcp.usage_history):
            os.remove(self.gcp.usage_history)


# ---------------------------------------------------------------------------
# get_locations
# ---------------------------------------------------------------------------

class TestGetLocations(GCPTestCase):

    def test_filters_by_us_prefix(self):
        loc_a = MagicMock(); loc_a.name = 'us-central1-b'
        loc_b = MagicMock(); loc_b.name = 'us-east1-a'
        loc_c = MagicMock(); loc_c.name = 'europe-west1-b'
        self.gcp.driver.list_locations.return_value = [loc_a, loc_c, loc_b]

        result = self.gcp.get_locations()

        self.assertEqual(result, ['us-central1-b', 'us-east1-a'])

    def test_returns_sorted(self):
        loc_a = MagicMock(); loc_a.name = 'us-east1-a'
        loc_b = MagicMock(); loc_b.name = 'us-central1-b'
        loc_c = MagicMock(); loc_c.name = 'us-central1-a'
        self.gcp.driver.list_locations.return_value = [loc_a, loc_b, loc_c]

        result = self.gcp.get_locations()

        self.assertEqual(result, ['us-central1-a', 'us-central1-b', 'us-east1-a'])

    def test_custom_prefix(self):
        loc_a = MagicMock(); loc_a.name = 'europe-west1-b'
        loc_b = MagicMock(); loc_b.name = 'us-central1-b'
        self.gcp.driver.list_locations.return_value = [loc_a, loc_b]

        result = self.gcp.get_locations(region_prefix='europe-')

        self.assertEqual(result, ['europe-west1-b'])


# ---------------------------------------------------------------------------
# connect_node
# ---------------------------------------------------------------------------

class TestConnectNode(GCPTestCase):

    def test_unknown_id_prints_not_exists_and_skips_ssh(self):
        self.gcp.driver.list_nodes.return_value = [
            _make_node(node_id='aaa'),
            _make_node(node_id='bbb'),
        ]

        with patch('os.system') as mock_system, \
             patch('builtins.print') as mock_print:
            self.gcp.connect_node('nonexistent-id')

        mock_system.assert_not_called()
        mock_print.assert_called_with('Node nonexistent-id does not exist.')

    def test_last_node_in_list_not_used_as_fallback(self):
        """The old bug: after a failed search, node was the last list item.
        The fix: node stays None when no match is found."""
        node_a = _make_node(node_id='aaa', public_ips=['10.0.0.1'])
        node_b = _make_node(node_id='bbb', public_ips=['10.0.0.2'])
        self.gcp.driver.list_nodes.return_value = [node_a, node_b]

        with patch('os.system') as mock_system, patch('builtins.print'):
            self.gcp.connect_node('zzz-does-not-exist')

        # Neither of the real nodes' IPs should have been SSH'd into
        for call_args in mock_system.call_args_list:
            cmd = call_args[0][0]
            self.assertNotIn('10.0.0.1', cmd)
            self.assertNotIn('10.0.0.2', cmd)


# ---------------------------------------------------------------------------
# create_nodes
# ---------------------------------------------------------------------------

class TestCreateNodes(GCPTestCase):

    def _run_create_nodes(self, ssh_side_effect=None):
        """
        Run create_nodes('t1', ['test-node'], need_confirmation=False, walltime='00:30:00')
        with standard patches applied. Returns the nodes dict.
        ssh_side_effect: if set, raised by ssh_until_success.
        """
        stale_node = _make_node(public_ips=[])
        fresh_node = _make_node(public_ips=['1.2.3.4'])
        self.gcp.driver.create_node.return_value = stale_node
        self.gcp.driver.wait_until_running.return_value = [(fresh_node, ['1.2.3.4'])]
        self._stub_finances()

        ssh_mock = MagicMock(side_effect=ssh_side_effect)

        with patch.dict(os.environ, {'USER': 'testuser', 'SKYWAYROOT': '/tmp'}), \
             patch('subprocess.run',
                   return_value=MagicMock(stdout='ssh-rsa AAAA key', returncode=0)), \
             patch('skyway.cloud.gcp.time.sleep'), \
             patch('skyway.cloud.gcp.utils.ssh_until_success', ssh_mock), \
             patch('skyway.cloud.gcp.pd') as mock_pd:
            mock_pd.DataFrame.return_value = MagicMock()
            mock_pd.concat.return_value = MagicMock()
            nodes = self.gcp.create_nodes(
                't1', ['test-node'],
                need_confirmation=False,
                walltime='00:30:00',
            )

        return nodes, ssh_mock

    def test_uses_refreshed_node_ip_after_wait_until_running(self):
        """wait_until_running return value must be captured; the refreshed node's
        IP is used for ssh_until_success, not the stale empty public_ips."""
        nodes, ssh_mock = self._run_create_nodes()

        ssh_mock.assert_called_once()
        host_arg = ssh_mock.call_args[0][0]
        self.assertEqual(host_arg, '1.2.3.4')
        self.assertIn('test-node', nodes)
        self.assertEqual(nodes['test-node'][2], '1.2.3.4')

    def test_ssh_failure_returns_empty_dict_and_destroys_node(self):
        """When ssh_until_success raises RuntimeError the node must be destroyed
        and removed from the returned dict."""
        nodes, _ = self._run_create_nodes(
            ssh_side_effect=RuntimeError('connection refused')
        )

        self.assertEqual(nodes, {})
        self.gcp.driver.destroy_node.assert_called_once()

    def test_retries_fallback_zone_on_creation_failure(self):
        """On a creation error in the preferred zone, create_nodes fetches
        available US zones and retries in the first fallback."""
        fresh_node = _make_node(public_ips=['5.6.7.8'])

        call_count = {'n': 0}
        def create_side_effect(*args, **kwargs):
            call_count['n'] += 1
            if call_count['n'] == 1:
                raise Exception('zone has no resources')
            return fresh_node

        self.gcp.driver.create_node.side_effect = create_side_effect
        self.gcp.driver.wait_until_running.return_value = [(fresh_node, ['5.6.7.8'])]

        loc1 = MagicMock(); loc1.name = 'us-central1-b'
        loc2 = MagicMock(); loc2.name = 'us-east1-a'
        self.gcp.driver.list_locations.return_value = [loc1, loc2]
        self._stub_finances()

        with patch.dict(os.environ, {'USER': 'testuser', 'SKYWAYROOT': '/tmp'}), \
             patch('subprocess.run',
                   return_value=MagicMock(stdout='ssh-rsa AAAA key', returncode=0)), \
             patch('skyway.cloud.gcp.time.sleep'), \
             patch('skyway.cloud.gcp.utils.ssh_until_success'), \
             patch('skyway.cloud.gcp.pd') as mock_pd:
            mock_pd.DataFrame.return_value = MagicMock()
            mock_pd.concat.return_value = MagicMock()
            nodes = self.gcp.create_nodes(
                't1', ['test-node'],
                need_confirmation=False,
                walltime='00:30:00',
            )

        self.assertIn('test-node', nodes)
        self.assertEqual(self.gcp.driver.create_node.call_count, 2)
        second_call_zone = self.gcp.driver.create_node.call_args_list[1].kwargs['location']
        self.assertEqual(second_call_zone, 'us-east1-a')

    def test_post_boot_script_goes_through_the_detached_helper(self):
        """The post boot script must not be shelled out to with a bare
        `ssh -t ... '<script>'`: a daemon it leaves behind (gcsfuse on every
        group GCP account) holds the session open and hangs create_nodes."""
        script_dir = tempfile.mkdtemp(prefix='skyway_ci_root_')
        os.makedirs(os.path.join(script_dir, 'etc', 'accounts'))
        script_path = os.path.join(script_dir, 'etc', 'accounts', 'post_boot.sh')
        with open(script_path, 'w') as f:
            f.write('mkdir -p /tmp/gcs; gcsfuse testbucket /tmp/gcs > /dev/null\n')
        self.addCleanup(shutil.rmtree, script_dir)

        self.gcp.post_boot_script = 'post_boot.sh'

        fresh_node = _make_node(public_ips=['1.2.3.4'])
        self.gcp.driver.create_node.return_value = _make_node(public_ips=[])
        self.gcp.driver.wait_until_running.return_value = [(fresh_node, ['1.2.3.4'])]
        self._stub_finances()

        post_boot_mock = MagicMock()

        with patch.dict(os.environ, {'USER': 'testuser', 'SKYWAYROOT': script_dir}), \
             patch('subprocess.run',
                   return_value=MagicMock(stdout='ssh-rsa AAAA key', returncode=0)) as mock_run, \
             patch('skyway.cloud.gcp.time.sleep'), \
             patch('skyway.cloud.gcp.utils.ssh_until_success'), \
             patch('skyway.cloud.gcp.utils.run_post_boot_script', post_boot_mock), \
             patch('skyway.cloud.gcp.pd') as mock_pd:
            mock_pd.DataFrame.return_value = MagicMock()
            mock_pd.concat.return_value = MagicMock()
            self.gcp.create_nodes(
                't1', ['test-node'],
                need_confirmation=False,
                walltime='00:30:00',
            )

        post_boot_mock.assert_called_once()
        host_arg = post_boot_mock.call_args[0][0]
        self.assertEqual(host_arg, '1.2.3.4')
        self.assertIn('gcsfuse testbucket', post_boot_mock.call_args[0][3])

        # and nothing else ran the script over a tty-allocating ssh
        for call_args in mock_run.call_args_list:
            cmd = call_args[0][0]
            cmd = cmd if isinstance(cmd, str) else ' '.join(cmd)
            self.assertNotIn('gcsfuse', cmd)

    def test_all_zones_fail_returns_empty_dict(self):
        """If every zone fails, the node should not appear in the returned dict."""
        self.gcp.driver.create_node.side_effect = Exception('no resources anywhere')

        loc1 = MagicMock(); loc1.name = 'us-central1-b'
        loc2 = MagicMock(); loc2.name = 'us-east1-a'
        self.gcp.driver.list_locations.return_value = [loc1, loc2]
        self._stub_finances()

        with patch.dict(os.environ, {'USER': 'testuser', 'SKYWAYROOT': '/tmp'}), \
             patch('subprocess.run',
                   return_value=MagicMock(stdout='ssh-rsa AAAA key', returncode=0)), \
             patch('skyway.cloud.gcp.time.sleep'):
            nodes = self.gcp.create_nodes(
                't1', ['test-node'],
                need_confirmation=False,
                walltime='00:30:00',
            )

        self.assertEqual(nodes, {})
        self.assertFalse(self.gcp.capacity_exhausted)

    def test_stockout_in_every_zone_is_quiet_and_flagged(self):
        """A stockout is summarized once, not printed for each zone, and
        flags the request as retriable for skyway_batch --retry."""
        import libcloud.common.google
        self.gcp.driver.create_node.side_effect = libcloud.common.google.GoogleBaseError(
            "The zone 'projects/p/zones/us-central1-a' does not have enough resources "
            "available to fulfill the request. (state:STOCKOUT, sub-state:STOCKOUT, "
            "resource type:compute).", 200, None)

        loc1 = MagicMock(); loc1.name = 'us-central1-b'
        loc2 = MagicMock(); loc2.name = 'us-east1-a'
        self.gcp.driver.list_locations.return_value = [loc1, loc2]
        self._stub_finances()

        with patch.dict(os.environ, {'USER': 'testuser', 'SKYWAYROOT': '/tmp'}), \
             patch('subprocess.run',
                   return_value=MagicMock(stdout='ssh-rsa AAAA key', returncode=0)), \
             patch('skyway.cloud.gcp.time.sleep'), \
             patch('builtins.print') as mock_print:
            nodes = self.gcp.create_nodes(
                't1', ['test-node'],
                need_confirmation=False,
                walltime='00:30:00',
            )

        self.assertEqual(nodes, {})
        self.assertTrue(self.gcp.capacity_exhausted)
        self.assertEqual(self.gcp.driver.create_node.call_count, 2)   # both zones scanned
        printed = ' '.join(str(c) for c in mock_print.call_args_list)
        self.assertNotIn('STOCKOUT', printed)
        self.assertIn('out of capacity', printed)


class TestCreateNodesInterrupted(GCPTestCase):
    """Ctrl-C before the SSH `shutdown -P` must not leave an instance running
    with no walltime timer."""

    def _now_ts(self, minutes_ago=0):
        t = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
        return t.strftime('%Y-%m-%dT%H:%M:%S.%f%z')

    def _create(self, ssh_side_effect=None):
        self._stub_finances()
        with patch.dict(os.environ, {'USER': 'testuser', 'SKYWAYROOT': '/tmp'}), \
             patch('subprocess.run',
                   return_value=MagicMock(stdout='ssh-rsa AAAA key', returncode=0)), \
             patch('skyway.cloud.gcp.time.sleep'), \
             patch('skyway.cloud.gcp.utils.ssh_until_success',
                   MagicMock(side_effect=ssh_side_effect)):
            return self.gcp.create_nodes('t1', ['test-node'],
                                         need_confirmation=False,
                                         walltime='00:30:00')

    def test_startup_script_arms_the_walltime(self):
        fresh_node = _make_node()
        self.gcp.driver.create_node.return_value = fresh_node
        self.gcp.driver.wait_until_running.return_value = [(fresh_node, ['1.2.3.4'])]
        self._create()

        metadata = self.gcp.driver.create_node.call_args.kwargs['ex_metadata']
        self.assertIn('shutdown -P +30', metadata['startup-script'])
        self.assertIn('ssh-keys', metadata)

    def test_interrupt_inside_create_node_deletes_the_instance_by_name(self):
        """create_node blocks until the insert finishes, so there is no handle
        yet; the instance must be found by name and deleted."""
        self.gcp.driver.create_node.side_effect = KeyboardInterrupt
        orphan = _make_node()
        orphan.extra['creationTimestamp'] = self._now_ts()
        self.gcp.driver.ex_get_node.return_value = orphan

        with self.assertRaises(KeyboardInterrupt):
            self._create()

        self.gcp.driver.ex_get_node.assert_called_with('test-node', 'us-central1-b')
        self.gcp.driver.destroy_node.assert_called_once_with(orphan)

    def test_interrupt_leaves_an_older_instance_with_the_same_name(self):
        self.gcp.driver.create_node.side_effect = KeyboardInterrupt
        existing = _make_node()
        existing.extra['creationTimestamp'] = self._now_ts(minutes_ago=60)
        self.gcp.driver.ex_get_node.return_value = existing

        with self.assertRaises(KeyboardInterrupt):
            self._create()

        self.gcp.driver.destroy_node.assert_not_called()

    def test_interrupt_when_nothing_was_created(self):
        self.gcp.driver.create_node.side_effect = KeyboardInterrupt
        self.gcp.driver.ex_get_node.side_effect = \
            libcloud.common.google.ResourceNotFoundError('not found', 404, 'notFound')

        with self.assertRaises(KeyboardInterrupt):
            self._create()

        self.gcp.driver.destroy_node.assert_not_called()

    def test_interrupt_before_ssh_deletes_node_and_closes_usage_row(self):
        fresh_node = _make_node()
        fresh_node.extra['creationTimestamp'] = self._now_ts(minutes_ago=1)
        self.gcp.driver.create_node.return_value = fresh_node
        self.gcp.driver.wait_until_running.return_value = [(fresh_node, ['1.2.3.4'])]

        with self.assertRaises(KeyboardInterrupt):
            self._create(ssh_side_effect=KeyboardInterrupt)

        self.gcp.driver.destroy_node.assert_called_once_with(fresh_node)
        df = pd.read_pickle(self.gcp.usage_history)
        self.assertEqual(len(df), 1)
        # about one minute at $0.1/hr, not the 30-minute projection ($0.05)
        self.assertLess(df.loc[0, 'Cost'], 0.01)


# ---------------------------------------------------------------------------
# restart_nodes
# ---------------------------------------------------------------------------

class TestRestartNodes(GCPTestCase):

    def test_uses_refreshed_node_ip_after_wait_until_running(self):
        """wait_until_running in restart_nodes must be captured so the refreshed
        node's IP — not the stale stopped-node's empty/old IP — is used for SSH."""
        stale_node = _make_node(state='stopped', public_ips=[])
        fresh_node = _make_node(state='running', public_ips=['9.8.7.6'])

        self.gcp.driver.list_nodes.return_value = [stale_node]
        self.gcp.driver.wait_until_running.return_value = [(fresh_node, ['9.8.7.6'])]
        self.gcp.get_instance_user_name = MagicMock(return_value='testuser')
        self._stub_finances()

        ssh_mock = MagicMock()

        with patch.dict(os.environ, {'USER': 'testuser', 'SKYWAYROOT': '/tmp'}), \
             patch('skyway.cloud.gcp.time.sleep'), \
             patch('skyway.cloud.gcp.utils.ssh_until_success', ssh_mock), \
             patch('skyway.cloud.gcp.pd') as mock_pd:
            mock_pd.DataFrame.return_value = MagicMock()
            mock_pd.concat.return_value = MagicMock()
            self.gcp.restart_nodes(
                node_names=['test-node'],
                need_confirmation=False,
                walltime='00:30:00',
            )

        ssh_mock.assert_called_once()
        host_arg = ssh_mock.call_args[0][0]
        self.assertEqual(host_arg, '9.8.7.6')

    def test_startup_script_is_updated_to_the_restart_walltime(self):
        """GCE reruns the startup-script on every boot; it must carry the new
        walltime, and the update must keep the other metadata (ssh-keys)."""
        stale_node = _make_node(state='stopped', public_ips=[])
        stale_node.extra['metadata'] = {'items': [
            {'key': 'ssh-keys', 'value': 'testuser:ssh-rsa AAAA'},
            {'key': 'startup-script', 'value': '#!/bin/bash\nshutdown -P +5\n'},
        ]}
        fresh_node = _make_node(state='running', public_ips=['9.8.7.6'])
        self.gcp.driver.list_nodes.return_value = [stale_node]
        self.gcp.driver.wait_until_running.return_value = [(fresh_node, ['9.8.7.6'])]
        self.gcp.get_instance_user_name = MagicMock(return_value='testuser')
        self._stub_finances()

        with patch.dict(os.environ, {'USER': 'testuser', 'SKYWAYROOT': '/tmp'}), \
             patch('skyway.cloud.gcp.time.sleep'), \
             patch('skyway.cloud.gcp.utils.ssh_until_success'), \
             patch('skyway.cloud.gcp.pd') as mock_pd:
            mock_pd.DataFrame.return_value = MagicMock()
            mock_pd.concat.return_value = MagicMock()
            self.gcp.restart_nodes(node_names=['test-node'],
                                   need_confirmation=False, walltime='02:00:00')

        node_arg, metadata = self.gcp.driver.ex_set_node_metadata.call_args[0]
        self.assertIs(node_arg, stale_node)
        self.assertIn('shutdown -P +120', metadata['startup-script'])
        self.assertEqual(metadata['ssh-keys'], 'testuser:ssh-rsa AAAA')


# ---------------------------------------------------------------------------
# get_running_cost
# ---------------------------------------------------------------------------

class TestGetRunningCost(GCPTestCase):
    """
    Live cost must be measured from the start of the current session, not from
    creationTimestamp: an instance that was stopped and started again would
    otherwise be billed for every hour it sat stopped in between.
    """

    # created a week before the session the instance is currently in
    _CREATED = '2024-01-01T00:00:00.000000+0000'
    _LAST_START = '2024-01-08T00:00:00.000000+0000'
    _NOW = datetime(2024, 1, 8, 2, 0, 0, tzinfo=timezone.utc)  # 2 h into session

    def _run(self, raw_instance):
        node = _make_node()
        node.extra['creationTimestamp'] = self._CREATED
        node.extra['selfLink'] = (
            'https://www.googleapis.com/compute/v1/projects/test-project'
            '/zones/us-central1-b/instances/test-node'
        )
        self.gcp.driver.list_nodes.return_value = [node]
        self.gcp._raw_instance_cache = {}
        self.gcp.driver.connection.request.return_value = MagicMock(object=raw_instance)
        self.gcp.get_unit_price_instance = MagicMock(return_value=0.1)

        with patch('skyway.cloud.gcp.datetime') as mock_dt:
            mock_dt.now.return_value = self._NOW
            mock_dt.strptime = datetime.strptime
            return self.gcp.get_running_cost(verbose=False, user_name='testuser')

    def test_bills_from_last_start_not_creation(self):
        cost = self._run({'lastStartTimestamp': self._LAST_START})
        # 2 h x $0.1, not the 170 h since creation
        self.assertAlmostEqual(cost, 0.2, places=6)

    def test_falls_back_to_creation_when_never_restarted(self):
        cost = self._run({})
        # no lastStartTimestamp: the session began at creation, 170 h ago
        self.assertAlmostEqual(cost, 17.0, places=6)

    def test_skips_node_with_no_usable_timestamp(self):
        node = _make_node()
        node.extra['creationTimestamp'] = None
        node.extra['selfLink'] = None
        self.gcp.driver.list_nodes.return_value = [node]
        self.gcp._raw_instance_cache = {}
        self.gcp.get_unit_price_instance = MagicMock(return_value=0.1)

        cost = self.gcp.get_running_cost(verbose=False, user_name='testuser')
        self.assertEqual(cost, 0.0)


if __name__ == '__main__':
    unittest.main()
