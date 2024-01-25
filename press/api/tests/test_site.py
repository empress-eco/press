# -*- coding: utf-8 -*-
# Copyright (c) 2019, Frappe and Contributors
# See license.txt

import datetime
from unittest.mock import MagicMock, Mock, patch

import frappe
import responses
from frappe.tests.utils import FrappeTestCase

from press.api.site import all
from press.press.doctype.agent_job.agent_job import AgentJob, poll_pending_jobs
from press.press.doctype.agent_job.test_agent_job import fake_agent_job
from press.press.doctype.app.test_app import create_test_app
from press.press.doctype.app_release.test_app_release import create_test_app_release
from press.press.doctype.bench.test_bench import create_test_bench
from press.press.doctype.cluster.test_cluster import create_test_cluster
from press.press.doctype.deploy.deploy import create_deploy_candidate_differences
from press.press.doctype.plan.test_plan import create_test_plan
from press.press.doctype.release_group.test_release_group import (
	create_test_release_group,
)
from press.press.doctype.remote_file.remote_file import RemoteFile
from press.press.doctype.remote_file.test_remote_file import create_test_remote_file
from press.press.doctype.server.test_server import create_test_server
from press.press.doctype.site.test_site import create_test_site
from press.press.doctype.team.test_team import create_test_press_admin_team


