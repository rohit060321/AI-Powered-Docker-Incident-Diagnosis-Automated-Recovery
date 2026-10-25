# Official NudgeBee self-host setup

The official source is cloned into ignored `mvp/vendor/nudgebee` at revision `106871a` (the checkout can be updated deliberately later). The deployment helper uses its Helm chart under `deploy/kubernetes/nudgebee`; it never deploys to an implicit current context. Configure `NUDGEBEE_KUBE_CONTEXT` and `NUDGEBEE_ADMIN_EMAIL` in `mvp/.env.local`, then run from the project root:

```sh
python3 -m mvp.nudgebee.deploy
```

The helper refuses clusters below 2 schedulable nodes or 12 GiB allocatable RAM. NudgeBee's documented bundled stack also asks for 200 GB SSD; verify that the cluster's StorageClass and backing disk can supply it before running. This Mac's Docker VM has 8 GB RAM and the host had ~20 GB free when checked, so the local `kind-agent-mvp` context is intentionally rejected for the full server. [Official server installation](https://docs.nudgebee.com/docs/installation/server/), [official GitHub source](https://github.com/nudgebee/nudgebee).

After the Helm install, verify `kubectl --context "$NUDGEBEE_KUBE_CONTEXT" get pods -n nudgebee` and port-forward `svc/app` to `localhost:3000`. Retrieve the bootstrap admin password from the `nudgebee` Kubernetes Secret through a secure terminal; do not paste it into chat or a committed file. Set up the JarvisLabs-compatible model in NudgeBee's AI/LLM settings, then configure the assessment workflow described in [the adapter run card](../adapters/NUDGEBEE_WORKFLOW.md). If NudgeBee runs on a separate cluster from `kind-agent-mvp`, install its agent on the KinD cluster only after the self-hosted server is reachable from that cluster.

The Community edition is source-available under BSL 1.1 for internal self-hosting. It is distinct from an unrestricted open-source license; check the [repository license](https://github.com/nudgebee/nudgebee/blob/main/LICENSING.md) for redistribution/managed-service use.

