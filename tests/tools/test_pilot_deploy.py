from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from tools.pilot_deploy import (
    BACKEND_NETWORK,
    COMPOSE_WAIT_TIMEOUT_SECONDS,
    COMPOSE_FILE,
    ENV_FILE,
    POSTGRES_VOLUME,
    RUNTIME_IMAGE_SERVICES,
    DeploymentGuardError,
    assert_container_topology,
    assert_digest_match,
    assert_healthy,
    assert_pinned_compose_command,
    assert_single_migration_head,
    compose_command,
    decode_json_document,
    deployment_commands,
    validate_clean_head,
    validate_compose_topology,
    validate_release_sha,
)


def config():
    service = lambda: {"networks": {"pilot_backend": {}}}
    return {
        "name": "app",
        "services": {
            "postgres": {
                **service(),
                "volumes": [{"type": "volume", "source": "pilot_postgres_data", "target": "/var/lib/postgresql/data"}],
            },
            "api": service(), "worker": service(), "proxy": {"networks": {"pilot_frontend": {}}},
        },
        "networks": {"pilot_backend": {"name": BACKEND_NETWORK}},
        "volumes": {"pilot_postgres_data": {"name": POSTGRES_VOLUME}},
    }


def inspection(service):
    value = {
        "State": {"Running": True, "Health": {"Status": "healthy"}},
        "NetworkSettings": {"Networks": {BACKEND_NETWORK: {}}},
        "Mounts": [],
    }
    if service == "postgres":
        value["Mounts"] = [{"Type": "volume", "Name": POSTGRES_VOLUME, "Destination": "/var/lib/postgresql/data"}]
    return value


class PilotDeployGuardTests(unittest.TestCase):
    def test_build_does_not_require_profile_only_migrate_image_identity(self):
        from tools.pilot_deploy import PilotDeployment

        class BuildRunner:
            dry_run = False

            def run(self, command, *, mutate=False):
                values = tuple(command)
                if "images" in values:
                    service = values[-1]
                    return {"api": "api-image", "worker": "worker-image"}.get(service, "")
                return ""

        deployment = PilotDeployment(
            root=Path.cwd(), release_sha="a" * 40, runner=BuildRunner(),
        )
        deployment.build()
        self.assertEqual(set(deployment.built_images), set(RUNTIME_IMAGE_SERVICES))
        self.assertNotIn("migrate", deployment.built_images)

    def test_build_still_fails_closed_for_missing_runtime_image_identity(self):
        from tools.pilot_deploy import PilotDeployment

        class MissingWorkerRunner:
            dry_run = False

            def run(self, command, *, mutate=False):
                values = tuple(command)
                if "images" in values and values[-1] == "api":
                    return "api-image"
                return ""

        deployment = PilotDeployment(
            root=Path.cwd(), release_sha="a" * 40, runner=MissingWorkerRunner(),
        )
        with self.assertRaisesRegex(DeploymentGuardError, "worker"):
            deployment.build()

    def test_deployment_json_uses_fail_closed_central_decoder(self):
        self.assertEqual({"name": "app"}, decode_json_document(
            '{"name": "app"}', context="compose",
        ))
        with self.assertRaisesRegex(DeploymentGuardError, "malformed JSON"):
            decode_json_document("{invalid", context="compose")

    def test_every_mutation_is_pilot_pinned_and_never_bare_compose(self):
        for command in deployment_commands():
            assert_pinned_compose_command(command)
            self.assertIn(COMPOSE_FILE, command)
            self.assertIn(ENV_FILE, command)
            self.assertNotEqual(("docker", "compose", "up"), command[:3])
            if "--wait" in command:
                self.assertIn(("--wait-timeout", COMPOSE_WAIT_TIMEOUT_SECONDS), set(zip(command, command[1:])))

    def test_unpinned_compose_is_rejected(self):
        with self.assertRaises(DeploymentGuardError):
            assert_pinned_compose_command(("docker", "compose", "up", "-d", "api"))

    def test_wrong_sha_and_dirty_or_different_head_fail(self):
        for value in ("", "abc", "G" * 40, "a" * 39):
            with self.subTest(value=value), self.assertRaises(DeploymentGuardError):
                validate_release_sha(value)
        sha = "a" * 40
        with self.assertRaises(DeploymentGuardError):
            validate_clean_head(supplied_sha=sha, head="b" * 40, status="")
        with self.assertRaises(DeploymentGuardError):
            validate_clean_head(supplied_sha=sha, head=sha, status=" M application/x.py")

    def test_missing_pilot_compose_and_env_are_fail_closed_contracts(self):
        from tools.pilot_deploy import PilotDeployment, Runner
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as value:
            root = Path(value)
            deployment = PilotDeployment(
                root=root, release_sha="a" * 40, runner=Runner(root, dry_run=True),
            )
            with self.assertRaises(DeploymentGuardError) as captured:
                deployment.preflight()
            self.assertIn(COMPOSE_FILE, str(captured.exception))
            (root / COMPOSE_FILE).write_text("services: {}", encoding="utf-8")
            with self.assertRaises(DeploymentGuardError) as captured:
                deployment.preflight()
            self.assertIn(ENV_FILE, str(captured.exception))

    def test_valid_topology_passes(self):
        validate_compose_topology(config())

    def test_wrong_project_network_volume_and_service_topology_fail(self):
        mutations = []
        value = config(); value["name"] = "other"; mutations.append(value)
        value = config(); value["networks"]["pilot_backend"]["name"] = "app_default"; mutations.append(value)
        value = config(); value["volumes"]["pilot_postgres_data"]["name"] = "app_postgres_data"; mutations.append(value)
        value = config(); value["services"].pop("worker"); mutations.append(value)
        value = config(); value["services"]["api"]["networks"] = {"default": {}}; mutations.append(value)
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(DeploymentGuardError):
                validate_compose_topology(mutation)

    def test_running_default_network_wrong_volume_and_unhealthy_worker_fail(self):
        values = {name: inspection(name) for name in ("postgres", "api", "worker")}
        assert_container_topology(values); assert_healthy(values)
        wrong_network = copy.deepcopy(values)
        wrong_network["worker"]["NetworkSettings"]["Networks"] = {"app_default": {}}
        with self.assertRaises(DeploymentGuardError): assert_container_topology(wrong_network)
        wrong_volume = copy.deepcopy(values)
        wrong_volume["postgres"]["Mounts"][0]["Name"] = "app_postgres_data"
        with self.assertRaises(DeploymentGuardError): assert_container_topology(wrong_volume)
        unhealthy = copy.deepcopy(values)
        unhealthy["worker"]["State"]["Health"]["Status"] = "unhealthy"
        with self.assertRaises(DeploymentGuardError): assert_healthy(unhealthy)

    def test_migration_head_mismatch_and_multiple_heads_fail(self):
        self.assertEqual("025", assert_single_migration_head(
            heads_output="025 (head)", current_output="025 (head)",
        ))
        for heads, current in (("024 (head)\n025 (head)", "025"), ("025 (head)", "024")):
            with self.assertRaises(DeploymentGuardError):
                assert_single_migration_head(heads_output=heads, current_output=current)

    def test_source_digest_mismatch_is_detectable(self):
        import hashlib
        first = hashlib.sha256(b"release-a").hexdigest()
        second = hashlib.sha256(b"release-b").hexdigest()
        assert_digest_match(component="worker:file", checkout_digest=first, runtime_digest=first)
        with self.assertRaises(DeploymentGuardError):
            assert_digest_match(component="worker:file", checkout_digest=first, runtime_digest=second)


if __name__ == "__main__":
    unittest.main()