class TestAPISite(FrappeTestCase):
	def setUp(self):
		self.team = create_test_press_admin_team()
		self.team.allocate_credit_amount(1000, source="Prepaid Credits", remark="Test")

	def tearDown(self):
		frappe.db.rollback()
		frappe.set_user("Administrator")

	@patch.object(AgentJob, "enqueue_http_request", new=Mock())
	def test_options_contains_only_public_groups_when_private_group_is_not_given(
		self,
	):
		from press.api.site import get_new_site_options

		app = create_test_app()

		group12 = create_test_release_group([app], public=True, frappe_version="Version 12")
		group13 = create_test_release_group([app], public=True, frappe_version="Version 13")
		group14 = create_test_release_group([app], public=True, frappe_version="Version 14")

		server = create_test_server()
		create_test_bench(group=group12, server=server.name)
		create_test_bench(group=group13, server=server.name)
		create_test_bench(group=group14, server=server.name)
		frappe.set_user(self.team.user)
		private_group = create_test_release_group(
			[app], public=False, frappe_version="Version 14"
		)
		create_test_bench(group=private_group, server=server.name)

		options = get_new_site_options()

		for version in options["versions"]:
			if version["name"] == "Version 14":
				self.assertEqual(version["group"]["name"], group14.name)

	@patch.object(AgentJob, "enqueue_http_request", new=Mock())
	def test_new_fn_creates_site_and_subscription(self):
		from press.api.site import new

		app = create_test_app()
		group = create_test_release_group([app])
		bench = create_test_bench(group=group)
		plan = create_test_plan("Site")

		frappe.set_user(self.team.user)
		new_site = new(
			{
				"name": "testsite",
				"group": group.name,
				"plan": plan.name,
				"apps": [app.name],
				"cluster": bench.cluster,
			}
		)

		created_site = frappe.get_last_doc("Site")
		subscription = frappe.get_last_doc("Subscription")
		self.assertEqual(new_site["site"], created_site.name)
		self.assertEqual(subscription.document_name, created_site.name)
		self.assertEqual(subscription.plan, plan.name)
		self.assertTrue(subscription.enabled)
		self.assertEqual(created_site.team, self.team.name)
		self.assertEqual(created_site.bench, bench.name)
		self.assertEqual(created_site.status, "Pending")

	@patch.object(AgentJob, "enqueue_http_request", new=Mock())
	def test_get_fn_returns_site_details(self):
		from press.api.site import get

		bench = create_test_bench()
		group = frappe.get_last_doc("Release Group", {"name": bench.group})
		frappe.set_user(self.team.user)
		site = create_test_site(bench=bench.name)
		site.reload()
		site_details = get(site.name)
		self.assertEqual(site_details["name"], site.name)
		self.assertDictEqual(
			{
				"name": site.name,
				"host_name": site.host_name,
				"status": site.status,
				"archive_failed": bool(site.archive_failed),
				"trial_end_date": site.trial_end_date,
				"setup_wizard_complete": site.setup_wizard_complete,
				"group": None,  # because group is public
				"team": site.team,
				"frappe_version": group.version,
				"latest_frappe_version": frappe.db.get_value(
					"Frappe Version", {"status": "Stable"}, order_by="name desc"
				),
				"is_public": group.public,
				"server": site.server,
				"server_region_info": frappe.db.get_value(
					"Cluster", site.cluster, ["title", "image"], as_dict=True
				),
				"can_change_plan": True,
				"hide_config": site.hide_config,
				"notify_email": site.notify_email,
				"info": {
					"auto_updates_enabled": True,
					"created_on": site.creation,
					"last_deployed": None,
					"owner": {
						"first_name": "Frappe",
						"last_name": None,
						"user_image": None,
					},
				},
				"ip": frappe.get_last_doc("Proxy Server").ip,
				"site_tags": [{"name": x.tag, "tag": x.tag_name} for x in site.tags],
				"tags": frappe.get_all(
					"Press Tag",
					{"team": self.team.name, "doctype_name": "Site"},
					["name", "tag"],
				),
				"pending_for_long": False,
				"site_migration": None,
				"version_upgrade": None,
			},
			site_details,
		)

	@patch(
		"press.press.doctype.app_release_difference.app_release_difference.Github",
		new=MagicMock(),
	)
	@patch.object(AgentJob, "enqueue_http_request", new=Mock())
	def _setup_site_update(self):
		version = "Version 13"
		app = create_test_app()
		group = create_test_release_group([app], frappe_version=version)
		self.bench1 = create_test_bench(group=group)

		create_test_app_release(
			app_source=frappe.get_doc("App Source", group.apps[0].source),
		)  # creates pull type release diff only but args are same

		self.bench2 = create_test_bench(group=group, server=self.bench1.server)

		self.assertNotEqual(self.bench1, self.bench2)
		# No need to create app release differences as it'll get autofilled by geo.json
		create_deploy_candidate_differences(self.bench2)  # for site update to be available

	@patch.object(AgentJob, "enqueue_http_request", new=Mock())
	def test_check_for_updates_shows_update_available_when_site_update_available(self):
		from press.api.site import check_for_updates

		self._setup_site_update()
		frappe.set_user(self.team.user)
		site = create_test_site(bench=self.bench1.name)
		out = check_for_updates(site.name)
		self.assertEqual(out["update_available"], True)

	@patch.object(AgentJob, "enqueue_http_request", new=Mock())
	def test_check_for_updates_shows_update_unavailable_when_no_new_bench(self):
		from press.api.site import check_for_updates

		bench = create_test_bench()

		frappe.set_user(self.team.user)
		site = create_test_site(bench=bench.name)
		out = check_for_updates(site.name)
		self.assertEqual(out["update_available"], False)

	@patch.object(AgentJob, "enqueue_http_request", new=Mock())
	def test_installed_apps_returns_installed_apps_of_site(self):
		from press.api.site import installed_apps

		app1 = create_test_app()
		app2 = create_test_app("erpnext", "ERPNext")
		group = create_test_release_group([app1, app2])
		bench = create_test_bench(group=group)

		frappe.set_user(self.team.user)
		site = create_test_site(bench=bench.name)
		out = installed_apps(site.name)
		self.assertEqual(len(out), 2)
		self.assertEqual(out[0]["name"], group.apps[0].source)
		self.assertEqual(out[1]["name"], group.apps[1].source)
		self.assertEqual(out[0]["app"], group.apps[0].app)
		self.assertEqual(out[1]["app"], group.apps[1].app)

	@patch.object(AgentJob, "enqueue_http_request", new=Mock())
	def test_available_apps_shows_apps_installed_in_bench_but_not_in_site(self):
		from press.api.site import available_apps

		app1 = create_test_app()
		app2 = create_test_app("erpnext", "ERPNext")
		app3 = create_test_app("insights", "Insights")
		group = create_test_release_group([app1, app2])
		bench = create_test_bench(group=group)

		group2 = create_test_release_group([app1, app3])
		create_test_bench(
			group=group2, server=bench.server
		)  # app3 shouldn't show in available_apps

		frappe.set_user(self.team.user)
		site = create_test_site(bench=bench.name, apps=[app1.name])
		out = available_apps(site.name)
		self.assertEqual(len(out), 1)
		self.assertEqual(out[0]["name"], group.apps[1].source)
		self.assertEqual(out[0]["app"], group.apps[1].app)

	def test_check_dns_(self):
		pass

	def test_install_app_adds_to_app_list_only_on_successful_job(self):
		from press.api.site import install_app

		app = create_test_app()
		app2 = create_test_app("erpnext", "ERPNext")
		group = create_test_release_group([app, app2])
		bench = create_test_bench(group=group)

		frappe.set_user(self.team.user)
		site = create_test_site(bench=bench.name, apps=[app.name])
		with fake_agent_job("Install App on Site", "Success"):
			install_app(site.name, app2.name)
			poll_pending_jobs()
		site.reload()
		self.assertEqual(len(site.apps), 2)
		self.assertEqual(site.status, "Active")

		site = create_test_site(bench=bench.name, apps=[app.name])
		with fake_agent_job("Install App on Site", "Failure"):
			install_app(site.name, app2.name)
			poll_pending_jobs()
		site.reload()
		self.assertEqual(len(site.apps), 1)
		self.assertEqual(site.status, "Active")

	def test_uninstall_app_removes_from_list_only_on_success(self):
		from press.api.site import uninstall_app

		app = create_test_app()
		app2 = create_test_app("erpnext", "ERPNext")
		group = create_test_release_group([app, app2])
		bench = create_test_bench(group=group)

		frappe.set_user(self.team.user)
		site = create_test_site(bench=bench.name, apps=[app.name, app2.name])
		with fake_agent_job("Uninstall App from Site", "Success"):
			uninstall_app(site.name, app2.name)
			poll_pending_jobs()
		site.reload()
		self.assertEqual(len(site.apps), 1)
		self.assertEqual(site.status, "Active")

		site = create_test_site(bench=bench.name, apps=[app.name, app2.name])
		with fake_agent_job("Uninstall App from Site", "Failure"):
			uninstall_app(site.name, app2.name)
			poll_pending_jobs()
		site.reload()
		self.assertEqual(len(site.apps), 2)
		self.assertEqual(site.status, "Active")

	@patch.object(RemoteFile, "exists", new=Mock(return_value=True))
	@patch.object(RemoteFile, "download_link", new="http://test.com")
	def test_restore_job_updates_apps_table_with_output_from_job(self):
		from press.api.site import restore

		app = create_test_app()
		app2 = create_test_app("erpnext", "ERPNext")
		app3 = create_test_app("insights", "Insights")
		group = create_test_release_group([app, app2, app3])
		bench = create_test_bench(group=group)

		frappe.set_user(self.team.user)
		site = create_test_site(bench=bench.name, apps=[app.name, app2.name])
		database = create_test_remote_file(site.name).name
		public = create_test_remote_file(site.name).name
		private = create_test_remote_file(site.name).name

		self.assertEqual(len(site.apps), 2)
		self.assertEqual(site.apps[0].app, "frappe")
		self.assertEqual(site.apps[1].app, "erpnext")
		self.assertEqual(site.status, "Active")

		with fake_agent_job(
			"Restore Site",
			"Success",
			data=frappe._dict(
				output="""frappe	15.0.0-dev HEAD
insights 0.8.3	    HEAD
"""
			),
		):
			restore(
				site.name,
				{
					"database": database,
					"public": public,
					"private": private,
				},
			)
			poll_pending_jobs()

		site.reload()
		self.assertEqual(len(site.apps), 2)
		self.assertEqual(site.apps[0].app, "frappe")
		self.assertEqual(site.apps[1].app, "insights")
		self.assertEqual(site.status, "Active")

	@patch.object(RemoteFile, "exists", new=Mock(return_value=True))
	@patch.object(RemoteFile, "download_link", new="http://test.com")
	def test_restore_job_updates_apps_table_when_only_frappe_is_installed(self):
		from press.api.site import restore

		app = create_test_app()
		app2 = create_test_app("erpnext", "ERPNext")
		group = create_test_release_group([app, app2])
		bench = create_test_bench(group=group)

		frappe.set_user(self.team.user)
		site = create_test_site(bench=bench.name, apps=[app.name, app2.name])
		database = create_test_remote_file(site.name).name
		public = create_test_remote_file(site.name).name
		private = create_test_remote_file(site.name).name

		self.assertEqual(len(site.apps), 2)
		self.assertEqual(site.apps[0].app, "frappe")
		self.assertEqual(site.apps[1].app, "erpnext")
		self.assertEqual(site.status, "Active")

		with fake_agent_job(
			"Restore Site", "Success", data=frappe._dict(output="""frappe 15.0.0-dev HEAD""")
		):
			restore(
				site.name,
				{
					"database": database,
					"public": public,
					"private": private,
				},
			)
			poll_pending_jobs()

		site.reload()
		self.assertEqual(len(site.apps), 1)
		self.assertEqual(site.apps[0].app, "frappe")
		self.assertEqual(site.status, "Active")

	@patch.object(RemoteFile, "exists", new=Mock(return_value=True))
	@patch.object(RemoteFile, "download_link", new="http://test.com")
	def test_new_site_from_backup_job_updates_apps_table_with_output_from_job(self):
		from press.api.site import new

		app = create_test_app()
		app2 = create_test_app("erpnext", "ERPNext")
		group = create_test_release_group([app, app2])
		plan = create_test_plan("Site")
		create_test_bench(group=group)

		# frappe.set_user(self.team.user) # can't this due to weird perm error with ignore_perimssions in new site
		database = create_test_remote_file().name
		public = create_test_remote_file().name
		private = create_test_remote_file().name
		with fake_agent_job(
			"New Site from Backup",
			"Success",
			data=frappe._dict(
				output="""frappe	15.0.0-dev HEAD
erpnext 0.8.3	    HEAD
"""
			),
		):
			new(
				{
					"name": "testsite",
					"group": group.name,
					"plan": plan.name,
					"apps": [app.name],
					"files": {
						"database": database,
						"public": public,
						"private": private,
					},
					"cluster": "Default",
				}
			)
			poll_pending_jobs()

		site = frappe.get_last_doc("Site")
		self.assertEqual(len(site.apps), 2)
		self.assertEqual(site.apps[0].app, "frappe")
		self.assertEqual(site.apps[1].app, "erpnext")
		self.assertEqual(site.status, "Active")

	def test_site_change_group(self):
		from press.api.site import change_group, change_group_options
		from press.press.doctype.site_update.site_update import process_update_site_job_update

		app = create_test_app()
		server = create_test_server()
		group1 = create_test_release_group([app])
		group2 = create_test_release_group([app])
		bench1 = create_test_bench(group=group1, server=server)
		bench2 = create_test_bench(group=group2, server=server)
		site = create_test_site(bench=bench1.name)

		self.assertEqual(
			change_group_options(site.name), [{"name": group2.name, "title": group2.title}]
		)

		with fake_agent_job(
			"Update Site Migrate",
			"Success",
			steps=[{"name": "Move Site", "status": "Success"}],
		):
			change_group(site.name, group2.name)

			responses.get(
				f"https://{site.host_name}/",
				status=200,
			)
			poll_pending_jobs()

			site_update = frappe.get_last_doc("Site Update")
			job = frappe.get_doc("Agent Job", site_update.update_job)

			process_update_site_job_update(job)

		site.reload()

		self.assertEqual(site.group, group2.name)
		self.assertEqual(site.bench, bench2.name)

	@patch(
		"press.press.doctype.agent_job.agent_job.process_site_migration_job_update",
		new=Mock(),
	)
	@patch("press.press.doctype.site.site.create_dns_record", new=Mock())
	def test_site_change_region(self):
		from press.api.site import change_region, change_region_options

		app = create_test_app()
		tokyo_cluster = create_test_cluster("Tokyo", public=True)
		seoul_cluster = create_test_cluster("Seoul", public=True)
		tokyo_server = create_test_server(cluster=tokyo_cluster.name)
		seoul_server = create_test_server(cluster=seoul_cluster.name)
		group = create_test_release_group([app])
		group.append(
			"servers",
			{
				"server": tokyo_server.name,
			},
		)
		group.save()
		bench = create_test_bench(group=group, server=tokyo_server.name)

		group.append(
			"servers",
			{
				"server": seoul_server.name,
			},
		)
		group.save()

		create_test_bench(group=group, server=seoul_server.name)
		site = create_test_site(bench=bench.name)

		options = change_region_options(site.name)

		self.assertEqual(
			options["regions"],
			[
				frappe.get_value(
					"Cluster", seoul_server.cluster, ["name", "title", "image"], as_dict=True
				)
			],
		)
		self.assertEqual(options["current_region"], tokyo_server.cluster)

		with fake_agent_job("Update Site Migrate"):
			responses.post(
				f"https://{site.server}:443/agent/benches/{site.bench}/sites/{site.host_name}/config",
				json={"jobs": []},
				status=200,
			)
			change_region(site.name, seoul_server.cluster)
			site_migration = frappe.get_last_doc("Site Migration")
			site_migration.update_site_record_fields()

		site.reload()
		self.assertEqual(site.cluster, seoul_server.cluster)

	def test_site_version_upgrade(self):
		from press.api.site import version_upgrade, get_private_groups_for_upgrade
		from press.press.doctype.site_update.site_update import process_update_site_job_update

		app = create_test_app()
		server = create_test_server()

		v14_group = create_test_release_group([app], frappe_version="Version 14")
		v14_group.append(
			"servers",
			{
				"server": server,
			},
		)
		v14_group.save()

		v15_group = create_test_release_group([app], frappe_version="Version 15")
		v15_group.append(
			"servers",
			{
				"server": server,
			},
		)
		v15_group.save()

		v14_bench = create_test_bench(group=v14_group, server=server)
		create_test_bench(group=v15_group, server=server)
		site = create_test_site(bench=v14_bench.name)

		self.assertEqual(
			get_private_groups_for_upgrade(site.name, v14_group.version),
			[
				{"name": v15_group.name, "title": v15_group.title},
			],
		)

		with fake_agent_job(
			"Update Site Migrate",
			"Success",
			steps=[{"name": "Move Site", "status": "Success"}],
		):
			version_upgrade(site.name, v15_group.name)

			responses.get(
				f"https://{site.host_name}/",
				status=200,
			)
			poll_pending_jobs()

			site_update = frappe.get_last_doc("Site Update")
			job = frappe.get_doc("Agent Job", site_update.update_job)

			process_update_site_job_update(job)

		site.reload()
		site_version = frappe.db.get_value("Release Group", site.group, "version")
		self.assertEqual(site_version, v15_group.version)

	@patch(
		"press.press.doctype.agent_job.agent_job.process_site_migration_job_update",
		new=Mock(),
	)
	def test_site_change_server(self):
		from press.api.site import (
			change_server,
			change_server_options,
			is_server_added_in_group,
		)
		from press.utils import get_current_team

		app = create_test_app()
		team = get_current_team()
		server = create_test_server(team=team)

		group = create_test_release_group([app])
		group.append(
			"servers",
			{
				"server": server,
			},
		)
		group.save()

		bench = create_test_bench(group=group, server=server.name)
		other_server = create_test_server(team=team)
		create_test_bench(group=group, server=other_server.name)

		group.append(
			"servers",
			{
				"server": other_server,
			},
		)
		group.save()

		site = create_test_site(bench=bench.name)

		self.assertEqual(
			change_server_options(site.name),
			[{"name": other_server.name, "title": None}],
		)

		self.assertEqual(
			is_server_added_in_group(site.name, other_server.name),
			True,
		)

		with fake_agent_job("Update Site Migrate"):
			responses.post(
				f"https://{site.server}:443/agent/benches/{site.bench}/sites/{site.host_name}/config",
				json={"jobs": []},
				status=200,
			)

			change_server(site.name, other_server.name)
			site_migration = frappe.get_last_doc("Site Migration")
			site_migration.update_site_record_fields()

		site.reload()
		self.assertEqual(site.server, other_server.name)

	def test_update_config(self):
		pass

	def test_get_upload_link(self):
		pass


