# Deploying the RCA stack to EC2

One host running `docker compose`. Secrets live in **SSM Parameter Store**, never in this repo,
never in the AMI, never in an environment variable you have to remember to set.

## How secrets reach the app

```
SSM Parameter Store  /clickathon/*        (SecureString, KMS-encrypted at rest)
        │
        │  read at boot, using the instance profile — no AWS keys on the box
        ▼
/opt/clickathon/.env                      (root-owned, 0600, never committed)
        │
        ▼
docker compose  →  backend, frontend, Langfuse, LibreChat
```

Bedrock narration authenticates through the same instance profile, so there are no AWS access
keys anywhere in the deployment. Rotating a secret is: update the SSM parameter, reboot. Nothing
to rebuild, nothing to edit on the host.

## Parameters

| Name | Type |
|---|---|
| `/clickathon/clickhouse/host` `/port` `/user` `/database` | String |
| `/clickathon/clickhouse/password` | **SecureString** |
| `/clickathon/langfuse/public_key` `/secret_key` `/init_user_password` | **SecureString** |
| `/clickathon/bedrock/region` `/model_id` | String |

Set one:

```bash
aws ssm put-parameter --region ap-southeast-2 \
  --name /clickathon/clickhouse/password --type SecureString --overwrite \
  --value 'the-new-password'
```

## IAM

`deploy/iam-policy.json` is deliberately narrow:

- `ssm:GetParameter*` on `/clickathon/*` **only** — not the whole parameter store
- `kms:Decrypt` gated by `kms:ViaService = ssm.ap-southeast-2.amazonaws.com`, so the role
  cannot decrypt anything except through SSM
- `bedrock:InvokeModel` / `Converse` for narration

## Creating the infrastructure

```bash
REGION=ap-southeast-2
ROLE=clickathon-ec2-role

aws iam create-role --role-name $ROLE \
  --assume-role-policy-document file://deploy/iam-trust.json
aws iam put-role-policy --role-name $ROLE --policy-name clickathon-ssm-bedrock \
  --policy-document file://deploy/iam-policy.json
aws iam create-instance-profile --instance-profile-name $ROLE
aws iam add-role-to-instance-profile --instance-profile-name $ROLE --role-name $ROLE
```

Security group needs 22, 80, 3000 (Langfuse), 3080 (LibreChat), 5173 (dashboard), 8000 (API).

**Check the subnet's network ACL before launching.** A permissive security group is not enough
if the NACL denies the port — that mistake cost us a wasted instance. Confirm the subnet allows
inbound on every port above, or put everything behind port 80 with a reverse proxy.

```bash
aws ec2 run-instances --region $REGION \
  --image-id $(aws ssm get-parameter --region $REGION \
      --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
      --query Parameter.Value --output text) \
  --instance-type t3.large \
  --subnet-id <a-public-subnet-with-a-permissive-nacl> \
  --security-group-ids <sg-id> --associate-public-ip-address \
  --iam-instance-profile Name=$ROLE \
  --block-device-mappings '[{"DeviceName":"/dev/xvda","Ebs":{"VolumeSize":50,"VolumeType":"gp3","Encrypted":true}}]' \
  --metadata-options 'HttpTokens=required,HttpEndpoint=enabled' \
  --user-data file://deploy/bootstrap.sh
```

`t3.large` is the floor. The stack is ten containers — Langfuse v3 alone runs its own ClickHouse,
Postgres, Redis and MinIO, and LibreChat brings MongoDB. `t3.medium`'s 4 GB will OOM, and
Langfuse's ClickHouse is the first casualty, which quietly takes tracing down with it.

## What the bootstrap does

1. Installs Docker and the Compose v2 plugin
2. Clones this repo
3. Reads every `/clickathon/*` parameter into `/opt/clickathon/.env`
4. Detects the instance's public IP and writes it into `LANGFUSE_HOST` and `VITE_API_URL`, so a
   trace link a judge clicks resolves to this host rather than `localhost`
5. Installs a systemd unit so the stack starts on boot and re-reads SSM every time

## Operating it

```bash
systemctl status clickathon           # is it up
journalctl -u clickathon -f           # service log
tail -f /var/log/clickathon-bootstrap.log
cd /opt/clickathon && docker compose ps
docker compose logs -f backend
systemctl restart clickathon          # re-reads SSM
```

## Ports

| Port | What |
|---|---|
| 5173 | Dashboard |
| 8000 | Backend API — `/health`, `/investigate`, `/v1/chat/completions` |
| 3000 | Langfuse |
| 3080 | LibreChat |

`GET /health` reports whether the RCA engine is live and whether Langfuse is wired, which is the
fastest way to tell a half-started stack from a working one.