class TestAPISiteList(FrappeTestCase):
	def setUp(self):
		from press.press.doctype.press_tag.test_press_tag import create_and_add_test_tag
		from press.press.doctype.site.test_site import create_test_site

		app = create_test_app()
		group = create_test_release_group([app])
		bench = create_test_bench(group=group)

		broken_site = create_test_site(bench=bench.name)
		broken_site.status = "Broken"
		broken_site.save()
		self.broken_site_dict = {
			"name": broken_site.name,
			"cluster": broken_site.cluster,
			"group": broken_site.group,
			"plan": None,
			"public": 0,
			"server_region_info": {"image": None, "title": None},
			"tags": [],
			"host_name": broken_site.host_name,
			"status": broken_site.status,
			"creation": broken_site.creation,
			"bench": broken_site.bench,
			"current_cpu_usage": broken_site.current_cpu_usage,
			"current_database_usage": broken_site.current_database_usage,
			"current_disk_usage": broken_site.current_disk_usage,
			"trial_end_date": broken_site.trial_end_date,
			"team": broken_site.team,
			"title": group.title,
			"version": group.version,
		}

		trial_site = create_test_site(bench=bench.name)
		trial_site.trial_end_date = datetime.datetime.now()
		trial_site.save()

		self.trial_site_dict = {
			"name": trial_site.name,
			"cluster": trial_site.cluster,
			"group": trial_site.group,
			"plan": None,
			"public": 0,
			"server_region_info": {"image": None, "title": None},
			"tags": [],
			"host_name": trial_site.host_name,
			"status": trial_site.status,
			"creation": trial_site.creation,
			"bench": trial_site.bench,
			"current_cpu_usage": trial_site.current_cpu_usage,
			"current_database_usage": trial_site.current_database_usage,
			"current_disk_usage": trial_site.current_disk_usage,
			"trial_end_date": trial_site.trial_end_date.date(),
			"team": trial_site.team,
			"title": group.title,
			"version": group.version,
		}

		tagged_site = create_test_site(bench=bench.name)
		create_and_add_test_tag(tagged_site.name, "Site")

		self.tagged_site_dict = {
			"name": tagged_site.name,
			"cluster": tagged_site.cluster,
			"group": tagged_site.group,
			"plan": None,
			"public": 0,
			"server_region_info": {"image": None, "title": None},
			"tags": ["test_tag"],
			"host_name": tagged_site.host_name,
			"status": tagged_site.status,
			"creation": tagged_site.creation,
			"bench": tagged_site.bench,
			"current_cpu_usage": tagged_site.current_cpu_usage,
			"current_database_usage": tagged_site.current_database_usage,
			"current_disk_usage": tagged_site.current_disk_usage,
			"trial_end_date": tagged_site.trial_end_date,
			"team": tagged_site.team,
			"title": group.title,
			"version": group.version,
		}

	def tearDown(self):
		frappe.db.rollback()

	def test_list_all_sites(self):
		self.assertCountEqual(
			all(), [self.broken_site_dict, self.trial_site_dict, self.tagged_site_dict]
		)

	def test_list_broken_sites(self):
		self.assertEqual(
			all(site_filter={"status": "Broken", "tag": ""}), [self.broken_site_dict]
		)

	def test_list_trial_sites(self):
		self.assertEqual(
			all(site_filter={"status": "Trial", "tag": ""}), [self.trial_site_dict]
		)

	def test_list_tagged_sites(self):
		self.assertEqual(
			all(site_filter={"status": "", "tag": "test_tag"}), [self.tagged_site_dict]
		)
